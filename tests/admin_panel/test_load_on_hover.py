"""Owner, 2026-11-16: staff pages load on hover, like the client portal. Only plain pages are loaded early: never a
download, file, photo, password link or any link that does something (they all have more parts in their address)."""
import json
import re

from django.contrib.staticfiles import finders

ALLOWED = ['/civ-admin/', '/civ-admin/:app/:model/', '/civ-admin/:app/:model/add/', '/civ-admin/:app/:model/:id/change/']


def rules():
    script = open(finders.find('admin_panel/civ.js')).read()
    block = script[script.index("rules.textContent = JSON.stringify(") + len("rules.textContent = JSON.stringify("):]
    found = re.findall(r"href_matches: '([^']+)'", block[:block.index('eagerness')])
    return script, found


def test_only_plain_pages_are_loaded_early():
    script, found = rules()
    assert "speculationrules" in script and "eagerness: 'moderate'" in script  # on hover, not every link at once
    assert found == ALLOWED


def to_regex(pattern: str) -> re.Pattern:
    return re.compile('^' + re.sub(r':\w+', '[^/]+', pattern) + '$')


def test_no_action_link_matches():
    pats = [to_regex(p) for p in rules()[1]]
    for path in ['/civ-admin/reports/report/4/download/', '/civ-admin/clients/client/3/consent-pages/2/photo/', '/civ-admin/staff/staffuser/2/password-link/',
                 '/civ-admin/buyers/buyerorg/1/links/2/stop/', '/civ-admin/provenance/proofrequest/5/file/', '/civ-admin/clients/client/3/documents/4/open/',
                 '/civ-admin/regulatory/ruleupdate/rule-update/3/approve/', '/civ-admin/logout/', '/civ-admin/reports/quoterequest/2/step/release/']:
        assert not any(p.match(path) for p in pats), path
    assert any(p.match('/civ-admin/clients/client/3/change/') for p in pats)
