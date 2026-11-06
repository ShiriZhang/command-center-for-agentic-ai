"""
Centralized Orchestration Configuration Loader and Models.
Shared across Orchestrator (backend), Researcher, and Verifier services
without cross-service runtime dependencies.
CSCI-GA.2630 Assignment 2
"""

from pathlib import Path
from typing import List, Optional, Set
import yaml
from pydantic import BaseModel, Field, model_validator
from shared.contracts import ResourceBudget

# Locate project root directory
BASE_DIR = Path(__file__).resolve().parent.parent

FORBIDDEN_RETRY_STATUS_CODES: Set[int] = {200, 400, 401, 409, 500}


class ClaimsConfig(BaseModel):
    """Configuration for atomic claims extraction and bounds."""

    max_per_development: int = Field(default=4, ge=1, description="Maximum atomic claims per development")


class BudgetsConfig(BaseModel):
    """Fixed worker shares and total run budget allocations."""

    total: ResourceBudget = Field(
        default_factory=lambda: ResourceBudget(max_steps=30, max_fetches=40, max_tokens=100000)
    )
    researcher: ResourceBudget = Field(
        default_factory=lambda: ResourceBudget(max_steps=18, max_fetches=20, max_tokens=60000)
    )
    verifier: ResourceBudget = Field(
        default_factory=lambda: ResourceBudget(max_steps=12, max_fetches=20, max_tokens=40000)
    )

    @model_validator(mode="after")
    def validate_splits(self) -> "BudgetsConfig":
        if self.researcher.max_steps + self.verifier.max_steps > self.total.max_steps:
            raise ValueError(
                f"Worker step allocations exceed total budget: "
                f"researcher={self.researcher.max_steps} + verifier={self.verifier.max_steps} > total={self.total.max_steps}"
            )
        if self.researcher.max_fetches + self.verifier.max_fetches > self.total.max_fetches:
            raise ValueError(
                f"Worker fetch allocations exceed total budget: "
                f"researcher={self.researcher.max_fetches} + verifier={self.verifier.max_fetches} > total={self.total.max_fetches}"
            )
        if self.researcher.max_tokens + self.verifier.max_tokens > self.total.max_tokens:
            raise ValueError(
                f"Worker token allocations exceed total budget: "
                f"researcher={self.researcher.max_tokens} + verifier={self.verifier.max_tokens} > total={self.total.max_tokens}"
            )
        return self


class DeadlinesConfig(BaseModel):
    """Execution deadlines for workers, HTTP attempts, and overall run."""

    worker_timeout_seconds: int = Field(default=120, gt=0, description="Worker monotonic execution deadline")
    attempt_timeout_seconds: int = Field(default=210, gt=0, description="Per-attempt HTTP wall-clock timeout")
    run_timeout_seconds: int = Field(default=900, gt=0, description="Total run execution deadline")
    finalization_reserve_seconds: int = Field(default=30, ge=0, description="Reserved time for report assembly")

    @model_validator(mode="after")
    def validate_deadlines(self) -> "DeadlinesConfig":
        if self.attempt_timeout_seconds <= self.worker_timeout_seconds:
            raise ValueError(
                f"attempt_timeout_seconds must exceed worker_timeout_seconds to allow network margin and cold starts "
                f"({self.attempt_timeout_seconds} <= {self.worker_timeout_seconds})"
            )
        if self.run_timeout_seconds <= self.attempt_timeout_seconds:
            raise ValueError(
                f"run_timeout_seconds must exceed attempt_timeout_seconds "
                f"({self.run_timeout_seconds} <= {self.attempt_timeout_seconds})"
            )
        if self.finalization_reserve_seconds >= self.run_timeout_seconds:
            raise ValueError(
                f"finalization_reserve_seconds must be less than run_timeout_seconds "
                f"({self.finalization_reserve_seconds} >= {self.run_timeout_seconds})"
            )
        available_dispatch_window = self.run_timeout_seconds - self.finalization_reserve_seconds
        if self.attempt_timeout_seconds > available_dispatch_window:
            raise ValueError(
                f"attempt_timeout_seconds ({self.attempt_timeout_seconds}) cannot exceed available "
                f"dispatch window ({available_dispatch_window}s = run {self.run_timeout_seconds}s - reserve {self.finalization_reserve_seconds}s)"
            )
        return self


class RetriesConfig(BaseModel):
    """Bounded retry parameters and status code filtering."""

    max_attempts: int = Field(default=3, ge=1, description="Total attempts allowed (1 initial + retries)")
    backoff_initial_seconds: float = Field(default=2.0, gt=0.0, description="Initial retry backoff delay")
    backoff_factor: float = Field(default=2.0, ge=1.0, description="Exponential backoff multiplier")
    retryable_status_codes: List[int] = Field(default_factory=lambda: [503])

    @model_validator(mode="after")
    def validate_retryable_codes(self) -> "RetriesConfig":
        for code in self.retryable_status_codes:
            if code in FORBIDDEN_RETRY_STATUS_CODES:
                raise ValueError(
                    f"HTTP status code {code} is terminal and cannot be configured as retryable"
                )
        return self


class OrchestrationConfig(BaseModel):
    """Aggregated orchestration configuration."""

    claims: ClaimsConfig = Field(default_factory=lambda: ClaimsConfig())
    budgets: BudgetsConfig = Field(default_factory=lambda: BudgetsConfig())
    deadlines: DeadlinesConfig = Field(default_factory=lambda: DeadlinesConfig())
    retries: RetriesConfig = Field(default_factory=lambda: RetriesConfig())


def load_orchestration_config(config_yaml_path: Optional[Path] = None) -> OrchestrationConfig:
    """
    Service-local loader for orchestration settings from config.yaml.
    Can be used independently by Orchestrator backend, Researcher, and Verifier.
    """
    target_path = config_yaml_path or (BASE_DIR / "config.yaml")
    if not target_path.exists():
        raise FileNotFoundError(f"Configuration file not found at: {target_path}")

    with open(target_path, "r", encoding="utf-8") as f:
        raw_yaml = yaml.safe_load(f) or {}

    orch_data = raw_yaml.get("orchestration", {})
    return OrchestrationConfig(**orch_data)
