"""
CLI Runner for Agentic Tracker.
Supports:
  python -m tracker.run
  python -m tracker.run --reset
  python -m tracker.run --steps 5
  python -m tracker.run --username NYUgrader --password Courant2026!

CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import argparse
import logging
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urlparse

import httpx

from tracker.agent import ResearchAgent
from tracker.config import config
from tracker.memory import RecrawlMemoryManager, JobDeduplicator
from tracker.reporter import (
    generate_run1_report,
    generate_run2_report,
    save_report_and_trace
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("tracker.run")


def authenticate_user(
    username: str,
    password: str,
    backend_url: str
) -> Optional[str]:
    """
    Attempts to authenticate with the A1 platform backend via POST /api/auth/login.
    Returns JWT Bearer access token if successful, None otherwise.
    """
    login_url = f"{backend_url.rstrip('/')}/api/auth/login"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                login_url,
                json={"username": username, "password": password}
            )
            if resp.status_code == 200:
                data = resp.json()
                token = data.get("access_token")
                logger.info(f"Authenticated successfully with backend as user '{username}'.")
                return token
            else:
                logger.warning(
                    f"Backend authentication failed (HTTP {resp.status_code}): {resp.text}"
                )
                return None
    except Exception as e:
        logger.info(f"Backend not available at {backend_url} ({e}); continuing with standalone local state.")
        return None


def sync_run_to_backend(
    token: str,
    backend_url: str,
    run_payload: Dict[str, Any]
) -> bool:
    """
    Posts the executed run record to backend POST /api/tracker/runs.
    """
    endpoint = f"{backend_url.rstrip('/')}/api/tracker/runs"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(endpoint, json=run_payload, headers=headers)
            if resp.status_code in (200, 201):
                logger.info("Successfully synced tracker run to backend database.")
                return True
            logger.warning(f"Failed to sync run to backend (HTTP {resp.status_code}): {resp.text}")
            return False
    except Exception as e:
        logger.warning(f"Could not reach backend to sync run: {e}")
        return False


def run_tracker(
    reset: bool = False,
    steps_override: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    backend_url: Optional[str] = None,
    skip_login: bool = False,
    token: Optional[str] = None,
    reports_dir: Optional[Path] = None,
    state_file: Optional[Union[str, Path]] = None
) -> Dict[str, Any]:
    """
    Orchestrates the tracker lifecycle:
    1. Authentication with backend (if available).
    2. Automatic Run 1 vs Run 2 detection.
    3. Handwritten Agent Loop execution.
    4. Two-Tier Deduplication and Classification.
    5. Report and Trace generation.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    user = username or config.tracker_username or os.getenv("TRACKER_USER", "NYUgrader")
    pwd = password or config.tracker_password or os.getenv("TRACKER_PASSWORD", "Courant2026!")
    b_url = backend_url or config.backend_url or "http://localhost:8000"

    jwt_token = token
    if not jwt_token and not skip_login and user and pwd:
        jwt_token = authenticate_user(user, pwd, b_url)

    memory_manager = RecrawlMemoryManager(state_file_path=state_file)

    if reset:
        logger.info("Reset flag provided. Wiping prior recrawl memory state.")
        memory_manager.reset_state()

    # Detect Run Number
    prior_state = memory_manager.load_previous_state()
    if prior_state is None:
        run_number = 1
        known_urls = set()
        prior_top_k = []
        logger.info("No prior state found. Executing as [RUN 1] (Initial Crawl).")
    else:
        run_number = prior_state.get("run_number", 1) + 1
        known_urls = memory_manager.get_known_urls()
        prior_top_k = memory_manager.get_previous_top_k()
        logger.info(
            f"Prior run state detected (Run {prior_state.get('run_number', 1)}). "
            f"Executing as [RUN {run_number}] (Differential Recrawl) with {len(known_urls)} cached URLs."
        )

    # Execute Autonomous Agent
    agent = ResearchAgent(config=config)
    result = agent.run(
        max_steps=steps_override or config.limits.max_steps,
        previous_urls=known_urls
    )

    def _extract_company_and_title(raw_title: str, raw_comp: Optional[str], u: str) -> Tuple[str, str]:
        comp = (raw_comp or "").strip()
        tit = (raw_title or "AI/ML Role").strip()

        # If comp already provided and valid
        if comp and comp not in ("Company", "Tech Company", "Untitled"):
            for sep in [" - ", " | ", ": ", " – "]:
                prefix = f"{comp}{sep}"
                if tit.lower().startswith(prefix.lower()):
                    tit = tit[len(prefix):].strip()
            return comp, tit

        # Delimiters in title: "Company - Title" or "Title at Company"
        for sep in [" - ", " | ", " – "]:
            if sep in tit:
                parts = [p.strip() for p in tit.split(sep, 1)]
                if len(parts) == 2:
                    p0, p1 = parts[0], parts[1]
                    role_keywords = ["engineer", "scientist", "developer", "intern", "researcher", "analyst", "fellow"]
                    if any(kw in p0.lower() for kw in role_keywords):
                        return p1, p0
                    return p0, p1

        if " at " in tit:
            parts = [p.strip() for p in tit.split(" at ", 1)]
            if len(parts) == 2:
                return parts[1], parts[0]

        # URL fallback: ATS domain or corporate netloc
        if u:
            try:
                parsed = urlparse(u)
                netloc = parsed.netloc.lower()
                path_parts = [p for p in parsed.path.strip("/").split("/") if p]
                if any(k in netloc for k in ["greenhouse.io", "lever.co", "ashbyhq.com"]) and path_parts:
                    return path_parts[0].replace("-", " ").title(), tit
                domain_parts = netloc.replace("www.", "").replace("careers.", "").replace("jobs.", "").split(".")
                if domain_parts and domain_parts[0]:
                    return domain_parts[0].capitalize(), tit
            except Exception:
                pass

        return comp or "Tech Company", tit

    # Extract and deduplicate discovered job roles
    all_candidate_jobs: List[Dict[str, Any]] = []

    # 1. From verified fetched articles
    for art in agent.fetched_articles:
        if art.get("status") == "fetched":
            u = art.get("url") or art.get("current_url") or ""
            comp, title = _extract_company_and_title(art.get("title") or "Verified Machine Learning Engineer", art.get("company"), u)
            all_candidate_jobs.append({
                "title": title,
                "company": comp,
                "url": u,
                "location": art.get("location") or "Remote / Hybrid",
                "snippet": (art.get("content") or "")[:400],
                "compensation": art.get("compensation") or "Disclosed in application portal"
            })

    # 2. From candidate discovery search hits
    for job in agent.extracted_jobs:
        u = job.get("url") or ""
        comp, title = _extract_company_and_title(job.get("title") or "AI/ML Role", job.get("company"), u)
        all_candidate_jobs.append({
            "title": title,
            "company": comp,
            "url": u,
            "location": job.get("location") or "Remote",
            "snippet": job.get("snippet") or "",
            "compensation": job.get("compensation") or ""
        })

    # Deduplicate candidate openings
    deduplicator = JobDeduplicator(llm_client=agent.llm)
    deduped_jobs = deduplicator.deduplicate_job_list(all_candidate_jobs)

    # Filter to only positions with valid http(s) URLs and non-empty titles
    valid_jobs = [
        j for j in deduped_jobs
        if j.get("url", "").startswith("http") and j.get("title")
    ]

    current_top_k = valid_jobs[:config.K]

    telemetry = {
        "status": result["status"],
        "halt_reason": result["halt_reason"],
        "step_count": result["step_count"],
        "fetch_count": result["fetch_count"],
        "tokens_spent": result["tokens_spent"]
    }

    # Generate Reports
    if run_number == 1:
        report_content = generate_run1_report(
            jobs=current_top_k,
            trace=result["trace"],
            metadata=telemetry
        )
        rep_path, trace_path = save_report_and_trace(
            report_content=report_content,
            trace_data=result["trace"],
            run_number=1,
            reports_dir=reports_dir
        )
        # Save memory state
        memory_manager.save_state(
            run_number=1,
            visited_urls=set(result["visited_urls"]),
            top_k_jobs=current_top_k,
            metadata=telemetry
        )
    else:
        # Run 2: Classify against Run 1 findings
        classified = memory_manager.classify_multi_run_developments(
            previous_top_k=prior_top_k,
            current_top_k=current_top_k
        )
        report_content = generate_run2_report(
            classified=classified,
            trace=result["trace"],
            metadata=telemetry
        )
        rep_path, trace_path = save_report_and_trace(
            report_content=report_content,
            trace_data=result["trace"],
            run_number=run_number,
            reports_dir=reports_dir
        )
        # Save accumulated memory state
        memory_manager.save_state(
            run_number=run_number,
            visited_urls=set(result["visited_urls"]),
            top_k_jobs=current_top_k,
            metadata=telemetry
        )

    # Optional backend database sync if authenticated
    if jwt_token:
        backend_payload = {
            "run_number": run_number,
            "topic": config.topic,
            "target_k": config.K,
            "status": result["status"],
            "step_count": result["step_count"],
            "fetch_count": result["fetch_count"],
            "tokens_spent": result["tokens_spent"],
            "report_path": str(rep_path),
            "trace_path": str(trace_path),
            "jobs": current_top_k,
            "articles": agent.fetched_articles
        }
        sync_run_to_backend(jwt_token, b_url, backend_payload)

    print("\n" + "=" * 60)
    print(f"  TRACKER [RUN {run_number}] EXECUTION FINISHED")
    print("=" * 60)
    print(f"Status:        {result['status'].upper()}")
    print(f"Steps Taken:   {result['step_count']} / {config.limits.max_steps}")
    print(f"Fetches:       {result['fetch_count']} / {config.limits.max_fetches}")
    print(f"Tokens Spent:  {result['tokens_spent']:,} / {config.limits.token_budget:,}")
    print(f"Top K Roles:   {len(current_top_k)}")
    print(f"Report File:   {rep_path}")
    print(f"Trace File:    {trace_path}")
    print("=" * 60 + "\n")

    return {
        "run_number": run_number,
        "status": result["status"],
        "top_k_count": len(current_top_k),
        "report_path": str(rep_path),
        "trace_path": str(trace_path)
    }


def main():
    parser = argparse.ArgumentParser(
        prog="python -m tracker.run",
        description="Autonomous Agentic Tracker for Top 10 newest entry-level and new grad AI/ML roles."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe prior recrawl state and execute as clean Run 1"
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=None,
        help="Override maximum step limit for test runs"
    )
    parser.add_argument(
        "--username",
        type=str,
        default=None,
        help="A1 Platform username for authenticated reporting"
    )
    parser.add_argument(
        "--password",
        type=str,
        default=None,
        help="A1 Platform password"
    )
    parser.add_argument(
        "--backend-url",
        type=str,
        default=None,
        help="A1 Backend API base URL (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--skip-login",
        action="store_true",
        help="Skip backend authentication and execute standalone"
    )

    args = parser.parse_args()
    run_tracker(
        reset=args.reset,
        steps_override=args.steps,
        username=args.username,
        password=args.password,
        backend_url=args.backend_url,
        skip_login=args.skip_login
    )


if __name__ == "__main__":
    main()
