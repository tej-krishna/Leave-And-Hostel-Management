# rooms_app/management/commands/create_rooms.py

from django.core.management.base import BaseCommand, CommandError
from rooms_app.models import Floor, Room # Import your models

class Command(BaseCommand):
    help = 'Creates 104 rooms for each existing floor in the database.'

    def handle(self, *args, **options):
        floors = Floor.objects.all()
        if not floors.exists():
            self.stdout.write(self.style.WARNING('No floors found in the database. Please create floors first.'))
            return

        rooms_created_count = 0
        rooms_skipped_count = 0

        for floor in floors:
            self.stdout.write(self.style.HTTP_INFO(f'Processing Floor: {floor.name} (ID: {floor.pk}, Number: {floor.floor_number})'))
            for i in range(1, 105): # Loop from 1 to 104
                room_number = str(i) # Room numbers are strings
                try:
                    # Use get_or_create to avoid creating duplicates
                    room, created = Room.objects.get_or_create(
                        floor=floor,
                        room_number=room_number,
                        defaults={'capacity': 3} # Default capacity for new rooms
                    )
                    if created:
                        rooms_created_count += 1
                        self.stdout.write(self.style.SUCCESS(f'  Created Room {room_number} for Floor {floor.floor_number}'))
                    else:
                        rooms_skipped_count += 1
                        self.stdout.write(self.style.NOTICE(f'  Room {room_number} already exists for Floor {floor.floor_number}, skipped.'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'  Error creating Room {room_number} for Floor {floor.floor_number}: {e}'))
                    raise CommandError(f'Failed to create rooms for floor {floor.name}.')


        self.stdout.write(self.style.SUCCESS(f'\n--- Room Creation Summary ---'))
        self.stdout.write(self.style.SUCCESS(f'Total rooms created: {rooms_created_count}'))
        self.stdout.write(self.style.NOTICE(f'Total rooms skipped (already existed): {rooms_skipped_count}'))
        self.stdout.write(self.style.SUCCESS('Room creation process complete.'))