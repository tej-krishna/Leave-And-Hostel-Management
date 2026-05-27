# HostelManagement/rooms_app/urls.py

from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    path('hostels/', views.hostel_3d_view, name='hostel_3d'),
    # Room Selection Grid
    path('selection/', RedirectView.as_view(pattern_name='room_selection', permanent=False), kwargs={'hostel_code': 'I1'}, name='room_selection_default'),
    path('selection/<str:hostel_code>/', views.room_selection_view, name='room_selection'),

    # AJAX endpoint for fetching room details for the modal/popup
    path('details/floor/<int:floor_pk>/room/<str:room_number>/', views.get_room_details_ajax, name='get_room_details_ajax'),

    # Detailed page for a specific room (non-AJAX, if needed for a dedicated page)
    # Note: If your 'room_detail_view' is only used via AJAX, this might be redundant with 'get_room_details_ajax'
    # but I'm keeping it if you intend to have a separate full page for room details.
    path('manage/floor/<int:floor_pk>/room/<str:room_number>/', views.room_detail_view, name='room_detail'),

    # Actions for alloting/unalloting students and toggling room status
    path('allot/<int:room_id>/', views.allot_student_to_room, name='allot_student_to_room'),
    path('unallot/<int:student_pk>/', views.unallot_student_from_room, name='unallot_student_from_room'),
    path('toggle-status/<int:room_id>/', views.toggle_room_status, name='toggle_room_status'),
]