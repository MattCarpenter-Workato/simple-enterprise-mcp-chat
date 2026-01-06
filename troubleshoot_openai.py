#!/usr/bin/env python3
"""
OpenAI Connection Troubleshooter

This script diagnoses common issues with OpenAI API connectivity, including:
- Network connectivity to OpenAI servers
- Firewall/proxy blocking
- API key validation
- SSL/TLS issues
- DNS resolution
- Model access

Usage:
    python troubleshoot_openai.py
    python troubleshoot_openai.py --verbose
"""

import os
import sys
import socket
import ssl
import time
import json
import argparse
from urllib.parse import urlparse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")

def print_test(name: str):
    print(f"\n{Colors.BOLD}Testing: {name}{Colors.END}")

def print_pass(message: str):
    print(f"  {Colors.GREEN}✓ PASS:{Colors.END} {message}")

def print_fail(message: str):
    print(f"  {Colors.RED}✗ FAIL:{Colors.END} {message}")

def print_warn(message: str):
    print(f"  {Colors.YELLOW}⚠ WARN:{Colors.END} {message}")

def print_info(message: str):
    print(f"  {Colors.BLUE}ℹ INFO:{Colors.END} {message}")


def check_api_key():
    """Check if OpenAI API key is configured."""
    print_test("API Key Configuration")

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        print_fail("OPENAI_API_KEY environment variable is not set")
        print_info("Set it in your .env file or environment: export OPENAI_API_KEY='sk-...'")
        return False

    if not api_key.startswith(("sk-", "sess-")):
        print_warn(f"API key has unusual format (starts with '{api_key[:5]}...')")
        print_info("OpenAI API keys typically start with 'sk-' or 'sess-'")
    else:
        print_pass(f"API key found (starts with '{api_key[:7]}...')")

    if len(api_key) < 20:
        print_warn("API key seems too short")
        return False

    return True


def check_dns_resolution(verbose: bool = False):
    """Check if DNS resolution works for OpenAI domains."""
    print_test("DNS Resolution")

    domains = [
        "api.openai.com",
        "openai.com",
    ]

    all_passed = True
    for domain in domains:
        try:
            start = time.time()
            ip = socket.gethostbyname(domain)
            elapsed = (time.time() - start) * 1000
            print_pass(f"{domain} -> {ip} ({elapsed:.0f}ms)")
            if verbose:
                print_info(f"  Full resolution: {socket.getaddrinfo(domain, 443)}")
        except socket.gaierror as e:
            print_fail(f"{domain}: DNS resolution failed - {e}")
            all_passed = False

    return all_passed


def check_tcp_connectivity(verbose: bool = False):
    """Check if TCP connections can be established to OpenAI."""
    print_test("TCP Connectivity (Port 443)")

    host = "api.openai.com"
    port = 443

    try:
        start = time.time()
        sock = socket.create_connection((host, port), timeout=10)
        elapsed = (time.time() - start) * 1000
        sock.close()
        print_pass(f"Connected to {host}:{port} ({elapsed:.0f}ms)")
        return True
    except socket.timeout:
        print_fail(f"Connection to {host}:{port} timed out")
        print_info("This often indicates a firewall blocking the connection")
        return False
    except socket.error as e:
        print_fail(f"Connection to {host}:{port} failed: {e}")
        return False


def check_ssl_tls(verbose: bool = False):
    """Check SSL/TLS connectivity to OpenAI."""
    print_test("SSL/TLS Handshake")

    host = "api.openai.com"
    port = 443

    try:
        context = ssl.create_default_context()
        start = time.time()

        with socket.create_connection((host, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                elapsed = (time.time() - start) * 1000
                cert = ssock.getpeercert()
                version = ssock.version()
                cipher = ssock.cipher()

                print_pass(f"SSL handshake successful ({elapsed:.0f}ms)")
                print_info(f"TLS Version: {version}")
                print_info(f"Cipher: {cipher[0]}")

                if verbose and cert:
                    print_info(f"Certificate subject: {cert.get('subject', 'N/A')}")
                    print_info(f"Certificate issuer: {cert.get('issuer', 'N/A')}")

                return True

    except ssl.SSLError as e:
        print_fail(f"SSL error: {e}")
        print_info("This could indicate SSL inspection/MITM by corporate firewall")
        return False
    except Exception as e:
        print_fail(f"SSL handshake failed: {e}")
        return False


def check_http_connectivity(verbose: bool = False):
    """Check HTTP/HTTPS connectivity using requests library."""
    print_test("HTTP/HTTPS Connectivity")

    try:
        import requests
    except ImportError:
        print_fail("requests library not installed")
        return False

    url = "https://api.openai.com/v1/models"
    api_key = os.getenv("OPENAI_API_KEY")

    # First, try without auth to check basic connectivity
    try:
        start = time.time()
        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "OpenAI-Troubleshooter/1.0"}
        )
        elapsed = (time.time() - start) * 1000

        # We expect 401 without auth, which proves connectivity works
        if response.status_code == 401:
            print_pass(f"HTTP connectivity works (got 401 as expected, {elapsed:.0f}ms)")
        else:
            print_info(f"Got status {response.status_code} ({elapsed:.0f}ms)")

        if verbose:
            print_info(f"Response headers: {dict(response.headers)}")

    except requests.exceptions.Timeout:
        print_fail("Request timed out - likely blocked by firewall")
        return False
    except requests.exceptions.SSLError as e:
        print_fail(f"SSL Error: {e}")
        print_info("Corporate firewalls often perform SSL inspection")
        print_info("Try setting: export REQUESTS_CA_BUNDLE=/path/to/corporate/ca.crt")
        return False
    except requests.exceptions.ProxyError as e:
        print_fail(f"Proxy Error: {e}")
        print_info("Check your HTTP_PROXY/HTTPS_PROXY environment variables")
        return False
    except requests.exceptions.ConnectionError as e:
        print_fail(f"Connection Error: {e}")
        return False
    except Exception as e:
        print_fail(f"Unexpected error: {e}")
        return False

    return True


def check_api_authentication(verbose: bool = False):
    """Check if API key is valid by making an authenticated request."""
    print_test("API Authentication")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print_fail("No API key configured")
        return False

    try:
        import requests
    except ImportError:
        print_fail("requests library not installed")
        return False

    url = "https://api.openai.com/v1/models"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "OpenAI-Troubleshooter/1.0"
    }

    try:
        start = time.time()
        response = requests.get(url, headers=headers, timeout=15)
        elapsed = (time.time() - start) * 1000

        if response.status_code == 200:
            print_pass(f"API authentication successful ({elapsed:.0f}ms)")
            data = response.json()
            model_count = len(data.get("data", []))
            print_info(f"Access to {model_count} models")
            return True
        elif response.status_code == 401:
            print_fail("Authentication failed - invalid API key")
            try:
                error = response.json()
                print_info(f"Error: {error.get('error', {}).get('message', 'Unknown')}")
            except:
                pass
            return False
        elif response.status_code == 403:
            print_fail("Access forbidden - API key may lack permissions")
            return False
        elif response.status_code == 429:
            print_warn("Rate limited - too many requests")
            return True  # Auth works, just rate limited
        else:
            print_warn(f"Unexpected status code: {response.status_code}")
            return False

    except Exception as e:
        print_fail(f"Request failed: {e}")
        return False


def check_model_access(verbose: bool = False):
    """Check access to specific models."""
    print_test("Model Access")

    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("MODEL", "gpt-4o-mini")

    if not api_key:
        print_fail("No API key configured")
        return False

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        # Try to list models
        models = client.models.list()
        available_models = [m.id for m in models.data]

        if model in available_models:
            print_pass(f"Model '{model}' is available")
        else:
            print_warn(f"Model '{model}' not found in available models")
            # Show similar models
            similar = [m for m in available_models if 'gpt' in m.lower()][:5]
            print_info(f"Available GPT models: {', '.join(similar)}")

        return True

    except Exception as e:
        print_fail(f"Could not check model access: {e}")
        return False


def check_simple_completion(verbose: bool = False):
    """Try to make a simple API call."""
    print_test("Simple API Call")

    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("MODEL", "gpt-4o-mini")

    if not api_key:
        print_fail("No API key configured")
        return False

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        start = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say 'test successful' in exactly two words."}],
            max_tokens=10
        )
        elapsed = (time.time() - start) * 1000

        result = response.choices[0].message.content
        print_pass(f"API call successful ({elapsed:.0f}ms)")
        print_info(f"Response: {result}")

        if verbose:
            print_info(f"Model used: {response.model}")
            print_info(f"Tokens: {response.usage.total_tokens}")

        return True

    except Exception as e:
        error_str = str(e)
        print_fail(f"API call failed: {e}")

        # Provide specific guidance based on error
        if "Connection" in error_str or "timeout" in error_str.lower():
            print_info("This suggests a network/firewall issue")
        elif "authentication" in error_str.lower() or "api key" in error_str.lower():
            print_info("Check your API key is correct and has credits")
        elif "rate" in error_str.lower():
            print_info("You're being rate limited - wait and try again")

        return False


def check_proxy_settings():
    """Check and display proxy settings."""
    print_test("Proxy Configuration")

    proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'NO_PROXY', 'no_proxy']
    found_proxy = False

    for var in proxy_vars:
        value = os.getenv(var)
        if value:
            found_proxy = True
            print_info(f"{var}={value}")

    if not found_proxy:
        print_info("No proxy environment variables set")
    else:
        print_warn("Proxy is configured - ensure it allows OpenAI traffic")

    return True


def check_firewall_indicators():
    """Check for common indicators of firewall blocking."""
    print_test("Firewall Indicators")

    indicators = []

    # Check for corporate CA certificates
    ca_bundle = os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("SSL_CERT_FILE")
    if ca_bundle:
        indicators.append(f"Custom CA bundle: {ca_bundle}")

    # Check for common corporate network indicators
    try:
        import socket
        hostname = socket.gethostname()
        if any(corp in hostname.lower() for corp in ['corp', 'internal', 'enterprise']):
            indicators.append(f"Corporate hostname detected: {hostname}")
    except:
        pass

    if indicators:
        print_warn("Possible corporate network indicators found:")
        for ind in indicators:
            print_info(f"  - {ind}")
    else:
        print_info("No obvious corporate network indicators")

    return True


def run_all_tests(verbose: bool = False):
    """Run all diagnostic tests."""
    print_header("OpenAI Connection Troubleshooter")
    print(f"Running diagnostics at {time.strftime('%Y-%m-%d %H:%M:%S')}")

    results = {}

    # Run tests in order of dependencies
    results['api_key'] = check_api_key()
    results['dns'] = check_dns_resolution(verbose)
    results['tcp'] = check_tcp_connectivity(verbose)
    results['ssl'] = check_ssl_tls(verbose)
    results['http'] = check_http_connectivity(verbose)
    check_proxy_settings()
    check_firewall_indicators()

    if results['http'] and results['api_key']:
        results['auth'] = check_api_authentication(verbose)
        if results['auth']:
            results['model'] = check_model_access(verbose)
            results['completion'] = check_simple_completion(verbose)

    # Summary
    print_header("Summary")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    if passed == total:
        print(f"{Colors.GREEN}All {total} tests passed! OpenAI connection is working.{Colors.END}")
    else:
        print(f"{Colors.RED}Passed {passed}/{total} tests{Colors.END}")

        # Provide recommendations
        print(f"\n{Colors.BOLD}Recommendations:{Colors.END}")

        if not results.get('dns'):
            print("  • Check your DNS settings or try using 8.8.8.8")
        if not results.get('tcp'):
            print("  • Port 443 may be blocked - contact your IT department")
        if not results.get('ssl'):
            print("  • SSL inspection may be interfering - ask IT about CA certificates")
        if not results.get('http'):
            print("  • HTTP requests are failing - check firewall/proxy settings")
        if not results.get('api_key'):
            print("  • Set your OPENAI_API_KEY in the .env file")
        if not results.get('auth'):
            print("  • Verify your API key is valid at https://platform.openai.com/api-keys")

        print(f"\n{Colors.BOLD}If you're behind a corporate firewall:{Colors.END}")
        print("  1. Ask IT to whitelist: api.openai.com")
        print("  2. Ask for the corporate CA certificate bundle")
        print("  3. Set: export REQUESTS_CA_BUNDLE=/path/to/ca-bundle.crt")
        print("  4. Or configure your proxy: export HTTPS_PROXY=http://proxy:port")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Diagnose OpenAI API connection issues"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed output"
    )

    args = parser.parse_args()
    run_all_tests(verbose=args.verbose)
