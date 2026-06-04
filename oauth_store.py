"""
OAuth 2.0 authentication for MCP servers, with tokens stored in SQLite.

Handles the full browser-based OAuth flow: endpoint auto-discovery
(`.well-known/oauth-authorization-server`), dynamic client registration
(RFC 7591), the PKCE authorization-code flow (RFC 7636) via a local callback
server, and automatic token refresh. Access tokens and client credentials are
persisted in the app database (`db.oauth_tokens`).

Call `get_token_for_server(name, url, oauth_config)` to obtain a valid access
token, running the browser flow only when needed.
"""

import base64
import hashlib
import logging
import secrets
import time
import webbrowser
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Callable, Optional
from urllib.parse import urlparse, parse_qs, urlencode

import requests

import db

logger = logging.getLogger("mcpchat.oauth")


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler that receives the OAuth redirect callback."""

    auth_code = None
    auth_error = None

    def do_GET(self):
        query_components = parse_qs(urlparse(self.path).query)

        if 'code' in query_components:
            OAuthCallbackHandler.auth_code = query_components['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
            <html><head><title>Authentication Successful</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: green;">[SUCCESS] Authentication Successful!</h1>
                <p>You can close this window and return to the app.</p>
            </body></html>
            """)
        elif 'error' in query_components:
            OAuthCallbackHandler.auth_error = query_components['error'][0]
            error_description = query_components.get('error_description', ['Unknown error'])[0]
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(f"""
            <html><head><title>Authentication Failed</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: red;">[ERROR] Authentication Failed</h1>
                <p><strong>Error:</strong> {OAuthCallbackHandler.auth_error}</p>
                <p>{error_description}</p>
                <p>Please close this window and try again.</p>
            </body></html>
            """.encode())
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"Invalid callback request")

    def log_message(self, format, *args):
        """Suppress HTTP server log noise."""
        pass


class OAuthHandler:
    """Runs the OAuth 2.0 / PKCE flow and stores tokens in the app database."""

    def __init__(self, server_name: str, server_url: str,
                 oauth_config: Optional[dict[str, Any]] = None):
        self.server_name = server_name
        self.server_url = server_url.rstrip('/')
        oauth_config = oauth_config or {}

        self.redirect_port = oauth_config.get('redirect_port', 8080)
        self.redirect_uri = f"http://localhost:{self.redirect_port}/callback"

        # Discover OAuth configuration from the server.
        self.discovery_data = self._discover_oauth_config()
        self.auth_url = oauth_config.get('auth_url') or self._discover_auth_url()
        self.token_url = oauth_config.get('token_url') or self._discover_token_url()
        self.registration_endpoint = (
            self.discovery_data.get('registration_endpoint') if self.discovery_data else None
        )

        self.client_id = oauth_config.get('client_id')
        self.client_secret = oauth_config.get('client_secret')
        self.scopes = oauth_config.get('scopes', [])

        # Auto-register a client if none was provided and registration is available.
        if not self.client_id and self.registration_endpoint:
            self._auto_register_client()

    # -- storage (SQLite) -----------------------------------------------------

    def get_stored_token(self) -> Optional[dict[str, Any]]:
        """Return stored token data if present and unexpired, else None.

        Returns None when only client credentials are stored (no access token) or
        when the token has expired.
        """
        data = db.get_oauth_token(self.server_name)
        if not data or "access_token" not in data:
            return None

        if "expires_at" in data:
            try:
                if datetime.now() >= datetime.fromisoformat(data["expires_at"]):
                    print(f"Token for {self.server_name} has expired, re-authenticating...")
                    return None
            except ValueError:
                pass
        return data

    def store_token(self, token_data: dict[str, Any]) -> None:
        """Persist token data, merging over any existing row so previously stored
        client credentials survive a token refresh/exchange."""
        merged = db.get_oauth_token(self.server_name) or {}
        merged.update(token_data)
        if "expires_in" in token_data:
            expires_at = datetime.now() + timedelta(seconds=token_data["expires_in"])
            merged["expires_at"] = expires_at.isoformat()
        db.set_oauth_token(self.server_name, merged)

    # -- discovery / registration --------------------------------------------

    def _discover_oauth_config(self) -> Optional[dict[str, Any]]:
        """Fetch `.well-known/oauth-authorization-server`, or None on failure."""
        try:
            url = f"{self.server_url}/.well-known/oauth-authorization-server"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return None

    def _auto_register_client(self):
        """Register an OAuth client via dynamic client registration (RFC 7591),
        reusing stored client credentials when available.

        Check the RAW stored row for a client_id — NOT get_stored_token(), which
        returns None once the *access* token expires. Re-registering on every
        access-token expiry would mint a new client_id that no longer matches the
        stored refresh token, so refresh fails with 400 and forces endless re-auth.
        """
        stored_data = db.get_oauth_token(self.server_name) or {}
        if stored_data.get('client_id'):
            print(f"  Using stored client credentials for {self.server_name}")
            self.client_id = stored_data['client_id']
            self.client_secret = stored_data.get('client_secret')
            return

        print(f"  Registering OAuth client for {self.server_name}...")
        if not self.registration_endpoint:
            return

        try:
            registration_data = {
                'client_name': f'MCP Chat - {self.server_name}',
                'redirect_uris': [self.redirect_uri],
                'grant_types': ['authorization_code', 'refresh_token'],
                'response_types': ['code'],
                'token_endpoint_auth_method': 'none',  # use PKCE instead
            }
            response = requests.post(self.registration_endpoint, json=registration_data, timeout=30)
            response.raise_for_status()

            reg = response.json()
            self.client_id = reg.get('client_id')
            self.client_secret = reg.get('client_secret')

            if self.client_id:
                print("  [OK] Client registered successfully")
                token_data = db.get_oauth_token(self.server_name) or {}
                token_data['client_id'] = self.client_id
                if self.client_secret:
                    token_data['client_secret'] = self.client_secret
                self.store_token(token_data)
        except Exception as e:
            logger.exception("OAuth client registration failed for %s", self.server_name)
            print(f"  Client registration failed: {e}")

    def _discover_auth_url(self) -> str:
        if self.discovery_data:
            auth_url = self.discovery_data.get('authorization_endpoint')
            if auth_url:
                print(f"  Discovered auth endpoint: {auth_url}")
                return auth_url
        return f"{self.server_url}/oauth/authorize"

    def _discover_token_url(self) -> str:
        if self.discovery_data:
            token_url = self.discovery_data.get('token_endpoint')
            if token_url:
                print(f"  Discovered token endpoint: {token_url}")
                return token_url
        return f"{self.server_url}/oauth/token"

    # -- token acquisition ----------------------------------------------------

    def refresh_token(self, refresh_token: str) -> Optional[dict[str, Any]]:
        """Refresh the access token using a refresh token."""
        try:
            data = {'grant_type': 'refresh_token', 'refresh_token': refresh_token}
            if self.client_id:
                data['client_id'] = self.client_id
            if self.client_secret:
                data['client_secret'] = self.client_secret

            response = requests.post(self.token_url, data=data, timeout=30)
            response.raise_for_status()
            token_data = response.json()
            self.store_token(token_data)
            return token_data
        except requests.RequestException as e:
            logger.error("Failed to refresh token for %s: %s", self.server_name, e)
            print(f"Failed to refresh token: {e}")
            return None

    def refresh_if_possible(self) -> Optional[str]:
        """Refresh using the stored refresh token (no browser). New access token
        or None if there's no refresh token / the refresh fails."""
        stored = db.get_oauth_token(self.server_name) or {}
        rt = stored.get('refresh_token')
        if not rt:
            return None
        refreshed = self.refresh_token(rt)
        return refreshed.get('access_token') if refreshed else None

    def token_noninteractive(self) -> Optional[str]:
        """Return a usable access token WITHOUT opening a browser: a valid stored
        token, else a refreshed one. None means the caller should prompt the user
        to re-authenticate (via authorize())."""
        valid = self.get_stored_token()
        if valid:
            return valid.get('access_token')
        return self.refresh_if_possible()

    def authorize(self, on_auth_url: Optional[Callable[[str], None]] = None) -> Optional[str]:
        """Return a valid access token, running the browser PKCE flow if needed.

        `on_auth_url`, if given, is called with the authorization URL before we
        start waiting for the callback. The UI uses this to show a clickable
        sign-in link — essential when running in a container, where
        `webbrowser.open` can't reach the user's browser."""
        valid = self.get_stored_token()
        if valid:
            print(f"Using stored token for {self.server_name}")
            return valid.get('access_token')

        # Try a silent refresh before falling back to the interactive flow.
        refreshed = self.refresh_if_possible()
        if refreshed:
            return refreshed

        print(f"\nStarting OAuth authentication for {self.server_name}...")
        print(f"Waiting for callback on http://localhost:{self.redirect_port}/callback")

        # PKCE (RFC 7636)
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')

        auth_params = {
            'redirect_uri': self.redirect_uri,
            'response_type': 'code',
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
        }
        if self.client_id:
            auth_params['client_id'] = self.client_id
        if self.scopes:
            auth_params['scope'] = ' '.join(self.scopes)

        auth_url = f"{self.auth_url}?{urlencode(auth_params)}"

        OAuthCallbackHandler.auth_code = None
        OAuthCallbackHandler.auth_error = None

        # Bind all interfaces (not just localhost) so a Docker port mapping can
        # reach the callback; the redirect URI stays http://localhost:8080/callback.
        server = HTTPServer(('', self.redirect_port), OAuthCallbackHandler)

        # Let the caller surface the link (needed in containers); also try to open
        # the local browser for native runs. webbrowser is a no-op in a headless
        # container and must never raise.
        if on_auth_url is not None:
            on_auth_url(auth_url)
        print("\nOpening browser for authentication...")
        try:
            webbrowser.open(auth_url)
        except Exception:  # noqa: BLE001 — no usable browser (e.g. in a container)
            pass

        timeout = 300  # 5 minutes
        start_time = time.time()
        while OAuthCallbackHandler.auth_code is None and OAuthCallbackHandler.auth_error is None:
            server.handle_request()
            if time.time() - start_time > timeout:
                logger.error("OAuth authentication timed out for %s", self.server_name)
                print("\nAuthentication timeout. Please try again.")
                server.server_close()
                return None
        server.server_close()

        if OAuthCallbackHandler.auth_error:
            logger.error("OAuth authentication failed for %s: %s",
                         self.server_name, OAuthCallbackHandler.auth_error)
            print(f"\nAuthentication failed: {OAuthCallbackHandler.auth_error}")
            return None

        auth_code = OAuthCallbackHandler.auth_code
        print("\nExchanging authorization code for access token...")

        token_data = {
            'grant_type': 'authorization_code',
            'code': auth_code,
            'redirect_uri': self.redirect_uri,
            'code_verifier': code_verifier,
        }
        if self.client_id:
            token_data['client_id'] = self.client_id
        if self.client_secret:
            token_data['client_secret'] = self.client_secret

        try:
            response = requests.post(self.token_url, data=token_data, timeout=30)
            response.raise_for_status()
            token_response = response.json()
            self.store_token(token_response)
            print(f"[OK] Successfully authenticated with {self.server_name}")
            return token_response.get('access_token')
        except requests.RequestException as e:
            body = e.response.text if e.response is not None else ""
            logger.error("Failed to exchange authorization code for %s: %s | response=%s",
                         self.server_name, e, body)
            print(f"\nFailed to exchange authorization code: {e}")
            if e.response is not None and e.response.text:
                print(f"Response: {e.response.text}")
            return None


def get_token_for_server(server_name: str, server_url: str,
                         oauth_config: Optional[dict[str, Any]] = None) -> Optional[str]:
    """Obtain an access token for a server, running the OAuth flow if needed."""
    return OAuthHandler(server_name, server_url, oauth_config).authorize()
