from django.db import models


class Heartbeat(models.Model):
    """The latest sign of life from the workers. The clock asks a worker to update it every minute."""
    name = models.CharField(max_length=50, unique=True)
    seen_at = models.DateTimeField()

    class Meta:
        db_table = 'job_heartbeat'

    def __str__(self) -> str:
        return f'{self.name} · {self.seen_at:%Y-%m-%d %H:%M} UTC'
