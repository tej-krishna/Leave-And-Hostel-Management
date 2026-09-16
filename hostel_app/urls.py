# HostelManagement/hostel_app/urls.py

from django.urls import path
from . import views

urlpatterns = [
    # General views
    path('login/', views.login_view, name='login'),
    path('perform_login/', views.perform_login, name='perform_login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboard for staff roles
    path('dashboard/', views.dashboard, name='dashboard'),

    # Student Status Management (Staff views)
    path('status_updater/', views.status_updater, name='status_updater'),
    path('update_student_status/<int:student_id>/', views.update_student_status, name='update_student_status'),
    path('students/<int:student_pk>/edit/', views.edit_student_view, name='edit_student'),

    # Student Lists (Staff views)
    path('students/total/', views.total_students_list, name='total_students_list'),
    path('students/present/', views.present_students_list, name='present_students_list'),
    path('students/leave/', views.leave_students_list, name='leave_students_list'),
    path('students/outing/', views.outing_students_list, name='outing_students_list'),
    path('students/yearwise/', views.yearwise_student_data, name='yearwise_student_data'),

    # Student Lookup (Shared: Staff and Student)
    path('student_lookup/', views.student_lookup_view, name='student_lookup'),
    path('students/<str:query>/detail/', views.student_lookup_view, name='student_detail_from_url'),

    # Leave Application (Student view)
    # Corrected path to 'apply/'
    path('leave/apply/', views.apply_leave_view, name='apply_leave'),
    path('leave/preview-route/', views.preview_leave_route, name='preview_leave_route'),

    # Leave Management (Staff view - read-only oversight, see views.leave_management_view)
    path('leave_management/', views.leave_management_view, name='leave_management'),
    path('update_leave_status/<int:leave_pk>/', views.update_leave_status, name='update_leave_status'),

    # Multi-stage leave approval workflow (Warden -> Caretaker -> Chief Warden -> DSW -> Dean -> AO -> Director)
    path('leave/approvals/', views.leave_approval_queue, name='leave_approval_queue'),
    path('leave/approvals/<int:leave_pk>/action/', views.process_leave_approval, name='process_leave_approval'),
    path('leave/verification/', views.caretaker_verification_queue, name='caretaker_verification_queue'),
    path('leave/verification/<int:leave_pk>/verify/', views.verify_student_departure, name='verify_student_departure'),
    path('leave/<int:leave_pk>/letter/', views.download_leave_letter, name='download_leave_letter'),

    # Biometric Tracking
    path('biometric_track/', views.biometric_track_view, name='biometric_track'),
]