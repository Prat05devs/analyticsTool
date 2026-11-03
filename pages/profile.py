import streamlit as st

from etl.states import name_of
from scoring.data import PILOT_IDS, spec
from scoring.score import effective_weights
from ui import theme
from ui.state import DEMOS, NEED_LABELS, OTHER_STATE, PRIORITY_LABELS, get_profile, industries, set_profile, to_profile

S = spec()
cur = get_profile() or {"industry": "manufacturing", "current_state": "UP", "capital_rs_crore": 8.0,
                        "priorities": [], "needs": [], "exclude_current": False, "states": list(PILOT_IDS)}

theme.eyebrow("Step 1 of 3")
st.title("Describe the expansion")
st.markdown("Five questions. We do not ask for revenue, company documents or anything that identifies you.")

with st.container(border=True):
    st.markdown("**Try a worked example**")
    d1, d2 = st.columns(2)
    for col, (key, demo) in zip([d1, d2], DEMOS.items()):
        with col:
            st.markdown(f"**{demo['title']}**  \n<span style='color:#4A5361;font-size:14px'>{demo['blurb']}</span>",
                        unsafe_allow_html=True)
            if st.button("Run this example", key=f"demo_{key}", use_container_width=True):
                set_profile({**demo["profile"], "states": list(PILOT_IDS)})
                st.switch_page("pages/eligibility.py")

form, side = st.columns([1.6, 1], gap="large")
with form:
    ind_keys = list(industries())
    with st.container(border=True):
        industry = st.radio("1 · Industry", ind_keys, index=ind_keys.index(cur["industry"]),
                            format_func=lambda k: industries()[k], horizontal=True)
        tgt = S["industries"][industry].get("model_target")
        st.caption("A next-year growth forecast is available for this industry if the model passes validation."
                   if tgt else f"Ranking only: {S['industries'][industry].get('target_note', '')}")

    with st.container(border=True):
        st.markdown("**2 · Where you are now**")
        c1, c2 = st.columns(2)
        opts = list(PILOT_IDS) + [OTHER_STATE]
        current = c1.selectbox("Current state", opts, index=opts.index(cur.get("current_state") or OTHER_STATE),
                               format_func=lambda s: s if s == OTHER_STATE else name_of(s))
        capital = c2.number_input("Investment capital (₹ crore)", min_value=0.0, step=0.5,
                                  value=float(cur.get("capital_rs_crore") or 0.0),
                                  help="Context only: no auditable state-level capex or rent data exists, "
                                       "so the budget does not change scores.")
        excl = st.checkbox("Leave my current state out of the ranking", value=bool(cur.get("exclude_current")),
                           disabled=current == OTHER_STATE)

    with st.container(border=True):
        pri = st.multiselect("3 · Priorities (up to 3)", list(PRIORITY_LABELS), default=cur.get("priorities", []),
                             format_func=PRIORITY_LABELS.get, max_selections=3,
                             help="Each chosen priority multiplies its dimension weight by 1.6, then all weights are "
                                  "renormalised.")
        if "policy" in pri:
            theme.caveat(S["priorities"]["policy_note"])

    with st.container(border=True):
        needs = st.multiselect("4 · Operational needs (optional)", list(NEED_LABELS), default=cur.get("needs", []),
                               format_func=NEED_LABELS.get)

    with st.container(border=True):
        states = st.multiselect("5 · States to compare", list(PILOT_IDS), default=cur.get("states") or list(PILOT_IDS),
                                format_func=name_of)
        st.caption("Scores are ranked against a frozen national reference, so removing a state does not change the "
                   "others' scores.")

profile = {"industry": industry, "current_state": current, "capital_rs_crore": capital or None, "priorities": pri,
           "needs": needs, "exclude_current": excl and current != OTHER_STATE, "states": states}

with side:
    with st.container(border=True):
        st.subheader("Weights you will use")
        st.caption(f"{industries()[industry]} defaults (v1), adjusted by your choices. Design defaults, not learned "
                   "optima.")
        w, _, notes = effective_weights(to_profile(profile))
        base = S["industries"][industry]["weights"]
        tot = sum(base.values())
        for d, v in w.items():
            changed = abs(v - base[d] / tot) > 1e-6
            st.markdown(f"<div style='display:flex;justify-content:space-between;font-size:14px'>"
                        f"<span>{S['dimensions'][d]['label']}</span><span class='ei-mono'>{100 * v:.1f}%</span></div>"
                        f"<div style='height:8px;background:#E6E9EF;border-radius:4px;margin:4px 0 10px'>"
                        f"<div style='width:{100 * v:.1f}%;height:8px;border-radius:4px;"
                        f"background:{'#1F4FD1' if changed else '#5B6472'}'></div></div>", unsafe_allow_html=True)
        for n in notes:
            st.caption("· " + n)

if len(states) < 2:
    theme.caveat("Choose at least two states: a ranking needs something to compare.")
if st.button("Check data coverage", type="primary", disabled=len(states) < 2):
    set_profile(profile)
    st.switch_page("pages/eligibility.py")
theme.footer()
