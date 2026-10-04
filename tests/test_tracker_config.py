"""
Unit Test Suite for Task 1.2: tracker/config.py validation and environment loading.
Built using standard library unittest to guarantee zero external test framework dependency.
"""

import os
import sys
import unittest
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tracker.config import load_tracker_config, TrackerConfig


class TestTrackerConfig(unittest.TestCase):

    def test_load_default_config(self):
        """Verify that default config.yaml loads into a valid TrackerConfig instance."""
        cfg = load_tracker_config()
        self.assertIsInstance(cfg, TrackerConfig)
        self.assertEqual(cfg.K, 10)
        self.assertEqual(cfg.model.provider == "openrouter" or cfg.model.provider == "groq", True)
        self.assertIn("http", cfg.network.allowed_schemes)
        self.assertIn("https", cfg.network.allowed_schemes)
        self.assertEqual(cfg.limits.max_steps, 15)
        self.assertEqual(cfg.limits.max_fetches, 12)
        self.assertEqual(cfg.limits.token_budget, 100000)

    def test_k_bounds_validation(self):
        """Verify that K must strictly satisfy 3 <= K <= 10."""
        cfg = load_tracker_config()
        data = cfg.model_dump()

        # K < 3 must fail validation
        data["K"] = 2
        with self.assertRaises(Exception):
            TrackerConfig(**data)

        # K > 10 must fail validation
        data["K"] = 11
        with self.assertRaises(Exception):
            TrackerConfig(**data)

    def test_active_model_credentials(self):
        """Verify that model credentials resolve properly based on provider."""
        cfg = load_tracker_config()
        base_url, key, model_name = cfg.get_active_model_credentials()
        self.assertTrue(base_url.startswith("https://"))
        self.assertTrue(len(model_name) > 0)

    def test_missing_online_keys_validation(self):
        """Verify that validate_required_online_keys() fails fast when keys are absent."""
        cfg = load_tracker_config()
        # Ensure keys are absent for test
        cfg.openrouter_api_key = None
        cfg.tavily_api_key = None
        old_openrouter = os.environ.pop("OPENROUTER_API_KEY", None)
        old_tavily = os.environ.pop("TAVILY_API_KEY", None)

        try:
            with self.assertRaises(ValueError) as ctx:
                cfg.validate_required_online_keys()
            self.assertIn("TERMINAL FAILURE", str(ctx.exception))
            self.assertIn("TAVILY_API_KEY", str(ctx.exception))
        finally:
            if old_openrouter:
                os.environ["OPENROUTER_API_KEY"] = old_openrouter
            if old_tavily:
                os.environ["TAVILY_API_KEY"] = old_tavily


if __name__ == "__main__":
    unittest.main()
