"""Shared by tools the client connects with "Allow" (Salesforce, HubSpot): calling the API with the client's access
pass, and renewing the pass with CiV's app ID and secret when the tool says it has expired. The renewed pass is saved
locked on the connection, like any key."""
import json
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_SECONDS = 30


class Disconnected(Exception):
    """The client removed CiV's access (or the pass cannot be renewed): someone must click Allow again."""


class OAuthTool:
    token_url = ''
    client_id_setting = client_secret_setting = ''

    def _creds(self) -> dict:
        return self.connection.get_credentials()

    def _renew(self) -> None:
        from django.conf import settings
        creds = self._creds()
        body = urllib.parse.urlencode({'grant_type': 'refresh_token', 'refresh_token': creds.get('refresh_token', ''),
                                       'client_id': getattr(settings, self.client_id_setting),
                                       'client_secret': getattr(settings, self.client_secret_setting)}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(self.token_url, data=body, headers={'Accept': 'application/json'}),
                                        timeout=TIMEOUT_SECONDS) as reply:
                fresh = json.loads(reply.read())
        except urllib.error.HTTPError as error:
            raise Disconnected(f'pass renewal refused (HTTP {error.code})') from None
        self.connection.set_credentials({**creds, **{k: v for k, v in fresh.items() if k in ('access_token', 'refresh_token', 'instance_url')}})
        self.connection.save(update_fields=['credentials', 'updated_at'])

    def call(self, url: str, body: dict | None = None) -> dict:
        """GET (or POST JSON) with the access pass; renews it once if the tool says it expired."""
        for attempt in (1, 2):
            headers = {'Authorization': f"Bearer {self._creds().get('access_token', '')}", 'Accept': 'application/json'}
            data = None
            if body is not None:
                data, headers['Content-Type'] = json.dumps(body).encode(), 'application/json'
            try:
                with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=TIMEOUT_SECONDS) as reply:
                    return json.loads(reply.read())
            except urllib.error.HTTPError as error:
                if error.code == 401 and attempt == 1:
                    self._renew()
                    continue
                if error.code in (401, 403):
                    raise Disconnected(f'HTTP {error.code}') from None
                raise
        raise Disconnected('still refused after renewing the pass')
