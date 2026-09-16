from hostel_app.models import Student
from django.db.models import Count

print(f"Total Students: {Student.objects.count()}")
print(f"I3 Students: {Student.objects.filter(room__floor__hostel='I3').count()}")
print(f"Leave Status: {Student.objects.filter(status='leave').count()}")
print(f"Outing Status: {Student.objects.filter(status='outing').count()}")

print("\nBatch/Gender/Hostel Breakdown:")
batches = ['E1', 'E2', 'E3', 'E4', 'P1', 'P2']
for b in batches:
    for g in ['M', 'F']:
        count = Student.objects.filter(year=b, gender=g).count()
        example_student = Student.objects.filter(year=b, gender=g).first()
        room_example = example_student.room if example_student else None
        hostel = room_example.floor.hostel if room_example else "None"
        floor = room_example.floor.floor_number if room_example else "None"
        print(f"{b} {g}: {count} students -> Assigned to {hostel} Floor {floor}")
