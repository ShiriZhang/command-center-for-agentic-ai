"""
Tests for Task 4.1: Verifier Idempotency and In-Flight Request Locking.
CSCI-GA.2630 Assignment 2
"""

from uuid import uuid4
import pytest
from services.verifier.idempotency import (
    IdempotencyRegistry,
    canonical_request_hash,
)


def test_canonical_request_hash_ignores_key_order():
    """Canonical request hash must ignore dictionary key ordering and whitespace differences."""
    d1 = {"run_id": "r1", "request_id": "req1", "payload": {"topic": "AI", "k": 5}}
    d2 = {"payload": {"k": 5, "topic": "AI"}, "request_id": "req1", "run_id": "r1"}
    assert canonical_request_hash(d1) == canonical_request_hash(d2)


def test_registry_new_request_registered():
    """First presentation of request_id registers it as in-flight and returns 'new'."""
    registry = IdempotencyRegistry()
    action, record = registry.check_or_register("req-123", "hash-abc")
    assert action == "new"
    assert record is None


def test_registry_in_flight_duplicate_returns_in_flight():
    """Identical request arriving while the original is still in-flight returns 'in_flight'."""
    registry = IdempotencyRegistry()
    registry.check_or_register("req-123", "hash-abc")
    action, record = registry.check_or_register("req-123", "hash-abc")
    assert action == "in_flight"
    assert record is not None
    assert record.state == "in_flight"


def test_registry_altered_body_returns_conflict():
    """Reusing the same request_id with an altered body returns 'conflict' (HTTP 409)."""
    registry = IdempotencyRegistry()
    registry.check_or_register("req-123", "hash-abc")
    action, record = registry.check_or_register("req-123", "hash-different")
    assert action == "conflict"
    assert record is not None


def test_registry_completed_request_replays_response():
    """Identical request arriving after completion returns 'completed' with stored response."""
    registry = IdempotencyRegistry()
    registry.check_or_register("req-123", "hash-abc")
    registry.complete("req-123", status_code=200, response_body=b'{"status":"complete"}')

    action, record = registry.check_or_register("req-123", "hash-abc")
    assert action == "completed"
    assert record is not None
    assert record.status_code == 200
    assert record.response_body == b'{"status":"complete"}'


def test_registry_fail_clears_in_flight_so_retry_can_proceed():
    """Transient failures marked via fail() remove the in-flight lock to permit retries."""
    registry = IdempotencyRegistry()
    registry.check_or_register("req-123", "hash-abc")
    registry.fail("req-123")

    action, record = registry.check_or_register("req-123", "hash-abc")
    assert action == "new"
    assert record is None
