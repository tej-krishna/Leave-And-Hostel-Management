# hostel_app/pdf.py
#
# Generates the official leave letter for very-long-leave requests escalated
# to AO Office / Director (see workflow.py: triggered when a leave's next
# stage becomes STAGE_AO). Renders from the actual LeaveApplication and its
# real approval_history - never invented/placeholder student data.

import io

from django.conf import settings
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.lib import colors


def generate_leave_letter_pdf(leave):
    """
    Build the official leave letter as PDF bytes for `leave` (a
    LeaveApplication instance). Reflects the request's *current* state -
    it is generated once, at the moment the request escalates to AO Office,
    so it necessarily shows the approval history collected so far (Warden
    through Dean) and states that AO Office / Director action is pending;
    it must never claim a status the request hasn't actually reached yet.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=20 * mm, bottomMargin=20 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'LetterTitle', parent=styles['Title'], alignment=TA_CENTER, fontSize=16,
    )
    subtitle_style = ParagraphStyle(
        'LetterSubtitle', parent=styles['Normal'], alignment=TA_CENTER,
        fontSize=10, textColor=colors.grey,
    )
    heading_style = ParagraphStyle(
        'SectionHeading', parent=styles['Heading3'], spaceBefore=10, spaceAfter=4,
    )
    body_style = styles['Normal']

    student = leave.student
    duration = leave.get_duration_days()
    story = []

    story.append(Paragraph(settings.INSTITUTION_NAME, title_style))
    story.append(Paragraph('Hostel Administration Office', subtitle_style))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph('OFFICIAL LEAVE REQUEST LETTER', styles['Heading2']))
    story.append(Paragraph(
        f"Reference: LEAVE-{leave.pk:06d} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Date: {timezone.localtime().strftime('%d-%b-%Y')}",
        body_style,
    ))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph('Student Details', heading_style))
    student_table = Table([
        ['Name', student.name, 'Student ID', student.student_id],
        ['Program / Branch', f"{student.get_year_display()} - {student.get_branch_display()}", 'Hostel', student.hostel],
        ['Room', student.room_number_display, 'Floor', student.floor_number_display],
    ], colWidths=[35 * mm, 55 * mm, 30 * mm, 45 * mm])
    student_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(student_table)
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph('Leave Details', heading_style))
    leave_table = Table([
        ['Type', leave.get_leave_type_display(), 'Duration', f"{duration} day(s)"],
        ['From', timezone.localtime(leave.out_time).strftime('%d-%b-%Y %H:%M'),
         'To', timezone.localtime(leave.in_time).strftime('%d-%b-%Y %H:%M')],
    ], colWidths=[35 * mm, 55 * mm, 30 * mm, 45 * mm])
    leave_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(leave_table)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"<b>Reason:</b> {leave.reason}", body_style))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph('Approval History', heading_style))
    history = list(leave.approval_history.all())
    if history:
        rows = [['Stage', 'Action', 'By', 'When', 'Comment']]
        for h in history:
            rows.append([
                h.stage.replace('_', ' ').title(),
                h.get_action_display(),
                h.actor.name if h.actor else 'System',
                timezone.localtime(h.timestamp).strftime('%d-%b-%Y %H:%M'),
                h.comment or '',
            ])
        hist_table = Table(rows, colWidths=[28 * mm, 28 * mm, 28 * mm, 32 * mm, 49 * mm])
        hist_table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(hist_table)
    else:
        story.append(Paragraph('No approval actions recorded yet.', body_style))

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        'This request has completed Warden, Caretaker, Chief Warden, DSW and Dean review '
        'as recorded above and now requires AO Office / Director approval before the '
        'student may proceed on leave.',
        body_style,
    ))
    story.append(Spacer(1, 14 * mm))

    sig_table = Table([
        ['AO Office Signature: _______________________', 'Director Signature: _______________________'],
        ['Date: ______________', 'Date: ______________'],
    ], colWidths=[85 * mm, 85 * mm])
    sig_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(sig_table)

    doc.build(story)
    return buffer.getvalue()
