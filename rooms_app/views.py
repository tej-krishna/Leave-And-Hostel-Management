from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, Http404
from .models import Floor, Room
from hostel_app.models import Student, HOSTEL_CHOICES # Assuming Student model and HOSTEL_CHOICES are in hostel_app
import json
from django.contrib import messages
from django.db.models import Q # Import Q for complex lookups
from django.views.decorators.http import require_POST

# Import the role_required decorator
from .utils import role_required # If utils.py is in rooms_app
# from common_app.utils import role_required # If utils.py is in a common_app


@role_required(['viewer', 'editor'])
def room_selection_view(request, hostel_code='I1'):
    """
    Displays an interactive grid of rooms, showing their occupancy status.
    Accessible by 'viewer' and 'editor' roles. Filtered by hostel.
    """
    all_floors = Floor.objects.filter(hostel=hostel_code).order_by('floor_number')

    all_rooms_data = {}
    for floor in all_floors:
        floor_rooms_data = {}

        # Pre-fetch rooms for the current floor to minimize DB hits
        rooms_on_floor = floor.rooms.all().prefetch_related('allotted_students')

        for room_obj in rooms_on_floor:
            # Only count 'student' role (resident) students as occupied for display on the room grid
            occupied_count = room_obj.get_occupied_beds_count() # Using the helper method
            floor_rooms_data[str(room_obj.room_number)] = {
                'room_id': room_obj.pk,
                'is_disabled': room_obj.is_disabled,
                'capacity': room_obj.capacity,
                'occupied': occupied_count,
            }

        # Ensure all possible room numbers (1-104) are represented, even if they don't exist in DB
        # This assumes room numbers are contiguous or within a known range for a floor.
        # If room numbers are arbitrary, this logic might need adjustment.
        for i in range(1, 105): # Assuming rooms from 1 to 104 per floor
            room_number_str = str(i)
            if room_number_str not in floor_rooms_data:
                floor_rooms_data[room_number_str] = {
                    'room_id': None, # Indicates room doesn't exist in DB
                    'is_disabled': False,
                    'capacity': 0,
                    'occupied': 0,
                }

        all_rooms_data[str(floor.pk)] = dict(sorted(floor_rooms_data.items(), key=lambda item: int(item[0])))

    all_rooms_data_json = json.dumps(all_rooms_data)

    context = {
        'all_floors': all_floors,
        'all_rooms_data_json': all_rooms_data_json,
        'title': f'Select Room - {hostel_code}',
        'user_role': request.session.get('user_role'),
        'current_hostel': hostel_code,
        'hostels': [h[0] for h in HOSTEL_CHOICES],
    }
    return render(request, 'rooms_app/room_selection.html', context)

def hostel_3d_view(request):
    return render(request, 'rooms_app/hostel_3d.html')

@role_required(['viewer', 'editor'])
def get_room_details_ajax(request, floor_pk, room_number):
    """
    AJAX endpoint to fetch detailed information about a specific room.
    Accessible by 'viewer' and 'editor' roles.
    """
    try:
        room = get_object_or_404(Room, floor__pk=floor_pk, room_number=room_number)
    except Http404:
        return JsonResponse({'error': 'Room not found'}, status=404)

    # Only retrieve 'student' role (resident) students allotted to the room for display
    students_in_room = room.allotted_students.filter(role='student')
    occupied_beds = students_in_room.count()
    available_beds = room.capacity - occupied_beds

    allotted_students_data = [
    {
        'pk': student.pk,
        'name': student.name,
        'student_id': student.student_id,
        'status': student.status, # <--- IMPORTANT: Send the actual status string
    }
    for student in students_in_room
]

    # Get unallotted 'student' role (resident) students for the dropdown
    # Using the custom manager normal_students and filtering by hostel
    unallotted_students = Student.normal_students.filter(room__isnull=True, hostel=room.floor.hostel).order_by('name')
    unallotted_students_data = [
        {
            'pk': student.pk,
            'name': student.name,
            'student_id': student.student_id,
        }
        for student in unallotted_students
    ]

    room_data = {
        'room_number': room.room_number,
        'room_pk': room.pk,
        'floor_number': room.floor.floor_number,
        'floor_name': room.floor.name,
        'capacity': room.capacity,
        'is_disabled': room.is_disabled,
        'occupied_beds': occupied_beds,
        'available_beds': available_beds,
        'is_full': room.is_full(), # Using the Room model's method
        'allotted_students': allotted_students_data,
        'unallotted_students': unallotted_students_data,
        'user_role': request.session.get('user_role'),
    }

    return JsonResponse(room_data)


@role_required(['viewer', 'editor'])
def room_detail_view(request, floor_pk, room_number):
    """
    Displays the detailed page for a specific room, allowing management actions.
    Accessible by 'viewer' and 'editor' roles.
    """
    room = get_object_or_404(Room, floor__pk=floor_pk, room_number=room_number)

    # Only display 'student' role (resident) students allotted to the room
    students_in_room = room.allotted_students.filter(role='student')
    occupied_beds = students_in_room.count()
    available_beds = room.capacity - occupied_beds

    # Only show 'student' role (resident) students in the unallotted dropdown for same hostel
    unallotted_students = Student.normal_students.filter(room__isnull=True, hostel=room.floor.hostel).order_by('name')

    context = {
        'room': room,
        'occupied_beds': occupied_beds,
        'available_beds': available_beds,
        'is_full': room.is_full(), # Using the Room model's method
        'allotted_students': students_in_room,
        'unallotted_students': unallotted_students,
        'title': f'Manage Room {room.room_number} (Floor {room.floor.floor_number})',
        'floor_pk': floor_pk,
        'room_number': room_number,
        'user_role': request.session.get('user_role'),
    }
    return render(request, 'rooms_app/room_detail.html', context)

@role_required(['editor'])
@require_POST
def allot_student_to_room(request, room_id):
    # Ensure this is an AJAX request if you want to force it
    # if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
    #     return HttpResponseBadRequest("Must be an AJAX request")

    room = get_object_or_404(Room, pk=room_id)
    student_pk = request.POST.get('student_id')

    # Add a check for is_disabled or is_full here as well, though frontend tries to prevent
    if room.is_disabled:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "Cannot allot student to a disabled room."}, status=400)
        messages.error(request, "Cannot allot student to a disabled room.")
        return redirect('room_selection')

    if room.is_full(): # Use the model method for consistency
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "Room is full. Cannot allot more students."}, status=400)
        messages.error(request, "Room is full. Cannot allot more students.")
        return redirect('room_selection')

    if not student_pk:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "No student selected."}, status=400)
        messages.error(request, "No student selected for allotment.")
        return redirect('room_selection')

    try:
        student = get_object_or_404(Student.normal_students, pk=student_pk) # Use normal_students manager
    except Http404:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "Selected student not found or cannot be allotted."}, status=404)
        messages.error(request, "Selected student not found or cannot be allotted.")
        return redirect('room_selection')


    if student.room: # Check if student is already allotted
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": f"Student {student.name} is already allotted to room {student.room.room_number}."}, status=400)
        messages.error(request, f"Student {student.name} is already allotted to room {student.room.room_number}.")
        return redirect('room_selection')


    # If all checks pass
    student.room = room
    student.save()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            "success": True,
            "message": f"Student {student.name} allotted successfully to Room {room.room_number}.",
            "room_id": room.pk, # <--- IMPORTANT: Return the room_id
            "floor_id": room.floor.pk, # <--- IMPORTANT: Return the floor_id as well
            "room_number": room.room_number
        })
    messages.success(request, f"Student {student.name} allotted successfully to Room {room.room_number}.")
    return redirect('room_selection')

@role_required(['editor'])
def unallot_student_from_room(request, student_pk):
    """
    Handles the POST request to unallot a student from their room.
    Accessible only by 'editor' role.
    Returns JSON response for AJAX calls.
    """
    if request.method == 'POST':
        try:
            # Ensure only 'student' role (resident) students can be unallotted via this view
            student = get_object_or_404(Student.normal_students, pk=student_pk)

            if student.room:
                old_room = student.room # Store for success message

                student.room = None
                student.save()

                return JsonResponse({
                    'success': True,
                    'message': f'Student {student.name} unallotted successfully from room {old_room.room_number}.',
                    'student_pk': student.pk, # Optionally return student_pk for client-side updates
                    'room_number': old_room.room_number
                }, status=200)
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Student is not currently allotted to any room.'
                }, status=400)
        except Http404:
            return JsonResponse({
                'success': False,
                'message': 'Student not found or is not a normal student.'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'An error occurred: {str(e)}'
            }, status=500)
    else:
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method. Only POST is allowed.'
        }, status=405)


@role_required(['editor'])
def toggle_room_status(request, room_id):
    """
    Toggles the is_disabled status of a room.
    Accessible only by 'editor' role.
    """
    if request.method == 'POST':
        room = get_object_or_404(Room, pk=room_id)
        room.is_disabled = not room.is_disabled
        room.save()
        status_message = "disabled" if room.is_disabled else "enabled"
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True, 
                'message': f"Room {room.room_number} has been {status_message}.", 
                'room_id': room.pk, 
                'room_number': room.room_number, 
                'is_disabled': room.is_disabled
            })
            
        messages.success(request, f"Room {room.room_number} has been {status_message}.")
        return redirect('room_selection') # Safe fallback route
    return JsonResponse({'error': 'Invalid request method'}, status=400)