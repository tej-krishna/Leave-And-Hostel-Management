# HostelManagement/HOSTEL/settings.py (Assuming HOSTEL is your project's root)

from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# You should generate a unique, long, and random key for production.
# Example: import os; os.urandom(50).hex()
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-default-key-replace-me')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '*').split(',')

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'hostel_app',
    'rooms_app',
    'essl_app',
]

MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'HOSTEL.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [], # You can add global template directories here if needed
        'APP_DIRS': True, # THIS MUST BE TRUE for Django to find templates within app/templates/app_name/
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'HOSTEL.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

# You might want to comment out the old SQLite configuration so you have it just in case
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'hostel_db',
#         'USER': 'hostel_user',
#         'PASSWORD': 'Kanna!120',
#         'HOST': 'localhost', # Or your database server IP
#         'PORT': '5432',      # Default PostgreSQL port
#     }
# }
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC' # Keep UTC for internal consistency, convert for display if needed.

USE_I18N = True

USE_TZ = True # Crucial for timezone-aware datetimes used by timezone.now()


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
# STATIC_ROOT is typically used in production to collect all static files into one directory.
# STATICFILES_DIRS is for development to tell Django where to find your app-specific static files.
STATICFILES_DIRS = [
    BASE_DIR / 'static', # Your project-level static files (e.g., global CSS/JS)
]

# Media files (user-uploaded content, or dynamically generated content like QR codes)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media' # This should be the absolute path to your media directory

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- WebAuthn (Biometric) Settings ---
WEBAUTHN_RP_ID = os.environ.get('WEBAUTHN_RP_ID', '10.147.165.181')
WEBAUTHN_RP_NAME = os.environ.get('WEBAUTHN_RP_NAME', 'HMS Biometrics')
WEBAUTHN_ORIGIN = os.environ.get('WEBAUTHN_ORIGIN', f'http://{WEBAUTHN_RP_ID}:8000')

# --- Leave Workflow: institution identity + long-leave escalation ---
# Used on the generated leave letter (hostel_app/pdf.py) and nowhere else -
# a placeholder default is used deliberately rather than guessing the real
# institution name from other data in the repo.
INSTITUTION_NAME = os.environ.get('INSTITUTION_NAME', 'Hostel Management Institution')

# Recipients for the very-long-leave (30+ day) escalation letter/email.
# Deliberately read from the environment, never hardcoded, so no real staff
# email address ends up committed to source control.
AO_EMAIL = os.environ.get('AO_EMAIL', '')
DIRECTOR_EMAIL = os.environ.get('DIRECTOR_EMAIL', '')

DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@hostel.local')

# Email backend: defaults to printing to the console in dev so the leave
# workflow never silently depends on a real mail server being configured.
# Set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend (+ the
# EMAIL_HOST* variables below) in .env for real delivery.
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '25'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'False').lower() == 'true'

