"""CiV's own browser: opens a public page like a visitor, never types into or submits a form, and returns a screenshot,
the page's words and measurements. Runs in its own container (Chromium installed there).

Safety: page addresses come from certificates, which come from leads anyone could write. The browser opens only
public internet addresses on the normal web ports, and every request the page makes is checked the same way, so a
page can never reach inside CiV's own network.
"""
import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from django.conf import settings

TIMEOUT_MS = 30_000
USER_AGENT = 'Mozilla/5.0 (compatible; CiV-PageCapture/1.0; consent page evidence)'
TEXT_LIMIT = 200_000

# Runs inside the page: what Step 4 needs, measured as the visitor would see it. Never changes the page.
MEASURE_JS = r"""
() => {
  const WORDS = /(consent|agree|authori[sz]e|permission|you may (call|text|contact)|autodial|automated|pre-?recorded|artificial|tcpa|calls? (and|or|&) texts?|text messages?|contact you)/gi;
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0; };
  const box = (el) => { const r = el.getBoundingClientRect(); return { top: Math.round(r.top + scrollY), left: Math.round(r.left), width: Math.round(r.width), height: Math.round(r.height) }; };
  const style = (el) => { const s = getComputedStyle(el); return { fontSize: parseFloat(s.fontSize), color: s.color, background: bg(el) }; };
  function bg(el) { for (let n = el; n; n = n.parentElement) { const c = getComputedStyle(n).backgroundColor; if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c; } return 'rgb(255, 255, 255)'; }
  const labelOf = (input) => { if (input.labels && input.labels.length) return input.labels[0].innerText.trim();
    const p = input.closest('label') || input.parentElement; return p ? p.innerText.trim().slice(0, 1000) : ''; };
  let best = null;
  for (const el of document.querySelectorAll('p, label, div, span, small, li, td, section')) {
    if (!visible(el)) continue;
    const t = (el.innerText || '').trim();
    if (t.length < 40 || t.length > 3000) continue;
    const hits = (t.match(WORDS) || []).length;
    if (hits < 2) continue;
    if (!best || hits > best.hits || (hits === best.hits && t.length < best.text.length)) best = { el, hits, text: t };
  }
  const buttons = [...document.querySelectorAll('button, input[type=submit], input[type=button], [role=button]')].filter(visible)
    .map((b) => ({ text: (b.innerText || b.value || '').trim().slice(0, 200), ...box(b) }));
  return {
    title: document.title.slice(0, 300),
    viewport: { width: innerWidth, height: innerHeight }, pageHeight: document.documentElement.scrollHeight,
    forms: document.forms.length,
    phoneFields: document.querySelectorAll('input[type=tel], input[name*=phone i], input[id*=phone i]').length,
    checkboxes: [...document.querySelectorAll('input[type=checkbox]')].map((c) => ({ checked: c.checked, visible: visible(c), label: labelOf(c), ...box(c) })),
    buttons,
    consentBlock: best ? { text: best.text.slice(0, 3000), hits: best.hits, ...box(best.el), ...style(best.el) } : null,
  };
}
"""


class BlockedAddress(Exception):
    """Not a public internet address on a normal web port: never opened."""


def is_public(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.port not in (None, 80, 443):
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, None)}
    except OSError:
        return False
    return bool(addresses) and all(ipaddress.ip_address(a.split('%')[0]).is_global for a in addresses)


@dataclass
class Shot:
    ok: bool
    problem: str = ''
    png: bytes = b''
    text: str = ''
    measurements: dict = field(default_factory=dict)


class Browser:
    """Opens pages with Chromium through Playwright. One browser for a batch of pages."""

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(executable_path=settings.CHROMIUM_PATH or None, args=['--no-sandbox'])
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()
        return False

    def capture(self, url: str, width: int, height: int) -> Shot:
        if not is_public(url):
            return Shot(False, 'Not a public web address: not opened')
        context = self._browser.new_context(viewport={'width': width, 'height': height}, user_agent=USER_AGENT, is_mobile=width < 600,
                                            has_touch=width < 600, service_workers='block')
        page = context.new_page()
        try:
            # Every request the page makes must also go to a public address.
            page.route('**/*', lambda route: route.continue_() if is_public(route.request.url) else route.abort())
            reply = page.goto(url, timeout=TIMEOUT_MS, wait_until='load')
            if reply is None or reply.status >= 400:
                return Shot(False, f'The page answered {reply.status if reply else "nothing"}')
            if not is_public(page.url):  # redirected somewhere private: nothing from it is kept
                return Shot(False, 'Redirected to a non-public address: not kept')
            page.wait_for_timeout(1500)  # late scripts draw the form
            return Shot(True, png=page.screenshot(full_page=True), text=page.inner_text('body')[:TEXT_LIMIT],
                        measurements=page.evaluate(MEASURE_JS))
        except Exception as error:  # timed out, blocked, closed: recorded as "could not capture"
            return Shot(False, f'Could not open: {type(error).__name__}')
        finally:
            context.close()
