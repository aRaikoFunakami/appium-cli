"""Unit tests for web_form_url (Phase 1) and web_eval lint (Phase 2)."""

from __future__ import annotations

import inspect
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from appium_cli.daemon import state
from appium_cli.tools import actions, observation
from appium_cli.utils.errors import AppiumCliError
from appium_cli.utils.exit_codes import FEATURE_NOT_ENABLED


class _FakeFormDriver:
    """Driver that pretends to be in WebView and returns a programmed form payload."""

    current_context = "CHROMIUM"

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.calls: list[tuple[Any, int]] = []

    def execute_script(self, script: str, target: Any, max_fields: int):
        assert "form.elements" in script
        self.calls.append((target, max_fields))
        return self.payload


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    state.reset()
    monkeypatch.setattr("appium_cli.tools.observation.current_context", lambda d: "CHROMIUM")
    monkeypatch.setattr("appium_cli.tools.observation.is_web_context", lambda ctx: True)
    yield
    state.reset()


def _payload(
    fields: list[dict[str, Any]],
    *,
    method: str = "GET",
    action_raw: str = "/search",
    action_resolved: str = "https://example.com/search",
    page_origin: str = "https://example.com",
    omitted: int = 0,
    truncated: bool = False,
) -> dict[str, Any]:
    return {
        "found": True,
        "method": method,
        "enctype": "application/x-www-form-urlencoded",
        "action_raw": action_raw,
        "action_resolved": action_resolved,
        "page_url": page_origin + "/page",
        "page_origin": page_origin,
        "form_selector_hint": "form",
        "fields": fields,
        "omitted_fields_count": omitted,
        "fields_truncated": truncated,
    }


def _field(name: str, value: str = "v", **kwargs: Any) -> dict[str, Any]:
    base = {
        "name": name,
        "value": value,
        "tag": "input",
        "type": "text",
        "hidden": False,
        "autocomplete": "",
        "inputmode": "",
        "placeholder": "",
        "aria_label": "",
        "id": "",
        "label": "",
    }
    base.update(kwargs)
    return base


def test_get_form_builds_url_and_emits_warnings():
    state.driver = _FakeFormDriver(_payload([
        _field("q", "hello"),
        _field("lang", "ja", type="text"),
    ]))
    text = observation.web_form_url("form")
    assert "frontend_interaction_skipped: true" in text
    assert "method: GET" in text
    assert "url: https://example.com/search?q=hello&lang=ja" in text
    assert "Do not use this as frontend E2E validation" in text


def test_raw_output_returns_structured_json():
    state.driver = _FakeFormDriver(_payload([_field("q", "hi")]))
    raw = observation.web_form_url("form", raw=True)
    payload = json.loads(raw)
    assert payload["inspection_only"] is True
    assert payload["frontend_interaction_skipped"] is True
    assert payload["method"] == "GET"
    assert payload["url"].endswith("?q=hi")
    assert payload["fields"][0]["name"] == "q"
    assert payload["fields"][0]["redacted"] is False
    # Internal alias must not leak in raw output
    assert "display_value" not in payload["fields"][0]


def test_hidden_field_is_always_redacted():
    state.driver = _FakeFormDriver(_payload([
        _field("q", "hi"),
        _field("token", "deadbeef", type="hidden", hidden=True),
    ]))
    raw = observation.web_form_url("form", raw=True)
    payload = json.loads(raw)
    token = next(f for f in payload["fields"] if f["name"] == "token")
    assert token["redacted"] is True
    assert token["value"] == "[REDACTED]"
    assert token["reason"] == "hidden"
    # URL must not contain the raw secret
    assert "deadbeef" not in payload["url"]
    assert "token=%5BREDACTED%5D" in payload["url"] or "token=[REDACTED]" in payload["url"].replace(
        "%5B", "[").replace("%5D", "]")


def test_password_type_is_redacted_with_type_password_reason():
    state.driver = _FakeFormDriver(_payload([
        _field("user", "alice"),
        _field("pw", "supersecret", type="password"),
    ]))
    raw = observation.web_form_url("form", raw=True)
    payload = json.loads(raw)
    pw = next(f for f in payload["fields"] if f["name"] == "pw")
    assert pw["redacted"] is True
    assert pw["reason"] == "type_password"
    assert "supersecret" not in payload["url"]


@pytest.mark.parametrize("name,reason", [
    ("csrf_token", "name_pattern"),
    ("api_key", "name_pattern"),
    ("otp", "name_pattern"),
    ("verification_code", "name_pattern"),
])
def test_name_pattern_redaction(name, reason):
    state.driver = _FakeFormDriver(_payload([_field(name, "secret!")]))
    raw = observation.web_form_url("form", raw=True)
    payload = json.loads(raw)
    f = payload["fields"][0]
    assert f["redacted"] is True
    assert f["reason"] == reason
    assert "secret!" not in payload["url"]


def test_autocomplete_current_password_is_redacted():
    state.driver = _FakeFormDriver(_payload([_field("p", "x", autocomplete="current-password")]))
    raw = observation.web_form_url("form", raw=True)
    payload = json.loads(raw)
    assert payload["fields"][0]["reason"] == "autocomplete"


def test_label_pattern_redaction():
    state.driver = _FakeFormDriver(_payload([_field("x", "v", label="Enter password")]))
    raw = observation.web_form_url("form", raw=True)
    payload = json.loads(raw)
    assert payload["fields"][0]["reason"] == "label_pattern"


def test_post_form_emits_no_url_and_payload_summary():
    state.driver = _FakeFormDriver(_payload([_field("q", "hello")], method="POST"))
    raw = observation.web_form_url("form", raw=True)
    payload = json.loads(raw)
    assert "url" not in payload
    assert payload["payload_summary"][0]["name"] == "q"
    assert any("post_no_replay_url" in w for w in payload["warnings"])


def test_javascript_action_emits_no_url():
    state.driver = _FakeFormDriver(_payload(
        [_field("q", "hi")],
        action_raw="javascript:void(0)",
        action_resolved="javascript:void(0)",
    ))
    raw = observation.web_form_url("form", raw=True)
    payload = json.loads(raw)
    assert "url" not in payload
    assert payload["non_http_action"] is True
    assert any("non_http_action" in w for w in payload["warnings"])


def test_cross_origin_action_warns_but_emits_url():
    state.driver = _FakeFormDriver(_payload(
        [_field("q", "hi")],
        action_raw="https://other.example/x",
        action_resolved="https://other.example/x",
        page_origin="https://example.com",
    ))
    raw = observation.web_form_url("form", raw=True)
    payload = json.loads(raw)
    assert "url" in payload
    assert payload["cross_origin_action"] is True
    assert any("cross_origin_action" in w for w in payload["warnings"])


def test_names_only_omits_values_and_url():
    state.driver = _FakeFormDriver(_payload([_field("q", "hello")]))
    raw = observation.web_form_url("form", raw=True, names_only=True)
    payload = json.loads(raw)
    assert "url" not in payload
    assert payload["fields"][0]["redacted"] is True
    assert payload["fields"][0]["value"] == "[REDACTED]"
    assert "hello" not in raw


def test_max_value_length_truncates():
    state.driver = _FakeFormDriver(_payload([_field("q", "x" * 500)]))
    raw = observation.web_form_url("form", raw=True, max_value_length=10)
    payload = json.loads(raw)
    f = payload["fields"][0]
    assert f["value"] == "x" * 10
    assert f["truncated"] is True


def test_multi_select_doseq_url_encoding():
    state.driver = _FakeFormDriver(_payload([
        _field("items", "a", tag="select", type="select-multiple"),
        _field("items", "b", tag="select", type="select-multiple"),
    ]))
    raw = observation.web_form_url("form", raw=True)
    payload = json.loads(raw)
    parsed = urlparse(payload["url"])
    qs = parse_qs(parsed.query)
    assert qs["items"] == ["a", "b"]


def test_empty_form_warns():
    state.driver = _FakeFormDriver(_payload([]))
    raw = observation.web_form_url("form", raw=True)
    payload = json.loads(raw)
    assert any("empty_form" in w for w in payload["warnings"])


def test_not_in_webview_context_raises_feature_not_enabled(monkeypatch):
    state.driver = _FakeFormDriver(_payload([]))
    monkeypatch.setattr("appium_cli.tools.observation.is_web_context", lambda ctx: False)
    with pytest.raises(AppiumCliError) as exc:
        observation.web_form_url("form")
    assert exc.value.exit_code == FEATURE_NOT_ENABLED


def test_js_error_no_form_raises():
    state.driver = _FakeFormDriver({"error": "no_form", "message": "no <form>"})
    with pytest.raises(AppiumCliError) as exc:
        observation.web_form_url(".thing")
    assert "no enclosing <form>" in str(exc.value)


def test_js_error_not_found_raises():
    state.driver = _FakeFormDriver({"error": "not_found", "message": "missing"})
    with pytest.raises(AppiumCliError) as exc:
        observation.web_form_url(".missing")
    assert "not found" in str(exc.value)


def test_no_unredact_flag_exists_on_function():
    sig = inspect.signature(observation.web_form_url)
    params = set(sig.parameters)
    assert "unredact" not in params
    assert "show_secrets" not in params
    assert "show_values" not in params
    assert "include_hidden" not in params


def test_no_unredact_flag_exists_on_cli_wrapper():
    from appium_cli.cli import tools as cli_tools

    sig = inspect.signature(cli_tools.web_form_url)
    params = set(sig.parameters)
    assert "unredact" not in params
    assert "show_secrets" not in params
    assert "show_values" not in params
    assert "include_hidden" not in params


def test_no_side_effects_on_driver():
    """Mocked driver must only see execute_script for the inspection JS; no get/click/submit."""
    calls: list[tuple[str, tuple]] = []

    class TrackingDriver(_FakeFormDriver):
        def get(self, *a, **k):
            calls.append(("get", a))
            raise AssertionError("web_form_url must not navigate")

        def click(self, *a, **k):
            calls.append(("click", a))
            raise AssertionError("web_form_url must not click")

    driver = TrackingDriver(_payload([_field("q", "hi")]))
    state.driver = driver
    observation.web_form_url("form")
    assert calls == []
    # And the JS that was sent must not contain submit() or .click() or window.location =
    sent_script = observation.WEB_FORM_URL_SCRIPT
    assert "submit()" not in sent_script
    assert "requestSubmit" not in sent_script
    assert "click()" not in sent_script
    assert "window.location" not in sent_script


# --- Phase 2: web_eval lint ---


@pytest.mark.parametrize("script", [
    "window.location = 'https://example.com'",
    "window.location.href = 'https://example.com'",
    "location.href = '/x'",
    "history.pushState({}, '', '/x')",
    "history.replaceState({}, '', '/x')",
])
def test_lint_web_eval_flags_navigation(script):
    warnings = actions.lint_web_eval(script)
    assert warnings
    assert any("goto" in w for w in warnings)


@pytest.mark.parametrize("script", [
    "document.querySelector('input').value = 'hi'",
    "el.value = 'x'; el.dispatchEvent(new Event('input', {bubbles: true}))",
])
def test_lint_web_eval_flags_value_injection(script):
    warnings = actions.lint_web_eval(script)
    assert warnings
    assert any("fill" in w for w in warnings)


@pytest.mark.parametrize("script", [
    "return document.title",
    "return window.location.href",  # read-only, not assignment
    "return document.querySelector('input').name",
])
def test_lint_web_eval_silent_on_safe_scripts(script):
    assert actions.lint_web_eval(script) == []


def test_daemon_web_eval_attaches_warnings(monkeypatch):
    from appium_cli.daemon import entry

    monkeypatch.setattr(entry.actions, "web_eval", lambda script, ref="": "ok")
    response = entry._handler({
        "tool": "web_eval",
        "args": {"script": "window.location.href = '/x'", "ref": ""},
    })
    assert response["text"] == "ok"
    assert "warnings" in response["data"]
    assert response["data"]["warnings"]


def test_daemon_web_eval_no_lint_suppresses(monkeypatch):
    from appium_cli.daemon import entry

    monkeypatch.setattr(entry.actions, "web_eval", lambda script, ref="": "ok")
    response = entry._handler({
        "tool": "web_eval",
        "args": {"script": "window.location.href = '/x'", "ref": "", "no_lint": True},
    })
    assert response["text"] == "ok"
    assert response["data"] == {}
