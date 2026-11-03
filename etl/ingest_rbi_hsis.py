"""Ingest RBI Handbook of Statistics on Indian States 2024-25 (raw XLSX or official HTML pages).

    python -m etl.ingest_rbi_hsis

Outputs
  data/curated/fact_economic.parquet         state x fy x activity, constant 2011-12 prices (modelling panel)
  data/curated/fact_indicator_rbi.parquet    every other RBI table, long (fact_indicator schema)
  data/curated/quarantine_rbi.parquet        anything on a different price base (never merged, rule 5)

Units are converted once, here: GSVA stays in Rs lakh (as published) plus a Rs crore column;
unemployment 'per thousand' -> per cent; tourist visits lakh -> million.

first_pub_est is an ESTIMATED first-release date of each observation, derived from each source's
publication cadence (see LAG_RULES). The handbook itself is one vintage (published_at = 2025-12-11);
real-time vintages are not available, which the model card states as a limitation.
"""
from __future__ import annotations

import datetime as dt
import re
import sys

import numpy as np
import pandas as pd

from etl.common import CUR, FACT_INDICATOR_COLS, RAW, ROOT, fy_start, reg_row, sources, write_parquet
from etl.rbi_html import parse_html, parse_xlsx, to_number
from etl.states import normalize_state

SOURCE_ID = "rbi_hsis_2024_25"

# GSVA/GSDP/NSDP tables -> fact_economic activity_code
ECON = {
    "T22": "gsdp_total", "T24": "nsdp_total", "T26": "gsva_total", "T30": "agriculture", "T34": "manufacturing",
    "T38": "construction", "T42": "industry", "T46": "financial_services", "T50": "services",
}

# table -> feature_code, output unit, scale factor, lag rule, header selector, block selector
# selector(header_tuple) returns (period_label, sub_code) or None to skip the column
def _single(h):
    return (h[-1], "")


def _hosp(h):
    return ("NHP (date not stated)", f"{'hospitals' if 'Hospitals' in h[0] else 'beds'}_{h[1].lower()}")


def _peak(h):
    if len(h) >= 3 and "Per cent" in h[-1]:
        return (h[0], "")
    return None


def _doctors(h):
    # keep 'In Position' doctors at PHCs and specialists at CHCs, and the shortfall
    if len(h) < 3:
        return None
    kind = "phc_doctors" if "PHC" in h[1] else "chc_specialists" if "Specialist" in h[1] or "CHC" in h[1] else None
    meas = "in_position" if "Position" in h[2] else "shortfall" if "Shortfall" in h[2] else None
    if kind and meas:
        return (h[0], f"{kind}_{meas}")
    return None


IND = {
    "T08": ("ur_rural_us_adj", "%", 0.1, "plfs", _single, "Rural Overall"),
    "T09": ("ur_urban_us_adj", "%", 0.1, "plfs", _single, "Urban Overall"),
    "T13": ("domestic_tourist_visits", "million", 1, "tourism", _single, None),
    "T16": ("health_staff", "persons", 1, "end_march_2y", _doctors, None),
    "T17": ("govt", "number", 1, "none", _hosp, None),
    "T18": ("public_health_expenditure", "Rs crore", 1, "fiscal_2y", _single, None),
    "T20": ("per_capita_nsdp_real", "Rs (2011-12 prices)", 1, "sdp", _single, None),
    "T108": ("cpi_inflation_general", "%", 1, "cpi", _single, None),
    "T111": ("cpi_inflation_housing_urban", "%", 1, "cpi", _single, None),
    "T112": ("rural_wage_construction", "Rs/day (men)", 1, "wage", _single, None),
    "T115": ("rural_wage_nonagri", "Rs/day (men)", 1, "wage", _single, None),
    "T116": ("asi_factories", "number", 1, "asi", _single, None),
    "T117": ("asi_fixed_capital", "Rs lakh", 1, "asi", _single, None),
    "T122": ("asi_workers", "persons", 1, "asi", _single, None),
    "T124": ("asi_emoluments", "Rs lakh", 1, "asi", _single, None),
    "T128": ("asi_gva", "Rs lakh (current prices)", 1, "asi", _single, None),
    "T132": ("asi_employees", "persons", 1, "asi", _single, None),
    "T138": ("per_capita_power_availability", "kWh", 1, "power", _single, None),
    "T139": ("power_availability", "net crore units", 1, "power", _single, None),
    "T140": ("installed_capacity_power", "MW", 1, "power", _single, None),
    "T141": ("power_requirement", "net crore units", 1, "power", _single, None),
    "T142": ("peak_deficit_pct", "%", 1, "power", _peak, None),
    "T143": ("renewable_capacity", "MW", 1, "end_march", _single, None),
    "T144": ("national_highways_km", "km", 1, "roads", _single, None),
    "T145": ("railway_route_km", "km", 1, "roads", _single, None),
    "T146": ("road_length_km", "km", 1, "roads", _single, None),
    "T147": ("state_highways_km", "km", 1, "roads", _single, None),
    "T148": ("td_losses_pct", "%", 1, "fiscal_2y", _single, None),
    "T149": ("telephones_per_100", "per 100 population", 1, "end_march", _single, None),
    "T152": ("bank_offices_scb", "number", 1, "end_march", _single, None),
    "T153": ("cd_ratio_sanction", "%", 1, "end_march", _single, None),
    "T154": ("cd_ratio_utilisation", "%", 1, "end_march", _single, None),
    "T155": ("deposits_scb", "Rs crore", 1, "end_march", _single, None),
    "T156": ("credit_scb", "Rs crore", 1, "end_march", _single, None),
    "T158": ("credit_industry_scb", "Rs crore", 1, "end_march", _single, None),
    "T159": ("personal_loans_scb", "Rs crore", 1, "end_march", _single, None),
    "T181": ("exports", "USD million", 1, "fiscal_1y", _single, None),
    "T182": ("foreign_tourist_visits", "million", 0.1, "tourism", _single, None),  # published in lakh
}


def first_pub_est(rule: str, period: str):
    """Estimated first public release date of one observation (publication-cadence approximation)."""
    m_fy = re.match(r"^(\d{4})-\d{2}$", period)
    m_y = re.match(r"^(\d{4})$", period)
    if rule == "none":
        return pd.NaT
    if m_fy:
        s = int(m_fy.group(1))
        return pd.Timestamp({
            "sdp": dt.date(s + 1, 12, 15),        # state accounts for FY s reach the RBI handbook ~Dec of s+1
            "asi": dt.date(s + 2, 9, 30),         # ASI 2024-25 was released 30 Sep 2026
            "plfs": dt.date(s + 1, 10, 31),       # PLFS Jul-Jun annual report ~Sep/Oct of the following year
            "power": dt.date(s + 1, 5, 31),       # CEA annual power supply position ~2 months after FY end
            "cpi": dt.date(s + 1, 5, 15),
            "wage": dt.date(s + 1, 6, 30),
            "fiscal_1y": dt.date(s + 1, 12, 31),
            "fiscal_2y": dt.date(s + 2, 12, 31),
        }.get(rule, dt.date(s + 2, 12, 31)))
    if m_y:
        y = int(m_y.group(1))
        return pd.Timestamp({
            "end_march": dt.date(y, 9, 30),       # end-March stock published by the following autumn
            "end_march_2y": dt.date(y + 1, 12, 31),
            "roads": dt.date(y + 2, 12, 31),      # road statistics lag ~2-3 years
            "tourism": dt.date(y + 1, 9, 30),     # tourism statistics for year y ~Sep of y+1
        }.get(rule, dt.date(y + 1, 12, 31)))
    return pd.NaT


def clean_period(p: str) -> tuple[str, str]:
    """('2024*' -> '2024', 'year_end_march'), ('2011-12' -> fy), ('2011' -> calendar)."""
    p = re.sub(r"[^\d\-]", "", p.strip())
    if re.match(r"^\d{4}-\d{2}$", p):
        return p, "fy"
    if re.match(r"^\d{4}-\d{4}$", p):  # rare long form 2011-2012
        return f"{p[:4]}-{p[-2:]}", "fy"
    if re.match(r"^\d{4}$", p):
        return p, "year"
    return p, "other"


def raw_file(tid_full: str):
    """Prefer the XLSX (as saved by the script or as downloaded manually), fall back to the HTML page."""
    folder = RAW / "rbi_hsis" / str(sources()["rbi_handbook_states_2024_25"]["release_date"])
    links = sources()["rbi_handbook_states_2024_25"]["tables"][tid_full]
    xname = links.get("xlsx", "").split("/")[-1]
    for cand in [folder / f"{tid_full}.xlsx", folder / xname]:
        if xname and cand.exists():
            return cand, "xlsx"
    html = folder / f"{tid_full}.html"
    return (html, "html") if html.exists() else (None, None)


def parse_table(tid_full: str):
    path, kind = raw_file(tid_full)
    if path is None:
        return None
    reg = reg_row(path)
    cells, unit, title = (parse_xlsx if kind == "xlsx" else parse_html)(path)
    df = pd.DataFrame([c.__dict__ for c in cells])
    df["state_id"] = df.state_raw.map(normalize_state)
    df = df.dropna(subset=["state_id"])
    df["value"] = df.value_raw.map(to_number)
    df["table_id"] = tid_full.split("_")[0]
    df["source_file"] = reg["local_path"]
    df["sha256"] = reg["sha256"]
    df["published_at"] = pd.Timestamp(str(sources()["rbi_handbook_states_2024_25"]["release_date"]))
    return df, unit, title, kind


def build():
    tables = sources()["rbi_handbook_states_2024_25"]["tables"]
    econ, ind, quarantine, log = [], [], [], []
    for tid_full in tables:
        tid = tid_full.split("_")[0]
        got = parse_table(tid_full)
        if got is None:
            log.append(f"{tid_full}: no raw file")
            continue
        df, unit, title, kind = got
        log.append(f"{tid_full}: {kind}, {len(df)} state cells, unit {unit!r}")
        if tid in ECON:
            df["base_year"] = df.header.map(lambda h: next((re.sub(r"Base:\s*", "", x) for x in h if "Base" in x), ""))
            df["fy"] = df.header.map(lambda h: clean_period(h[-1])[0])
            bad = df[df.base_year != "2011-12"]
            if len(bad):
                quarantine.append(bad.assign(reason="price base is not 2011-12"))
            df = df[df.base_year == "2011-12"]
            df = df.assign(activity_code=ECON[tid], value_rs_lakh=df.value, value_rs_crore=df.value / 100,
                           real_nominal="real", vintage="2025-12-11")
            df["first_pub_est"] = df.fy.map(lambda p: first_pub_est("sdp", p))
            econ.append(df[["state_id", "fy", "activity_code", "value_rs_lakh", "value_rs_crore", "real_nominal",
                            "base_year", "table_id", "vintage", "published_at", "first_pub_est", "source_file",
                            "sha256", "state_raw", "value_raw"]])
        elif tid in IND:
            code, unit_out, scale, rule, sel, block = IND[tid]
            if block:
                df = df[df.block.str.contains(block, case=False, na=False)]
            picked = df.header.map(sel)
            df = df[picked.notna()].copy()
            picked = picked[picked.notna()]
            df["period_raw"] = picked.map(lambda x: x[0])
            df["sub"] = picked.map(lambda x: x[1])
            df[["period", "period_type"]] = df.period_raw.map(clean_period).apply(pd.Series)
            if tid == "T17":
                df["period"], df["period_type"] = "NHP", "snapshot"
            df["feature_code"] = np.where(df["sub"] != "", code + "_" + df["sub"], code)
            df["value"] = df.value * scale
            df["unit"] = unit_out
            df["source_id"] = SOURCE_ID
            df["first_pub_est"] = df.period.map(lambda p: first_pub_est(rule, p))
            df["quality"] = "official"
            df["note"] = title[:160]
            ind.append(df[FACT_INDICATOR_COLS])
    econ = pd.concat(econ, ignore_index=True)
    ind = pd.concat(ind, ignore_index=True)
    # duplicate cells can only come from a parsing error -> fail loudly
    dup_e = econ.duplicated(["state_id", "fy", "activity_code"]).sum()
    dup_i = ind.duplicated(["state_id", "period", "feature_code"]).sum()
    if dup_e or dup_i:
        d = ind[ind.duplicated(["state_id", "period", "feature_code"], keep=False)].head(10)
        raise ValueError(f"duplicate cells: econ {dup_e}, indicator {dup_i}\n{d}")
    write_parquet(econ, "fact_economic")
    write_parquet(ind, "fact_indicator_rbi")
    q = pd.concat(quarantine) if quarantine else pd.DataFrame(columns=["state_id", "reason"])
    write_parquet(q.astype(str), "quarantine_rbi")
    return econ, ind, q, log


def main():
    econ, ind, q, log = build()
    print("\n".join(log))
    print(f"\nfact_economic: {len(econ)} rows, {econ.state_id.nunique()} states, "
          f"{econ.fy.nunique()} years, {econ.activity_code.nunique()} activities")
    print(f"fact_indicator_rbi: {len(ind)} rows, {ind.feature_code.nunique()} feature codes")
    print(f"quarantined: {len(q)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
