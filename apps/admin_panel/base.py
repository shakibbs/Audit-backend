"""Base for every admin section: adds the portal-style page heading above lists and forms."""
from unfold.admin import ModelAdmin


class CivModelAdmin(ModelAdmin):
    eyebrow = 'CiV admin'  # small teal label above the title
    page_sub = ''  # one line saying what the page is for
    list_before_template = 'admin_panel/page_head_list.html'
    change_form_outer_before_template = 'admin_panel/page_head_form.html'
