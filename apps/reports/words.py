"""The banned-word check every report passes before release (spec §9 wording rules)."""
import re

BANNED = [r'violations?', r'breach(es)?', r'illegal', r'compromised consent', r'fake leads?', r'fraud\w*', r'genuine',
          r'non-?compliant', r'ensures? compliance', r'protects you', r'guaranteed?', r'scrub(bed|bing)?', r'screen(ing)?',
          r'court-ready', r'you must', r'fix steps?', r'leads to claim back', r'stored write-once']
PATTERN = re.compile(r'\b(' + '|'.join(BANNED) + r')\b', re.I)


def banned_words(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in PATTERN.finditer(text)})
