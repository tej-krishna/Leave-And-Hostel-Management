# hostel_app/workflow.py
#
# Single authoritative implementation of the multi-stage leave approval
# workflow: duration -> required approval chain -> stage transitions ->
# authorization. Views must go through approve_leave()/reject_leave() rather
# than mutating LeaveApplication.current_stage directly, so there is exactly
# one place that decides what "next stage" and "who is allowed to act" mean.

from django.db import transaction
from django.utils import timezone

from .models import LeaveApplication, LeaveApprovalHistory


# --- Duration -> required approval chain -----------------------------------
#
# Thresholds implemented (documented because the source requirement did not
# pin exact boundaries for the 10/15/30-day tiers):
#   1-3 days   -> Warden -> Caretaker                         (final: Caretaker)
#   4-9 days   -> + Chief Warden                              (final: Chief Warden)
#   10-29 days -> + DSW -> Dean                                (final: Dean)
#   30+ days   -> + AO Office -> Director                      (final: Director)
# "duration" is LeaveApplication.get_duration_days() - see that method for
# the exact inclusive/ceiling definition used everywhere (routing, UI, PDF,
# email, tests) so no two places can disagree.

def get_required_chain(duration_days):
    if duration_days <= 3:
        return [LeaveApplication.STAGE_WARDEN, LeaveApplication.STAGE_CARETAKER]
    if duration_days <= 9:
        return [
            LeaveApplication.STAGE_WARDEN,
            LeaveApplication.STAGE_CARETAKER,
            LeaveApplication.STAGE_CHIEF_WARDEN,
        ]
    if duration_days <= 29:
        return [
            LeaveApplication.STAGE_WARDEN,
            LeaveApplication.STAGE_CARETAKER,
            LeaveApplication.STAGE_CHIEF_WARDEN,
            LeaveApplication.STAGE_DSW,
            LeaveApplication.STAGE_DEAN,
        ]
    return [
        LeaveApplication.STAGE_WARDEN,
        LeaveApplication.STAGE_CARETAKER,
        LeaveApplication.STAGE_CHIEF_WARDEN,
        LeaveApplication.STAGE_DSW,
        LeaveApplication.STAGE_DEAN,
        LeaveApplication.STAGE_AO,
        LeaveApplication.STAGE_DIRECTOR,
    ]


# Maps a logged-in staff role (Student.role) to the single approval-chain
# stage it is allowed to act on. 'caretaker' deliberately appears only once
# here (the CARETAKER approval stage) - the separate post-approval ID
# verification step is authorized independently in verify_departure(),
# because it is a different action (confirming identity, not approving a
# request) even though the same human role performs both.
ROLE_TO_STAGE = {
    'warden': LeaveApplication.STAGE_WARDEN,
    'caretaker': LeaveApplication.STAGE_CARETAKER,
    'chief_warden': LeaveApplication.STAGE_CHIEF_WARDEN,
    'dsw': LeaveApplication.STAGE_DSW,
    'dean': LeaveApplication.STAGE_DEAN,
    'ao': LeaveApplication.STAGE_AO,
    'director': LeaveApplication.STAGE_DIRECTOR,
}

TERMINAL_STAGES = {
    LeaveApplication.STAGE_CARETAKER_VERIFICATION,
    LeaveApplication.STAGE_CLEARED_FOR_DEPARTURE,
    LeaveApplication.STAGE_OUT,
    LeaveApplication.STAGE_COMPLETED,
    LeaveApplication.STAGE_REJECTED,
}


class WorkflowError(Exception):
    """Raised when a requested transition is not currently valid."""


def get_next_stage(leave):
    """Given the leave's current_stage, what stage comes after an approval."""
    chain = get_required_chain(leave.get_duration_days())
    try:
        idx = chain.index(leave.current_stage)
    except ValueError:
        raise WorkflowError(
            f"Leave #{leave.pk} is at stage '{leave.current_stage}', which is not part of "
            f"its required chain {chain} for a {leave.get_duration_days()}-day request."
        )
    if idx + 1 < len(chain):
        return chain[idx + 1]
    return LeaveApplication.STAGE_CARETAKER_VERIFICATION


def can_act(approver, leave):
    """Server-side authorization check: may this staff member approve/reject
    this specific leave right now? Never trust a hidden/disabled button."""
    role = getattr(approver, 'role', None)
    required_stage = ROLE_TO_STAGE.get(role)
    if required_stage is None:
        return False
    if leave.status != 'pending':
        return False
    return leave.current_stage == required_stage


@transaction.atomic
def approve_leave(leave_id, approver, comment=''):
    """
    Approve the leave at its current stage, on behalf of `approver` (a
    Student whose role matches the current stage). Locks the row for the
    duration of the check-then-act sequence so two simultaneous approvals
    (or an approval racing a rejection) can't both apply.

    Returns the refreshed LeaveApplication. Raises WorkflowError if the
    approver's role does not match the leave's current stage, or the leave
    is not currently pending - this is the actual authorization boundary,
    not whatever the UI happened to show.
    """
    leave = LeaveApplication.objects.select_for_update().get(pk=leave_id)

    if not can_act(approver, leave):
        raise WorkflowError(
            f"{approver.name} (role={approver.role}) is not authorized to act on "
            f"leave #{leave.pk} at stage {leave.current_stage}."
        )

    previous_stage = leave.current_stage
    next_stage = get_next_stage(leave)
    is_final = next_stage == LeaveApplication.STAGE_CARETAKER_VERIFICATION

    leave.current_stage = next_stage
    if is_final:
        leave.status = 'approved'
        leave.final_approved_at = timezone.now()
    leave.save()

    LeaveApprovalHistory.objects.create(
        leave=leave,
        stage=previous_stage,
        actor=approver,
        action=LeaveApprovalHistory.ACTION_APPROVED,
        comment=comment,
        previous_status=previous_stage,
        new_status=next_stage,
    )

    return leave, (next_stage == LeaveApplication.STAGE_AO)


@transaction.atomic
def reject_leave(leave_id, approver, comment=''):
    """Reject the leave at its current stage. Stops the chain immediately -
    no later authority (higher or lower) can act on a rejected request."""
    leave = LeaveApplication.objects.select_for_update().get(pk=leave_id)

    if not can_act(approver, leave):
        raise WorkflowError(
            f"{approver.name} (role={approver.role}) is not authorized to act on "
            f"leave #{leave.pk} at stage {leave.current_stage}."
        )

    previous_stage = leave.current_stage
    leave.status = 'rejected'
    leave.current_stage = LeaveApplication.STAGE_REJECTED
    leave.save()

    LeaveApprovalHistory.objects.create(
        leave=leave,
        stage=previous_stage,
        actor=approver,
        action=LeaveApprovalHistory.ACTION_REJECTED,
        comment=comment,
        previous_status=previous_stage,
        new_status=LeaveApplication.STAGE_REJECTED,
    )
    return leave


@transaction.atomic
def verify_departure(leave_id, caretaker, submitted_student_id):
    """
    Caretaker's final ID check before a student may depart. Requires the
    leave to have completed its full approval chain (status == 'approved',
    stage == CARETAKER_VERIFICATION) and the caretaker to have typed the
    student's actual ID - an arbitrary/mistyped ID must not clear anyone
    for departure.
    """
    leave = LeaveApplication.objects.select_for_update().get(pk=leave_id)

    if getattr(caretaker, 'role', None) != 'caretaker':
        raise WorkflowError(f"{caretaker.name} is not a caretaker.")

    if leave.status != 'approved' or leave.current_stage != LeaveApplication.STAGE_CARETAKER_VERIFICATION:
        raise WorkflowError(
            f"Leave #{leave.pk} is not awaiting caretaker verification (stage={leave.current_stage})."
        )

    id_matches = submitted_student_id.strip().lower() == leave.student.student_id.strip().lower()

    if not id_matches:
        LeaveApprovalHistory.objects.create(
            leave=leave,
            stage=leave.current_stage,
            actor=caretaker,
            action=LeaveApprovalHistory.ACTION_VERIFICATION_FAILED,
            comment=f"Entered ID '{submitted_student_id}' does not match.",
            previous_status=leave.current_stage,
            new_status=leave.current_stage,
        )
        return leave, False

    leave.current_stage = LeaveApplication.STAGE_CLEARED_FOR_DEPARTURE
    leave.caretaker_verified_at = timezone.now()
    leave.caretaker_verified_by = caretaker
    leave.save()

    LeaveApprovalHistory.objects.create(
        leave=leave,
        stage=LeaveApplication.STAGE_CARETAKER_VERIFICATION,
        actor=caretaker,
        action=LeaveApprovalHistory.ACTION_VERIFIED,
        comment='Student ID verified for departure.',
        previous_status=LeaveApplication.STAGE_CARETAKER_VERIFICATION,
        new_status=LeaveApplication.STAGE_CLEARED_FOR_DEPARTURE,
    )
    return leave, True


# --- UI timeline (backend-authoritative; templates only render this) -------
#
# The brief for the leave-workflow UI explicitly requires that the approval
# route/timeline shown to users reflects the real backend workflow and is
# never computed in JavaScript. This is the one function every "approval
# route" / "approval timeline" widget in the templates calls into.

_STAGE_LABELS = dict(LeaveApplication.STAGE_CHOICES)


def build_approval_timeline(leave):
    """
    Returns an ordered list of steps describing this leave's full journey:
    the approval chain required for its duration, then the post-approval
    departure/return stages. Each step is a dict:
        {stage, label, state, actor, timestamp, comment}
    where state is one of 'done' | 'current' | 'rejected' | 'locked'.
    """
    chain = get_required_chain(leave.get_duration_days())
    history_by_stage = {}
    for h in leave.approval_history.all():
        # Keep the most recent action recorded at each stage (a stage can
        # have more than one row, e.g. a failed verification attempt then a
        # successful one - the latest one reflects the current truth).
        history_by_stage.setdefault(h.stage, []).append(h)

    steps = []
    rejected = leave.status == 'rejected'
    rejected_at_stage = None
    if rejected:
        rejection_rows = [h for rows in history_by_stage.values() for h in rows
                           if h.action == LeaveApprovalHistory.ACTION_REJECTED]
        if rejection_rows:
            rejected_at_stage = rejection_rows[-1].stage

    reached_current = False
    for stage in chain:
        rows = history_by_stage.get(stage, [])
        approved_row = next((h for h in rows if h.action == LeaveApprovalHistory.ACTION_APPROVED), None)
        if approved_row:
            state = 'done'
        elif stage == rejected_at_stage:
            state = 'rejected'
            reached_current = True
        elif not reached_current and leave.current_stage == stage:
            state = 'current'
            reached_current = True
        elif not reached_current and not rejected:
            state = 'current'
            reached_current = True
        else:
            state = 'locked'
        steps.append({
            'stage': stage,
            'label': _STAGE_LABELS.get(stage, stage.replace('_', ' ').title()),
            'state': state,
            'actor': approved_row.actor if approved_row else None,
            'timestamp': approved_row.timestamp if approved_row else None,
            'comment': approved_row.comment if approved_row else None,
        })

    if rejected:
        return steps

    # Post-approval stages, shown only once the chain has actually finished.
    post_stages = [
        (LeaveApplication.STAGE_CARETAKER_VERIFICATION, LeaveApprovalHistory.ACTION_VERIFIED, leave.caretaker_verified_at, leave.caretaker_verified_by),
        (LeaveApplication.STAGE_OUT, LeaveApprovalHistory.ACTION_GATE_OUT, leave.gate_out_at, None),
        (LeaveApplication.STAGE_COMPLETED, LeaveApprovalHistory.ACTION_HOSTEL_IN, leave.hostel_in_at, None),
    ]
    chain_done = all(s['state'] == 'done' for s in steps)
    reached_current = False
    for stage, action, when, actor in post_stages:
        if when:
            state = 'done'
        elif chain_done and not reached_current:
            state = 'current'
            reached_current = True
        else:
            state = 'locked'
        steps.append({
            'stage': stage,
            'label': _STAGE_LABELS.get(stage, stage.replace('_', ' ').title()),
            'state': state,
            'actor': actor,
            'timestamp': when,
            'comment': None,
        })

    return steps
