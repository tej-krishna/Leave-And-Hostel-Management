from django.urls import path, re_path
from . import views

urlpatterns = [
    re_path(r'^cdata(?:\.aspx)?$', views.iclock_cdata, name='iclock_cdata'),
    re_path(r'^getrequest(?:\.aspx)?$', views.iclock_getrequest, name='iclock_getrequest'),
    re_path(r'^devicecmd(?:\.aspx)?$', views.iclock_devicecmd, name='iclock_devicecmd'),
    path('devices/', views.device_config, name='device_config'),
    path('devices/delete/<int:device_id>/', views.delete_device, name='delete_device'),
    path('ip-assignment/', views.ip_assignment, name='ip_assignment'),
    path('test-device/<int:device_id>/', views.test_device, name='test_device'),
    path('quick-setup-devices/', views.quick_setup_devices, name='quick_setup_devices'),
    path('api/logs/', views.api_biometric_logs, name='api_biometric_logs'),
    re_path(r'^(?P<path>.*)$', views.debug_log_all),
]
