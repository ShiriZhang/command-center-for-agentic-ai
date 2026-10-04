"""
Unit Tests for Backend SQLAlchemy Models.
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import sys
import unittest
from pathlib import Path

# Add backend directory to path
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import inspect
from app.database import engine, Base
from app.models import User, TrackerRun, TrackerArticle, TrackerDevelopment


class TestBackendModels(unittest.TestCase):
    """
    Verifies that Tracker models are properly defined, mapped to Base metadata,
    and have correct schema definitions and cascading relationships.
    """

    def test_tables_registered_in_metadata(self):
        """
        Verify that tracker_runs, tracker_articles, and tracker_developments
        are registered in SQLAlchemy Base.metadata.
        """
        table_names = Base.metadata.tables.keys()
        self.assertIn("users", table_names)
        self.assertIn("tracker_runs", table_names)
        self.assertIn("tracker_articles", table_names)
        self.assertIn("tracker_developments", table_names)

    def test_tracker_run_foreign_key_and_cascade(self):
        """
        Verify that tracker_runs has a foreign key to users.id with CASCADE deletion.
        """
        table = Base.metadata.tables["tracker_runs"]
        fks = list(table.foreign_keys)
        self.assertEqual(len(fks), 1)
        fk = fks[0]
        self.assertEqual(fk.target_fullname, "users.id")
        self.assertEqual(fk.ondelete, "CASCADE")

    def test_tracker_article_foreign_key(self):
        """
        Verify that tracker_articles has a foreign key to tracker_runs.id with CASCADE deletion.
        """
        table = Base.metadata.tables["tracker_articles"]
        fks = list(table.foreign_keys)
        self.assertEqual(len(fks), 1)
        fk = fks[0]
        self.assertEqual(fk.target_fullname, "tracker_runs.id")
        self.assertEqual(fk.ondelete, "CASCADE")

    def test_tracker_development_foreign_key(self):
        """
        Verify that tracker_developments has a foreign key to tracker_runs.id with CASCADE deletion.
        """
        table = Base.metadata.tables["tracker_developments"]
        fks = list(table.foreign_keys)
        self.assertEqual(len(fks), 1)
        fk = fks[0]
        self.assertEqual(fk.target_fullname, "tracker_runs.id")
        self.assertEqual(fk.ondelete, "CASCADE")

    def test_model_instantiation(self):
        """
        Verify that models can be instantiated with required attributes.
        """
        user = User(username="test_user", email="test@test.com", hashed_password="hashed_pwd")
        run = TrackerRun(
            user=user,
            run_number=1,
            topic="Top 10 AI Roles",
            target_k=10,
            status="complete",
            step_count=5,
            fetch_count=3,
            tokens_spent=1500
        )
        article = TrackerArticle(
            run=run,
            url="https://boards.greenhouse.io/corp/1",
            title="ML Engineer",
            status="fetched",
            byte_size=1024,
            fetch_time_ms=120
        )
        dev = TrackerDevelopment(
            run=run,
            fingerprint="corp:ml engineer",
            rank=1,
            title="ML Engineer",
            company="Corp",
            primary_url="https://boards.greenhouse.io/corp/1",
            recrawl_status="New since last run"
        )

        self.assertEqual(run.user.username, "test_user")
        self.assertEqual(len(run.articles), 1)
        self.assertEqual(len(run.developments), 1)
        self.assertEqual(run.articles[0].status, "fetched")
        self.assertEqual(run.developments[0].recrawl_status, "New since last run")


if __name__ == "__main__":
    unittest.main()
