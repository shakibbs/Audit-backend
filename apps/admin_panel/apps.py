from django.apps import AppConfig


class AdminPanelConfig(AppConfig):
    name = 'apps.admin_panel'
    label = 'admin_panel'
    verbose_name = 'CiV admin panel'

    def ready(self):
        # Unfold's own page search names results after Django apps ("Client reports • Reports"); the menu's own
        # section names come from apps.admin_panel.search instead (owner, 2026-11-07).
        from django.contrib import admin
        admin.site._search_apps = lambda app_list, search_term: []
