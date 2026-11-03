"""Shared paths and helpers for the ETL scripts."""
from __future__ import annotations

import datetime as dt
import hashlib
import pathlib

import pandas as pd
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CUR = ROOT / "data" / "curated"
REP = ROOT / "reports"
REGISTER = ROOT / "data" / "source_register.csv"
WAREHOUSE = CUR / "warehouse.duckdb"

FACT_INDICATOR_COLS = ["state_id", "period", "period_type", "feature_code", "value", "unit", "source_id",
                       "table_id", "published_at", "first_pub_est", "source_file", "sha256", "quality", "note"]


def sources() -> dict:
    return yaml.safe_load((ROOT / "data_sources.yaml").read_text())


def register() -> pd.DataFrame:
    return pd.read_csv(REGISTER, dtype=str).fillna("")


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def reg_row(path: pathlib.Path) -> dict:
    """Register row for a raw file; raises if the file was never registered (rule 2)."""
    rel = str(pathlib.Path(path).resolve().relative_to(ROOT))
    reg = register()
    hit = reg[reg.local_path == rel]
    if hit.empty:
        raise LookupError(f"{rel} is not in data/source_register.csv - run scripts/download_sources.py --register-manual")
    row = hit.iloc[-1].to_dict()
    if row["sha256"] != sha256(path):
        raise ValueError(f"sha256 mismatch for {rel}: raw files are immutable")
    return row


def fy_start(fy: str) -> int:
    return int(str(fy)[:4])


def fy_label(start: int) -> str:
    return f"{start}-{str(start + 1)[-2:]}"


def write_parquet(df: pd.DataFrame, name: str) -> pathlib.Path:
    CUR.mkdir(parents=True, exist_ok=True)
    out = CUR / f"{name}.parquet"
    df.to_parquet(out, index=False)
    return out


def today() -> str:
    return dt.date.today().isoformat()
