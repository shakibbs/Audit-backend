"""Background workers: Celery, with Redis as the to-do list. Each app keeps its jobs in tasks.py."""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('civ')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
