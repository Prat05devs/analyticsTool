"""TRAI Performance Indicator Report, Apr-Jun 2026: internet subscribers per 100 population by State/UT.

    python -m etl.ingest_trai_pir

The PIR reports by licensed service area (LSA) AND, in Table 1.43, by State/UT. We use the State/UT table.
The LSA table (1.42) is kept with an explicit, documented LSA->state map (etl/lsa_state_map.csv) because
several LSAs bundle states (AP incl. Telangana in LSA terms, Maharashtra incl. Goa, Mumbai separate, ...).
"""
from __future__ import annotations

import glob
import re
import sys

import pandas as pd

from etl.common import FACT_INDICATOR_COLS, ROOT, reg_row, write_parquet
from etl.pdf_utils import find_page, num, page_text, spot_check
from etl.states import normalize_state

PUBLISHED_AT = pd.Timestamp("2026-10-12")
LINE = re.compile(r"^(?:\d+\s+)?([A-Za-z&().\- ]+?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.]+)\s*$")
NAMELESS = re.compile(r"^\d+\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.]+)\s*$")
FIX = {"Chattisgarh": "Chhattisgarh", "Tamil Nadu incl. Chennai": "Tamil Nadu", "West Bengal incl. Kolkata": "West Bengal",
       "Dadar & Nagar Haweli": "Dadra & Nagar Haveli and Daman & Diu", "Andaman & Nicobar": "Andaman & Nicobar Islands"}


def build():
    path = glob.glob(str(ROOT / "data/raw/trai_pir/*/QPIR_12102026.pdf"))[0]
    reg = reg_row(path)
    page = find_page(path, r"Table 1\.43 ?: State/UT wise number of Internet Subscribers per 100")
    lines = page_text(path, page).splitlines()
    rows, checks = [], []
    pending = None  # a state name printed on its own line, above a row that has only the serial number
    for raw in lines:
        s = raw.strip()
        if s.startswith("Uttar Pradesh"):
            pending = "Uttar Pradesh"
            continue
        m, nl = LINE.match(s), NAMELESS.match(s)
        if nl and pending:
            groups = [pending] + list(nl.groups())
        elif m:
            groups = list(m.groups())
        else:
            if s and s != "Union Territories" and not s.startswith("(") and not re.search(r"\d", s) and len(s) < 40:
                pending = FIX.get(s, s) if pending is None else pending
            continue
        name = groups[0].strip()
        if name == "Total":
            name = "All India"
        name = FIX.get(name, name)
        pending = None
        try:
            sid = normalize_state(name)
        except KeyError:
            continue
        vals = dict(zip(["subs_rural_mn", "subs_urban_mn", "subs_total_mn", "rural", "urban", "total"],
                        groups[1:7]))
        for code, key in [("internet_subs_per_100", "total"), ("internet_subs_per_100_urban", "urban"),
                          ("internet_subs_per_100_rural", "rural")]:
            v = num(vals[key])
            if v != v:
                continue
            rows.append({"state_id": sid, "period": "2026-06", "period_type": "month_end", "feature_code": code,
                         "value": v, "unit": "subscribers per 100 population", "source_id": "trai_pir",
                         "table_id": "PIR Apr-Jun 2026 Table 1.43", "published_at": PUBLISHED_AT,
                         "first_pub_est": PUBLISHED_AT, "source_file": reg["local_path"], "sha256": reg["sha256"],
                         "quality": "official",
                         "note": "subscriptions, not measured speed; >100 where people hold several connections"})
            checks.append({"page": page, "label": f"{name} {code}", "value": vals[key]})
    df = pd.DataFrame(rows).drop_duplicates(["state_id", "feature_code"])[FACT_INDICATOR_COLS]
    return df, checks


def main():
    df, checks = build()
    write_parquet(df, "fact_indicator_trai")
    print(f"TRAI PIR: {df.state_id.nunique()} states/UTs, {len(df)} cells")
    print(spot_check(checks))
    return 0 if df.state_id.nunique() >= 30 else 1


if __name__ == "__main__":
    sys.exit(main())
