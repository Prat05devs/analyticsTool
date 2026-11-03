"""Model frame for the manufacturing growth target (blueprint 6.1-6.2).

    python -m features.build_panel

Target   g(s, t+1) = 100 * (Y(s, t+1) / Y(s, t) - 1),  Y = real manufacturing GSVA (RBI T34, 2011-12 prices)
Origin   FY t; forecast date = estimated first release of FY t state accounts (Dec of the calendar year FY t ends
         in + 9 months, see etl.ingest_rbi_hsis.first_pub_est). Every feature is joined AS OF that date:
         an indicator observation enters only if its first_pub_est <= forecast date (rule 7).
Panel    national: the 28 states + Delhi + J&K (scoring.data.reference_ids). UTs with gaps are left out.
         J&K 2019-20 (geography break) is never used as a target or as a lag.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from etl.common import CUR, fy_label, fy_start, write_parquet
from scoring.data import reference_ids

TARGET = "manufacturing"
GEO_BREAKS = {("JK", "2019-20")}

FEATURE_GROUPS = {
    "macro": ["g_lag1", "g_lag2", "g_mean3", "g_vol", "gsva_g_lag1", "log_pc_nsdp", "mfg_share", "nat_g_lag1"],
    "business": ["asi_workers_g", "asi_factories_g", "credit_industry_g"],
    "infrastructure": ["power_shortage_pct", "power_avail_pc_g"],
}


def growth_table(econ: pd.DataFrame, act: str) -> pd.DataFrame:
    e = econ[econ.activity_code == act].sort_values(["state_id", "fy"]).copy()
    e["g"] = e.groupby("state_id").value_rs_lakh.pct_change(fill_method=None) * 100
    # a growth rate that spans a geography break is not comparable
    e.loc[[(s, f) in GEO_BREAKS for s, f in zip(e.state_id, e.fy)], "g"] = np.nan
    return e


def asof(ind: pd.DataFrame, code: str, sid: str, date: pd.Timestamp, n: int = 1) -> pd.DataFrame:
    """Latest n observations of `code` for a state that had been published by `date`."""
    f = ind[(ind.feature_code == code) & (ind.state_id == sid) & ind.first_pub_est.notna() & (ind.first_pub_est <= date)]
    return f.sort_values("period").tail(n)


def _yoy(ind, code, sid, date):
    obs = asof(ind, code, sid, date, 2)
    if len(obs) < 2 or obs.value.iloc[0] <= 0:
        return np.nan, pd.NaT
    return 100 * (obs.value.iloc[1] / obs.value.iloc[0] - 1), obs.first_pub_est.max()


def build() -> pd.DataFrame:
    econ = pd.read_parquet(CUR / "fact_economic.parquet")
    ind = pd.read_parquet(CUR / "fact_indicator.parquet")
    ind["first_pub_est"] = pd.to_datetime(ind.first_pub_est)
    states = reference_ids()
    m = growth_table(econ, TARGET)
    tot = growth_table(econ, "gsva_total")
    mw = m.pivot(index="state_id", columns="fy", values="g")
    vw = m.pivot(index="state_id", columns="fy", values="value_rs_lakh")
    pub = m.pivot(index="state_id", columns="fy", values="first_pub_est")
    tw = tot.pivot(index="state_id", columns="fy", values="g")
    totv = tot.pivot(index="state_id", columns="fy", values="value_rs_lakh")
    pc = ind[ind.feature_code == "per_capita_nsdp_real"].pivot_table(index="state_id", columns="period", values="value")
    fys = sorted(m.fy.unique())
    rows = []
    for t in fys[1:]:
        t1 = fy_label(fy_start(t) + 1)
        tm1, tm2 = fy_label(fy_start(t) - 1), fy_label(fy_start(t) - 2)
        nat = mw.loc[mw.index.isin(states), t].mean() if t in mw else np.nan  # cross-state mean, same release
        for sid in states:
            if sid not in mw.index or t not in mw.columns:
                continue
            date = pub.loc[sid, t] if pd.notna(pub.loc[sid, t]) else pd.Timestamp(f"{fy_start(t) + 1}-12-15")
            hist = mw.loc[sid, [c for c in fys if c <= t]].dropna()
            target = mw.loc[sid, t1] if t1 in mw.columns else np.nan
            row = {
                "state_id": sid, "origin_fy": t, "target_fy": t1, "forecast_date": date,
                "target": target,
                "y_t": vw.loc[sid, t], "g_lag1": mw.loc[sid, t],
                "g_lag2": mw.loc[sid, tm1] if tm1 in mw.columns else np.nan,
                "g_mean3": mw.loc[sid, [c for c in (tm2, tm1, t) if c in mw.columns]].mean(skipna=False)
                if all(c in mw.columns for c in (tm2, tm1, t)) else np.nan,
                "g_vol": hist.std() if len(hist) >= 3 else np.nan,
                "gsva_g_lag1": tw.loc[sid, t] if sid in tw.index else np.nan,
                "log_pc_nsdp": np.log(pc.loc[sid, t]) if sid in pc.index and t in pc.columns and pd.notna(pc.loc[sid, t]) else np.nan,
                "mfg_share": 100 * vw.loc[sid, t] / totv.loc[sid, t] if pd.notna(totv.loc[sid, t]) else np.nan,
                "nat_g_lag1": nat,
            }
            latest_pub = [pub.loc[sid, t]]
            for code, name in [("asi_workers", "asi_workers_g"), ("asi_factories", "asi_factories_g"),
                               ("credit_industry_scb", "credit_industry_g"),
                               ("per_capita_power_availability", "power_avail_pc_g")]:
                row[name], p = _yoy(ind, code, sid, date)
                latest_pub.append(p)
            ps = asof(ind, "power_shortage_pct", sid, date)
            row["power_shortage_pct"] = ps.value.iloc[-1] if len(ps) else np.nan
            latest_pub.append(ps.first_pub_est.max() if len(ps) else pd.NaT)
            row["max_feature_pub"] = max([p for p in latest_pub if pd.notna(p)], default=pd.NaT)
            row["covid_target"] = t1 in {"2020-21", "2021-22"}
            rows.append(row)
    frame = pd.DataFrame(rows)
    frame = frame[frame.g_lag1.notna()]
    assert (frame.max_feature_pub <= frame.forecast_date).all(), "look-ahead leakage in features"
    return frame


def main():
    f = build()
    write_parquet(f, "model_frame_manufacturing")
    lab = f.dropna(subset=["target"])
    print(f"model frame: {len(f)} state-origin rows, {len(lab)} with target, {f.state_id.nunique()} states, "
          f"origins {f.origin_fy.min()}..{f.origin_fy.max()}")
    print(f.groupby("origin_fy")[["target", "g_lag2", "g_mean3", "g_vol", "asi_workers_g", "power_shortage_pct"]]
          .count().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
