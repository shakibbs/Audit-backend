"""The fixed words of every metric and audit domain (names, what they measure, units). Same for every client; the
portal reads them from here, never from sample data. Values always come from the engines."""

# code: (name, group, definition, source, unit, better)
METRICS = {
    'M01': ('Consent Coverage', 'Permission', 'Contacts whose legal basis requires proof, with status VERIFIED or WEAK, over all such contacts.', 'CiV', '%', 'higher'),
    'M02': ('Consent Status Mix', 'Permission', 'Contacts by consent status, split by legal basis and primary reason code.', 'CiV', '', 'none'),
    'M03': ('Certificate Validity', 'Permission', 'Pairs whose certificate opens at the provider or from CiV’s stored copy and agrees with every other source.', 'CiV', '%', 'higher'),
    'M04': ('Form Wording Pass Rate', 'Permission', 'Consent page versions passing every required checklist item; optional misses are warnings.', 'CiV', '%', 'higher'),
    'M05': ('Form Change Alerts', 'Permission', 'Consent pages whose normalised hash changed since the last capture.', 'CiV', '', 'lower'),
    'M06': ('Lead Traceability', 'Permission', 'Web leads traced to a vendor or your own form, a capture page, a time and a certificate.', 'CiV', '%', 'higher'),
    'M07': ('Vendor Terms on File', 'Permission', 'Active vendors with an unexpired contract containing every required clause.', 'AI', '%', 'higher'),
    'M08': ('Opt-out Propagation Time', 'Stopping', 'Hours from an opt-out until every contacting system suppresses the number.', 'CiV', 'h', 'lower'),
    'M09': ('Opt-outs Unprocessed at Deadline', 'Stopping', 'Opt-outs not processed within 10 business days, recipient time zone.', 'CiV', '', 'lower'),
    'M10': ('Contacts After Opt-out', 'Stopping', 'Contacts at or after an in-scope opt-out plus the grace period.', 'CiV', '', 'lower'),
    'M11': ('Pre-Contact Reassigned Checks', 'Who you contact', 'Robocalls made long after consent that were preceded by your own check after the latest monthly update.', 'Client', '%', 'higher'),
    'M12': ('Internal List Contacts', 'Who you contact', 'Contacts to numbers after they entered your internal do-not-contact list.', 'Client', '', 'lower'),
    'M13': ('DNC Scrub Record Check', 'Who you contact', 'Scrub age at contact, and contacts to flagged numbers in separate buckets.', 'Client', '%', 'lower'),
    'M14': ('Litigator List Contacts', 'Who you contact', 'Contacts to numbers on your own litigator list. Never scored.', 'Client', '', 'none'),
    'M15': ('Cross-border Contacts', 'Who you contact', 'Contacts to numbers outside the United States.', 'CiV', '', 'none'),
    'M16': ('Out-of-Hours Contacts', 'How you contact', 'Contacts outside permitted hours in the recipient’s own time zone.', 'CiV', '', 'lower'),
    'M17': ('Over-Limit Contacts', 'How you contact', 'Contacts beyond a state frequency limit.', 'CiV', '', 'lower'),
    'M18': ('Restricted-Holiday Contacts', 'How you contact', 'Contacts on dates a state restricts.', 'CiV', '', 'lower'),
    'M19': ('Robo-contact Required-Proof Count', 'How you contact', 'Robocalls and robotexts lacking the proof type their category requires.', 'CiV', '', 'lower'),
    'M20': ('Disclosure Check', 'How you contact', 'Reviewed calls and templates carrying every required disclosure.', 'AI', '%', 'higher'),
    'M21': ('Caller ID Quality', 'How you contact', 'Calls with a valid caller ID that answers a CiV callback.', 'CiV', '%', 'higher'),
    'M31': ('Abandoned-Call Rate', 'How you contact', 'Answered marketing calls not connected to a live agent within two seconds.', 'CiV', '%', 'lower'),
    'M22a': ('Proof Completeness', 'Records and controls', 'Numbers where every applicable proof element is present.', 'CiV', '%', 'higher'),
    'M22b': ('Conduct Pass Rate', 'Records and controls', 'Numbers with no opt-out, internal-list, hours, frequency or holiday issue.', 'CiV', '%', 'higher'),
    'M23': ('Record Age Coverage', 'Records and controls', 'Numbers whose records cover the lawsuit window and the retention rule.', 'CiV', '%', 'higher'),
    'M24': ('Complaint Resolution', 'Records and controls', 'Complaints resolved against your target.', 'Client', '%', 'higher'),
    'M25a': ('Training Currency', 'Records and controls', 'Contacting agents with a training record inside 365 days.', 'AI', '%', 'higher'),
    'M25b': ('Acquired List Proof', 'Records and controls', 'Acquired lists whose sampled numbers show a consent chain.', 'CiV', '%', 'higher'),
    'M26': ('Few-Signal Lead Rate', 'Lead provenance', 'Leads showing few risk signals.', 'CiV', '%', 'higher'),
    'M27': ('Consent Page Match Rate', 'Lead provenance', 'Certificate snapshots matching CiV’s own capture.', 'CiV', '%', 'higher'),
    'M28': ('Consent Completeness Rate', 'Lead provenance', 'Leads passing every required checklist item.', 'CiV', '%', 'higher'),
    'M29': ('Vendor Grade Distribution', 'Lead provenance', 'Vendors at each grade over 90 days.', 'CiV', '', 'none'),
    'M30': ('Disputable Lead Value', 'Lead provenance', 'Dispute candidates inside each vendor’s dispute window.', 'CiV', '', 'none'),
    'M34': ('Re-added Opted-out Numbers', 'Stopping', 'Opted-out numbers brought back by an uploaded or imported list.', 'CiV', '', 'lower'),
    'M38': ('Missed Opt-outs', 'Stopping', 'Opt-outs still not marked in one of your tools at the deadline.', 'CiV', '', 'lower'),
    'M41': ('Stop Requests Never Reached', 'Stopping', 'Stop requests that never reached every tool by the deadline.', 'CiV', '', 'lower'),
    'M42': ('Added Within 10 Business Days', 'Stopping', 'Stop requests marked in every tool before the deadline.', 'CiV', '%', 'higher'),
    'M45': ('Contacts After Naming an Attorney', 'Who you contact', 'People contacted again after they named an attorney.', 'AI', '', 'lower'),
    'M48': ('Contacts After a Wrong-number Reply', 'Who you contact', 'Contacts after a person replied "wrong number".', 'AI', '', 'lower'),
}

# Why a metric has no value when no engine measures it yet (the portal says "Not measured").
NOT_BUILT = {
    'M02': 'Shown on Consent Integrity', 'M03': 'Comes with certificate checks', 'M04': 'Comes with consent page checks',
    'M05': 'Comes with consent page checks', 'M06': 'Comes with lead source tracing', 'M13': 'Shown on Who You Contact',
    'M14': 'Your litigator list is not supplied', 'M20': 'Comes with AI review of calls and texts', 'M22a': 'Comes with the evidence file checks',
    'M22b': 'Comes with the evidence file checks', 'M23': 'Comes with record age checks', 'M24': 'Comes with complaint checks',
    'M25a': 'Comes with the AI document reader', 'M25b': 'Comes with acquired list checks', 'M26': 'Comes with lead inspection',
    'M27': 'Comes with lead inspection', 'M28': 'Comes with lead inspection', 'M29': 'Shown on Vendor Ledger',
}

# code: (name, family, what it tests, where the data comes from, metrics)
DOMAINS = {
    'CON': ('Consent proof', 'Permission', 'Every call and text has proof of permission that covers it, of the type its legal basis requires.', 'Consent certificates (Tier 2), CRM (Tier 3)', ['M01', 'M02', 'M03']),
    'WEB': ('Consent forms', 'Permission', 'Consent pages, including affiliate pages, carry every required checklist item and are re-captured daily.', 'CiV page captures (Tier 1)', ['M04', 'M05', 'M28']),
    'LPV': ('Lead source tracing', 'Permission', 'Each web lead traces to a named vendor or your own form, a capture page, a time and a certificate.', 'Lead platform (Tier 3)', ['M06', 'M26', 'M27']),
    'VND': ('Vendor contracts', 'Permission', 'Every active lead vendor has signed terms containing the required clauses.', 'Uploaded contracts (Tier 4)', ['M07', 'M29', 'M30']),
    'AFF': ('Affiliate oversight', 'Permission', 'Affiliate networks supply sub-IDs and publish only approved consent pages.', 'Lead platform (Tier 3), page captures (Tier 1)', ['M06', 'M26']),
    'RND': ('Reassigned numbers', 'Who you contact', 'Robocalls made long after consent are preceded by your own reassigned-number check.', 'Your query logs (Tier 4)', ['M11']),
    'IDN': ('Internal DNC list', 'Who you contact', 'Your own do-not-contact list is honoured in every contacting system.', 'Your internal list (Tier 4)', ['M12']),
    'NDN': ('National DNC', 'Who you contact', 'National DNC scrubs are current and flagged numbers are handled. Runs on your scrub records only.', 'Your scrub records (Tier 4)', ['M13']),
    'SDN': ('State DNC', 'Who you contact', 'State DNC lists are handled where states maintain them. Runs on your scrub records only.', 'Your scrub records (Tier 4)', ['M13']),
    'XBD': ('Non-US numbers', 'Who you contact', 'Contacts to numbers outside the United States are identified for separate review.', 'Dialer, SMS (Tier 3)', ['M15']),
    'DLR': ('Autodialer use', 'How you contact', 'Autodialed contacts carry the consent they require and abandoned calls stay within the limit.', 'Dialer (Tier 3)', ['M19', 'M31']),
    'PRV': ('Prerecorded and AI voice', 'How you contact', 'Prerecorded and AI-voice messages carry written consent and every required disclosure.', 'Dialer, recordings (Tier 3)', ['M19', 'M20']),
    'SMS': ('Text messaging', 'How you contact', 'Texts follow consent, opt-out and quiet-hour rules.', 'SMS platform (Tier 3)', ['M10', 'M16']),
    'CTF': ('Calling hours and frequency', 'How you contact', 'Contacts stay within permitted hours, frequency limits and restricted holidays.', 'Dialer, SMS (Tier 3), CRM addresses (Tier 3)', ['M16', 'M17', 'M18']),
    'IDD': ('Caller ID and identity', 'How you contact', 'Caller ID is valid, answers a callback and identifies the caller.', 'Dialer (Tier 3)', ['M21']),
    'SHK': ('Call authentication', 'How you contact', 'Calls carry STIR/SHAKEN attestation.', 'Dialer / carrier (Tier 3)', ['M21']),
    'VLT': ('Ringless voicemail', 'How you contact', 'Ringless voicemail drops carry the consent they require.', '—', []),
    'REV': ('Opt-out handling', 'Stopping', 'Opt-outs on every channel stop contact in every system, on time. Measured from your real opt-outs.', 'Dialer, SMS, CRM (Tier 3)', ['M08', 'M09', 'M10']),
    'REC': ('Record keeping', 'Records', 'Records exist to show each contact was permitted.', 'All sources', ['M22a', 'M22b']),
    'RET': ('Record retention', 'Records', 'Records are held for the lawsuit window and the five-year record-keeping rule.', 'All sources', ['M23']),
    'SEC': ('Data security', 'Records', 'Consumer data is protected and every access is logged.', 'Connector metadata (Tier 3), uploads (Tier 4)', []),
    'GOV': ('Policies and training', 'Company controls', 'Written policies exist and every contacting agent is trained.', 'Uploaded policies and training logs (Tier 4)', ['M25a']),
    'INC': ('Complaint handling', 'Company controls', 'Complaints are logged and resolved within target.', 'Your complaint log (Tier 4)', ['M24']),
    'PLT': ('Calling platforms', 'Company controls', 'Calling and texting platforms are configured and registered correctly.', 'Connector metadata (Tier 3)', []),
    'MNA': ('Acquired lead lists', 'Company controls', 'Purchased or inherited lists carry a consent chain.', 'Uploaded lists (Tier 4)', ['M25b']),
}
OUTSIDE_SCORE = {'NDN', 'SDN'}  # shown, never part of the Audit Score


def domains_of(code: str) -> list[str]:
    return [d for d, row in DOMAINS.items() if code in row[4]]


def complete(found: list[dict]) -> list[dict]:
    """Every catalogue metric, in catalogue order, with its fixed words; one no engine sent says "Not measured"."""
    by = {m['code']: m for m in found}
    out = []
    for code, (name, group, definition, source, unit, better) in METRICS.items():
        m = by.pop(code, None) or {'code': code, 'value': None, 'display': 'Not measured', 'note': '',
                                    'notMeasured': NOT_BUILT.get(code, 'Not measured yet'), 'history': [None, None, None, None]}
        out.append({'name': name, 'group': group, 'definition': definition, 'source': source, 'unit': unit, 'better': better,
                    'domains': domains_of(code), 'evidence': '', 'note': '', 'notMeasured': None, 'history': [None, None, None, None],
                    **{k: v for k, v in m.items() if v is not None or k == 'value'}})
    return out + [{'name': m['code'], 'group': '', 'definition': '', 'source': 'CiV', 'unit': '', 'better': 'none', 'domains': [],
                   'evidence': '', 'note': '', 'notMeasured': None, 'history': [None, None, None, None], **m} for m in by.values()]
