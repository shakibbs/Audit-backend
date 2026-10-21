from django.apps import AppConfig


class ConsentConfig(AppConfig):
    name = 'apps.consent'
    label = 'consent'
    verbose_name = 'Consent'

    def ready(self):
        from django.db.models.signals import post_save

        from apps.contacts.models import PhoneEpoch
        from apps.optouts.models import OptOutEvent
        from apps.rulebook.signals import rules_changed
        from apps.sync import handoff

        from . import keeping
        from .proofs import proofs_seen
        # After the certificate scanner (its claims exist by now) and the normalizer (the contact is saved).
        for receivers, receiver in ((handoff.RECEIVERS, proofs_seen), (handoff.RECEIVERS, keeping.contact_seen),
                                    (handoff.SEEN, keeping.records_seen), (handoff.SWEEP_DONE, keeping.sweep_done)):
            if receiver not in receivers:
                receivers.append(receiver)
        # Something new that can change results queues a recheck of just the contacts it touches.
        from apps.certificates import claim as certificate_claims
        if keeping.phone_checked not in certificate_claims.PHONE_CHECKED:
            certificate_claims.PHONE_CHECKED.append(keeping.phone_checked)
        from apps.captures import capture as page_captures
        if keeping.page_captured not in page_captures.CAPTURED:
            page_captures.CAPTURED.append(keeping.page_captured)
        post_save.connect(keeping.optout_saved, sender=OptOutEvent, dispatch_uid='consent_optout')
        post_save.connect(keeping.epoch_saved, sender=PhoneEpoch, dispatch_uid='consent_epoch')
        rules_changed.connect(keeping.rules_changed, dispatch_uid='consent_rules')
