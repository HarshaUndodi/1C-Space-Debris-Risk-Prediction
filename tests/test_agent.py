"""Voice agent: rule-based answers are grounded in the app's data; the Claude loop runs tools and falls back safely."""
from types import SimpleNamespace
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import agent, main, schemas
from orbitguard import config


@pytest.fixture
def client(monkeypatch):
    if not config.DEMO_EVENTS_PATH.exists():
        pytest.skip("demo events not built")
    monkeypatch.setattr(main, "store", main.Store("real"))
    monkeypatch.setattr(config, "LLM_PROVIDER", "none")
    with TestClient(main.app) as c:
        yield c


def ask(client, message, history=None):
    r = client.post("/api/agent", json={"message": message, "history": history or []})
    assert r.status_code == 200, r.text
    return schemas.AgentReply.model_validate(r.json())


def test_status_update_mentions_counts_and_top_event(client):
    top = client.get("/api/alerts?limit=1").json()[0]["event_id"]
    a = ask(client, "Give me a status update")
    assert a.source == "rules" and "need a maneuver" in a.reply and f"event {top}" in a.reply
    assert top in a.event_ids


def test_explain_named_event(client):
    a = ask(client, "Tell me about event 1568")
    assert "Event 1568" in a.reply and "actual outcome" in a.reply and a.event_ids == ["1568"]


def test_decision_support_gives_burn_and_defers_to_operator(client):
    a = ask(client, "Should we maneuver for event 1568?")
    assert "millimetres per second" in a.reply and "grams of propellant" in a.reply
    assert a.reply.endswith("The final call is yours.")


def test_ordinal_and_followup_references(client):
    top = client.get("/api/alerts?limit=1").json()[0]["event_id"]
    a = ask(client, "what about the top alert")
    assert f"Event {top}" in a.reply
    b = ask(client, "should we burn for that one", history=[{"role": "assistant", "text": a.reply}])
    assert f"event {top}" in b.reply


def test_live_and_metrics_and_help(client):
    live = ask(client, "any live conjunctions for the ISS?").reply
    assert "kilometres" in live or "screening" in live
    assert "percent" in ask(client, "how accurate is the model").reply
    assert "percent" in ask(client, "can we trust it").reply
    assert "status update" in ask(client, "blorp").reply


def test_spoken_style_has_no_markdown(client):
    for q in ("status", "event 1568", "should we maneuver for event 1568", "how good is it"):
        text = ask(client, q).reply
        assert not any(sym in text for sym in ("**", "#", "- ", "`"))


def test_claude_loop_runs_tools_then_answers(monkeypatch, client):
    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test")
    first = SimpleNamespace(stop_reason="tool_use", content=[
        SimpleNamespace(type="tool_use", id="t1", name="get_event", input={"event_id": "1568"})])
    final = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Event 1568 needs a burn.")])
    fake = mock.Mock()
    create = fake.with_options.return_value.beta.messages.create
    create.side_effect = [first, final]
    with mock.patch("anthropic.Anthropic", return_value=fake):
        a = ask(client, "what should we do about 1568")
    assert a.source == "claude" and a.reply == "Event 1568 needs a burn." and a.event_ids == ["1568"]
    msgs = create.call_args_list[1].kwargs["messages"]
    results = [c for m in msgs if m["role"] == "user" and isinstance(m["content"], list)
               for c in m["content"] if isinstance(c, dict) and c.get("type") == "tool_result"]
    assert results and "decision_by_lead_time" in results[0]["content"]   # real tool output went back to the model
    kw = create.call_args_list[0].kwargs
    assert kw["model"] == "claude-opus-5" and kw["fallbacks"] == "default"


def test_claude_failure_falls_back_to_rules(monkeypatch, client):
    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test")
    fake = mock.Mock()
    fake.with_options.return_value.beta.messages.create.side_effect = TimeoutError()
    with mock.patch("anthropic.Anthropic", return_value=fake):
        a = ask(client, "status update")
    assert a.source == "rules" and "need a maneuver" in a.reply


def chat(client, message, history=None, hour=None):
    r = client.post("/api/agent", json={"message": message, "history": history or [], "client_hour": hour})
    assert r.status_code == 200, r.text
    return r.json()["reply"]


@pytest.mark.parametrize("hour,greeting", [(8, "Good morning"), (14, "Good afternoon"), (19, "Good evening"), (2, "Hello"), (None, "Hello")])
def test_time_aware_greeting(client, hour, greeting):
    a = chat(client, "Hi Nova", hour=hour)
    assert a.startswith(f"{greeting}! I'm Nova") and "status update?" in a


@pytest.mark.parametrize("msg,expect", [
    ("hello", "I'm Nova"), ("good evening", "I'm Nova"), ("how are you?", "All systems nominal"),
    ("are you there", "listening"), ("who are you", "voice of OrbitGuard"), ("who built you", "Hackfest"),
    ("thank you so much", "welcome"), ("bye nova", "Goodbye"), ("tell me a joke", ""), ("great job", "Thank you"),
    ("sorry", "No worries"), ("what time is it", "UTC"), ("cool", "Anything else"), ("what can you do", "status update"),
])
def test_small_talk(client, msg, expect):
    a = chat(client, msg)
    assert expect in a and "I didn't catch that" not in a


@pytest.mark.parametrize("msg,expect", [
    ("what is a CDM", "conjunction data message"), ("what does TCA mean", "closest approach"),
    ("explain delta-v", "change in velocity"), ("what's SHAP", "pushed the model"), ("what is calibration", "face value"),
    ("what is OrbitGuard", "co-pilot"),
])
def test_glossary(client, msg, expect):
    assert expect in chat(client, msg)


def test_greeting_does_not_swallow_a_real_question(client):
    a = chat(client, "hey nova, any live conjunctions for the ISS?", hour=10)
    assert a.startswith("Good morning! ") and ("kilometres" in a or "screening" in a)
    b = chat(client, "hi, should we maneuver for event 1568?")
    assert "millimetres per second" in b


def test_yes_accepts_the_offer(client):
    greet = chat(client, "hello")
    status = chat(client, "yes please", history=[{"role": "user", "text": "hello"}, {"role": "assistant", "text": greet}])
    assert "need a maneuver" in status
    explain = chat(client, "tell me about event 1568")
    assert "Want me to check whether event 1568 needs a burn?" in explain
    burn = chat(client, "sure", history=[{"role": "assistant", "text": explain}])
    assert "millimetres per second" in burn


def test_no_and_repeat(client):
    assert "No problem" in chat(client, "no thanks")
    last = "Event 1568 is a maneuver."
    assert chat(client, "say that again", history=[{"role": "assistant", "text": last}]) == last


def test_spoken_formatting():
    assert agent.one_in(-3.283) == "1 in 1,919"
    assert agent.one_in(-6.5) == "below 1 in 3 million"
    assert agent.pc_words(1.4e-4) == "1 in 7,143"
    assert agent.pc_words(1.1e-7) == "1 in 9.1 million"
    assert agent.spoken_name("ISS (ZARYA)") == "the ISS" and agent.spoken_name("CARTOSAT-3") == "CARTOSAT-3"
    assert agent._lc("Latest CDM risk") == "latest CDM risk"


def test_no_doubled_articles(client):
    for q in ("status", "live ISS"):
        assert "the the" not in ask(client, q).reply.lower()
