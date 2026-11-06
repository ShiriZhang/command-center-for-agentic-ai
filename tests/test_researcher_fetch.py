"""
Unit tests for Task 3.6: Researcher SSRF Guardrails and Fetch Path Security.
Verifies IP validation (loopback, private, metadata, public IPv6),
DNS inspection, hop-by-hop redirect inspection, 1 MiB streaming byte caps,
and remaining deadline bounding.
"""

import socket
import pytest
from unittest.mock import patch, MagicMock

from services.researcher.fetch import (
    validate_destination_ip,
    resolve_and_validate_hostname,
    guarded_fetch,
    FetchResult,
)


class TestIPAndDNSGuardrails:
    def test_loopback_rejections(self):
        """Loopback IPs (IPv4 and IPv6) must be rejected."""
        assert validate_destination_ip("127.0.0.1")[0] is False
        assert validate_destination_ip("127.0.0.5")[0] is False
        assert validate_destination_ip("::1")[0] is False

    def test_private_network_rejections(self):
        """RFC 1918 private IPv4 and ULA IPv6 must be rejected."""
        assert validate_destination_ip("10.0.0.1")[0] is False
        assert validate_destination_ip("172.16.5.1")[0] is False
        assert validate_destination_ip("192.168.1.100")[0] is False
        assert validate_destination_ip("fc00::1")[0] is False

    def test_metadata_and_link_local_rejections(self):
        """Cloud metadata (169.254.169.254) and link-local ranges must be rejected."""
        assert validate_destination_ip("169.254.169.254")[0] is False
        assert validate_destination_ip("169.254.1.1")[0] is False
        assert validate_destination_ip("fe80::1")[0] is False

    def test_mapped_ipv4_in_ipv6_rejections(self):
        """IPv4-mapped IPv6 pointing to private/loopback must be rejected."""
        assert validate_destination_ip("::ffff:127.0.0.1")[0] is False
        assert validate_destination_ip("::ffff:169.254.169.254")[0] is False
        assert validate_destination_ip("::ffff:10.0.0.1")[0] is False

    def test_public_ipv4_accepted(self):
        """Standard public IPv4 addresses must be accepted."""
        is_safe, err = validate_destination_ip("8.8.8.8")
        assert is_safe is True
        assert err is None

    def test_public_ipv6_accepted(self):
        """Spec requirement: Blocking every IPv6 address is not the policy; public IPv6 is permitted."""
        is_safe, err = validate_destination_ip("2001:4860:4860::8888")
        assert is_safe is True
        assert err is None

        is_safe2, _ = validate_destination_ip("2607:f8b0:4004:809::200e")
        assert is_safe2 is True

    def test_dns_resolution_rejects_mixed_records_with_private_ip(self):
        """If DNS returns multiple records and any one is private, reject the host."""
        mock_addrinfo = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80)),  # Poisoned/Private
        ]
        with patch("socket.getaddrinfo", return_value=mock_addrinfo):
            is_safe, err, _ = resolve_and_validate_hostname("example.com", 80)
            assert is_safe is False
            assert "private" in str(err).lower() or "rejected" in str(err).lower()

    def test_dns_resolution_accepts_clean_public_records(self):
        mock_addrinfo = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 443)),
        ]
        with patch("socket.getaddrinfo", return_value=mock_addrinfo):
            is_safe, err, ips = resolve_and_validate_hostname("example.com", 443)
            assert is_safe is True
            assert err is None
            assert len(ips) == 2


class TestGuardedFetchExecution:
    def test_reject_forbidden_scheme(self):
        """Only http and https schemes are permitted."""
        res = guarded_fetch("file:///etc/passwd", remaining_deadline_seconds=10.0)
        assert res.status == "rejected"
        assert "scheme" in str(res.error).lower()

        res2 = guarded_fetch("gopher://127.0.0.1:70", remaining_deadline_seconds=10.0)
        assert res2.status == "rejected"

    def test_reject_when_deadline_exhausted(self):
        """If remaining deadline is <= 0, do not connect; return error immediately."""
        res = guarded_fetch("https://example.com", remaining_deadline_seconds=0.0)
        assert res.status == "error"
        assert "deadline" in str(res.error).lower() or "timeout" in str(res.error).lower()

    def test_reject_redirect_to_cloud_metadata(self):
        """A redirect to 169.254.169.254 must be intercepted and rejected without fetching metadata."""
        mock_resp_redirect = MagicMock()
        mock_resp_redirect.status_code = 302
        mock_resp_redirect.headers = {"Location": "http://169.254.169.254/latest/meta-data"}

        with patch("socket.getaddrinfo") as mock_dns, patch("httpx.Client.stream") as mock_stream:
            # First hop: public IP
            mock_dns.side_effect = [
                [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))],
                [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))],
            ]
            mock_stream.return_value.__enter__.return_value = mock_resp_redirect

            res = guarded_fetch("http://example.com/redirect", remaining_deadline_seconds=10.0)
            assert res.status == "rejected"
            assert "metadata" in str(res.error).lower() or "link-local" in str(res.error).lower()
            # Must NOT have made a second HTTP request to metadata!
            assert mock_stream.call_count == 1

    def test_streaming_byte_limit_enforced_at_1mb(self):
        """Stream exceeding 1 MiB (1,048,576 bytes) must be capped at 1 MiB."""
        oversized_chunk = b"x" * 65536  # 64 KiB chunks
        # 20 chunks = 1,310,720 bytes (> 1 MiB)
        chunks = [oversized_chunk for _ in range(20)]

        mock_stream_response = MagicMock()
        mock_stream_response.status_code = 200
        mock_stream_response.headers = {"Content-Type": "text/html"}
        mock_stream_response.encoding = "utf-8"
        mock_stream_response.iter_bytes.return_value = iter(chunks)

        with patch("socket.getaddrinfo") as mock_dns, patch("httpx.Client.stream") as mock_stream:
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
            mock_stream.return_value.__enter__.return_value = mock_stream_response

            res = guarded_fetch("http://example.com/huge", remaining_deadline_seconds=10.0, max_bytes=1048576)
            assert res.status == "fetched"
            assert res.byte_size == 1048576
            assert len(res.raw_bytes) == 1048576

    def test_redirect_stops_when_remaining_fetches_exhausted(self):
        """Spec Scenario: WHEN a page response redirects but no fetch allocation remains, worker does not follow it."""
        mock_resp_redirect = MagicMock()
        mock_resp_redirect.status_code = 301
        mock_resp_redirect.headers = {"Location": "http://example.com/target"}

        with patch("socket.getaddrinfo") as mock_dns, patch("httpx.Client.stream") as mock_stream:
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
            mock_stream.return_value.__enter__.return_value = mock_resp_redirect

            # remaining_fetches is 0: initial fetch succeeds but redirect cannot be followed
            res = guarded_fetch(
                "http://example.com/start",
                remaining_deadline_seconds=10.0,
                remaining_fetches=0,
            )
            assert res.status == "error"
            assert "allocation exhausted" in str(res.error).lower()
            assert mock_stream.call_count == 1

    def test_pinned_transport_attaches_approved_ip(self):
        """SSRF: Connection must pin to resolved IP via PinnedHTTPTransport."""
        from services.researcher.fetch import PinnedHTTPTransport, PinnedSyncBackend
        transport = PinnedHTTPTransport("93.184.216.34")
        assert isinstance(transport._pool._network_backend, PinnedSyncBackend)
        assert transport._pool._network_backend.pinned_ip == "93.184.216.34"

    def test_guarded_fetch_emits_outbound_telemetry(self, tmp_path):
        """Task 3.7: Guarded fetch emits outbound telemetry."""
        from services.researcher.telemetry import TelemetryLogger
        log_file = tmp_path / "fetch_telemetry.jsonl"
        logger = TelemetryLogger(log_path=log_file)

        mock_stream_response = MagicMock()
        mock_stream_response.status_code = 200
        mock_stream_response.headers = {"Content-Type": "text/html"}
        mock_stream_response.encoding = "utf-8"
        mock_stream_response.iter_bytes.return_value = iter([b"<html><head><title>Test</title></head><body>Hello</body></html>"])

        with patch("socket.getaddrinfo") as mock_dns, patch("httpx.Client.stream") as mock_stream:
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
            mock_stream.return_value.__enter__.return_value = mock_stream_response

            res = guarded_fetch(
                "http://example.com/test",
                remaining_deadline_seconds=10.0,
                telemetry_logger=logger,
                run_id="run-1",
                request_id="req-1",
                step=1,
            )
            assert res.status == "fetched"

        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        import json
        rec = json.loads(lines[0])
        assert rec["direction"] == "outbound"
        assert rec["service"] == "researcher"
        assert rec["endpoint_or_tool"] == "GET http://example.com/test"
        assert rec["status"] == "fetched"
        assert rec["run_id"] == "run-1"
        assert rec["request_id"] == "req-1"
