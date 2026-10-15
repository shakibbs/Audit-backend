from django import forms
from unfold.widgets import UnfoldAdminSelect2MultipleWidget, UnfoldAdminSelect2Widget, UnfoldAdminTextInputWidget

from apps.rulebook.models import RuleValue

from .models import RegChange


def rule_choices() -> list[tuple[str, str]]:
    """Each rule once, shown as "name · meaning" so it can be found by either, in the Rulebook's order."""
    seen: dict[str, str] = {}
    for key, meaning in RuleValue.objects.filter(jurisdiction='US').values_list('key', 'meaning').order_by('section', 'key'):
        seen.setdefault(key, meaning)
    for key in RuleValue.objects.values_list('key', flat=True):  # brand-new rules that exist only for a state
        seen.setdefault(key, '')
    return [(key, f'{key} · {meaning}' if meaning else key) for key, meaning in seen.items()]


class RegChangeForm(forms.ModelForm):
    """Rules are picked from the real Rulebook (no typos); metrics are typed as codes, comma-separated."""
    rule_keys = forms.MultipleChoiceField(label='Rules it touches', required=False, widget=UnfoldAdminSelect2MultipleWidget,
                                          help_text='Type to search by name or meaning; pick as many as needed')
    metrics = forms.CharField(label='Metrics it affects', required=False, help_text='Codes separated by commas, e.g. M16, M17',
                              widget=UnfoldAdminTextInputWidget)

    class Meta:
        model = RegChange
        fields = ['title', 'jurisdiction', 'status', 'announced_on', 'effective_from', 'effective_text', 'summary',
                  'rule_keys', 'metrics', 'source', 'source_url', 'review']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['rule_keys'].choices = rule_choices()
        if self.instance.pk:
            self.initial['metrics'] = ', '.join(self.instance.metrics)

    def clean_metrics(self):
        return [m.strip() for m in self.cleaned_data['metrics'].split(',') if m.strip()]


class RuleUpdateForm(forms.ModelForm):
    """The rule is picked from the Rulebook. Once approved or rejected, an update can no longer be edited."""
    key = forms.ChoiceField(label='Modifies rule', required=False, help_text='Blank = a brand-new rule', widget=UnfoldAdminSelect2Widget)

    class Meta:
        from .models import RuleUpdate
        model = RuleUpdate
        fields = ['key', 'new_key', 'new_meaning', 'jurisdiction', 'value', 'shown', 'status', 'effective_from']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['key'].choices = [('', '— new rule —')] + rule_choices()
        if self.instance.pk and self.instance.state != 'waiting':
            for field in self.fields.values():
                field.disabled = True
