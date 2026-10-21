"""Module 13 step 1: the law watcher reads the Federal Register (pretend API here), keeps calling-rule items once each,
and shows them to CiV staff; the Rulebook never changes by itself."""
from datetime import date

import pytest

from apps.regulatory.models import LawItem
from apps.regulatory.watcher import matches, refresh
from apps.rulebook.models import RuleValue
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db

DOCS = [
    {'document_number': '2026-1', 'type': 'Proposed Rule', 'title': 'Strengthening the Ability of Consumers To Stop Robocalls',
     'abstract': 'Revocation of consent under the Telephone Consumer Protection Act.', 'publication_date': '2026-09-30',
     'effective_on': None, 'html_url': 'https://www.federalregister.gov/d/2026-1', 'agencies': [{'name': 'Federal Communications Commission'}]},
    {'document_number': '2026-2', 'type': 'Rule', 'title': 'Telecommunications Relay Service ASCII Format Requirement',
     'abstract': 'Relay services for people who are deaf.', 'publication_date': '2026-09-10', 'effective_on': '2026-10-10',
     'html_url': 'https://www.federalregister.gov/d/2026-2', 'agencies': []},
]


def pretend(params):
    assert params['conditions[type][]'] == ['RULE', 'PRORULE']
    return {'results': DOCS, 'total_pages': 1}


def test_keeps_calling_rules_only_and_each_once():
    assert refresh(date(2026, 10, 22), pretend) == 1
    item = LawItem.objects.get()
    assert (item.ref, item.kind, item.state) == ('2026-1', 'Proposed Rule', 'new')
    assert {'robocall', 'revocation', 'telephone consumer protection'} <= set(item.matched)
    assert refresh(date(2026, 10, 23), pretend) == 0  # already saved


def test_relay_services_are_not_calling_rules():
    assert matches(DOCS[1]) == []


def test_the_rulebook_never_changes_by_itself(client):
    from apps.rulebook.loader import RULEBOOK_DIR, load
    load(RULEBOOK_DIR / 'v3.0.yaml')
    before = list(RuleValue.objects.values_list('key', 'value'))
    refresh(date(2026, 10, 22), pretend)
    assert list(RuleValue.objects.values_list('key', 'value')) == before
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    page = client.get('/civ-admin/regulatory/lawitem/').content.decode()
    assert 'Strengthening the Ability of Consumers To Stop Robocalls' in page
    client.post('/civ-admin/regulatory/lawitem/', {'action': 'dismiss', '_selected_action': [LawItem.objects.get().pk]})
    assert LawItem.objects.get().state == 'dismissed'


def test_sorting_rules_level_stage_and_the_earlier_proposal():
    from apps.rulebook.loader import RULEBOOK_DIR, load
    load(RULEBOOK_DIR / 'v3.0.yaml')
    final = {'document_number': '2027-9', 'type': 'Rule', 'title': 'Revocation of consent: final rule',
             'abstract': 'Callers must honor opt-out requests made by any reasonable means under the Telephone Consumer Protection Act.',
             'publication_date': '2026-10-15', 'effective_on': '2026-10-20', 'html_url': 'https://www.federalregister.gov/d/2027-9',
             'agencies': [], 'docket_ids': ['CG Docket No. 02-278']}
    proposed = {**DOCS[0], 'docket_ids': ['CG Docket No. 02-278']}
    refresh(date(2026, 10, 22), lambda params: {'results': [proposed, final], 'total_pages': 1})
    items = {i.ref: i for i in LawItem.objects.all()}
    p, f = items['2026-1'], items['2027-9']
    assert 'optout_deadline_business_days' in f.rule_keys and (f.level, f.stage) == ('High', 'in_force')
    assert (p.level, p.stage) == ('Medium', 'proposed') and f.follows_id == p.pk


def test_the_admin_dashboard_counts_high_items(client):
    from apps.rulebook.loader import RULEBOOK_DIR, load
    load(RULEBOOK_DIR / 'v3.0.yaml')
    LawItem.objects.create(source='federal_register', ref='x', kind='Rule', title='t', published_on=date(2026, 10, 1), url='https://x.y',
                           level='High', stage='final')
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    assert 'New law items' in client.get('/civ-admin/').content.decode()


def test_the_item_page_shows_plain_words_not_code(client):
    item = LawItem.objects.create(source='federal_register', ref='y', kind='Proposed Rule', title='Robocalls', published_on=date(2026, 10, 1),
                                  url='https://x.y', rule_keys=['M21'], matched=['robocall', 'call authentication'], stage='proposed')
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    page = client.get(f'/civ-admin/regulatory/lawitem/{item.pk}/change/').content.decode()
    assert 'robocall, call authentication' in page and 'Proposed (not law yet)' in page and 'None given' in page
    assert '[\n' not in page.split('Calling words found')[1][:300]


def test_the_item_page_shows_the_value_in_force_of_each_rule_it_may_change(client):
    from apps.rulebook.loader import RULEBOOK_DIR, load
    load(RULEBOOK_DIR / 'v3.0.yaml')
    item = LawItem.objects.create(source='federal_register', ref='z', kind='Rule', title='Opt-outs', published_on=date(2026, 10, 1),
                                  url='https://x.y', rule_keys=['optout_deadline_business_days', 'M21'], stage='final')
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    page = client.get(f'/civ-admin/regulatory/lawitem/{item.pk}/change/').content.decode()
    assert 'optout_deadline_business_days' in page and 'now 10' in page and 'a metric CiV measures' in page


class PretendDrafter:
    model = 'pretend-ai'

    def __init__(self):
        self.seen = []

    def __call__(self, item):
        self.seen.append(item)
        return {'summary': 'Callers must stop within 5 business days.', 'confidence': 0.92,
                'drafts': [{'key': 'optout_deadline_business_days', 'value': 5, 'shown': '5 business days', 'effective_from': '2027-01-01',
                            'quote': 'within five business days'},
                           {'key': 'made_up_rule', 'value': 1, 'shown': '1', 'quote': 'something'},
                           {'key': 'calling_hours', 'value': {}, 'shown': 'x'}]}  # no quote: never kept


def test_no_ai_chosen_means_nothing_is_sent():
    from apps.regulatory.drafting import draft_new
    LawItem.objects.create(source='federal_register', ref='a1', kind='Rule', title='t', published_on=date(2026, 10, 1), url='https://x.y')
    assert draft_new() == 0 and LawItem.objects.get().ai_done_at is None


def test_the_ai_drafts_with_quotes_and_reads_the_full_text_only_for_high_items(monkeypatch):
    from apps.regulatory import drafting
    from apps.rulebook.loader import RULEBOOK_DIR, load
    load(RULEBOOK_DIR / 'v3.0.yaml')
    monkeypatch.setattr(drafting, 'full_text', lambda item: 'FULL TEXT within five business days')
    high = LawItem.objects.create(source='federal_register', ref='h', kind='Rule', title='Opt-outs', published_on=date(2026, 10, 1),
                                  url='https://x.y', text_url='https://x.y/raw', level='High', rule_keys=['optout_deadline_business_days'])
    LawItem.objects.create(source='federal_register', ref='m', kind='Proposed Rule', title='Other', published_on=date(2026, 10, 2),
                           url='https://x.y', level='Medium')
    ai = PretendDrafter()
    drafting.use(ai)
    try:
        assert drafting.draft_new() == 2
    finally:
        drafting.use(None)
    high.refresh_from_db()
    assert high.ai_read == 'full_text' and high.ai_model == 'pretend-ai' and high.ai_confidence == 0.92
    assert [d['key'] for d in high.ai_drafts] == ['optout_deadline_business_days', 'made_up_rule']
    assert high.ai_drafts[0]['known'] and not high.ai_drafts[1]['known']
    texts = {s['title']: s['text'] for s in ai.seen}
    assert texts['Opt-outs'].startswith('FULL TEXT') and texts['Other'] == ''
    assert LawItem.objects.get(ref='m').ai_read == 'summary'


def test_the_draft_box_on_the_item_page(client):
    item = LawItem.objects.create(source='federal_register', ref='d', kind='Rule', title='Opt-outs', published_on=date(2026, 10, 1),
                                  url='https://x.y')
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    assert 'No AI chosen yet' in client.get(f'/civ-admin/regulatory/lawitem/{item.pk}/change/').content.decode()


def test_a_final_rule_becomes_a_law_change_whose_approval_ends_the_old_value(client):
    from datetime import timedelta

    from apps.regulatory.approve import approve
    from apps.regulatory.models import RegChange, RuleUpdate
    from apps.rulebook.loader import RULEBOOK_DIR, load
    from apps.rulebook.lookup import RuleSet
    load(RULEBOOK_DIR / 'v3.0.yaml')
    item = LawItem.objects.create(source='federal_register', ref='f1', kind='Rule', title='Opt-outs within five days',
                                  published_on=date(2026, 10, 15), effective_on=date(2027, 1, 1), url='https://www.federalregister.gov/d/f1',
                                  rule_keys=['optout_deadline_business_days', 'M21'], summary='Official abstract.', ai_summary='Stop within 5 days.',
                                  ai_model='pretend-ai', ai_drafts=[{'key': 'optout_deadline_business_days', 'value': 5, 'shown': '5 business days',
                                                                     'effective_from': '2027-01-01', 'quote': 'within five business days', 'known': True}])
    staff = StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    client.force_login(staff)
    assert 'Create a law change from this item' in client.get(f'/civ-admin/regulatory/lawitem/{item.pk}/change/').content.decode()
    assert 'AI-drafted value' in client.get(f'/civ-admin/regulatory/lawitem/{item.pk}/make-change/').content.decode()
    client.post(f'/civ-admin/regulatory/lawitem/{item.pk}/make-change/')
    item.refresh_from_db()
    change = RegChange.objects.get(law_items=item)
    assert (item.state, change.status, change.review, change.summary) == ('used', 'adopted', 'to_check', 'Stop within 5 days.')
    assert change.rule_keys == ['optout_deadline_business_days'] and change.metrics == ['M21']
    update = RuleUpdate.objects.get(reg_change=change)
    assert (update.value, update.status, update.state) == (5, 'proposed', 'waiting')
    approve(update, staff)
    rules = RuleSet('internal')
    assert rules.get('optout_deadline_business_days', on=date(2026, 12, 31)).value == 10  # the old value, ended the day before
    assert rules.get('optout_deadline_business_days', on=date(2027, 1, 1)).value == 5


def test_a_proposed_rule_becomes_a_law_change_without_rule_updates(client):
    from apps.regulatory.from_item import make_change
    from apps.regulatory.models import RuleUpdate
    staff = StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    item = LawItem.objects.create(source='federal_register', ref='p1', kind='Proposed Rule', title='Robocalls', published_on=date(2026, 10, 1),
                                  url='https://x.y', ai_drafts=[{'key': 'calling_hours', 'value': {}, 'shown': 'x', 'quote': 'q', 'known': True}])
    change = make_change(item, staff)
    assert change.status == 'proposed' and change.effective_text == 'Not law yet (proposed)' and not RuleUpdate.objects.filter(reg_change=change).exists()
    assert make_change(item, staff) == change  # made once
