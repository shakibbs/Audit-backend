from django.apps import AppConfig


class ContactsConfig(AppConfig):
    name = 'apps.contacts'
    label = 'contacts'
    verbose_name = 'Contacts (normalizer)'

    def ready(self):
        from apps.sync import handoff

        from .epochs import crm_record_seen
        from .normalize import normalize_record
        for receiver in (normalize_record, crm_record_seen):  # every call or text → a contact; CRM people → owner signals
            if receiver not in handoff.RECEIVERS:
                handoff.RECEIVERS.append(receiver)
