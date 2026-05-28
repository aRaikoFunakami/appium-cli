"""Tests for compiling natural-language prompts into structured task plans."""

from __future__ import annotations

from pathlib import Path

from agent_browser.controller.task_compiler import TaskCompiler
from agent_browser.controller.task_plan import StepKind


ROOT = Path(__file__).resolve().parents[1]


def test_twine4car_prompt_compiles_to_five_ordered_mandatory_steps() -> None:
    goal = (ROOT / "prompts" / "t4c.txt").read_text(encoding="utf-8")

    plan = TaskCompiler().compile(goal)

    assert [step.kind for step in plan.steps] == [
        StepKind.LAUNCH,
        StepKind.NAVIGATE,
        StepKind.SCROLL,
        StepKind.INTERACT,
        StepKind.NAVIGATE,
    ]
    assert [step.depends_on for step in plan.steps] == [
        [],
        ["step-1"],
        ["step-2"],
        ["step-3"],
        ["step-4"],
    ]
    assert all(step.mandatory for step in plan.steps)


def test_twine4car_prompt_extracts_action_details() -> None:
    goal = (ROOT / "prompts" / "t4c.txt").read_text(encoding="utf-8")

    plan = TaskCompiler().compile(goal)

    assert plan.steps[0].arguments["app_id"] == "com.access_company.twine4car.videocenter"
    assert plan.steps[1].target_hint == "映画"
    assert plan.steps[2].intent == "scroll up"
    assert plan.steps[2].arguments["direction"] == "up"
    assert "お気に入りボタン" in (plan.steps[3].target_hint or "")
    assert plan.steps[4].target_hint == "お気に入り"


def test_twine4car_success_criteria_are_preserved() -> None:
    goal = (ROOT / "prompts" / "t4c.txt").read_text(encoding="utf-8")

    plan = TaskCompiler().compile(goal)

    assert [criterion.description for criterion in plan.success_criteria] == [
        "コンテンツはお気に入りリストに追加される",
        "追加されたコンテンツはお気に入りページで確認できる",
    ]


def test_english_prompt_classification() -> None:
    goal = """\
1. Launch the app com.example.demo
2. Select the Movie tab
3. Scroll up
4. Tap the favorite button
5. Select the Favorites tab
Expected:
A. The content is visible in Favorites
"""

    plan = TaskCompiler().compile(goal)

    assert [step.kind for step in plan.steps] == [
        StepKind.LAUNCH,
        StepKind.NAVIGATE,
        StepKind.SCROLL,
        StepKind.INTERACT,
        StepKind.NAVIGATE,
    ]
    assert plan.steps[2].arguments["direction"] == "up"


def test_display_expectation_extracts_quoted_text() -> None:
    goal = """\
1. Tap the Recent tab
期待動作
アプリ履歴のない場合、「アプリはありません」を表示する
"""

    plan = TaskCompiler().compile(goal)

    assert len(plan.success_criteria) == 1
    assert plan.success_criteria[0].method == "text_present"
    assert plan.success_criteria[0].args["text"] == "アプリはありません"
