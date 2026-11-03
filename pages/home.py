import streamlit as st

from scoring.data import registry
from ui import theme

theme.eyebrow("State screening for established businesses")
left, right = st.columns([1.15, 1], gap="large")
with left:
    st.markdown("<h1 style='font-size:clamp(40px,5vw,60px);line-height:1.03;margin:0 0 12px'>"
                "Where should your business expand next?</h1>", unsafe_allow_html=True)
    theme.lead("Compare evidence-backed state expansion opportunities using public economic data. "
               "Every number shows its source table and period.")
    c1, c2 = st.columns([1, 1])
    if c1.button("Start an analysis", type="primary", use_container_width=True):
        st.switch_page("pages/profile.py")
    if c2.button("How the index works", use_container_width=True):
        st.switch_page("pages/methods.py")
with right:
    st.markdown(
        "<div class='ei-card'><p class='ei-eyebrow'>What you get</p>"
        "<p style='margin:0 0 10px'><strong>Top three states</strong> with a relative 0–100 index, the dimensions "
        "behind it and evidence-linked reasons for and against.</p>"
        "<p style='margin:0 0 10px'><strong>Source beside every number</strong>: table, period, and a raw "
        "government file with a recorded checksum.</p>"
        "<p style='margin:0'><strong>How sure the ranking is</strong>: stability under ±20% weight changes, what "
        "would make the runner-up win, and which data are missing or old.</p></div>", unsafe_allow_html=True)

st.write("")
cols = st.columns(4)
facts = [("7", "pilot states: Maharashtra, Gujarat, Karnataka, Tamil Nadu, Telangana, Uttar Pradesh, Rajasthan"),
         ("6", "industries: retail, manufacturing, IT & professional services, logistics, healthcare, hospitality"),
         ("FY 2024-25", "latest state accounts (RBI Handbook, 11 Dec 2025, 2011-12 prices)"),
         ("30", "states in the frozen national reference each indicator is ranked against")]
for c, (v, l) in zip(cols, facts):
    with c:
        theme.stat(v, l)

st.write("")
a, b = st.columns(2, gap="large")
with a:
    st.subheader("Forecast status by industry")
    reg = registry()
    m = reg.get("manufacturing", {})
    if m.get("status") == "validated":
        st.markdown(theme.badge("Manufacturing: forecast validated", "blue"), unsafe_allow_html=True)
        st.markdown(f"Next-year real manufacturing GSVA growth. Validation MAE {m['validation_mae']['model']:.1f} pp "
                    f"vs {m['validation_mae'][m['best_baseline']]:.1f} pp for the best baseline; hold-out error "
                    f"{m['holdout_mae']['model']:.1f} pp.")
    else:
        st.markdown(theme.badge("Manufacturing: ranking only", "grey"), unsafe_allow_html=True)
        st.markdown(m.get("reason", "Model not trained yet."))
    st.markdown(theme.badge("Retail · IT · Logistics · Healthcare · Hospitality: ranking only", "grey"),
                unsafe_allow_html=True)
    st.markdown("No consistent state-level sector output series exists, so no forecast is shown for these.")
with b:
    st.subheader("What this is not")
    theme.caveat("Not a probability of commercial success, profit or survival. Not site or parcel selection: "
                 "everything is measured at state level. Not financial advice. Weights are documented design "
                 "defaults, not learned optima, and you can change them.")
theme.footer()
