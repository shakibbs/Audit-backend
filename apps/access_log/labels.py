"""Plain words and pill color for each logged action, shared by the admin list and dashboard."""
ACTION_LABEL = {
    'sign_in': ('Signed in', 'green'), 'sign_in_failed': ('Failed sign-in', 'red'), 'sign_in_locked': ('Locked out', 'amber'), 'account_locked_everywhere': ('Locked everywhere (attack)', 'red'),
    'quote_requested': ('Quote requested', 'teal'), 'quote_request_accepted': ('Quote accepted', 'teal'),
    'quote_request_done': ('Quote request done', 'gray'), 'litigation_package_made': ('Litigation package made', 'teal'),
    'litigation_package_released': ('Litigation package released', 'green'),
    'litigation_package_downloaded': ('Litigation package downloaded', 'gray'),
    'sign_out': ('Signed out', 'gray'), 'staff_sign_in_failed': ('Failed staff sign-in', 'red'),
    'staff_sign_in_locked': ('Staff sign-in locked', 'amber'), 'password_reset_requested': ('Asked for reset', 'gray'),
    'password_reset_done': ('Reset password', 'teal'), 'password_changed': ('Changed password', 'teal'), 'password_link_sent': ('Password link sent', 'teal'),
    'invite_sent': ('Invite sent', 'teal'), 'invite_accepted': ('Joined', 'green'), 'invite_cancelled': ('Invite cancelled', 'gray'),
    'user_added': ('User added', 'teal'), 'user_changed': ('User changed', 'gray'), 'user_turned_off': ('User turned off', 'amber'),
    'document_added': ('Document added', 'teal'), 'document_changed': ('Document changed', 'gray'),
    'document_removed': ('Document removed', 'amber'), 'document_opened': ('Document opened', 'gray'),
    'contract_added': ('Contract added', 'teal'), 'contract_changed': ('Contract changed', 'gray'),
    'client_status_changed': ('Stage changed', 'teal'), 'client_deleted': ('Company deleted (records kept)', 'red'),
    'client_restored': ('Company restored', 'green'),
    'onboarding_step_done': ('Onboarding step done', 'green'), 'onboarding_step_undone': ('Onboarding step undone', 'amber'),
    'connection_added': ('Connection added', 'teal'), 'connection_changed': ('Connection changed', 'gray'),
    'connection_key_changed': ('Key replaced', 'amber'), 'connection_tested': ('Connection tested', 'gray'),
    'connection_removed': ('Connection removed', 'amber'), 'connect_link_sent': ('Connect link sent', 'teal'),
    'reg_change_added': ('Law change added', 'teal'), 'reg_change_changed': ('Law change edited', 'gray'),
    'reg_change_removed': ('Law change removed', 'amber'), 'rule_update_deleted': ('Draft rule update deleted', 'amber'),
    'optout_readded': ('Opted-out number re-added', 'red'),
    'certificate_lost': ('Certificate lost', 'red'), 'certificate_deadline_close': ('Certificate deadline close', 'amber'),
    'source_stale': ('Source stale', 'amber'), 'source_access_removed': ('Tool refused CiV\'s access', 'red'), 'source_recovered': ('Source back', 'green'),
    'reg_change_read': ('Law change read', 'gray'), 'rule_update_reviewed': ('Lawyer reviewed a rule', 'teal'),
    'law_change_suggested': ('Law change suggested', 'teal'),
    'rule_update_approved': ('Rule updated', 'green'), 'rule_update_rejected': ('Rule update rejected', 'gray'),
    'proof_request_answered': ('Proof request answered', 'teal'), 'proof_file_opened': ('Proof file opened', 'gray'),
    'proof_reviewed': ('Proof checked', 'teal'), 'upload_received': ('File uploaded', 'teal'), 'lead_source_marked': ('Lead source check marked', 'gray'),
    'buyer_invite_resend': ('Insurer invite resent', 'teal'), 'buyer_invite_cancel': ('Insurer invite cancelled', 'gray'),
    'buyer_deleted': ('Insurer deleted by CiV (records kept)', 'red'), 'buyer_restored': ('Insurer restored by CiV', 'green'), 'buyer_user_deleted': ('Insurer person deleted by CiV', 'amber'),
    'attestation_viewed': ('Insurer opened your sheet', 'teal'), 'attestation_sent': ('Sheet sent to insurer software', 'teal'),
    'attestation_send_failed': ('Sheet send to insurer failed', 'amber'),
    'record_added': ('Added', 'teal'), 'record_changed': ('Changed', 'gray'), 'record_deleted': ('Deleted', 'red'),
    'staff_sign_in': ('Staff signed in', 'green'), 'staff_sign_out': ('Staff signed out', 'gray'),
    'staff_password_set': ('Staff password set', 'teal'), 'welcome_link_sent': ('Welcome / password link sent', 'teal'),
    'invite_resent': ('Invite resent', 'teal'), 'wrong_current_password': ('Wrong current password', 'amber'),
    'client_key_created': ('Phone-code key made', 'teal'), 'client_key_destroyed': ('Phone-code key destroyed', 'red'),
}


def action_label(action: str) -> tuple[str, str]:
    return ACTION_LABEL.get(action, (action.replace('_', ' ').capitalize(), 'gray'))


def who(entry) -> str:
    """Plain words for who did it (staff panel, 2026-10-23): CiV's own jobs say "CiV (automatic)", a try before sign-in
    says "Not signed in"; the thing it was about always goes in the Object column, never here."""
    kind = entry.actor_kind
    if kind == 'system':
        return 'CiV (automatic)'
    if kind == 'anonymous':
        return 'Not signed in'
    return entry.actor_label or entry.get_actor_kind_display()
