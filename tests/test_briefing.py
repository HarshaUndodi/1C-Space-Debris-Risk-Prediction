"""Operator briefing: exactly three tagged lines; LLM output is validated and falls back to the template."""
from types import SimpleNamespace
from unittest import mock

import pytest

from orbitguard import config, decision, explain

CTX = {"event_id": "42", "decision": "MANEUVER", "time_to_tca_days": 2.1, "p_high": 0.4, "risk_p10": -6.5,
       "risk_p50": -4.9, "risk_p90": -3.9, "miss_distance_m": 226.0, "chaser_type": "DEBRIS",
       "drivers": [{"label": "Latest CDM risk", "shap": 1.6}, {"label": "Average risk so far", "shap": 0.9}],
       "maneuver": {"dv_ms": 0.12, "direction": "+along", "burn_lead_h": 24, "post_pc": 3e-7, "propellant_g": 27.8}}

GOOD = ("[ALERT] Risk about 1 in 80,000 with debris, TCA in 2.1 days.\n"
        "[DIAGNOSTIC] Driven by the latest CDM risk and the average risk so far.\n"
        "[ACTION] MANEUVER: 0.12 m/s +along burn 24 h before TCA.")


def fake_client(text=GOOD, stop="end_turn", exc=None):
    client = mock.Mock()
    create = client.with_options.return_value.messages.create
    if exc:
        create.side_effect = exc
    else:
        create.return_value = SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])
    return client


@pytest.fixture
def llm_on(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test-key")


def test_template_has_three_tagged_lines():
    lines = explain.template_briefing(CTX)
    assert [ln.split("]")[0] + "]" for ln in lines] == ["[ALERT]", "[DIAGNOSTIC]", "[ACTION]"]
    assert "debris" in lines[0] and "0.12 m/s +along" in lines[2] and "28 g" in lines[2]
    hold = explain.template_briefing({**CTX, "decision": "HOLD", "maneuver": None})
    assert hold[2] == "[ACTION] HOLD: no action, re-assess at next CDM."


def test_llm_disabled_uses_template(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "none")
    lines, src = explain.briefing(CTX, "k", cache={})
    assert src == "template" and lines == explain.template_briefing(CTX)


def test_llm_valid_output_is_used(llm_on):
    with mock.patch("anthropic.Anthropic", return_value=fake_client()):
        lines, src = explain.briefing(CTX, "k", cache={})
    assert src == "llm" and lines == GOOD.splitlines()


@pytest.mark.parametrize("text", ["just one line", GOOD.replace("[ACTION]", "[ACT]"), GOOD + "\n[EXTRA] line"])
def test_llm_malformed_output_falls_back(llm_on, text):
    with mock.patch("anthropic.Anthropic", return_value=fake_client(text=text)):
        lines, src = explain.briefing(CTX, "k", cache={})
    assert src == "template" and lines == explain.template_briefing(CTX)


def test_llm_error_or_timeout_falls_back(llm_on):
    with mock.patch("anthropic.Anthropic", return_value=fake_client(exc=TimeoutError("8 s"))):
        _, src = explain.briefing(CTX, "k", cache={})
    assert src == "template"


def test_llm_truncated_falls_back(llm_on):
    with mock.patch("anthropic.Anthropic", return_value=fake_client(stop="max_tokens")):
        _, src = explain.briefing(CTX, "k", cache={})
    assert src == "template"


def test_cache_reused_and_upgraded(llm_on):
    cache = {"k": {"lines": ["[ALERT] a", "[DIAGNOSTIC] b", "[ACTION] c"], "source": "template",
                   "ctx_hash": explain._ctx_hash(CTX)}}
    with mock.patch("anthropic.Anthropic", return_value=fake_client()) as m:
        _, src = explain.briefing(CTX, "k", cache=cache)
        assert src == "llm" and cache["k"]["source"] == "llm"   # template entry upgraded when LLM available
        explain.briefing(CTX, "k", cache=cache)
        assert m.call_count == 1                                   # LLM entry served from cache


def test_cache_invalidated_when_numbers_change(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "none")
    cache = {}
    first, _ = explain.briefing(CTX, "k", cache=cache)
    changed = {**CTX, "risk_p50": -3.2}
    second, _ = explain.briefing(changed, "k", cache=cache)
    assert first != second and second == explain.template_briefing(changed)


def test_decision_logic():
    assert decision.decide(0.5, -3.5, 0.1) == "MANEUVER"
    assert decision.decide(0.5, -5.0, 0.1) == "WATCH"
    assert decision.decide(0.05, -3.0, 0.1) == "HOLD"


def test_feature_labels_are_plain_english():
    assert explain.label("last_c_sigma_r") == "Debris radial uncertainty"
    assert explain.label("delta_t_sigma_n") == "Change in satellite cross-track uncertainty"
    assert explain.label("last_c_obs_used") == "Debris observations used"
