"""
Centralized Configuration Loader and Validator for Tracker
CSCI-GA.2630 Assignment 1B: Agentic Foundations
"""

import os
from pathlib import Path
from typing import List, Optional, Tuple
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

# Locate project root directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from root or backend .env
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / "backend" / ".env")


class ModelFallbackConfig(BaseModel):
    provider: str = "groq"
    name: str = "llama-3.3-70b-versatile"
    base_url: str = "https://api.groq.com/openai/v1"


class ModelConfig(BaseModel):
    provider: str = "openrouter"
    name: str = "meta-llama/llama-3.3-70b-instruct:free"
    base_url: str = "https://openrouter.ai/api/v1"
    temperature: float = 0.1
    fallback: Optional[ModelFallbackConfig] = None


class LimitsConfig(BaseModel):
    max_steps: int = Field(15, gt=0, description="Maximum total agent loop steps")
    max_fetches: int = Field(12, gt=0, description="Maximum web articles fetched")
    token_budget: int = Field(100000, gt=0, description="Cumulative token spend budget")
    timeout_seconds: int = Field(300, gt=0, description="Overall execution timeout")


class NetworkConfig(BaseModel):
    allowed_schemes: List[str] = Field(default_factory=lambda: ["http", "https"])
    allowed_hosts: List[str] = Field(default_factory=lambda: ["*"])
    blocked_ip_ranges: List[str] = Field(default_factory=lambda: [
        "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
        "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10"
    ])
    max_response_bytes: int = Field(1048576, gt=0, description="1MB response limit")
    request_timeout_seconds: int = Field(10, gt=0, description="HTTP socket timeout")


class DeduplicationConfig(BaseModel):
    similarity_threshold: float = Field(0.5, ge=0.0, le=1.0)
    max_disambiguation_calls: int = Field(5, ge=0)


class TrackerConfig(BaseModel):
    topic: str
    K: int = Field(10, ge=3, le=10, description="Ranked developments target count (3 <= K <= 10)")
    model: ModelConfig
    instructions: str
    tools: List[str]
    limits: LimitsConfig
    network: NetworkConfig
    deduplication: DeduplicationConfig

    # Secrets and environment-derived configurations
    openrouter_api_key: Optional[str] = None
    tavily_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    backend_url: str = "http://localhost:8000"
    tracker_username: Optional[str] = None
    tracker_password: Optional[str] = None

    @field_validator("K")
    @classmethod
    def validate_k_bound(cls, v: int) -> int:
        if not (3 <= v <= 10):
            raise ValueError(f"K must be between 3 and 10 as mandated by course spec, got {v}")
        return v

    def get_active_model_credentials(self) -> Tuple[str, str, str]:
        """
        Resolves the active LLM provider credentials.
        Returns: (base_url, api_key, model_name)
        """
        if self.model.provider == "openrouter":
            key = self.openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
            return self.model.base_url, key, self.model.name
        elif self.model.provider == "groq":
            key = self.groq_api_key or os.getenv("GROQ_API_KEY", "")
            return self.model.base_url, key, self.model.name
        else:
            key = os.getenv("LLM_API_KEY", "")
            return self.model.base_url, key, self.model.name

    def validate_required_online_keys(self) -> None:
        """
        Pure Online Mode verification:
        Fails fast if OPENROUTER_API_KEY or TAVILY_API_KEY is missing.
        """
        missing = []
        if self.model.provider == "openrouter" and not (self.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")):
            missing.append("OPENROUTER_API_KEY")
        if not (self.tavily_api_key or os.getenv("TAVILY_API_KEY")):
            missing.append("TAVILY_API_KEY")

        if missing:
            raise ValueError(
                f"[TERMINAL FAILURE] Missing required API keys for online mode: {', '.join(missing)}. "
                "Please configure them in your .env file or environment variables."
            )


def load_tracker_config(config_yaml_path: Optional[Path] = None) -> TrackerConfig:
    """
    Loads and validates the tracker configuration from YAML and environment variables.
    """
    target_path = config_yaml_path or (BASE_DIR / "config.yaml")
    if not target_path.exists():
        raise FileNotFoundError(f"Tracker configuration file not found at: {target_path}")

    with open(target_path, "r", encoding="utf-8") as f:
        raw_yaml = yaml.safe_load(f)

    # Inject environment variables into configuration
    raw_yaml["openrouter_api_key"] = os.getenv("OPENROUTER_API_KEY")
    raw_yaml["tavily_api_key"] = os.getenv("TAVILY_API_KEY")
    raw_yaml["groq_api_key"] = os.getenv("GROQ_API_KEY")
    raw_yaml["backend_url"] = os.getenv("BACKEND_URL", "http://localhost:8000")
    raw_yaml["tracker_username"] = os.getenv("TRACKER_USER", "NYUgrader")
    raw_yaml["tracker_password"] = os.getenv("TRACKER_PASSWORD", "Courant2026!")

    return TrackerConfig(**raw_yaml)


# Global singleton instance loaded on import
config = load_tracker_config()
