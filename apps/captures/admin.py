"""Admin, client page: a "Consent pages" tab with each page CiV photographs, the latest photos and checklist."""
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from unfold.admin import TabularInline

from .api import ITEMS, latest
from .checklist import evaluate
from .models import ConsentPage, PageCapture

SIGN = {'pass': '✅', 'fail': '❌', 'not_measured': '–'}
FAIL_SIGN = {'warning': '⚠️', 'info': 'ℹ️'}


class ConsentPageInline(TabularInline):
    """Read only: pages come from the client's certificates, photos from CiV's own browser."""
    model = ConsentPage
    tab = True
    extra = 0
    can_delete = False
    verbose_name = 'consent page'
    verbose_name_plural = 'Consent pages'
    fields = ('address', 'seen', 'photo_taken', 'photos', 'checklist')
    readonly_fields = fields
    ordering = ('-last_seen_at',)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='Seen in certificates')
    def seen(self, page):
        return f'{page.first_seen_at:%d %b %Y} – {page.last_seen_at:%d %b %Y}'

    @admin.display(description='Latest photo')
    def photo_taken(self, page):
        shots = latest(page)
        if not shots:
            return 'Not yet (taken hourly, about once a day per page)'
        good = [s for s in shots if s.ok]
        return f'{shots[0].captured_at:%d %b %Y %H:%M} UTC' + ('' if good else f' · could not capture: {shots[0].problem}')

    @admin.display(description='Photos')
    def photos(self, page):
        shots = [s for s in latest(page) if s.ok and s.screenshot]
        if not shots:
            return '-'
        return format_html_join(' ', '<a class="civ-btn civ-btn-ghost" href="{}" target="_blank" rel="noopener">{}</a>',
                                ((reverse('admin:clients_client_page_photo', args=[page.client_id, s.pk]),
                                  'Phone' if s.viewport.startswith('390') else 'Computer') for s in shots))

    @admin.display(description='Checklist (draft)')
    def checklist(self, page):
        good = [s for s in latest(page) if s.ok]
        if not good:
            return '-'
        items = evaluate({s.viewport: s.measurements for s in good}, page.client.name)['items']
        rows = [(FAIL_SIGN.get(effect, SIGN['fail']) if items.get(code) == 'fail' else SIGN[items.get(code, 'not_measured')], words)
                for code, (words, effect) in ITEMS.items() if effect != 'ai']
        return format_html('<span class="civ tiny">{}</span>', format_html_join(' · ', '{} {}', rows))


def open_photo(request, client_id, capture_id):
    if not request.user.has_perm('captures.view_consentpage'):
        raise PermissionDenied
    shot = get_object_or_404(PageCapture, pk=capture_id, client_id=client_id)
    if not shot.screenshot:
        raise Http404
    response = FileResponse(shot.screenshot.open('rb'), content_type='image/png')
    response['Cache-Control'] = 'private, no-store'
    return response
