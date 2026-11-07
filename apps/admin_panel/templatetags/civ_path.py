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


@register.filter
def add_button_text(inline_admin_formset) -> str:
    """ "Add a connection" when the tab has none yet, "Add another connection" after (owner, 2026-11-07)."""
    name = str(inline_admin_formset.opts.verbose_name)
    name = name if name[:2].isupper() else name[:1].lower() + name[1:]
    if inline_admin_formset.formset.initial_form_count():
        return f'Add another {name}'
    return f"Add {'an' if name[:1].lower() in 'aeiou' else 'a'} {name}"
