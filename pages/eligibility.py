import pandas as pd
import streamlit as st

from etl.states import name_of
from scoring.data import registry, spec
from ui import theme
from ui.narrative import source_tag
from ui.state import describe, get_profile, run

p = get_profile()
if not p:
    st.info("Start with your business profile.")
    if st.button("Go to the profile", type="primary"):
        st.switch_page("pages/profile.py")
    st.stop()

S = spec()
prof = S["industries"][p["industry"]]
with st.spinner("Checking data coverage…"):
    res = run(p, with_stability=False)
reg = registry().get(prof.get("model_target") or "", {})
validated = reg.get("status") == "validated"

theme.eyebrow("Step 2 of 3 · " + describe(p))
compared = [s for s in p["states"] if not (p.get("exclude_current") and s == p.get("current_state"))]
n_ok = len(res.ranking)
st.title(f"{n_ok} of {len(compared)} states can be compared")
st.markdown(f"For {prof['label'].lower()}, each state needs at least one observed official indicator in: "
            f"**{', '.join(S['dimensions'][d]['label'].lower() for d in prof['mandatory_dimensions'])}**. "
            "Nothing is filled in where data are missing.")

if res.message:
    theme.caveat(res.message, "No ranking can be produced")
    for r in res.excluded.itertuples():
        st.markdown(f"- **{r.state}**: {r.reason}")
    st.stop()

# status per state
rows = []
t = res.indicators
for sid in compared:
    if sid in set(res.excluded.state_id):
        rows.append((sid, "Excluded", res.excluded.set_index("state_id").reason[sid]))
        continue
    has_fc = validated and t[(t.state_id == sid) & (t.indicator.str.startswith("forecast")) & t.score.notna()].size > 0
    if has_fc:
        rows.append((sid, "Forecast + ranking", f"validated {prof['model_target']} model"))
    elif validated:
        last = t[(t.state_id == sid) & (t.indicator == "momentum_manufacturing")].period
        rows.append((sid, "Ranking only", f"state accounts end in {last.iloc[0] if len(last) else 'an earlier year'}, "
                                           f"so no {reg.get('forecast_fy')} forecast can be issued"))
    else:
        rows.append((sid, "Ranking only", reg.get("reason") or prof.get("target_note", "no defensible sector target")))
status = pd.DataFrame(rows, columns=["state_id", "status", "reason"])

c = st.columns(3)
for col, (lab, kind) in zip(c, [("Forecast + ranking", "blue"), ("Ranking only", "grey"), ("Excluded", "amber")]):
    sub = status[status.status == lab]
    with col:
        theme.stat(str(len(sub)), lab + (": " + ", ".join(name_of(s) for s in sub.state_id) if len(sub) else ""))

gaps = [f"{r.state}: {r.disclosure}" for r in res.ranking.itertuples() if r.disclosure]
if gaps:
    theme.caveat(" · ".join(gaps), f"{len(gaps)} gap(s) disclosed, not filled")
if not validated and prof.get("model_target"):
    theme.note("Forecast unavailable: " + reg.get("reason", "model not validated") + ".")

st.subheader("Indicator coverage")
dims = list(prof["indicators"])
cov = []
for sid in [s for s in compared if s not in set(res.excluded.state_id)] + list(res.excluded.state_id):
    g = t[t.state_id == sid]
    row = {"State": name_of(sid), "Status": status.set_index("state_id").status.get(sid, "")}
    for d in dims:
        gd = g[g.dimension == d]
        row[S["dimensions"][d]["label"]] = f"{int(gd.score.notna().sum())}/{len(gd)}"
    per = g[g.indicator.isin(["momentum_manufacturing", "momentum_services", "momentum_gsva_total"])].period
    row["Latest state accounts"] = per.max() if len(per) else ""
    cov.append(row)
cov = pd.DataFrame(cov)


def _amber(v):
    if isinstance(v, str) and "/" in v:
        a, b = v.split("/")
        return "color:#8A5A00;font-weight:600" if a != b else ""
    return ""


st.dataframe(cov.style.map(_amber), hide_index=True, use_container_width=True)
st.caption("observed / indicators in the profile. Amber = an indicator is not published for that state; weights within "
           "the dimension are renormalised over what is observed.")

with st.expander("Why each state has this status"):
    for r in status.itertuples():
        st.markdown(f"- **{name_of(r.state_id)}** · {r.status}: {r.reason}")

st.subheader("Source vintages used")
v = (t[t.observed].assign(src=[source_tag(r) for r in t[t.observed].itertuples()])
     .groupby("label").agg(source=("src", lambda s: ", ".join(sorted(set(x.split(" · ")[0] for x in s)))),
                           periods=("period", lambda s: " to ".join(sorted({str(x) for x in s})[::max(1, len(set(s)) - 1)]))))
st.dataframe(v.reset_index().rename(columns={"label": "Indicator", "source": "Source", "periods": "Period(s)"}),
             hide_index=True, use_container_width=True)

b1, b2 = st.columns([1, 4])
if b1.button("See the ranking", type="primary", use_container_width=True):
    st.switch_page("pages/results.py")
if b2.button("Edit profile"):
    st.switch_page("pages/profile.py")
theme.footer()
