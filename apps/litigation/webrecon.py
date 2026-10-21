"""Reads WebRecon's monthly litigation statistics posts (owner decision 2026-10-21: no key; public blog; their
robots.txt allows it). The post list comes from their sitemap; each post is read once (the latest two again, in case
they were corrected), at most PER_RUN per run, a second apart. Figures read: TCPA lawsuits and class actions in the
month, TCPA year to date, the % changes, and the share of repeat plaintiffs. A post whose TCPA line can't be read is
kept as "could not read", so a site redesign shows up instead of silently stopping."""
import hashlib
import html
import re
import time
import urllib.request
from datetime import date

from .models import LitigationMonth

SITEMAP = 'https://webrecon.com/sitemap.xml'
AGENT = 'CiV litigation reader (Comply iV; reads the monthly posts)'
PER_RUN = 24
MONTHS = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}
POST = re.compile(r'https://webrecon\.com/litigation-statistics/webrecon-([a-z]+)-(\d{4})[^<\s]*')


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={'User-Agent': AGENT})
    with urllib.request.urlopen(request, timeout=30) as reply:
        return reply.read(2_000_000).decode('utf-8', 'ignore')


def posts(sitemap: str) -> dict[date, str]:
    """{first day of month: post URL} from the sitemap; a month with two posts keeps the longer address (e.g. the
    year-in-review)."""
    out = {}
    for m in POST.finditer(sitemap):
        month = MONTHS.get(m.group(1)[:3])
        if month:
            key = date(int(m.group(2)), month, 1)
            if key not in out or len(m.group(0)) > len(out[key]):
                out[key] = m.group(0)
    return out


def text_of(page: str) -> str:
    page = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', page, flags=re.S | re.I)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', page)))


def number(s: str) -> int:
    return int(s.replace(',', ''))


def read(page: str) -> dict:
    t = text_of(page)
    found = {}
    m = re.search(r'(\d[\d,]*)\s+TCPA\s*,\s*(\d[\d,]*)\s+Class Action', t, re.I)
    if m:
        found.update(tcpa=number(m.group(1)), tcpa_class=number(m.group(2)))
    else:
        m = re.search(r'(\d[\d,]*)\s+TCPA\b(?!\s*\()', t)
        if m and 'Year to Date' not in t[max(0, m.start() - 200):m.start()]:
            found['tcpa'] = number(m.group(1))
    m = re.search(r'Year to Date.{0,300}?(\d[\d,]*)\s+TCPA', t, re.I)
    if m:
        found['tcpa_ytd'] = number(m.group(1))
    m = re.search(r'TCPA\s+([+-]\d+(?:\.\d+)?)%', t)
    if m:
        found['change_month'] = float(m.group(1))
    m = re.search(r'TCPA\s*\(([+-]\d+(?:\.\d+)?)%\)', t)
    if m:
        found['change_ytd'] = float(m.group(1))
    m = re.search(r'(\d+(?:\.\d+)?)%\s+of all plaintiffs[^.]{0,80}?(?:filed|sued)[^.]{0,40}?before', t, re.I)
    if m:
        found['repeat_plaintiffs'] = float(m.group(1))
    return found


def refresh(get=fetch, pause: float = 1.0) -> int:
    """New posts (and the latest two again). Returns how many posts were read."""
    listed = posts(get(SITEMAP))
    have = set(LitigationMonth.objects.filter(read_ok=True).values_list('month', flat=True))
    newest = sorted(listed, reverse=True)[:2]
    todo = [m for m in sorted(listed, reverse=True) if m not in have or m in newest][:PER_RUN]
    for i, month in enumerate(todo):
        if i and pause:
            time.sleep(pause)
        try:
            page = get(listed[month])
            figures = read(page)
        except Exception:  # site down or an odd post: marked "could not read", the run goes on
            page, figures = '', {}
        LitigationMonth.objects.update_or_create(month=month, defaults={
            'url': listed[month], 'read_ok': 'tcpa' in figures, 'page_sha256': hashlib.sha256(page.encode()).hexdigest(),
            **{k: figures.get(k) for k in ('tcpa', 'tcpa_class', 'tcpa_ytd', 'change_month', 'change_ytd', 'repeat_plaintiffs')}})
    return len(todo)
