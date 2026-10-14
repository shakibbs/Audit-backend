#!/bin/sh
# Starts the backend: apply database changes as the owner, refresh the limited user, then serve with Gunicorn.
set -e
DB_AS_OWNER=1 python manage.py migrate --noinput
DB_AS_OWNER=1 python manage.py create_app_role
python manage.py load_rulebook  # rulebook/*.yaml; unchanged files are skipped
exec gunicorn config.wsgi --bind 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-3}" --timeout 60 --access-logfile -
