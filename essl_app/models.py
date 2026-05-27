from django.db import models

class AttendanceLog(models.Model):
    # Depending on device configuration, punch state maps to different gate actions
    STAGE_CHOICES = [
        ('0', 'Gate In'),
        ('1', 'Gate Out'),
        ('2', 'Hostel Out'),
        ('3', 'Hostel In'),
    ]

    user_id = models.CharField(max_length=100, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    punch_state = models.CharField(max_length=2, choices=STAGE_CHOICES, default='0')
    device_ip = models.GenericIPAddressField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user_id} - {self.get_punch_state_display()} at {self.timestamp}"

class BiometricDevice(models.Model):
    LOCATION_CHOICES = AttendanceLog.STAGE_CHOICES

    name = models.CharField(max_length=100, help_text="e.g. Hostel Out Main Gate")
    ip_address = models.GenericIPAddressField(unique=True)
    location_type = models.CharField(max_length=2, choices=LOCATION_CHOICES)
    last_seen = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.ip_address}) - {self.get_location_type_display()}"
