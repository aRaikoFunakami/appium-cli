"""Tests for WebSnapshotGenerator."""

from __future__ import annotations

import pytest

from appium_cli.core.snapshot import LocatorStrategy, RefEntry
from appium_cli.core.web_snapshot_generator import (
    WebSnapshotGenerator,
    _derive_ref,
    _determine_role,
    _make_unique,
    _to_snake,
)


class TestToSnake:
    def test_basic(self):
        assert _to_snake("searchForm") == "searchform"

    def test_special_chars(self):
        assert _to_snake("my-input_field!") == "my_input_field"

    def test_empty(self):
        assert _to_snake("   ") == ""

    def test_truncates(self):
        result = _to_snake("a" * 100)
        assert len(result) == 40


class TestDeriveRef:
    def test_from_id(self):
        elem = {"id": "searchForm", "test_id": "", "aria_label": "", "name": ""}
        assert _derive_ref(elem, "textbox") == "web_searchform"

    def test_from_test_id(self):
        elem = {"id": "", "test_id": "login-button", "aria_label": "", "name": ""}
        assert _derive_ref(elem, "button") == "web_login_button"

    def test_from_aria_label(self):
        elem = {"id": "", "test_id": "", "aria_label": "Submit", "name": ""}
        assert _derive_ref(elem, "button") == "web_submit"

    def test_from_name_fallback(self):
        elem = {"id": "", "test_id": "", "aria_label": "", "name": "News article title"}
        assert _derive_ref(elem, "link") == "web_link_news_article_title"

    def test_from_placeholder(self):
        elem = {"id": "", "test_id": "", "aria_label": "", "name": "", "placeholder": "Search..."}
        assert _derive_ref(elem, "textbox") == "web_input_search"

    def test_generic_fallback(self):
        elem = {"id": "", "test_id": "", "aria_label": "", "name": ""}
        assert _derive_ref(elem, "button") == "web_btn"


class TestMakeUnique:
    def test_unique(self):
        assert _make_unique("web_btn", set()) == "web_btn"

    def test_collision(self):
        assert _make_unique("web_btn", {"web_btn"}) == "web_btn_2"

    def test_multiple_collisions(self):
        assert _make_unique("web_btn", {"web_btn", "web_btn_2"}) == "web_btn_3"


class TestDetermineRole:
    def test_link(self):
        assert _determine_role({"tag": "a"}) == "link"

    def test_button(self):
        assert _determine_role({"tag": "button"}) == "button"

    def test_input_text(self):
        assert _determine_role({"tag": "input", "type": "text"}) == "textbox"

    def test_input_checkbox(self):
        assert _determine_role({"tag": "input", "type": "checkbox"}) == "checkbox"

    def test_input_radio(self):
        assert _determine_role({"tag": "input", "type": "radio"}) == "radio"

    def test_input_submit(self):
        assert _determine_role({"tag": "input", "type": "submit"}) == "button"

    def test_select(self):
        assert _determine_role({"tag": "select"}) == "select"

    def test_img(self):
        assert _determine_role({"tag": "img"}) == "image"

    def test_aria_role_override(self):
        assert _determine_role({"tag": "div", "role": "button"}) == "button"

    def test_unknown_tag(self):
        assert _determine_role({"tag": "div"}) == "element"


class TestWebSnapshotGeneratorFromDom:
    def setup_method(self):
        self.gen = WebSnapshotGenerator()

    def test_generates_snapshot_with_web_prefix(self):
        elements = [
            {"tag": "a", "id": "", "test_id": "", "aria_label": "", "name": "Home",
             "value": "", "type": "", "href": "/", "css": "", "bounds": {},
             "disabled": False, "checked": False, "selected": False, "readonly": False},
            {"tag": "button", "id": "submitBtn", "test_id": "", "aria_label": "", "name": "Submit",
             "value": "", "type": "", "href": "", "css": "#submitBtn", "bounds": {},
             "disabled": False, "checked": False, "selected": False, "readonly": False},
        ]
        snap, ref_map = self.gen.generate_from_dom(elements, "CHROMIUM", "https://example.com", "Example")

        assert snap.context == "CHROMIUM"
        assert snap.source_type == "web"
        assert snap.screen_id
        assert len(snap.elements) == 2
        assert all(e.ref.startswith("web_") for e in snap.elements)
        assert "web_submitbtn" in ref_map
        assert ref_map["web_submitbtn"].context == "CHROMIUM"
        assert ref_map["web_submitbtn"].source_type == "web"

    def test_dedup_suffixes(self):
        elements = [
            {"tag": "a", "id": "", "test_id": "", "aria_label": "", "name": "Link",
             "value": "", "type": "", "href": "/1", "css": "", "bounds": {}},
            {"tag": "a", "id": "", "test_id": "", "aria_label": "", "name": "Link",
             "value": "", "type": "", "href": "/2", "css": "", "bounds": {}},
        ]
        snap, ref_map = self.gen.generate_from_dom(elements, "CHROMIUM")

        refs = [e.ref for e in snap.elements]
        assert refs[0] != refs[1]
        assert refs[1].endswith("_2")

    def test_depth_limits_elements(self):
        elements = [
            {"tag": "a", "id": f"el{i}", "test_id": "", "aria_label": "", "name": f"Link {i}",
             "value": "", "type": "", "href": "", "css": f"#el{i}", "bounds": {}}
            for i in range(20)
        ]
        snap, ref_map = self.gen.generate_from_dom(elements, "CHROMIUM", depth=5)
        assert len(snap.elements) == 5
        assert len(ref_map) == 5

    def test_css_strategy_generated(self):
        elements = [
            {"tag": "button", "id": "btn1", "test_id": "", "aria_label": "", "name": "Click",
             "value": "", "type": "", "href": "", "css": "#btn1", "bounds": {}},
        ]
        _, ref_map = self.gen.generate_from_dom(elements, "CHROMIUM")
        entry = list(ref_map.values())[0]
        css_strategies = [s for s in entry.strategies if s.by == "css selector"]
        assert len(css_strategies) == 1
        assert css_strategies[0].value == "#btn1"

    def test_snapshot_text_includes_context_lines(self):
        elements = [
            {"tag": "button", "id": "btn1", "test_id": "", "aria_label": "", "name": "OK",
             "value": "", "type": "", "href": "", "css": "#btn1", "bounds": {}},
        ]
        snap, _ = self.gen.generate_from_dom(elements, "CHROMIUM", "https://example.com")
        text = snap.to_text()
        assert "context: CHROMIUM" in text
        assert "source: web" in text

    def test_element_states(self):
        elements = [
            {"tag": "input", "id": "chk1", "test_id": "", "aria_label": "", "name": "",
             "value": "", "type": "checkbox", "href": "", "css": "#chk1", "bounds": {},
             "disabled": True, "checked": True, "selected": False, "readonly": False},
        ]
        snap, _ = self.gen.generate_from_dom(elements, "CHROMIUM")
        el = snap.elements[0]
        assert "disabled" in el.state
        assert "checked" in el.state

    def test_nav_back_set_when_url(self):
        snap, _ = self.gen.generate_from_dom([], "CHROMIUM", url="https://example.com")
        assert snap.nav.get("back") is True

    def test_container_ref_is_web_document(self):
        elements = [
            {"tag": "a", "id": "lnk", "test_id": "", "aria_label": "", "name": "Go",
             "value": "", "type": "", "href": "/", "css": "#lnk", "bounds": {}},
        ]
        snap, _ = self.gen.generate_from_dom(elements, "CHROMIUM")
        assert snap.elements[0].container_ref == "web_document"
        assert snap.containers[0].ref == "web_document"


class TestWebSnapshotGeneratorFromHTML:
    def setup_method(self):
        self.gen = WebSnapshotGenerator()

    def test_parses_html_links_and_buttons(self):
        html = """
        <html><body>
            <a href="/home">Home</a>
            <button id="submit">Submit</button>
            <input type="text" placeholder="Search" />
        </body></html>
        """
        snap, ref_map = self.gen.generate(html, "WEBVIEW_com.example", "https://example.com")

        assert len(snap.elements) >= 2
        assert snap.context == "WEBVIEW_com.example"
        assert snap.source_type == "web"
        assert all(e.ref.startswith("web_") for e in snap.elements)

    def test_parses_data_testid(self):
        html = '<html><body><button data-testid="login-btn">Login</button></body></html>'
        snap, ref_map = self.gen.generate(html, "CHROMIUM")

        assert "web_login_btn" in ref_map

    def test_parses_aria_label(self):
        html = '<html><body><div role="button" aria-label="Close">X</div></body></html>'
        snap, ref_map = self.gen.generate(html, "CHROMIUM")

        assert "web_close" in ref_map


class TestRefEntryDefaults:
    """Verify backward compatibility of RefEntry context fields."""

    def test_default_context_is_native(self):
        entry = RefEntry(
            strategies=[LocatorStrategy(by="id", value="test")],
            expected_bounds=(0, 0, 0, 0),
            role="button",
            name="Test",
        )
        assert entry.context == "NATIVE_APP"
        assert entry.source_type == "native"

    def test_web_context(self):
        entry = RefEntry(
            strategies=[],
            expected_bounds=(0, 0, 0, 0),
            role="link",
            name="Test",
            context="CHROMIUM",
            source_type="web",
        )
        assert entry.context == "CHROMIUM"
        assert entry.source_type == "web"


class TestAccessibilitySnapshotDefaults:
    """Verify backward compatibility of AccessibilitySnapshot context fields."""

    def test_default_context_is_native(self):
        from appium_cli.core.snapshot import AccessibilitySnapshot
        snap = AccessibilitySnapshot(screen_id="abc123")
        assert snap.context == "NATIVE_APP"
        assert snap.source_type == "native"

    def test_native_snapshot_text_has_no_context_line(self):
        from appium_cli.core.snapshot import AccessibilitySnapshot
        snap = AccessibilitySnapshot(screen_id="abc123")
        text = snap.to_text()
        assert "context:" not in text
        assert "source:" not in text

    def test_web_snapshot_text_has_context_line(self):
        from appium_cli.core.snapshot import AccessibilitySnapshot
        snap = AccessibilitySnapshot(screen_id="abc123", context="CHROMIUM", source_type="web")
        text = snap.to_text()
        assert "context: CHROMIUM" in text
        assert "source: web" in text
