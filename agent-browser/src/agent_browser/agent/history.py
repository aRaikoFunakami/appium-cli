"""Token-bounded operation history for browser automation."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field


def _hash_short(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:8]


INFO_ONLY_TOOLS = frozenset({
    "snapshot",
    "web_snapshot",
    "snapshot_show",
    "snapshot_search",
    "snapshot_refs",
    "web_query",
    "find_by_text",
    "describe",
    "get_page_source",
    "webview_url",
    "webview_title",
    "screenshot",
})

LOOP_REPEAT_EXEMPT = frozenset({"snapshot", "web_snapshot", "screenshot"})


@dataclass(slots=True)
class HistoryItem:
    step: int
    action_name: str | None
    args_summary: str
    success: bool
    result_summary: str
    screen_hash: str | None = None

    def to_prompt_line(self) -> str:
        mark = "ok" if self.success else "fail"
        name = self.action_name or "no_tool"
        args = f"({self.args_summary})" if self.args_summary else "()"
        return f"[{self.step}] {name}{args} -> {mark} {self.result_summary}"


@dataclass(slots=True)
class OperationHistory:
    recent_steps: int = 5
    compacted_history_cap: int = 500
    items: list[HistoryItem] = field(default_factory=list)
    compacted_history: str = ""

    def add(self, item: HistoryItem) -> None:
        self.items.append(item)
        if len(self.items) > self.recent_steps * 3:
            self._compact_old()

    def recent_lines(self) -> str:
        return "\n".join(item.to_prompt_line() for item in self.items[-self.recent_steps :])

    def _compact_old(self) -> None:
        old = self.items[: -self.recent_steps]
        if not old:
            return
        important = [
            item.to_prompt_line()
            for item in old
            if (not item.success) or item.action_name not in INFO_ONLY_TOOLS
        ]
        compacted = "\n".join(important[-5:])
        if len(compacted) > self.compacted_history_cap:
            compacted = compacted[: self.compacted_history_cap - 20] + "... [trimmed]"
        self.compacted_history = compacted
        self.items = self.items[-self.recent_steps :]


@dataclass(slots=True)
class LoopDetector:
    window_size: int = 10
    actions: list[str] = field(default_factory=list)
    screens: list[str] = field(default_factory=list)
    warning_count: int = 0

    def record(self, action_name: str | None, args_summary: str, observation: str) -> None:
        name = action_name or "no_tool"
        self.actions.append(f"{name}:{_hash_short(args_summary)}")
        self.screens.append(_hash_short(observation) if observation else "")
        if len(self.actions) > self.window_size:
            self.actions.pop(0)
        if len(self.screens) > self.window_size:
            self.screens.pop(0)

    def detect(self) -> str | None:
        if len(self.actions) < 3:
            self.warning_count = 0
            return None

        warning: str | None = None
        recent_names = [item.split(":", 1)[0] for item in self.actions[-3:]]
        if all(name in INFO_ONLY_TOOLS for name in recent_names):
            warning = "The last 3 steps were information-only. Choose an action that changes progress."

        if warning is None:
            counts = Counter(self.actions)
            for key, count in counts.items():
                name = key.split(":", 1)[0]
                if count >= 3 and name not in LOOP_REPEAT_EXEMPT:
                    warning = f"The same action '{name}' repeated {count} times. Try a different approach."
                    break

        if warning is None and len(self.screens) >= 5:
            recent_screens = self.screens[-5:]
            if recent_screens[0] and len(set(recent_screens)) == 1:
                warning = "The screen has not changed for 5 steps. Avoid repeating the same observation/action."

        if warning is None:
            self.warning_count = 0
            return None
        self.warning_count += 1
        if self.warning_count >= 3:
            return f"CRITICAL LOOP WARNING: {warning} Finish with failure if no new approach is available."
        return warning
