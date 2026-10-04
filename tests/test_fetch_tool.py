"""
Unit Test Suite for Task 2.1: fetch_article SSRF Guardrails and Content Sanitization.
Tests loopback rejection, private network rejection, metadata rejection, and public site fetching.
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tracker.tools.fetch import fetch_article, validate_url_ssrf, clean_html_to_text


class TestFetchArticleGuardrails(unittest.TestCase):

    def test_reject_loopback_ipv4(self):
        """Verify that loopback 127.0.0.1 is strictly rejected before socket connection."""
        res = fetch_article("http://127.0.0.1:8000/admin")
        self.assertEqual(res["status"], "rejected")
        self.assertIn("loopback", res["error"].lower())

    def test_reject_localhost_hostname(self):
        """Verify that 'localhost' resolving to 127.0.0.1 is strictly rejected."""
        res = fetch_article("http://localhost:8000/healthz")
        self.assertEqual(res["status"], "rejected")
        self.assertIn("loopback", res["error"].lower())

    def test_reject_cloud_metadata_link_local(self):
        """Verify that AWS/Cloud metadata address 169.254.169.254 is rejected."""
        res = fetch_article("http://169.254.169.254/latest/meta-data")
        self.assertEqual(res["status"], "rejected")
        self.assertTrue("link-local" in res["error"].lower() or "blocked" in res["error"].lower())

    def test_reject_private_rfc1918_addresses(self):
        """Verify that private IP ranges (10.0.0.0/8, 192.168.0.0/16) are rejected."""
        res_class_a = fetch_article("http://10.1.2.3:8080/internal")
        self.assertEqual(res_class_a["status"], "rejected")
        self.assertIn("private", res_class_a["error"].lower())

        res_class_c = fetch_article("http://192.168.1.1/router")
        self.assertEqual(res_class_c["status"], "rejected")
        self.assertIn("private", res_class_c["error"].lower())

    def test_reject_non_http_schemes(self):
        """Verify that file:// and ftp:// are rejected at the scheme validation step."""
        is_safe, error, _ = validate_url_ssrf("file:///etc/passwd")
        self.assertFalse(is_safe)
        self.assertIn("forbidden scheme", error.lower())

        is_safe_ftp, error_ftp, _ = validate_url_ssrf("ftp://example.com")
        self.assertFalse(is_safe_ftp)
        self.assertIn("forbidden scheme", error_ftp.lower())

    def test_html_script_decomposition(self):
        """Verify that malicious script tags seeded in untrusted pages are stripped."""
        malicious_html = """
        <html>
            <head><title>Test Job Posting</title></head>
            <body>
                <h1>Staff Research Engineer</h1>
                <script>alert('Stored XSS Vulnerability'); window.location='http://attacker.com';</script>
                <p>We are hiring an ML Engineer in New York.</p>
                <style>body { display: none; }</style>
            </body>
        </html>
        """
        title, clean_text = clean_html_to_text(malicious_html)
        self.assertEqual(title, "Test Job Posting")
        self.assertIn("Staff Research Engineer", clean_text)
        self.assertIn("We are hiring an ML Engineer", clean_text)
        # Ensure script code is NOT present in text
        self.assertNotIn("alert", clean_text)
        self.assertNotIn("attacker.com", clean_text)
        self.assertNotIn("display: none", clean_text)

    def test_fetch_legitimate_public_url(self):
        """Verify that public internet URLs pass SSRF validation and fetch properly."""
        res = fetch_article("https://example.com")
        self.assertEqual(res["status"], "fetched")
        self.assertIsNone(res["error"])
        self.assertGreater(res["byte_size"], 0)
        self.assertIn("Example Domain", res["title"])
        self.assertIn("Example Domain", res["content"])


if __name__ == "__main__":
    unittest.main()
