"""Settings for the storefront's end-to-end tests (next-casspea/e2e).

The test settings, with a database file instead of an in-memory one: the
in-memory database belongs to a single connection, and runserver serves
each request on its own, so a cart would vanish between requests.

Usage:
    python manage.py migrate --settings=erp.settings_e2e
    python manage.py loaddata <fixtures> --settings=erp.settings_e2e
    python manage.py runserver 8000 --settings=erp.settings_e2e
"""
import os
import tempfile
from pathlib import Path

from .settings_test import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.environ.get('E2E_DB_PATH', str(Path(tempfile.gettempdir()) / 'casspea-e2e.sqlite3')),
    }
}

# Never closed during a test run, whatever date it is.
STORE_ORDER_DEADLINE = ''
