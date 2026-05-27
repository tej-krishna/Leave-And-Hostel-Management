# HOSTEL/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings # Import settings
from django.conf.urls.static import static # Import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('hostel_app.urls')), # Assuming your hostel_app URLs are included here
    path('rooms/', include('rooms_app.urls')), # Includes all rooms_app URLs prefixed with 'rooms/' (e.g., /rooms/selection)# Add other app URLs as needed
    path('iclock/', include('essl_app.urls')), # eSSL biometric integration
]

# ONLY add this in development, DO NOT use in production
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT) # If you use STATIC_ROOT