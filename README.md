# Hostel Management System (HMS)

A comprehensive Django-based application designed to manage hostels, student allocations, leave tracking, and biometric attendance (via eSSL devices).

## Features

- **Room Management:** Interactive hostel views, room selection grid, and student allocation controls.
- **Student Management:** Leave applications, status tracking, and student lookup.
- **Biometric Integration:** Sync attendance logs and control eSSL biometric devices directly from the dashboard.

---

## 🚀 Getting Started Locally

Follow these steps to download, set up, and run the project on your local machine.

### Prerequisites
- **Python 3.8+**
- **Git**
- **pip** (Python package installer)

### 1. Clone the Repository

Open your terminal or command prompt and clone the repository. (If you haven't uploaded it to GitHub yet, create a repository and use its URL here).

```bash
git clone https://github.com/YourUsername/YourRepositoryName.git
cd YourRepositoryName
```

### 2. Set Up a Virtual Environment

It is highly recommended to use a virtual environment to isolate the project dependencies.

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

Install the required Python packages from the `requirements.txt` file:

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

The project uses a `.env` file to manage sensitive configurations (like the `SECRET_KEY`, `DEBUG` mode, and Biometric IPs).

1. Copy the provided `.env.example` file to create a new file named `.env`:
   - On Windows: `copy .env.example .env`
   - On macOS/Linux: `cp .env.example .env`
2. Open `.env` in a text editor and update the values if necessary (the default ones are fine for local testing).

### 5. Apply Database Migrations

Set up the SQLite database schema by running the Django migrations:

```bash
python manage.py migrate
```

### 6. Create a Superuser (Optional but Recommended)

To access the Django admin panel, you'll need an administrative account:

```bash
python manage.py createsuperuser
```
Follow the prompts to set your username, email, and password.

### 7. Run the Development Server

Start the local Django development server:

```bash
python manage.py runserver
```

Open your web browser and navigate to `http://127.0.0.1:8000/`. To access the admin panel, go to `http://127.0.0.1:8000/admin/`.

---

## 📚 App Architecture & Endpoints

### Hostel App (`hostel_app`)

#### Authentication & Dashboard
- **URL Routes:** `/login/`, `/logout/`, `/dashboard/`
- **Options/Actions:** Staff and student authentication, redirecting to the main dashboard for staff roles to manage the hostel.

#### Student Status & Management
- **URL Routes:** `/status_updater/`, `/students/<student_pk>/edit/`
- **Options/Actions:** Staff views to manually update student statuses (Present, Outing, Leave, etc.) and edit student details.

#### Student Lists
- **URL Routes:** `/students/total/`, `/students/present/`, `/students/leave/`, `/students/outing/`, `/students/yearwise/`
- **Options/Actions:** Provides filtered lists of students based on their current status and academic year.

#### Leave Application & Management
- **URL Routes:** `/leave/apply/` (Student), `/leave_management/` (Staff)
- **Options/Actions:** Allows students to apply for leave. Staff can review, approve, or reject leave applications and update their status.

#### Biometric Tracking & Lookup
- **URL Routes:** `/biometric_track/`, `/student_lookup/`
- **Options/Actions:** View live biometric attendance logs and look up specific student details quickly.

### Rooms App (`rooms_app`)

#### Hostel 3D View
- **URL Route:** `/rooms/hostels/` (name: `hostel_3d`)
- **View Function:** `hostel_3d_view` in `rooms_app/views.py`
- **Options/Actions:** 
  - **Hostel Building Selection:** Visual representation/list of hostels. Clicking one redirects to the Room Selection grid.

#### Room Selection Grid
- **URL Route:** `/rooms/selection/<hostel_code>/` (name: `room_selection`)
- **View Function:** `room_selection_view` in `rooms_app/views.py`
- **Options/Actions:** 
  - **Floor Navigation:** Select different floors to view rooms.
  - **Room Block:** Clicking on a room opens a modal (via AJAX).
  - **Room Indicators:** Visual cues indicating full/available capacity.

#### Room Detail / Management Modal
- **URL Routes:** `/rooms/details/floor/<floor_pk>/room/<room_number>/` (AJAX) or `/rooms/manage/floor/<floor_pk>/room/<room_number>/` (Detail)
- **Options/Actions:** 
  - **Student List:** Shows students currently allotted.
  - **Unallot Button:** Removes a student from the room.
  - **Allot Student Form:** Input ID to add a student.
  - **Toggle Room Status:** Disables/enables the room.

### ESSL App (`essl_app`)

#### Biometric Device Configuration
- **URL Route:** `/iclock/devices/` (name: `device_config`)
- **Options/Actions:** 
  - **Device List:** Shows all configured devices and IP addresses.
  - **Add Device Form:** Adds a new device to the database.
  - **Test Connection:** Verify connectivity to physical devices.

#### Device Endpoints (Backend Sync)
- **URL Routes:** `/iclock/cdata`, `/iclock/getrequest`, `/iclock/devicecmd`
- **Description:** Hidden API endpoints that the physical eSSL devices communicate with to sync logs and receive commands.

#### API Logs
- **URL Route:** `/iclock/api/logs/` (name: `api_biometric_logs`)
- **Description:** JSON endpoint that serves the log data for the biometric track dashboard table in `hostel_app`.
