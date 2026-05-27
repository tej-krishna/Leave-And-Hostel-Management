

### 3.2 Rooms App (ooms_app)

#### 3.2.1 Hostel 3D View
- **URL Route:** /rooms/hostels/ (name: hostel_3d)
- **View Function:** hostel_3d_view in ooms_app/views.py 
- **Options/Actions:** 
  - **Hostel Building Selection:** Visual representation/list of hostels (e.g., I1, I2, K2). Clicking one redirects to the Room Selection grid for that hostel.

#### 3.2.2 Room Selection Grid
- **URL Route:** /rooms/selection/<hostel_code>/ (name: oom_selection)
- **View Function:** oom_selection_view in ooms_app/views.py 
- **Options/Actions:** 
  - **Floor Navigation:** Select different floors to view rooms.
  - **Room Block:** Clicking on a room opens a modal (via AJAX to /rooms/details/floor/<floor_pk>/room/<room_number>/ handled by get_room_details_ajax).
  - **Room Indicators:** Visual cues indicating full/available capacity based on 'student' roles in the room.

#### 3.2.3 Room Detail / Management Modal
- **URL Routes:** /rooms/details/floor/<floor_pk>/room/<room_number>/ (AJAX) or /rooms/manage/floor/<floor_pk>/room/<room_number>/ (Detail)
- **View Functions:** get_room_details_ajax, oom_detail_view in ooms_app/views.py 
- **Options/Actions:** 
  - **Student List:** Shows students currently allotted to the room.
  - **Unallot Button:** Removes a student from the room (POST to /rooms/unallot/<student_pk>/ handled by unallot_student_from_room).
  - **Allot Student Form:** Input ID to add a student (POST to /rooms/allot/<room_id>/ handled by llot_student_to_room).
  - **Toggle Room Status:** Disables/enables the room (POST to /rooms/toggle-status/<room_id>/ handled by 	oggle_room_status).

### 3.3 ESSL App (essl_app)

#### 3.3.1 Biometric Device Configuration
- **URL Route:** /iclock/devices/ (name: device_config)
- **View Function:** device_config in essl_app/views.py 
- **Options/Actions:** 
  - **Device List:** Shows all configured devices, IP addresses, and location types.
  - **Add Device Form:** Adds a new device to the database.
  - **Delete Button:** POST to /iclock/devices/delete/<device_id>/ to remove a device.
  - **Test Connection:** POST to /iclock/test-device/<device_id>/ to verify connectivity.

#### 3.3.2 Device Endpoints (Backend Sync)
- **URL Routes:** /iclock/cdata, /iclock/getrequest, /iclock/devicecmd 
- **View Functions:** iclock_cdata, iclock_getrequest, iclock_devicecmd 
- **Description:** These are hidden API endpoints that the physical eSSL devices communicate with to sync logs and receive commands. No direct HTML template is involved.

#### 3.3.3 API Logs
- **URL Route:** /iclock/api/logs/ (name: pi_biometric_logs)
- **View Function:** pi_biometric_logs in essl_app/views.py 
- **Description:** JSON endpoint that serves the log data for the iometric_track dashboard table in hostel_app.
