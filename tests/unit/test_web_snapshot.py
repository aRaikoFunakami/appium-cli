"""Tests for tree-first WebSnapshot generation."""

from __future__ import annotations

from appium_cli.core.snapshot import AccessibilitySnapshot, LocatorStrategy, RefEntry
from appium_cli.core.web_snapshot import WebSnapshot, WebSnapshotNode
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
        assert len(_to_snake("a" * 100)) == 40


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


class TestWebSnapshotModel:
    def test_renders_indented_tree(self):
        snap = WebSnapshot.from_root(
            context="CHROMIUM",
            url="https://example.com",
            title="Example",
            root=WebSnapshotNode(
                role="document",
                name="Example",
                children=[
                    WebSnapshotNode(
                        role="link",
                        name="Details",
                        ref="web_details",
                        children=[WebSnapshotNode(role="text", name="Click")],
                    )
                ],
            ),
        )

        text = snap.to_text()
        assert "context: CHROMIUM" in text
        assert '- link "Details" [ref:web_details]' in text
        assert '  - link "Details" [ref:web_details]' in text
        assert '    - text "Click"' in text

    def test_ref_map_is_derived_from_tree(self):
        node = WebSnapshotNode(
            role="button",
            name="Submit",
            ref="web_submit",
            strategies=[LocatorStrategy(by="css selector", value="#submit")],
        )
        snap = WebSnapshot.from_root(context="CHROMIUM", root=WebSnapshotNode(role="document", children=[node]))

        ref_map = snap.to_ref_map()
        assert ref_map["web_submit"].context == "CHROMIUM"
        assert ref_map["web_submit"].source_type == "web"
        assert ref_map["web_submit"].strategies[0].value == "#submit"

    def test_inputs_scope_renders_textboxes_only(self):
        snap = WebSnapshot.from_root(
            context="CHROMIUM",
            root=WebSnapshotNode(
                role="document",
                children=[
                    WebSnapshotNode(role="textbox", name="Search", ref="web_search"),
                    WebSnapshotNode(role="button", name="Submit", ref="web_submit"),
                ],
            ),
        )
        text = snap.to_text(scope="inputs")
        assert 'textbox "Search"' in text
        assert 'button "Submit"' not in text

    def test_find_text_returns_nearest_actionable_ancestor(self):
        snap = WebSnapshot.from_root(
            context="CHROMIUM",
            root=WebSnapshotNode(
                role="document",
                children=[
                    WebSnapshotNode(
                        role="link",
                        name="News article",
                        ref="web_news_article",
                        children=[WebSnapshotNode(role="heading", name="Breaking News")],
                    )
                ],
            ),
        )

        matches = snap.find_text("Breaking")
        assert len(matches) == 1
        assert matches[0].node.role == "heading"
        assert matches[0].target is not None
        assert matches[0].target.ref == "web_news_article"


class TestWebSnapshotGeneratorFromDom:
    def setup_method(self):
        self.gen = WebSnapshotGenerator()

    def test_generates_tree_with_actionable_parent_ref(self):
        tree = {
            "tag": "body",
            "role": "document",
            "name": "Example",
            "children": [
                {
                    "tag": "a",
                    "id": "",
                    "test_id": "",
                    "aria_label": "",
                    "name": "News article",
                    "value": "",
                    "type": "",
                    "href": "/news",
                    "css": 'a[href="/news"]',
                    "bounds": {},
                    "children": [
                        {"tag": "h2", "role": "heading", "name": "News article", "children": []}
                    ],
                }
            ],
        }
        snap, ref_map = self.gen.generate_from_dom(tree, "CHROMIUM", "https://example.com", "Example")

        assert snap.context == "CHROMIUM"
        assert snap.source_type == "web"
        assert snap.screen_id
        link = snap.root.children[0]
        heading = link.children[0]
        assert link.ref is not None
        assert link.ref in ref_map
        assert heading.role == "heading"
        assert heading.ref is None

    def test_dedup_suffixes(self):
        tree = {
            "tag": "body",
            "role": "document",
            "children": [
                {"tag": "a", "name": "Link", "href": "/1", "children": []},
                {"tag": "a", "name": "Link", "href": "/2", "children": []},
            ],
        }
        snap, _ = self.gen.generate_from_dom(tree, "CHROMIUM")

        refs = [node.ref for node in snap.root.children]
        assert refs[0] != refs[1]
        assert refs[1].endswith("_2")

    def test_depth_limits_tree(self):
        tree = {
            "tag": "body",
            "role": "document",
            "children": [
                {
                    "tag": "section",
                    "children": [
                        {"tag": "a", "name": "Deep Link", "href": "/deep", "children": []}
                    ],
                }
            ],
        }
        snap, ref_map = self.gen.generate_from_dom(tree, "CHROMIUM", depth=1)

        assert snap.truncated is True
        assert not ref_map
        assert "- ..." in snap.to_text()

    def test_max_nodes_limits_tree(self):
        tree = {
            "tag": "body",
            "role": "document",
            "children": [
                {"tag": "a", "id": f"el{i}", "name": f"Link {i}", "children": []}
                for i in range(20)
            ],
        }
        snap, ref_map = self.gen.generate_from_dom(tree, "CHROMIUM", max_nodes=5)
        assert snap.truncated is True
        assert len(ref_map) <= 4

    def test_css_strategy_generated(self):
        tree = {
            "tag": "body",
            "role": "document",
            "children": [
                {"tag": "button", "id": "btn1", "name": "Click", "css": "#btn1", "bounds": {}, "children": []}
            ],
        }
        _, ref_map = self.gen.generate_from_dom(tree, "CHROMIUM")
        entry = list(ref_map.values())[0]
        css_strategies = [strategy for strategy in entry.strategies if strategy.by == "css selector"]
        assert len(css_strategies) == 1
        assert css_strategies[0].value == "#btn1"

    def test_named_role_gets_xpath_strategy(self):
        tree = {
            "tag": "body",
            "children": [
                {"tag": "div", "role": "button", "name": "Close", "children": []}
            ],
        }
        _, ref_map = self.gen.generate_from_dom(tree, "CHROMIUM")
        entry = ref_map["web_btn_close"]
        assert any(strategy.by == "xpath" and "@role='button'" in strategy.value for strategy in entry.strategies)

    def test_element_states(self):
        tree = {
            "tag": "body",
            "children": [
                {
                    "tag": "input",
                    "id": "chk1",
                    "type": "checkbox",
                    "disabled": True,
                    "checked": True,
                    "children": [],
                }
            ],
        }
        snap, _ = self.gen.generate_from_dom(tree, "CHROMIUM")
        node = snap.root.children[0]
        assert "disabled" in node.state
        assert "checked" in node.state

    def test_nav_back_set_when_url(self):
        snap, _ = self.gen.generate_from_dom({"tag": "body", "children": []}, "CHROMIUM", url="https://example.com")
        assert snap.nav.get("back") is True

    def test_boxes_render_bounds(self):
        tree = {
            "tag": "body",
            "children": [
                {
                    "tag": "button",
                    "id": "btn",
                    "name": "OK",
                    "bounds": {"x1": 1, "y1": 2, "x2": 3, "y2": 4},
                    "children": [],
                }
            ],
        }
        snap, _ = self.gen.generate_from_dom(tree, "CHROMIUM")
        assert "bounds=(1, 2, 3, 4)" in snap.to_text(boxes=True)

    def test_generic_named_leaf_renders_as_text(self):
        tree = {
            "tag": "body",
            "children": [
                {"tag": "p", "name": "Plain paragraph", "children": []}
            ],
        }
        snap, _ = self.gen.generate_from_dom(tree, "CHROMIUM")
        assert '- text "Plain paragraph"' in snap.to_text()


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

        assert snap.context == "WEBVIEW_com.example"
        assert snap.source_type == "web"
        assert "- element" not in snap.to_text()
        assert all(ref.startswith("web_") for ref in ref_map)
        assert "web_submit" in ref_map

    def test_parses_data_testid(self):
        html = '<html><body><button data-testid="login-btn">Login</button></body></html>'
        _, ref_map = self.gen.generate(html, "CHROMIUM")
        assert "web_login_btn" in ref_map

    def test_parses_aria_label(self):
        html = '<html><body><div role="button" aria-label="Close">X</div></body></html>'
        _, ref_map = self.gen.generate(html, "CHROMIUM")
        assert "web_close" in ref_map


class TestRefEntryDefaults:
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
    def test_default_context_is_native(self):
        snap = AccessibilitySnapshot(screen_id="abc123")
        assert snap.context == "NATIVE_APP"
        assert snap.source_type == "native"

    def test_native_snapshot_text_has_no_context_line(self):
        snap = AccessibilitySnapshot(screen_id="abc123")
        text = snap.to_text()
        assert "context:" not in text
        assert "source:" not in text
