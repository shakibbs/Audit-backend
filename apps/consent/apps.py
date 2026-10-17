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
        post_save.connect(keeping.optout_saved, sender=OptOutEvent, dispatch_uid='consent_optout')
        post_save.connect(keeping.epoch_saved, sender=PhoneEpoch, dispatch_uid='consent_epoch')
        rules_changed.connect(keeping.rules_changed, dispatch_uid='consent_rules')
