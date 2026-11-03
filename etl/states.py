"""Fixed state master (dim_state) and alias map.

Rules
- Footnote markers (*, #, @, ^, trailing digits) are stripped before lookup; the original label is kept upstream.
- Region subtotals, telecom service areas and 'Others/Total' rows are not states -> normalize_state() returns None.
- Historical geography is explicit:
  * Telangana: formed 2 Jun 2014. The RBI 2011-12 base GSVA series carries back-cast Telangana and residual
    Andhra Pradesh figures from 2011-12; ASI shows '.' (not applicable) before 2012-13. Both are kept as published.
  * Jammu & Kashmir: up to 2018-19 the series covers J&K *including* Ladakh; from 2019-20 it is the UT of J&K only.
    validate.py flags the 2019-20 growth as a geography break and features/build_panel.py drops it as a target.
  * Dadra & Nagar Haveli and Daman & Diu merged in Jan 2020 -> kept as one id 'DNHDD'; older split rows map to it
    only when the merged label is used (split labels are dropped to avoid double counting).
"""
from __future__ import annotations

import re

import pandas as pd

PILOTS = ["Maharashtra", "Gujarat", "Karnataka", "Tamil Nadu", "Telangana", "Uttar Pradesh", "Rajasthan"]

# state_id, canonical_name, kind, historic_geography
STATES = [
    ("AN", "Andaman & Nicobar Islands", "UT", ""),
    ("AP", "Andhra Pradesh", "State", "Residual AP from 2 Jun 2014; 2011-12 base series published for residual AP from 2011-12"),
    ("AR", "Arunachal Pradesh", "State", ""),
    ("AS", "Assam", "State", ""),
    ("BR", "Bihar", "State", ""),
    ("CH", "Chandigarh", "UT", ""),
    ("CT", "Chhattisgarh", "State", ""),
    ("DNHDD", "Dadra & Nagar Haveli and Daman & Diu", "UT", "Merged UT from 26 Jan 2020"),
    ("DL", "Delhi", "UT", ""),
    ("GA", "Goa", "State", ""),
    ("GJ", "Gujarat", "State", ""),
    ("HR", "Haryana", "State", ""),
    ("HP", "Himachal Pradesh", "State", ""),
    ("JK", "Jammu & Kashmir", "UT", "Includes Ladakh up to 2018-19; UT of J&K only from 2019-20 (series break)"),
    ("JH", "Jharkhand", "State", ""),
    ("KA", "Karnataka", "State", ""),
    ("KL", "Kerala", "State", ""),
    ("LA", "Ladakh", "UT", "Separate UT from 31 Oct 2019"),
    ("LD", "Lakshadweep", "UT", ""),
    ("MP", "Madhya Pradesh", "State", ""),
    ("MH", "Maharashtra", "State", ""),
    ("MN", "Manipur", "State", ""),
    ("ML", "Meghalaya", "State", ""),
    ("MZ", "Mizoram", "State", ""),
    ("NL", "Nagaland", "State", ""),
    ("OR", "Odisha", "State", ""),
    ("PY", "Puducherry", "UT", ""),
    ("PB", "Punjab", "State", ""),
    ("RJ", "Rajasthan", "State", ""),
    ("SK", "Sikkim", "State", ""),
    ("TN", "Tamil Nadu", "State", ""),
    ("TG", "Telangana", "State", "Formed 2 Jun 2014; back-cast in RBI 2011-12 base series from 2011-12"),
    ("TR", "Tripura", "State", ""),
    ("UP", "Uttar Pradesh", "State", ""),
    ("UK", "Uttarakhand", "State", ""),
    ("WB", "West Bengal", "State", ""),
    ("IN", "All India", "Country", "National total as published"),
]

ALIASES = {
    "andaman & nicobar": "AN", "andaman & nicobar island": "AN", "andaman and nicobar islands": "AN",
    "dadra & nagar haveli & daman & diu": "DNHDD", "dadra & nagar haveli and daman and diu": "DNHDD",
    "daman & diu and dadra & nagar haveli": "DNHDD",
    "jammu & kashmir and ladakh": "JK", "jammu and kashmir": "JK",
    "laksha dweep": "LD", "uttarpradesh": "UP", "orissa": "OR", "pondicherry": "PY", "nct of delhi": "DL",
    "all-india": "IN", "all india": "IN", "india": "IN", "uttaranchal": "UK", "chattisgarh": "CT",
    "a & n islands": "AN", "a&n islands": "AN", "dadra and nagar haveli and daman and diu": "DNHDD", "jammu & kashmir (ut)": "JK", "j&k": "JK", "j & k": "JK",
}
# Labels that are deliberately NOT states (dropped). Dadra/Daman split rows are dropped, see module docstring.
NOT_STATES = {
    "central region", "eastern region", "north-eastern region", "northern region", "southern region", "western region",
    "others", "total", "damodar valley corporation", "mumbai", "kolkata", "chennai", "north east-i", "north east-ii",
    "uttar pradesh-(e&w)", "dadra & nagar haveli", "daman & diu",
}

_BY_NAME = {name.lower(): sid for sid, name, _, _ in STATES}


def clean_label(raw: str) -> str:
    s = re.sub(r"\s+", " ", str(raw)).strip()
    s = re.sub(r"[*#@^$]+$", "", s).strip()
    s = re.sub(r"(?<=[A-Za-z])\d+$", "", s).strip()  # footnote digit glued to the name, e.g. 'Odisha3'
    return s


def normalize_state(raw: str) -> str | None:
    """Return state_id or None for non-state rows. Raises KeyError for an unknown label (fix the map)."""
    s = clean_label(raw).lower()
    if s in NOT_STATES:
        return None
    if s in _BY_NAME:
        return _BY_NAME[s]
    if s in ALIASES:
        return ALIASES[s]
    raise KeyError(f"unmapped state label: {raw!r}")


def dim_state() -> pd.DataFrame:
    df = pd.DataFrame(STATES, columns=["state_id", "canonical_name", "kind", "historic_geography"])
    df["pilot_flag"] = df.canonical_name.isin(PILOTS)
    return df


def name_of(state_id: str) -> str:
    return {sid: n for sid, n, _, _ in STATES}[state_id]


def id_of(name: str) -> str:
    return normalize_state(name)
