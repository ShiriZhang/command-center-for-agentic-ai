"""
fetch_article Tool with DNS Pre-Resolution SSRF Guardrails and Hop-by-Hop Redirect Inspection.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import ipaddress
import re
import socket
import time
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, urljoin
import httpx
from bs4 import BeautifulSoup

from tracker.config import config


def validate_url_ssrf(
    url: str,
    allowed_schemes: Optional[List[str]] = None,
    blocked_networks: Optional[List[str]] = None
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validates a URL against Server-Side Request Forgery (SSRF) vulnerabilities.
    
    Security Checks:
    1. Scheme check: only permitted schemes (http, https). Rejects file://, gopher://, dict://, etc.
    2. Host presence: hostname must not be empty.
    3. DNS Pre-Resolution: Resolves hostname to IPv4/IPv6 socket addresses.
    4. IP Classification: Rejects loopback (127.0.0.1), private networks (RFC 1918),
       link-local (169.254.169.254 AWS metadata), multicast, and reserved addresses.
    
    Returns:
        (is_safe, error_message, resolved_ip)
    """
    schemes = allowed_schemes or config.network.allowed_schemes
    blocked_cidrs = [
        ipaddress.ip_network(cidr)
        for cidr in (blocked_networks or config.network.blocked_ip_ranges)
    ]

    # Step 1: Parse URI and validate scheme
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Invalid URL format: {e}", None

    scheme = parsed.scheme.lower()
    if scheme not in schemes:
        return False, f"Forbidden scheme '{scheme}'. Only {schemes} are permitted.", None

    hostname = parsed.hostname
    if not hostname:
        return False, "URL missing valid hostname.", None

    port = parsed.port or (443 if scheme == "https" else 80)

    # Step 2: DNS Pre-Resolution
    try:
        # socket.getaddrinfo returns a list of 5-tuples: (family, type, proto, canonname, sockaddr)
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return False, f"DNS resolution failed for host '{hostname}': {e}", None
    except Exception as e:
        return False, f"Socket error resolving '{hostname}': {e}", None

    if not addr_info:
        return False, f"DNS returned no addresses for host '{hostname}'.", None

    # Step 3: IP Classification across all resolved records
    for info in addr_info:
        ip_str = info[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"Malformed IP address resolved: {ip_str}", None

        # Check standard dangerous categories
        if ip_obj.is_loopback:
            return False, f"Guardrail rejection: Host resolves to loopback IP ({ip_str})", ip_str
        if ip_obj.is_link_local:
            return False, f"Guardrail rejection: Host resolves to link-local metadata IP ({ip_str})", ip_str
        if ip_obj.is_private:
            return False, f"Guardrail rejection: Host resolves to private network IP ({ip_str})", ip_str
        if ip_obj.is_multicast or ip_obj.is_reserved:
            return False, f"Guardrail rejection: Host resolves to reserved/multicast IP ({ip_str})", ip_str
        if ip_str in ("0.0.0.0", "::"):
            return False, f"Guardrail rejection: Host resolves to unspecified wildcard IP ({ip_str})", ip_str

        # Check explicit CIDR blocklist from config
        for cidr in blocked_cidrs:
            if ip_obj in cidr:
                return False, f"Guardrail rejection: IP {ip_str} falls within blocked CIDR {cidr}", ip_str

    first_ip = addr_info[0][4][0]
    return True, None, first_ip


def clean_html_to_text(html_content: str) -> Tuple[str, str]:
    """
    Extracts readable plain text and title from raw HTML, stripping scripts,
    styles, and non-content tags to prevent Stored XSS and noise.
    
    Returns:
        (title, clean_text)
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # Extract title before decomposing tags
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    elif soup.h1:
        title = soup.h1.get_text().strip()

    # Decompose script, style, and interactive tags
    for element in soup(["script", "style", "noscript", "iframe", "svg", "header", "footer", "nav"]):
        element.decompose()

    # Extract text with whitespace separation
    text = soup.get_text(separator=" ")
    
    # Collapse multiple whitespace characters and clean up newlines
    clean_text = re.sub(r"[ \t]+", " ", text)
    clean_text = re.sub(r"\n\s*\n+", "\n\n", clean_text).strip()

    return title, clean_text


def fetch_article(url: str) -> Dict[str, Any]:
    """
    Fetches and sanitizes article content with multi-layered network security:
    1. Scheme and SSRF DNS pre-resolution guardrails.
    2. Hop-by-Hop Redirect Inspection (follow_redirects=False) preventing redirect bounce SSRF.
    3. 10-second timeout and 1MB size limit.
    4. Clean plain-text extraction neutralizing embedded HTML/script payloads.
    
    Returns a standardized dictionary compliant with the Assignment 1B specification:
    {
        "url": str,
        "title": str,
        "content": str,
        "status": "fetched" | "rejected" | "error",
        "error": Optional[str],
        "byte_size": int,
        "fetch_time_ms": int
    }
    """
    start_time = time.time()
    current_url = url
    max_redirects = 3
    redirect_count = 0

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 FNMS-Tracker/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    # Redirect loop with manual hop-by-hop SSRF validation
    while redirect_count <= max_redirects:
        # Step 1: Pre-flight SSRF Guardrail Check on the current hop
        is_safe, error_msg, resolved_ip = validate_url_ssrf(current_url)
        if not is_safe:
            latency_ms = int((time.time() - start_time) * 1000)
            return {
                "url": url,
                "current_url": current_url,
                "title": "",
                "content": "",
                "status": "rejected",
                "error": error_msg,
                "byte_size": 0,
                "fetch_time_ms": latency_ms
            }

        # Step 2: Execute network request with strict timeout and no auto-redirect
        try:
            with httpx.Client(
                timeout=config.network.request_timeout_seconds,
                follow_redirects=False,
                verify=True
            ) as client:
                response = client.get(current_url, headers=headers)
        except httpx.TimeoutException:
            latency_ms = int((time.time() - start_time) * 1000)
            return {
                "url": url,
                "current_url": current_url,
                "title": "",
                "content": "",
                "status": "error",
                "error": f"Request timed out after {config.network.request_timeout_seconds}s",
                "byte_size": 0,
                "fetch_time_ms": latency_ms
            }
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return {
                "url": url,
                "current_url": current_url,
                "title": "",
                "content": "",
                "status": "error",
                "error": f"HTTP request failed: {e}",
                "byte_size": 0,
                "fetch_time_ms": latency_ms
            }

        # Step 3: Handle HTTP Redirection manually (Hop-by-Hop verification)
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            if not location:
                break
            next_url = urljoin(current_url, location)
            current_url = next_url
            redirect_count += 1
            continue

        # Terminal HTTP status check
        if response.status_code >= 400:
            latency_ms = int((time.time() - start_time) * 1000)
            return {
                "url": url,
                "current_url": current_url,
                "title": "",
                "content": "",
                "status": "error",
                "error": f"HTTP {response.status_code} error returned by server",
                "byte_size": len(response.content),
                "fetch_time_ms": latency_ms
            }

        # Step 4: Size Limit Enforcement (1MB max)
        raw_bytes = response.content
        byte_size = len(raw_bytes)
        if byte_size > config.network.max_response_bytes:
            raw_bytes = raw_bytes[:config.network.max_response_bytes]

        # Step 5: Clean HTML and extract text
        try:
            html_text = raw_bytes.decode(response.encoding or "utf-8", errors="replace")
        except Exception:
            html_text = raw_bytes.decode("utf-8", errors="replace")

        title, clean_text = clean_html_to_text(html_text)
        latency_ms = int((time.time() - start_time) * 1000)

        return {
            "url": url,
            "current_url": current_url,
            "title": title or "Untitled Article",
            "content": clean_text,
            "status": "fetched",
            "error": None,
            "byte_size": byte_size,
            "fetch_time_ms": latency_ms
        }

    # Redirect count exceeded
    latency_ms = int((time.time() - start_time) * 1000)
    return {
        "url": url,
        "current_url": current_url,
        "title": "",
        "content": "",
        "status": "error",
        "error": f"Exceeded maximum redirection limit ({max_redirects} hops)",
        "byte_size": 0,
        "fetch_time_ms": latency_ms
    }


if __name__ == "__main__":
    import json
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) < 2:
        print("Usage: python -m tracker.tools.fetch <url>")
        sys.exit(1)

    target_url = sys.argv[1]
    result = fetch_article(target_url)
    print(json.dumps(result, indent=2, ensure_ascii=False))
