"""Deterministic scoring for target and container selection."""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent_browser.world.model import RefView, Snapshot


@dataclass(slots=True)
class ScrollScoreContext:
    """Inputs that influence scroll container scoring."""

    direction: str = "down"
    target_hint: str | None = None
    main_content_bias: float = 1.0
    header_penalty: float = 1.0
    header_fraction: float = 0.2


def score_scroll_container(container: RefView, snapshot: Snapshot, ctx: ScrollScoreContext) -> float:
    """Score a scrollable container for a requested scroll direction."""
    score = 0.0
    screen_height = _screen_height(snapshot)
    header_bottom = int(screen_height * ctx.header_fraction)

    if container.scrollable and _direction_matches(container.scroll_direction, ctx.direction):
        score += 2.0
    if _height(container) > screen_height * 0.4:
        score += 1.5 * ctx.main_content_bias
    if container.bounds and container.bounds[1] >= header_bottom:
        score += 1.0
    if ctx.target_hint and _container_contains_hint(container, snapshot, ctx.target_hint):
        score += 1.0
    if container.bounds and container.bounds[1] < header_bottom:
        score -= 2.0 * ctx.header_penalty
    if _looks_like_navigation(container):
        score -= 1.5
    if _looks_like_genre_chip_list(container):
        score -= 1.0
    if re.search(r"scroll|content|list|recycler", container.ref, re.IGNORECASE) and not re.search(
        r"tab|genre|menu", container.ref, re.IGNORECASE
    ):
        score += 0.5
    return score


def rank_scroll_containers(
    snapshot: Snapshot,
    ctx: ScrollScoreContext,
) -> list[tuple[RefView, float]]:
    """Return scroll containers sorted from best to worst."""
    scored = [
        (container, score_scroll_container(container, snapshot, ctx))
        for container in snapshot.scrollable_containers()
    ]
    return sorted(scored, key=lambda item: (-item[1], item[0].ref))


def _direction_matches(scroll_direction: str | None, requested: str) -> bool:
    if scroll_direction in {"vertical", "both"} and requested in {"up", "down"}:
        return True
    if scroll_direction in {"horizontal", "both"} and requested in {"left", "right"}:
        return True
    return scroll_direction == requested


def _screen_height(snapshot: Snapshot) -> int:
    if snapshot.screen_bounds is None:
        return 1
    return max(1, snapshot.screen_bounds[3] - snapshot.screen_bounds[1])


def _height(ref: RefView) -> int:
    if ref.bounds is None:
        return 0
    return max(0, ref.bounds[3] - ref.bounds[1])


def _container_contains_hint(container: RefView, snapshot: Snapshot, target_hint: str) -> bool:
    lowered = target_hint.lower()
    for ref in snapshot.refs_within(container.ref):
        if lowered in ref.ref.lower() or lowered in ref.name.lower():
            return True
    return False


def _looks_like_navigation(container: RefView) -> bool:
    haystack = f"{container.ref} {container.name} {container.container_kind or ''}".lower()
    return any(token in haystack for token in ("tab", "nav", "menu"))


def _looks_like_genre_chip_list(container: RefView) -> bool:
    haystack = f"{container.ref} {container.name}".lower()
    if "genre" in haystack:
        return True
    if container.bounds is None:
        return False
    width = container.bounds[2] - container.bounds[0]
    height = container.bounds[3] - container.bounds[1]
    return width > height * 4 and height < 200
