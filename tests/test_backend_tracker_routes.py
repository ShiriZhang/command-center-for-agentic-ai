"""
Integration Tests for Backend Tracker API Endpoints and Security Policies.
CSCI-GA.2630 Assignment 1B & 2: Agentic Tracker

Covers:
- Rule 2 (RFC 6750): Unauthenticated / bad token requests return 401 Unauthorized.
- Spec 5.8: Public run ingestion via POST /api/tracker/runs is removed (405 Method Not Allowed).
- Rule 3 (Horizontal Authorization): Multi-tenant isolation between distinct users (403 Forbidden).
- Retrieval of orchestrated runs, developments, and article audit logs.
- Asynchronous trigger dispatch (POST /api/tracker/trigger returns 202 Accepted).
- Telemetry aggregation (GET /api/tracker/history).
- Scoped state reset (DELETE /api/tracker/runs).
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

# Add backend directory to path
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token, hash_password
from app.database import Base, get_db
from app.main import app
from app.models import TrackerArticle, TrackerDevelopment, TrackerRun, User


class TestBackendTrackerRoutes(unittest.TestCase):
    """
    Test suite verifying backend tracker endpoints, JWT authentication,
    and Rule 3 horizontal authorization barriers.
    """

    @classmethod
    def setUpClass(cls):
        # Configure isolated in-memory SQLite database with StaticPool for thread-sharing
        cls.test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.TestingSessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=cls.test_engine,
        )

        def override_get_db():
            db = cls.TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def setUp(self):
        # Fresh schema per test method
        Base.metadata.create_all(bind=self.test_engine)

        db = self.TestingSessionLocal()
        # Seed User A
        self.user_a = User(
            username="alice",
            email="alice@example.com",
            hashed_password=hash_password("Password123!"),
        )
        # Seed User B
        self.user_b = User(
            username="bob",
            email="bob@example.com",
            hashed_password=hash_password("Password456!"),
        )
        db.add_all([self.user_a, self.user_b])
        db.commit()
        db.refresh(self.user_a)
        db.refresh(self.user_b)
        db.close()

        # Generate tokens
        token_a = create_access_token({"sub": str(self.user_a.id)})
        token_b = create_access_token({"sub": str(self.user_b.id)})
        self.user_a_headers = {"Authorization": f"Bearer {token_a}"}
        self.user_b_headers = {"Authorization": f"Bearer {token_b}"}

    def tearDown(self):
        Base.metadata.drop_all(bind=self.test_engine)

    def test_unauthenticated_requests_return_401(self):
        """
        Verify Rule 2: All protected tracker endpoints require valid Bearer JWT.
        Missing or forged tokens must return HTTP 401 Unauthorized.
        """
        endpoints = [
            ("GET", "/api/tracker/runs"),
            ("POST", "/api/tracker/trigger"),
            ("GET", "/api/tracker/history"),
            ("GET", "/api/tracker/runs/1"),
            ("DELETE", "/api/tracker/runs"),
        ]

        for method, endpoint in endpoints:
            # 1. No Authorization header
            resp = self.client.request(method, endpoint)
            self.assertEqual(
                resp.status_code,
                401,
                f"{method} {endpoint} without token did not return 401 (got {resp.status_code})",
            )
            self.assertIn("WWW-Authenticate", resp.headers)

            # 2. Forged / Tampered token
            resp_bad = self.client.request(
                method,
                endpoint,
                headers={"Authorization": "Bearer forged.invalid.token"},
            )
            self.assertEqual(
                resp_bad.status_code,
                401,
                f"{method} {endpoint} with invalid token did not return 401 (got {resp_bad.status_code})",
            )

    def test_post_runs_prohibited_405(self):
        """
        Verify Spec 5.8: Public run ingestion via POST /api/tracker/runs is removed (returns 405).
        """
        resp = self.client.post("/api/tracker/runs", json={}, headers=self.user_a_headers)
        self.assertEqual(resp.status_code, 405)

    def test_authenticated_create_and_retrieve_run(self):
        """
        Verify authenticated user can retrieve an orchestrated research run with developments and article logs.
        """
        db = self.TestingSessionLocal()
        run = TrackerRun(
            user_id=self.user_a.id,
            run_number=1,
            topic="Top 10 newest entry-level and new grad AI/ML engineering roles",
            target_k=10,
            status="complete",
            step_count=6,
            fetch_count=4,
            tokens_spent=14200,
            report_path="reports/run1.md",
            trace_path="reports/run1_trace.json",
        )
        db.add(run)
        db.flush()

        dev1 = TrackerDevelopment(
            run_id=run.id,
            rank=1,
            title="Machine Learning Engineer - Early Career",
            company="DeepMind",
            primary_url="https://deepmind.google/careers/mle-entry",
            supporting_sources='["https://aidevboard.com/job/101"]',
            location="New York, NY",
            compensation="$160,000 - $195,000",
            qualifications_summary="Strong proficiency in PyTorch, distributed training, and Transformer architectures.",
            recrawl_status="New since last run",
        )
        art1 = TrackerArticle(
            run_id=run.id,
            url="https://deepmind.google/careers/mle-entry",
            title="DeepMind Careers",
            status="fetched",
            byte_size=45120,
            fetch_time_ms=320,
        )
        art2 = TrackerArticle(
            run_id=run.id,
            url="http://127.0.0.1:8000/admin",
            title=None,
            status="rejected",
            byte_size=0,
            fetch_time_ms=5,
            error_message="127.0.0.1 SSRF loopback rejected",
        )
        db.add_all([dev1, art1, art2])
        db.commit()
        run_id = run.id
        db.close()

        # GET /api/tracker/runs
        get_resp = self.client.get("/api/tracker/runs", headers=self.user_a_headers)
        self.assertEqual(get_resp.status_code, 200)
        runs_list = get_resp.json()
        self.assertEqual(len(runs_list), 1)
        self.assertEqual(runs_list[0]["id"], run_id)

        # GET /api/tracker/runs/:id
        single_resp = self.client.get(f"/api/tracker/runs/{run_id}", headers=self.user_a_headers)
        self.assertEqual(single_resp.status_code, 200)
        data = single_resp.json()
        self.assertEqual(data["id"], run_id)
        self.assertEqual(data["run_number"], 1)
        self.assertEqual(data["user_id"], self.user_a.id)
        self.assertEqual(len(data["developments"]), 1)
        self.assertEqual(len(data["articles"]), 2)

    def test_rule_3_horizontal_authorization_enforced(self):
        """
        Verify Rule 3: Cross-user access violations return HTTP 403 Forbidden.
        User B cannot view User A's runs.
        """
        db = self.TestingSessionLocal()
        run_a = TrackerRun(
            user_id=self.user_a.id,
            run_number=1,
            topic="Private Research Run of User A",
            target_k=5,
            status="complete",
        )
        db.add(run_a)
        db.commit()
        user_a_run_id = run_a.id
        db.close()

        # 1. User B attempts to access User A's run by ID -> 403 Forbidden
        cross_get = self.client.get(
            f"/api/tracker/runs/{user_a_run_id}",
            headers=self.user_b_headers,
        )
        self.assertEqual(cross_get.status_code, 403)
        self.assertIn("Forbidden", cross_get.json()["detail"])

        # 2. User B calling GET /api/tracker/runs sees empty list (User A's run is invisible)
        user_b_runs = self.client.get("/api/tracker/runs", headers=self.user_b_headers).json()
        self.assertEqual(len(user_b_runs), 0)

    def test_tracker_history_aggregation(self):
        """
        Verify GET /api/tracker/history aggregates runs, step counts, fetch counts,
        and token expenditures strictly for the authenticated user.
        """
        db = self.TestingSessionLocal()
        r1 = TrackerRun(
            user_id=self.user_a.id,
            run_number=1,
            topic="Topic A",
            status="complete",
            step_count=8,
            fetch_count=6,
            tokens_spent=20000,
        )
        r2 = TrackerRun(
            user_id=self.user_a.id,
            run_number=2,
            topic="Topic A",
            status="complete",
            step_count=5,
            fetch_count=3,
            tokens_spent=15000,
        )
        db.add_all([r1, r2])
        db.commit()
        db.close()

        # Fetch history summary for User A
        hist_resp = self.client.get("/api/tracker/history", headers=self.user_a_headers)
        self.assertEqual(hist_resp.status_code, 200)
        hist = hist_resp.json()
        self.assertEqual(hist["total_runs"], 2)
        self.assertEqual(hist["last_run_number"], 2)
        self.assertEqual(hist["total_steps"], 13)
        self.assertEqual(hist["total_fetches"], 9)
        self.assertEqual(hist["total_tokens"], 35000)
        self.assertEqual(len(hist["runs"]), 2)

        # User B's history summary should remain 0
        hist_b = self.client.get("/api/tracker/history", headers=self.user_b_headers).json()
        self.assertEqual(hist_b["total_runs"], 0)
        self.assertEqual(hist_b["total_tokens"], 0)

    @patch("app.routes.tracker._run_lifecycle_in_background")
    def test_tracker_trigger_endpoint(self, mock_task):
        """
        Verify POST /api/tracker/trigger returns HTTP 202 Accepted with triggered status
        and assigns appropriate next run number.
        """
        trig1 = self.client.post(
            "/api/tracker/trigger",
            json={"reset": False, "steps_override": 3},
            headers=self.user_a_headers,
        )
        self.assertEqual(trig1.status_code, 202)
        self.assertEqual(trig1.json()["status"], "triggered")
        self.assertEqual(trig1.json()["run_number"], 1)
        mock_task.assert_called_once()

    def test_delete_tracker_runs_scoped_to_user(self):
        """
        Verify DELETE /api/tracker/runs wipes all runs for User A while preserving User B's runs.
        """
        db = self.TestingSessionLocal()
        r_a = TrackerRun(user_id=self.user_a.id, run_number=1, topic="A", status="complete")
        r_b = TrackerRun(user_id=self.user_b.id, run_number=1, topic="B", status="complete")
        db.add_all([r_a, r_b])
        db.commit()
        db.close()

        # User A issues DELETE /api/tracker/runs
        del_resp = self.client.delete("/api/tracker/runs", headers=self.user_a_headers)
        self.assertEqual(del_resp.status_code, 200)
        self.assertIn("Successfully deleted 1 tracker runs", del_resp.json()["message"])

        # User A's runs list should now be empty
        runs_a = self.client.get("/api/tracker/runs", headers=self.user_a_headers).json()
        self.assertEqual(len(runs_a), 0)

        # User B's runs list should still have 1 run
        runs_b = self.client.get("/api/tracker/runs", headers=self.user_b_headers).json()
        self.assertEqual(len(runs_b), 1)


if __name__ == "__main__":
    unittest.main()
