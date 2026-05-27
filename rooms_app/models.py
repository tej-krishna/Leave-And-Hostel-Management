from django.db import models
from hostel_app.models import Student, HOSTEL_CHOICES # Import Student and HOSTEL_CHOICES

class Floor(models.Model):
    hostel = models.CharField(max_length=5, choices=HOSTEL_CHOICES, default='I1')
    floor_number = models.IntegerField()
    name = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.hostel} - Floor {self.floor_number}"

    class Meta:
        unique_together = ('hostel', 'floor_number')
        ordering = ['hostel', 'floor_number']

class Room(models.Model):
    floor = models.ForeignKey(Floor, related_name='rooms', on_delete=models.CASCADE)
    room_number = models.IntegerField()
    capacity = models.IntegerField(default=0)
    is_disabled = models.BooleanField(default=False)

    class Meta:
        unique_together = ('floor', 'room_number')
        ordering = ['room_number']

    def __str__(self):
        return f"Room {self.room_number} (Floor {self.floor.floor_number})"

    def is_full(self):
        # A room is considered full if the number of 'student' role students
        # currently in the room equals or exceeds its capacity.
        # This uses the 'normal_students' manager defined in the Student model.
        occupied_count = self.allotted_students.filter(role='student').count()
        return occupied_count >= self.capacity

    def get_occupied_beds_count(self):
        # Helper to get the count of 'student' role students
        return self.allotted_students.filter(role='student').count()

    def get_available_beds_count(self):
        return self.capacity - self.get_occupied_beds_count()