"""Plain words and pill color for each logged action, shared by the admin list and dashboard."""
ACTION_LABEL = {
    'sign_in': ('Signed in', 'green'), 'sign_in_failed': ('Failed sign-in', 'red'), 'sign_in_locked': ('Locked out', 'amber'),
    'sign_out': ('Signed out', 'gray'), 'password_reset_requested': ('Asked for reset', 'gray'),
    'password_reset_done': ('Reset password', 'teal'), 'password_link_sent': ('Password link sent', 'teal'),
    'invite_sent': ('Invite sent', 'teal'), 'invite_accepted': ('Joined', 'green'), 'invite_cancelled': ('Invite cancelled', 'gray'),
    'user_changed': ('User changed', 'gray'), 'user_turned_off': ('User turned off', 'amber'),
    'connection_added': ('Connection added', 'teal'), 'connection_changed': ('Connection changed', 'gray'),
    'connection_key_changed': ('Key replaced', 'amber'), 'connection_tested': ('Connection tested', 'gray'),
    'connection_removed': ('Connection removed', 'amber'), 'connect_link_sent': ('Connect link sent', 'teal'),
}


def action_label(action: str) -> tuple[str, str]:
    return ACTION_LABEL.get(action, (action.replace('_', ' ').capitalize(), 'gray'))
