"""
Tests for Task 5.10: Orchestration Telemetry and Deterministic Report Generation.
CSCI-GA.2630 Assignment 2
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import pytest

from backend.app.models import TrackerArticle, TrackerClaim, TrackerDevelopment, TrackerRun
from backend.app.orchestration.report import generate_markdown_report, save_report_artifacts
from backend.app.orchestration.telemetry import TelemetryLogger, TelemetryRecord


def test_telemetry_logger_emits_11_fields_and_excludes_secrets():
    """Spec 5.10: Emits 11-field schema and excludes secrets."""
    with TemporaryDirectory() as tmp_dir:
        log_file = Path(tmp_dir) / "orchestrator.jsonl"
        logger = TelemetryLogger(log_path=log_file)

        run_id = str(uuid4())
        req_id = str(uuid4())

        record = logger.log_event(
            service="orchestrator",
            run_id=run_id,
            request_id=req_id,
            step=1,
            direction="outbound",
            endpoint_or_tool="researcher:/research",
            status="200",
            latency_ms=152.3,
            attempt=1,
            tokens=0,
            secret_token="SUPER_SECRET_LEAK",  # Must be stripped!
        )

        assert record.service == "orchestrator"
        assert record.run_id == run_id
        assert record.request_id == req_id
        assert record.step == 1
        assert record.direction == "outbound"
        assert record.endpoint_or_tool == "researcher:/research"
        assert record.status == "200"
        assert record.latency_ms == 152.3
        assert record.attempt == 1
        assert record.tokens == 0

        # Verify disk JSONL line
        assert log_file.exists()
        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert "secret_token" not in entry
        assert "SUPER_SECRET_LEAK" not in lines[0]
        assert len(entry) == 11  # Exactly the 11 OpenSpec fields!


def test_deterministic_report_generation_zero_models():
    """Spec 5.10: Deterministic report artifact generated with zero model synthesis."""
    run = TrackerRun(
        id=1,
        run_uuid=str(uuid4()),
        run_number=1,
        topic="AI Engineering",
        target_k=1,
        status="complete",
        researcher_status="complete",
        verifier_status="complete",
        step_count=8,
        fetch_count=7,
        tokens_spent=15000,
        measured_steps=8,
        measured_fetches=7,
        measured_tokens=15000,
        charged_steps=8,
        charged_fetches=7,
        charged_tokens=15000,
        reserved_steps=30,
        reserved_fetches=40,
        reserved_tokens=100000,
    )

    dev = TrackerDevelopment(
        id=1,
        run_id=1,
        rank=1,
        title="Senior AI Researcher",
        company="Open Tech",
        primary_url="https://example.com/job",
        recrawl_status="New since last run",
    )
    claim1 = TrackerClaim(
        id=1,
        run_id=1,
        development_id=1,
        claim_id="c1",
        text="Requires PyTorch",
        source_url="https://example.com/job",
        verdict="supported",
        evidence="Requires PyTorch and Python",
    )
    claim2 = TrackerClaim(
        id=2,
        run_id=1,
        development_id=1,
        claim_id="c2",
        text="Pays $200k",
        source_url="https://example.com/job",
        verdict="unverified",
        evidence=None,
    )
    dev.claims = [claim1, claim2]
    run.developments = [dev]

    art = TrackerArticle(
        id=1,
        run_id=1,
        url="https://example.com/job",
        title="Job Post",
        status="fetched",
        fetch_time_ms=120,
    )
    run.articles = [art]

    md_content = generate_markdown_report(run)

    assert "# Tracker Execution Report" in md_content
    assert "Senior AI Researcher" in md_content
    assert "Open Tech" in md_content
    assert "[SUPPORTED]" in md_content
    assert "Requires PyTorch and Python" in md_content
    assert "[UNVERIFIED]" in md_content
    assert "Job Post" in md_content


def test_save_report_artifacts():
    """Spec 5.10: Saves Markdown and JSON report artifacts."""
    with TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        run = TrackerRun(
            id=1,
            run_uuid=str(uuid4()),
            run_number=1,
            topic="AI Engineering",
            target_k=1,
            status="complete",
            researcher_status="complete",
            verifier_status="complete",
        )
        run.developments = []
        run.articles = []

        md_path, json_path = save_report_artifacts(run, output_dir=out_dir)

        assert md_path.exists()
        assert json_path.exists()
        assert md_path.suffix == ".md"
        assert json_path.suffix == ".json"

        # Verify JSON report structure
        json_data = json.loads(json_path.read_text(encoding="utf-8"))
        assert json_data["run_uuid"] == run.run_uuid
        assert json_data["status"] == "complete"
