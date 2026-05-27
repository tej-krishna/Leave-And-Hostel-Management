import random
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date
from hostel_app.models import Student, HOSTEL_CHOICES
from rooms_app.models import Room, Floor

class Command(BaseCommand):
    help = 'Populates the database with 6600 dummy students based on specific batch and allocation rules.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing students before populating',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write("Clearing existing students...")
            Student.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Existing students cleared."))

        # 1. Configuration
        BATCHES = [
            {'name': 'E4', 'prefix': 'N21', 'birth_year': 2005, 'm_count': 640, 'f_count': 460},
            {'name': 'E3', 'prefix': 'N22', 'birth_year': 2006, 'm_count': 380, 'f_count': 720},
            {'name': 'E2', 'prefix': 'N23', 'birth_year': 2007, 'm_count': 380, 'f_count': 720},
            {'name': 'E1', 'prefix': 'N24', 'birth_year': 2008, 'm_count': 380, 'f_count': 720},
            {'name': 'P2', 'prefix': 'N25', 'birth_year': 2009, 'm_count': 380, 'f_count': 720},
            {'name': 'P1', 'prefix': 'N26', 'birth_year': 2010, 'm_count': 380, 'f_count': 720},
        ]

        ALLOCATION_MAP = {
            ('E1', 'M'): ('I1', 0),
            ('E2', 'M'): ('I1', 1),
            ('E3', 'M'): ('I1', 2),
            ('E4', 'M'): ('I1', 3),
            ('P1', 'M'): ('I2', 1),
            ('P2', 'M'): ('I2', 2),
            ('P1', 'F'): ('K4', 0),
            ('P2', 'F'): ('K4', 1),
            ('E1', 'F'): ('K3', 0),
            ('E2', 'F'): ('K3', 1),
            ('E3', 'F'): ('K2', 0),
            ('E4', 'F'): ('K2', 1),
        }

        BLOOD_GROUPS = ['B+', 'B-', 'A-', 'A+', 'O-', 'O+', 'AB-', 'AB+']
        
        FIRST_NAMES_M = ["Rahul", "Sandeep", "Kiran", "Vijay", "Anil", "Suresh", "Ramesh", "Prasad", "Naresh", "Sai", "Vamsi", "Praveen", "Ravi", "Mahesh", "Ganesh", "Kartik", "Harish", "Ashok", "Varun", "Arjun", "Vikram", "Siddharth", "Nikhil", "Aakash", "Rohit"]
        FIRST_NAMES_F = ["Sneha", "Anjali", "Priya", "Lakshmi", "Divya", "Sravani", "Keerthi", "Meghana", "Deepika", "Shanthi", "Swathi", "Pallavi", "Ramya", "Sindhu", "Jyothi", "Amruta", "Vani", "Sunitha", "Geetha", "Kavya", "Anusha", "Bhavana", "Meenakshi", "Siri", "Navya"]
        LAST_NAMES = ["Reddy", "Yadav", "Sharma", "Verma", "Rao", "Chowdhary", "Patel", "Singh", "Das", "Nair", "Iyer", "Kulkarni", "Gupta", "Jain", "Mishra", "Pandey", "Varma", "Goud", "Babu", "Naidu"]

        # 2. Cache Rooms
        self.stdout.write("Fetching rooms...")
        all_rooms = Room.objects.select_related('floor').exclude(floor__hostel='I3')
        room_registry = {} # (hostel, floor_num) -> [list of rooms]
        hostel_registry = {} # hostel -> [list of all rooms in hostel]

        for room in all_rooms:
            key = (room.floor.hostel, room.floor.floor_number)
            if key not in room_registry:
                room_registry[key] = []
            room_registry[key].append(room)
            
            h_key = room.floor.hostel
            if h_key not in hostel_registry:
                hostel_registry[h_key] = []
            hostel_registry[h_key].append(room)

        # Track room occupancy manually to avoid querying DB constantly
        occupancy_tracker = {room.id: room.get_occupied_beds_count() for room in all_rooms}

        # 3. Helper Functions
        used_mobiles = set(Student.objects.values_list('mobile_number', flat=True))
        
        def generate_mobile():
            while True:
                num = "9" + "".join([str(random.randint(0, 9)) for _ in range(9)])
                if num not in used_mobiles:
                    used_mobiles.add(num)
                    return num

        # 4. Generate Students
        students_to_create = []
        total_assigned = 0
        total_skipped = 0

        self.stdout.write("Generating student data...")
        for batch in BATCHES:
            self.stdout.write(f"Processing Batch {batch['name']}...")
            
            gender_data = [('M', batch['m_count']), ('F', batch['f_count'])]
            batch_student_counter = 1
            
            for gender, count in gender_data:
                for _ in range(count):
                    student_id = f"{batch['prefix']}{str(batch_student_counter).zfill(4)}"
                    batch_student_counter += 1
                    
                    name_list = FIRST_NAMES_M if gender == 'M' else FIRST_NAMES_F
                    full_name = f"{random.choice(name_list)} {random.choice(LAST_NAMES)}"
                    
                    # Status toggle
                    rand_status = random.random()
                    if rand_status < 0.85:
                        status = 'present'
                    elif rand_status < 0.95:
                        status = 'leave'
                    else:
                        status = 'outing'

                    # Allocation
                    target_key = (batch['name'], gender)
                    target_room = None
                    
                    if target_key in ALLOCATION_MAP:
                        hostel, floor_num = ALLOCATION_MAP[target_key]
                        
                        # Try target floor
                        potential_rooms = room_registry.get((hostel, floor_num), [])
                        for room in potential_rooms:
                            if occupancy_tracker[room.id] < room.capacity:
                                target_room = room
                                break
                        
                        # Fallback to any room in same hostel
                        if not target_room:
                            fallback_rooms = hostel_registry.get(hostel, [])
                            for room in fallback_rooms:
                                if occupancy_tracker[room.id] < room.capacity:
                                    target_room = room
                                    break
                    
                    if target_room:
                        occupancy_tracker[target_room.id] += 1
                        total_assigned += 1
                    else:
                        total_skipped += 1

                    # Parent info
                    p_name = f"{random.choice(FIRST_NAMES_M)} {random.choice(LAST_NAMES)}"
                    p_mobile = "8" + "".join([str(random.randint(0, 9)) for _ in range(9)])

                    students_to_create.append(Student(
                        hostel=target_room.floor.hostel if target_room else 'I1',
                        name=full_name,
                        student_id=student_id,
                        gender=gender,
                        dob=date(batch['birth_year'], random.randint(1, 12), random.randint(1, 28)),
                        mobile_number=generate_mobile(),
                        university_email=f"{student_id.lower()}@rguktn.ac.in",
                        personal_email=f"{student_id.lower()}_personal@gmail.com",
                        year=batch['name'],
                        branch=random.choice(['PUC', 'ECE', 'CSE', 'EEE', 'ME', 'MME', 'CE', 'CHE', 'AI&ML']),
                        room=target_room,
                        parent_name=p_name,
                        parent_mobile=p_mobile,
                        blood_group=random.choice(BLOOD_GROUPS),
                        address="Street No. " + str(random.randint(1, 100)) + ", Landmark, City, State",
                        status=status,
                        role='student'
                    ))

                    # Bulk create in chunks
                    if len(students_to_create) >= 500:
                        Student.objects.bulk_create(students_to_create)
                        students_to_create = []

        # Final bulk create
        if students_to_create:
            Student.objects.bulk_create(students_to_create)

        self.stdout.write(self.style.SUCCESS(f"Successfully populated {total_assigned} students."))
        if total_skipped > 0:
            self.stdout.write(self.style.WARNING(f"Skipped {total_skipped} students due to lack of room capacity."))
