"""Base for every admin section: adds the portal-style page heading above lists and forms, and writes every add,
change and delete into the access log with what changed (QA 2026-10-23: "every sign-in, sign-out and change")."""
from unfold.admin import ModelAdmin

HIDDEN = ('password', 'key', 'secret', 'token', 'hash')  # never written into the log, only the field name


def _shown(form, name, value) -> str:
    field = form.fields.get(name)
    if any(word in name for word in HIDDEN):
        return '•••'
    if isinstance(value, (list, tuple, set)) or hasattr(value, 'all'):  # several choices
        items = value.all() if hasattr(value, 'all') else value
        return ', '.join(str(v) for v in items)[:60] or '—'
    choices = dict(getattr(field, 'choices', []) or []) if field is not None and not hasattr(field, 'queryset') else {}
    if isinstance(value, str | int | bool) and value in choices:
        value = choices[value]
    elif field is not None and hasattr(field, 'queryset') and value not in (None, ''):
        found = field.queryset.filter(pk=getattr(value, 'pk', value)).first()
        value = found if found is not None else value
    text = '—' if value in (None, '') else str(value)
    return text if len(text) <= 60 else text[:57] + '…'


def client_of(obj) -> int | None:
    from apps.clients.models import Client
    if isinstance(obj, Client):
        return obj.pk
    return getattr(obj, 'client_id', None)


class CivModelAdmin(ModelAdmin):
    eyebrow = 'CiV admin'  # small teal label above the title
    page_sub = ''  # one line saying what the page is for
    list_before_template = 'admin_panel/page_head_list.html'
    change_form_outer_before_template = 'admin_panel/page_head_form.html'
    access_log = True  # False on pages that write their own, more specific entries
    access_log_deletes = True  # False where delete_model writes its own line
    access_log_inlines = False  # True: also log changes made in this page's tabs (pages whose tabs do not log themselves)

    def construct_change_message(self, request, form, formsets, add=False):
        """Remembers "Field: old → new" for the log line (the form still holds both values here)."""
        changes = []
        for name in form.changed_data:
            label = getattr(form.fields.get(name), 'label', None) or name.replace('_', ' ').capitalize()
            if add:
                changes.append(f'{label}: {_shown(form, name, form.cleaned_data.get(name))}')
            else:
                changes.append(f'{label}: {_shown(form, name, form.initial.get(name))} → {_shown(form, name, form.cleaned_data.get(name))}')
        request._civ_changes = changes
        return super().construct_change_message(request, form, formsets, add)

    def _log(self, request, action: str, obj, changes=()) -> None:
        if not self.access_log:
            return
        from apps.access_log.recorder import record
        what = f'{obj._meta.verbose_name.capitalize()}: {obj}'
        if changes:
            what += ' · ' + '; '.join(changes)
        record(action, request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
               client_id=client_of(obj), object=what[:254])

    def log_addition(self, request, obj, message):
        self._log(request, 'record_added', obj, getattr(request, '_civ_changes', ()))
        return super().log_addition(request, obj, message)

    def log_change(self, request, obj, message):
        changes = getattr(request, '_civ_changes', None)
        if changes is None or changes:  # an action button (no form) or a real change; a save with nothing changed is quiet
            self._log(request, 'record_changed', obj, changes or ())
        return super().log_change(request, obj, message)

    def log_deletions(self, request, queryset):
        if self.access_log_deletes:
            for obj in queryset:
                self._log(request, 'record_deleted', obj)
        return super().log_deletions(request, queryset)

    def save_formset(self, request, form, formset, change):
        if self.access_log and self.access_log_inlines:
            for sub_form in formset.forms:
                if sub_form in getattr(formset, 'deleted_forms', []) or not sub_form.has_changed() or not sub_form.instance.pk:
                    continue
                changes = [f'{getattr(sub_form.fields.get(n), "label", n)}: {_shown(sub_form, n, sub_form.initial.get(n))} → '
                           f'{_shown(sub_form, n, sub_form.cleaned_data.get(n))}' for n in sub_form.changed_data]
                self._log(request, 'record_changed', sub_form.instance, changes)
        return super().save_formset(request, form, formset, change)
