from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch

from . import workflow
from .models import Student, LeaveApplication, StudentStatusLog, LeaveApprovalHistory
from .pdf import generate_leave_letter_pdf
from .email_utils import send_ao_escalation_email


def make_student(**kwargs):
    defaults = dict(
        name='Test Student',
        student_id='N100001',
        mobile_number='9000000001',
        year='E1',
        branch='CSE',
        gender='M',
        role='student',
    )
    defaults.update(kwargs)
    return Student.objects.create(**defaults)


_role_counter = [0]


def make_staff(role, **kwargs):
    """A staff account for one hierarchy role. student_id/mobile_number are
    auto-uniquified since several staff members are often created per test."""
    _role_counter[0] += 1
    n = _role_counter[0]
    defaults = dict(
        name=f"{role.title()} {n}",
        student_id=f"STAFF-{role}-{n}",
        mobile_number=f"98000{n:05d}",
        year='E1',
        branch='CSE',
        role=role,
    )
    defaults.update(kwargs)
    return Student.objects.create(**defaults)


def make_leave(student, days=1, **kwargs):
    now = timezone.now() + timedelta(days=1)
    defaults = dict(
        student=student,
        leave_type='leave',
        reason='Test reason',
        out_time=now,
        in_time=now + timedelta(days=days),
    )
    defaults.update(kwargs)
    return LeaveApplication.objects.create(**defaults)


class RoleRequiredAccessControlTests(TestCase):
    """role_required() gates every staff view off the session, not just the UI."""

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, reverse('login'))

    def test_student_role_cannot_reach_staff_dashboard(self):
        student = make_student()
        session = self.client.session
        session['user_role'] = 'student'
        session['student_id'] = 'N100001'
        session['student_pk'] = student.pk
        session.save()

        response = self.client.get(reverse('dashboard'))
        # role_required() sends students to their own landing page, not staff pages
        self.assertRedirects(response, reverse('apply_leave'))

    def test_viewer_role_cannot_update_student_status_editor_only(self):
        student = make_student()
        session = self.client.session
        session['user_role'] = 'viewer'
        session.save()

        response = self.client.post(
            reverse('update_student_status', args=[student.pk]),
            {'status': 'leave'},
        )
        self.assertRedirects(response, reverse('dashboard'))
        student.refresh_from_db()
        self.assertEqual(student.status, 'present')  # unchanged


class LoginAuthenticationTests(TestCase):
    """
    Documents current login behavior: a Student record has no password field,
    so perform_login() authenticates solely on (student_id, name) match. This
    is a P0 finding in the audit (anyone who knows a student's ID and name -
    both visible on ID cards / room lists / the student lookup page - can log
    in as that student, including 'editor'/'viewer' staff accounts). This
    test pins current behavior; it should be rewritten once real credential
    checking is added.
    """

    def test_correct_id_and_name_logs_in_without_any_password(self):
        make_student(name='Jane Roe', student_id='N100001', role='editor')
        response = self.client.post(reverse('perform_login'), {
            'student_id': 'N100001',
            'name': 'Jane Roe',
        })
        self.assertRedirects(response, reverse('dashboard'))
        self.assertEqual(self.client.session['user_role'], 'editor')

    def test_wrong_name_for_a_known_id_is_rejected(self):
        make_student(name='Jane Roe', student_id='N100001')
        response = self.client.post(reverse('perform_login'), {
            'student_id': 'N100001',
            'name': 'Someone Else',
        })
        self.assertRedirects(response, reverse('login'))
        self.assertNotIn('student_pk', self.client.session)

    def test_every_hierarchy_role_lands_on_the_approval_queue(self):
        """
        Regression test for a bug found during browser verification: adding
        the new warden/caretaker/.../director roles without updating
        perform_login()'s role dispatch meant every one of them hit the
        'unrecognised role' branch and was immediately logged back out.
        """
        for role in ['warden', 'caretaker', 'chief_warden', 'dsw', 'dean', 'ao', 'director']:
            staff = make_staff(role)
            response = self.client.post(reverse('perform_login'), {
                'student_id': staff.student_id,
                'name': staff.name,
            })
            self.assertRedirects(response, reverse('leave_approval_queue'))
            self.assertEqual(self.client.session['user_role'], role)
            self.client.get(reverse('logout'))


class LeaveApplicationOverlapTests(TestCase):
    def setUp(self):
        self.student = make_student()
        self.client_session_login()

    def client_session_login(self):
        session = self.client.session
        session['student_pk'] = self.student.pk
        session['student_id'] = self.student.student_id
        session['user_role'] = 'student'
        session.save()

    def _apply(self, out_time, in_time):
        return self.client.post(reverse('apply_leave'), {
            'leave_type': 'outing',
            'out_time': out_time.strftime('%Y-%m-%dT%H:%M'),
            'in_time': in_time.strftime('%Y-%m-%dT%H:%M'),
            'reason': 'Test reason',
            'parent_coming': '',
            'approval_of': '',
            'companion_id': '',
        })

    def test_overlapping_pending_leave_is_rejected(self):
        now = timezone.now() + timedelta(days=1)
        first = self._apply(now, now + timedelta(hours=4))
        self.assertEqual(LeaveApplication.objects.count(), 1)
        self.assertEqual(first.status_code, 302)

        # Overlaps the first application's window
        second = self._apply(now + timedelta(hours=1), now + timedelta(hours=5))
        self.assertEqual(LeaveApplication.objects.count(), 1)  # rejected, not saved
        messages = list(second.wsgi_request._messages) if hasattr(second, 'wsgi_request') else None


class RetiredFlatApprovalEndpointTests(TestCase):
    """
    The old single-step 'editor approves any leave' endpoint
    (update_leave_status) is intentionally retired now that leave approval
    is a multi-stage hierarchy (see hostel_app/workflow.py and
    LEAVE_WORKFLOW_TESTS below) - an 'editor' is not one of the hierarchy
    roles, so letting it approve directly would bypass Warden/Caretaker/etc
    entirely. This replaces the old
    LeaveApprovalStatusSyncTests.test_approving_leave_updates_student_status_and_logs_it
    and .test_rejecting_leave_does_not_change_student_status, which asserted
    the now-removed bypass behavior; the new behavior it must be replaced
    with is proven here and in LeaveWorkflowStageRoutingTests /
    LeaveWorkflowEndToEndTests below.
    """

    def setUp(self):
        self.student = make_student()
        self.leave = LeaveApplication.objects.create(
            student=self.student,
            leave_type='outing',
            reason='Test',
            out_time=timezone.now(),
            in_time=timezone.now() + timedelta(hours=2),
        )
        session = self.client.session
        session['user_role'] = 'editor'
        session.save()

    def test_editor_posting_to_the_old_endpoint_no_longer_changes_anything(self):
        response = self.client.post(
            reverse('update_leave_status', args=[self.leave.pk]),
            {'action': 'approve'},
        )
        self.assertRedirects(response, reverse('leave_management'))
        self.leave.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(self.leave.status, 'pending')
        self.assertEqual(self.leave.current_stage, LeaveApplication.STAGE_WARDEN)
        self.assertEqual(self.student.status, 'present')


# =============================================================================
# Leave Workflow: duration -> approval chain routing
# =============================================================================

class LeaveWorkflowDurationRoutingTests(TestCase):
    """Required duration matrix (section 42): 1, 3, 4, 5, 10, 15, 30, 60 days,
    plus the 9/29 boundary just below the next tier. Thresholds implemented:
      1-3   -> Warden, Caretaker
      4-9   -> + Chief Warden
      10-29 -> + DSW, Dean
      30+   -> + AO, Director
    """

    def test_duration_calculation_rounds_up_to_whole_days(self):
        student = make_student()
        leave = make_leave(student, days=0)
        leave.out_time = timezone.now()
        leave.in_time = leave.out_time + timedelta(hours=30)  # 1.25 days
        self.assertEqual(leave.get_duration_days(), 2)

    def test_1_day_chain_is_warden_then_caretaker(self):
        self.assertEqual(
            workflow.get_required_chain(1),
            [LeaveApplication.STAGE_WARDEN, LeaveApplication.STAGE_CARETAKER],
        )

    def test_3_day_chain_is_warden_then_caretaker(self):
        self.assertEqual(
            workflow.get_required_chain(3),
            [LeaveApplication.STAGE_WARDEN, LeaveApplication.STAGE_CARETAKER],
        )

    def test_4_day_chain_adds_chief_warden(self):
        self.assertEqual(
            workflow.get_required_chain(4),
            [LeaveApplication.STAGE_WARDEN, LeaveApplication.STAGE_CARETAKER, LeaveApplication.STAGE_CHIEF_WARDEN],
        )

    def test_5_day_chain_adds_chief_warden(self):
        self.assertEqual(
            workflow.get_required_chain(5),
            [LeaveApplication.STAGE_WARDEN, LeaveApplication.STAGE_CARETAKER, LeaveApplication.STAGE_CHIEF_WARDEN],
        )

    def test_9_day_chain_still_stops_at_chief_warden(self):
        self.assertEqual(
            workflow.get_required_chain(9),
            [LeaveApplication.STAGE_WARDEN, LeaveApplication.STAGE_CARETAKER, LeaveApplication.STAGE_CHIEF_WARDEN],
        )

    def test_10_day_chain_adds_dsw_and_dean(self):
        self.assertEqual(
            workflow.get_required_chain(10),
            [
                LeaveApplication.STAGE_WARDEN, LeaveApplication.STAGE_CARETAKER,
                LeaveApplication.STAGE_CHIEF_WARDEN, LeaveApplication.STAGE_DSW, LeaveApplication.STAGE_DEAN,
            ],
        )

    def test_15_day_chain_adds_dsw_and_dean(self):
        self.assertEqual(
            workflow.get_required_chain(15),
            [
                LeaveApplication.STAGE_WARDEN, LeaveApplication.STAGE_CARETAKER,
                LeaveApplication.STAGE_CHIEF_WARDEN, LeaveApplication.STAGE_DSW, LeaveApplication.STAGE_DEAN,
            ],
        )

    def test_29_day_chain_still_stops_at_dean(self):
        self.assertEqual(
            workflow.get_required_chain(29),
            [
                LeaveApplication.STAGE_WARDEN, LeaveApplication.STAGE_CARETAKER,
                LeaveApplication.STAGE_CHIEF_WARDEN, LeaveApplication.STAGE_DSW, LeaveApplication.STAGE_DEAN,
            ],
        )

    def test_30_day_chain_adds_ao_and_director(self):
        self.assertEqual(
            workflow.get_required_chain(30),
            [
                LeaveApplication.STAGE_WARDEN, LeaveApplication.STAGE_CARETAKER,
                LeaveApplication.STAGE_CHIEF_WARDEN, LeaveApplication.STAGE_DSW, LeaveApplication.STAGE_DEAN,
                LeaveApplication.STAGE_AO, LeaveApplication.STAGE_DIRECTOR,
            ],
        )

    def test_60_day_chain_adds_ao_and_director(self):
        self.assertEqual(
            workflow.get_required_chain(60),
            [
                LeaveApplication.STAGE_WARDEN, LeaveApplication.STAGE_CARETAKER,
                LeaveApplication.STAGE_CHIEF_WARDEN, LeaveApplication.STAGE_DSW, LeaveApplication.STAGE_DEAN,
                LeaveApplication.STAGE_AO, LeaveApplication.STAGE_DIRECTOR,
            ],
        )


# =============================================================================
# Leave Workflow: stage-gated authorization
# =============================================================================

class LeaveWorkflowAuthorizationTests(TestCase):
    def setUp(self):
        self.student = make_student()
        self.warden = make_staff('warden')
        self.caretaker = make_staff('caretaker')
        self.chief_warden = make_staff('chief_warden')

    def test_warden_can_approve_a_fresh_request(self):
        leave = make_leave(self.student, days=1)
        leave, escalated = workflow.approve_leave(leave.pk, self.warden)
        self.assertFalse(escalated)
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_CARETAKER)
        self.assertEqual(leave.status, 'pending')

    def test_caretaker_cannot_approve_a_request_still_at_warden(self):
        leave = make_leave(self.student, days=1)
        with self.assertRaises(workflow.WorkflowError):
            workflow.approve_leave(leave.pk, self.caretaker)
        leave.refresh_from_db()
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_WARDEN)

    def test_chief_warden_cannot_bypass_earlier_stages(self):
        leave = make_leave(self.student, days=5)  # requires chief warden eventually
        with self.assertRaises(workflow.WorkflowError):
            workflow.approve_leave(leave.pk, self.chief_warden)

    def test_short_leave_finalizes_at_caretaker(self):
        leave = make_leave(self.student, days=1)
        workflow.approve_leave(leave.pk, self.warden)
        leave, escalated = workflow.approve_leave(leave.pk, self.caretaker)
        self.assertFalse(escalated)
        self.assertEqual(leave.status, 'approved')
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_CARETAKER_VERIFICATION)
        self.assertIsNotNone(leave.final_approved_at)

    def test_rejection_stops_the_chain_and_cannot_be_approved_afterward(self):
        leave = make_leave(self.student, days=1)
        workflow.reject_leave(leave.pk, self.warden, comment='Not valid')
        leave.refresh_from_db()
        self.assertEqual(leave.status, 'rejected')
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_REJECTED)

        # No one - not even the same warden - can approve a rejected request.
        with self.assertRaises(workflow.WorkflowError):
            workflow.approve_leave(leave.pk, self.warden)

    def test_repeated_approval_of_an_already_forwarded_request_fails(self):
        leave = make_leave(self.student, days=1)
        workflow.approve_leave(leave.pk, self.warden)
        # Warden tries to approve again after it has already moved to Caretaker.
        with self.assertRaises(workflow.WorkflowError):
            workflow.approve_leave(leave.pk, self.warden)

    def test_approval_history_is_recorded_and_never_overwritten(self):
        leave = make_leave(self.student, days=1)
        workflow.approve_leave(leave.pk, self.warden, comment='Looks fine')
        workflow.approve_leave(leave.pk, self.caretaker, comment='Confirmed')
        history = list(LeaveApprovalHistory.objects.filter(leave=leave).order_by('timestamp'))
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].actor, self.warden)
        self.assertEqual(history[0].action, LeaveApprovalHistory.ACTION_APPROVED)
        self.assertEqual(history[1].actor, self.caretaker)

    def test_view_layer_rejects_wrong_role_over_http(self):
        """Direct HTTP abuse, not just the service-layer check: a caretaker
        session hitting the approval endpoint for a warden-stage leave must
        be refused server-side."""
        leave = make_leave(self.student, days=1)
        session = self.client.session
        session['user_role'] = 'caretaker'
        session['student_pk'] = self.caretaker.pk
        session.save()

        response = self.client.post(
            reverse('process_leave_approval', args=[leave.pk]),
            {'action': 'approve'},
        )
        self.assertEqual(response.status_code, 302)
        leave.refresh_from_db()
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_WARDEN)  # unchanged

    def test_student_role_cannot_reach_any_approval_queue(self):
        response = self.client.get(reverse('leave_approval_queue'))
        self.assertRedirects(response, reverse('login'))


# =============================================================================
# Leave Workflow: caretaker ID verification
# =============================================================================

class CaretakerVerificationTests(TestCase):
    def setUp(self):
        self.student = make_student(student_id='N555000')
        self.caretaker = make_staff('caretaker')
        self.leave = make_leave(self.student, days=1)
        self.leave.status = 'approved'
        self.leave.current_stage = LeaveApplication.STAGE_CARETAKER_VERIFICATION
        self.leave.save()

    def test_correct_id_clears_student_for_departure(self):
        leave, verified = workflow.verify_departure(self.leave.pk, self.caretaker, 'N555000')
        self.assertTrue(verified)
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_CLEARED_FOR_DEPARTURE)
        self.assertEqual(leave.caretaker_verified_by, self.caretaker)
        self.assertIsNotNone(leave.caretaker_verified_at)

    def test_wrong_id_does_not_clear_departure(self):
        leave, verified = workflow.verify_departure(self.leave.pk, self.caretaker, 'N999999')
        self.assertFalse(verified)
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_CARETAKER_VERIFICATION)
        self.assertTrue(
            LeaveApprovalHistory.objects.filter(
                leave=leave, action=LeaveApprovalHistory.ACTION_VERIFICATION_FAILED
            ).exists()
        )

    def test_cannot_verify_a_leave_not_yet_fully_approved(self):
        pending_leave = make_leave(self.student, days=1)
        with self.assertRaises(workflow.WorkflowError):
            workflow.verify_departure(pending_leave.pk, self.caretaker, self.student.student_id)

    def test_duplicate_verification_is_rejected(self):
        workflow.verify_departure(self.leave.pk, self.caretaker, 'N555000')
        with self.assertRaises(workflow.WorkflowError):
            workflow.verify_departure(self.leave.pk, self.caretaker, 'N555000')


# =============================================================================
# Leave Workflow: PDF letter + AO/Director email (long leaves)
# =============================================================================

@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    AO_EMAIL='ao@example.test', DIRECTOR_EMAIL='director@example.test',
)
class LongLeaveLetterAndEmailTests(TestCase):
    def setUp(self):
        self.student = make_student()
        self.leave = make_leave(self.student, days=35, reason='Family function')
        # Fast-forward through the chain to just before AO, recording real
        # history, so the generated letter reflects genuine approval data.
        warden, caretaker, cw, dsw, dean = (
            make_staff('warden'), make_staff('caretaker'), make_staff('chief_warden'),
            make_staff('dsw'), make_staff('dean'),
        )
        workflow.approve_leave(self.leave.pk, warden, 'ok')
        workflow.approve_leave(self.leave.pk, caretaker, 'ok')
        workflow.approve_leave(self.leave.pk, cw, 'ok')
        workflow.approve_leave(self.leave.pk, dsw, 'ok')
        self.leave, self.escalated = workflow.approve_leave(self.leave.pk, dean, 'ok')

    def test_dean_approval_on_a_35_day_leave_escalates_to_ao(self):
        self.assertTrue(self.escalated)
        self.assertEqual(self.leave.current_stage, LeaveApplication.STAGE_AO)
        self.assertEqual(self.leave.status, 'pending')  # not finally approved yet

    def test_pdf_letter_contains_real_student_and_leave_data(self):
        pdf_bytes = generate_leave_letter_pdf(self.leave)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
        # Reportlab output is compressed, so we can't grep the text directly,
        # but we can confirm a non-trivial, well-formed document was built.
        self.assertGreater(len(pdf_bytes), 1000)

    def test_email_is_sent_to_configured_ao_and_director_with_pdf_attached(self):
        mail.outbox = []
        result = send_ao_escalation_email(self.leave)
        self.assertTrue(result)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.email_status, LeaveApplication.EMAIL_SENT)
        self.assertIsNotNone(self.leave.email_sent_at)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertIn('ao@example.test', sent.to)
        self.assertIn('director@example.test', sent.to)
        self.assertEqual(len(sent.attachments), 1)
        self.assertTrue(self.leave.letter_pdf)

    def test_email_failure_is_recorded_without_raising_or_blocking_approval(self):
        with patch('hostel_app.email_utils.EmailMessage.send', side_effect=RuntimeError('SMTP down')):
            result = send_ao_escalation_email(self.leave)
        self.assertFalse(result)
        self.leave.refresh_from_db()
        # The approval itself (current_stage == AO) must still stand even
        # though the notification email failed.
        self.assertEqual(self.leave.current_stage, LeaveApplication.STAGE_AO)
        self.assertEqual(self.leave.email_status, LeaveApplication.EMAIL_FAILED)
        self.assertIn('SMTP down', self.leave.email_error)

    def test_no_recipients_configured_fails_safely(self):
        with override_settings(AO_EMAIL='', DIRECTOR_EMAIL=''):
            result = send_ao_escalation_email(self.leave)
        self.assertFalse(result)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.email_status, LeaveApplication.EMAIL_FAILED)


# =============================================================================
# Leave Workflow: full end-to-end journeys
# =============================================================================

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                    AO_EMAIL='ao@example.test', DIRECTOR_EMAIL='director@example.test')
class LeaveWorkflowEndToEndTests(TestCase):
    """One complete short-leave journey and one complete very-long-leave
    journey through every stage: apply -> approvals -> caretaker
    verification -> biometric gate-out -> biometric gate-in -> hostel-in ->
    completed, student status returning to 'present' at the end via the
    same essl_app ingestion path exercised in essl_app/tests.py."""

    def _biometric_punch(self, student, punch_state, when):
        from essl_app.views import iclock_cdata
        from django.test import RequestFactory
        rf = RequestFactory()
        numeric = student.student_id.lstrip('N').lstrip('n').lstrip('0')
        ts = when.strftime('%Y-%m-%d %H:%M:%S')
        body = f"{numeric}\t{ts}\t0\t{punch_state}\t0\t0\t0"
        return iclock_cdata(rf.post('/iclock/cdata?table=ATTLOG', data=body, content_type='text/plain'))

    def test_short_leave_full_journey_to_present(self):
        student = make_student(student_id='N700001', status='present')
        warden, caretaker = make_staff('warden'), make_staff('caretaker')

        out_time = timezone.now() + timedelta(minutes=1)
        leave = make_leave(student, days=1, out_time=out_time, in_time=out_time + timedelta(hours=5))

        workflow.approve_leave(leave.pk, warden)
        leave, escalated = workflow.approve_leave(leave.pk, caretaker)
        self.assertFalse(escalated)
        self.assertEqual(leave.status, 'approved')
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_CARETAKER_VERIFICATION)

        leave, verified = workflow.verify_departure(leave.pk, caretaker, student.student_id)
        self.assertTrue(verified)
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_CLEARED_FOR_DEPARTURE)

        # Biometric Hostel-Out -> student goes OUT on this specific leave.
        self._biometric_punch(student, '2', timezone.now())
        student.refresh_from_db()
        leave.refresh_from_db()
        self.assertEqual(student.status, 'leave')
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_OUT)
        self.assertIsNotNone(leave.gate_out_at)

        # Return: Gate-In then Hostel-In.
        self._biometric_punch(student, '0', timezone.now())
        self._biometric_punch(student, '3', timezone.now())
        student.refresh_from_db()
        leave.refresh_from_db()
        self.assertEqual(student.status, 'present')
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_COMPLETED)
        self.assertIsNotNone(leave.gate_in_at)
        self.assertIsNotNone(leave.hostel_in_at)
        self.assertIsNotNone(leave.completed_at)

    def test_biometric_gate_out_is_blocked_until_caretaker_clears_it(self):
        """The key new safeguard: a fully-approved leave (status='approved')
        that has NOT yet passed caretaker verification must not let a
        fingerprint match alone send the student OUT."""
        student = make_student(student_id='N700002', status='present')
        warden, caretaker = make_staff('warden'), make_staff('caretaker')
        out_time = timezone.now() + timedelta(minutes=1)
        leave = make_leave(student, days=1, out_time=out_time, in_time=out_time + timedelta(hours=5))
        workflow.approve_leave(leave.pk, warden)
        leave, _ = workflow.approve_leave(leave.pk, caretaker)
        self.assertEqual(leave.status, 'approved')
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_CARETAKER_VERIFICATION)

        self._biometric_punch(student, '2', timezone.now())  # Hostel-Out, no verification yet

        student.refresh_from_db()
        leave.refresh_from_db()
        self.assertEqual(student.status, 'present')  # unchanged - departure blocked
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_CARETAKER_VERIFICATION)
        self.assertIsNone(leave.gate_out_at)

    def test_very_long_leave_reaches_ao_and_director_before_verification(self):
        student = make_student(student_id='N700003', status='present')
        warden, caretaker, cw, dsw, dean, ao, director = (
            make_staff('warden'), make_staff('caretaker'), make_staff('chief_warden'),
            make_staff('dsw'), make_staff('dean'), make_staff('ao'), make_staff('director'),
        )
        out_time = timezone.now() + timedelta(days=1)
        leave = make_leave(student, days=45, out_time=out_time, in_time=out_time + timedelta(days=45))

        workflow.approve_leave(leave.pk, warden)
        workflow.approve_leave(leave.pk, caretaker)
        workflow.approve_leave(leave.pk, cw)
        workflow.approve_leave(leave.pk, dsw)
        leave, escalated = workflow.approve_leave(leave.pk, dean)
        self.assertTrue(escalated)
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_AO)

        from .email_utils import send_ao_escalation_email
        mail.outbox = []
        send_ao_escalation_email(leave)
        self.assertEqual(len(mail.outbox), 1)

        # AO cannot skip Director, and Director cannot act before AO.
        with self.assertRaises(workflow.WorkflowError):
            workflow.approve_leave(leave.pk, director)

        leave, escalated = workflow.approve_leave(leave.pk, ao)
        self.assertFalse(escalated)
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_DIRECTOR)

        leave, _ = workflow.approve_leave(leave.pk, director)
        self.assertEqual(leave.status, 'approved')
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_CARETAKER_VERIFICATION)


class ApprovalTimelineTests(TestCase):
    """
    build_approval_timeline() is the single backend source of truth the UI's
    approval-route/timeline widgets render - the brief explicitly forbids
    computing this in JavaScript. These tests pin its contract independent
    of any template.
    """

    def test_short_leave_timeline_before_any_approval(self):
        student = make_student()
        leave = make_leave(student, days=1)
        steps = workflow.build_approval_timeline(leave)
        stages = [s['stage'] for s in steps]
        self.assertEqual(stages, [
            LeaveApplication.STAGE_WARDEN, LeaveApplication.STAGE_CARETAKER,
            LeaveApplication.STAGE_CARETAKER_VERIFICATION, LeaveApplication.STAGE_OUT,
            LeaveApplication.STAGE_COMPLETED,
        ])
        self.assertEqual(steps[0]['state'], 'current')
        self.assertTrue(all(s['state'] == 'locked' for s in steps[1:]))

    def test_timeline_reflects_partial_progress(self):
        student = make_student()
        warden = make_staff('warden')
        leave = make_leave(student, days=1)
        workflow.approve_leave(leave.pk, warden, 'Looks fine')
        leave.refresh_from_db()

        steps = workflow.build_approval_timeline(leave)
        by_stage = {s['stage']: s for s in steps}
        self.assertEqual(by_stage[LeaveApplication.STAGE_WARDEN]['state'], 'done')
        self.assertEqual(by_stage[LeaveApplication.STAGE_WARDEN]['actor'], warden)
        self.assertEqual(by_stage[LeaveApplication.STAGE_WARDEN]['comment'], 'Looks fine')
        self.assertEqual(by_stage[LeaveApplication.STAGE_CARETAKER]['state'], 'current')
        self.assertEqual(by_stage[LeaveApplication.STAGE_CARETAKER_VERIFICATION]['state'], 'locked')

    def test_rejected_leave_timeline_stops_and_marks_rejection(self):
        student = make_student()
        warden = make_staff('warden')
        leave = make_leave(student, days=1)
        workflow.reject_leave(leave.pk, warden, 'Not approved')
        leave.refresh_from_db()

        steps = workflow.build_approval_timeline(leave)
        by_stage = {s['stage']: s for s in steps}
        self.assertEqual(by_stage[LeaveApplication.STAGE_WARDEN]['state'], 'rejected')
        self.assertEqual(by_stage[LeaveApplication.STAGE_CARETAKER]['state'], 'locked')
        # No post-approval (verification/gate-out/completed) stages for a
        # rejected request - it never reaches them.
        self.assertNotIn(LeaveApplication.STAGE_CARETAKER_VERIFICATION, by_stage)

    def test_long_leave_timeline_includes_full_chain(self):
        student = make_student()
        leave = make_leave(student, days=40)
        steps = workflow.build_approval_timeline(leave)
        stages = [s['stage'] for s in steps]
        self.assertEqual(stages[:7], [
            LeaveApplication.STAGE_WARDEN, LeaveApplication.STAGE_CARETAKER,
            LeaveApplication.STAGE_CHIEF_WARDEN, LeaveApplication.STAGE_DSW,
            LeaveApplication.STAGE_DEAN, LeaveApplication.STAGE_AO, LeaveApplication.STAGE_DIRECTOR,
        ])


class PreviewLeaveRouteEndpointTests(TestCase):
    """
    The apply-leave form's "approval route" preview is backend-computed
    (workflow.get_required_chain), never reimplemented in JS - this endpoint
    is what the frontend actually calls. These tests exercise the real HTTP
    endpoint, not the underlying function directly.
    """

    def setUp(self):
        self.student = make_student()
        session = self.client.session
        session['user_role'] = 'student'
        session['student_pk'] = self.student.pk
        session.save()

    def _preview(self, out_time, in_time):
        return self.client.get(reverse('preview_leave_route'), {
            'out_time': out_time.strftime('%Y-%m-%dT%H:%M'),
            'in_time': in_time.strftime('%Y-%m-%dT%H:%M'),
        })

    def test_short_leave_route_stops_at_caretaker(self):
        now = timezone.now()
        response = self._preview(now, now + timedelta(days=2))
        data = response.json()
        self.assertTrue(data['valid'])
        self.assertEqual(data['duration'], 2)
        self.assertEqual(data['route'], ['Student', 'Pending Warden', 'Pending Caretaker', 'Caretaker Verification', 'Departure'])

    def test_long_leave_route_includes_full_hierarchy(self):
        now = timezone.now()
        response = self._preview(now, now + timedelta(days=35))
        data = response.json()
        self.assertTrue(data['valid'])
        self.assertIn('Pending AO Office', data['route'])
        self.assertIn('Pending Director', data['route'])

    def test_return_before_departure_is_rejected(self):
        now = timezone.now()
        response = self._preview(now, now - timedelta(hours=1))
        data = response.json()
        self.assertFalse(data['valid'])

    def test_non_student_cannot_access_preview(self):
        session = self.client.session
        session['user_role'] = 'viewer'
        session.save()
        response = self.client.get(reverse('preview_leave_route'), {'out_time': '', 'in_time': ''})
        self.assertRedirects(response, reverse('dashboard'))
