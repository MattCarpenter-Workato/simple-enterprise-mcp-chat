"""
DB-backed OAuth handler for the web UI.

`oauth_handler.OAuthHandler` implements the full OAuth 2.0 / PKCE flow but stores
tokens in a JSON file (.mcp_tokens.json). The web UI keeps everything in SQLite,
so we subclass it and override only the two storage methods it calls
(get_stored_token / store_token). The entire discovery / PKCE / refresh flow is
reused unchanged, and oauth_handler.py stays untouched so the CLI scripts keep
working from the file.
"""

from datetime import datetime, timedelta
from typing import Any, Optional

from oauth_handler import OAuthHandler
import db


class DBOAuthHandler(OAuthHandler):
    """OAuthHandler that persists tokens and client credentials in SQLite."""

    def get_stored_token(self) -> Optional[dict[str, Any]]:
        """Return stored token data if present and unexpired.

        Mirrors the base contract: returns None when there's no access token
        (i.e. only client credentials are stored) or when the token has expired.
        """
        data = db.get_oauth_token(self.server_name)
        if not data:
            return None

        if "access_token" not in data:
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

        # Compute an absolute expiry from expires_in, matching the base class.
        if "expires_in" in token_data:
            expires_at = datetime.now() + timedelta(seconds=token_data["expires_in"])
            merged["expires_at"] = expires_at.isoformat()

        db.set_oauth_token(self.server_name, merged)


def get_token_for_server(server_name: str, server_url: str,
                         oauth_config: Optional[dict[str, Any]] = None) -> Optional[str]:
    """DB-backed equivalent of oauth_handler.get_token_for_server."""
    handler = DBOAuthHandler(server_name, server_url, oauth_config)
    return handler.authorize()
