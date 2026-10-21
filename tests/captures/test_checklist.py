"""Module 7 step 4: the consent checklist read from CiV's own page capture, and its effect on each call."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.captures.checklist import contrast, evaluate
from apps.captures.models import ConsentPage, PageCapture
from apps.certificates.models import CertificateClaim
from apps.consent.checks import check_contact
from apps.consent.keeping import run_rechecks
from apps.consent.models import ConsentProof, ConsentResult, Recheck
from apps.consent.needs import work_out
from apps.consent.words import check_states
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.rulebook.loader import RULEBOOK_DIR, load

pytestmark = pytest.mark.django_db
GOOD_TEXT = ('By clicking Get My Quote, I agree that SunPath Residential Solar may call and text me at the number provided, '
             'including by autodialer. Consent is not a condition of purchase.')


def form(text=GOOD_TEXT, ticked=False, size=14, colour='rgb(51, 51, 51)', button='Get My Quote', top=300, phone=1, block=True):
    return {'viewport': {'width': 1440, 'height': 900}, 'phoneFields': phone, 'buttons': [{'text': button, 'top': 420}] if button else [],
            'checkboxes': [{'checked': ticked, 'visible': True, 'label': 'I agree', 'top': top + 10}],
            'consentBlock': {'text': text, 'top': top, 'height': 60, 'fontSize': size, 'color': colour, 'background': 'rgb(255, 255, 255)'} if block else None}


def items(**kw):
    return evaluate({'1440x900': form(**kw)}, 'SunPath Residential Solar')


def test_a_fair_form_passes_every_rule_item():
    found = items()
    assert found['codes'] == [] and found['warnings'] == [] and found['measured']
    assert {k for k, v in found['items'].items() if v == 'not_measured'} == {'CC_OPT_OUT', 'CC_NOT_CONDITION', 'CC_AUTODIAL_DISCLOSED'}


def test_a_pre_ticked_box_is_no_proof():
    assert items(ticked=True)['codes'] == ['NP_PRETICKED']


def test_tiny_grey_text_is_weak_wording():
    found = items(size=9, colour='rgb(187, 187, 187)')
    assert found['codes'] == ['WK_WORDING'] and found['items']['CC_FONT_SIZE'] == found['items']['CC_CONTRAST'] == 'fail'
    assert round(contrast('rgb(187, 187, 187)', 'rgb(255, 255, 255)'), 1) == 1.9


def test_the_words_name_another_button():
    assert items(text=GOOD_TEXT.replace('Get My Quote', 'Submit'))['items']['CC_BUTTON_MATCH'] == 'fail'


def test_text_below_the_button_is_only_a_warning():
    found = items(top=600)
    assert found['codes'] == [] and found['warnings'] == ['CC_ABOVE_BUTTON']


def test_no_consent_words_on_the_real_form_is_no_proof_but_a_first_step_page_is_not_measured():
    assert items(block=False)['codes'] == ['NP_NO_CONSENT_TEXT']
    later_step = items(block=False, phone=0)
    assert later_step['codes'] == [] and not later_step['measured']


def test_the_worse_screen_size_counts():
    found = evaluate({'1440x900': form(), '390x844': form(size=8)}, 'SunPath Residential Solar')
    assert found['codes'] == ['WK_WORDING'] and found['by_viewport']['1440x900']['CC_FONT_SIZE'] == 'pass'


def test_the_company_named_is_information_only():
    found = evaluate({'1440x900': form()}, 'Ridgeline HVAC')
    assert found['items']['CC_SELLER_NAMED'] == 'fail' and found['codes'] == []


# --- effect on each call ------------------------------------------------------------------------------------------------

@pytest.fixture
def call(company):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    now = timezone.now()
    made = now - timedelta(days=2)
    page = ConsentPage.objects.create(client=company, address='sunpathsolar.com/free-quote', first_seen_at=made, last_seen_at=made)
    claim = CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref='a' * 40, state='claimed', deadline_at=now,
                                            cert_created_at=made, cert_expires_at=now + timedelta(days=400), page=page.address)
    ConsentProof.objects.create(client=company, phone_token='p1', epoch=epoch_for(company.pk, 'p1', made), kind='certificate',
                                proof_type='web_cert', certificate=claim, captured_at=made, source_system='salesforce', source_record_id='leads:1')
    c = ContactEvent.objects.create(client=company, phone_token='p1', phone_token_kid='k1', source_system='convoso', source_record_id='c1',
                                    source_grade='C', channel='call', direction='outbound', occurred_at=now - timedelta(hours=1),
                                    dial_mode='manual', epoch=epoch_for(company.pk, 'p1', now))
    work_out(c)

    def run(measurements=None, hours_away=3):
        if measurements is not None:
            PageCapture.objects.create(client=company, page=page, captured_at=made + timedelta(hours=hours_away), viewport='1440x900',
                                       ok=True, measurements=measurements)
        check_contact(c)
        return ConsentResult.objects.get(contact=c, variant='strict')
    return run


def test_a_pre_ticked_form_makes_the_call_no_proof(call):
    r = call(form(ticked=True))
    assert (r.status, r.primary_code) == ('no_proof', 'NP_PRETICKED') and check_states(r)[:3] == ['pass', 'pass', 'fails']


def test_tiny_text_makes_the_call_weak(call):
    r = call(form(size=8))
    assert (r.status, r.primary_code) == ('weak', 'WK_WORDING') and 'draft:consent_checklist' in r.labels


def test_a_fair_form_is_measured_and_verified(call):
    r = call(form())
    assert r.status == 'verified' and 'not_measured:consent_wording' not in r.labels and 'not_measured:ai_wording' in r.labels
    assert check_states(r)[2] == 'pass'


def test_no_capture_within_a_day_is_not_measured_never_worse(call):
    r = call(form(ticked=True), hours_away=60)
    assert r.status == 'verified' and 'not_measured:consent_wording' in r.labels


def test_a_new_capture_rechecks_the_calls_that_used_the_page(call, company):
    from apps.captures.capture import capture_page
    from tests.captures.test_capture import FakeBrowser
    from apps.captures.browser import Shot
    call()
    FakeBrowser.answer = Shot(True, png=b'png', text='x', measurements=form(ticked=True))
    capture_page(ConsentPage.objects.get(), FakeBrowser(), now=timezone.now() - timedelta(days=2, hours=-1))
    assert Recheck.objects.filter(reason='page_captured').exists()
    run_rechecks()
    assert ConsentResult.objects.get(variant='strict').primary_code == 'NP_PRETICKED'


def test_the_real_browser_reads_a_pre_ticked_form(settings):
    """Real Chromium on sample forms (skipped where no browser is installed)."""
    import shutil
    path = shutil.which('chromium') or shutil.which('chromium-browser')
    if not path:
        pytest.skip('no Chromium here')
    from playwright.sync_api import sync_playwright

    from apps.captures.browser import MEASURE_JS
    page_html = ('<body style="font-family:Arial"><form><input type=tel name=phone><label><input type=checkbox {tick}> I agree</label>'
                 '<p style="font-size:{size}px;color:{colour}">By clicking Get My Quote, I agree that SunPath Residential Solar may call '
                 'and text me at the number provided using an autodialer. Consent is not a condition of purchase.</p>'
                 '<button type=submit>Get My Quote</button></form></body>')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=path)
        tab = browser.new_page(viewport={'width': 390, 'height': 844})
        found = {}
        for name, html in (('bad', page_html.format(tick='checked', size=9, colour='#bbb')), ('fair', page_html.format(tick='', size=14, colour='#333'))):
            tab.set_content(html)
            found[name] = evaluate({'390x844': tab.evaluate(MEASURE_JS)}, 'SunPath Residential Solar')
        browser.close()
    assert found['bad']['codes'] == ['NP_PRETICKED', 'WK_WORDING']
    assert found['fair']['codes'] == [] and found['fair']['items']['CC_SELLER_NAMED'] == 'pass'
