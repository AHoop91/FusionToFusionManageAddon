import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from src.auth.callback_server import CallbackServer
from src.config.config_service import ConfigService
from src.config.hub import tenant_code, tenant_of_link
from src.config.models import MODE_LOCAL, ConnectionSettings
from src.fm.client import FmApiError, FmClient


class TenantTests(unittest.TestCase):
    def test_only_plain_host_labels_are_tenants(self):
        self.assertEqual(tenant_code(" MyCompany "), "mycompany")
        self.assertEqual(tenant_code("my-co1"), "my-co1")
        for bad in ("", None, "evil.example/x#", "a.b", "a b", "a@evil.com", "-a", "a-", "x" * 64, "a/b", "a:80"):
            self.assertEqual(tenant_code(bad), "", bad)

    def test_client_refuses_a_tenant_that_could_redirect_the_token(self):
        for bad in ("evil.example/x#", "a.evil.com", "", "u@evil.com"):
            with self.assertRaises(FmApiError, msg=bad):
                FmClient(ConnectionSettings(tenant=bad), mock.Mock()).base_url
        self.assertEqual(FmClient(ConnectionSettings(tenant="acme"), mock.Mock()).base_url, "https://acme.autodeskplm360.net")

    def test_a_saved_tenant_must_be_a_plain_name(self):
        self.assertEqual(ConnectionSettings(client_id="c", tenant="acme").validate(), [])
        self.assertTrue(ConnectionSettings(client_id="c", tenant="evil.example/x#").validate(require_tenant=False))

    def test_effective_settings_use_only_the_saved_tenant(self):
        with tempfile.TemporaryDirectory() as folder:
            service = ConfigService(os.path.join(folder, "config.json"))
            self.assertEqual(service.effective_settings().tenant, "")
            self.assertEqual(service.update(MODE_LOCAL, ConnectionSettings(client_id="c", tenant="Acme"), service.config.workspaces, ""), [])
            self.assertEqual(service.effective_settings().tenant, "acme")
            self.assertEqual(service.config.local.tenant, "Acme")


class TenantFromLinkTests(unittest.TestCase):
    def test_the_tenant_comes_from_the_item_address_or_urn(self):
        url = "https://ACME.autodeskplm360.net/plm/extAccess?itemUrn=x"
        self.assertEqual(tenant_of_link("", url), "acme")
        self.assertEqual(tenant_of_link("urn:adsk.plm:tenant.workspace.item:ACME.57.15745", ""), "acme")
        self.assertEqual(tenant_of_link("", "https://evil.example/plm"), "")
        self.assertEqual(tenant_of_link("", "https://x.evil.com/?.autodeskplm360.net"), "")
        self.assertEqual(tenant_of_link("", ""), "")


class RedirectTests(unittest.TestCase):
    def redirect(self, url, to):
        from src.core.http import _SafeRedirects
        request = urllib.request.Request(url, headers={"Authorization": "Bearer t"})
        return _SafeRedirects().redirect_request(request, None, 302, "Found", {}, to)

    def test_token_stays_on_its_own_host(self):
        self.assertEqual(self.redirect("https://a.example/x", "https://a.example/y").get_header("Authorization"), "Bearer t")
        self.assertIsNone(self.redirect("https://a.example/x", "https://b.example/y").get_header("Authorization"))

    def test_a_redirect_to_http_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.redirect("https://a.example/x", "http://a.example/y")


class SignedHeaderTests(unittest.TestCase):
    def test_only_headers_meant_for_a_signed_address_are_sent(self):
        from src.fm.client import signed_headers
        sent = signed_headers({"x-amz-meta-a": "1", "Content-MD5": "m", "Host": "evil", "Content-Length": "1", "Authorization": "x"})
        self.assertEqual(sent, {"x-amz-meta-a": "1", "Content-MD5": "m"})


class CallbackTests(unittest.TestCase):
    def get(self, port, query):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?{query}", timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            exc.close()
            return exc.code

    def test_a_wrong_state_does_not_end_the_sign_in(self):
        server = CallbackServer(0, "right")
        port = server._server.server_address[1]
        found = {}
        thread = threading.Thread(target=lambda: found.update(server.wait(10, threading.Event())))
        thread.start()
        self.assertEqual(self.get(port, "state=wrong&code=x"), 400)
        self.assertEqual(self.get(port, "code=x"), 400)
        self.assertEqual(self.get(port, "state=right&code=abc"), 200)
        thread.join(10)
        self.assertEqual(found["code"], "abc")


if __name__ == "__main__":
    unittest.main()
