# HostelManagement/hostel_app/models.py

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
    ROLE_CHOICES = [
        ('student', 'Student'),
        ('viewer', 'Viewer'),
        ('editor', 'Editor'),
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
        max_length=10,
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