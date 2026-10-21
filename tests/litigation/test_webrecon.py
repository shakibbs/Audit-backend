"""Module 10 step 4b: WebRecon's monthly posts read into the insurer's Litigation page (pretend website here)."""
from datetime import date

import pytest

from apps.litigation.api import page
from apps.litigation.models import LitigationMonth
from apps.litigation.webrecon import posts, read, refresh

pytestmark = pytest.mark.django_db
BASE = 'https://webrecon.com/litigation-statistics/'
SITEMAP = ''.join(f'<loc>{BASE}{s}</loc>' for s in ('webrecon-aug-2025-stats', 'webrecon-august-2026-stats', 'webrecon-dec-2025-stats',
                                                    'webrecon-dec-2025-stats-year-in-review', 'webrecon-july-2026-stats'))


def post(month_line, ytd, extra=''):
    return (f'<html><script>var x="999 TCPA";</script><h1>Stat Breakdown</h1><p>ups (FDCPA +4.0%, TCPA +11.9%) {extra}</p>'
            f'<p>YTD numbers: TCPA (+20.2%), FCRA (+42.4%)</p><p>About 36% of all plaintiffs who filed suit last month had filed at least once before.</p>'
            f'<ul><li>365 FDCPA, 34 Class Action (9.3%)</li><li>{month_line}</li></ul><p>Statistics Year to Date:</p>'
            f'<ul><li>3000 FDCPA</li><li>7274 FCRA</li><li>{ytd} TCPA</li></ul>')


PAGES = {
    f'{BASE}webrecon-august-2026-stats': post('198 TCPA, 143 Class Action (72.2%)', '1,907'),
    f'{BASE}webrecon-aug-2025-stats': post('177 TCPA, 120 Class Action (67.8%)', '1586'),
    f'{BASE}webrecon-july-2026-stats': post('177 TCPA, 108 Class Action (61.0%)', '1709'),
    f'{BASE}webrecon-dec-2025-stats-year-in-review': post('222 TCPA, 151 Class Action (68.0%)', '2810'),
}


def get(url):
    return SITEMAP if url.endswith('sitemap.xml') else PAGES.get(url, '<html>Redesigned page</html>')


def test_posts_by_month_from_the_sitemap():
    found = posts(SITEMAP)
    assert found[date(2026, 8, 1)].endswith('august-2026-stats') and found[date(2025, 12, 1)].endswith('year-in-review')


def test_reads_the_tcpa_figures():
    assert read(PAGES[f'{BASE}webrecon-august-2026-stats']) == {
        'tcpa': 198, 'tcpa_class': 143, 'tcpa_ytd': 1907, 'change_month': 11.9, 'change_ytd': 20.2, 'repeat_plaintiffs': 36.0}


def test_refresh_reads_each_post_once_and_the_latest_two_again():
    assert refresh(get, pause=0) == 4
    assert LitigationMonth.objects.get(month=date(2026, 8, 1)).tcpa_class == 143
    assert refresh(get, pause=0) == 2  # only the two newest are read again


def test_a_redesigned_page_is_marked_not_silently_skipped():
    PAGES_BACKUP = dict(PAGES)
    PAGES[f'{BASE}webrecon-august-2026-stats'] = '<html>Redesigned page</html>'
    try:
        refresh(get, pause=0)
    finally:
        PAGES.clear()
        PAGES.update(PAGES_BACKUP)
    assert LitigationMonth.objects.get(month=date(2026, 8, 1)).read_ok is False
    assert page()['headline'][1]['label'] == 'Class actions filed, Jul 2026'  # the latest month that could be read


def test_the_insurer_page_gets_real_cards_by_id():
    assert page() == {}  # nothing read yet: the sample stays
    refresh(get, pause=0)
    d = page()
    ids = {h['id']: h for h in d['headline']}
    assert ids['filings-year']['value'] == '1,907' and ids['filings-year']['label'] == 'Federal TCPA filings, 2026 so far'
    assert ids['class-month']['note'] == '72.2% of 198 TCPA filings · vs 120 in Aug 2025'
    assert ids['repeat-plaintiffs']['value'] == '36%'
    assert d['classByYear'] == [{'label': 'Aug 2025', 'count': 120}, {'label': 'Aug 2026', 'count': 143}] and d['classMonth'] == 'August'


def test_signed_in_users_can_read_it(member_user, signed_in):
    refresh(get, pause=0)
    assert signed_in(member_user).get('/api/litigation').json()['headline'][0]['id'] == 'filings-year'


def test_a_stray_comma_or_a_failing_page_never_stops_the_run():
    assert read('<p>Year to Date: , TCPA</p><p>12 TCPA, 3 Class Action (25%)</p>')['tcpa'] == 12

    def broken(url):
        if url.endswith('sitemap.xml'):
            return SITEMAP
        raise OSError('down')
    assert refresh(broken, pause=0) == 4 and not LitigationMonth.objects.filter(read_ok=True).exists()
