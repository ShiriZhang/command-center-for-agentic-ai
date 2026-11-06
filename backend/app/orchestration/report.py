"""
Deterministic Report Generator for Orchestration Runs.
Produces clean Markdown and JSON reports without model synthesis (pure Python logic).
CSCI-GA.2630 Assignment 2
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.app.models import TrackerRun


def generate_markdown_report(run: TrackerRun) -> str:
    """
    Generates a deterministic Markdown report artifact for a completed or partial run.
    Uses pure Python code with ZERO model calls.
    """
    r_any: Any = run
    status_badge = str(r_any.status or "unknown").upper()
    res_status = str(r_any.researcher_status or "none")
    ver_status = str(r_any.verifier_status or "none")
    res_error = str(r_any.researcher_error) if r_any.researcher_error else "None"
    ver_error = str(r_any.verifier_error) if r_any.verifier_error else "None"

    lines: List[str] = [
        f"# Tracker Execution Report — Run #{r_any.run_number}",
        "",
        f"**Run UUID:** `{r_any.run_uuid}`  ",
        f"**Topic:** {r_any.topic}  ",
        f"**Target K:** {r_any.target_k}  ",
        f"**Overall Status:** `{status_badge}`  ",
        f"**Baseline Eligible:** `{bool(r_any.is_baseline_eligible)}`  ",
        f"**Reset Generation:** `{r_any.reset_generation}`  ",
        f"**Created At:** {r_any.created_at}  ",
        "",
    ]

    if r_any.stale_source_run_uuid:
        lines.extend([
            "> [!NOTE]",
            f"> **Stale Baseline Fallback:** Researcher failed or was interrupted. Displaying historical results from baseline run `{r_any.stale_source_run_uuid}`.",
            "",
        ])

    # Section 1: Resource Accounting
    lines.extend([
        "## 1. Resource Consumption and Accounting",
        "",
        "| Metric | Steps (Calls) | Fetches (Hops) | Tokens Spent |",
        "| :--- | :---: | :---: | :---: |",
        f"| **Reserved Total** | {r_any.reserved_steps or 0} | {r_any.reserved_fetches or 0} | {r_any.reserved_tokens or 0} |",
        f"| **Measured Usage** | {r_any.measured_steps or 0} | {r_any.measured_fetches or 0} | {r_any.measured_tokens or 0} |",
        f"| **Charged Usage** | {r_any.charged_steps or 0} | {r_any.charged_fetches or 0} | {r_any.charged_tokens or 0} |",
        "",
        "### Worker Outcomes",
        f"- **Researcher:** `{res_status}` (Error: {res_error})",
        f"- **Verifier:** `{ver_status}` (Error: {ver_error})",
        "",
    ])

    # Section 2: Top K Job Developments
    developments = getattr(run, "developments", []) or []
    lines.extend([
        f"## 2. Synthesized Job Opportunities (Top {len(developments)})",
        "",
    ])

    if not developments:
        if res_status in ("failed", "interrupted"):
            lines.extend([
                "_Researcher failed or was interrupted. There are no new results and no saved baseline._",
                "",
            ])
        else:
            lines.extend([
                "_No job openings synthesized for this execution._",
                "",
            ])
    else:
        for dev in developments:
            d_any: Any = dev
            badge = d_any.recrawl_status or "New since last run"
            lines.extend([
                f"### {d_any.rank}. {d_any.title} — {d_any.company}",
                f"- **Status Badge:** `{badge}`",
                f"- **Primary URL:** [{d_any.primary_url}]({d_any.primary_url})",
                f"- **Location:** {d_any.location or 'Not specified'}",
                f"- **Compensation:** {d_any.compensation or 'Not specified'}",
            ])
            if d_any.qualifications_summary:
                lines.append(f"- **Qualifications:** {d_any.qualifications_summary}")

            claims = getattr(dev, "claims", []) or []
            if claims:
                lines.append("")
                lines.append("**Atomic Cited Claims & Verification Verdicts:**")
                for c in claims:
                    c_any: Any = c
                    verdict_str = str(c_any.verdict or "unverified").upper()
                    lines.append(
                        f"  - `[{verdict_str}]` Claim `{c_any.claim_id}`: {c_any.text}  "
                    )
                    lines.append(f"    - *Source:* [{c_any.source_url}]({c_any.source_url})")
                    if c_any.verdict == "supported" and c_any.evidence:
                        lines.append(f"    - *Normalized Excerpt:* \"{c_any.evidence}\"")
            lines.append("")

    # Section 3: Web Fetch Audit
    articles = getattr(run, "articles", []) or []
    lines.extend([
        f"## 3. Web Fetch Source Audit ({len(articles)} sources)",
        "",
    ])

    if not articles:
        lines.extend([
            "_No source pages fetched during this execution._",
            "",
        ])
    else:
        lines.extend([
            "| Source URL | Status | Latency | Title / Notes |",
            "| :--- | :---: | :---: | :--- |",
        ])
        for art in articles:
            a_any: Any = art
            title_str = (a_any.title or "Untitled").replace("|", "-")
            lines.append(
                f"| [{a_any.url}]({a_any.url}) | `{a_any.status}` | {a_any.fetch_time_ms or 0}ms | {title_str} |"
            )
        lines.append("")

    return "\n".join(lines)


def save_report_artifacts(
    run: TrackerRun,
    output_dir: Optional[Path] = None,
) -> Tuple[Path, Path]:
    """
    Saves deterministic Markdown and JSON execution artifacts for the run.
    Returns (markdown_path, json_path).
    """
    r_any: Any = run
    run_uuid = str(r_any.run_uuid)
    base_dir = output_dir or Path("reports")
    base_dir.mkdir(parents=True, exist_ok=True)

    md_path = base_dir / f"run_{run_uuid}.md"
    json_path = base_dir / f"run_{run_uuid}.json"

    # Markdown report
    md_content = generate_markdown_report(run)
    md_path.write_text(md_content, encoding="utf-8")

    # Structured JSON report
    developments = []
    for dev in getattr(run, "developments", []) or []:
        d_any: Any = dev
        claims = [
            {
                "claim_id": str(c.claim_id),
                "text": str(c.text),
                "source_url": str(c.source_url),
                "verdict": str(c.verdict),
                "evidence": c.evidence,
            }
            for c in getattr(dev, "claims", []) or []
        ]
        developments.append({
            "rank": d_any.rank,
            "title": d_any.title,
            "company": d_any.company,
            "primary_url": d_any.primary_url,
            "location": d_any.location,
            "compensation": d_any.compensation,
            "recrawl_status": d_any.recrawl_status,
            "claims": claims,
        })

    articles = [
        {
            "url": str(a.url),
            "status": str(a.status),
            "fetch_time_ms": a.fetch_time_ms,
            "title": a.title,
            "error_message": a.error_message,
        }
        for a in getattr(run, "articles", []) or []
    ]

    json_payload = {
        "run_uuid": run_uuid,
        "run_number": r_any.run_number,
        "topic": r_any.topic,
        "target_k": r_any.target_k,
        "status": r_any.status,
        "researcher_status": r_any.researcher_status,
        "verifier_status": r_any.verifier_status,
        "is_baseline_eligible": r_any.is_baseline_eligible,
        "reset_generation": r_any.reset_generation,
        "stale_source_run_uuid": r_any.stale_source_run_uuid,
        "created_at": r_any.created_at.isoformat() if r_any.created_at else None,
        "accounting": {
            "reserved_steps": r_any.reserved_steps or 0,
            "reserved_fetches": r_any.reserved_fetches or 0,
            "reserved_tokens": r_any.reserved_tokens or 0,
            "measured_steps": r_any.measured_steps or 0,
            "measured_fetches": r_any.measured_fetches or 0,
            "measured_tokens": r_any.measured_tokens or 0,
            "charged_steps": r_any.charged_steps or 0,
            "charged_fetches": r_any.charged_fetches or 0,
            "charged_tokens": r_any.charged_tokens or 0,
        },
        "developments": developments,
        "articles": articles,
    }

    json_path.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")
    return md_path, json_path
