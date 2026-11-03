"""Rebuild the analysis-ready CSVs from the raw-traceable fact tables (not from data/extracted).

    python scripts/build_curated.py        (run after etl.ingest_* and etl.build_indicators)

Outputs (data/curated/):
  state_income_panel_long.csv   state x fy x activity, Rs lakh, constant 2011-12 prices (RBI HSIS 2024-25)
  state_growth_panel.csv        real growth % by activity
  state_structure_latest.csv    sector shares, per-capita NSDP, CAGR, volatility (latest year per state)
  pilot_state_profile.csv       7 pilots, long: every latest indicator with unit, period, quality, source file + URL
  city_profile.csv              28 pilot-state cities: speed (Ookla), wage floor, private salary bands, or
                                'not available' with the reason
reports/validation_report.md    short summary; the full checks are in reports/validation_rbi_panel.md

Earlier versions read data/extracted/ (hand transcriptions); two of those cells were wrong
(see reports/validation_rbi_panel.md), so every number now comes from a parsed raw file.
"""
import glob
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from etl.states import PILOTS, name_of, normalize_state  # noqa: E402
from scoring.data import latest, sources_url  # noqa: E402

CUR = ROOT / "data" / "curated"
REP = ROOT / "reports"
CITY_STATE = {"Mumbai": "MH", "Pune": "MH", "Nagpur": "MH", "Nashik": "MH", "Ahmedabad": "GJ", "Surat": "GJ",
              "Vadodara": "GJ", "Rajkot": "GJ", "Bengaluru": "KA", "Mysuru": "KA", "Hubballi-Dharwad": "KA",
              "Mangaluru": "KA", "Chennai": "TN", "Coimbatore": "TN", "Madurai": "TN", "Tiruchirappalli": "TN",
              "Hyderabad": "TG", "Warangal": "TG", "Lucknow": "UP", "Noida": "UP", "Kanpur": "UP", "Ghaziabad": "UP",
              "Agra": "UP", "Varanasi": "UP", "Jaipur": "RJ", "Jodhpur": "RJ", "Udaipur": "RJ", "Kota": "RJ"}


def panels():
    econ = pd.read_parquet(CUR / "fact_economic.parquet")
    econ["state"] = econ.state_id.map(name_of)
    long = econ[["state", "fy", "value_rs_lakh", "activity_code", "base_year", "table_id", "source_file"]].rename(
        columns={"activity_code": "activity"})
    long["source"] = "RBI Handbook of Statistics on Indian States 2024-25 (11 Dec 2025)"
    long.to_csv(CUR / "state_income_panel_long.csv", index=False)
    g = long.sort_values(["activity", "state", "fy"]).copy()
    g["growth_pct"] = g.groupby(["activity", "state"]).value_rs_lakh.pct_change(fill_method=None) * 100
    g.dropna(subset=["growth_pct"])[["state", "fy", "activity", "growth_pct"]].to_csv(
        CUR / "state_growth_panel.csv", index=False)
    w = long.pivot_table(index=["state", "fy"], columns="activity", values="value_rs_lakh")
    pc = latest(["per_capita_nsdp_real"]).assign(state=lambda d: d.state_id.map(name_of)).set_index("state")
    rows = []
    for st, d in w.groupby(level=0):
        d = d.droplevel(0).dropna(subset=["gsva_total"])
        first, last = d.index.min(), d.index.max()
        yrs = int(last[:4]) - int(first[:4])
        tot = d.loc[last]
        mg = g[(g.state == st) & (g.activity == "manufacturing")].growth_pct.dropna()
        gg = g[(g.state == st) & (g.activity == "gsva_total")].growth_pct.dropna()
        rows.append({"state": st, "latest_fy": last, "gsva_total_rs_crore": tot.gsva_total / 100,
                     "share_manufacturing_pct": 100 * tot.manufacturing / tot.gsva_total,
                     "share_industry_pct": 100 * tot.industry / tot.gsva_total,
                     "share_services_pct": 100 * tot.services / tot.gsva_total,
                     "share_financial_pct": 100 * tot.financial_services / tot.gsva_total,
                     "gsva_cagr_pct_full_period": 100 * ((tot.gsva_total / d.loc[first].gsva_total) ** (1 / yrs) - 1),
                     "gsva_growth_latest_pct": gg.iloc[-1] if len(gg) else np.nan,
                     "gsva_growth_3y_mean_pct": gg.tail(3).mean() if len(gg) else np.nan,
                     "manufacturing_growth_latest_pct": mg.iloc[-1] if len(mg) else np.nan,
                     "manufacturing_growth_volatility_sd": mg.std(),
                     "per_capita_nsdp_rs_constant": pc.value.get(st, np.nan),
                     "per_capita_nsdp_fy": pc.period.get(st)})
    pd.DataFrame(rows).to_csv(CUR / "state_structure_latest.csv", index=False, float_format="%.2f")
    return long


def pilot_profile():
    pid = [normalize_state(p) for p in PILOTS]
    lat = latest(quality=("official", "derived", "secondary", "private"))
    lat = lat[lat.state_id.isin(pid)].copy()
    lat["state"] = lat.state_id.map(name_of)
    lat["source_url"] = lat.source_file.map(sources_url)
    out = lat[["state", "feature_code", "value", "unit", "period", "quality", "table_id", "source_file", "source_url",
               "note"]].sort_values(["state", "feature_code"])
    out.to_csv(CUR / "pilot_state_profile.csv", index=False)
    return out


def city_profile():
    speed = {}
    files = sorted(glob.glob(str(CUR / "internet_speed" / "city_speed_*.csv")))
    for f in files:
        tag = pathlib.Path(f).stem.split("_")[-1]
        d = pd.read_csv(f)
        for r in d.itertuples():
            speed.setdefault(r.city, {})[(tag, r.kind)] = (r.avg_download_mbps, r.avg_latency_ms, r.tests, r.shapeName)
    sec = latest(quality=("secondary", "private")).set_index(["state_id", "feature_code"])
    rows = []
    for city, sid in CITY_STATE.items():
        row = {"city": city, "state": name_of(sid)}
        tags = sorted({t for t, _ in speed.get(city, {})})
        if tags:
            t = tags[-1]
            for kind in ["fixed", "mobile"]:
                v = speed[city].get((t, kind))
                row[f"{kind}_download_mbps"] = round(v[0], 1) if v else np.nan
                row[f"{kind}_latency_ms"] = round(v[1], 0) if v else np.nan
                row[f"{kind}_tests"] = v[2] if v else np.nan
                if len(tags) > 1 and v and (tags[0], kind) in speed[city]:
                    row[f"{kind}_download_change_pct"] = round(100 * (v[0] / speed[city][(tags[0], kind)][0] - 1), 1)
            row["speed_period"] = t
            row["speed_district"] = speed[city].get((t, "fixed"), speed[city].get((t, "mobile")))[3]
            row["speed_source"] = "Ookla Open Data (CC BY-NC-SA 4.0), district containing the city"
        else:
            row["speed_source"] = "not available: Ookla extraction not yet run for this quarter"
        mw = [k for k in sec.index if k[0] == sid and k[1].startswith("min_wage")]
        if mw:
            r = sec.loc[mw[0]]
            row.update(min_wage_monthly_rs=r.value, min_wage_period=r.period, min_wage_quality=r.quality,
                       min_wage_note=f"STATE-level figure, {r.note.split(';')[0]}; city zone not verified against "
                                     "the gazette", min_wage_source_url=sources_url(r.source_file))
        else:
            row["min_wage_note"] = "not available: no figure could be verified in a saved source"
        ms = [k for k in sec.index if k[0] == sid and k[1].endswith("__" + city.lower())]
        if ms:
            for k in ms:
                r = sec.loc[k]
                row[k[1].split("__")[0]] = r.value
                row[k[1].split("__")[0] + "_source_url"] = sources_url(r.source_file)
            row["salary_quality"] = "private survey"
        else:
            row["salary_note"] = "not available: no private salary band verified for this city"
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(CUR / "city_profile.csv", index=False)
    return out


def main():
    long = panels()
    prof = pilot_profile()
    city = city_profile()
    (REP / "validation_report.md").write_text(
        "# Validation report (summary)\n\nThe full checks are in `validation_rbi_panel.md` (run `python -m etl.validate`).\n"
        f"- State income panel: {long.state.nunique()} states/UTs, {long.fy.nunique()} years, "
        f"{long.activity.nunique()} activities, {long.value_rs_lakh.isna().sum()} cells not published.\n"
        f"- Pilot profile: {len(prof)} latest values, every one with a raw file and URL.\n"
        f"- City profile: {len(city)} cities; speed available for {int(city.get('fixed_download_mbps', pd.Series(dtype=float)).notna().sum())}.\n")
    print(f"wrote curated CSVs; pilot profile {len(prof)} rows; city profile {len(city)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
