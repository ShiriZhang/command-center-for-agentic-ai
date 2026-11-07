"""
CLI Runner for Agentic Tracker.
Acts as an authenticated backend trigger and poll client.
Supports:
  python -m tracker.run
  python -m tracker.run --reset
  python -m tracker.run --steps 10
  python -m tracker.run --username NYUgrader --password Courant2026!

CSCI-GA.2630 Assignment 2
"""

import argparse
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Union

import httpx

from shared.config import load_orchestration_config
from tracker.config import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tracker.run")


def authenticate_user(
    username: str,
    password: str,
    backend_url: str,
) -> Optional[str]:
    """
    Attempts to authenticate with the backend via POST /api/auth/login.
    Returns JWT Bearer access token if successful, None otherwise.
    """
    login_url = f"{backend_url.rstrip('/')}/api/auth/login"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                login_url,
                json={"username": username, "password": password},
            )
            if resp.status_code == 200:
                data = resp.json()
                token = data.get("access_token")
                logger.info(f"Authenticated successfully with backend as user '{username}'.")
                return token
            logger.warning(
                f"Backend authentication failed (HTTP {resp.status_code}): {resp.text}"
            )
            return None
    except Exception as e:
        logger.error(f"Backend not available at {backend_url} ({e}).")
        return None


def trigger_tracker_run(
    token: str,
    backend_url: str,
    reset: bool = False,
    steps_override: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Triggers an orchestration run on the backend via POST /api/tracker/trigger.
    Returns the accepted response payload containing run_id and run_uuid.
    """
    trigger_url = f"{backend_url.rstrip('/')}/api/tracker/trigger"
    headers = {"Authorization": f"Bearer {token}"}
    payload: Dict[str, Any] = {"reset": reset}
    if steps_override is not None:
        payload["steps_override"] = steps_override

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(trigger_url, json=payload, headers=headers)
        if resp.status_code == 202:
            return resp.json()
        elif resp.status_code == 409:
            raise RuntimeError(
                f"Conflict: An active tracker run is already in progress on the backend. ({resp.text})"
            )
        else:
            raise RuntimeError(
                f"Backend trigger failed (HTTP {resp.status_code}): {resp.text}"
            )


def poll_tracker_run(
    token: str,
    backend_url: str,
    run_id: int,
    poll_interval: float = 2.0,
    max_wait_seconds: float = 900.0,
) -> Dict[str, Any]:
    """
    Polls GET /api/tracker/runs/:id until terminal status ('complete' or 'partial').
    """
    poll_url = f"{backend_url.rstrip('/')}/api/tracker/runs/{run_id}"
    headers = {"Authorization": f"Bearer {token}"}
    start_time = time.monotonic()

    with httpx.Client(timeout=15.0) as client:
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > max_wait_seconds:
                raise TimeoutError(
                    f"Tracker run {run_id} did not finish within {max_wait_seconds}s deadline."
                )

            resp = client.get(poll_url, headers=headers)
            if resp.status_code == 200:
                run_data = resp.json()
                current_status = run_data.get("status")
                if current_status in ("complete", "partial"):
                    return run_data
                logger.info(
                    f"Run {run_id} in progress (status: {current_status}). Waiting {poll_interval}s..."
                )
            elif resp.status_code == 404:
                raise RuntimeError(f"Tracker run {run_id} not found on backend.")
            else:
                logger.warning(
                    f"Warning: Poll received HTTP {resp.status_code}: {resp.text}. Retrying..."
                )

            time.sleep(poll_interval)


def format_and_display_run(run: Dict[str, Any]) -> None:
    """
    Formats and outputs terminal report summary for the run.
    """
    run_num = run.get("run_number", 1)
    status_str = str(run.get("status", "unknown")).upper()
    run_uuid = run.get("run_uuid", "unknown")
    res_status = run.get("researcher_status", "unknown")
    ver_status = run.get("verifier_status", "unknown")
    steps = run.get("step_count", run.get("charged_steps", 0))
    fetches = run.get("fetch_count", run.get("charged_fetches", 0))
    tokens = run.get("tokens_spent", run.get("charged_tokens", 0))
    developments = run.get("developments", [])
    rep_path = run.get("report_path")
    trace_path = run.get("trace_path")

    # Claim breakdown
    supported_cnt = 0
    unsupported_cnt = 0
    unreachable_cnt = 0
    unverified_cnt = 0
    for dev in developments:
        for claim in dev.get("claims", []):
            v = claim.get("verdict", "").lower()
            if v == "supported":
                supported_cnt += 1
            elif v == "unsupported":
                unsupported_cnt += 1
            elif v == "unreachable":
                unreachable_cnt += 1
            elif v == "unverified":
                unverified_cnt += 1

    print("\n" + "=" * 65)
    print(f"  TRACKER [RUN {run_num}] EXECUTION FINISHED")
    print("=" * 65)
    print(f"Status:            {status_str}")
    print(f"Run UUID:          {run_uuid}")
    print(f"Researcher Status: {res_status}")
    print(f"Verifier Status:   {ver_status}")
    if run.get("researcher_error"):
        print(f"Researcher Error:  {run.get('researcher_error')}")
    if run.get("verifier_error"):
        print(f"Verifier Error:    {run.get('verifier_error')}")
    if run.get("stale_source_run_uuid"):
        stale_ts = run.get("stale_source_created_at") or "prior baseline"
        print(f"[STALE ORIGIN]:    Sourced from baseline run {run.get('stale_source_run_uuid')} (created at {stale_ts})")
    print(f"Steps Taken:       {steps}")
    print(f"Fetches:           {fetches}")
    print(f"Tokens Spent:      {tokens:,}")
    print(f"Top K Roles:       {len(developments)}")
    print(f"Claims Breakdown:  {supported_cnt} supported, {unsupported_cnt} unsupported, "
          f"{unreachable_cnt} unreachable, {unverified_cnt} unverified")
    if rep_path:
        print(f"Report File:       {rep_path}")
    if trace_path:
        print(f"Trace File:        {trace_path}")
    print("=" * 65 + "\n")


def run_tracker(
    reset: bool = False,
    steps_override: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    backend_url: Optional[str] = None,
    skip_login: bool = False,
    token: Optional[str] = None,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    """
    Authenticated trigger/poll client lifecycle:
    1. Validates budget limits (--steps cannot increase server budget).
    2. Authenticates with backend (or uses provided token). Outage fails immediately without local model calls.
    3. Triggers Orchestrator via POST /api/tracker/trigger.
    4. Polls GET /api/tracker/runs/:id to completion.
    5. Displays summary and returns run metadata.
    """
    reconf = getattr(sys.stdout, "reconfigure", None)
    if callable(reconf):
        reconf(encoding="utf-8", errors="replace")

    # 1. Budget validation
    if steps_override is not None:
        if steps_override < 2:
            raise ValueError(f"--steps override must be at least 2 (minimum 1 step for researcher and 1 for verifier), got {steps_override}")
        orch_cfg = load_orchestration_config()
        max_allowed_steps = orch_cfg.budgets.total.max_steps
        if steps_override > max_allowed_steps:
            raise ValueError(
                f"--steps override ({steps_override}) cannot exceed total configured allowance ({max_allowed_steps})."
            )

    b_url = (backend_url or config.backend_url or "http://localhost:8000").rstrip("/")

    # 2. Authenticate
    jwt_token = token or os.getenv("TRACKER_TOKEN") or os.getenv("NYUGRADER_TOKEN")
    if not jwt_token:
        user = username or config.tracker_username or os.getenv("TRACKER_USER", "NYUgrader")
        pwd = password or config.tracker_password or os.getenv("TRACKER_PASSWORD", "Courant2026!")
        if not user or not pwd:
            raise RuntimeError(
                "Backend authentication requires username and password. "
                "Standalone local model execution has been removed."
            )
        jwt_token = authenticate_user(user, pwd, b_url)
        if not jwt_token:
            raise RuntimeError(
                f"Backend authentication failed or backend unreachable at {b_url}. "
                "Standalone local model execution has been removed."
            )

    # 3. Trigger run
    logger.info(f"Triggering tracker run on backend at {b_url} (reset={reset})...")
    trigger_resp = trigger_tracker_run(
        token=jwt_token,
        backend_url=b_url,
        reset=reset,
        steps_override=steps_override,
    )
    run_id = int(trigger_resp["run_id"])
    run_uuid = str(trigger_resp.get("run_uuid", ""))
    run_number = int(trigger_resp.get("run_number", 1))
    logger.info(f"Tracker run accepted: run_id={run_id}, run_uuid={run_uuid}, run_number={run_number}")

    # 4. Poll run
    logger.info(f"Polling run {run_id} to completion...")
    run_data = poll_tracker_run(
        token=jwt_token,
        backend_url=b_url,
        run_id=run_id,
        poll_interval=poll_interval,
    )

    # 5. Display terminal summary
    format_and_display_run(run_data)

    return {
        "run_id": run_id,
        "run_uuid": run_uuid,
        "run_number": run_number,
        "status": run_data.get("status", "complete"),
        "top_k_count": len(run_data.get("developments", [])),
        "report_path": run_data.get("report_path"),
        "trace_path": run_data.get("trace_path"),
    }


def main():
    parser = argparse.ArgumentParser(
        prog="python -m tracker.run",
        description="Authenticated Client for Autonomous Agentic Tracker.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Start a fresh scoped comparison lineage on backend without deleting history",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=None,
        help="Override step limit (can only reduce total configured allowance)",
    )
    parser.add_argument(
        "--username",
        type=str,
        default=None,
        help="A1 Platform username for authenticated reporting",
    )
    parser.add_argument(
        "--password",
        type=str,
        default=None,
        help="A1 Platform password",
    )
    parser.add_argument(
        "--backend-url",
        type=str,
        default=None,
        help="A1 Backend API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Direct JWT bearer token for backend authentication",
    )
    parser.add_argument(
        "--skip-login",
        action="store_true",
        help="[Deprecated] Standalone local model execution is removed; flag is ignored or rejected",
    )

    args = parser.parse_args()

    if args.skip_login:
        logger.warning(
            "Flag --skip-login is deprecated. Standalone local model execution is disabled; "
            "all runs are orchestrated through the backend."
        )

    try:
        run_tracker(
            reset=args.reset,
            steps_override=args.steps,
            username=args.username,
            password=args.password,
            backend_url=args.backend_url,
            token=args.token,
        )
    except Exception as e:
        logger.error(f"Tracker execution failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
