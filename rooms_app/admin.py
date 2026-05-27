# HostelManagement/rooms_app/admin.py

from django.contrib import admin
from .models import Floor, Room

# Register your models here
@admin.register(Floor)
class FloorAdmin(admin.ModelAdmin):
    list_display = ('hostel', 'floor_number', 'name')
    list_filter = ('hostel',)
    search_fields = ('name', 'floor_number')

@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('room_number', 'floor', 'capacity', 'is_disabled', 'occupied_count', 'available_count')
    list_filter = ('floor__hostel', 'floor__floor_number', 'is_disabled')
    search_fields = ('room_number',)

    def occupied_count(self, obj):
        return obj.get_occupied_beds_count()
    occupied_count.short_description = 'Occupied'

    def available_count(self, obj):
        return obj.get_available_beds_count()
    available_count.short_description = 'Available'