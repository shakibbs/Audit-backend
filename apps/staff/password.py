"""A CiV staff member changing their own password in the panel: the access log gets a line (QA 2026-10-23), and any
password link still waiting in their email stops working (owner, 2026-10-30): they can ask for a new one."""
from django.contrib import admin


def change_own_password(request, extra_context=None):
    response = admin.site.password_change(request, extra_context)
    if request.method == 'POST' and response.status_code == 302:  # the form was accepted
        from apps.access_log.recorder import record
        closed, _ = request.user.welcomes.filter(used_at__isnull=True).delete()
        record('password_changed', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
               object=f'CiV staff: own password{f" · {closed} unused password link(s) closed" if closed else ""}')
    return response
