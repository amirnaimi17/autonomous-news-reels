"""Admin settings. The database file is the same one the generator uses."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("STUDIO_SECRET_KEY", "dev-studio-key-change-before-any-deployment")
DEBUG = os.getenv("STUDIO_DEBUG", "true").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "library",
    "django_crontab",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "studio.urls"
WSGI_APPLICATION = "studio.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("STUDIO_DATABASE", str(BASE_DIR / "data" / "news_reels.db")),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# django-crontab. The clock is this computer's timezone, which is Europe/Berlin.
# Django's TIME_ZONE is not what these hours use.
CRONJOBS = [
    ("0 7,11,15,19 * * *", "library.cron.generate_scheduled_reel"),
]
CRONTAB_LOCK_JOBS = True
CRONTAB_PYTHON_EXECUTABLE = os.getenv(
    "CRONTAB_PYTHON_EXECUTABLE",
    str(BASE_DIR / ".venv" / "bin" / "python"),
)
CRONTAB_DJANGO_MANAGE_PATH = os.getenv(
    "CRONTAB_DJANGO_MANAGE_PATH",
    str(BASE_DIR / "manage.py"),
)
