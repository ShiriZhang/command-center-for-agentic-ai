"""
Correlated structured JSONL telemetry logger for Orchestrator service.
Strictly adheres to the 11-field OpenSpec cross-service schema.
CSCI-GA.2630 Assignment 2
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class TelemetryRecord(BaseModel):
    """
    Structured trace record adhering strictly to the 11-field OpenSpec schema:
    ts, service, run_id, request_id, step, direction, endpoint_or_tool, status, latency_ms, attempt, tokens.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    ts: str = Field(description="ISO 8601 UTC timestamp")
    service: str = Field(description="Originating service identifier (orchestrator)")
    run_id: Optional[str] = Field(default=None, description="Correlated run UUID or None")
    request_id: Optional[str] = Field(default=None, description="Correlated request UUID or None")
    step: int = Field(ge=0, description="Step index within the orchestration run")
    direction: Literal["inbound", "outbound"] = Field(description="Trace traffic direction")
    endpoint_or_tool: str = Field(description="Endpoint or worker target")
    status: str = Field(description="Operation outcome status or HTTP code")
    latency_ms: float = Field(ge=0.0, description="Locally measured caller latency in ms")
    attempt: int = Field(ge=1, description="1-indexed attempt number")
    tokens: int = Field(ge=0, default=0, description="Tokens consumed if model call, else 0")


class TelemetryLogger:
    """Thread-safe JSON Lines structured logger ensuring 11-field schema compliance."""

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path
        self._lock = threading.Lock()
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_event(
        self,
        service: str = "orchestrator",
        run_id: Optional[str] = None,
        request_id: Optional[str] = None,
        step: int = 0,
        direction: Literal["inbound", "outbound"] = "outbound",
        endpoint_or_tool: str = "unknown",
        status: str = "ok",
        latency_ms: float = 0.0,
        attempt: int = 1,
        tokens: int = 0,
        ts: Optional[str] = None,
        **extra_metadata: Any,
    ) -> TelemetryRecord:
        """
        Emits a structured JSONL record adhering strictly to the 11-field schema.
        Any extra parameters (such as tokens, prompts, credentials) are stripped and omitted.
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

    def export_run_traces(self, run_id: str, dest_path: Path) -> Path:
        """Copies all trace records matching run_id into a run-specific JSONL file."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if self.log_path and self.log_path.exists():
            with self._lock:
                with open(self.log_path, "r", encoding="utf-8") as src, open(dest_path, "w", encoding="utf-8") as dst:
                    for line in src:
                        try:
                            data = json.loads(line)
                            if data.get("run_id") == run_id:
                                dst.write(line)
                        except Exception:
                            pass
        return dest_path


default_orchestrator_logger = TelemetryLogger(Path("reports/orchestrator.jsonl"))
