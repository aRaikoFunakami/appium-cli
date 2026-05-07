"""Tests for Browser Agent construction helpers."""

from __future__ import annotations

import pytest

from agent_browser.agents import _BASE_POLICY, _model_settings_for_model


class TestModelSettings:
    @pytest.mark.parametrize("model", ["gpt-5", "gpt-5.5", "gpt-5.3-codex"])
    def test_gpt_5_models_omit_temperature(self, model: str) -> None:
        settings = _model_settings_for_model(model)

        assert settings.temperature is None
        assert settings.parallel_tool_calls is False

    def test_legacy_models_keep_temperature(self) -> None:
        settings = _model_settings_for_model("gpt-4.1-mini")

        assert settings.temperature == 0.2
        assert settings.parallel_tool_calls is False


class TestBasePolicyTargetedExtraction:
    """Ensure _BASE_POLICY recommends targeted extraction over whole artifacts."""

    @pytest.mark.parametrize(
        "keyword",
        ["snapshot_search", "snapshot_refs", "web_query", "snapshot_show"],
    )
    def test_policy_mentions_targeted_extraction_tools(self, keyword: str) -> None:
        assert keyword in _BASE_POLICY

    def test_policy_does_not_default_to_whole_artifact_reading(self) -> None:
        # Should not recommend reading full compact artifacts as the default
        assert "snapshot_show compact" not in _BASE_POLICY
        assert "snapshot_show(artifact=" not in _BASE_POLICY

    def test_policy_prefers_targeted_extraction_before_scroll(self) -> None:
        # snapshot_search should appear before "scroll_down" as recovery strategy
        search_pos = _BASE_POLICY.index("snapshot_search")
        # The error handling section mentions scroll_down after targeted tools
        scroll_pos = _BASE_POLICY.index("scroll_down + snapshot")
        assert search_pos < scroll_pos
