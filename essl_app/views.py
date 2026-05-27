import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
import socket

from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import make_aware, get_current_timezone
from django.utils import timezone
from django.contrib import messages
from .models import AttendanceLog
from hostel_app.models import Student, StudentStatusLog, LeaveApplication
from hostel_app.views import role_required

@csrf_exempt
def iclock_cdata(request):
    # Enhanced logging for diagnostics
    client_ip = request.META.get('REMOTE_ADDR')
    print(f"\n!!! [BIOMETRIC DATA RECEIVED] !!!")
    print(f"IP: {client_ip} | Method: {request.method}")
    print(f"GET Params: {request.GET}")
    
    if request.method == 'POST':
        table = request.GET.get('table', '').upper()
        if table != 'ATTLOG':
            print(f"DEBUG: Skipping table '{table}' - not ATTLOG")
            return HttpResponse("OK\n")
            
        # Get client IP
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            client_ip = x_forwarded_for.split(',')[0]
        else:
            client_ip = request.META.get('REMOTE_ADDR')

        from .models import BiometricDevice
        device = BiometricDevice.objects.filter(ip_address=client_ip).first()
        
        # Parse the raw data from the device
        try:
            raw_data = request.body.decode('utf-8', errors='replace')
        except Exception as e:
            print(f"ERROR decoding body: {e}")
            return HttpResponse("OK\n")

        lines = raw_data.split('\n')
        
        device_name = device.name if device else 'Unknown Device'
        print(f"DEBUG: Processing {len(lines)} lines from {device_name} ({client_ip})")
        # Print first few bytes/chars for debugging
        print(f"DEBUG: Raw sample: {raw_data[:100].replace('\t', '[TAB]').replace('\n', '[NL]')}...")
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            parts = line.split('\t')
            if len(parts) >= 4:
                user_id = parts[0].strip()
                timestamp_str = parts[1]
                # Default to what device sends, but override if we know the device IP location
                punch_state = parts[3]
                if device:
                    punch_state = device.location_type
                
                try:
                    naive_dt = datetime.datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    aware_dt = make_aware(naive_dt, timezone=get_current_timezone())
                    
                    # Prevent duplicates
                    time_threshold_start = aware_dt - datetime.timedelta(seconds=60)
                    time_threshold_end = aware_dt + datetime.timedelta(seconds=60)
                    
                    recent_log = AttendanceLog.objects.filter(
                        user_id=user_id,
                        punch_state=punch_state,
                        timestamp__gte=time_threshold_start,
                        timestamp__lte=time_threshold_end
                    ).exists()
                    
                    if not recent_log:
                        AttendanceLog.objects.create(
                            user_id=user_id, 
                            timestamp=aware_dt,
                            punch_state=punch_state,
                            device_ip=client_ip
                        )
                        
                        # --- Dynamic Status Update Logic ---
                        try:
                            # The eSSL device sends '210190', but DB has 'N210190'
                            student = Student.objects.get(student_id__endswith=user_id)
                            
                            new_status = student.status
                            current_time = timezone.now()
                            
                            # OUT states: '1' (Gate Out), '2' (Hostel Out)
                            if punch_state in ['1', '2']:
                                # Only change status if they are 'present'
                                if student.status == 'present':
                                    # Check for an active approved leave
                                    # Allow a window (e.g., within 2 hours of out_time)
                                    active_leave = LeaveApplication.objects.filter(
                                        student=student,
                                        status='approved',
                                        out_time__lte=current_time + datetime.timedelta(hours=2),
                                        in_time__gte=current_time - datetime.timedelta(hours=2)
                                    ).order_by('-out_time').first()
                                    
                                    if active_leave:
                                        new_status = 'outing' if active_leave.leave_type == 'outing' else 'leave'
                                    else:
                                        # Unauthorized exit? For now, maybe just don't change status or log it.
                                        pass
                                        
                            # IN states: '0' (Gate In), '3' (Hostel In)
                            # Per user request: Gate In (0) is good, but keep tracking 
                            # until Hostel In (3) is punched.
                            elif punch_state == '3':
                                if student.status in ['outing', 'leave']:
                                    new_status = 'present'
                                    
                                    # Cleanup: Remove only the PREVIOUS logs of this trip (0,1,2) 
                                    # but KEEP the '3' (Hostel In) so it shows as the "Present" state in the log table
                                    numeric_id = student.student_id.lstrip('N').lstrip('n').lstrip('0')
                                    AttendanceLog.objects.filter(
                                        Q(user_id__icontains=numeric_id) | Q(user_id__icontains=student.student_id),
                                        punch_state__in=['0', '1', '2']
                                    ).delete()
                            
                            elif punch_state == '0':
                                # Gate In - we log it but DON'T change status to 'present' 
                                pass
                                
                            elif punch_state in ['1', '2']:
                                # New trip starting - clear any old "Hostel In" logs for this student
                                numeric_id = student.student_id.lstrip('N').lstrip('n').lstrip('0')
                                AttendanceLog.objects.filter(
                                    Q(user_id__icontains=numeric_id) | Q(user_id__icontains=student.student_id),
                                    punch_state='3'
                                ).delete()
                                
                                if punch_state == '1': new_status = 'outing'
                                elif punch_state == '2': new_status = 'leave'
                                    
                            # Update student status if it changed
                            if new_status != student.status:
                                student.status = new_status
                                student.save()
                                
                                # Log the status change
                                StudentStatusLog.objects.create(
                                    student=student,
                                    current_status=new_status,
                                    log_type='biometric',
                                )
                                
                        except Student.DoesNotExist:
                            print(f"Student not found for biometric user_id: {user_id}")
                        except Student.MultipleObjectsReturned:
                            print(f"Multiple students found matching user_id: {user_id}. Need exact match logic.")
                            
                except Exception as e:
                    print(f"Error parsing log line '{line}': {e}")
                    
        return HttpResponse("OK\n")
    return HttpResponse("OK\n")

@csrf_exempt
def iclock_getrequest(request):
    sn = request.GET.get('SN', 'Unknown')
    ip = request.META.get('REMOTE_ADDR')
    print(f"\n!!! [BIOMETRIC HANDSHAKE] !!! SN: {sn} | IP: {ip}")
    
    # Standard ADMS response to tell the device to start syncing
    # Registry=1 tells the device it's registered and should proceed with uploads
    response_text = "OK\nRegistry=1\n"
    return HttpResponse(response_text)

@csrf_exempt
def iclock_devicecmd(request):
    return HttpResponse("OK\n")

@role_required(['editor'])
def device_config(request):
    from .models import BiometricDevice
    devices = BiometricDevice.objects.all()
    
    if request.method == 'POST':
        name = request.POST.get('name')
        ip_address = request.POST.get('ip_address')
        location_type = request.POST.get('location_type')
        device_id = request.POST.get('device_id')
        
        if device_id: # Edit
            device = get_object_or_404(BiometricDevice, pk=device_id)
            device.name = name
            device.ip_address = ip_address
            device.location_type = location_type
            device.save()
            messages.success(request, f"Device {name} updated.")
        else: # Add
            BiometricDevice.objects.create(
                name=name,
                ip_address=ip_address,
                location_type=location_type
            )
            messages.success(request, f"Device {name} added.")
        return redirect('device_config')

    context = {
        'devices': devices,
        'title': 'Biometric Device Configuration',
        'location_choices': AttendanceLog.STAGE_CHOICES,
        'user_role': request.session.get('user_role'),
    }
    return render(request, 'essl_app/device_config.html', context)

@role_required(['editor'])
def delete_device(request, device_id):
    from .models import BiometricDevice
    device = get_object_or_404(BiometricDevice, pk=device_id)
    name = device.name
    device.delete()
    messages.success(request, f"Device {name} deleted.")
    return redirect('ip_assignment')

@role_required(['editor'])
def ip_assignment(request):
    from .models import BiometricDevice
    devices = BiometricDevice.objects.all()
    
    if request.method == 'POST':
        name = request.POST.get('name')
        ip_address = request.POST.get('ip_address')
        location_type = request.POST.get('location_type')
        device_id = request.POST.get('device_id')
        
        if device_id: # Edit
            device = get_object_or_404(BiometricDevice, pk=device_id)
            device.name = name
            device.ip_address = ip_address
            device.location_type = location_type
            device.save()
            messages.success(request, f"Device {name} updated.")
        else: # Add
            BiometricDevice.objects.create(
                name=name,
                ip_address=ip_address,
                location_type=location_type
            )
            messages.success(request, f"Device {name} added.")
        return redirect('ip_assignment')

    context = {
        'devices': devices,
        'title': 'IP & Location Assignment',
        'location_choices': AttendanceLog.STAGE_CHOICES,
        'user_role': request.session.get('user_role'),
    }
    return render(request, 'essl_app/ip_assignment.html', context)

@role_required(['editor'])
def test_device(request, device_id):
    from .models import BiometricDevice
    device = get_object_or_404(BiometricDevice, pk=device_id)
    
    # Try to connect to port 80 (HTTP), 4370 (ZK Biometric), or 8000 (Custom)
    # Most ZK devices have a web interface on 80.
    target_ports = [80, 4370, 8000]
    is_online = False
    found_port = None
    
    for port in target_ports:
        try:
            with socket.create_connection((device.ip_address, port), timeout=2):
                is_online = True
                found_port = port
                break
        except (socket.timeout, ConnectionRefusedError, OSError):
            continue
            
    if is_online:
        device.save() # Updates last_seen due to auto_now=True
        return JsonResponse({
            'status': 'online',
            'message': f'Device is ONLINE (Port {found_port})',
            'last_seen': device.last_seen.strftime('%Y-%m-%d %H:%M:%S')
        })
    else:
        return JsonResponse({
            'status': 'offline',
            'message': 'Device is OFFLINE or unreachable'
        })

@role_required(['editor'])
def quick_setup_devices(request):
    from .models import BiometricDevice
    
    setup_data = [
        ('192.168.137.70', '2', 'Hostel Out'),
        ('192.168.137.71', '1', 'Gate Out'),
        ('192.168.137.72', '0', 'Gate In'),
        ('192.168.137.73', '3', 'Hostel In'),
    ]
    
    added_count = 0
    updated_count = 0
    
    for ip, loc_type, name in setup_data:
        device, created = BiometricDevice.objects.update_or_create(
            ip_address=ip,
            defaults={'location_type': loc_type, 'name': name}
        )
        if created:
            added_count += 1
        else:
            updated_count += 1
            
    messages.success(request, f"Quick Setup Complete: {added_count} added, {updated_count} updated.")
    return redirect('ip_assignment')
@role_required(['viewer', 'editor'])
def api_biometric_logs(request):
    """
    API endpoint for AJAX updates
    """
    from essl_app.models import AttendanceLog, BiometricDevice
    from hostel_app.models import Student, LeaveApplication
    from django.db.models import Q
    from django.utils import timezone
    import datetime
    
    # 1. Logs Data
    logs = AttendanceLog.objects.order_by('-timestamp')[:50]
    device_map = {d.ip_address: d.name for d in BiometricDevice.objects.all()}
    student_map = {s.student_id.lstrip('N').lstrip('n').lstrip('0'): s for s in Student.objects.all()}
    
    log_data = []
    for log in logs:
        uid = log.user_id.lstrip('0') or log.user_id
        student = student_map.get(uid)
        log_data.append({
            'student_name': student.name if student else f"Unknown",
            'student_id': student.student_id if student else log.user_id,
            'device_name': device_map.get(log.device_ip, log.device_ip or "Unknown"),
            'punch_type': log.get_punch_state_display(),
            'punch_code': log.punch_state,
            'status': student.status if student else "present",
            'timestamp': log.timestamp.strftime('%H:%M:%S'),
        })

    # 2. Movement Data (for real-time lights)
    today = timezone.now().date()
    on_leave_students = Student.objects.filter(
        status__in=['leave', 'outing'],
        role='student'
    ).distinct()

    movement_data = []
    for student in on_leave_students:
        active_leave = student.leave_applications.filter(
            status='approved',
            out_time__date__lte=today,
            in_time__date__gte=today
        ).order_by('-out_time').first()
        
        if not active_leave: continue

        numeric_id = student.student_id.lstrip('N').lstrip('n').lstrip('0')
        punch_start = active_leave.out_time - datetime.timedelta(minutes=60)
        
        student_punches = AttendanceLog.objects.filter(
            Q(user_id__icontains=numeric_id) | Q(user_id__icontains=student.student_id),
            timestamp__gte=punch_start
        ).order_by('timestamp')

        # Sequential Logic
        p_info = {'2': None, '1': None, '0': None, '3': None}
        last_t = punch_start
        
        h_out = student_punches.filter(punch_state='2', timestamp__gte=last_t).first()
        if h_out:
            p_info['2'] = h_out.timestamp.strftime('%H:%M')
            last_t = h_out.timestamp
            g_out = student_punches.filter(punch_state='1', timestamp__gte=last_t).first()
            if g_out:
                p_info['1'] = g_out.timestamp.strftime('%H:%M')
                last_t = g_out.timestamp
                g_in = student_punches.filter(punch_state='0', timestamp__gte=last_t).first()
                if g_in:
                    p_info['0'] = g_in.timestamp.strftime('%H:%M')
                    last_t = g_in.timestamp
                    h_in = student_punches.filter(punch_state='3', timestamp__gte=last_t).first()
                    if h_in:
                        p_info['3'] = h_in.timestamp.strftime('%H:%M')

        movement_data.append({
            'sid': student.student_id,
            'status': student.status,
            'h_out': p_info['2'],
            'g_out': p_info['1'],
            'g_in': p_info['0'],
            'h_in': p_info['3']
        })

    return JsonResponse({
        'logs': log_data,
        'movements': movement_data
    })

@csrf_exempt
def debug_log_all(request, path=''):
    print(f"!!! CATCH-ALL LOG !!! Path: /{path} | Method: {request.method} | GET: {request.GET} | IP: {request.META.get('REMOTE_ADDR')}")
    return HttpResponse("OK\n")
