"""Tests for Browser Agent construction helpers."""

from __future__ import annotations

import pytest

from agent_browser.agents import _model_settings_for_model


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
