"""Preflight suggestions for common CLI argument-order mistakes."""

from __future__ import annotations

from dataclasses import dataclass
from shlex import quote


DIRECTIONS = {"up", "down", "left", "right"}
DIRECTION_FIRST_COMMANDS = {"scroll", "swipe", "fling"}
ROOT_OPTIONS_WITH_VALUE = {"--install-completion", "--show-completion"}


@dataclass(frozen=True)
class UsageSuggestion:
    """Concrete correction for a likely command-line usage mistake."""

    command: str
    message: str
    suggestion: str


def suggest_usage(argv: list[str]) -> UsageSuggestion | None:
    """Return a suggestion for known invalid argument orders.

    This intentionally only recognizes high-confidence patterns. Ambiguous or
    unknown inputs fall through to Typer so existing parsing behavior remains
    the default.
    """

    command, args = _split_root_command(argv)
    if not command:
        return None

    if command in DIRECTION_FIRST_COMMANDS:
        return _suggest_direction_first(command, args)
    if command == "scroll_element":
        return _suggest_scroll_element(args)
    return None


def format_suggestion(suggestion: UsageSuggestion) -> str:
    """Render a CLI-facing suggestion message."""

    return (
        f"ERROR: {suggestion.message}\n"
        f"Did you mean: {suggestion.suggestion}\n"
        f"Run 'appium-cli {suggestion.command} --help' to confirm the command syntax."
    )


def _split_root_command(argv: list[str]) -> tuple[str | None, list[str]]:
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--":
            return None, []
        if token.startswith("-"):
            option_name = token.split("=", 1)[0]
            i += 1
            if "=" not in token and option_name in ROOT_OPTIONS_WITH_VALUE and i < len(argv):
                i += 1
            continue
        return token, argv[i + 1 :]
    return None, []


def _positionals(args: list[str]) -> list[str]:
    positionals: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            positionals.extend(args[i + 1 :])
            break
        if token.startswith("-"):
            i += 1
            if "=" not in token and i < len(args) and not args[i].startswith("-"):
                i += 1
            continue
        positionals.append(token)
        i += 1
    return positionals


def _suggest_direction_first(command: str, args: list[str]) -> UsageSuggestion | None:
    positionals = _positionals(args)
    if len(positionals) != 2:
        return None

    ref, direction = positionals
    if direction not in DIRECTIONS or ref in DIRECTIONS:
        return None

    alias = f"{command}_{direction}"
    suggestion = f"appium-cli {alias} {quote(ref)}"
    return UsageSuggestion(
        command=alias,
        message=f"unexpected argument order for {command}; use the normalized {alias} <ref> form",
        suggestion=suggestion,
    )


def _suggest_scroll_element(args: list[str]) -> UsageSuggestion | None:
    positionals = _positionals(args)
    if len(positionals) != 3:
        return None

    by, value, direction = positionals
    if direction not in DIRECTIONS:
        return None

    suggestion = f"appium-cli scroll_element {quote(by)} {quote(value)} --direction={quote(direction)}"
    return UsageSuggestion(
        command="scroll_element",
        message="unexpected positional direction for scroll_element; pass direction with --direction",
        suggestion=suggestion,
    )
