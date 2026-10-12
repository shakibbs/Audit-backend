# Load the workers' app with Django, so jobs can be sent from anywhere in the backend.
from .celery import app as celery_app

__all__ = ('celery_app',)
