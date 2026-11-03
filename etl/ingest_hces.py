"""HCES 2023-24 (Aug 2023 - Jul 2024): average MPCE by state, rural and urban, plus RSE.

    python -m etl.ingest_hces

Source: NSS Report 592, Table 3.17 (average MPCE without imputation, 18 major states) and Appendix Table C1
(RSE, all States/UTs). A survey snapshot: it is never interpolated into an annual series.
"""
from __future__ import annotations

import glob
import re
import sys

import pandas as pd

from etl.common import FACT_INDICATOR_COLS, ROOT, reg_row, write_parquet
from etl.pdf_utils import find_page, num, page_text, spot_check
from etl.states import normalize_state

PUBLISHED_AT = pd.Timestamp("2025-01-01")  # final report release (factsheet Dec 2024); used for as-of filtering
ROW = re.compile(r"^([A-Za-z&\- ]+?)\s+([\d,]+)\s+([\d,]+)\s+(\d+)\s+([\d,]+)\s+([\d,]+)\s+(\d+)\s*$")
RSE = re.compile(r"^([A-Za-z&\- ]+?)\s+([\d.]+)\s+([\d.]+)\s+[\d,]+\s+[\d,]+\s+[\d,]+\s+[\d,]+\s*$")


def build():
    path = glob.glob(str(ROOT / "data/raw/hces_2023_24/*/Final_Report_HCES_2023-24L.pdf"))[0]
    reg = reg_row(path)
    p_mpce = find_page(path, r"Table 3\.17: Average MPCE and urban-rural")
    p_rse = find_page(path, r"Table C1: Relative Standard Errors")
    rows, checks = [], []
    rse = {}
    for line in page_text(path, p_rse).splitlines():
        m = RSE.match(line.strip())
        if m:
            sid = normalize_state(m.group(1))
            if sid:
                rse[sid] = (float(m.group(2)), float(m.group(3)))
    for line in page_text(path, p_mpce).splitlines():
        m = ROW.match(line.strip())
        if not m:
            continue
        sid = normalize_state(m.group(1))
        for code, val, rs in [("mpce_rural", m.group(2), 0), ("mpce_urban", m.group(3), 1)]:
            rows.append({"state_id": sid, "period": "2023-24 (Aug-Jul)", "period_type": "survey",
                         "feature_code": code, "value": num(val), "unit": "Rs per person per month",
                         "source_id": "hces_2023_24", "table_id": "NSS-592 Table 3.17", "published_at": PUBLISHED_AT,
                         "first_pub_est": PUBLISHED_AT, "source_file": reg["local_path"], "sha256": reg["sha256"],
                         "quality": "official",
                         "note": f"survey snapshot; RSE {rse.get(sid, (None, None))[rs]}% (Table C1)"})
            checks.append({"page": p_mpce, "label": f"{m.group(1)} {code}", "value": val})
    df = pd.DataFrame(rows)[FACT_INDICATOR_COLS]
    rse_df = pd.DataFrame([{"state_id": k, "rse_rural_pct": v[0], "rse_urban_pct": v[1]} for k, v in rse.items()])
    return df, rse_df, checks


def main():
    df, rse_df, checks = build()
    write_parquet(df, "fact_indicator_hces")
    write_parquet(rse_df, "hces_rse")
    print(f"HCES: {df.state_id.nunique()} states, {len(df)} cells; RSE for {len(rse_df)} states/UTs")
    print(spot_check(checks))
    return 0 if df.state_id.nunique() >= 18 else 1


if __name__ == "__main__":
    sys.exit(main())
