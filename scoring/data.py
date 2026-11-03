"""Read-side helpers shared by eligibility, scoring and the app."""
from __future__ import annotations

import functools
import json

import pandas as pd
import yaml

from etl.common import CUR, ROOT
from etl.states import PILOTS, normalize_state

PILOT_IDS = [normalize_state(p) for p in PILOTS]
# national reference set for normalisation: 28 states + Delhi + J&K
REFERENCE_KINDS = {"State"}
REFERENCE_EXTRA = {"DL", "JK"}


@functools.lru_cache(maxsize=1)
def spec(version: str = "v1") -> dict:
    return yaml.safe_load((ROOT / "scoring" / f"weights_{version}.yaml").read_text())


@functools.lru_cache(maxsize=1)
def fact() -> pd.DataFrame:
    return pd.read_parquet(CUR / "fact_indicator.parquet")


@functools.lru_cache(maxsize=1)
def dim_state() -> pd.DataFrame:
    return pd.read_parquet(CUR / "dim_state.parquet")


def registry() -> dict:
    p = ROOT / "models" / "registry.json"
    return json.loads(p.read_text()) if p.exists() else {}


def latest(features=None, quality=("official", "derived")) -> pd.DataFrame:
    """Latest observed row per state x feature (no filling)."""
    f = fact()
    f = f[f.quality.isin(quality)]
    if features is not None:
        f = f[f.feature_code.isin(list(features))]
    f = f.assign(_k=f.period.astype(str)).sort_values("_k")
    return f.groupby(["state_id", "feature_code"]).tail(1).drop(columns="_k")


def reference_ids() -> list[str]:
    d = dim_state()
    return sorted(set(d[d.kind.isin(REFERENCE_KINDS)].state_id) | REFERENCE_EXTRA)


def forecasts() -> pd.DataFrame:
    p = CUR / "forecast_manufacturing.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=["state_id", "forecast_fy", "forecast", "lo", "hi"])


@functools.lru_cache(maxsize=1)
def _register_urls() -> dict:
    reg = pd.read_csv(ROOT / "data" / "source_register.csv", dtype=str).fillna("")
    return dict(zip(reg.local_path, reg.url))


def sources_url(source_file: str) -> str:
    """Official URL(s) of the raw file(s) behind a value."""
    urls = _register_urls()
    return " ; ".join(dict.fromkeys(urls.get(f, "") for f in str(source_file).split(";") if f))
