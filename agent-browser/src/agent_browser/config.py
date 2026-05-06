"""Runtime configuration loaded from environment variables and optional .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# python-dotenv is an optional convenience: env vars take precedence
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None  # type: ignore[assignment]


_SECRET_KEYS = frozenset({"openai_api_key"})


def _env_str(key: str, default: str | None = None) -> str | None:
    value = os.environ.get(key)
    if value is None or value == "":
        return default
    return value


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(slots=True)
class AgentBrowserConfig:
    """Runtime configuration for the Browser Agent."""

    model: str = "gpt-4.1-mini"
    platform: str = "android"
    udid: str | None = None
    appium_port: int = 4723
    max_turns: int = 30
    max_retries: int = 2
    step_timeout_seconds: float = 60.0
    artifacts_dir: Path = field(default_factory=lambda: Path("artifacts"))
    memory_path: Path = field(default_factory=lambda: Path(".agent-browser-memory.jsonl"))
    log_level: str = "INFO"
    # Secret. Never include in repr/logs.
    openai_api_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, dotenv_path: Path | str | None = None) -> "AgentBrowserConfig":
        """Load configuration from environment, optionally seeding from a .env file.

        Environment variables always take precedence over values in .env.
        """
        if load_dotenv is not None:
            # override=False ensures real env vars win
            if dotenv_path is not None:
                load_dotenv(dotenv_path=str(dotenv_path), override=False)
            else:
                load_dotenv(override=False)

        artifacts = Path(_env_str("AGENT_BROWSER_ARTIFACTS_DIR", "artifacts") or "artifacts")
        memory = Path(_env_str("AGENT_BROWSER_MEMORY_PATH", ".agent-browser-memory.jsonl") or ".agent-browser-memory.jsonl")

        return cls(
            model=_env_str("AGENT_BROWSER_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini",
            platform=_env_str("AGENT_BROWSER_PLATFORM", "android") or "android",
            udid=_env_str("AGENT_BROWSER_UDID"),
            appium_port=_env_int("AGENT_BROWSER_APPIUM_PORT", 4723),
            max_turns=_env_int("AGENT_BROWSER_MAX_TURNS", 30),
            max_retries=_env_int("AGENT_BROWSER_MAX_RETRIES", 2),
            step_timeout_seconds=_env_float("AGENT_BROWSER_STEP_TIMEOUT", 60.0),
            artifacts_dir=artifacts,
            memory_path=memory,
            log_level=_env_str("AGENT_BROWSER_LOG_LEVEL", "INFO") or "INFO",
            openai_api_key=_env_str("OPENAI_API_KEY"),
        )

    def public_dict(self) -> dict[str, object]:
        """Return config as a dict with secrets redacted (safe to log)."""
        out: dict[str, object] = {}
        for slot in self.__slots__:
            value = getattr(self, slot)
            if slot in _SECRET_KEYS:
                out[slot] = "***" if value else None
            elif isinstance(value, Path):
                out[slot] = str(value)
            else:
                out[slot] = value
        return out
