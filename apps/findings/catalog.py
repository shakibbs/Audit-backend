"""What each measured problem is called, how serious it is (owner decision 2026-10-21) and where it belongs. Titles
are noun phrases of what CiV observed, never "violation", "illegal" or "you must" (spec §9 wording rules)."""
HIGH, MEDIUM, LOW = 'High', 'Medium', 'Low'

# metric: (title, severity, domain, unit)
MEASURED = {
    'M10': ('Contacts after an opt-out', HIGH, 'REV', 'contact'),
    'M12': ('Contacts after joining your internal do-not-call list', HIGH, 'IDN', 'contact'),
    'M48': ('Contacts after a “wrong number” reply', HIGH, 'RND', 'contact'),
    'M45': ('Contacts after naming an attorney', HIGH, 'LIT', 'person'),
    'M34': ('Opted-out numbers brought back by an uploaded list', HIGH, 'REV', 'number'),
    'M16': ('Out-of-hours contacts', MEDIUM, 'CTF', 'contact'),
    'M18': ('Contacts on restricted holidays', MEDIUM, 'CTF', 'contact'),
    'M01': ('Contacts without consent proof that covers them', MEDIUM, 'CON', 'contact'),
    'M08': ('Slow opt-out handling across your tools', MEDIUM, 'REV', None),
    'M09': ('Opt-outs not handled by the deadline', MEDIUM, 'REV', 'opt-out'),
    'M41': ('Stop requests that never reached every tool', MEDIUM, 'REV', 'stop request'),
    'M42': ('Stop requests added to your tools late', LOW, 'REV', None),
    'M15': ('Contacts to numbers outside the United States', LOW, 'XBD', 'contact'),
    'M17': ('Contacts over state frequency limits', LOW, 'CTF', 'contact'),
    'M19': ('Robocalls or robotexts without the proof their category needs', LOW, 'DLR', 'contact'),
    'M31': ('Abandoned-call rate above the limit', LOW, 'DLR', None),
    'M11': ('Contacts without a recent reassigned-number check', LOW, 'RND', None),
}
# missing client data (worst case): (title, domain, why)
WORST = {
    'M12': ('Internal do-not-call list not supplied', 'IDN', 'Counted as the worst case until you upload your internal do-not-call list in the Upload centre.'),
    'M11': ('Reassigned-number query logs not supplied', 'RND', 'Counted as “not checked” until you upload your reassigned-number query logs in the Upload centre.'),
}
WORST_SEVERITY = MEDIUM
SKIP = {'M38'}  # the same problem as M41 (shown, never a second finding)

# Common responses: DRAFTS by CiV for the client's lawyers to review (owner decision 2026-10-16: no CiV lawyer). They
# describe what other companies commonly check; never "you must", never legal advice (spec §9).
RESPONSES = {
    'M10': 'Companies commonly check that STOP replies and spoken opt-outs reach the do-not-contact list in every dialer and texting tool, and that campaigns load that list before each run.',
    'M12': 'Companies commonly check that every campaign loads the internal do-not-call list before dialing, including lists uploaded by hand.',
    'M48': 'Companies commonly mark a number as a new owner when someone says "wrong number", so the old consent is not used again.',
    'M45': 'Companies commonly route anyone who names an attorney to their legal team and stop marketing contact while it is reviewed.',
    'M34': 'Companies commonly check uploaded lists against the opt-out list before they reach a campaign.',
    'M16': 'Companies commonly set calling windows by the recipient\'s state and time zone, using the stricter window when the location is unsure.',
    'M18': 'Companies commonly pause campaigns on the restricted holidays of the states they call into.',
    'M01': 'Companies commonly keep a consent record (certificate, signed form or customer record) for every number before it is called or texted.',
    'M08': 'Companies commonly connect opt-outs from every channel to every contacting tool, so a stop in one tool reaches the others the same day.',
    'M09': 'Companies commonly review open opt-outs daily so each one reaches every tool well before the 10-business-day deadline.',
    'M41': 'Companies commonly check each stop request against every dialer, texting tool and CRM until all of them show it.',
    'M42': 'Companies commonly add stop requests to every tool the same day they arrive.',
    'M15': 'Companies commonly filter numbers outside the United States from campaigns that are set up for US rules only.',
    'M17': 'Companies commonly cap how often one person is contacted in a day across all campaigns.',
    'M19': 'Companies commonly send leads whose only proof is a customer relationship to manually dialed campaigns.',
    'M31': 'Companies commonly lower the predictive dialing ratio until the 30-day abandoned rate is under the limit.',
    'M11': 'Companies commonly check the reassigned-numbers database before calling numbers whose consent is older than a few months.',
    'M12-worst': 'Upload your internal do-not-call list in the Upload centre so CiV can measure contacts after it.',
    'M11-worst': 'Upload your reassigned-number query logs in the Upload centre so CiV can measure your checks.',
}
