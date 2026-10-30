"""The path at the top of a staff page (owner, 2026-10-31): a name is never shown twice in a row
("Insurers and acquirers › Insurers and acquirers")."""
from django import template

register = template.Library()


@register.filter
def plain_path(parts):
    out = []
    for part in parts or []:
        title = str(part.get('title', '')).strip().lower()
        if out and str(out[-1].get('title', '')).strip().lower() == title:
            out[-1] = part  # keep the later one: it is the page itself, with its own link
            continue
        out.append(part)
    return out
