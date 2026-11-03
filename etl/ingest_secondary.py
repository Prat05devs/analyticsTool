"""Verify the research extracts in data/extracted/ against raw snapshots of the pages they cite.

    python -m etl.ingest_secondary

A value is admitted to fact_indicator only if the number is found in the registered raw snapshot of its
source_url, close to the state/city name (small numbers need the name within the same passage).
quality = 'official' when the snapshot is an official publication, 'secondary' for press/aggregator pages,
'private' for private salary surveys. Everything else is written to reports/unverified_values.csv and never
reaches the app or the scoring engine (rule 2).
"""
from __future__ import annotations

import re
import sys

import pandas as pd

from etl.common import FACT_INDICATOR_COLS, REP, ROOT, register, write_parquet
from etl.pdf_utils import digits_only, full_text
from etl.states import normalize_state

EXTRACTS = ROOT / "data/extracted"
OFFICIAL_HOSTS = ("pib.gov.in", "mospi.gov.in", "trai.gov.in", "tourism.gov.in", "rbi.org.in")
CITY_STATE = {"Ahmedabad": "GJ", "Bengaluru": "KA", "Chennai": "TN", "Hyderabad": "TG", "Mumbai": "MH", "Pune": "MH"}


def snapshot_for(url: str):
    reg = register()
    hit = reg[(reg.url == url) & reg.local_path.str.startswith("data/raw")]
    if hit.empty:
        return None, None
    row = hit.iloc[-1]
    return ROOT / row.local_path, row


def value_strings(v: float) -> list[str]:
    out = {f"{v:.2f}".rstrip("0").rstrip("."), f"{v:g}"}
    if float(v).is_integer():
        out.add(str(int(v)))
    if v >= 1000 and float(v).is_integer():
        out.add(f"{v / 1e5:.2f}".rstrip("0").rstrip("."))  # e.g. 1789000 -> 17.89 (lakh)
    return sorted(out, key=len, reverse=True)


def verify(text: str, value: float, names: list[str], window: int = 600) -> bool:
    t = digits_only(text)
    for s in value_strings(value):
        for m in re.finditer(rf"(?<![\d.]){re.escape(s)}(?![\d])", t):
            if len(s.replace(".", "").lstrip("0")) >= 5:  # a 5+ digit figure is specific enough on its own
                return True
            ctx = t[max(0, m.start() - window): m.end() + window].lower()
            if any(n.lower() in ctx for n in names if n):
                return True
    return False


def admit(rows, rej, r, sid, code, period, unit, note, path, reg_row, quality):
    rows.append({"state_id": sid, "period": str(period), "period_type": "latest", "feature_code": code,
                 "value": float(r.value), "unit": unit, "source_id": "research_extract_2026_11_03",
                 "table_id": r.source_name, "published_at": pd.Timestamp(reg_row.acquisition_date),
                 "first_pub_est": pd.NaT, "source_file": str(path.relative_to(ROOT)), "sha256": reg_row.sha256,
                 "quality": quality, "note": note})


def quality_of(url: str, source_type: str) -> str:
    if "private" in source_type:
        return "private"
    return "official" if any(h in url for h in OFFICIAL_HOSTS) and source_type.startswith("official") else "secondary"


def build():
    rows, rej = [], []
    ind = pd.read_csv(EXTRACTS / "latest_2026/indicators_2025_2026_long.csv")
    for r in ind.itertuples():
        path, reg_row = snapshot_for(r.source_url)
        geo = r.geo.split(" (")[0]
        sid = normalize_state(geo) if geo != "All India" else "IN"
        names = ["India"] if sid == "IN" else [geo]
        ok = path is not None and verify(full_text(str(path)), float(r.value), names)
        if ok:
            admit(rows, rej, r, sid, r.indicator + ("" if "(" not in r.geo else "_" + r.geo.split("(")[1].rstrip(")")),
                  r.period, r.unit, f"{r.notes if isinstance(r.notes, str) else ''}".strip(), path, reg_row,
                  quality_of(r.source_url, r.source_type))
        else:
            rej.append({"file": "indicators_2025_2026_long.csv", "geo": r.geo, "indicator": r.indicator,
                        "period": r.period, "value": r.value, "source_url": r.source_url,
                        "reason": "no raw snapshot" if path is None else "value not found next to the name in snapshot"})
    wages = pd.read_csv(EXTRACTS / "latest_2026/wages_and_salaries_2026.csv")
    for r in wages.itertuples():
        path, reg_row = snapshot_for(r.source_url)
        sid = CITY_STATE.get(r.geo) or (normalize_state(r.geo) if r.geo_level == "state" else None)
        names = [r.geo, r.zone_or_city.split(" (")[0]]
        ok = sid is not None and path is not None and verify(full_text(str(path)), float(r.value), names)
        code = {"statutory minimum wage": "min_wage", "market salary (all sectors)": "market_salary",
                "market CTC (all functions)": "market_ctc"}[r.category]
        level = re.sub(r"[^a-z0-9]+", "_", r.level.lower()).strip("_")
        if ok:
            note = f"{r.zone_or_city}; {r.source_type}; {r.notes if isinstance(r.notes, str) else ''}"
            admit(rows, rej, r, sid, f"{code}_{level}" + (f"__{r.geo.lower()}" if r.geo_level == "city" else ""),
                  r.period_effective, r.unit, note, path, reg_row, quality_of(r.source_url, r.source_type))
        else:
            rej.append({"file": "wages_and_salaries_2026.csv", "geo": r.geo, "indicator": f"{code} {r.level}",
                        "period": r.period_effective, "value": r.value, "source_url": r.source_url,
                        "reason": "not a pilot-state city" if sid is None else
                        "no raw snapshot" if path is None else "value not found next to the name in snapshot"})
    yu = pd.read_csv(EXTRACTS / "labour/plfs_youth_ur_usual_status_by_state.csv", na_values=["NA"])
    for r in yu.itertuples():
        for col in ["ur_15_29_2022_23", "ur_15_29_2023_24"]:
            rej.append({"file": "plfs_youth_ur_usual_status_by_state.csv", "geo": r.state, "indicator": col,
                        "period": col[-7:].replace("_", "-"), "value": getattr(r, col),
                        "source_url": "dge.gov.in 3232_e.pdf / eparlib AU430.pdf",
                        "reason": "source PDF not downloadable (404 / DNS) - manual download needed"})
    return pd.DataFrame(rows)[FACT_INDICATOR_COLS], pd.DataFrame(rej)


def main():
    df, rej = build()
    write_parquet(df, "fact_indicator_secondary")
    rej.to_csv(REP / "unverified_values.csv", index=False)
    print(f"admitted {len(df)} values ({df.quality.value_counts().to_dict()}); unverified {len(rej)} "
          f"-> reports/unverified_values.csv")
    print(df[["state_id", "feature_code", "period", "value", "quality"]].to_string())
    print(rej.groupby(["file", "reason"]).size().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
