# HostelManagement/hostel_app/admin.py

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import Student, LeaveApplication, StudentStatusLog, LeaveApprovalHistory
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
        'status', 'current_stage', 'email_status',
    )
    list_filter = ('status', 'current_stage', 'leave_type', 'student__year', 'student__branch') # Filter by student details
    search_fields = ('student__name', 'student__student_id', 'reason')
    date_hierarchy = 'out_time'
    ordering = ('-out_time',)
    readonly_fields = (
        'current_stage', 'final_approved_at', 'caretaker_verified_at', 'caretaker_verified_by',
        'gate_out_at', 'gate_in_at', 'hostel_in_at', 'completed_at',
        'letter_pdf', 'letter_generated_at', 'email_status', 'email_sent_at', 'email_error',
    )

    fieldsets = (
        (None, {
            'fields': ('student', 'leave_type', 'reason', 'out_time', 'in_time', 'approval_of', 'status')
        }),
        ('Workflow state (read-only - use the authority queues to change these)', {
            'fields': (
                'current_stage', 'final_approved_at', 'caretaker_verified_at', 'caretaker_verified_by',
                'gate_out_at', 'gate_in_at', 'hostel_in_at', 'completed_at',
            ),
        }),
        ('Long-leave letter / email (read-only)', {
            'fields': ('letter_pdf', 'letter_generated_at', 'email_status', 'email_sent_at', 'email_error'),
        }),
    )

    # Add custom URLs to the admin for approve/reject
    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<path:object_id>/approve/', self.admin_site.admin_view(self.approve_leave), name='hostel_app_leaveapplication_approve'),
            path('<path:object_id>/reject/', self.admin_site.admin_view(self.reject_leave), name='hostel_app_leaveapplication_reject'),
        ]
        return custom_urls + urls

    # NOTE: these two "quick action" links used to set leave.status directly,
    # which would let anyone with Django admin access instantly bypass the
    # entire Warden -> Caretaker -> ... -> Director approval chain added in
    # the leave workflow feature. That's exactly the "authority bypass" the
    # workflow's authorization rules are meant to prevent, so both actions
    # are now disabled here rather than left as a backdoor around
    # hostel_app/workflow.py. The URLs are kept (rather than removed) so the
    # existing "Actions" column/links in this admin don't 404; they just
    # explain where approvals now happen instead of mutating anything.
    def approve_leave(self, request, object_id):
        leave = self.get_object(request, object_id)
        if not leave:
            return self.message_user(request, "Leave application not found.", level='error')
        self.message_user(
            request,
            "Leave approvals now go through the staged workflow (Warden -> Caretaker -> ...). "
            "Use the relevant authority's approval queue instead of the admin.",
            level='warning',
        )
        return self.response_change(request, leave)

    def reject_leave(self, request, object_id):
        leave = self.get_object(request, object_id)
        if not leave:
            return self.message_user(request, "Leave application not found.", level='error')
        self.message_user(
            request,
            "Leave rejections now go through the staged workflow. "
            "Use the relevant authority's approval queue instead of the admin.",
            level='warning',
        )
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


@admin.register(LeaveApprovalHistory)
class LeaveApprovalHistoryAdmin(admin.ModelAdmin):
    """Read-only audit trail - never editable/deletable from the admin so
    the workflow's history can't be silently overwritten (requirement: the
    approval history must never be silently overwritten)."""
    list_display = ('leave', 'stage', 'action', 'actor', 'timestamp')
    list_filter = ('action', 'stage')
    search_fields = ('leave__student__name', 'leave__student__student_id')
    ordering = ('-timestamp',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False