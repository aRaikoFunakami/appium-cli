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


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    return raw.lower() in ("1", "true", "yes")


@dataclass(slots=True)
class AgentBrowserConfig:
    """Runtime configuration for the Browser Agent."""

    model: str = "gpt-4.1-mini"
    platform: str = "android"
    udid: str | None = None
    appium_port: int = 4723
    max_turns: int = 50
    max_retries: int = 2
    step_timeout_seconds: float = 60.0
    recent_steps: int = 5
    max_observation_chars: int = 4000
    max_action_result_chars: int = 500
    max_error_chars: int = 300
    working_state_char_cap: int = 2400
    max_output_tokens: int = 4096
    temperature: float = 0.2
    reasoning_effort: str | None = None
    artifacts_dir: Path = field(default_factory=lambda: Path("artifacts"))
    memory_path: Path = field(default_factory=lambda: Path(".agent-browser-memory.jsonl"))
    log_level: str = "INFO"
    # --- Completion verification ---
    max_verification_retries: int = 2
    max_wall_seconds: float = 300.0
    max_no_progress_steps: int = 8
    verify_with_llm: bool = True
    min_result_chars: int = 50
    judge_model: str = "gpt-4.1-mini"
    judge_fail_open: bool = True
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
            max_turns=_env_int("AGENT_BROWSER_MAX_TURNS", 50),
            max_retries=_env_int("AGENT_BROWSER_MAX_RETRIES", 2),
            step_timeout_seconds=_env_float("AGENT_BROWSER_STEP_TIMEOUT", 60.0),
            recent_steps=_env_int("AGENT_BROWSER_RECENT_STEPS", 5),
            max_observation_chars=_env_int("AGENT_BROWSER_MAX_OBSERVATION_CHARS", 4000),
            max_action_result_chars=_env_int("AGENT_BROWSER_MAX_ACTION_RESULT_CHARS", 500),
            max_error_chars=_env_int("AGENT_BROWSER_MAX_ERROR_CHARS", 300),
            working_state_char_cap=_env_int("AGENT_BROWSER_WORKING_STATE_CHARS", 2400),
            max_output_tokens=_env_int("AGENT_BROWSER_MAX_OUTPUT_TOKENS", 4096),
            temperature=_env_float("AGENT_BROWSER_TEMPERATURE", 0.2),
            reasoning_effort=_env_str("AGENT_BROWSER_REASONING_EFFORT"),
            artifacts_dir=artifacts,
            memory_path=memory,
            log_level=_env_str("AGENT_BROWSER_LOG_LEVEL", "INFO") or "INFO",
            max_verification_retries=_env_int("AGENT_BROWSER_MAX_VERIFICATION_RETRIES", 2),
            max_wall_seconds=_env_float("AGENT_BROWSER_MAX_WALL_SECONDS", 300.0),
            max_no_progress_steps=_env_int("AGENT_BROWSER_MAX_NO_PROGRESS_STEPS", 8),
            verify_with_llm=_env_bool("AGENT_BROWSER_VERIFY_WITH_LLM", True),
            min_result_chars=_env_int("AGENT_BROWSER_MIN_RESULT_CHARS", 50),
            judge_model=_env_str("AGENT_BROWSER_JUDGE_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini",
            judge_fail_open=_env_bool("AGENT_BROWSER_JUDGE_FAIL_OPEN", True),
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
