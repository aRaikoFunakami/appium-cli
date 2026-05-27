"""Tests for deterministic scroll container planning."""

from __future__ import annotations

from pathlib import Path

from agent_browser.controller.planner import Planner
from agent_browser.controller.scoring import ScrollScoreContext, rank_scroll_containers
from agent_browser.controller.task_compiler import TaskCompiler
from agent_browser.world import load_snapshot


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "twine4car"


def test_twine4car_scroll_scoring_prefers_main_content_container() -> None:
    snapshot = load_snapshot(FIXTURE_DIR / "movie_tab_before_scroll")

    ranking = rank_scroll_containers(snapshot, ScrollScoreContext(direction="up"))

    assert [ref.ref for ref, _score in ranking] == [
        "movies_section_scroll_view",
        "rv_popups",
        "rv_genres",
        "rv_tab_menu",
    ]
    scores = {ref.ref: score for ref, score in ranking}
    assert scores["movies_section_scroll_view"] > scores["rv_tab_menu"]
    assert scores["movies_section_scroll_view"] > scores["rv_genres"]


def test_planner_emits_scroll_up_against_main_content_container() -> None:
    goal = """\
1. Select the Movie tab
2. Scroll up
3. Tap the favorite button
"""
    snapshot = load_snapshot(FIXTURE_DIR / "movie_tab_before_scroll")
    plan = TaskCompiler().compile(goal)
    scroll_step = plan.get_step("step-2")

    action = Planner().plan_scroll(scroll_step, snapshot)

    assert action.tool == "scroll_up"
    assert action.args == {"ref": "movies_section_scroll_view", "percent": 0.8}
    assert action.expected_effect == "ref_movement"
    assert action.verify_with == "snapshot_diff"
    assert [fallback.args.get("ref") for fallback in action.fallback[:2]] == [
        "rv_popups",
        "rv_genres",
    ]


def test_planner_can_tap_favorite_after_scroll_step_is_done() -> None:
    goal = """\
1. Select the Movie tab
2. Scroll up
3. Tap the favorite button
"""
    snapshot = load_snapshot(FIXTURE_DIR / "movie_tab_before_scroll")
    plan = TaskCompiler().compile(goal)
    interact_step = plan.get_step("step-3")

    action = Planner().plan_interaction(interact_step, snapshot)

    assert action.tool == "tap"
    assert action.args == {"ref": "iv_favorite_icon"}
    assert action.expected_effect == "favorite_toggled"
