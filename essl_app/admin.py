from django.contrib import admin
from .models import AttendanceLog, BiometricDevice

@admin.register(AttendanceLog)
class AttendanceLogAdmin(admin.ModelAdmin):
    list_display = ('user_id', 'timestamp', 'punch_state', 'device_ip', 'synced_at')
    list_filter = ('punch_state', 'timestamp')
    search_fields = ('user_id', 'device_ip')

@admin.register(BiometricDevice)
class BiometricDeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'ip_address', 'location_type', 'last_seen')
    list_filter = ('location_type',)
    search_fields = ('name', 'ip_address')
