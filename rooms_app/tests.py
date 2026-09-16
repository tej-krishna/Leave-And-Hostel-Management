from django.test import TestCase
from django.urls import reverse

from .models import Floor, Room
from hostel_app.models import Student


def make_student(**kwargs):
    defaults = dict(
        name='Test Student',
        student_id='N200001',
        mobile_number='9000000002',
        year='E1',
        branch='CSE',
        role='student',
    )
    defaults.update(kwargs)
    return Student.objects.create(**defaults)


class RoomAllocationTests(TestCase):
    def setUp(self):
        self.floor = Floor.objects.create(hostel='I1', floor_number=1)
        self.room = Room.objects.create(floor=self.floor, room_number=101, capacity=1)
        session = self.client.session
        session['user_role'] = 'editor'
        session.save()

    def _allot(self, student):
        return self.client.post(
            reverse('allot_student_to_room', args=[self.room.pk]),
            {'student_id': student.pk},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

    def test_allotment_fills_room_and_is_reflected_in_capacity_helpers(self):
        student = make_student(student_id='N200001')
        response = self._allot(student)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.room.refresh_from_db()
        self.assertTrue(self.room.is_full())
        self.assertEqual(self.room.get_available_beds_count(), 0)

    def test_room_at_capacity_rejects_further_allotment(self):
        first = make_student(student_id='N200001', name='First', mobile_number='9000000011')
        first.room = self.room
        first.save()

        second = make_student(student_id='N200002', name='Second', mobile_number='9000000012')
        response = self._allot(second)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        second.refresh_from_db()
        self.assertIsNone(second.room)

    def test_disabled_room_rejects_allotment(self):
        self.room.is_disabled = True
        self.room.save()
        student = make_student(student_id='N200003')
        response = self._allot(student)
        self.assertEqual(response.status_code, 400)
        self.assertIn('disabled', response.json()['error'].lower())

    def test_student_already_allotted_cannot_be_allotted_again(self):
        other_room = Room.objects.create(floor=self.floor, room_number=102, capacity=2)
        student = make_student(student_id='N200004')
        student.room = other_room
        student.save()

        response = self._allot(student)
        self.assertEqual(response.status_code, 400)
        self.assertIn('already allotted', response.json()['error'].lower())
        student.refresh_from_db()
        self.assertEqual(student.room_id, other_room.pk)

    def test_unallot_frees_the_room(self):
        student = make_student(student_id='N200005')
        student.room = self.room
        student.save()

        response = self.client.post(reverse('unallot_student_from_room', args=[student.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        student.refresh_from_db()
        self.assertIsNone(student.room)
        self.room.refresh_from_db()
        self.assertFalse(self.room.is_full())
