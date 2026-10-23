"""The access log keeps the visitor's address, not the portal's (QA 2026-10-23)."""
from django.test import RequestFactory

from apps.access_log.recorder import client_ip


def test_behind_our_proxy_the_last_forwarded_address_is_used():
    request = RequestFactory().get('/', REMOTE_ADDR='172.18.0.5', HTTP_X_FORWARDED_FOR='1.2.3.4, 203.0.113.9')
    assert client_ip(request) == '203.0.113.9'  # the entry our proxy added; the visitor's own "1.2.3.4" is ignored


def test_a_visitor_cannot_pick_their_address():
    request = RequestFactory().get('/', REMOTE_ADDR='8.8.4.4', HTTP_X_FORWARDED_FOR='10.0.0.1')
    assert client_ip(request) == '8.8.4.4'
    assert client_ip(RequestFactory().get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_FORWARDED_FOR='junk')) == '127.0.0.1'
