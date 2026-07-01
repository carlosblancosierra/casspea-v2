"""Settings for running the test suite locally and in CI.

Usage:
    python manage.py test --settings=erp.settings_test

Provides safe defaults for every environment variable the base settings
require, then overrides anything that would talk to an external service
(Postgres, S3, Stripe, Royal Mail, SMTP) so the suite runs anywhere with
no configuration.
"""
import os

# The base settings read these at import time and fail hard when they are
# missing. Provide harmless defaults *before* importing them. setdefault is
# used so real values (e.g. in CI secrets) still win.
_TEST_ENV_DEFAULTS = {
    'DEBUG': 'true',
    'USE_S3': 'false',
    'POSTGRES_DB': 'test',
    'POSTGRES_USER': 'test',
    'POSTGRES_PASSWORD': 'test',
    'POSTGRES_HOST': 'localhost',
    'POSTGRES_PORT': '5432',
    'STRIPE_PUBLIC_KEY': 'pk_test_dummy',
    'STRIPE_SECRET_KEY': 'sk_test_dummy',
    'STRIPE_WEBHOOK_SECRET': 'whsec_dummy',
    'ROYAL_MAIL_API_KEY': 'test-royal-mail-key',
}
for _key, _value in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

from .settings import *  # noqa: E402,F401,F403

# Fast, dependency-free test database.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Never send anything real during tests.
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Run django-q tasks synchronously so tests are deterministic.
Q_CLUSTER = {**Q_CLUSTER, 'sync': True}  # noqa: F405

# Speed up user creation in tests.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
