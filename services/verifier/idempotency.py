"""
In-memory process-local idempotency registry and canonical request hashing for Verifier.
CSCI-GA.2630 Assignment 2
"""

import hashlib
import json
import threading
from typing import Any, Dict, Literal, Optional, Tuple


def canonical_request_hash(data: Any) -> str:
    """
    Computes a deterministic SHA-256 hash of a JSON-serializable structure,
    ignoring key order and redundant whitespace.
    """
    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class IdempotencyRecord:
    """Stores the execution state and cached terminal response of a request."""

    def __init__(self, request_id: str, canonical_hash: str, state: str = "in_flight"):
        self.request_id = request_id
        self.canonical_hash = canonical_hash
        self.state = state  # "in_flight" or "completed"
        self.status_code: int = 200
        self.response_body: bytes = b""
        self.headers: Dict[str, str] = {}


class IdempotencyRegistry:
    """Thread-safe in-memory registry for process-lifetime request deduplication and response replay."""

    def __init__(self):
        self._lock = threading.Lock()
        self._records: Dict[str, IdempotencyRecord] = {}

    def check_or_register(
        self, request_id: str, canonical_hash: str
    ) -> Tuple[Literal["new", "in_flight", "completed", "conflict"], Optional[IdempotencyRecord]]:
        """
        Atomically inspects and registers the given request.
        - If request_id unknown: registers as in-flight and returns ("new", None).
        - If request_id known with DIFFERENT hash: returns ("conflict", record) -> HTTP 409.
        - If request_id in-flight with SAME hash: returns ("in_flight", record) -> HTTP 503 + Retry-After.
        - If request_id completed with SAME hash: returns ("completed", record) -> replay terminal response.
        """
        with self._lock:
            existing = self._records.get(request_id)
            if existing is None:
                new_record = IdempotencyRecord(request_id, canonical_hash, state="in_flight")
                self._records[request_id] = new_record
                return ("new", None)

            if existing.canonical_hash != canonical_hash:
                return ("conflict", existing)

            if existing.state == "in_flight":
                return ("in_flight", existing)

            return ("completed", existing)

    def complete(
        self,
        request_id: str,
        status_code: int,
        response_body: bytes,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Marks the request completed and caches its terminal response."""
        with self._lock:
            record = self._records.get(request_id)
            if record is not None:
                record.state = "completed"
                record.status_code = status_code
                record.response_body = response_body
                record.headers = headers or {}

    def fail(self, request_id: str) -> None:
        """Removes an abandoned or transiently failed in-flight request to permit subsequent retries."""
        with self._lock:
            self._records.pop(request_id, None)

    def clear(self) -> None:
        """Clears all records (useful for test isolation)."""
        with self._lock:
            self._records.clear()
