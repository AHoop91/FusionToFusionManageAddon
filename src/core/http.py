"""The one way the add-in opens an https address.

A redirect is followed only to another https address, and the access token is sent only to the host it was meant for.
"""

import urllib.error
import urllib.parse
import urllib.request


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect to https only, and drops the access token when it leaves the host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlparse(newurl)
        if target.scheme.lower() != "https":
            raise urllib.error.HTTPError(req.full_url, code, f"Refused a redirect to a non-https address: {newurl}", headers, fp)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and target.netloc != urllib.parse.urlparse(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


OPENER = urllib.request.build_opener(_SafeRedirects)
