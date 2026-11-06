"""
Correlated structured JSONL telemetry logger for Verifier service.
CSCI-GA.2630 Assignment 2
"""

import os
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class TelemetryRecord(BaseModel):
    """
    Structured trace record adhering to the 11-field OpenSpec schema:
    ts, service, run_id, request_id, step, direction, endpoint_or_tool, status, latency_ms, attempt, tokens.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    ts: str = Field(description="ISO 8601 UTC timestamp")
    service: str = Field(description="Originating service identifier (verifier)")
    run_id: Optional[str] = Field(default=None, description="Correlated run UUID or None")
    request_id: Optional[str] = Field(default=None, description="Correlated request UUID or None")
    step: int = Field(ge=0, description="Step index within the verification execution")
    direction: Literal["inbound", "outbound"] = Field(description="Trace traffic direction")
    endpoint_or_tool: str = Field(description="Endpoint name, model identifier, or tool name")
    status: str = Field(description="Operation outcome status")
    latency_ms: float = Field(ge=0.0, description="Locally measured caller latency in ms")
    attempt: int = Field(ge=1, description="1-indexed attempt number")
    tokens: int = Field(ge=0, default=0, description="Tokens consumed if model call, else 0")


class TelemetryLogger:
    """Thread-safe JSON Lines structured logger ensuring schema compliance."""

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path
        self._lock = threading.Lock()
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_event(
        self,
        service: str,
        run_id: Optional[str],
        request_id: Optional[str],
        step: int,
        direction: Literal["inbound", "outbound"],
        endpoint_or_tool: str,
        status: str,
        latency_ms: float,
        attempt: int = 1,
        tokens: int = 0,
        ts: Optional[str] = None,
        **extra_metadata: Any,
    ) -> TelemetryRecord:
        """
        Emits a structured JSONL record adhering strictly to the 11-field schema.
        Any extra parameters (such as raw prompts or credentials) are stripped and omitted.
        """
        timestamp = ts or datetime.now(timezone.utc).isoformat()

        record = TelemetryRecord(
            ts=timestamp,
            service=service,
            run_id=run_id,
            request_id=request_id,
            step=step,
            direction=direction,
            endpoint_or_tool=endpoint_or_tool,
            status=status,
            latency_ms=round(float(latency_ms), 2),
            attempt=attempt,
            tokens=tokens,
        )

        if self.log_path:
            line = record.model_dump_json() + "\n"
            with self._lock:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(line)

        return record


def get_verifier_log_path() -> Path:
    """Returns the configured log path for Verifier, supporting run-scoped directories."""
    env_path = os.environ.get("VERIFIER_LOG_PATH")
    if env_path:
        return Path(env_path)
    return Path("reports/verifier.jsonl")


# Global default logger instance
default_verifier_logger = TelemetryLogger(get_verifier_log_path())
