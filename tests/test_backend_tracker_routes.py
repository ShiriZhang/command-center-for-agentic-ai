"""
Integration Tests for Backend Tracker API Endpoints and Security Policies.
CSCI-GA.2630 Assignment 1B: Agentic Foundations

Covers:
- Rule 2 (RFC 6750): Unauthenticated / bad token requests return 401 Unauthorized.
- Rule 3 (Horizontal Authorization): Multi-tenant isolation between distinct users (403 Forbidden).
- CRUD operations for research runs, developments, and article audit logs.
- Asynchronous trigger dispatch (POST /api/tracker/trigger).
- Telemetry aggregation (GET /api/tracker/history).
- Scoped state reset (DELETE /api/tracker/runs).
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


# Add backend directory to path
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models import User, TrackerRun, TrackerArticle, TrackerDevelopment
from app.auth import create_access_token, hash_password


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
            poolclass=StaticPool
        )
        cls.TestingSessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=cls.test_engine
        )
        Base.metadata.create_all(bind=cls.test_engine)

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
        Base.metadata.drop_all(bind=cls.test_engine)

    def setUp(self):
        # Clear database between tests
        db = self.TestingSessionLocal()
        db.query(TrackerDevelopment).delete()
        db.query(TrackerArticle).delete()
        db.query(TrackerRun).delete()
        db.query(User).delete()
        db.commit()

        # Seed User A (NYU Grader)
        self.user_a = User(
            username="nyu_grader",
            email="grader@courant.nyu.edu",
            hashed_password=hash_password("Courant2026!")
        )
        # Seed User B (Competitor Student)
        self.user_b = User(
            username="student_b",
            email="student_b@nyu.edu",
            hashed_password=hash_password("StudentPass123!")
        )
        db.add_all([self.user_a, self.user_b])
        db.commit()
        db.refresh(self.user_a)
        db.refresh(self.user_b)

        self.user_a_token = create_access_token({"sub": str(self.user_a.id)})
        self.user_b_token = create_access_token({"sub": str(self.user_b.id)})

        self.user_a_headers = {"Authorization": f"Bearer {self.user_a_token}"}
        self.user_b_headers = {"Authorization": f"Bearer {self.user_b_token}"}
        db.close()

    def test_unauthenticated_requests_return_401(self):
        """
        Verify Rule 2: All tracker endpoints require valid Bearer JWT.
        Missing or forged tokens must return HTTP 401 Unauthorized.
        """
        endpoints = [
            ("GET", "/api/tracker/runs"),
            ("POST", "/api/tracker/runs"),
            ("POST", "/api/tracker/trigger"),
            ("GET", "/api/tracker/history"),
            ("GET", "/api/tracker/runs/1"),
            ("DELETE", "/api/tracker/runs"),
        ]

        for method, endpoint in endpoints:
            # 1. No Authorization header
            resp = self.client.request(method, endpoint)
            self.assertEqual(
                resp.status_code, 401,
                f"{method} {endpoint} without token did not return 401 (got {resp.status_code})"
            )
            self.assertIn("WWW-Authenticate", resp.headers)

            # 2. Forged / Tampered token
            resp_bad = self.client.request(
                method,
                endpoint,
                headers={"Authorization": "Bearer forged.invalid.token"}
            )
            self.assertEqual(
                resp_bad.status_code, 401,
                f"{method} {endpoint} with invalid token did not return 401 (got {resp_bad.status_code})"
            )

    def test_authenticated_create_and_retrieve_run(self):
        """
        Verify authenticated user can post a research run with jobs and article logs,
        and retrieve it with correct provenance links and telemetry.
        """
        run_payload = {
            "run_number": 1,
            "topic": "Top 10 newest entry-level and new grad AI/ML engineering roles",
            "target_k": 10,
            "status": "complete",
            "step_count": 6,
            "fetch_count": 4,
            "tokens_spent": 14200,
            "report_path": "reports/run1.md",
            "trace_path": "reports/run1_trace.json",
            "jobs": [
                {
                    "rank": 1,
                    "title": "Machine Learning Engineer - Early Career",
                    "company": "DeepMind",
                    "url": "https://deepmind.google/careers/mle-entry",
                    "supporting_sources": ["https://aidevboard.com/job/101"],
                    "location": "New York, NY",
                    "compensation": "$160,000 - $195,000",
                    "snippet": "Strong proficiency in PyTorch, distributed training, and Transformer architectures.",
                    "recrawl_status": "New since last run"
                },
                {
                    "rank": 2,
                    "title": "AI Systems Engineer (New Grad)",
                    "company": "Anthropic",
                    "url": "https://jobs.lever.co/anthropic/ai-systems",
                    "supporting_sources": [],
                    "location": "San Francisco, CA",
                    "compensation": "$175,000 - $210,000",
                    "snippet": "Kernel optimization with Triton, CUDA, and high-performance inference.",
                    "recrawl_status": "New since last run"
                }
            ],
            "articles": [
                {
                    "url": "https://deepmind.google/careers/mle-entry",
                    "title": "DeepMind Careers",
                    "status": "fetched",
                    "byte_size": 45120,
                    "fetch_time_ms": 320,
                    "error_message": None
                },
                {
                    "url": "http://127.0.0.1:8000/admin",
                    "title": None,
                    "status": "rejected",
                    "byte_size": 0,
                    "fetch_time_ms": 1,
                    "error_message": "SSRF Guardrail: Blocked loopback address (127.0.0.1)"
                }
            ]
        }

        # POST /api/tracker/runs
        create_resp = self.client.post(
            "/api/tracker/runs",
            json=run_payload,
            headers=self.user_a_headers
        )
        self.assertEqual(create_resp.status_code, 201)
        data = create_resp.json()
        run_id = data["id"]
        self.assertEqual(data["run_number"], 1)
        self.assertEqual(data["user_id"], self.user_a.id)
        self.assertEqual(len(data["developments"]), 2)
        self.assertEqual(len(data["articles"]), 2)

        # Verify job development fields & aliases
        dev1 = data["developments"][0]
        self.assertEqual(dev1["title"], "Machine Learning Engineer - Early Career")
        self.assertEqual(dev1["company"], "DeepMind")
        self.assertEqual(dev1["primary_url"], "https://deepmind.google/careers/mle-entry")
        self.assertEqual(dev1["supporting_sources"], ["https://aidevboard.com/job/101"])
        self.assertEqual(dev1["recrawl_status"], "New since last run")

        # Verify article audit log
        art2 = data["articles"][1]
        self.assertEqual(art2["status"], "rejected")
        self.assertIn("127.0.0.1", art2["error_message"])

        # GET /api/tracker/runs
        get_resp = self.client.get("/api/tracker/runs", headers=self.user_a_headers)
        self.assertEqual(get_resp.status_code, 200)
        runs_list = get_resp.json()
        self.assertEqual(len(runs_list), 1)
        self.assertEqual(runs_list[0]["id"], run_id)

        # GET /api/tracker/runs/:id
        single_resp = self.client.get(f"/api/tracker/runs/{run_id}", headers=self.user_a_headers)
        self.assertEqual(single_resp.status_code, 200)
        self.assertEqual(single_resp.json()["id"], run_id)

    def test_rule_3_horizontal_authorization_enforced(self):
        """
        Verify Rule 3: Cross-user access violations return HTTP 403 Forbidden.
        User B cannot view User A's runs or create runs on User A's behalf.
        """
        # User A creates a run
        run_payload = {
            "run_number": 1,
            "topic": "Private Research Run of User A",
            "target_k": 5,
            "jobs": [{"title": "Confidential Role", "company": "Secret AI", "url": "https://secret.ai/job"}]
        }
        create_resp = self.client.post("/api/tracker/runs", json=run_payload, headers=self.user_a_headers)
        self.assertEqual(create_resp.status_code, 201)
        user_a_run_id = create_resp.json()["id"]

        # 1. User B attempts to access User A's run by ID -> 403 Forbidden
        cross_get = self.client.get(
            f"/api/tracker/runs/{user_a_run_id}",
            headers=self.user_b_headers
        )
        self.assertEqual(
            cross_get.status_code, 403,
            f"Expected 403 Forbidden when accessing another user's run, got {cross_get.status_code}"
        )
        self.assertIn("Forbidden", cross_get.json()["detail"])

        # 2. User B attempts to forge user_id in POST /api/tracker/runs -> 403 Forbidden
        malicious_create_payload = {
            "user_id": self.user_a.id,  # Spoofed user ID
            "run_number": 2,
            "topic": "Malicious Spoofed Run",
            "target_k": 5
        }
        cross_post = self.client.post(
            "/api/tracker/runs",
            json=malicious_create_payload,
            headers=self.user_b_headers
        )
        self.assertEqual(
            cross_post.status_code, 403,
            f"Expected 403 Forbidden when creating a run for another user, got {cross_post.status_code}"
        )

        # 3. User B calling GET /api/tracker/runs sees empty list (User A's run is invisible)
        user_b_runs = self.client.get("/api/tracker/runs", headers=self.user_b_headers).json()
        self.assertEqual(len(user_b_runs), 0)

    def test_tracker_history_aggregation(self):
        """
        Verify GET /api/tracker/history aggregates runs, step counts, fetch counts,
        and token expenditures strictly for the authenticated user.
        """
        # User A posts Run 1
        self.client.post(
            "/api/tracker/runs",
            json={
                "run_number": 1,
                "topic": "Topic A",
                "status": "complete",
                "step_count": 8,
                "fetch_count": 6,
                "tokens_spent": 20000,
            },
            headers=self.user_a_headers
        )

        # User A posts Run 2
        self.client.post(
            "/api/tracker/runs",
            json={
                "run_number": 2,
                "topic": "Topic A",
                "status": "complete",
                "step_count": 5,
                "fetch_count": 3,
                "tokens_spent": 15000,
            },
            headers=self.user_a_headers
        )

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

    @patch("app.routes.tracker._trigger_tracker_task")
    def test_tracker_trigger_endpoint(self, mock_task):
        """
        Verify POST /api/tracker/trigger returns HTTP 200 with triggered status
        and assigns appropriate next run number.
        """
        # First trigger without prior runs -> run_number = 1
        trig1 = self.client.post(
            "/api/tracker/trigger",
            json={"reset": False, "steps_override": 3},
            headers=self.user_a_headers
        )
        self.assertEqual(trig1.status_code, 200)
        self.assertEqual(trig1.json()["status"], "triggered")
        self.assertEqual(trig1.json()["run_number"], 1)
        mock_task.assert_called_once()

    def test_delete_tracker_runs_scoped_to_user(self):
        """
        Verify DELETE /api/tracker/runs wipes all runs for User A while preserving User B's runs.
        """
        # Seed run for User A and User B
        self.client.post("/api/tracker/runs", json={"run_number": 1, "topic": "A"}, headers=self.user_a_headers)
        self.client.post("/api/tracker/runs", json={"run_number": 1, "topic": "B"}, headers=self.user_b_headers)

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
