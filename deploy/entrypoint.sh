#!/bin/sh
# Starts the backend: apply database changes, then serve with Gunicorn.
set -e
python manage.py migrate --noinput
exec gunicorn config.wsgi --bind 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-3}" --timeout 60 --access-logfile -
