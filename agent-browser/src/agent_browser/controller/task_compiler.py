"""Prompt-to-task-plan compiler for the structured controller."""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent_browser.controller.task_plan import (
    StepKind,
    SuccessCriterion,
    TaskPlan,
    TaskStep,
)


_NUMBERED_STEP_RE = re.compile(r"^\s*(?P<num>\d+)[\.\)、)]\s*(?P<text>.+?)\s*$")
_CRITERION_RE = re.compile(r"^\s*(?P<label>[A-ZＡ-Ｚ])[\.\)、)]\s*(?P<text>.+?)\s*$")
_APP_ID_RE = re.compile(r"\((?P<app_id>[A-Za-z0-9_.]+)\)")
_QUOTED_RE = re.compile(r"[「\"](?P<text>.*?)[」\"]")


@dataclass(slots=True)
class TaskCompiler:
    """Compile user goals into an ordered deterministic task plan."""

    strict_ordering: bool = True

    def compile(self, goal: str) -> TaskPlan:
        """Compile a natural-language goal into ordered steps and criteria."""
        step_lines, criterion_lines = self._split_goal(goal)
        steps: list[TaskStep] = []
        previous_mandatory_id: str | None = None

        for index, raw_text in enumerate(step_lines, start=1):
            kind = self._classify_step(raw_text)
            step_id = f"step-{index}"
            arguments = self._extract_arguments(raw_text, kind)
            step = TaskStep(
                id=step_id,
                index=index,
                kind=kind,
                raw_text=raw_text,
                intent=self._intent_for(raw_text, kind, arguments),
                target_hint=self._target_hint_for(raw_text, kind),
                expected_effect=self._expected_effect_for(kind),
                mandatory=True,
                depends_on=[previous_mandatory_id] if previous_mandatory_id else [],
                arguments=arguments,
            )
            steps.append(step)
            previous_mandatory_id = step_id

        criteria = [
            SuccessCriterion(
                id=f"criterion-{index}",
                description=text,
                method=self._criterion_method(text),
                args={"raw_text": text},
            )
            for index, text in enumerate(criterion_lines, start=1)
        ]
        return TaskPlan(goal=goal, steps=steps, success_criteria=criteria)

    def _split_goal(self, goal: str) -> tuple[list[str], list[str]]:
        step_lines: list[str] = []
        criterion_lines: list[str] = []
        in_criteria = False

        for line in goal.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if "期待動作" in stripped or stripped.lower().startswith(("expected", "expectation")):
                in_criteria = True
                continue

            if in_criteria:
                criterion = self._criterion_text(stripped)
                if criterion:
                    criterion_lines.append(criterion)
                continue

            match = _NUMBERED_STEP_RE.match(stripped)
            if match:
                step_lines.append(match.group("text"))

        if not step_lines:
            step_lines = [line.strip() for line in goal.splitlines() if line.strip()]
        return step_lines, criterion_lines

    def _criterion_text(self, line: str) -> str | None:
        match = _CRITERION_RE.match(line)
        if match:
            return match.group("text")
        return line or None

    def _classify_step(self, text: str) -> StepKind:
        normalized = text.lower()
        if self._contains_any(text, "起動", "立ち上げ") or self._contains_any(
            normalized, "launch", "open app", "start app"
        ):
            return StepKind.LAUNCH
        if self._contains_any(text, "スクロール", "スワイプ") or self._contains_any(
            normalized, "scroll", "swipe"
        ):
            return StepKind.SCROLL
        if self._contains_any(text, "待機", "待つ") or self._contains_any(normalized, "wait"):
            return StepKind.WAIT
        if self._contains_any(text, "確認", "検証") or self._contains_any(
            normalized, "verify", "assert", "confirm"
        ):
            return StepKind.VERIFY
        if self._contains_any(text, "タブ") or self._contains_any(
            normalized, "tab", "navigate", "select"
        ):
            return StepKind.NAVIGATE
        return StepKind.INTERACT

    def _extract_arguments(self, text: str, kind: StepKind) -> dict[str, str]:
        args: dict[str, str] = {}
        if kind == StepKind.LAUNCH:
            match = _APP_ID_RE.search(text)
            if match:
                args["app_id"] = match.group("app_id")
        if kind == StepKind.SCROLL:
            args["direction"] = self._scroll_direction(text)
        return args

    def _scroll_direction(self, text: str) -> str:
        normalized = text.lower()
        direction_patterns = (
            ("up", ("上", "up")),
            ("down", ("下", "down")),
            ("left", ("左", "left")),
            ("right", ("右", "right")),
        )
        for direction, patterns in direction_patterns:
            if any(pattern in normalized or pattern in text for pattern in patterns):
                return direction
        return "down"

    def _intent_for(self, text: str, kind: StepKind, arguments: dict[str, str]) -> str:
        if kind == StepKind.SCROLL:
            return f"scroll {arguments.get('direction', 'down')}"
        if kind == StepKind.LAUNCH and "app_id" in arguments:
            return f"launch {arguments['app_id']}"
        return self._strip_action_suffix(text)

    def _target_hint_for(self, text: str, kind: StepKind) -> str | None:
        if kind == StepKind.SCROLL:
            return None
        quoted = _QUOTED_RE.search(text)
        if quoted:
            return quoted.group("text")
        if kind == StepKind.LAUNCH:
            app_id_match = _APP_ID_RE.search(text)
            without_app_id = _APP_ID_RE.sub("", text).strip()
            return self._strip_action_suffix(without_app_id) or (
                app_id_match.group("app_id") if app_id_match else None
            )
        hint = self._strip_action_suffix(text)
        return hint or None

    def _strip_action_suffix(self, text: str) -> str:
        cleaned = text.strip()
        suffixes = (
            "をタップする",
            "をクリックする",
            "を選択する",
            "を起動する",
            "にスクロールする",
            "スクロールする",
            "する",
        )
        for suffix in suffixes:
            if cleaned.endswith(suffix):
                return cleaned[: -len(suffix)].strip()
        return cleaned

    def _expected_effect_for(self, kind: StepKind) -> str:
        return {
            StepKind.LAUNCH: "app launched",
            StepKind.NAVIGATE: "screen or selected tab changes",
            StepKind.SCROLL: "visible content moves",
            StepKind.INTERACT: "target state changes",
            StepKind.VERIFY: "expected state is confirmed",
            StepKind.WAIT: "time passes or loading settles",
        }[kind]

    def _criterion_method(self, text: str) -> str:
        if self._contains_any(text, "表示", "確認", "visible", "shown", "appears"):
            return "text_present"
        return "llm_judge"

    def _contains_any(self, text: str, *needles: str) -> bool:
        return any(needle in text for needle in needles)
