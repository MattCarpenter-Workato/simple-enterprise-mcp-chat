"""
Test script to diagnose OAuth flow for Workato MCP servers
"""

import requests
from urllib.parse import urlencode

# Test the sheets MCP server OAuth endpoints
SERVER_URL = "https://2107.apim.mcp.workato.com"

print("Testing OAuth Discovery for Workato MCP Server")
print("=" * 60)
print(f"Server URL: {SERVER_URL}")
print()

# Test 1: Check if server has a discovery endpoint
print("Test 1: Checking for OAuth discovery endpoint...")
discovery_urls = [
    f"{SERVER_URL}/.well-known/oauth-authorization-server",
    f"{SERVER_URL}/.well-known/openid-configuration",
    f"{SERVER_URL}/oauth/.well-known/oauth-authorization-server",
]

for url in discovery_urls:
    try:
        response = requests.get(url, timeout=5)
        print(f"  {url}")
        print(f"  Status: {response.status_code}")
        if response.status_code == 200:
            print(f"  Response: {response.json()}")
            print()
    except Exception as e:
        print(f"  {url}")
        print(f"  Error: {e}")
        print()

# Test 2: Check the authorization endpoint directly
print("\nTest 2: Testing authorization endpoint...")
auth_url = f"{SERVER_URL}/oauth/authorize"
test_params = {
    'redirect_uri': 'http://localhost:8080/callback',
    'response_type': 'code'
}

try:
    response = requests.get(f"{auth_url}?{urlencode(test_params)}", timeout=5, allow_redirects=False)
    print(f"  URL: {auth_url}")
    print(f"  Status: {response.status_code}")
    print(f"  Headers: {dict(response.headers)}")
    if response.text:
        print(f"  Response: {response.text[:500]}")
except Exception as e:
    print(f"  Error: {e}")

# Test 3: Try with WWW-Authenticate header check
print("\nTest 3: Checking authentication requirements...")
try:
    response = requests.get(SERVER_URL, timeout=5)
    print(f"  Base URL Status: {response.status_code}")
    if 'WWW-Authenticate' in response.headers:
        print(f"  WWW-Authenticate: {response.headers['WWW-Authenticate']}")
except Exception as e:
    print(f"  Error: {e}")

# Test 4: Check if it needs MCP tools/list to understand the flow
print("\nTest 4: Testing MCP tools/list endpoint...")
try:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {}
    }
    response = requests.post(SERVER_URL, json=payload, timeout=5)
    print(f"  Status: {response.status_code}")
    if response.status_code == 401:
        print(f"  Response: {response.text[:500]}")
        if 'WWW-Authenticate' in response.headers:
            print(f"  WWW-Authenticate: {response.headers['WWW-Authenticate']}")
except Exception as e:
    print(f"  Error: {e}")

print("\n" + "=" * 60)
print("Diagnosis complete. Check the output above for clues.")
print("\nCommon scenarios:")
print("1. If WWW-Authenticate header is present, it shows the required auth scheme")
print("2. If status is 302/303, check Location header for redirect URL")
print("3. If discovery endpoint works, use that configuration")
