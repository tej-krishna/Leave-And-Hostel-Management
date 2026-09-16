# Backfills current_stage on any LeaveApplication rows that existed before
# the multi-stage approval workflow was introduced. Every such row defaults
# to current_stage='WARDEN' (the model field's default), which is wrong for
# rows that were already approved/rejected under the old single-step
# approve/reject flow:
#   - status='approved' -> treated as having already cleared the full old
#     approval step, so it is fast-forwarded to CLEARED_FOR_DEPARTURE
#     (pre-cleared for departure) rather than re-entering the new chain
#     at Warden. This preserves the existing eSSL gate-out behavior for
#     any leave that was already approved (see essl_app/views.py, which
#     now requires current_stage in {CLEARED_FOR_DEPARTURE, OUT} before a
#     biometric event may authorize departure).
#   - status='rejected' -> current_stage='REJECTED'.
#   - status='pending' -> left at the default 'WARDEN' (start of chain).
from django.db import migrations

from hostel_app.models import LeaveApplication


def backfill_stage(apps, schema_editor):
    LeaveApplicationModel = apps.get_model('hostel_app', 'LeaveApplication')
    LeaveApplicationModel.objects.filter(status='approved').update(
        current_stage=LeaveApplication.STAGE_CLEARED_FOR_DEPARTURE
    )
    LeaveApplicationModel.objects.filter(status='rejected').update(
        current_stage=LeaveApplication.STAGE_REJECTED
    )


def noop_reverse(apps, schema_editor):
    # Not reversible in a meaningful way (we'd have to know each row's
    # original pre-workflow state, which wasn't tracked). Left as a no-op
    # so `migrate` back is still possible without erroring.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('hostel_app', '0017_leaveapplication_caretaker_verified_at_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_stage, noop_reverse),
    ]
