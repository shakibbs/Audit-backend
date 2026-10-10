"""The bare admin address (e.g. https://admin.complyiv.com/) opens the admin panel."""
from django.shortcuts import redirect


def root_redirect(request):
    return redirect('/civ-admin/')
