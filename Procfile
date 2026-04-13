release: python manage.py migrate
web: gunicorn erp.wsgi:application --preload --workers 2
