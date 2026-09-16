# hostel_app/email_utils.py
#
# Sends the AO Office / Director escalation email for very-long leaves.
# Leave-state and email-state are deliberately decoupled (LeaveApplication
# .email_status): an SMTP failure here must never roll back or block the
# approval that just happened in workflow.approve_leave(). Call this AFTER
# that transaction has committed, and never let it raise into the caller.

import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.utils import timezone

from .models import LeaveApplication, LeaveApprovalHistory
from .pdf import generate_leave_letter_pdf

logger = logging.getLogger(__name__)


def send_ao_escalation_email(leave):
    """
    Generate the leave letter PDF, attach it to an email, and send it to the
    configured AO_EMAIL / DIRECTOR_EMAIL recipients. Always updates
    `leave.email_status` to SENT or FAILED (never leaves it silently PENDING
    on an exception), and never raises - a mail-server outage must not be
    able to break the approval workflow that triggered this call.
    """
    leave.email_status = LeaveApplication.EMAIL_PENDING
    leave.save(update_fields=['email_status'])

    recipients = [addr for addr in (settings.AO_EMAIL, settings.DIRECTOR_EMAIL) if addr]

    try:
        if not recipients:
            raise RuntimeError(
                'No AO_EMAIL/DIRECTOR_EMAIL configured - set them in .env to enable delivery.'
            )

        pdf_bytes = generate_leave_letter_pdf(leave)
        leave.letter_pdf.save(
            f"leave_{leave.pk}_letter.pdf",
            ContentFile(pdf_bytes),
            save=False,
        )
        leave.letter_generated_at = timezone.now()

        subject = (
            f"[Leave Escalation] {leave.student.name} ({leave.student.student_id}) - "
            f"{leave.get_duration_days()}-day {leave.get_leave_type_display()} requires AO/Director approval"
        )
        body = (
            f"Student: {leave.student.name} ({leave.student.student_id})\n"
            f"Duration: {leave.get_duration_days()} day(s)\n"
            f"Dates: {timezone.localtime(leave.out_time).strftime('%d-%b-%Y %H:%M')} to "
            f"{timezone.localtime(leave.in_time).strftime('%d-%b-%Y %H:%M')}\n"
            f"Reason: {leave.reason}\n"
            f"Request reference: LEAVE-{leave.pk:06d}\n"
            f"Current status: Approved through Dean - awaiting AO Office / Director action.\n\n"
            f"The official leave letter is attached as a PDF.\n"
        )

        message = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
        )
        message.attach(f"leave_{leave.pk}_letter.pdf", pdf_bytes, 'application/pdf')
        message.send(fail_silently=False)

        leave.email_status = LeaveApplication.EMAIL_SENT
        leave.email_sent_at = timezone.now()
        leave.email_error = None
        leave.save(update_fields=['email_status', 'email_sent_at', 'email_error', 'letter_pdf', 'letter_generated_at'])

        LeaveApprovalHistory.objects.create(
            leave=leave, stage=leave.current_stage, actor=None,
            action=LeaveApprovalHistory.ACTION_LETTER_GENERATED,
            comment=f"Letter generated and emailed to {', '.join(recipients)}.",
            previous_status=leave.current_stage, new_status=leave.current_stage,
        )
        LeaveApprovalHistory.objects.create(
            leave=leave, stage=leave.current_stage, actor=None,
            action=LeaveApprovalHistory.ACTION_EMAIL_SENT,
            comment=f"Sent to {', '.join(recipients)}.",
            previous_status=leave.current_stage, new_status=leave.current_stage,
        )
        return True

    except Exception as exc:
        logger.exception("Failed to send AO escalation email for leave #%s", leave.pk)
        leave.email_status = LeaveApplication.EMAIL_FAILED
        leave.email_error = str(exc)
        leave.save(update_fields=['email_status', 'email_error'])
        LeaveApprovalHistory.objects.create(
            leave=leave, stage=leave.current_stage, actor=None,
            action=LeaveApprovalHistory.ACTION_EMAIL_FAILED,
            comment=str(exc)[:500],
            previous_status=leave.current_stage, new_status=leave.current_stage,
        )
        return False
