import pandas as pd
import streamlit as st

from etl.states import name_of
from scoring.data import spec
from scoring.score import effective_weights
from ui import charts, theme
from ui.export import csv_bytes, pdf_bytes
from ui.narrative import disclosure_lines, fmt, managerial, model_explanation, reasons, source_tag
from ui.state import describe, get_profile, run, to_profile

p = get_profile()
if not p:
    st.info("Start with your business profile.")
    if st.button("Go to the profile", type="primary"):
        st.switch_page("pages/profile.py")
    st.stop()

S = spec()
with st.spinner("Scoring states…"):
    base = run(p)
if base.message:
    theme.caveat(base.message, "No ranking")
    st.stop()

# ---- what-if weights (kept in session; start from the profile's effective weights)
eff, _, _ = effective_weights(to_profile(p))
wkey = "whatif"
whatif = st.session_state.get(wkey)
res = run(p, dimension_weights=whatif) if whatif else base
rk = res.ranking
top = rk.head(3)

theme.eyebrow("Step 3 of 3 · " + describe(p))
names = list(top.state)
st.title(f"{names[0]} leads" + (f", {names[1]} and {names[2]} follow" if len(names) >= 3 else
                                (f", {names[1]} follows" if len(names) == 2 else "")))
st.markdown("Index = weighted mean of national percentile scores (0–100) against 30 states. "
            "**It is a relative screening score, not a probability of success.** "
            + ("Weights changed in *What if* below." if whatif else ""))
d1, d2, _ = st.columns([1, 1, 3])
d1.download_button("Download CSV", csv_bytes(res, p), file_name="expansion_screening.csv", mime="text/csv",
                   use_container_width=True)
d2.download_button("PDF brief", pdf_bytes(res, p), file_name="expansion_brief.pdf", mime="application/pdf",
                   use_container_width=True)

# ---- top three cards
stab = base.stability.set_index("state_id") if base.stability is not None else None
expl, has_model = model_explanation(p["industry"])
fc_rows = res.indicators[res.indicators.indicator.str.startswith("forecast")].set_index("state_id")
cols = st.columns(len(top))
for i, (col, r) in enumerate(zip(cols, top.itertuples())):
    pos, neg = reasons(res, r.state_id, 2)
    level = r.data_confidence.split(":")[0]
    badges = theme.badge(f"Data confidence: {level}", "blue" if level == "High" else "amber")
    if stab is not None and not whatif and r.state_id in stab.index:
        badges += theme.badge(f"Same rank in {int(100 * stab.loc[r.state_id].share_same_rank)}% of ±20% re-weightings")
    if has_model:
        if r.state_id in fc_rows.index and pd.notna(fc_rows.loc[r.state_id].value):
            f = fc_rows.loc[r.state_id]
            fc = (f"<div class='ei-fc'><span class='ei-src'>Forecast · manufacturing real GSVA growth, {f.period}</span>"
                  f"<span class='ei-mono' style='font-size:18px'>{f.value:+.1f}%</span>"
                  f"<span class='ei-src'>{theme.esc(f.note)}</span></div>")
        else:
            fc = ("<div class='ei-fc'><span class='ei-src'>Forecast</span><strong>Not available</strong>"
                  "<span class='ei-src'>State accounts end before the latest year, so no forecast can be issued. "
                  "Ranking only.</span></div>")
    else:
        fc = "<div class='ei-fc'><span class='ei-src'>Forecast</span><strong>Ranking only</strong><span class='ei-src'>" \
             "No validated sector target for this industry.</span></div>"
    why = "".join(f"<div class='ei-why'><span class='p' aria-hidden='true'>+</span><span>{theme.esc(x)}</span></div>"
                  for x in pos)
    wn = "".join(f"<div class='ei-why'><span class='n' aria-hidden='true'>–</span><span>{theme.esc(x)}</span></div>"
                 for x in neg)
    gap = f"<div class='ei-caveat' style='font-size:13px'>{theme.esc(r.disclosure)}</div>" if r.disclosure else ""
    with col:
        st.markdown(
            f"<div class='ei-card{' lead' if i == 0 else ''}'>"
            f"<div style='display:flex;justify-content:space-between;gap:12px'><div><span class='ei-mono' "
            f"style='color:#4A5361;font-size:13px'>#{r.rank}</span><h2 style='margin:0;font-size:26px'>{r.state}</h2></div>"
            f"<div style='text-align:right'><span class='ei-score'>{r.score:.1f}</span>"
            f"<span class='ei-src'>index / 100</span></div></div><div style='margin-top:12px'>{badges}</div>{fc}"
            f"<p style='margin:8px 0 2px;font-size:14px;font-weight:600;color:#163A9E'>Why it ranks here</p>{why}"
            f"<p style='margin:10px 0 2px;font-size:14px;font-weight:600;color:#9A3D00'>Watch-outs</p>{wn}{gap}</div>",
            unsafe_allow_html=True)

st.write("")
# ---- map + selected state
m1, m2 = st.columns([1.25, 1], gap="large")
with m1:
    st.subheader("Pilot states on the map")
    st.plotly_chart(charts.india_map(res, charts.map_facts(res)), use_container_width=True,
                    config={"displayModeBar": False})
    st.caption("Hover a state for comparable macro indicators. Grey = not compared. Boundaries: geoBoundaries ADM1 "
               "(CC BY 4.0), not an official Survey of India map.")
with m2:
    sel = st.selectbox("Look at a state", list(rk.state_id), format_func=name_of)
    r = rk.set_index("state_id").loc[sel]
    st.markdown(f"<div style='display:flex;justify-content:space-between;align-items:baseline'><h3 style='margin:0'>"
                f"{r.state}</h3><span class='ei-score' style='font-size:28px'>{r.score:.1f}</span></div>"
                f"<span class='ei-src'>rank {int(r['rank'])} · {theme.esc(r.data_confidence)}</span>",
                unsafe_allow_html=True)
    st.plotly_chart(charts.dimension_bars(res, sel), use_container_width=True, config={"displayModeBar": False})

# ---- comparison matrix
st.subheader("Comparison matrix")
dims = list(res.dim_weights)
mat = rk[["rank", "state", "score"] + [f"dim_{d}" for d in dims]].copy()
mat.columns = ["Rank", "State", "Index"] + [f"{S['dimensions'][d]['label']} ({100 * res.dim_weights[d]:.0f}%)"
                                            for d in dims]
st.dataframe(mat.style.format({c: "{:.1f}" for c in mat.columns[2:]}, na_rep="n/a")
             .background_gradient(cmap="Blues", subset=mat.columns[3:], vmin=0, vmax=100),
             hide_index=True, use_container_width=True)
with st.expander("All indicators: raw value, period, source and percentile score"):
    t = res.indicators.copy()
    t["Value"] = [fmt(v, u) for v, u in zip(t.value, t.unit)]
    t["Source · period"] = [source_tag(x) if x.observed else "not available" for x in t.itertuples()]
    piv = t.pivot_table(index=["dimension", "label"], columns="state", values="Value", aggfunc="first")
    st.dataframe(piv[[c for c in rk.state if c in piv.columns]], use_container_width=True)
    st.dataframe(t[["state", "dimension", "label", "Value", "Source · period", "score", "quality"]]
                 .rename(columns={"label": "indicator", "score": "percentile score"}),
                 hide_index=True, use_container_width=True)

# ---- what-if and stability
a, b = st.columns(2, gap="large")
with a:
    st.subheader("What if you weight it differently?")
    st.caption("Sliders set relative weights; they are renormalised to 100%. Starting values include your priorities.")
    start = whatif or {d: round(100 * v, 1) for d, v in eff.items()}
    new = {}
    for d in dims:
        new[d] = st.slider(S["dimensions"][d]["label"], 0.0, 60.0, float(start.get(d, 0)), 0.5, key=f"w_{d}")
    c1, c2 = st.columns(2)
    if c1.button("Apply weights", type="primary", use_container_width=True):
        st.session_state[wkey] = new if sum(new.values()) > 0 else None
        st.rerun()
    if c2.button("Reset", use_container_width=True):
        st.session_state.pop(wkey, None)
        for d in dims:
            st.session_state.pop(f"w_{d}", None)
        st.rerun()
    if whatif:
        moved = base.ranking.set_index("state_id")["rank"] - rk.set_index("state_id")["rank"]
        ch = [f"{name_of(s)} {'up' if v > 0 else 'down'} {abs(int(v))}" for s, v in moved.items() if v]
        theme.note("Rank changes vs your profile weights: " + (", ".join(ch) if ch else "none"))
with b:
    st.subheader("How stable is this ranking?")
    if base.stability is not None:
        st.caption("500 random re-weightings of your profile weights, each dimension moved ±20%. "
                   "Bar = share keeping the same rank; brackets = best–worst rank seen.")
        st.plotly_chart(charts.stability_bars(base.stability), use_container_width=True,
                        config={"displayModeBar": False})
    if res.counter:
        st.markdown(f"<div class='ei-note'><strong>Could the runner-up win?</strong><br>{theme.esc(res.counter)}</div>",
                    unsafe_allow_html=True)

# ---- two-state compare
st.subheader("Compare two states")
x1, x2 = st.columns(2)
sa = x1.selectbox("First state", list(rk.state_id), index=0, format_func=name_of, key="cmp_a")
sb = x2.selectbox("Second state", [s for s in rk.state_id if s != sa], index=0, format_func=name_of, key="cmp_b")
st.plotly_chart(charts.compare_bars(res, sa, sb), use_container_width=True, config={"displayModeBar": False})
t = res.indicators
side = (t[t.state_id.isin([sa, sb])].assign(v=lambda d: [f"{fmt(v, u)} ({pp})" if o else "not available"
                                                          for v, u, pp, o in zip(d.value, d.unit, d.period, d.observed)])
        .pivot_table(index="label", columns="state", values="v", aggfunc="first"))
st.dataframe(side[[name_of(sa), name_of(sb)]], use_container_width=True)

# ---- explanation
e1, e2 = st.columns(2, gap="large")
with e1:
    st.subheader("Model explanation")
    st.markdown(expl)
with e2:
    st.subheader("Managerial interpretation")
    st.markdown(managerial(res))

notes = res.notes + disclosure_lines(res)
if notes:
    with st.expander("How your choices and the data gaps were handled"):
        for n in notes:
            st.markdown("- " + n)
theme.footer()
