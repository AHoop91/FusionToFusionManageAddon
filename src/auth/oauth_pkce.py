"""APS OAuth 2.0 Authorization Code + PKCE (3-legged) helpers.

A public client is used: only the Client ID is needed, no client secret is
stored or shipped. This module is stateless. It builds the authorize URL and
talks to the token endpoint; the redirect is captured by ``callback_server``
and the session is managed by ``auth_service``.
"""

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from ..core.http import OPENER
from .errors import AuthError

AUTHORIZE_URL = "https://developer.api.autodesk.com/authentication/v2/authorize"
TOKEN_URL = "https://developer.api.autodesk.com/authentication/v2/token"

TOKEN_REQUEST_TIMEOUT_SECONDS = 30


# ---- PKCE and authorize URL -------------------------------------------------

def generate_pkce() -> Dict[str, str]:
    """Return a PKCE verifier, S256 challenge and anti-CSRF state."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return {"verifier": verifier, "challenge": challenge, "state": secrets.token_urlsafe(16)}


def build_authorize_url(client_id: str, redirect_uri: str, scopes: List[str],
                        challenge: str, state: str) -> str:
    """URL the user's browser opens to sign in and grant access."""
    query = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return f"{AUTHORIZE_URL}?{query}"


# ---- Token endpoint ---------------------------------------------------------

def _post_token(form: Dict[str, str]) -> Dict[str, Any]:
    """POST to the token endpoint and stamp an absolute expiry time."""
    request = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode(form).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"},
    )
    try:
        with OPENER.open(request, timeout=TOKEN_REQUEST_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise AuthError(f"Token request failed ({exc.code}): {detail}", rejected=exc.code in (400, 401)) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise AuthError(f"Could not reach Autodesk: {exc}") from exc
    body["expires_at"] = time.time() + int(body.get("expires_in", 0))
    return body


def exchange_code(client_id: str, code: str, redirect_uri: str, verifier: str) -> Dict[str, Any]:
    """Trade an authorization code for an access/refresh token bundle."""
    return _post_token({
        "grant_type": "authorization_code", "client_id": client_id, "code": code,
        "redirect_uri": redirect_uri, "code_verifier": verifier,
    })


def refresh_tokens(client_id: str, refresh_token: str, scopes: List[str]) -> Dict[str, Any]:
    """Trade a refresh token for a fresh token bundle."""
    return _post_token({
        "grant_type": "refresh_token", "client_id": client_id,
        "refresh_token": refresh_token, "scope": " ".join(scopes),
    })
