"""CiV backend settings. Every secret and per-machine value comes from .env."""
import os
from pathlib import Path

from celery.schedules import crontab
from dotenv import load_dotenv

from apps.admin_panel.theme import unfold_config

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def env_list(name: str, default: str = '') -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


SECRET_KEY = os.environ['DJANGO_SECRET_KEY']
DEBUG = os.environ.get('DJANGO_DEBUG', 'false').lower() == 'true'
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS', 'http://localhost:3000')

INSTALLED_APPS = [
    'apps.admin_panel',  # before unfold, so its dashboard page wins
    'unfold',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'apps.staff',
    'apps.access_log',
    'apps.clients',
    'apps.accounts',
    'apps.connections',
    'apps.onboarding',
    'apps.billing',
    'apps.documents',
    'apps.jobs',
    'apps.keyring',
    'apps.ledger',
    'apps.anchoring',
    'apps.tenancy',
    'apps.rulebook',
    'apps.regulatory',
    'apps.sync',
    'apps.certificates',
    'apps.contacts',
    'apps.imports',
    'apps.optouts',
    'apps.reconcile',
    'apps.consent',
    'apps.captures',
    'apps.provenance',
    'apps.uploads',
    'apps.metrics',
    'apps.conversations',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.tenancy.middleware.TenantScopeMiddleware',  # which client's rows this request may see
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

# CiV staff accounts (admin panel). Client users live in a separate table.
AUTH_USER_MODEL = 'staff.StaffUser'
# Signing in on the admin login page directly lands on the dashboard.
LOGIN_URL = '/civ-admin/login/'
LOGIN_REDIRECT_URL = '/civ-admin/'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Day to day the app logs in as the limited user (DB_APP_USER) when one is set, so the tenancy lock applies.
# Database changes run as the owner (DB_USER): entrypoint.sh sets DB_AS_OWNER=1 for them.
_AS_OWNER = os.environ.get('DB_AS_OWNER') == '1' or not os.environ.get('DB_APP_USER')
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'civ'),
        'USER': os.environ.get('DB_USER', '') if _AS_OWNER else os.environ['DB_APP_USER'],
        'PASSWORD': os.environ.get('DB_PASSWORD', '') if _AS_OWNER else os.environ.get('DB_APP_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', ''),
        'PORT': os.environ.get('DB_PORT', ''),
    }
}

# New passwords are saved with Argon2; bcrypt hashes are accepted and upgraded on next sign-in.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Session cookie: not readable by page scripts; HTTPS-only outside local development.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = 60 * 60 * 12
PASSWORD_RESET_TIMEOUT = 60 * 60  # reset links work for 1 hour

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_AUTHENTICATION_CLASSES': ['apps.accounts.authentication.ClientSessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'UNAUTHENTICATED_USER': None,
}

# Emails print in the terminal until a real email service is chosen.
MAILERS = {'default': {'BACKEND': os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')}}
# Links in emails point at the portal.
PORTAL_URL = os.environ.get('PORTAL_URL', 'http://localhost:3000')
# Admin panel look and menu.
UNFOLD = unfold_config(PORTAL_URL)

# Background workers (apps.jobs). Without REDIS_URL (local, tests) a job runs at once, in the same process.
REDIS_URL = os.environ.get('REDIS_URL', '')
CELERY_BROKER_URL = REDIS_URL or 'memory://'
CELERY_TASK_ALWAYS_EAGER = not REDIS_URL
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True  # a job is done only when it finishes; a crashed worker's job runs again
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TIMEZONE = 'UTC'
CELERY_BEAT_SCHEDULE = {
    'heartbeat': {'task': 'apps.jobs.tasks.heartbeat', 'schedule': 60.0},
    'seal-nightly': {'task': 'apps.anchoring.tasks.seal_nightly', 'schedule': crontab(minute=30, hour=0)},  # 00:30 UTC
    'stamp-missing': {'task': 'apps.anchoring.tasks.stamp_missing', 'schedule': crontab(minute=15)},  # hourly retry
    # Live sync (apps.sync): Rulebook poll_interval_minutes 2, catchup_interval_minutes 60, full_sweep_interval_days 7.
    'sync-poll': {'task': 'apps.sync.tasks.poll_due', 'schedule': 2 * 60.0},
    'sync-catchup': {'task': 'apps.sync.tasks.catchup_all', 'schedule': crontab(minute=40)},
    'sync-full-sweep': {'task': 'apps.sync.tasks.full_sweep_due', 'schedule': crontab(minute=10, hour=3)},
    'sync-health': {'task': 'apps.sync.tasks.check_health', 'schedule': 10 * 60.0},
    # Consent certificates must be claimed within 72 hours: the queue runs every minute.
    'claim-certificates': {'task': 'apps.certificates.tasks.claim_certificates', 'schedule': 60.0},
    'consent-needs': {'task': 'apps.consent.tasks.work_out_needs', 'schedule': 60.0},  # each new contact: what it needs, its result
    'consent-recheck': {'task': 'apps.consent.tasks.keep_results_up_to_date', 'schedule': 60.0},  # queued rechecks, read certificates
    'provenance': {'task': 'apps.provenance.tasks.rebuild_provenance', 'schedule': crontab(minute='*/30')},  # where each number came from
    'purge-old-proof-files': {'task': 'apps.provenance.tasks.purge_old_proof_files', 'schedule': crontab(minute=50, hour=4)},
    'purge-old-uploads': {'task': 'apps.uploads.tasks.purge_old_uploads', 'schedule': crontab(minute=55, hour=4)},
    'conversation-review': {'task': 'apps.conversations.tasks.review_conversations', 'schedule': 60.0},  # off until an AI is chosen
    'conversation-exam': {'task': 'apps.conversations.tasks.run_exams', 'schedule': crontab(minute=10, hour=2)},  # the AI's exam (step 4)
    'optout-mark-check': {'task': 'apps.optouts.tasks.check_marks', 'schedule': 300.0},  # urgent within 15 min of an opt-out
    'capture-pages': {'task': 'apps.captures.tasks.capture_pages', 'schedule': crontab(minute=20)},  # hourly; each page about once a day
    'purge-old-captures': {'task': 'apps.captures.tasks.purge_old_captures', 'schedule': crontab(minute=45, hour=4)},
    'consent-nightly': {'task': 'apps.consent.tasks.recheck_time_passed', 'schedule': crontab(minute=0, hour=3)},  # expiring certificates
    'proof-dates': {'task': 'apps.consent.tasks.refresh_proof_dates', 'schedule': 5 * 60.0},  # claimed certificates date their proofs
    # Uploaded lists (apps.imports): CRM records regrouped into batches every 15 minutes.
    'import-batches': {'task': 'apps.imports.tasks.rebuild_batches', 'schedule': 15 * 60.0},
    # Records completeness (apps.reconcile): this month and last, every night.
    'records-completeness': {'task': 'apps.reconcile.tasks.check_completeness', 'schedule': crontab(minute=30, hour=2)},
}
# Live notices ("hooks") from clients' tools are OFF (owner decision 2026-10-16): CiV only asks each tool, every
# 2 minutes, so there is no public door. The /hooks/ code stays for later; it answers only when this is true.
SYNC_HOOKS_ENABLED = os.environ.get('SYNC_HOOKS_ENABLED', 'false').lower() == 'true'
# CiV's own app registrations with OAuth CRMs, used only to renew a client's access pass (never in GitHub).
SALESFORCE_CLIENT_ID = os.environ.get('SALESFORCE_CLIENT_ID', '')
SALESFORCE_CLIENT_SECRET = os.environ.get('SALESFORCE_CLIENT_SECRET', '')
HUBSPOT_CLIENT_ID = os.environ.get('HUBSPOT_CLIENT_ID', '')
HUBSPOT_CLIENT_SECRET = os.environ.get('HUBSPOT_CLIENT_SECRET', '')
# Records read per turn: small, so a big client never holds up the others.
SYNC_BATCH_SIZE = int(os.environ.get('SYNC_BATCH_SIZE', '500'))
# Outside stamps for the daily seal (apps.anchoring), tried in order.
ANCHOR_TSA_URLS = env_list('ANCHOR_TSA_URLS', 'https://freetsa.org/tsr,http://ts.ssl.com')
ANCHOR_OTS_CALENDARS = env_list('ANCHOR_OTS_CALENDARS', 'https://a.pool.opentimestamps.org,https://b.pool.opentimestamps.org')

DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'CiV <no-reply@complyiv.com>')

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
FORMAT_MODULE_PATH = ['config.formats']  # portal-style dates

STATIC_URL = 'static/'
# Client documents: private files on disk, opened only through a staff-only view (no public URL).
MEDIA_ROOT = Path(os.environ.get('MEDIA_ROOT', BASE_DIR / 'media'))
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
STATIC_ROOT = BASE_DIR / 'staticfiles'  # filled by collectstatic
if not DEBUG:  # production: WhiteNoise serves the admin panel's styles (runserver does it locally)
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    # Production: compressed files with version stamps (needs collectstatic). Local and tests: plain files.
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage' if DEBUG
                    else 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

# Behind Traefik (HTTPS ends there): trust its "this was HTTPS" header.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
if not DEBUG:
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '3600'))
    SECURE_CONTENT_TYPE_NOSNIFF = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Page captures run only in the capture container, which has Chromium (deploy/Dockerfile.capture).
CELERY_TASK_ROUTES = {'apps.captures.tasks.capture_pages': {'queue': 'capture'}}
CHROMIUM_PATH = os.environ.get('CHROMIUM_PATH', '')  # empty = Playwright's own browser

# AI conversation review (Module 9): empty = no AI chosen yet, nothing is sent anywhere (owner decision 2026-10-21).
CONVERSATION_REVIEW_MODEL = os.environ.get('CONVERSATION_REVIEW_MODEL', '')
