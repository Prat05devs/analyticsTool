"""Session state: the business profile, demo scenarios and cached scoring."""
from __future__ import annotations

import streamlit as st

from etl.states import name_of
from scoring.data import PILOT_IDS, spec
from scoring.score import Profile, score

PRIORITY_LABELS = {"demand": "Market demand", "infrastructure": "Reliable infrastructure", "labour": "Labour",
                   "cost": "Operating cost", "growth": "Growth", "policy": "Policy"}
NEED_LABELS = {"power_intensive": "Power-intensive", "digital_first": "Digital-first",
               "logistics_heavy": "Logistics-heavy", "skilled_labour": "Skilled labour"}
OTHER_STATE = "Other state"

DEMOS = {
    "up_manufacturer": {
        "title": "UP manufacturer, ₹8 crore",
        "blurb": "Manufacturing firm in Uttar Pradesh; priorities: power, logistics, available labour.",
        "profile": dict(industry="manufacturing", current_state="UP", capital_rs_crore=8.0,
                        priorities=["infrastructure", "labour"], needs=["power_intensive", "logistics_heavy"],
                        exclude_current=False),
    },
    "it_services_mh": {
        "title": "IT services firm from Maharashtra, ₹3 crore",
        "blurb": "Professional-services business opening a second delivery centre; priorities: labour, cost, "
                 "connectivity.",
        "profile": dict(industry="it_services", current_state="MH", capital_rs_crore=3.0,
                        priorities=["labour", "cost", "infrastructure"], needs=["digital_first", "skilled_labour"],
                        exclude_current=True),
    },
}


def industries() -> dict:
    return {k: v["label"] for k, v in spec()["industries"].items()}


def get_profile() -> dict | None:
    return st.session_state.get("profile")


def set_profile(p: dict):
    st.session_state["profile"] = p
    st.session_state.pop("whatif", None)


def to_profile(p: dict, dimension_weights: dict | None = None) -> Profile:
    states = p.get("states") or list(PILOT_IDS)
    return Profile(industry=p["industry"], priorities=list(p.get("priorities", [])), needs=list(p.get("needs", [])),
                   states=list(states), current_state=p.get("current_state"),
                   exclude_current=bool(p.get("exclude_current")), capital_rs_crore=p.get("capital_rs_crore"),
                   dimension_weights=dimension_weights)


@st.cache_data(show_spinner=False)
def _score_cached(key: tuple, with_stability: bool):
    p = dict(key[0])
    p["priorities"], p["needs"], p["states"] = list(key[1]), list(key[2]), list(key[3])
    dw = dict(key[4]) if key[4] else None
    return score(to_profile(p, dw), with_stability=with_stability)


def run(p: dict, dimension_weights: dict | None = None, with_stability: bool = True):
    base = tuple(sorted((k, v) for k, v in p.items() if k not in {"priorities", "needs", "states"}))
    key = (base, tuple(p.get("priorities", [])), tuple(p.get("needs", [])),
           tuple(p.get("states") or PILOT_IDS), tuple(sorted(dimension_weights.items())) if dimension_weights else None)
    return _score_cached(key, with_stability)


def describe(p: dict) -> str:
    parts = [industries()[p["industry"]]]
    cs = p.get("current_state")
    parts.append(f"from {name_of(cs)}" if cs and cs != OTHER_STATE else "from another state")
    if p.get("capital_rs_crore") is not None:
        parts.append(f"₹{p['capital_rs_crore']:g} crore")
    if p.get("needs"):
        parts.append(", ".join(NEED_LABELS[n].lower() for n in p["needs"]))
    return " · ".join(parts)
