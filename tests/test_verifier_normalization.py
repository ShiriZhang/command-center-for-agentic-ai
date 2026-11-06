"""
Tests for Task 4.4: Pure Code Evidence Verification & String Normalization.
CSCI-GA.2630 Assignment 2
"""

import pytest

from services.verifier.normalization import (
    normalize_for_matching,
    verify_evidence,
)


class TestStringNormalization:
    """Verifies html.unescape, NFKC, whitespace collapse, outer trim, and lowercase."""

    def test_html_entities_decoded(self):
        raw = "We&rsquo;re hiring &amp; expanding &quot;AI&quot; team"
        norm = normalize_for_matching(raw)
        assert "we're hiring & expanding \"ai\" team" == norm or "we’re hiring & expanding \"ai\" team" == norm

    def test_unicode_nfkc(self):
        # Fullwidth 'ＡＩ' becomes 'ai' under NFKC + lowercase
        raw = "Full-time ＡＩ role"
        norm = normalize_for_matching(raw)
        assert norm == "full-time ai role"

    def test_whitespace_collapse_and_outer_trim(self):
        raw = "   \n\t  Software   Engineer  \n\t  in   New York   \t\n  "
        norm = normalize_for_matching(raw)
        assert norm == "software engineer in new york"


class TestCodeEvidenceVerification:
    """Verifies code-level evidence verification and downgrade rules."""

    def test_supported_verdict_with_matching_excerpt(self):
        page_text = "Acme Corp is hiring a Junior AI Engineer with $120k salary in NYC."
        verdict, evidence = verify_evidence(
            verdict="supported",
            evidence="hiring a Junior AI Engineer",
            page_text=page_text,
        )
        assert verdict == "supported"
        assert evidence == "hiring a Junior AI Engineer"

    def test_supported_verdict_with_html_entity_in_page_or_evidence(self):
        page_text = "Acme &amp; Sons is looking for engineers."
        verdict, evidence = verify_evidence(
            verdict="supported",
            evidence="Acme & Sons is looking",
            page_text=page_text,
        )
        assert verdict == "supported"
        assert evidence == "Acme & Sons is looking"

    def test_absent_excerpt_downgrades_to_unsupported(self):
        """Spec Scenario: Hallucinated evidence absent from page downgrades to unsupported with null evidence."""
        page_text = "We offer $100k - $120k base compensation."
        verdict, evidence = verify_evidence(
            verdict="supported",
            evidence="We offer $250k base compensation",  # Absent!
            page_text=page_text,
        )
        assert verdict == "unsupported"
        assert evidence is None

    def test_empty_or_whitespace_evidence_downgrades_to_unsupported(self):
        """Spec requirement: Blank or empty excerpt downgrades to unsupported with null evidence."""
        page_text = "Some page text"
        verdict, evidence = verify_evidence(
            verdict="supported",
            evidence="   \n\t  ",
            page_text=page_text,
        )
        assert verdict == "unsupported"
        assert evidence is None

    def test_none_evidence_downgrades_to_unsupported(self):
        page_text = "Some page text"
        verdict, evidence = verify_evidence(
            verdict="supported",
            evidence=None,
            page_text=page_text,
        )
        assert verdict == "unsupported"
        assert evidence is None

    def test_overlong_evidence_downgrades_to_unsupported(self):
        """Spec requirement: Excerpt exceeding 300 Unicode characters downgrades to unsupported."""
        page_text = "A" * 500
        overlong_evidence = "A" * 301
        verdict, evidence = verify_evidence(
            verdict="supported",
            evidence=overlong_evidence,
            page_text=page_text,
        )
        assert verdict == "unsupported"
        assert evidence is None

    def test_unsupported_verdict_forces_null_evidence(self):
        """Non-supported verdicts must always have null evidence."""
        verdict, evidence = verify_evidence(
            verdict="unsupported",
            evidence="some excerpt",
            page_text="some page text",
        )
        assert verdict == "unsupported"
        assert evidence is None

    def test_unreachable_verdict_forces_null_evidence(self):
        verdict, evidence = verify_evidence(
            verdict="unreachable",
            evidence="some excerpt",
            page_text="",
        )
        assert verdict == "unreachable"
        assert evidence is None
