"""Every /api request: odd input gets a short JSON message, never Django's error page (QA 2026-10-23).
- a hidden NUL character in the address or the body → 400;
- a JSON body that is not an object → 400;
- an error a view did not catch → 400 for bad values (too long, out of range, wrong kind, already saved) or a plain
  500 message, logged with its trace for CiV;
- unknown /api addresses and refused CSRF checks answer in JSON too."""
import json
import logging

from django.db import DataError, IntegrityError
from django.http import JsonResponse

log = logging.getLogger('civ.api')

BAD_VALUE = 'Some of the values sent are not allowed (too long, out of range or the wrong kind). Check them and try again.'


def is_api(request) -> bool:
    return request.path.startswith('/api/')


class ApiGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_api(request):
            if '\x00' in request.META.get('QUERY_STRING', '') or '%00' in request.META.get('QUERY_STRING', '').lower():
                return JsonResponse({'detail': 'Remove the hidden character from what you typed.'}, status=400)
            if request.method in ('POST', 'PATCH', 'PUT') and 'json' in request.META.get('CONTENT_TYPE', ''):
                body = request.body
                if b'\\u0000' in body or b'\x00' in body:
                    return JsonResponse({'detail': 'Remove the hidden character from what you typed.'}, status=400)
                if body.strip():
                    try:
                        data = json.loads(body)
                    except ValueError:
                        return JsonResponse({'detail': 'The request was not readable.'}, status=400)
                    if not isinstance(data, dict):
                        return JsonResponse({'detail': 'The request was not readable.'}, status=400)
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not is_api(request):
            return None
        log.exception('API error on %s %s', request.method, request.path)
        if isinstance(exception, (DataError, ValueError, TypeError, KeyError, UnicodeError, OverflowError)):
            return JsonResponse({'detail': BAD_VALUE}, status=400)
        if isinstance(exception, IntegrityError):
            return JsonResponse({'detail': 'That conflicts with something already saved.'}, status=400)
        return JsonResponse({'detail': 'The request could not be completed. CiV has been told.'}, status=500)


def not_found(request, *args, **kwargs):
    return JsonResponse({'detail': 'Not found.'}, status=404)


def csrf_failure(request, reason=''):
    if is_api(request):
        return JsonResponse({'detail': 'Your page is out of date. Reload it and try again.'}, status=403)
    from django.views.csrf import csrf_failure as django_page
    return django_page(request, reason)
