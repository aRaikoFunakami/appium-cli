"""Structured controller loop for agent-browser."""

from __future__ import annotations

import logging

from agent_browser.appium_tools import BrowserAgentContext
from agent_browser.config import AgentBrowserConfig
from agent_browser.controller.executor import ActionOutcome, Executor
from agent_browser.controller.planner import PlannedAction, Planner
from agent_browser.controller.policy import PolicyEngine
from agent_browser.controller.recovery import RecoveryManager
from agent_browser.controller.task_compiler import TaskCompiler
from agent_browser.controller.task_plan import StepKind
from agent_browser.controller.verification import infer_content_identity, verify_success_criteria
from agent_browser.schemas import TaskResult
from agent_browser.token_counter import UsageTracker
from agent_browser.world.model import WorldModel

logger = logging.getLogger(__name__)


async def run_structured_controller(
    goal: str,
    cfg: AgentBrowserConfig,
    context: BrowserAgentContext,
    usage_tracker: UsageTracker | None = None,
) -> TaskResult:
    """Run a task through the structured controller."""
    tracker = usage_tracker or UsageTracker(primary_model=cfg.model)
    plan = TaskCompiler().compile(goal)
    world = WorldModel()
    executor = Executor(context=context, world=world)
    planner = Planner(
        main_content_bias=cfg.scroll_main_content_bias,
        header_penalty=cfg.scroll_header_penalty,
    )
    policy = PolicyEngine(plan=plan, strict_step_order=cfg.step_block_strict)
    recovery = RecoveryManager(plan=plan)

    logger.info("[structured] compiled plan: steps=%d criteria=%d", len(plan.steps), len(plan.success_criteria))

    while not plan.finished() and not plan.failed():
        step = plan.next_ready_step()
        if step is None:
            break
        plan.mark_running(step.id)

        action = await _plan_action(step, planner, executor, world)
        policy.current_refs = set(world.current().refs) if world.current() else set()
        decision = policy.allow(step, action.tool, action.args)
        if not decision.allowed:
            plan.mark_failed(step.id, decision.reason or "policy blocked action")
            break

        if action.expected_effect == "favorite_toggled" and world.current() is not None:
            content_text = infer_content_identity(plan, world.current(), str(action.args.get("ref", "")))
            if content_text:
                step.evidence.append(f"content_text:{content_text}")

        outcome = await executor.execute(action)
        if not outcome.ok:
            recovery_action = recovery.recover(step, outcome)
            if recovery_action is not None:
                logger.info("[structured] recovery %s for %s", recovery_action.reason, step.id)
                outcome = await executor.execute(recovery_action.action)

        if outcome.ok:
            plan.mark_done(step.id, evidence=outcome.diff_summary or outcome.raw_text)
        else:
            plan.mark_failed(step.id, outcome.error or "action failed")

    final_verification = verify_success_criteria(plan, world)
    if plan.finished() and not final_verification.passed:
        logger.info("[structured] final verification failed: %s", final_verification.reason)
        recovered = await _retry_failed_expectation(plan, planner, executor, world)
        if recovered:
            final_verification = verify_success_criteria(plan, world)

    success = plan.finished() and not plan.failed() and final_verification.passed
    failures = [
        f"{step.id}: {step.last_error}"
        for step in plan.steps
        if step.last_error
    ]
    if plan.finished() and not final_verification.passed:
        failures.append(f"success criteria: {final_verification.reason}")
    return TaskResult(
        goal=goal,
        success=success,
        summary="Task completed by structured controller." if success else "Structured controller did not satisfy the expected outcome.",
        verification_passed=final_verification.passed,
        verification_reason=final_verification.reason,
        tool_calls=len(context.memory.tool_calls),
        retries=context.memory.total_retries(),
        artifacts=list(context.memory.artifacts),
        failures=failures + list(context.memory.failures),
        billing=tracker.to_billing_info(),
    )


async def _plan_action(
    step,
    planner: Planner,
    executor: Executor,
    world: WorldModel,
) -> PlannedAction:
    if step.kind == StepKind.LAUNCH and "app_id" in step.arguments:
        return PlannedAction(
            tool="activate_app",
            args={"app_id": step.arguments["app_id"]},
            rationale=f"launch app for {step.id}",
            expected_effect="screen_change",
            verify_with="none",
        )

    if world.current() is None:
        await executor.observe()
    snapshot = world.current()
    if snapshot is None:
        return PlannedAction(
            tool="snapshot",
            args={"scope": "full", "context": "native", "boxes": False},
            rationale="observe before planning",
            expected_effect="info_only",
            verify_with="none",
        )
    return planner.plan(step, snapshot)


async def _retry_failed_expectation(
    plan,
    planner: Planner,
    executor: Executor,
    world: WorldModel,
) -> bool:
    criteria_text = "\n".join(criterion.description for criterion in plan.success_criteria).lower()
    if "お気に入り" not in criteria_text and "favorite" not in criteria_text:
        return False

    favorite_step = _find_step(plan, StepKind.INTERACT, ("お気に入り", "favorite"))
    if favorite_step is None:
        return False
    sequence = _retry_sequence_for(plan, favorite_step)

    for step in sequence:
        if world.current() is None:
            await executor.observe()
        snapshot = world.current()
        if snapshot is None:
            return False
        action = planner.plan(step, snapshot)
        if action.expected_effect == "favorite_toggled":
            content_text = infer_content_identity(plan, snapshot, str(action.args.get("ref", "")))
            if content_text:
                step.evidence.append(f"content_text:{content_text}")
        outcome = await executor.execute(action)
        if not outcome.ok:
            return False
    return True


def _find_step(plan, kind: StepKind, target_markers: tuple[str, ...]):
    for step in plan.steps:
        if step.kind != kind:
            continue
        if not target_markers:
            return step
        haystack = f"{step.target_hint or ''} {step.intent} {step.raw_text}".lower()
        if any(marker.lower() in haystack for marker in target_markers):
            return step
    return None


def _retry_sequence_for(plan, effect_step):
    prior_navigation = [
        step for step in plan.steps if step.index < effect_step.index and step.kind == StepKind.NAVIGATE
    ]
    prior_scroll = [
        step for step in plan.steps if step.index < effect_step.index and step.kind == StepKind.SCROLL
    ]
    following_navigation = [
        step for step in plan.steps if step.index > effect_step.index and step.kind == StepKind.NAVIGATE
    ]
    sequence = [
        prior_navigation[-1] if prior_navigation else None,
        prior_scroll[-1] if prior_scroll else None,
        effect_step,
        following_navigation[0] if following_navigation else None,
    ]
    return [step for step in sequence if step is not None]
