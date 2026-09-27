"""
Settings for the django-paystack-wallet demo.

Wallet behaviour is configured in demo/.env (copy demo/.env.example), exactly as a
real project would, so you can flip features on and off without touching code.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR.parent))    # the wallet package from this repository

from wallet.conf import load_env_file  # noqa: E402

load_env_file(BASE_DIR / '.env')

SECRET_KEY = os.environ.get('DEMO_SECRET_KEY', 'demo-only-not-secret')
DEBUG = os.environ.get('DEMO_DEBUG', 'true').lower() == 'true'
ALLOWED_HOSTS = [h.strip() for h in os.environ.get(
    'DEMO_ALLOWED_HOSTS', 'localhost,127.0.0.1,.ngrok-free.app,.ngrok.io,.trycloudflare.com',
).split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = ['https://*.ngrok-free.app', 'https://*.ngrok.io', 'https://*.trycloudflare.com']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'djmoney',
    'wallet',
    'shop',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'demo_project.urls'
WSGI_APPLICATION = 'demo_project.wsgi.application'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
        'shop.context.demo_context',
    ]},
}]

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lagos'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'],
}

# Notification emails are printed in the terminal running the server
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'wallet-demo@example.com'

# Show what the wallet is doing in the terminal
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'short': {'format': '[%(name)s] %(levelname)s %(message)s'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'short'}},
    'loggers': {
        'wallet': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'wallet.audit': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'wallet.notifications': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}
