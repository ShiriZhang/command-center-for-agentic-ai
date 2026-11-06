"""
Tests for Task 4.2: Verifier Service Guarded Fetching & SSRF Guardrails.
CSCI-GA.2630 Assignment 2
"""

from unittest.mock import MagicMock, patch
import pytest

from services.verifier.fetch import (
    FetchResult,
    clean_html_to_text,
    guarded_fetch,
    resolve_and_validate_hostname,
    validate_destination_ip,
)


class TestSSRFIPValidation:
    """Verifies strict IP filtering against loopback, private, metadata, and unsafe IPv6."""

    def test_reject_loopback_ipv4(self):
        is_safe, err = validate_destination_ip("127.0.0.1")
        assert not is_safe
        assert "Loopback" in str(err)

    def test_reject_loopback_ipv6(self):
        is_safe, err = validate_destination_ip("::1")
        assert not is_safe
        assert "Loopback" in str(err)

    def test_reject_cloud_metadata_ipv4(self):
        is_safe, err = validate_destination_ip("169.254.169.254")
        assert not is_safe
        assert "metadata" in str(err).lower() or "link-local" in str(err).lower()

    def test_reject_private_ranges(self):
        for ip in ["10.0.0.1", "172.16.0.5", "192.168.1.100"]:
            is_safe, err = validate_destination_ip(ip)
            assert not is_safe
            assert "Private" in str(err)

    def test_reject_ipv4_mapped_ipv6_loopback(self):
        is_safe, err = validate_destination_ip("::ffff:127.0.0.1")
        assert not is_safe
        assert "Loopback" in str(err)

    def test_reject_link_local_ipv6(self):
        is_safe, err = validate_destination_ip("fe80::1")
        assert not is_safe
        assert "Link-local" in str(err) or "metadata" in str(err).lower()

    def test_permit_public_ipv4(self):
        is_safe, err = validate_destination_ip("93.184.216.34")
        assert is_safe
        assert err is None

    def test_permit_public_ipv6(self):
        is_safe, err = validate_destination_ip("2606:4700:4700::1111")
        assert is_safe
        assert err is None


class TestHostnameResolution:
    """Verifies DNS pre-resolution and rejection if any returned record is prohibited."""

    def test_dns_resolution_rejects_localhost(self):
        is_safe, err, ips = resolve_and_validate_hostname("localhost", 80)
        assert not is_safe
        assert "prohibited" in str(err).lower() or "loopback" in str(err).lower()

    @patch("socket.getaddrinfo")
    def test_dns_resolution_rejects_dual_homed_with_prohibited_ip(self, mock_getaddrinfo):
        # Dual-homed: one public, one private
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 80)),
            (2, 1, 6, "", ("10.0.0.1", 80)),
        ]
        is_safe, err, ips = resolve_and_validate_hostname("malicious-rebind.com", 80)
        assert not is_safe
        assert "prohibited" in str(err).lower()


class TestGuardedFetchExecution:
    """Verifies streaming limit, redirect inspection, deadline enforcement, and SSRF rejection."""

    def test_direct_localhost_rejected_without_page_request(self):
        """Spec Scenario: Direct prohibited source never fetched -> unreachable without page request."""
        res = guarded_fetch("http://127.0.0.1:8000/admin")
        assert res.status == "rejected"
        assert "prohibited" in str(res.error).lower() or "loopback" in str(res.error).lower()

    def test_direct_metadata_rejected_without_page_request(self):
        res = guarded_fetch("http://169.254.169.254/latest/meta-data/")
        assert res.status == "rejected"
        assert "prohibited" in str(res.error).lower() or "metadata" in str(res.error).lower()

    def test_expired_deadline_aborts_before_fetching(self):
        res = guarded_fetch("https://example.com/page", remaining_deadline_seconds=0.0)
        assert res.status == "error"
        assert "deadline" in str(res.error).lower()

    @patch("services.verifier.fetch.resolve_and_validate_hostname")
    @patch("httpx.Client.send")
    def test_redirect_to_cloud_metadata_blocked_per_hop(self, mock_send, mock_resolve):
        """Spec Scenario: Public redirect to cloud metadata blocked before following redirect."""
        # Initial hop resolves to approved public IP
        mock_resolve.side_effect = [
            (True, None, ["93.184.216.34"]),  # 1st hop: safe
            (False, "DNS resolution yielded prohibited address (Link-local / cloud metadata address rejected: 169.254.169.254)", []),  # 2nd hop
        ]

        # 1st response redirects to metadata
        resp1 = MagicMock()
        resp1.is_redirect = True
        resp1.headers = {"location": "http://169.254.169.254/latest/meta-data/"}
        resp1.status_code = 302
        mock_send.return_value = resp1

        res = guarded_fetch("https://example.com/redirector")
        assert res.status == "rejected"
        assert "prohibited" in str(res.error).lower()
        # Must NOT have made a second HTTP request to metadata!
        assert mock_send.call_count == 1

    @patch("services.verifier.fetch.resolve_and_validate_hostname")
    @patch("httpx.Client.send")
    def test_streaming_byte_limit_enforced_at_1mb(self, mock_send, mock_resolve):
        """Spec requirement: 1 MiB (1,048,576 bytes) streaming size cap."""
        mock_resolve.return_value = (True, None, ["93.184.216.34"])

        resp = MagicMock()
        resp.is_redirect = False
        resp.status_code = 200
        resp.headers = {"content-type": "text/html"}

        # Simulate 2 MiB stream
        chunk_size = 64 * 1024
        chunks = [b"A" * chunk_size for _ in range(32)]  # 2 MiB
        resp.iter_bytes.return_value = iter(chunks)
        mock_send.return_value = resp

        res = guarded_fetch("https://example.com/huge-page", max_bytes=1048576)
        assert res.status == "fetched"
        assert res.byte_size == 1048576
        assert len(res.raw_bytes) == 1048576

    @patch("services.verifier.fetch.resolve_and_validate_hostname")
    @patch("httpx.Client.send")
    def test_redirect_stops_when_remaining_fetches_exhausted(self, mock_send, mock_resolve):
        """Spec Scenario: Redirect consumes the last fetch -> stops before following."""
        mock_resolve.return_value = (True, None, ["93.184.216.34"])

        resp1 = MagicMock()
        resp1.is_redirect = True
        resp1.headers = {"location": "https://example.com/target"}
        resp1.status_code = 301
        mock_send.return_value = resp1

        # remaining_fetches is 1 (only enough for the first hop, not for redirect)
        res = guarded_fetch("https://example.com/source", remaining_fetches=1)
        assert res.status == "error"
        assert "fetch budget exhausted" in str(res.error).lower()

    def test_clean_html_to_text(self):
        html = "<html><head><title>Test Title</title></head><body><h1>Heading</h1><script>alert(1);</script><p>Hello World</p></body></html>"
        title, text = clean_html_to_text(html)
        assert title == "Test Title"
        assert "Hello World" in text
        assert "alert(1)" not in text
