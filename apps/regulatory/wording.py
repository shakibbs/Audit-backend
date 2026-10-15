"""Banned wording (same list as the portal's src/lib/wording.ts): client-visible text may never contain these."""
import re

BANNED = ['violation', 'violations', 'breach', 'breaches', 'illegal', 'compromised', 'fake', 'fraud', 'fraudulent', 'genuine',
          'compliant', 'non-compliant', 'noncompliant', 'ensures compliance', 'protects you', 'guaranteed', 'guarantee']
_PATTERNS = [(w, re.compile(rf'(^|[^a-z]){w.replace("-", "[-\\s]").replace(" ", "[-\\s]")}(?=$|[^a-z])', re.I)) for w in BANNED]


def banned_words(text: str) -> list[str]:
    return [word for word, pattern in _PATTERNS if pattern.search(text or '')]
