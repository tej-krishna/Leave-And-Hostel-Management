# HostelManagement/hostel_app/models.py

import math
from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils import timezone # Import timezone for datetime operations
import uuid # For generating unique nonces

# --- NEW: Custom Manager for 'Normal' Students ---
# This manager will filter out students with 'viewer' or 'editor' roles
# ensuring that queries like Student.normal_students.all() only return
# students who are actual residents.
class NormalStudentsManager(models.Manager):
    def get_queryset(self):
        # Filter for students whose role is explicitly 'student'
        return super().get_queryset().filter(role='student')

HOSTEL_CHOICES = [
    ('I1', 'I1'), ('I2', 'I2'), ('I3', 'I3'),
    ('K2', 'K2'), ('K3', 'K3'), ('K4', 'K4'),
]

class Student(models.Model):
    YEAR_CHOICES = [
        ('P1', 'P1'), ('P2', 'P2'),
        ('E1', 'E1'), ('E2', 'E2'), ('E3', 'E3'), ('E4', 'E4'),
    ]

    BRANCH_CHOICES = [
        ('PUC', 'PUC'), ('ECE', 'ECE'), ('CSE', 'CSE'),
        ('EEE', 'EEE'), ('ME', 'ME'), ('MME', 'MME'),
        ('CE', 'CE'), ('CHE', 'CHE'), ('AI&ML', 'AI&ML'),
    ]

    STATUS_CHOICES = [
        ('present', 'Present'),
        ('leave', 'Leave'),
        ('outing', 'Outing'),
    ]

    # New ROLE_CHOICES for different user types
    # The multi-stage leave approval hierarchy (warden -> ... -> director)
    # added below uses these same accounts/login: a staff member's Student
    # record just carries one of the hierarchy roles instead of 'editor'.
    # 'viewer'/'editor' are unchanged and keep their existing room/device
    # management access from the earlier audit.
    ROLE_CHOICES = [
        ('student', 'Student'),
        ('viewer', 'Viewer'),
        ('editor', 'Editor'),
        ('warden', 'Warden'),
        ('caretaker', 'Caretaker'),
        ('chief_warden', 'Chief Warden'),
        ('dsw', 'DSW'),
        ('dean', 'Dean'),
        ('ao', 'AO Office'),
        ('director', 'Director'),
    ]

    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
    ]

    hostel = models.CharField(max_length=5, choices=HOSTEL_CHOICES, default='I1')
    name = models.CharField(max_length=100)
    student_id = models.CharField(max_length=20, unique=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, null=True, blank=True)
    dob = models.DateField(null=True, blank=True)
    mobile_number = models.CharField(max_length=15, unique=True)
    university_email = models.EmailField(max_length=100, null=True, blank=True)
    personal_email = models.EmailField(max_length=100, null=True, blank=True)
    year = models.CharField(max_length=2, choices=YEAR_CHOICES)
    branch = models.CharField(max_length=10, choices=BRANCH_CHOICES)
    room = models.ForeignKey('rooms_app.Room', on_delete=models.SET_NULL, null=True, blank=True, related_name='allotted_students')
    parent_name = models.CharField(max_length=100, null=True, blank=True)
    parent_mobile = models.CharField(max_length=15, null=True, blank=True)
    blood_group = models.CharField(max_length=5, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='present'
    )
    # New 'role' field with a default of 'student'
    role = models.CharField(
        max_length=15,
        choices=ROLE_CHOICES,
        default='student', # Default role for new students
        help_text="Defines the user's access level (student, viewer, editor)."
    )

    # --- NEW: Assign the custom manager to 'normal_students' ---
    objects = models.Manager() # The default manager that returns all objects
    normal_students = NormalStudentsManager() # Our custom manager for 'student' roles

    def __str__(self):
        return self.name

    @property
    def room_number_display(self):
        return self.room.room_number if self.room else "N/A"

    @property
    def floor_number_display(self):
        if self.room and self.room.floor:
            return self.room.floor.floor_number
        return "N/A"

    @property
    def auto_university_email(self):
        if self.university_email:
            return self.university_email
        return f"{self.student_id}@rguktn.ac.in"

class LeaveApplication(models.Model):
    LEAVE_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    LEAVE_TYPE_CHOICES = [
        ('leave', 'Leave'),
        ('outing', 'Outing'),
    ]

    # Ordered approval-chain stages, plus the post-approval departure/return
    # stages. `status` above stays the coarse pending/approved/rejected
    # summary that the rest of the app (overlap checks, dashboards, the
    # eSSL ingestion in essl_app/views.py) already filters on unchanged;
    # `current_stage` is the new fine-grained "who acts next" pointer.
    STAGE_WARDEN = 'WARDEN'
    STAGE_CARETAKER = 'CARETAKER'
    STAGE_CHIEF_WARDEN = 'CHIEF_WARDEN'
    STAGE_DSW = 'DSW'
    STAGE_DEAN = 'DEAN'
    STAGE_AO = 'AO'
    STAGE_DIRECTOR = 'DIRECTOR'
    STAGE_CARETAKER_VERIFICATION = 'CARETAKER_VERIFICATION'
    STAGE_CLEARED_FOR_DEPARTURE = 'CLEARED_FOR_DEPARTURE'
    STAGE_OUT = 'OUT'
    STAGE_COMPLETED = 'COMPLETED'
    STAGE_REJECTED = 'REJECTED'

    STAGE_CHOICES = [
        (STAGE_WARDEN, 'Pending Warden'),
        (STAGE_CARETAKER, 'Pending Caretaker'),
        (STAGE_CHIEF_WARDEN, 'Pending Chief Warden'),
        (STAGE_DSW, 'Pending DSW'),
        (STAGE_DEAN, 'Pending Dean'),
        (STAGE_AO, 'Pending AO Office'),
        (STAGE_DIRECTOR, 'Pending Director'),
        (STAGE_CARETAKER_VERIFICATION, 'Awaiting ID Verification'),
        (STAGE_CLEARED_FOR_DEPARTURE, 'Gate-Out Pending'),
        (STAGE_OUT, 'Outside Campus'),
        (STAGE_COMPLETED, 'Completed'),
        (STAGE_REJECTED, 'Rejected'),
    ]

    EMAIL_NOT_REQUIRED = 'NOT_REQUIRED'
    EMAIL_PENDING = 'PENDING'
    EMAIL_SENT = 'SENT'
    EMAIL_FAILED = 'FAILED'
    EMAIL_STATUS_CHOICES = [
        (EMAIL_NOT_REQUIRED, 'Not Required'),
        (EMAIL_PENDING, 'Pending'),
        (EMAIL_SENT, 'Sent'),
        (EMAIL_FAILED, 'Failed'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='leave_applications')
    leave_type = models.CharField(max_length=10, choices=LEAVE_TYPE_CHOICES, default='leave', help_text="Type of application: Leave or Outing.")
    reason = models.TextField(help_text="Reason for leave/outing.")
    out_time = models.DateTimeField(default=timezone.now, help_text="Date and time student plans to leave.")
    in_time = models.DateTimeField(default=timezone.now, help_text="Date and time student plans to return.")
    approval_of = models.CharField(max_length=150, blank=True, null=True, help_text="Optional: Name or role of the person who approved this.")

    status = models.CharField(
        max_length=10,
        choices=LEAVE_STATUS_CHOICES,
        default='pending',
        help_text="Status of the leave application (Pending, Approved, Rejected)."
    )

    # --- Multi-stage approval workflow state ---
    current_stage = models.CharField(
        max_length=30,
        choices=STAGE_CHOICES,
        default=STAGE_WARDEN,
        help_text="Which authority the request is currently waiting on, or its post-approval departure/return stage.",
    )
    final_approved_at = models.DateTimeField(null=True, blank=True)
    caretaker_verified_at = models.DateTimeField(null=True, blank=True)
    caretaker_verified_by = models.ForeignKey(
        Student, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='verified_departures',
        help_text="The caretaker who confirmed the student's ID before departure.",
    )
    gate_out_at = models.DateTimeField(null=True, blank=True, help_text="First biometric out-punch (Gate Out or Hostel Out) recorded for this leave.")
    gate_in_at = models.DateTimeField(null=True, blank=True, help_text="Biometric Gate-In punch recorded for this leave's return.")
    hostel_in_at = models.DateTimeField(null=True, blank=True, help_text="Biometric Hostel-In punch that completed this leave's return.")
    completed_at = models.DateTimeField(null=True, blank=True)

    # --- Long-leave official letter (generated when the leave escalates to AO Office) ---
    letter_pdf = models.FileField(upload_to='leave_letters/', null=True, blank=True)
    letter_generated_at = models.DateTimeField(null=True, blank=True)
    email_status = models.CharField(max_length=15, choices=EMAIL_STATUS_CHOICES, default=EMAIL_NOT_REQUIRED)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_error = models.TextField(blank=True, null=True, help_text="Last email send error, if email_status is FAILED.")

    parent_coming = models.BooleanField(default=False, help_text="Is the student's own parent coming to pick them up?")
    companion = models.ForeignKey(
        Student,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='accompanied_leaves',
        help_text="The student whose parent is coming (for restricted group leave)."
    )



    def __str__(self):
        return f"{self.get_leave_type_display()} for {self.student.name} ({self.get_status_display()})"

    class Meta:
        ordering = ['-out_time']

    def get_duration_days(self):
        """
        The single authoritative duration calculation, used for approval-chain
        routing, display, the generated PDF letter, and the email. Defined as
        the ceiling of the elapsed time in whole days, minimum 1 - e.g. a leave
        from 1 Sep 9am to 3 Sep 6pm is 3 days, not 2, since it spans into a
        third calendar day. This threshold choice is documented in
        PROJECT_AUDIT/LEAVE_WORKFLOW.md because the source requirement did not
        pin an exact inclusive/exclusive convention.
        """
        if not self.out_time or not self.in_time:
            return 0
        delta_seconds = (self.in_time - self.out_time).total_seconds()
        if delta_seconds <= 0:
            return 0
        return max(1, math.ceil(delta_seconds / 86400))


class LeaveApprovalHistory(models.Model):
    """
    Immutable audit trail for the leave approval/departure/return workflow.
    One row per action - never updated or overwritten, per the workflow
    requirement that approval history must be preserved in full.
    """
    ACTION_APPROVED = 'APPROVED'
    ACTION_REJECTED = 'REJECTED'
    ACTION_VERIFIED = 'VERIFIED'
    ACTION_VERIFICATION_FAILED = 'VERIFICATION_FAILED'
    ACTION_GATE_OUT = 'GATE_OUT'
    ACTION_GATE_IN = 'GATE_IN'
    ACTION_HOSTEL_IN = 'HOSTEL_IN'
    ACTION_LETTER_GENERATED = 'LETTER_GENERATED'
    ACTION_EMAIL_SENT = 'EMAIL_SENT'
    ACTION_EMAIL_FAILED = 'EMAIL_FAILED'
    ACTION_CHOICES = [
        (ACTION_APPROVED, 'Approved'),
        (ACTION_REJECTED, 'Rejected'),
        (ACTION_VERIFIED, 'ID Verified'),
        (ACTION_VERIFICATION_FAILED, 'ID Verification Failed'),
        (ACTION_GATE_OUT, 'Biometric Gate-Out'),
        (ACTION_GATE_IN, 'Biometric Gate-In'),
        (ACTION_HOSTEL_IN, 'Biometric Hostel-In'),
        (ACTION_LETTER_GENERATED, 'Letter Generated'),
        (ACTION_EMAIL_SENT, 'Email Sent'),
        (ACTION_EMAIL_FAILED, 'Email Failed'),
    ]

    leave = models.ForeignKey(LeaveApplication, on_delete=models.CASCADE, related_name='approval_history')
    stage = models.CharField(max_length=30, help_text="The stage this action was taken at.")
    actor = models.ForeignKey(
        Student, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='leave_actions_taken',
        help_text="The staff member who took this action (blank for system/biometric events).",
    )
    action = models.CharField(max_length=25, choices=ACTION_CHOICES)
    comment = models.TextField(blank=True, null=True)
    previous_status = models.CharField(max_length=30, blank=True, null=True)
    new_status = models.CharField(max_length=30, blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']
        verbose_name_plural = 'Leave approval history'

    def __str__(self):
        who = self.actor.name if self.actor else 'System'
        return f"{self.leave_id}: {who} {self.get_action_display()} at {self.stage}"



# --- MODIFIED StudentStatusLog MODEL ---
class StudentStatusLog(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='status_logs')
    current_status = models.CharField(max_length=10, choices=Student.STATUS_CHOICES, help_text="The status the student changed to.")
    change_timestamp = models.DateTimeField(auto_now_add=True, help_text="Date and time of the status change.")
    log_type = models.CharField(
        max_length=50,
        choices=[
            ('manual', 'Manual'),
            ('biometric', 'Biometric')
        ],
        default='manual',
        help_text="Indicates if the status change was manual or via biometric scan."
    )


    def __str__(self):
        return f"Status of {self.student.name} became '{self.get_current_status_display()}' on {self.change_timestamp.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        ordering = ['-change_timestamp']

# --- MODIFIED pre_save SIGNAL ---
@receiver(pre_save, sender=Student)
def log_student_status_change(sender, instance, **kwargs):
    if instance.pk: # Only proceed if the instance already exists (i.e., it's an update)
        try:
            # Fetch the original object from the database to compare its status
            original_student = sender.objects.get(pk=instance.pk)
            if original_student.status != instance.status:
                # Status has changed, create a log entry with only the new (current) status
                # This signal is for manual changes; QR scans will create their own logs.
                StudentStatusLog.objects.create(
                    student=instance,
                    current_status=instance.status, # Log the new status
                    log_type='manual' # Explicitly mark as manual
                )
        except sender.DoesNotExist:
            pass # This handles the case where the object is new and doesn't exist in the DB yet