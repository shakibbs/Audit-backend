from django.apps import AppConfig


class StaffConfig(AppConfig):
    name = 'apps.staff'
    label = 'staff'
    verbose_name = 'CiV staff'

    def ready(self):
        from django.contrib.auth.signals import user_logged_in, user_logged_out

        from .models import StaffUser

        def staff_in(sender, request, user, **kwargs):
            if isinstance(user, StaffUser):
                from apps.access_log.recorder import record
                record('staff_sign_in', request=request, actor_kind='staff', actor_id=user.pk, actor_label=user.email)

        def staff_out(sender, request, user, **kwargs):
            if isinstance(user, StaffUser):
                from apps.access_log.recorder import record
                record('staff_sign_out', request=request, actor_kind='staff', actor_id=user.pk, actor_label=user.email)

        user_logged_in.connect(staff_in, dispatch_uid='civ_staff_sign_in')
        user_logged_out.connect(staff_out, dispatch_uid='civ_staff_sign_out')
