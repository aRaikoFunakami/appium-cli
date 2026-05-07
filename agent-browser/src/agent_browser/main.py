"""CLI entry point and run orchestration for agent-browser."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from agent_browser.agent import run_react_loop
from agent_browser.appium_tools import BrowserAgentContext
from agent_browser.config import AgentBrowserConfig
from agent_browser.memory import EpisodicMemory, JsonlMemoryStore, WorkingMemory
from agent_browser.schemas import MemoryEvent, TaskResult
from agent_browser.session import AppiumSessionManager

logger = logging.getLogger(__name__)


def _configure_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
        force=True,
    )


def _build_task_result(goal: str, memory: WorkingMemory) -> TaskResult:
    return TaskResult(
        goal=goal,
        success=False,
        url=memory.current_url,
        summary="Task did not complete.",
        tool_calls=len(memory.tool_calls),
        retries=memory.total_retries(),
        artifacts=list(memory.artifacts),
        failures=list(memory.failures),
    )


async def run_browser_task(
    goal: str,
    config: AgentBrowserConfig | None = None,
) -> TaskResult:
    """Execute a single browser task end-to-end and return a structured result."""
    cfg = config or AgentBrowserConfig.from_env()
    _configure_logging(cfg.log_level)
    cfg.artifacts_dir.mkdir(parents=True, exist_ok=True)

    episodic = EpisodicMemory(JsonlMemoryStore(cfg.memory_path))
    memory = WorkingMemory(goal=goal)
    context = BrowserAgentContext(config=cfg, memory=memory, episodic=episodic)

    logger.info("[run] goal: %s", goal)
    logger.info("[run] config: %s", cfg.public_dict())

    async with AppiumSessionManager(cfg) as session_info:
        logger.info(
            "[run] session ready: udid=%s server=%s started_by_us=%s",
            session_info.udid,
            session_info.server_url,
            session_info.started_by_us,
        )
        try:
            result = await run_react_loop(goal=goal, cfg=cfg, context=context)
        except Exception as exc:
            logger.exception("[run] runner failed")
            memory.record_failure(f"runner_error: {type(exc).__name__}: {exc}")
            episodic.record(
                MemoryEvent(
                    event_type="task_failed",
                    detail=f"runner_error: {type(exc).__name__}: {exc}",
                )
            )
            result = _build_task_result(goal, memory)

    logger.info(
        "[run] done: success=%s tool_calls=%d retries=%d artifacts=%d failures=%d",
        result.success,
        result.tool_calls,
        result.retries,
        len(result.artifacts),
        len(result.failures),
    )
    return result


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-browser",
        description="Single-agent mobile browser automation (Android Chrome).",
    )
    parser.add_argument("goal", help="The natural-language browsing goal to accomplish.")
    parser.add_argument("--model", default=None, help="Override model (default from env).")
    parser.add_argument("--udid", default=None, help="Android device UDID.")
    parser.add_argument("--max-turns", type=int, default=None, help="Override max agent turns.")
    parser.add_argument("--log-level", default=None, help="DEBUG/INFO/WARNING.")
    parser.add_argument("--env-file", default=None, help="Path to a .env file.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print final TaskResult as JSON to stdout.",
    )
    args = parser.parse_args(argv)

    cfg = AgentBrowserConfig.from_env(dotenv_path=args.env_file)
    if args.model:
        cfg.model = args.model
    if args.udid:
        cfg.udid = args.udid
    if args.max_turns is not None:
        cfg.max_turns = args.max_turns
    if args.log_level:
        cfg.log_level = args.log_level

    if not cfg.openai_api_key:
        print(
            "ERROR: OPENAI_API_KEY is not set. Configure it in the environment "
            "or in a .env file.",
            file=sys.stderr,
        )
        return 2

    try:
        result = asyncio.run(run_browser_task(args.goal, cfg))
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        status = "OK" if result.success else "FAIL"
        print(f"[{status}] {result.summary}")
        if result.title:
            print(f"  title: {result.title}")
        if result.url:
            print(f"  url:   {result.url}")
        print(f"  tools={result.tool_calls} retries={result.retries} artifacts={len(result.artifacts)}")
        if result.failures:
            print("  failures:")
            for failure in result.failures[-5:]:
                print(f"    - {failure[:200]}")
    return 0 if result.success else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(cli_main())
