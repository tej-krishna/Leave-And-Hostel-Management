# HostelManagement/hostel_app/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count, Case, When, IntegerField, Q
from django.db.models.functions import TruncDate
from django.contrib import messages
from django.urls import reverse # Import reverse
from .models import Student, LeaveApplication, StudentStatusLog
from .forms import LeaveApplicationForm, StudentForm
from functools import wraps # Import wraps for decorator

from django.http import JsonResponse, HttpResponse # Import JsonResponse for API, HttpResponse for image
from datetime import datetime, timedelta
from django.utils import timezone # For timezone.now() and timezone-aware datetimes


# --- Decorator for Role-Based Access Control ---
def role_required(allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            user_role = request.session.get('user_role')
            if user_role in allowed_roles:
                return view_func(request, *args, **kwargs)
            elif not user_role:
                messages.error(request, "You need to log in to access this page.")
                return redirect('login')
            else:
                messages.error(request, "You do not have permission to access this page.")
                if user_role == 'student':
                    # Student's default page is apply_leave, not dashboard
                    return redirect('apply_leave')
                else:
                    return redirect('dashboard')
        return _wrapped_view
    return decorator

# Helper function to apply common filters and exclude staff-role students
def _filter_students_and_exclude_staff(request, queryset):
    # This function now expects the queryset to already be filtered (e.g., from Student.normal_students)
    search_id = request.GET.get('search_id')
    search_year = request.GET.get('search_year')

    if search_id:
        queryset = queryset.filter(student_id__icontains=search_id)
    if search_year:
        queryset = queryset.filter(year=search_year)

    return queryset, search_id, search_year


# --- QR Code Specific Views ---




@role_required(['viewer', 'editor'])
def dashboard(request):
    # Use normal_students manager to only count resident students
    total_students = Student.normal_students.count()
    present_count = Student.normal_students.filter(status='present').count()
    leave_count = Student.normal_students.filter(status='leave').count()
    outing_count = Student.normal_students.filter(status='outing').count()

    # Hostel-wise status aggregation
    hostel_data = Student.normal_students.values('hostel').annotate(
        total=Count('id'),
        present=Count(Case(When(status='present', then=1), output_field=IntegerField())),
        leave=Count(Case(When(status='leave', then=1), output_field=IntegerField())),
        outing=Count(Case(When(status='outing', then=1), output_field=IntegerField()))
    ).order_by('hostel')

    # Year-wise status aggregation
    year_data = Student.normal_students.values('year').annotate(
        total=Count('id'),
        present=Count(Case(When(status='present', then=1), output_field=IntegerField())),
        leave=Count(Case(When(status='leave', then=1), output_field=IntegerField())),
        outing=Count(Case(When(status='outing', then=1), output_field=IntegerField()))
    ).order_by('year')

    # Day-wise approved leave trends (Last 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    leave_trends = LeaveApplication.objects.filter(
        status='approved',
        out_time__gte=thirty_days_ago
    ).annotate(date=TruncDate('out_time')).values('date').annotate(count=Count('id')).order_by('date')

    # Convert QuerySets to lists/dicts for JSON serialization in template if needed
    # but Django templates handle them fine for loops. 
    # For JS charts, we might want to prepare them as lists.

    # --- Logic for Status Updater Modal ---
    students = Student.normal_students.all().order_by('name')
    students, search_id, search_year = _filter_students_and_exclude_staff(request, students)
    available_years = Student.normal_students.values_list('year', flat=True).distinct().order_by('year')

    context = {
        'total_students': total_students,
        'present_count': present_count,
        'leave_count': leave_count,
        'outing_count': outing_count,
        'hostel_data': list(hostel_data),
        'year_data': list(year_data),
        'leave_trends': list(leave_trends),
        'user_role': request.session.get('user_role'),
        # Data for Status Updater Modal
        'students': students,
        'search_id': search_id,
        'search_year': search_year,
        'available_years': available_years,
        'YEAR_CHOICES': Student.YEAR_CHOICES,
    }
    return render(request, 'hostel_app/dashboard.html', context)


@role_required(['viewer', 'editor'])
def status_updater(request):
    # Start with only normal students from the custom manager
    students = Student.normal_students.all().order_by('name')

    # Apply filters using the helper function
    students, search_id, search_year = _filter_students_and_exclude_staff(request, students)

    # Available years should also only come from normal students
    available_years = Student.normal_students.values_list('year', flat=True).distinct().order_by('year')

    context = {
        'students': students,
        'search_id': search_id,
        'search_year': search_year,
        'available_years': available_years,
        'YEAR_CHOICES': Student.YEAR_CHOICES,
        'user_role': request.session.get('user_role'),
    }
    return render(request, 'hostel_app/status_updater.html', context)

@role_required(['editor'])
def update_student_status(request, student_id):
    if request.method == 'POST':
        # Ensure only normal students can have their status updated this way
        student = get_object_or_404(Student.normal_students, pk=student_id)
        new_status = request.POST.get('status')
        if new_status in ['present', 'leave', 'outing']:
            student.status = new_status
            student.save()
            messages.success(request, f"Status for {student.name} updated to {student.get_status_display()}.")
        next_url = request.POST.get('next') or 'status_updater'
        return redirect(next_url)
@role_required(['editor'])
def edit_student_view(request, student_pk):
    student = get_object_or_404(Student, pk=student_pk)
    if request.method == 'POST':
        form = StudentForm(request.POST, instance=student)
        if form.is_valid():
            form.save()
            messages.success(request, f"Details for {student.name} updated successfully.")
            return redirect('student_detail_from_url', query=student.student_id)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = StudentForm(instance=student)
    
    context = {
        'form': form,
        'student': student,
        'title': f'Edit Student: {student.name}',
        'user_role': request.session.get('user_role'),
    }
    return render(request, 'hostel_app/edit_student.html', context)

@role_required(['viewer', 'editor'])

def total_students_list(request):
    # Use normal_students manager
    students = Student.normal_students.all().order_by('name')
    students, search_id, search_year = _filter_students_and_exclude_staff(request, students)
    context = {
        'students': students,
        'title': 'Total Students',
        'search_id': search_id,
        'search_year': search_year,
        'YEAR_CHOICES': Student.YEAR_CHOICES,
        'user_role': request.session.get('user_role'),
    }
    return render(request, 'hostel_app/student_list.html', context)

@role_required(['viewer', 'editor'])
def present_students_list(request):
    # Use normal_students manager
    students = Student.normal_students.filter(status='present').order_by('name')
    students, search_id, search_year = _filter_students_and_exclude_staff(request, students)
    context = {
        'students': students,
        'title': 'Present Students',
        'search_id': search_id,
        'search_year': search_year,
        'YEAR_CHOICES': Student.YEAR_CHOICES,
        'user_role': request.session.get('user_role'),
    }
    return render(request, 'hostel_app/student_list.html', context)

@role_required(['viewer', 'editor'])
def leave_students_list(request):
    # Use normal_students manager
    students = Student.normal_students.filter(status='leave').order_by('name')
    students, search_id, search_year = _filter_students_and_exclude_staff(request, students)
    context = {
        'students': students,
        'title': 'Students on Leave',
        'search_id': search_id,
        'search_year': search_year,
        'YEAR_CHOICES': Student.YEAR_CHOICES,
        'user_role': request.session.get('user_role'),
    }
    return render(request, 'hostel_app/student_list.html', context)


@role_required(['viewer', 'editor'])
def outing_students_list(request):
    # Use normal_students manager
    students = Student.normal_students.filter(status='outing').order_by('name')
    students, search_id, search_year = _filter_students_and_exclude_staff(request, students)
    context = {
        'students': students,
        'title': 'Students on Outing',
        'search_id': search_id,
        'search_year': search_year,
        'YEAR_CHOICES': Student.YEAR_CHOICES,
        'user_role': request.session.get('user_role'),
    }
    return render(request, 'hostel_app/student_list.html', context)

@role_required(['viewer', 'editor'])
def yearwise_student_data(request):
    # Use normal_students manager for aggregate counts
    year_data = Student.normal_students.values('year').annotate(
        total_count=Count('student_id'),
        present_count=Count(Case(When(status='present', then=1), output_field=IntegerField())),
        leave_count=Count(Case(When(status='leave', then=1), output_field=IntegerField())),
        outing_count=Count(Case(When(status='outing', then=1), output_field=IntegerField()))
    ).order_by('year')

    context = {
        'year_data': year_data,
        'title': 'Year-wise Student Data',
        'user_role': request.session.get('user_role'),
    }
    return render(request, 'hostel_app/yearwise_data.html', context)

@role_required(['viewer', 'editor', 'student'])
def student_lookup_view(request, query=None): # Add query as a path parameter
    student = None
    leave_applications = []
    status_logs = []
    
    # Prioritize path parameter if it exists
    search_term = query if query else request.GET.get('query', '').strip()

    logged_in_student_id = request.session.get('student_id')
    user_role = request.session.get('user_role')

    # If a student is logged in with 'student' role, pre-fill their own ID if no search_term
    if not search_term and logged_in_student_id and user_role == 'student':
        search_term = logged_in_student_id

    if search_term: # Use search_term here
        try:
            # Editors/Viewers can search any student (including staff students).
            # Students can only search their own (handled by subsequent logic).
            # Use default manager here, as staff can lookup other staff students.
            student = Student.objects.get(Q(student_id__iexact=search_term)) # Use search_term
        except Student.DoesNotExist:
            # If not found by ID, try name (only if one unique match), again including staff students
            matching_students = Student.objects.filter(Q(name__icontains=search_term)) # Use search_term
            if matching_students.count() == 1:
                student = matching_students.first()
            elif matching_students.count() > 1:
                messages.info(request, f"Multiple students found for '{search_term}'. Please refine your search or use Student ID for exact match.")
                student = None
            else:
                messages.error(request, f"No student found for '{search_term}'. Please try a different ID or name.")

        if student:
            # IMP: If a 'student' role user tries to view someone else's details
            if user_role == 'student' and student.student_id != logged_in_student_id:
                messages.error(request, "You are not authorized to view other students' details.")
                student = None
            else:
                leave_applications = student.leave_applications.all().order_by('-out_time')
                status_logs = student.status_logs.all().order_by('-change_timestamp') # Ensure ordering

    context = {
        'student': student,
        'leave_applications': leave_applications,
        'status_logs': status_logs,
        'query': search_term, # Use search_term for the template
        'title': 'Student Lookup',
        'user_role': request.session.get('user_role'),
    }
    return render(request, 'hostel_app/student_lookup.html', context)

@role_required(['viewer', 'editor'])
def student_list_view(request):
    # Use normal_students manager to get all resident students
    all_students = Student.normal_students.all().order_by('name')
    context = {
        'all_students': all_students,
        'title': 'All Students',
        'user_role': request.session.get('user_role'),
    }
    return render(request, 'hostel_app/student_list.html', context)

def login_view(request):
    """
    Displays the login form.
    """
    if request.session.get('student_pk'):
        user_role = request.session.get('user_role')
        if user_role == 'student':
            return redirect('apply_leave')
        elif user_role in ['viewer', 'editor']:
            return redirect('dashboard')
    return render(request, 'hostel_app/login.html')


def perform_login(request):
    """
    Handles the login attempt by checking Student ID and Name,
    and redirects based on the user's role.
    """
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        name = request.POST.get('name')

        if not student_id or not name:
            messages.error(request, 'Please enter both Student ID and Name.')
            return redirect('login')

        try:
            student = Student.objects.get(student_id__iexact=student_id, name__iexact=name)
            request.session['student_pk'] = student.pk
            request.session['student_name'] = student.name
            request.session['user_role'] = student.role
            request.session['student_id'] = student.student_id

            messages.success(request, f'Welcome, {student.name}! You are now logged in as a {student.role.capitalize()}.')

            if student.role == 'student':
                return redirect('apply_leave')
            elif student.role in ['viewer', 'editor']:
                return redirect('dashboard')
            else:
                messages.error(request, 'Your account has an unrecognised role. Please contact support.')
                request.session.pop('student_pk', None)
                request.session.pop('student_name', None)
                request.session.pop('user_role', None)
                request.session.pop('student_id', None)
                return redirect('login')

        except Student.DoesNotExist:
            messages.error(request, 'Invalid Student ID or Name.')
            return redirect('login')
    return redirect('login')


def logout_view(request):
    """
    Logs out the user by clearing the session.
    """
    request.session.pop('student_pk', None)
    request.session.pop('student_name', None)
    request.session.pop('user_role', None)
    request.session.pop('student_id', None)
    messages.info(request, 'You have been logged out.')
    return redirect('login')

@role_required(['student'])
def apply_leave_view(request):
    student_pk = request.session.get('student_pk')

    if not student_pk:
        messages.warning(request, 'Please log in to apply for leave.')
        return redirect('login')

    student = get_object_or_404(Student, pk=student_pk, role='student')

    # Find the most recent active approved leave for this student (within 24-hour return window)
    active_approved_leave = None
    if student.status != 'present':
        recent_approved_leaves = LeaveApplication.objects.filter(
            student=student,
            status='approved',
            in_time__gte=timezone.now() - timedelta(hours=24)
        ).order_by('-out_time')
        active_approved_leave = recent_approved_leaves.first()

    if request.method == 'POST':
        form = LeaveApplicationForm(request.POST, student=student)
        if form.is_valid():
            # Check for overlapping active leaves before saving
            requested_out_time = form.cleaned_data['out_time']
            requested_in_time = form.cleaned_data['in_time']

            # Check for overlapping approved leaves
            overlapping_approved_leaves_query = Q(
                student=student,
                status='approved',
                out_time__lt=requested_in_time,
                in_time__gt=requested_out_time
            )
            # If student is present, ignore approved leaves that have already started
            if student.status == 'present':
                overlapping_approved_leaves_query &= Q(out_time__gt=timezone.now())

            overlapping_approved_leaves = LeaveApplication.objects.filter(overlapping_approved_leaves_query).exists()

            if overlapping_approved_leaves:
                messages.error(request, 'You have an overlapping APPROVED leave application. Please wait for it to conclude or cancel it before applying for another.')
                # Re-render the form with current data
                context = {
                    'form': form,
                    'student': student,
                    'title': f'Apply for Leave: {student.name}',
                    'user_role': request.session.get('user_role'),
                    'active_approved_leave': active_approved_leave,
                }
                return render(request, 'hostel_app/apply_leave.html', context)
            
            # Check for overlapping pending leaves
            overlapping_pending_leaves_query = Q(
                student=student,
                status='pending',
                out_time__lt=requested_in_time,
                in_time__gt=requested_out_time
            )
            # If student is present, ignore pending leaves that have already started
            if student.status == 'present':
                overlapping_pending_leaves_query &= Q(out_time__gt=timezone.now())

            overlapping_pending_leaves = LeaveApplication.objects.filter(overlapping_pending_leaves_query).exists()

            if overlapping_pending_leaves:
                messages.error(request, 'You have an overlapping PENDING leave application. Please wait for approval/rejection or cancel it.')
                context = {
                    'form': form,
                    'student': student,
                    'title': f'Apply for Leave: {student.name}',
                    'user_role': request.session.get('user_role'),
                    'active_approved_leave': active_approved_leave,
                }
                return render(request, 'hostel_app/apply_leave.html', context)

            leave_application = form.save(commit=False)
            leave_application.student = student
            leave_application.status = 'pending'
            leave_application.save()
            messages.success(request, 'Leave application submitted successfully! It awaits approval.')
            # Redirect to student lookup page for this student, to see the new pending leave
            # --- UPDATED URL NAME HERE ---
            return redirect(reverse('student_detail_from_url', args=[student.student_id]))
        else:
            messages.error(request, 'Please correct the errors in the form.')
    else:
        form = LeaveApplicationForm(student=student)

    context = {
        'form': form,
        'student': student,
        'all_students': Student.normal_students.exclude(pk=student.pk).only('name', 'student_id'),
        'title': f'Apply for Leave: {student.name}',
        'user_role': request.session.get('user_role'),
        'active_approved_leave': active_approved_leave, 
        'is_restricted': student.gender == 'F' and student.year not in ['E3', 'E4'],
    }
    return render(request, 'hostel_app/apply_leave.html', context)

# NEW VIEW: To display the QR code page for a student


@role_required(['viewer', 'editor'])
def leave_management_view(request):
    # Only show leave applications from 'student' role (resident) students
    all_leave_applications = LeaveApplication.objects.filter(student__role='student').order_by('-out_time')
    context = {
        'all_leave_applications': all_leave_applications,
        'title': 'Leave Management',
        'user_role': request.session.get('user_role'),
        'current_time': timezone.now(),
    }
    return render(request, 'hostel_app/leave_management.html', context)

@role_required(['editor'])
def update_leave_status(request, leave_pk):
    if request.method == 'POST':
        # Ensure only leave applications from 'student' role (resident) students can be updated
        leave_application = get_object_or_404(LeaveApplication, pk=leave_pk, student__role='student')
        action = request.POST.get('action')

        if action == 'approve':
            leave_application.status = 'approved'
            leave_application.save()
            
            # --- NEW: Automatically update student status upon approval ---
            student = leave_application.student
            new_status = 'outing' if leave_application.leave_type == 'outing' else 'leave'
            
            if student.status != new_status:
                student.status = new_status
                student.save()
                
                # Log the status change
                StudentStatusLog.objects.create(
                    student=student,
                    current_status=new_status,
                    log_type='manual', # Marking as manual/system since it's triggered by approval
                )

            messages.success(request, f'Leave for {leave_application.student.name} departing {leave_application.out_time.date()} has been APPROVED and status updated to {new_status}.')

        elif action == 'reject':
            leave_application.status = 'rejected'
            leave_application.save()
            messages.info(request, f'Leave for {leave_application.student.name} departing {leave_application.out_time.date()} has been REJECTED.')

        else:
            messages.error(request, 'Invalid action for leave update.')

    return redirect('leave_management')


@role_required(['viewer', 'editor'])
def biometric_track_view(request):
    """
    Shows real-time biometric tracking:
    - Movement tracker for students on approved leave
    - Recent raw AttendanceLog punches from eSSL devices
    """
    from essl_app.models import AttendanceLog, BiometricDevice
    from django.utils import timezone
    import datetime

    query = request.GET.get('q', '').strip()
    punch_filter = request.GET.get('punch', '')

    # 1. --- Approved Leave Movement Status ---
    # Find students who are either currently 'on leave'/'outing' 
    # OR have an approved leave starting today or ongoing.
    today = timezone.now().date()
    on_leave_students = Student.normal_students.filter(
        Q(status__in=['leave', 'outing'])
    ).distinct().order_by('name')

    movement_data = []
    for student in on_leave_students:
        # Get the most recent approved leave application
        active_leave = student.leave_applications.filter(
            status='approved',
            out_time__date__lte=today,
            in_time__date__gte=today
        ).order_by('-out_time').first()
        
        if not active_leave:
            continue

        # Look for punches for this student starting from their planned out_time (with 12 hour buffer before)
        punch_start_time = active_leave.out_time - datetime.timedelta(minutes=60)
        numeric_id = student.student_id.lstrip('N').lstrip('n').lstrip('0')
        
        student_punches = AttendanceLog.objects.filter(
            Q(user_id__icontains=numeric_id) | Q(user_id__icontains=student.student_id),
            timestamp__gte=punch_start_time
        ).order_by('timestamp')
        
        punch_info = {
            '2': None, # Hostel Out
            '1': None, # Gate Out
            '0': None, # Gate In
            '3': None  # Hostel In
        }
        
        last_found_time = punch_start_time
        
        # 1. Hostel Out (2)
        h_out = student_punches.filter(punch_state='2', timestamp__gte=last_found_time).first()
        if h_out:
            punch_info['2'] = h_out.timestamp
            last_found_time = h_out.timestamp
            
            # 2. Gate Out (1) - must be after Hostel Out
            g_out = student_punches.filter(punch_state='1', timestamp__gte=last_found_time).first()
            if g_out:
                punch_info['1'] = g_out.timestamp
                last_found_time = g_out.timestamp
                
                # 3. Gate In (0) - must be after Gate Out
                g_in = student_punches.filter(punch_state='0', timestamp__gte=last_found_time).first()
                if g_in:
                    punch_info['0'] = g_in.timestamp
                    last_found_time = g_in.timestamp
                    
                    # 4. Hostel In (3) - must be after Gate In
                    h_in = student_punches.filter(punch_state='3', timestamp__gte=last_found_time).first()
                    if h_in:
                        punch_info['3'] = h_in.timestamp

        movement_data.append({
            'student': student,
            'leave': active_leave,
            'punches': punch_info,
            'passed_h_out': punch_info['2'],
            'passed_g_out': punch_info['1'],
            'passed_g_in': punch_info['0'],
            'passed_h_in': punch_info['3'],
        })

    # 2. --- Recent Punch Log (Original Logic) ---
    # Base queryset - last 200 entries
    logs = AttendanceLog.objects.order_by('-timestamp')[:200]

    # Build a lookup: last 4+ digits of student_id -> Student
    all_students = Student.objects.all()
    student_map = {}
    for s in all_students:
        numeric = s.student_id.lstrip('N').lstrip('n').lstrip('0') or s.student_id
        student_map[numeric] = s

    # Annotate logs with student info and device info
    device_map = {d.ip_address: d.name for d in BiometricDevice.objects.all()}
    
    enriched_logs = []
    for log in logs:
        uid = log.user_id.lstrip('0') or log.user_id
        student = student_map.get(uid)
        device_name = device_map.get(log.device_ip, log.device_ip or "Unknown")
        
        enriched_logs.append({
            'log': log,
            'student': student,
            'device_name': device_name,
        })

    # Apply filters to logs
    if query:
        enriched_logs = [
            e for e in enriched_logs
            if query.lower() in (e['student'].name.lower() if e['student'] else '')
            or query.lower() in (e['student'].student_id.lower() if e['student'] else '')
            or query in e['log'].user_id
        ]
    if punch_filter:
        enriched_logs = [e for e in enriched_logs if e['log'].punch_state == punch_filter]

    # Current status summary
    present_count = Student.objects.filter(status='present', role='student').count()
    leave_count = Student.objects.filter(status='leave', role='student').count()
    outing_count = Student.objects.filter(status='outing', role='student').count()

    context = {
        'title': 'Biometric Tracking',
        'movement_data': movement_data,
        'enriched_logs': enriched_logs,
        'query': query,
        'punch_filter': punch_filter,
        'user_role': request.session.get('user_role'),
        'present_count': present_count,
        'leave_count': leave_count,
        'outing_count': outing_count,
    }
    return render(request, 'hostel_app/biometric_track.html', context)


