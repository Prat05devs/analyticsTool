import pandas as pd
import streamlit as st

from etl.common import REP, ROOT
from scoring.data import registry, spec
from ui import theme

S = spec()
st.title("Methods and data lineage")
theme.lead("How each number gets from a government file to your screen, what the model can and cannot say, and the "
           "exact weights used. Last refresh 3 Nov 2026 · scoring weights v1.")

st.subheader("Lineage")
steps = [("01", "Raw files", "Official XLSX/HTML/PDF saved unchanged under data/raw/<source>/<vintage>/ with sha256 "
                             "in data/source_register.csv"),
         ("02", "Parse & map", "etl/ingest_*.py: fixed state alias map, units converted once, footnotes stripped"),
         ("03", "Validate", "etl/validate.py: duplicates, ±40% jumps flagged, single price base, revisions logged"),
         ("04", "Warehouse", "DuckDB: dim_state, fact_economic, fact_indicator (+ derived ratios)"),
         ("05", "Model", "features/build_panel.py + models/train.py: lag features as of release date, ridge vs "
                         "baselines"),
         ("06", "Score", "scoring/score.py: percentile vs 30 states, weights v1, your priorities")]
cols = st.columns(len(steps))
for c, (n, t, d) in zip(cols, steps):
    c.markdown(f"<div class='ei-stat'><span class='ei-mono' style='font-size:12px;color:#4A5361'>{n}</span><br>"
               f"<strong>{t}</strong><div class='l' style='font-size:13px'>{theme.esc(d)}</div></div>",
               unsafe_allow_html=True)

st.subheader("Forecast models and targets")
reg = registry()
rows = []
for ind, prof in S["industries"].items():
    key = prof.get("model_target") or ind
    r = reg.get(key, {})
    rows.append({"Industry": prof["label"], "Status": r.get("status", "not trained").replace("_", " "),
                 "Target": r.get("target", "none (ranking only)"), "Reason": r.get("reason", prof.get("target_note", ""))})
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
card = REP / "model_card_manufacturing.md"
if card.exists():
    with st.expander("Model card: manufacturing (full)"):
        st.markdown(card.read_text())

st.subheader("Default weights (v1)")
st.caption("Design defaults from the blueprint, tilted by industry. NOT learned optima. Indicators are scored as their "
           "percentile among 30 states (cost and risk reversed); missing indicators are dropped and weights "
           "renormalised, never filled; a state missing a mandatory dimension is excluded.")
w = pd.DataFrame({p["label"]: p["weights"] for p in S["industries"].values()}).T
w.columns = [S["dimensions"][c]["label"] for c in w.columns]
st.dataframe(w, use_container_width=True)
with st.expander("Indicator definitions"):
    ind = pd.DataFrame([{"code": k, "indicator": v["label"], "unit": v["unit"],
                         "direction": "higher is better" if v["direction"] > 0 else "lower is better",
                         "caveat": v.get("proxy", "")} for k, v in S["indicators"].items()])
    st.dataframe(ind, hide_index=True, use_container_width=True)

st.subheader("Eligibility matrix (7 states × 6 industries, default settings)")
em = REP / "eligibility_matrix.csv"
if em.exists():
    e = pd.read_csv(em)
    st.dataframe(e.pivot(index="state", columns="industry", values="status"), use_container_width=True)
    with st.expander("Reasons"):
        st.dataframe(e[["industry", "state", "status", "reason", "data_gaps"]], hide_index=True,
                     use_container_width=True)

st.subheader("Coverage of the state accounts panel")
img = REP / "coverage_heatmap.png"
if img.exists():
    st.image(str(img), caption="RBI HSIS 2024-25, state × fiscal year × activity (white = not published)")

st.subheader("Sources")
reg_df = pd.read_csv(ROOT / "data/source_register.csv", dtype=str).fillna("")
st.dataframe(reg_df[["dataset_id", "publisher", "url", "local_path", "sha256", "acquisition_date", "status"]],
             hide_index=True, use_container_width=True,
             column_config={"url": st.column_config.LinkColumn("url"), "sha256": st.column_config.TextColumn(width="small")})
un = REP / "unavailable_sources.csv"
if un.exists():
    st.markdown("**Not available (never estimated)**")
    for r in pd.read_csv(un).itertuples():
        st.markdown(f"- **{r.source.replace('_', ' ')}**: {r.reason}")
theme.note("Secondary pages (GST collections, minimum wages, private salary surveys) are shown only where the number "
           "was found in a saved copy of the cited page, and are labelled; they never enter a score. Ookla speed data "
           "is CC BY-NC-SA 4.0 (non-commercial): a commercial deployment needs Ookla's permission.")

st.subheader("Was this comparison useful?")
st.caption("Feedback is kept only for this browser session and is never used as ground truth for any model.")
f1, f2, _ = st.columns([1, 1, 4])
if f1.button("Yes"):
    st.session_state["feedback"] = "yes"
if f2.button("Not really"):
    st.session_state["feedback"] = "no"
if st.session_state.get("feedback"):
    st.success("Thanks, noted.")
theme.footer()
