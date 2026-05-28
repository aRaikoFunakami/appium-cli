"""Tests for deterministic final success criteria verification."""

from __future__ import annotations

from agent_browser.controller.task_compiler import TaskCompiler
from agent_browser.controller.verification import verify_success_criteria
from agent_browser.world.model import Snapshot, TextTarget, WorldModel


def _plan():
    return TaskCompiler().compile(
        """\
1. Tap the favorite button
2. Tap the favorites tab
期待動作：
A. コンテンツはお気に入りリストに追加される
B. 追加されたコンテンツはお気に入りページで確認できる
"""
    )


def _snapshot(texts: list[str]) -> Snapshot:
    return Snapshot(
        id="snapshot",
        screen_id="screen",
        context="NATIVE_APP",
        refs={},
        text_targets=[TextTarget(text=text) for text in texts],
    )


def test_favorites_criteria_fail_when_page_has_no_content() -> None:
    plan = _plan()
    plan.steps[0].evidence.append("content_text:Example Movie")
    world = WorldModel()
    world.update(_snapshot(["ホーム", "映画", "お気に入り", "もっと表示する"]))

    result = verify_success_criteria(plan, world)

    assert result.passed is False
    assert result.reason == "recorded content not visible in final page: Example Movie"


def test_favorites_criteria_pass_when_added_content_is_visible() -> None:
    plan = _plan()
    plan.steps[0].evidence.append("content_text:ソニック × シャドウ TOKYO MISSION")
    world = WorldModel()
    world.update(_snapshot(["ホーム", "映画", "お気に入り", "もっと表示する", "ソニック × シャドウ TOKYO MISSION"]))

    result = verify_success_criteria(plan, world)

    assert result.passed is True
    assert result.reason == "favorites content visible: ソニック × シャドウ TOKYO MISSION"


def test_favorites_criteria_fail_without_recorded_content_identity() -> None:
    world = WorldModel()
    world.update(_snapshot(["ホーム", "映画", "お気に入り", "もっと表示する", "Some Movie"]))

    result = verify_success_criteria(_plan(), world)

    assert result.passed is False
    assert result.reason == "no interacted content identity recorded"


def test_text_present_criteria_pass_when_expected_text_is_visible() -> None:
    plan = TaskCompiler().compile(
        """\
1. Tap the app sub-tab
期待動作
アプリ履歴のない場合、「アプリはありません」を表示する
"""
    )
    world = WorldModel()
    world.update(_snapshot(["ホーム", "最近の項目", "アプリはありません"]))

    result = verify_success_criteria(plan, world)

    assert result.passed is True
    assert result.reason == "expected text visible: アプリはありません"


def test_text_present_criteria_fail_when_expected_text_is_missing() -> None:
    plan = TaskCompiler().compile(
        """\
1. Tap the app sub-tab
期待動作
アプリ履歴のない場合、「アプリはありません」を表示する
"""
    )
    world = WorldModel()
    world.update(_snapshot(["ホーム", "最近の項目"]))

    result = verify_success_criteria(plan, world)

    assert result.passed is False
    assert result.reason == "expected text not visible: アプリはありません"


def test_text_present_criteria_uses_visible_texts_from_compact_snapshot() -> None:
    plan = TaskCompiler().compile(
        """\
1. Tap the app sub-tab
期待動作
アプリ履歴のない場合、「アプリはありません」を表示する
"""
    )
    world = WorldModel()
    world.update(
        Snapshot(
            id="snapshot",
            screen_id="screen",
            context="NATIVE_APP",
            refs={},
            visible_texts=["アプリはありません"],
        )
    )

    result = verify_success_criteria(plan, world)

    assert result.passed is True
    assert result.reason == "expected text visible: アプリはありません"
