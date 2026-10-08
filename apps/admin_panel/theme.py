"""Look and menu of the CiV admin panel (Unfold theme), in CiV's teal."""
from django.conf import settings
from django.templatetags.static import static
from django.urls import reverse_lazy

# The portal's teal: 600 = --brand, 500 = --brand-2, 700 = --brand-ink, 100 = --brand-soft.
TEAL = {
    '50': '#effaf8', '100': '#e2f2ef', '200': '#bfe6df', '300': '#8dd5c9', '400': '#34c3b1', '500': '#13b5a2',
    '600': '#0e8c7f', '700': '#0a6a60', '800': '#0b5750', '900': '#0c4843', '950': '#062b28',
}

# The portal's neutrals: light page #f4f6f4 and lines #e6e9e5; dark page #0a111c and cards #101b29.
NEUTRAL = {
    '50': '#f4f6f4', '100': '#f1f4f1', '200': '#e6e9e5', '300': '#c9d1cc', '400': '#9aa6ac', '500': '#7b878e',
    '600': '#647079', '700': '#3d4b55', '800': '#1d2c40', '900': '#101b29', '950': '#0a111c',
}


def link(title: str, icon: str, url: str) -> dict:
    return {'title': title, 'icon': icon, 'link': reverse_lazy(url)}


def unfold_config(portal_url: str) -> dict:
    """Read by settings.py as UNFOLD; takes the portal address so 'View site' opens the portal."""
    return {
        'SITE_TITLE': 'CiV admin',
        'SITE_HEADER': 'Comply iV',
        'SITE_SUBHEADER': 'CiV admin',
        'SITE_URL': portal_url,
        'SHOW_VIEW_ON_SITE': False,
        'ENVIRONMENT': 'apps.admin_panel.theme.environment',
        'DASHBOARD_CALLBACK': 'apps.admin_panel.dashboard.dashboard',
        'COLORS': {'primary': TEAL, 'base': NEUTRAL, 'font': {
            # Portal text: --txt for main text, --txt-2 for secondary, in light and dark.
            'important-light': '#15232b', 'default-light': '#15232b', 'subtle-light': '#647079',
            'important-dark': '#eef3fa', 'default-dark': '#eef3fa', 'subtle-dark': '#9fb0c7',
        }},
        'STYLES': [lambda request: static('admin_panel/civ.css')],
        'SCRIPTS': [lambda request: static('admin_panel/civ.js')],
        'SIDEBAR': {
            'show_search': True,
            'show_all_applications': False,
            'navigation': [
                {'title': 'Overview', 'items': [link('Dashboard', 'space_dashboard', 'admin:index')]},
                {'title': 'Clients', 'separator': True, 'items': [
                    link('Client companies', 'apartment', 'admin:clients_client_changelist'),
                    link('Client users', 'group', 'admin:accounts_clientuser_changelist'),
                    link('Invites', 'forward_to_inbox', 'admin:accounts_invite_changelist'),
                    link('Connections', 'cable', 'admin:connections_connection_changelist'),
                ]},
                {'title': 'CiV team', 'separator': True, 'items': [
                    link('CiV staff', 'badge', 'admin:staff_staffuser_changelist'),
                    link('Permission groups', 'admin_panel_settings', 'admin:auth_group_changelist'),
                ]},
                {'title': 'Records', 'separator': True, 'items': [
                    link('Access log', 'history', 'admin:access_log_accessentry_changelist'),
                ]},
            ],
        },
    }


def environment(request):
    """Label in the top bar so nobody mistakes the local copy for the live one."""
    return ['Local', 'warning'] if settings.DEBUG else ['Live', 'danger']
