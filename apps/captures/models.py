"""CiV's own copies of public consent pages (spec page_capture; owner decision D32a: CiV keeps the screenshot, the
page text and the measurements). One page per address per client; a capture per screen size, about once a day."""
from django.db import models


class ConsentPage(models.Model):
    """A consent form page seen in the client's certificates: host and path only (a query string could carry a
    person's details)."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='consent_pages')
    address = models.CharField(max_length=300)  # e.g. sunpathsolar.com/free-quote
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()  # the latest certificate that named it
    last_captured_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'consent_page'
        constraints = [models.UniqueConstraint(fields=['client', 'address'], name='one_page_per_address')]

    def __str__(self) -> str:
        return self.address


def screenshot_path(capture, filename: str) -> str:
    return f'captures/{capture.client_id}/{capture.page_id}/{capture.captured_at:%Y%m%d-%H%M%S}-{capture.viewport}.png'


class PageCapture(models.Model):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='page_captures')
    page = models.ForeignKey(ConsentPage, on_delete=models.CASCADE, related_name='captures')
    captured_at = models.DateTimeField()
    viewport = models.CharField(max_length=12)  # 390x844 (phone) · 1440x900 (computer)
    ok = models.BooleanField()
    problem = models.CharField(max_length=200, blank=True)  # why it could not be captured (never held against the client)
    screenshot = models.FileField(upload_to=screenshot_path, blank=True)  # private: media files have no public address
    screenshot_sha256 = models.CharField(max_length=64, blank=True)
    text = models.TextField(blank=True)  # the page's words (a public page)
    text_sha256 = models.CharField(max_length=64, blank=True)
    consent_block = models.TextField(blank=True)  # the words that ask for permission, if found on this page
    consent_block_sha256 = models.CharField(max_length=64, blank=True)
    measurements = models.JSONField(default=dict)  # checkboxes, buttons, font size, colours, positions (Step 4 reads these)
    fingerprint_sha256 = models.CharField(max_length=64, blank=True)  # the sealed fingerprint of this capture
    purged_at = models.DateTimeField(null=True, blank=True)  # screenshot and text deleted after 4 years; hashes kept

    class Meta:
        db_table = 'page_capture'
        indexes = [models.Index(fields=['client', 'page', 'captured_at'])]
        ordering = ['-captured_at']
