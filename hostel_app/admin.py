# HostelManagement/hostel_app/admin.py

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import Student, LeaveApplication, StudentStatusLog # Import new models
from django.utils import timezone 
import uuid # For generating nonces

# --- Admin for Student Model ---
@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'student_id', 'mobile_number', 'year', 'branch',
        'room_number_display', 'status', 'role', 'view_on_site_link' # Add 'role' to list display
    )
    search_fields = ('name', 'student_id', 'mobile_number')
    list_filter = ('year', 'branch', 'status', 'role') # Add 'role' to list filter
    ordering = ('year', 'branch', 'name')
    fieldsets = (
        (None, {
            'fields': ('name', 'student_id', 'gender', 'dob', 'mobile_number', 'room', 'hostel', 'role')
        }),
        ('Contact Information', {
            'fields': ('university_email', 'personal_email', 'address'),
        }),
        ('Parent Information', {
            'fields': ('parent_name', 'parent_mobile'),
        }),
        ('Academic & Personal Details', {
            'fields': ('year', 'branch', 'blood_group'),
        }),
        ('Hostel Status', {
            'fields': ('status',),
            'description': "Current status in the hostel. Manual override only."
        }),
    )

    
    # Custom method to display room number from related Room object
    def room_number_display(self, obj):
        return obj.room.room_number if obj.room else 'N/A'
    room_number_display.short_description = 'Room No.'
    
    # Custom method to create a link to view student details on the front-end
    def view_on_site_link(self, obj):
        # Assuming 'student_lookup' is the URL name for your student detail page
        # And it accepts a student_id as a query parameter
        url = reverse('student_lookup') + f'?query={obj.student_id}'
        return format_html('<a href="{}" target="_blank">View Details</a>', url)
    view_on_site_link.short_description = 'Details'

# --- Admin for LeaveApplication Model ---
@admin.register(LeaveApplication)
class LeaveApplicationAdmin(admin.ModelAdmin):
    list_display = (
        'student', 'leave_type', 'out_time', 'in_time', 'reason',
        'status', 'actions_column'
    )
    list_filter = ('status', 'leave_type', 'student__year', 'student__branch') # Filter by student details
    search_fields = ('student__name', 'student__student_id', 'reason')
    date_hierarchy = 'out_time'
    ordering = ('-out_time',)
    
    # Read-only fields in the admin form
    # Removed readonly constraint as per user request to be able to edit everything
    # readonly_fields = ('student',) 

    fieldsets = (
        (None, {
            'fields': ('student', 'leave_type', 'reason', 'out_time', 'in_time', 'approval_of', 'status')
        }),
    )

    # Custom column for actions (Approve/Reject)
    def actions_column(self, obj):
        if obj.status == 'pending':
            return format_html(
                '<a class="button" href="{}">Approve</a> &nbsp;'
                '<a class="button" href="{}">Reject</a>',
                reverse('admin:hostel_app_leaveapplication_approve', args=[obj.pk]),
                reverse('admin:hostel_app_leaveapplication_reject', args=[obj.pk])
            )
        return "" # No actions for rejected leaves
    actions_column.short_description = 'Actions'

    # Add custom URLs to the admin for approve/reject
    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<path:object_id>/approve/', self.admin_site.admin_view(self.approve_leave), name='hostel_app_leaveapplication_approve'),
            path('<path:object_id>/reject/', self.admin_site.admin_view(self.reject_leave), name='hostel_app_leaveapplication_reject'),
        ]
        return custom_urls + urls

    # Custom admin view for approving leave
    def approve_leave(self, request, object_id):
        leave = self.get_object(request, object_id)
        if not leave:
            return self.message_user(request, "Leave application not found.", level='error')
        
        try:
            leave.status = 'approved'
            leave.save() # Save status change first
            self.message_user(request, f"Leave for {leave.student.name} approved successfully.")
        except Exception as e:
            self.message_user(request, f"Error approving leave: {e}", level='error')
        
        return self.response_change(request, leave) # Redirect back to the change form

    # Custom admin view for rejecting leave
    def reject_leave(self, request, object_id):
        leave = self.get_object(request, object_id)
        if not leave:
            return self.message_user(request, "Leave application not found.", level='error')

        leave.status = 'rejected'
        leave.save()

        self.message_user(request, f"Leave for {leave.student.name} rejected.")
        return self.response_change(request, leave)

@admin.register(StudentStatusLog)
class StudentStatusLogAdmin(admin.ModelAdmin):
    list_display = (
        'student', 'current_status', 'change_timestamp', 'log_type'
    )
    list_filter = ('current_status', 'log_type', 'change_timestamp')
    search_fields = ('student__name', 'student__student_id')
    # Log fields are kept readable but editable if needed as per user request
    # readonly_fields = ('student', 'current_status', 'change_timestamp', 'log_type')

    ordering = ('-change_timestamp',)