"""OrbitGuard voice agent ("Nova"): status updates and decision support over the app's own data.

* With LLM_PROVIDER=anthropic and a key: a Claude tool-use loop. Every number comes from tools that read
  the same data the dashboard shows (alerts, event detail, maneuvers, live conjunctions, metrics).
* Otherwise, or on any error: a rule-based agent that answers the common questions from the same tools.
Replies are written for speech: short, plain sentences, no markdown.
"""
from __future__ import annotations

import json
import logging
import math
import re
from typing import Any, Callable

from fastapi import HTTPException

from orbitguard import config

log = logging.getLogger("orbitguard.agent")

AGENT_MODEL = "claude-opus-5"
MAX_TOOL_ROUNDS = 6


# --- data access (the API's own handlers, so answers match the dashboard) -----------------------

def _m():
    from api import main
    return main


def _safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except HTTPException as exc:
        return {"error": exc.detail}


def one_in(log10_risk: float | None) -> str:
    if log10_risk is None or not math.isfinite(log10_risk):
        return "unknown"
    if log10_risk <= config.RISK_FLOOR_LOG10 + 1e-9:
        return "below 1 in 3 million"
    n = 10 ** (-log10_risk)
    return f"1 in {n:,.0f}" if n < 1e6 else f"1 in {n / 1e6:.1f} million"


def _lc(label: str) -> str:
    """Lower-case a label for mid-sentence use, keeping acronyms ('Latest CDM risk' → 'latest CDM risk')."""
    return label if label[:2].isupper() else label[:1].lower() + label[1:]


def pc_words(pc: float) -> str:
    """Collision probability as speech: 1.4e-4 → '1 in 7,176'; 1.1e-7 → '1 in 9.1 million' (no model floor)."""
    if pc <= 1e-12:
        return "essentially zero"
    n = 1.0 / pc
    if n < 1e6:
        return f"1 in {n:,.0f}"
    return f"1 in {n / 1e6:.1f} million" if n < 1e9 else f"1 in {n / 1e9:.1f} billion"


DIRECTION_WORDS = {"+along": "along the direction of travel", "-along": "against the direction of travel",
                   "+radial": "away from Earth", "-radial": "toward Earth"}
OBJECT_WORDS = {"DEBRIS": "debris", "PAYLOAD": "a satellite", "ROCKET BODY": "a spent rocket body",
                "UNKNOWN": "an object of unknown type", "TBA": "an unidentified object"}


def spoken_name(name: str) -> str:
    """'ISS (ZARYA)' → 'the ISS'; drops parentheses that speech engines read out literally."""
    base = re.sub(r"\s*\(.*?\)", "", name).strip()
    return "the ISS" if base.upper() == "ISS" else base


def tool_get_alerts(limit: int = 8) -> dict:
    items = _m().alerts(source="historical", limit=max(1, min(limit, 30)), cutoff=2)
    counts: dict[str, int] = {}
    for a in _m().alerts(source="historical", limit=1000, cutoff=2):
        counts[a["decision"]] = counts.get(a["decision"], 0) + 1
    return {"counts_by_decision": counts, "ranked": [
        {"rank": i + 1, "event_id": a["event_id"], "decision": a["decision"], "p_high": a["p_high"],
         "risk_p50": one_in(a["risk_p50"]), "risk_p90": one_in(a["risk_p90"]), "miss_distance_m": round(a["miss_distance_m"]),
         "chaser_type": a["chaser_type"], "days_to_tca": a["time_to_tca_days"]} for i, a in enumerate(items)]}


def tool_get_event(event_id: str) -> dict:
    d = _safe(lambda: _m().alert_detail(event_id, 2))
    if "error" in d:
        return d
    replay = {}
    for c in d.get("available_cutoffs", []):
        r = _safe(lambda c=c: _m().alert_detail(event_id, c))
        if "error" not in r:
            replay[f"{c}_days_before"] = r["decision"]
    return {"event_id": event_id, "decision": d["decision"], "p_high_calibrated": d["p_high"],
            "risk_p10": one_in(d["risk_p10"]), "risk_p50": one_in(d["risk_p50"]), "risk_p90": one_in(d["risk_p90"]),
            "baseline_latest_cdm": one_in(d["baseline_risk"]), "miss_distance_m": round(d["miss_distance_m"]),
            "chaser_type": d["chaser_type"], "chaser_spoken": OBJECT_WORDS.get(d["chaser_type"].upper(), "an object"),
            "days_to_tca": d["time_to_tca_days"],
            "actual_outcome": one_in(d.get("true_final_risk")) if d.get("true_final_risk") is not None else None,
            "top_drivers": [{"label": _lc(s["label"]), "pushes": "up" if s["shap"] >= 0 else "down"} for s in d["shap_top"][:3]],
            "decision_by_lead_time": replay, "briefing": d["briefing"], "source": d["source"]}


def tool_get_maneuver(event_id: str) -> dict:
    m = _safe(lambda: _m().alert_maneuver(event_id))
    if "error" in m:
        return m
    r = m["recommended"]
    late = [p for p in m.get("points", []) if p["burn_lead_h"] == 6 and p["post_pc"] <= m["target_pc"]]
    late_dv = min((p["dv_ms"] for p in late), default=None)
    return {"event_id": event_id, "pre_burn_pc": pc_words(m["pre_burn_pc"]), "target_pc": pc_words(m["target_pc"]),
            "target_met": m["target_met"], "burn_needed": r["dv_ms"] > 0,
            "recommended": {"delta_v_mm_per_s": round(r["dv_ms"] * 1000, 1), "direction": DIRECTION_WORDS[r["direction"]],
                            "hours_before_tca": r["burn_lead_h"], "residual_pc": pc_words(r["post_pc"]),
                            "propellant_grams": round(r["propellant_g"], 2)},
            "cheapest_burn_if_waiting_until_6h_before_mm_per_s": round(late_dv * 1000, 1) if late_dv else None,
            "secondary_conjunction_check": m["secondary_check"].get("note") if not m["secondary_check"]["applicable"]
            else f"{len(m['secondary_check']['new_conjunctions'])} new conjunctions under 5 km after the burn",
            "note": m.get("note")}


def tool_get_live(norad: int = config.DEFAULT_PRIMARY_NORAD) -> dict:
    res = _safe(lambda: _m().live_conjunctions(norad, 72))
    if "error" in res:
        return {"status": "screening still running, try again in a few seconds"}
    conj = res["conjunctions"]
    return {"primary": spoken_name(res["primary"]["name"]), "objects_screened": (res.get("stats") or {}).get("objects"),
            "screen_seconds": res["compute_seconds"], "close_approaches_under_10km": len(conj),
            "list": [{"event_id": c.get("event_id"), "secondary": spoken_name(c["secondary"]["name"]), "type": c["secondary"]["type"],
                      "tca_utc": c["tca"], "miss_km": c["miss_km"], "rel_speed_km_s": c["rel_speed_kms"],
                      "pc_estimated": pc_words(c["pc_est"])} for c in conj[:6]],
            "caveat": "live Pc uses assumed uncertainties; catalog data has no covariance"}


def tool_get_metrics() -> dict:
    m = _m().metrics()
    b95 = m.get("baseline_at_95_recall_level", {})
    return {"test_events": m["n_test_events"], "high_risk_events": m["n_test_high_risk"],
            "model_recall": m["model"]["recall"], "model_false_alarm_rate": m["model"]["false_alarm_rate"],
            "baseline_recall": b95.get("recall"), "baseline_false_alarm_rate": b95.get("false_alarm_rate"),
            "brier_model": m["model"]["brier"], "brier_baseline": m["baseline"]["brier"],
            "kelvins_model": m["model"]["kelvins_score"], "kelvins_baseline": (m.get("baseline_clipped") or {}).get("kelvins_score"),
            "pc_engine_spearman_vs_esa": (m.get("pc_validation") or {}).get("spearman_all")}


def tool_get_space_weather() -> dict:
    return _m().space_weather()


TOOLS: dict[str, tuple[Callable[..., Any], dict]] = {
    "get_alerts": (tool_get_alerts, {
        "description": "Ranked collision alerts (ESA held-out events, decision 2 days before closest approach) with counts by decision.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "description": "how many top alerts, default 8"}}}}),
    "get_event": (tool_get_event, {
        "description": "Full detail for one event: decision, calibrated probability, risk band, top reasons, decision at each lead time, actual outcome.",
        "input_schema": {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"]}}),
    "get_maneuver": (tool_get_maneuver, {
        "description": "Cheapest avoidance burn for an event: delta-v, direction, timing, residual collision probability, propellant.",
        "input_schema": {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"]}}),
    "get_live": (tool_get_live, {
        "description": "Live close approaches under 10 km for a satellite over the next 72 hours from the CelesTrak catalog (default ISS, NORAD 25544).",
        "input_schema": {"type": "object", "properties": {"norad": {"type": "integer"}}}}),
    "get_metrics": (tool_get_metrics, {
        "description": "How good the model is on the held-out test set versus the naive baseline.",
        "input_schema": {"type": "object", "properties": {}}}),
    "get_space_weather": (tool_get_space_weather, {
        "description": "Latest solar flux F10.7 and geomagnetic Ap index, with a heuristic drag-uncertainty flag.",
        "input_schema": {"type": "object", "properties": {}}}),
}

SYSTEM = """You are Nova, the voice of OrbitGuard, a collision-avoidance assistant for satellite operators.
Your replies are spoken aloud, so:
- Use short, plain sentences. No markdown, lists, symbols or emoji. Say "one in nineteen hundred", not "1/1919".
- Keep it under about 70 words unless the operator asks for detail.
- Use only numbers returned by your tools. If you do not have a number, say so; never invent one.
When helping with a decision, give: your recommendation (maneuver, watch, or hold), the main reason, the
uncertainty, and the cheapest burn if relevant. The operator makes the final call; say so briefly when recommending a burn.
Be warm and natural with greetings, thanks and small talk: answer in a sentence, then offer something useful
(usually a status update). Greet by time of day when you know the operator's local hour. If asked what a term means
(CDM, TCA, Pc, delta-v, SHAP, calibration), explain it in one or two plain sentences.
Historical events are real ESA conjunctions from 2015 to 2019 replayed as a test set. Live data is screening only,
with assumed uncertainties. Refer to events by their number, for example "event 1568"."""


# --- Claude agent ------------------------------------------------------------------------------

def _claude_reply(message: str, history: list[dict], client_hour: int | None = None) -> tuple[str, list[str]] | None:
    if not (config.LLM_PROVIDER == "anthropic" and config.ANTHROPIC_API_KEY):
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msgs: list[dict] = [{"role": h["role"], "content": h["text"]} for h in history[-10:]
                            if h.get("role") in ("user", "assistant") and h.get("text")]
        # The API requires alternating turns that start with the user.
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        msgs.append({"role": "user", "content": message})
        tools = [{"name": n, **spec} for n, (_, spec) in TOOLS.items()]
        mentioned: list[str] = []
        for _ in range(MAX_TOOL_ROUNDS):
            system = SYSTEM + (f"\nThe operator's local hour is {client_hour}." if client_hour is not None else "")
            resp = client.with_options(timeout=45.0, max_retries=1).beta.messages.create(
                model=AGENT_MODEL, max_tokens=4000, system=system, tools=tools, messages=msgs,
                output_config={"effort": "low"},                       # voice: favour latency
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
            if resp.stop_reason == "refusal":
                return None
            msgs.append({"role": "assistant", "content": resp.content})
            calls = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not calls:
                text = " ".join(b.text for b in resp.content if b.type == "text").strip()
                return (text, mentioned) if text else None
            results = []
            for b in calls:
                fn = TOOLS.get(b.name, (None,))[0]
                try:
                    out = fn(**(b.input or {})) if fn else {"error": f"unknown tool {b.name}"}
                    if isinstance(b.input, dict) and b.input.get("event_id"):
                        mentioned.append(str(b.input["event_id"]))
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out, default=str)})
                except Exception as exc:   # tool failure goes back to the model, not to the user
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(exc), "is_error": True})
            msgs.append({"role": "user", "content": results})
        return None
    except Exception as exc:
        log.warning("Claude agent failed (%s), using rules", type(exc).__name__)
        return None


# --- rule-based agent --------------------------------------------------------------------------

ORDINALS = {"top": 0, "first": 0, "highest": 0, "worst": 0, "second": 1, "third": 2}


def _event_ref(text: str, history: list[dict]) -> str | None:
    """'event 1568' / 'EVT 1568' / '1568' / 'top alert' / 'that one' (last event mentioned)."""
    m = re.search(r"\b(?:event|evt|alert)?\s*#?\s*(\d{2,5})\b", text, re.I)
    if m:
        return m.group(1)
    for word, idx in ORDINALS.items():
        if re.search(rf"\b{word}\b", text, re.I):
            ranked = tool_get_alerts(3)["ranked"]
            return ranked[idx]["event_id"] if idx < len(ranked) else None
    if re.search(r"\b(that|this|it|same)\b", text, re.I):
        for h in reversed(history):
            m = re.search(r"event (\d{2,5})", h.get("text", ""), re.I)
            if m:
                return m.group(1)
    return None


def _status() -> tuple[str, list[str]]:
    a = tool_get_alerts(3)
    c = a["counts_by_decision"]
    top = a["ranked"][0] if a["ranked"] else None
    live = tool_get_live()
    sw = tool_get_space_weather()
    parts = [f"Here's your update. {c.get('MANEUVER', 0)} events need a maneuver, {c.get('WATCH', 0)} are on watch, "
             f"and {c.get('HOLD', 0)} are on hold."]
    if top:
        parts.append(f"Top priority is event {top['event_id']}, with {OBJECT_WORDS.get(top['chaser_type'].upper(), 'an object')}, "
                     f"about {top['days_to_tca']:.1f} days out, with final risk around {top['risk_p50']}.")
    if "close_approaches_under_10km" in live:
        n = live["close_approaches_under_10km"]
        if n:
            closest = min(live["list"], key=lambda x: x["miss_km"])
            parts.append(f"Live, {live['primary']} has {n} close approaches in the next three days. "
                         f"The closest is {closest['secondary']} at {closest['miss_km']:.1f} kilometres, low risk.")
        else:
            parts.append(f"Live, {live['primary']} has no close approaches under ten kilometres.")
    parts.append(f"Space weather is {sw['heuristic_drag_flag']}.")
    return " ".join(parts), [top["event_id"]] if top else []


def _explain(eid: str) -> tuple[str, list[str]]:
    e = tool_get_event(eid)
    if "error" in e:
        return f"I couldn't find event {eid}.", []
    drivers = " and ".join(d["label"] for d in e["top_drivers"][:2])
    replay = e["decision_by_lead_time"]
    first_flag = next((k.split("_")[0] for k, v in sorted(replay.items(), key=lambda kv: -int(kv[0].split("_")[0]))
                       if v in ("MANEUVER", "WATCH")), None)
    worst = f", up to {e['risk_p90']} in the pessimistic case" if e["risk_p90"] != e["risk_p50"] else ""
    text = (f"Event {eid} is a {e['decision'].lower()}, a close approach with {e['chaser_spoken']}. "
            f"Final risk is about {e['risk_p50']}{worst}, with a miss distance of {e['miss_distance_m']} metres. "
            f"The main reasons are {drivers}.")
    if first_flag and e["source"] == "historical":
        text += f" OrbitGuard first flagged it {first_flag} days before closest approach."
    if e.get("actual_outcome"):
        text += f" For the record, the actual outcome was {e['actual_outcome']}."
    if e["decision"] in ("MANEUVER", "WATCH"):
        text += f" Want me to check whether event {eid} needs a burn?"
    return text, [eid]


def _decide(eid: str) -> tuple[str, list[str]]:
    e = tool_get_event(eid)
    if "error" in e:
        return f"I couldn't find event {eid}.", []
    m = tool_get_maneuver(eid)
    if e["decision"] == "HOLD":
        return (f"For event {eid}, I recommend holding. Risk is about {e['risk_p50']}, below our alert threshold. "
                f"Re-assess at the next message."), [eid]
    if "error" in m:
        return (f"Event {eid} is a {e['decision'].lower()}, but I don't have burn options for it because its covariance "
                f"is incomplete. I'd keep watching and request an updated message."), [eid]
    if not m["burn_needed"]:
        return f"For event {eid}, no burn is needed. The current collision probability is already below the target.", [eid]
    r = m["recommended"]
    verb = "I recommend the burn" if e["decision"] == "MANEUVER" else "It's on watch, so I'd prepare this burn but not execute yet"
    text = (f"For event {eid}, {verb}. Pessimistic risk is {e['risk_p90']}. The cheapest option is "
            f"{r['delta_v_mm_per_s']:.1f} millimetres per second {r['direction']}, "
            f"{r['hours_before_tca']:.0f} hours before closest approach. That cuts the collision chance from {m['pre_burn_pc']} to "
            f"{r['residual_pc']}, using about {r['propellant_grams']:.1f} grams of propellant.")
    late = m["cheapest_burn_if_waiting_until_6h_before_mm_per_s"]
    if late and r["hours_before_tca"] > 6:
        text += f" Waiting until six hours out would cost about {late / max(r['delta_v_mm_per_s'], 1e-9):.0f} times the delta-v."
    text += " The final call is yours."
    return text, [eid]


def _live() -> tuple[str, list[str]]:
    live = tool_get_live()
    if "close_approaches_under_10km" not in live:
        return "Live screening is still running. Ask me again in a few seconds.", []
    n = live["close_approaches_under_10km"]
    if not n:
        return f"{live['primary'][:1].upper() + live['primary'][1:]} has no close approaches under ten kilometres in the next three days.", []
    closest = min(live["list"], key=lambda x: x["miss_km"])
    return (f"I screened {live['objects_screened']:,} objects in {live['screen_seconds']:.1f} seconds. {live['primary'][:1].upper() + live['primary'][1:]} has {n} "
            f"close approaches under ten kilometres in the next three days. The closest is {closest['secondary']} at "
            f"{closest['miss_km']:.1f} kilometres. All estimated risks are low, so no action is needed. "
            f"Remember, live risk uses assumed uncertainties."), []


def _metrics() -> tuple[str, list[str]]:
    m = tool_get_metrics()
    return (f"On {m['test_events']:,} held-out ESA events, OrbitGuard caught {m['model_recall'] * 100:.0f} percent of the "
            f"{m['high_risk_events']} high-risk ones with a {m['model_false_alarm_rate'] * 100:.0f} percent false alarm rate. "
            f"The naive baseline gets {m['baseline_recall'] * 100:.0f} percent with {m['baseline_false_alarm_rate'] * 100:.0f} percent "
            f"false alarms. We're also better calibrated, and we tie the baseline on the competition score."), []


HELP = ("You can ask me for a status update, about a specific event like event 1568, whether we should maneuver for the top alert, "
        "about live close approaches for the ISS, or how accurate the model is.")

# --- small talk ---------------------------------------------------------------------------------

OFFER_STATUS = "Would you like a status update?"
JOKES = [
    "I'd tell you a joke about orbital decay, but it would take a few years to land.",
    "Why don't satellites get lonely? They're surrounded by about twenty-six thousand tracked objects. Some of them are just a little too close.",
    "How does the space station stay so calm? It just goes with the flow. About seven point six kilometres per second of it.",
    "Space debris has excellent confidence. It's always making a close approach.",
    "I asked a satellite how it was doing. It said things were looking up. Then it remembered which way up was.",
]
GLOSSARY = {
    r"conjunctions?": "A conjunction is a predicted close approach between two objects in orbit. Operators get warned days before it happens.",
    r"cdms?|conjunction data messages?": "A CDM, or conjunction data message, is the warning an operator receives about a close approach. "
                                         "It carries the predicted miss distance, the uncertainties, and a collision probability. Several arrive per event as tracking improves.",
    r"tca|time of closest approach": "TCA means time of closest approach, the moment the two objects pass nearest to each other.",
    r"pc|poc|probability of collision|collision probability": "Pc is the probability of collision. We compute it by integrating the combined position uncertainty "
                                                              "over a disk the size of both objects. One in ten thousand or worse is the usual maneuver trigger.",
    r"delta[- ]?v|dv": "Delta-v is the change in velocity a burn gives the satellite, in metres per second. Small burns made early are far cheaper than big burns made late.",
    r"shap": "SHAP values show how much each input pushed the model's prediction up or down. I use them to explain why an alert fired.",
    r"calibrat\w*": "Calibrated means the probabilities can be taken at face value. If I say ten percent, it should happen about one time in ten.",
    r"kelvins?": "Kelvins is the European Space Agency's collision avoidance challenge. Its real conjunction data is what my model was trained and tested on.",
    r"p10|p90|band|confidence band": "The P10 to P90 band is the range I expect the final risk to fall in, eight times out of ten. P90 is the pessimistic end.",
    r"watch|hold|maneuver decision|decisions": "Maneuver means plan a burn. Watch means it's high risk but below the maneuver trigger, so keep a burn ready. Hold means no action for now.",
    r"orbitguard": "OrbitGuard is an AI co-pilot for satellite operators. It turns noisy collision warnings into calibrated decisions, explains them, and plans the cheapest avoidance burn.",
    r"sgp4": "SGP4 is the standard model for predicting where catalogued objects will be, from their published orbital elements. I use it for live screening.",
}

_GREET = r"(hi|hello|hey|hiya|howdy|yo|greetings|namaste|good (morning|afternoon|evening|day))"
_DOMAIN = re.compile(r"\b(\d{2,5}|event|evt|alert|alerts|maneuver\w*|burn\w*|should|live|iss|conjunction\w*|close approach\w*|"
                     r"status|update|brief\w*|accura\w*|metrics?|baseline|recall|weather|solar|threat|risk\w*|recommend\w*)\b", re.I)


def _time_greeting(hour: int | None) -> str:
    if hour is None:
        return "Hello"
    return "Good morning" if 5 <= hour < 12 else "Good afternoon" if 12 <= hour < 17 else "Good evening" if 17 <= hour < 22 else "Hello"


def _last_assistant(history: list[dict]) -> str:
    return next((h.get("text", "") for h in reversed(history) if h.get("role") == "assistant"), "")


def _glossary(t: str) -> str | None:
    m = re.search(r"\b(what(?:'s| is| are| does)|define|meaning of|explain|tell me what)\b(.*)", t)
    if not m:
        return None
    rest = m.group(2)
    for pat, text in GLOSSARY.items():
        if re.search(rf"\b({pat})\b", rest, re.I):
            return text
    return None


def _small_talk(t: str, history: list[dict], hour: int | None) -> tuple[str, list[str]] | None:
    """Casual conversation. Returns None when the message is really a domain question."""
    words = re.findall(r"[a-z']+", t)
    short = len(words) <= 7
    last = _last_assistant(history)

    if gl := _glossary(t):
        return gl, []
    # yes / no to something Nova just offered
    if short and re.fullmatch(r"\s*(yes|yeah|yep|sure|ok(ay)?|please|go ahead|do it|yes please|sounds good|why not)[.! ]*", t):
        if OFFER_STATUS in last or "status update?" in last:
            return _status()
        m = re.search(r"Want me to check whether event (\d+) needs a burn\?", last)
        if m:
            return _decide(m.group(1))
        return "Great. " + HELP, []
    if short and re.fullmatch(r"\s*(no|nope|nah|not now|no thanks|later)[.! ]*", t):
        return "No problem. I'll be here when you need me.", []
    if re.search(r"\b(say (that|it) again|repeat( that)?|come again|pardon|what did you say)\b", t) and last:
        return last, re.findall(r"event (\d{2,5})", last, re.I)[:1]
    if _DOMAIN.search(t):
        return None
    if re.search(rf"^\s*{_GREET}\b", t) and short:
        return f"{_time_greeting(hour)}! I'm Nova, your OrbitGuard assistant. {OFFER_STATUS}", []
    if re.search(r"\bhow (are|r) (you|u)\b|\bhow's it going\b|\bhow are things\b|\bwhat'?s up\b|\bsup\b", t):
        return f"All systems nominal, thanks for asking. I'm keeping an eye on the sky. {OFFER_STATUS}", []
    if re.search(r"\b(are you there|can you hear me|you there|testing|test)\b", t):
        return f"I'm here and listening, loud and clear. {OFFER_STATUS}", []
    if re.search(r"\b(who|what) are you\b|\byour name\b|\bintroduce yourself\b", t):
        return ("I'm Nova, the voice of OrbitGuard. I watch collision warnings for satellites, tell you which ones matter, "
                "explain why, and suggest the cheapest way to dodge. " + OFFER_STATUS), []
    if re.search(r"\bwho (made|built|created|designed) you\b|\bwho'?s your (maker|creator)\b", t):
        return ("I was built for the KLE Tech Hackfest by the OrbitGuard team, on real European Space Agency conjunction data "
                "and the live US satellite catalog."), []
    if re.search(r"\bwhat can you do\b|\bhelp\b|\bhow do (i|you) (use|work)\b", t):
        return HELP, []
    if re.search(r"\b(thanks|thank you|thx|cheers|appreciate)\b", t):
        return "You're welcome. Fly safe.", []
    if re.search(r"\b(bye|goodbye|good night|goodnight|see you|later|that's all|thats all)\b", t):
        return "Goodbye. I'll keep watching the sky.", []
    if re.search(r"\b(joke|funny|make me laugh)\b", t):
        return JOKES[len(history) % len(JOKES)], []
    if short and re.fullmatch(r"\s*(ok(ay)?|cool|great|nice|got it|alright|fine|hmm+|interesting|wow)[.! ]*", t):
        return "Anything else I can check for you?", []
    if re.search(r"\b(good job|well done|great job|nice work|awesome|amazing|you'?re (great|smart|awesome|the best|cool)|love you)\b", t):
        return "Thank you! I learned from the best. Thirteen thousand real conjunction events, to be exact.", []
    if re.search(r"\b(sorry|my bad|oops)\b", t):
        return "No worries at all.", []
    if re.search(r"\bwhat time is it\b|\bcurrent time\b|\btime now\b", t):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        return f"It's {now.strftime('%H:%M')} UTC.", []
    return None


def _greeting_prefix(t: str, hour: int | None) -> str:
    return f"{_time_greeting(hour)}! " if re.search(rf"^\s*{_GREET}\b", t) else ""


def _rules_reply(message: str, history: list[dict], hour: int | None = None) -> tuple[str, list[str]]:
    t = message.lower().strip()
    chat = _small_talk(t, history, hour)
    if chat:
        return chat
    text, ids = _domain_reply(t, history)
    return _greeting_prefix(t, hour) + text, ids


def _domain_reply(t: str, history: list[dict]) -> tuple[str, list[str]]:
    eid = _event_ref(t, history)
    if re.search(r"\b(should|maneuver\w*|manoeuvre\w*|burn\w*|avoid\w*|delta|decide|decision|recommend\w*)\b", t):
        if eid:
            return _decide(eid)
        top = tool_get_alerts(1)["ranked"]
        return _decide(top[0]["event_id"]) if top else ("There are no alerts right now.", [])
    if eid:
        return _explain(eid)
    if re.search(r"\b(live|iss|station|conjunction|close approach|right now|today)\b", t):
        return _live()
    if re.search(r"\b(accura\w*|metrics?|good|baseline|recall|false alarms?|perform\w*|trust\w*|reliab\w*)\b", t):
        return _metrics()
    if re.search(r"\b(weather|solar|flux|geomagnetic|storm)\b", t):
        sw = tool_get_space_weather()
        return (f"Solar flux is {sw['f107']:.0f} and the Ap index is {sw['ap']:.0f}, so drag uncertainty is "
                f"{sw['heuristic_drag_flag']}. That flag is a rule of thumb."), []
    if re.search(r"\b(update|status|brief\w*|summary|overview|what's happening|whats happening|situation|threat|hello|hi|hey)\b", t):
        return _status()
    if re.search(r"\b(help|what can you)\b", t):
        return HELP, []
    return "I didn't catch that. " + HELP, []


# --- entry point --------------------------------------------------------------------------------

def reply(message: str, history: list[dict] | None = None, client_hour: int | None = None) -> dict:
    history = history or []
    message = (message or "").strip()[:500]
    if not message:
        message = "Give me a status update."
    out = _claude_reply(message, history, client_hour)
    if out and out[0]:
        text, mentioned = out
        source = "claude"
    else:
        text, mentioned = _rules_reply(message, history, client_hour)
        source = "rules"
    ids = list(dict.fromkeys(mentioned)) or re.findall(r"event (\d{2,5})", text, re.I)[:1]
    return {"reply": text, "source": source, "event_ids": ids[:3]}
