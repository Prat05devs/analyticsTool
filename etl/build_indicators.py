"""Build fact_indicator (all sources + derived indicators) and the DuckDB warehouse.

    python -m etl.build_indicators

Derived indicators are computed only from curated official values and carry every component's raw file
and sha256 (semicolon-separated) so they trace back to data/raw. Period matching is explicit:
  * end-March stock for year Y  <->  FY (Y-1)-Y population;
  * if a state's population is not published for that FY, the latest earlier FY is used and the note says so
    (Gujarat: state accounts end in 2022-23).
Population is not published in the handbook; it is derived as NSDP (Rs lakh) x 1e5 / per-capita NSDP (Rs),
which is how per-capita NSDP is defined.
"""
from __future__ import annotations

import sys

import duckdb
import numpy as np
import pandas as pd

from etl.common import CUR, FACT_INDICATOR_COLS, WAREHOUSE, fy_label, fy_start, write_parquet
from etl.states import dim_state

SOURCES = ["rbi", "hces", "trai", "secondary"]


def load_sources() -> pd.DataFrame:
    frames = [pd.read_parquet(CUR / f"fact_indicator_{s}.parquet") for s in SOURCES if (CUR / f"fact_indicator_{s}.parquet").exists()]
    return pd.concat(frames, ignore_index=True)


def _join_files(*rows) -> tuple[str, str]:
    files, shas = [], []
    for r in rows:
        for f, s in zip(str(r["source_file"]).split(";"), str(r["sha256"]).split(";")):
            if f not in files:
                files.append(f)
                shas.append(s)
    return ";".join(files), ";".join(shas)


def _row(sid, period, ptype, code, value, unit, comps, note, first_pub=pd.NaT, table="derived"):
    f, s = _join_files(*comps)
    return {"state_id": sid, "period": period, "period_type": ptype, "feature_code": code, "value": value,
            "unit": unit, "source_id": "derived", "table_id": table, "published_at": max(c["published_at"] for c in comps),
            "first_pub_est": first_pub, "source_file": f, "sha256": s, "quality": "derived", "note": note}


def derive(ind: pd.DataFrame, econ: pd.DataFrame) -> pd.DataFrame:
    out = []
    key = ind.set_index(["state_id", "feature_code", "period"]).sort_index()
    ekey = econ.set_index(["state_id", "activity_code", "fy"]).sort_index()

    def get(sid, code, period):
        try:
            r = key.loc[(sid, code, period)]
            return None if pd.isna(r["value"]) else r
        except KeyError:
            return None

    def eget(sid, act, fy):
        try:
            r = ekey.loc[(sid, act, fy)]
            return None if pd.isna(r["value_rs_lakh"]) else r
        except KeyError:
            return None

    states = sorted(set(econ.state_id))
    fys = sorted(econ.fy.unique())

    # population (persons) by FY
    pop = {}
    for sid in states:
        for fy in fys:
            n, pc = eget(sid, "nsdp_total", fy), get(sid, "per_capita_nsdp_real", fy)
            if n is not None and pc is not None and pc["value"] > 0:
                v = n["value_rs_lakh"] * 1e5 / pc["value"]
                pop[(sid, fy)] = (v, n, pc)
                out.append(_row(sid, fy, "fy", "population_derived", v, "persons", [n, pc],
                                "NSDP (T24, Rs lakh) x 1e5 / per-capita NSDP (T20, Rs)", n["first_pub_est"]))

    def pop_asof(sid, fy):
        cands = [f for f in fys if (sid, f) in pop and f <= fy]
        if not cands:
            return None, None
        f = max(cands)
        return pop[(sid, f)], f

    # energy shortage and peak unmet, by FY
    for sid in set(ind.state_id):
        for fy in sorted(ind[(ind.feature_code == "power_requirement") & (ind.state_id == sid)].period):
            rq, av = get(sid, "power_requirement", fy), get(sid, "power_availability", fy)
            if rq is not None and av is not None and rq["value"] > 0:
                out.append(_row(sid, fy, "fy", "power_shortage_pct", max(0.0, (rq["value"] - av["value"]) / rq["value"] * 100),
                                "%", [rq, av], "(requirement T141 - availability T139) / requirement; floored at 0",
                                rq["first_pub_est"]))
        for r in ind[(ind.feature_code == "peak_deficit_pct") & (ind.state_id == sid)].itertuples():
            if pd.notna(r.value):
                rr = key.loc[(sid, "peak_deficit_pct", r.period)]
                out.append(_row(sid, r.period, "fy", "peak_unmet_pct", max(0.0, -r.value), "%", [rr],
                                "T142 surplus(+)/deficit(-) per cent, deficit as a positive number", rr["first_pub_est"]))

    # per-capita ratios on the latest period, with explicit population as-of match
    ratio_specs = [
        ("national_highways_km", "nh_km_per_lakh_pop", 1e5, "km per lakh people", "year"),
        ("railway_route_km", "rail_km_per_lakh_pop", 1e5, "km per lakh people", "year"),
        ("bank_offices_scb", "bank_offices_per_lakh_pop", 1e5, "per lakh people", "year"),
        ("personal_loans_scb", "personal_loans_per_capita", 1e7, "Rs per person", "year"),  # Rs crore -> Rs
        ("govt_beds_total", "govt_beds_per_lakh_pop", 1e5, "per lakh people", "snapshot"),
        ("health_staff_chc_specialists_in_position", "specialists_per_lakh_pop", 1e5, "per lakh people", "year"),
        ("health_staff_phc_doctors_in_position", "phc_doctors_per_lakh_pop", 1e5, "per lakh people", "year"),
    ]
    for src, code, scale, unit, kind in ratio_specs:
        sub = ind[(ind.feature_code == src) & ind.value.notna()]
        for sid, g in sub.groupby("state_id"):
            r = g.sort_values("period").iloc[-1]
            if kind == "year":
                fy = fy_label(int(r.period) - 1)  # end-March Y -> FY (Y-1)-Y
            else:
                fy = max(fys)
            p, fy_used = pop_asof(sid, fy)
            if p is None:
                continue
            rr = key.loc[(sid, src, r.period)]
            note = f"{src} ({r.table_id}, {r.period}) / population {fy_used}"
            if fy_used != fy:
                note += f" (population for {fy} not published; latest earlier FY used)"
            out.append(_row(sid, r.period, r.period_type, code, r.value * scale / p[0], unit, [rr, p[1], p[2]], note))

    # credit to industry share
    for sid in set(ind.state_id):
        g = ind[(ind.state_id == sid) & (ind.feature_code == "credit_industry_scb") & ind.value.notna()]
        if g.empty:
            continue
        per = g.period.max()
        a, b = get(sid, "credit_industry_scb", per), get(sid, "credit_scb", per)
        if a is not None and b is not None and b["value"] > 0:
            out.append(_row(sid, per, "year", "credit_industry_share", a["value"] / b["value"] * 100, "%", [a, b],
                            "credit to industry (T158) / total SCB credit (T156)"))

    # momentum (3-year mean real growth, latest 3 growth years) and sector shares from fact_economic
    e = econ.sort_values(["state_id", "activity_code", "fy"]).copy()
    e["g"] = e.groupby(["state_id", "activity_code"]).value_rs_lakh.pct_change(fill_method=None) * 100
    for (sid, act), g in e.groupby(["state_id", "activity_code"]):
        if act not in {"manufacturing", "services", "financial_services", "gsva_total"}:
            continue
        g = g.dropna(subset=["value_rs_lakh"])
        if len(g) < 4:
            continue
        last3 = g.tail(4)
        comps = [ekey.loc[(sid, act, fy)].rename({"value_rs_lakh": "value"}) for fy in last3.fy]
        out.append(_row(sid, last3.fy.iloc[-1], "fy", f"momentum_{act}", float(g.g.tail(3).mean()), "% a year",
                        comps, f"mean real growth {last3.fy.iloc[1]}..{last3.fy.iloc[-1]} ({last3.table_id.iloc[0]}, 2011-12 prices)",
                        last3.first_pub_est.iloc[-1]))
    w = econ.pivot_table(index=["state_id", "fy"], columns="activity_code", values="value_rs_lakh").dropna(subset=["gsva_total"])
    for sid, g in w.groupby(level=0):
        fy = g.index.get_level_values(1).max()
        row = g.loc[(sid, fy)]
        tot = ekey.loc[(sid, "gsva_total", fy)].rename({"value_rs_lakh": "value"})
        for act in ["manufacturing", "services", "financial_services"]:
            if pd.notna(row.get(act)):
                c = ekey.loc[(sid, act, fy)].rename({"value_rs_lakh": "value"})
                out.append(_row(sid, fy, "fy", f"share_{act}", row[act] / row.gsva_total * 100, "% of GSVA", [c, tot],
                                f"{act} / total GSVA, {fy}, 2011-12 prices"))
        if pd.notna(row.get("gsdp_total")):
            c = ekey.loc[(sid, "gsdp_total", fy)].rename({"value_rs_lakh": "value"})
            out.append(_row(sid, fy, "fy", "gsdp_rs_crore", row.gsdp_total / 100, "Rs crore (2011-12 prices)", [c],
                            "real GSDP (T22), Rs lakh / 100", c["first_pub_est"]))
    # straight renames so the scoring catalogue reads one namespace
    for src, code in [("exports", "exports_usd_mn")]:
        for r in ind[(ind.feature_code == src) & ind.value.notna()].itertuples():
            rr = key.loc[(r.state_id, src, r.period)]
            out.append(_row(r.state_id, r.period, r.period_type, code, r.value, r.unit, [rr], f"= {src} ({r.table_id})",
                            r.first_pub_est))
    return pd.DataFrame(out)[FACT_INDICATOR_COLS]


def build():
    ind = load_sources()
    econ = pd.read_parquet(CUR / "fact_economic.parquet")
    der = derive(ind, econ)
    fact = pd.concat([ind, der], ignore_index=True)
    fact = fact[fact.value.notna()]
    dups = fact.duplicated(["state_id", "period", "feature_code"]).sum()
    if dups:
        raise ValueError(f"{dups} duplicate (state, period, feature) rows in fact_indicator")
    fact["period"] = fact["period"].astype(str)
    write_parquet(fact, "fact_indicator")
    ds = dim_state()
    write_parquet(ds, "dim_state")
    con = duckdb.connect(str(WAREHOUSE))
    for name, df in [("dim_state", ds), ("fact_economic", econ), ("fact_indicator", fact)]:
        con.register("tmp", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM tmp")
        con.unregister("tmp")
    con.execute("""CREATE OR REPLACE VIEW latest_indicator AS
        SELECT * FROM fact_indicator QUALIFY row_number() OVER (PARTITION BY state_id, feature_code
        ORDER BY period DESC) = 1""")
    n = con.execute("SELECT count(*) FROM fact_indicator").fetchone()[0]
    con.close()
    return fact, der, n


def main():
    fact, der, n = build()
    print(f"fact_indicator: {n} rows, {fact.feature_code.nunique()} features "
          f"({len(der)} derived rows); quality: {fact.quality.value_counts().to_dict()}")
    print(f"warehouse: {WAREHOUSE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
