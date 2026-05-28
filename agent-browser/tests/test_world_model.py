"""Tests for loading appium-cli snapshot artifacts into a World Model."""

from __future__ import annotations

from pathlib import Path

from agent_browser.world import WorldModel, load_snapshot
from agent_browser.world.query import candidate_refs_by_name, find_text, refs_within, scrollable_containers


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "twine4car"


def test_loads_twine4car_movie_tab_snapshot() -> None:
    snapshot = load_snapshot(FIXTURE_DIR / "movie_tab_before_scroll")

    assert snapshot.id == "native-2026-05-27T09-26-19-125Z-1af846"
    assert snapshot.screen_id == "1af846"
    assert snapshot.context == "NATIVE_APP"
    assert "movies_section_scroll_view" in snapshot.refs
    assert "favoriteicon" in snapshot.refs


def test_scrollable_containers_include_main_movie_section() -> None:
    snapshot = load_snapshot(FIXTURE_DIR / "movie_tab_before_scroll")

    refs = {container.ref: container for container in scrollable_containers(snapshot)}

    assert refs["movies_section_scroll_view"].scroll_direction == "vertical"
    assert refs["rv_tab_menu"].scrollable is True
    assert refs["rv_genres"].scrollable is True


def test_text_targets_preserve_tappable_tab_refs() -> None:
    snapshot = load_snapshot(FIXTURE_DIR / "movie_tab_before_scroll")

    movie_targets = find_text(snapshot, "映画")
    favorite_targets = find_text(snapshot, "お気に入り")

    assert movie_targets[0].tap_target_ref == "tabbackground_2"
    assert favorite_targets[0].tap_target_ref == "tabbackground_6"


def test_visible_texts_include_non_actionable_text_from_compact_artifact(tmp_path) -> None:
    base = tmp_path / "recent_app_empty"
    base.with_suffix(".index.json").write_text(
        '{"refs": [], "containers": [], "text_targets": []}',
        encoding="utf-8",
    )
    base.with_suffix(".meta.json").write_text(
        '{"snapshot_id": "recent_app_empty", "screen_id": "0a72c8", "context": "NATIVE_APP"}',
        encoding="utf-8",
    )
    base.with_suffix(".compact.yml").write_text(
        'screen: example\n\n- container\n  - text "アプリはありません"\n',
        encoding="utf-8",
    )

    snapshot = load_snapshot(base)

    assert "アプリはありません" in snapshot.visible_texts


def test_refs_within_main_movie_section_include_favorite_buttons() -> None:
    snapshot = load_snapshot(FIXTURE_DIR / "movie_tab_before_scroll")

    button_refs = {ref.ref for ref in refs_within(snapshot, "movies_section_scroll_view", role="button")}

    assert "favoriteicon" in button_refs
    assert "favoriteicon_5" in button_refs
    assert "tabbackground_2" not in button_refs


def test_world_model_tracks_current_and_previous_snapshots() -> None:
    snapshot = load_snapshot(FIXTURE_DIR / "movie_tab_before_scroll")
    world = WorldModel()

    assert world.has_current() is False
    world.update(snapshot)

    assert world.has_current() is True
    assert world.current() is snapshot
    assert world.previous() is None


def test_candidate_refs_by_name_finds_favorite_icons() -> None:
    snapshot = load_snapshot(FIXTURE_DIR / "movie_tab_before_scroll")

    refs = {ref.ref for ref in candidate_refs_by_name(snapshot, "favorite")}

    assert "favoriteicon" in refs
    assert "favoriteicon_5" in refs
