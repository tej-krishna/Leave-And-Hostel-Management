import time
import requests
from django.core.management.base import BaseCommand
from essl_app.models import BiometricDevice

class Command(BaseCommand):
    help = 'Pings all biometric devices every 5 seconds to trigger live sync'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting Device Pinger... (Press Ctrl+C to stop)'))
        
        while True:
            devices = BiometricDevice.objects.all()
            if not devices:
                self.stdout.write('No devices configured. Waiting...')
                time.sleep(10)
                continue

            for device in devices:
                try:
                    # We send a GET request to the device's web port or a dummy path
                    # This pokes the device and often triggers it to flush its ADMS buffer
                    url = f"http://{device.ip_address}"
                    self.stdout.write(f"Poking {device.name} at {url}...")
                    
                    # Short timeout so we don't block
                    requests.get(url, timeout=2)
                except Exception as e:
                    # We expect some errors if the device doesn't have a web server on port 80
                    # but the TCP handshake alone often helps NAT/sync.
                    pass

            time.sleep(5)
