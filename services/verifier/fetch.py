"""
Guarded HTTP fetch client with SSRF DNS pre-resolution, pinned destination checks,
hop-by-hop redirect verification, streaming byte caps, and remaining-deadline enforcement.
CSCI-GA.2630 Assignment 2
"""

import ipaddress
import re
import socket
import time
from typing import Any, List, Optional, Tuple
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import httpcore
import httpx


def validate_destination_ip(ip_str: str) -> Tuple[bool, Optional[str]]:
    """
    Validates a resolved IPv4/IPv6 address against SSRF attack vectors.
    Permits public IPv4 and public IPv6.
    Rejects loopback, private networks, cloud metadata, multicast, and reserved ranges.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False, f"Malformed IP address: {ip_str}"

    # Handle IPv4-mapped IPv6 (::ffff:127.0.0.1 or ::ffff:7f00:1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    if ip.is_loopback:
        return False, f"Loopback address rejected: {ip_str}"
    if ip.is_link_local:
        return False, f"Link-local / cloud metadata address rejected: {ip_str}"
    if ip.is_private:
        return False, f"Private network address rejected: {ip_str}"
    if ip.is_multicast or ip.is_reserved:
        return False, f"Multicast or reserved address rejected: {ip_str}"
    if ip.is_unspecified:
        return False, f"Unspecified wildcard address rejected: {ip_str}"

    return True, None


def resolve_and_validate_hostname(
    hostname: str, port: int
) -> Tuple[bool, Optional[str], List[str]]:
    """
    Resolves hostname via DNS and checks all returned socket addresses.
    If ANY returned address is prohibited, rejects the host.
    Returns (is_safe, error_message, approved_ip_list).
    """
    try:
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return False, f"DNS resolution failed for {hostname}: {e}", []
    except Exception as e:
        return False, f"Socket error resolving {hostname}: {e}", []

    if not addr_info:
        return False, f"DNS returned no addresses for {hostname}", []

    approved_ips: List[str] = []
    for info in addr_info:
        ip_str = str(info[4][0])
        is_safe, err = validate_destination_ip(ip_str)
        if not is_safe:
            return False, f"DNS resolution yielded prohibited address ({err})", []
        approved_ips.append(ip_str)

    return True, None, approved_ips


class PinnedSyncBackend(httpcore.SyncBackend):
    """Network backend that connects directly to a verified pinned IP to prevent TOCTOU DNS rebinding."""

    def __init__(self, pinned_ip: str):
        super().__init__()
        self.pinned_ip = pinned_ip

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options: Optional[Any] = None,
    ) -> httpcore.NetworkStream:
        return super().connect_tcp(
            self.pinned_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class PinnedHTTPTransport(httpx.HTTPTransport):
    """HTTP transport pinning connections to a pre-validated IP address."""

    def __init__(self, pinned_ip: str, **kwargs: Any):
        super().__init__(**kwargs)
        self._pool._network_backend = PinnedSyncBackend(pinned_ip)


def clean_html_to_text(html_content: str) -> Tuple[str, str]:
    """Extracts readable plain text and title from HTML."""
    soup = BeautifulSoup(html_content, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    elif soup.h1:
        title = soup.h1.get_text().strip()

    for element in soup(["script", "style", "noscript", "iframe", "svg", "header", "footer", "nav"]):
        element.decompose()

    text = soup.get_text(separator=" ")
    clean_text = re.sub(r"[ \t]+", " ", text)
    clean_text = re.sub(r"\n\s*\n+", "\n\n", clean_text).strip()
    return title, clean_text


def sanitize_url(raw_url: str) -> str:
    """Strips credentials, query parameters, and fragments from a URL for safe logging."""
    try:
        parsed = urlparse(raw_url)
        clean_netloc = parsed.hostname or ""
        if parsed.port and parsed.port not in (80, 443):
            clean_netloc = f"{clean_netloc}:{parsed.port}"
        return f"{parsed.scheme}://{clean_netloc}{parsed.path}"
    except Exception:
        return "sanitized_url"


class FetchResult:
    """Standardized outcome of a guarded source fetch."""

    def __init__(
        self,
        url: str,
        current_url: str,
        status: str,  # "fetched", "rejected", "error"
        title: str = "",
        content: str = "",
        raw_bytes: bytes = b"",
        byte_size: int = 0,
        latency_ms: int = 0,
        error: Optional[str] = None,
        redirect_hops: int = 0,
        resolved_ip: Optional[str] = None,
    ):
        self.url = url
        self.current_url = current_url
        self.status = status
        self.title = title
        self.content = content
        self.raw_bytes = raw_bytes
        self.byte_size = byte_size
        self.latency_ms = latency_ms
        self.error = error
        self.redirect_hops = redirect_hops
        self.resolved_ip = resolved_ip


def guarded_fetch(
    url: str,
    remaining_deadline_seconds: float = 10.0,
    max_bytes: int = 1048576,  # 1 MiB streaming byte cap
    max_redirects: int = 3,
    allowed_schemes: Tuple[str, ...] = ("http", "https"),
    remaining_fetches: Optional[int] = None,
    telemetry_logger: Optional[Any] = None,
    run_id: Optional[str] = None,
    request_id: Optional[str] = None,
    step: int = 0,
) -> FetchResult:
    """
    Executes a guarded HTTP GET fetch complying with Assignment 2 SSRF requirements:
    1. Rejects if remaining deadline <= 0.
    2. Validates scheme and hostname.
    3. Resolves DNS and validates all IP records (loopback, private, metadata, public IPv6).
    4. Connects via pinned IP transport to prevent DNS rebinding.
    5. Enforces hop-by-hop manual redirect inspection up to max_redirects hops.
    6. Stops before following redirect if remaining_fetches is exhausted.
    7. Streams response body up to max_bytes (1 MiB), terminating stream if exceeded.
    8. Emits outbound telemetry if logger is provided.
    """
    start_time = time.monotonic()

    def _maybe_log(result: FetchResult) -> FetchResult:
        if telemetry_logger:
            telemetry_logger.log_event(
                service="verifier",
                run_id=run_id,
                request_id=request_id,
                step=step,
                direction="outbound",
                endpoint_or_tool=f"GET {sanitize_url(result.current_url or url)}",
                status=result.status,
                latency_ms=result.latency_ms,
                attempt=result.redirect_hops + 1,
                tokens=0,
            )
        return result

    # 1. Check remaining deadline before beginning
    if remaining_deadline_seconds <= 0.0:
        return _maybe_log(
            FetchResult(
                url=url,
                current_url=url,
                status="error",
                error="Monotonic execution deadline reached before starting fetch",
            )
        )

    current_url = url
    redirect_hops = 0
    pinned_ip: Optional[str] = None

    while True:
        # Validate scheme
        try:
            parsed = urlparse(current_url)
        except Exception as e:
            return _maybe_log(
                FetchResult(
                    url=url,
                    current_url=current_url,
                    status="rejected",
                    error=f"Malformed URL: {e}",
                    redirect_hops=redirect_hops,
                )
            )

        if parsed.scheme.lower() not in allowed_schemes:
            return _maybe_log(
                FetchResult(
                    url=url,
                    current_url=current_url,
                    status="rejected",
                    error=f"Prohibited scheme '{parsed.scheme}'. Only {allowed_schemes} are allowed",
                    redirect_hops=redirect_hops,
                )
            )

        hostname = parsed.hostname
        if not hostname:
            return _maybe_log(
                FetchResult(
                    url=url,
                    current_url=current_url,
                    status="rejected",
                    error="URL has no hostname",
                    redirect_hops=redirect_hops,
                )
            )

        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        # 3. DNS Resolution and SSRF destination validation
        is_safe, err_msg, approved_ips = resolve_and_validate_hostname(hostname, port)
        if not is_safe or not approved_ips:
            return _maybe_log(
                FetchResult(
                    url=url,
                    current_url=current_url,
                    status="rejected",
                    error=err_msg or "Destination rejected by SSRF guardrails",
                    redirect_hops=redirect_hops,
                )
            )

        pinned_ip = approved_ips[0]

        # Calculate call timeout bounded by remaining deadline
        elapsed = time.monotonic() - start_time
        call_timeout = min(10.0, max(0.1, remaining_deadline_seconds - elapsed))

        # 4. Connect via pinned IP transport
        try:
            transport = PinnedHTTPTransport(pinned_ip=pinned_ip, verify=True)
            with httpx.Client(
                transport=transport,
                timeout=httpx.Timeout(call_timeout),
                follow_redirects=False,
                headers={"User-Agent": "VerifierService/1.0 (SafeSSRFGuard)"},
            ) as client:
                req = client.build_request("GET", current_url)
                resp = client.send(req, stream=True)

                # 5. Handle redirects manually
                if resp.is_redirect:
                    resp.close()
                    location = resp.headers.get("location")
                    if not location:
                        return _maybe_log(
                            FetchResult(
                                url=url,
                                current_url=current_url,
                                status="error",
                                error="Redirect status received without Location header",
                                redirect_hops=redirect_hops,
                                resolved_ip=pinned_ip,
                            )
                        )

                    redirect_hops += 1
                    if redirect_hops > max_redirects:
                        return _maybe_log(
                            FetchResult(
                                url=url,
                                current_url=current_url,
                                status="error",
                                error=f"Exceeded maximum redirect limit of {max_redirects}",
                                redirect_hops=redirect_hops,
                                resolved_ip=pinned_ip,
                            )
                        )

                    # Check remaining fetch budget for redirect hop
                    if remaining_fetches is not None and remaining_fetches - redirect_hops < 1:
                        return _maybe_log(
                            FetchResult(
                                url=url,
                                current_url=current_url,
                                status="error",
                                error="Fetch budget exhausted before following redirect hop",
                                redirect_hops=redirect_hops - 1,
                                resolved_ip=pinned_ip,
                            )
                        )

                    # Resolve relative redirect
                    current_url = urljoin(current_url, location)
                    continue

                # 6. Stream content up to max_bytes (1 MiB)
                content_chunks: List[bytes] = []
                total_bytes = 0
                for chunk in resp.iter_bytes():
                    needed = min(len(chunk), max_bytes - total_bytes)
                    if needed > 0:
                        content_chunks.append(chunk[:needed])
                        total_bytes += needed
                    if total_bytes >= max_bytes:
                        break

                resp.close()
                raw_bytes = b"".join(content_chunks)
                latency_ms = int((time.monotonic() - start_time) * 1000)

                # Decode and clean HTML
                text_content = ""
                title = ""
                try:
                    encoding = resp.encoding or "utf-8"
                    decoded_html = raw_bytes.decode(encoding, errors="replace")
                    title, text_content = clean_html_to_text(decoded_html)
                except Exception:
                    text_content = raw_bytes.decode("utf-8", errors="replace")

                return _maybe_log(
                    FetchResult(
                        url=url,
                        current_url=current_url,
                        status="fetched",
                        title=title,
                        content=text_content,
                        raw_bytes=raw_bytes,
                        byte_size=total_bytes,
                        latency_ms=latency_ms,
                        redirect_hops=redirect_hops,
                        resolved_ip=pinned_ip,
                    )
                )

        except Exception as e:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            return _maybe_log(
                FetchResult(
                    url=url,
                    current_url=current_url,
                    status="error",
                    error=f"Network error fetching source: {e}",
                    latency_ms=latency_ms,
                    redirect_hops=redirect_hops,
                    resolved_ip=pinned_ip,
                )
            )
