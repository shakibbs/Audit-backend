"""Plain words and pill color for each logged action, shared by the admin list and dashboard."""
ACTION_LABEL = {
    'sign_in': ('Signed in', 'green'), 'sign_in_failed': ('Failed sign-in', 'red'), 'sign_in_locked': ('Locked out', 'amber'),
    'sign_out': ('Signed out', 'gray'), 'password_reset_requested': ('Asked for reset', 'gray'),
    'password_reset_done': ('Reset password', 'teal'), 'password_link_sent': ('Password link sent', 'teal'),
    'invite_sent': ('Invite sent', 'teal'), 'invite_accepted': ('Joined', 'green'), 'invite_cancelled': ('Invite cancelled', 'gray'),
    'user_added': ('User added', 'teal'), 'user_changed': ('User changed', 'gray'), 'user_turned_off': ('User turned off', 'amber'),
    'document_added': ('Document added', 'teal'), 'document_changed': ('Document changed', 'gray'),
    'document_removed': ('Document removed', 'amber'), 'document_opened': ('Document opened', 'gray'),
    'contract_added': ('Contract added', 'teal'), 'contract_changed': ('Contract changed', 'gray'),
    'client_status_changed': ('Stage changed', 'teal'),
    'onboarding_step_done': ('Onboarding step done', 'green'), 'onboarding_step_undone': ('Onboarding step undone', 'amber'),
    'connection_added': ('Connection added', 'teal'), 'connection_changed': ('Connection changed', 'gray'),
    'connection_key_changed': ('Key replaced', 'amber'), 'connection_tested': ('Connection tested', 'gray'),
    'connection_removed': ('Connection removed', 'amber'), 'connect_link_sent': ('Connect link sent', 'teal'),
    'reg_change_added': ('Law change added', 'teal'), 'reg_change_changed': ('Law change edited', 'gray'),
    'reg_change_removed': ('Law change removed', 'amber'),
    'optout_readded': ('Opted-out number re-added', 'red'),
    'certificate_lost': ('Certificate lost', 'red'), 'certificate_deadline_close': ('Certificate deadline close', 'amber'),
    'source_stale': ('Source stale', 'amber'), 'source_recovered': ('Source back', 'green'),
    'reg_change_read': ('Law change read', 'gray'), 'rule_update_reviewed': ('Lawyer reviewed a rule', 'teal'),
    'law_change_suggested': ('Law change suggested', 'teal'),
    'rule_update_approved': ('Rule updated', 'green'), 'rule_update_rejected': ('Rule update rejected', 'gray'),
    'proof_request_answered': ('Proof request answered', 'teal'), 'proof_file_opened': ('Proof file opened', 'gray'),
    'proof_reviewed': ('Proof checked', 'teal'), 'upload_received': ('File uploaded', 'teal'), 'lead_source_marked': ('Lead source check marked', 'gray'),
    'attestation_viewed': ('Insurer opened your sheet', 'teal'), 'attestation_sent': ('Sheet sent to insurer software', 'teal'),
    'attestation_send_failed': ('Sheet send to insurer failed', 'amber'),
    'client_key_created': ('Phone-code key made', 'teal'), 'client_key_destroyed': ('Phone-code key destroyed', 'red'),
}


def action_label(action: str) -> tuple[str, str]:
    return ACTION_LABEL.get(action, (action.replace('_', ' ').capitalize(), 'gray'))
