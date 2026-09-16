from django.test import TestCase, RequestFactory
from django.utils import timezone

from .models import AttendanceLog, BiometricDevice
from .views import iclock_cdata
from hostel_app.models import Student


def make_student(**kwargs):
    defaults = dict(
        name='Test Student',
        student_id='N300001',
        mobile_number='9000000003',
        year='E1',
        branch='CSE',
        role='student',
    )
    defaults.update(kwargs)
    return Student.objects.create(**defaults)


class IclockCdataTests(TestCase):
    """
    Exercises the unauthenticated /iclock/cdata ingestion endpoint directly,
    since real eSSL hardware is not available in this environment. These
    tests pin the behavior fixed during the audit:
      - a missing `Q` import made the punch_state == '3' (Hostel In) branch
        raise NameError, silently leaving returning students marked as
        'leave'/'outing' forever (P1, reproduced and fixed).
      - the endpoint identified devices by client IP but trusted a
        client-supplied X-Forwarded-For header for it, letting anyone spoof
        a configured device's IP over plain HTTP (P1, fixed by using
        REMOTE_ADDR only).
    """

    def setUp(self):
        self.rf = RequestFactory()

    def _post_attlog(self, body, remote_addr='127.0.0.1', extra_headers=None):
        headers = extra_headers or {}
        req = self.rf.post(
            '/iclock/cdata?table=ATTLOG',
            data=body,
            content_type='text/plain',
            REMOTE_ADDR=remote_addr,
            **headers,
        )
        return iclock_cdata(req)

    def test_hostel_in_punch_resets_status_to_present(self):
        student = make_student(status='leave')
        ts = timezone.localtime().strftime('%Y-%m-%d %H:%M:%S')
        # user_id '300001' matches student_id 'N300001' via endswith lookup
        body = f"300001\t{ts}\t0\t3\t0\t0\t0"

        response = self._post_attlog(body)

        self.assertEqual(response.status_code, 200)
        student.refresh_from_db()
        self.assertEqual(student.status, 'present')

    def test_hostel_out_punch_marks_leave_when_cleared_for_departure(self):
        """
        As of the leave-workflow feature, status='approved' alone is no
        longer sufficient to authorize a biometric departure - the leave
        must also have passed Caretaker ID verification
        (current_stage=CLEARED_FOR_DEPARTURE). See
        hostel_app.tests.LeaveWorkflowEndToEndTests
        .test_biometric_gate_out_is_blocked_until_caretaker_clears_it for the
        negative case (approved but not yet verified -> departure blocked).
        """
        from hostel_app.models import LeaveApplication
        from datetime import timedelta

        student = make_student(status='present')
        leave = LeaveApplication.objects.create(
            student=student,
            leave_type='leave',
            reason='Test',
            out_time=timezone.now(),
            in_time=timezone.now() + timedelta(hours=5),
            status='approved',
            current_stage=LeaveApplication.STAGE_CLEARED_FOR_DEPARTURE,
        )
        ts = timezone.localtime().strftime('%Y-%m-%d %H:%M:%S')
        body = f"300001\t{ts}\t0\t2\t0\t0\t0"

        self._post_attlog(body)

        student.refresh_from_db()
        leave.refresh_from_db()
        self.assertEqual(student.status, 'leave')
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_OUT)
        self.assertIsNotNone(leave.gate_out_at)

    def test_duplicate_gate_out_punch_does_not_duplicate_the_departure_record(self):
        from hostel_app.models import LeaveApplication, LeaveApprovalHistory
        from datetime import timedelta

        student = make_student(status='present')
        leave = LeaveApplication.objects.create(
            student=student, leave_type='leave', reason='Test',
            out_time=timezone.now(), in_time=timezone.now() + timedelta(hours=5),
            status='approved', current_stage=LeaveApplication.STAGE_CLEARED_FOR_DEPARTURE,
        )
        # Hostel-Out, then (per real ADMS sequencing) Gate-Out moments later -
        # both are "out states" for the same trip and must not double-record
        # gate_out_at or create two GATE_OUT history rows.
        t1 = timezone.localtime()
        self._post_attlog(f"300001\t{t1.strftime('%Y-%m-%d %H:%M:%S')}\t0\t2\t0\t0\t0")
        t2 = t1 + timedelta(minutes=2)
        self._post_attlog(f"300001\t{t2.strftime('%Y-%m-%d %H:%M:%S')}\t0\t1\t0\t0\t0")

        leave.refresh_from_db()
        self.assertEqual(leave.current_stage, LeaveApplication.STAGE_OUT)
        self.assertEqual(
            LeaveApprovalHistory.objects.filter(leave=leave, action=LeaveApprovalHistory.ACTION_GATE_OUT).count(),
            1,
        )

    def test_duplicate_punch_within_60_seconds_is_not_double_logged(self):
        make_student()
        ts_dt = timezone.localtime()
        ts = ts_dt.strftime('%Y-%m-%d %H:%M:%S')
        body = f"300001\t{ts}\t0\t0\t0\t0\t0"

        self._post_attlog(body)
        self._post_attlog(body)  # identical replayed punch

        self.assertEqual(AttendanceLog.objects.filter(user_id='300001').count(), 1)

    def test_spoofed_x_forwarded_for_does_not_impersonate_a_configured_device(self):
        device = BiometricDevice.objects.create(
            name='Hostel Out Main Gate',
            ip_address='192.168.137.70',
            location_type='2',
        )
        make_student(status='present')
        ts = timezone.localtime().strftime('%Y-%m-%d %H:%M:%S')
        # Attacker's real REMOTE_ADDR is 10.0.0.9; they forge X-Forwarded-For
        # to claim they are the trusted device at 192.168.137.70.
        body = f"300001\t{ts}\t0\t1\t0\t0\t0"
        self._post_attlog(body, remote_addr='10.0.0.9', extra_headers={
            'HTTP_X_FORWARDED_FOR': '192.168.137.70',
        })

        log = AttendanceLog.objects.get(user_id='300001')
        # The log must be attributed to the real socket peer, not the
        # attacker-supplied header, and must NOT inherit the trusted
        # device's configured location_type ('2' / Hostel Out).
        self.assertEqual(log.device_ip, '10.0.0.9')
        self.assertNotEqual(log.punch_state, device.location_type)
