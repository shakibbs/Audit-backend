"""Background workers: the heartbeat job and the timetable."""
import pytest
from django.conf import settings

from apps.jobs.models import Heartbeat
from apps.jobs.tasks import heartbeat
from config.celery import app


@pytest.mark.django_db
def test_heartbeat_job_records_a_sign_of_life():
    heartbeat.delay()  # without Redis the job runs at once
    first = Heartbeat.objects.get(name='workers').seen_at
    heartbeat.delay()
    assert Heartbeat.objects.count() == 1
    assert Heartbeat.objects.get(name='workers').seen_at >= first


def test_clock_runs_the_heartbeat_every_minute():
    entry = settings.CELERY_BEAT_SCHEDULE['heartbeat']
    assert entry['task'] == 'apps.jobs.tasks.heartbeat' and entry['schedule'] == 60.0
    assert 'apps.jobs.tasks.heartbeat' in app.tasks
