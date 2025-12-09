"""
OAuth 2.0 Authentication Handler for MCP Servers

This module handles OAuth 2.0 authentication flows for MCP servers that require
browser-based authentication. It launches a local web server to receive the OAuth
callback and exchanges the authorization code for access tokens.
"""

import json
import os
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
from typing import Optional, Dict, Any
import requests
import time
from datetime import datetime, timedelta


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth callback"""

    auth_code = None
    auth_error = None

    def do_GET(self):
        """Handle GET request from OAuth provider"""
        # Parse the query parameters
        query_components = parse_qs(urlparse(self.path).query)

        # Check for authorization code
        if 'code' in query_components:
            OAuthCallbackHandler.auth_code = query_components['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            success_html = """
            <html>
            <head><title>Authentication Successful</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: green;">✓ Authentication Successful!</h1>
                <p>You can close this window and return to the terminal.</p>
            </body>
            </html>
            """
            self.wfile.write(success_html.encode())
        elif 'error' in query_components:
            OAuthCallbackHandler.auth_error = query_components['error'][0]
            error_description = query_components.get('error_description', ['Unknown error'])[0]
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            error_html = f"""
            <html>
            <head><title>Authentication Failed</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: red;">✗ Authentication Failed</h1>
                <p><strong>Error:</strong> {OAuthCallbackHandler.auth_error}</p>
                <p>{error_description}</p>
                <p>Please close this window and try again.</p>
            </body>
            </html>
            """
            self.wfile.write(error_html.encode())
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"Invalid callback request")

    def log_message(self, format, *args):
        """Suppress HTTP server log messages"""
        pass


class OAuthHandler:
    """Handles OAuth 2.0 authentication flow for MCP servers"""

    TOKEN_STORAGE_FILE = ".mcp_tokens.json"

    def __init__(self, server_name: str, server_url: str, oauth_config: Optional[Dict[str, Any]] = None):
        """
        Initialize OAuth handler

        Args:
            server_name: Name of the MCP server
            server_url: Base URL of the MCP server
            oauth_config: Optional OAuth configuration. If not provided, will attempt
                         to discover OAuth endpoints from the server URL.
                         Can contain:
                - auth_url: Authorization endpoint (optional, will auto-discover)
                - token_url: Token endpoint (optional, will auto-discover)
                - client_id: OAuth client ID (optional for some flows)
                - client_secret: OAuth client secret (optional)
                - scopes: List of OAuth scopes (optional)
                - redirect_port: Port for local callback server (default: 8080)
        """
        self.server_name = server_name
        self.server_url = server_url.rstrip('/')
        oauth_config = oauth_config or {}

        # Try to auto-discover OAuth endpoints if not provided
        self.auth_url = oauth_config.get('auth_url') or self._discover_auth_url()
        self.token_url = oauth_config.get('token_url') or self._discover_token_url()
        self.client_id = oauth_config.get('client_id')
        self.client_secret = oauth_config.get('client_secret')
        self.scopes = oauth_config.get('scopes', [])
        self.redirect_port = oauth_config.get('redirect_port', 8080)
        self.redirect_uri = f"http://localhost:{self.redirect_port}/callback"

    def _discover_auth_url(self) -> str:
        """
        Discover OAuth authorization URL from server

        Returns:
            Authorization URL, or a default based on server URL
        """
        # For Workato MCP servers, construct the auth URL from the base
        # Example: https://2107.apim.mcp.workato.com/ -> https://2107.apim.mcp.workato.com/oauth/authorize
        return f"{self.server_url}/oauth/authorize"

    def _discover_token_url(self) -> str:
        """
        Discover OAuth token URL from server

        Returns:
            Token URL, or a default based on server URL
        """
        # For Workato MCP servers, construct the token URL from the base
        # Example: https://2107.apim.mcp.workato.com/ -> https://2107.apim.mcp.workato.com/oauth/token
        return f"{self.server_url}/oauth/token"

    def get_stored_token(self) -> Optional[Dict[str, Any]]:
        """
        Retrieve stored access token if valid

        Returns:
            Token data if valid, None otherwise
        """
        if not os.path.exists(self.TOKEN_STORAGE_FILE):
            return None

        try:
            with open(self.TOKEN_STORAGE_FILE, 'r') as f:
                tokens = json.load(f)

            if self.server_name not in tokens:
                return None

            token_data = tokens[self.server_name]

            # Check if token has expired
            if 'expires_at' in token_data:
                expires_at = datetime.fromisoformat(token_data['expires_at'])
                if datetime.now() >= expires_at:
                    print(f"Token for {self.server_name} has expired, re-authenticating...")
                    return None

            return token_data
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def store_token(self, token_data: Dict[str, Any]):
        """
        Store access token securely

        Args:
            token_data: Token information from OAuth provider
        """
        # Load existing tokens
        tokens = {}
        if os.path.exists(self.TOKEN_STORAGE_FILE):
            try:
                with open(self.TOKEN_STORAGE_FILE, 'r') as f:
                    tokens = json.load(f)
            except json.JSONDecodeError:
                pass

        # Calculate expiration time
        if 'expires_in' in token_data:
            expires_at = datetime.now() + timedelta(seconds=token_data['expires_in'])
            token_data['expires_at'] = expires_at.isoformat()

        # Store token for this server
        tokens[self.server_name] = token_data

        # Save to file
        with open(self.TOKEN_STORAGE_FILE, 'w') as f:
            json.dump(tokens, f, indent=2)

        # Secure the file (readable/writable only by owner)
        os.chmod(self.TOKEN_STORAGE_FILE, 0o600)

    def refresh_token(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """
        Refresh access token using refresh token

        Args:
            refresh_token: Refresh token from previous authorization

        Returns:
            New token data or None if refresh failed
        """
        try:
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token
            }

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
            print(f"Failed to refresh token: {e}")
            return None

    def authorize(self) -> Optional[str]:
        """
        Perform OAuth 2.0 authorization flow

        Returns:
            Access token or None if authorization failed
        """
        # Check for stored valid token
        stored_token = self.get_stored_token()
        if stored_token:
            print(f"Using stored token for {self.server_name}")
            return stored_token.get('access_token')

        # Try to refresh if we have a refresh token
        if stored_token and 'refresh_token' in stored_token:
            refreshed = self.refresh_token(stored_token['refresh_token'])
            if refreshed:
                return refreshed.get('access_token')

        # Start fresh authorization flow
        print(f"\nStarting OAuth authentication for {self.server_name}...")
        print(f"A browser window will open for you to authorize access.")
        print(f"Waiting for callback on http://localhost:{self.redirect_port}/callback")

        # Build authorization URL
        auth_params = {
            'redirect_uri': self.redirect_uri,
            'response_type': 'code'
        }

        # Add optional parameters if provided
        if self.client_id:
            auth_params['client_id'] = self.client_id
        if self.scopes:
            auth_params['scope'] = ' '.join(self.scopes)

        auth_url = f"{self.auth_url}?{urlencode(auth_params)}"

        # Reset callback handler state
        OAuthCallbackHandler.auth_code = None
        OAuthCallbackHandler.auth_error = None

        # Start local HTTP server for callback
        server = HTTPServer(('localhost', self.redirect_port), OAuthCallbackHandler)

        # Open browser for authorization
        print(f"\nOpening browser for authentication...")
        webbrowser.open(auth_url)

        # Wait for callback (with timeout)
        timeout = 300  # 5 minutes
        start_time = time.time()

        while OAuthCallbackHandler.auth_code is None and OAuthCallbackHandler.auth_error is None:
            server.handle_request()
            if time.time() - start_time > timeout:
                print("\nAuthentication timeout. Please try again.")
                server.server_close()
                return None

        server.server_close()

        # Check for errors
        if OAuthCallbackHandler.auth_error:
            print(f"\nAuthentication failed: {OAuthCallbackHandler.auth_error}")
            return None

        # Exchange authorization code for access token
        auth_code = OAuthCallbackHandler.auth_code
        print("\nExchanging authorization code for access token...")

        token_data = {
            'grant_type': 'authorization_code',
            'code': auth_code,
            'redirect_uri': self.redirect_uri
        }

        if self.client_id:
            token_data['client_id'] = self.client_id

        if self.client_secret:
            token_data['client_secret'] = self.client_secret

        try:
            response = requests.post(self.token_url, data=token_data, timeout=30)
            response.raise_for_status()

            token_response = response.json()

            # Store the token
            self.store_token(token_response)

            print(f"✓ Successfully authenticated with {self.server_name}")

            return token_response.get('access_token')
        except requests.RequestException as e:
            print(f"\nFailed to exchange authorization code: {e}")
            if hasattr(e.response, 'text'):
                print(f"Response: {e.response.text}")
            return None


def get_token_for_server(server_name: str, server_url: str, oauth_config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Convenience function to get access token for a server

    Args:
        server_name: Name of the MCP server
        server_url: Base URL of the MCP server
        oauth_config: Optional OAuth configuration dictionary

    Returns:
        Access token or None if authentication failed
    """
    handler = OAuthHandler(server_name, server_url, oauth_config)
    return handler.authorize()
