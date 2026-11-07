"""
Tests for Tracker CLI Client (tracker.run).
Verifies that tracker.run acts as an authenticated trigger/poll client
to the backend, does not execute local model calls or episodic persistence,
enforces budget constraints on --steps, and supports --reset without deleting history.
CSCI-GA.2630 Assignment 2
"""

import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from tracker.run import authenticate_user, run_tracker


class TestTrackerCLIClient(unittest.TestCase):
    """Unit tests for tracker.run authenticated client."""

    @patch("httpx.Client.post")
    def test_authenticate_user_success(self, mock_post):
        """Valid credentials return the JWT access token."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "valid-jwt-token"}
        mock_post.return_value = mock_resp

        token = authenticate_user("NYUgrader", "Courant2026!", "http://localhost:8000")
        self.assertEqual(token, "valid-jwt-token")

    @patch("httpx.Client.post")
    def test_authenticate_user_failure(self, mock_post):
        """Invalid credentials return None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_post.return_value = mock_resp

        token = authenticate_user("wrong", "pwd", "http://localhost:8000")
        self.assertIsNone(token)

    @patch("tracker.run.authenticate_user", return_value=None)
    def test_backend_outage_fails_without_local_model_calls(self, mock_auth):
        """
        When backend authentication fails or backend is unreachable,
        the CLI must fail with an error and perform NO local model calls
        and NOT touch reports/tracker_state.json.
        """
        state_file = Path("reports/tracker_state.json")
        mtime_before = state_file.stat().st_mtime if state_file.exists() else None

        with patch("tracker.agent.ResearchAgent") as mock_agent:
            with self.assertRaises((RuntimeError, SystemExit, ConnectionError)):
                run_tracker(
                    username="NYUgrader",
                    password="wrong",
                    backend_url="http://localhost:8000",
                )
            mock_agent.assert_not_called()

        if state_file.exists() and mtime_before is not None:
            self.assertEqual(state_file.stat().st_mtime, mtime_before)

    def test_steps_override_cannot_increase_configured_budget(self):
        """
        CLI must reject a --steps override that exceeds the total configured allowance.
        """
        # If total budget is 30, requesting 100 must be rejected before any execution
        with self.assertRaises((ValueError, SystemExit)):
            run_tracker(
                steps_override=9999,
                token="mock-token",
                backend_url="http://localhost:8000",
            )

    def test_steps_override_cannot_be_less_than_two(self):
        """
        CLI must reject a --steps override less than 2 because researcher and verifier
        each require at least 1 step in an explicit split.
        """
        with self.assertRaises((ValueError, SystemExit)):
            run_tracker(
                steps_override=1,
                token="mock-token",
                backend_url="http://localhost:8000",
            )

    @patch("httpx.Client")
    def test_trigger_and_poll_to_completion(self, mock_client_cls):
        """
        CLI triggers backend via POST /api/tracker/trigger and polls
        GET /api/tracker/runs/{run_id} until terminal status.
        """
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        # POST /api/tracker/trigger returns 202 Accepted
        trigger_resp = MagicMock()
        trigger_resp.status_code = 202
        trigger_resp.json.return_value = {
            "status": "triggered",
            "message": "Tracker run 1 queued successfully",
            "run_number": 1,
            "run_id": 42,
            "run_uuid": "11111111-1111-1111-1111-111111111111",
        }

        # First poll: status="running", Second poll: status="complete"
        poll_running = MagicMock()
        poll_running.status_code = 200
        poll_running.json.return_value = {
            "id": 42,
            "run_uuid": "11111111-1111-1111-1111-111111111111",
            "run_number": 1,
            "status": "running",
            "topic": "Test topic",
            "target_k": 10,
            "researcher_status": "complete",
            "verifier_status": "running",
            "step_count": 5,
            "fetch_count": 8,
            "tokens_spent": 12000,
            "developments": [],
            "articles": [],
        }

        poll_complete = MagicMock()
        poll_complete.status_code = 200
        poll_complete.json.return_value = {
            "id": 42,
            "run_uuid": "11111111-1111-1111-1111-111111111111",
            "run_number": 1,
            "status": "complete",
            "topic": "Test topic",
            "target_k": 10,
            "researcher_status": "complete",
            "verifier_status": "complete",
            "step_count": 10,
            "fetch_count": 15,
            "tokens_spent": 25000,
            "report_path": "reports/run_1_report.md",
            "trace_path": "reports/trace_11111111-1111-1111-1111-111111111111.jsonl",
            "developments": [
                {
                    "id": 1,
                    "rank": 1,
                    "title": "AI Engineer",
                    "company": "Tech Corp",
                    "primary_url": "https://example.com/job1",
                    "claims": [
                        {
                            "claim_id": "c1",
                            "text": "Salary $150k",
                            "source_url": "https://example.com/job1",
                            "verdict": "supported",
                            "evidence": "salary is $150k",
                        }
                    ],
                }
            ],
            "articles": [],
        }

        mock_client.post.return_value = trigger_resp
        mock_client.get.side_effect = [poll_running, poll_complete]

        result = run_tracker(
            token="mock-jwt-token",
            backend_url="http://localhost:8000",
            poll_interval=0.01,
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["run_id"], 42)
        self.assertEqual(result["run_number"], 1)
        self.assertEqual(result["top_k_count"], 1)
        # Verify trigger payload had expected structure
        mock_client.post.assert_called_once()
        trigger_call_url = mock_client.post.call_args[0][0]
        self.assertIn("/api/tracker/trigger", trigger_call_url)

    @patch("httpx.Client")
    def test_reset_starts_new_lineage_without_deleting_history(self, mock_client_cls):
        """
        --reset calls reset endpoint or sends reset=True to trigger,
        and does NOT call DELETE /api/tracker/runs.
        """
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        trigger_resp = MagicMock()
        trigger_resp.status_code = 202
        trigger_resp.json.return_value = {
            "status": "triggered",
            "message": "Reset run queued",
            "run_number": 2,
            "run_id": 99,
            "run_uuid": "22222222-2222-2222-2222-222222222222",
        }

        poll_complete = MagicMock()
        poll_complete.status_code = 200
        poll_complete.json.return_value = {
            "id": 99,
            "run_uuid": "22222222-2222-2222-2222-222222222222",
            "run_number": 2,
            "status": "complete",
            "step_count": 8,
            "fetch_count": 10,
            "tokens_spent": 15000,
            "developments": [],
            "articles": [],
        }

        mock_client.post.return_value = trigger_resp
        mock_client.get.return_value = poll_complete

        result = run_tracker(
            reset=True,
            token="mock-jwt-token",
            backend_url="http://localhost:8000",
            poll_interval=0.01,
        )

        self.assertEqual(result["status"], "complete")
        # Ensure DELETE was never invoked
        mock_client.delete.assert_not_called()
        # Ensure trigger payload contained reset=True
        post_kwargs = mock_client.post.call_args[1]
        self.assertTrue(post_kwargs.get("json", {}).get("reset"))

    @patch("httpx.Client")
    def test_trigger_409_active_run_handling(self, mock_client_cls):
        """
        When backend returns HTTP 409 Conflict, CLI handles it gracefully
        and reports the active run.
        """
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        conflict_resp = MagicMock()
        conflict_resp.status_code = 409
        conflict_resp.text = "Conflict: Active run already running"
        conflict_resp.json.return_value = {"detail": "Conflict: Active run already running"}
        mock_client.post.return_value = conflict_resp

        with self.assertRaises(RuntimeError) as ctx:
            run_tracker(
                token="mock-jwt-token",
                backend_url="http://localhost:8000",
            )
        self.assertIn("Conflict", str(ctx.exception))
