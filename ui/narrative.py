"""Deterministic text built only from scored numbers (no LLM, so no summary can contradict the figures)."""
from __future__ import annotations

import math

import pandas as pd

from etl.states import name_of
from scoring.data import registry, spec


def indian(n: float, decimals: int = 0) -> str:
    """12345678 -> '1,23,45,678' (Indian digit grouping)."""
    neg = n < 0
    s = f"{abs(n):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        whole = f"{head},{tail}"
    return ("-" if neg else "") + whole + (f".{frac}" if frac else "")


def fmt(v, unit: str = "") -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    u = unit.lower()
    if u.startswith("rs crore"):
        return f"₹{indian(v)} cr"
    if u.startswith("rs") and "day" in u:
        return f"₹{indian(v)}/day"
    if u.startswith("rs"):
        return f"₹{indian(v)}"
    if "%" in u:
        return f"{v:.1f}%" if abs(v) >= 1 or v == 0 else f"{v:.2f}%"
    if u in {"persons", "number"}:
        return indian(v)
    if "usd million" in u:
        return f"US${indian(v)} mn"
    if abs(v) >= 1000:
        return indian(v)
    return f"{v:.1f}" if abs(v) >= 10 else f"{v:.2f}"


def source_tag(row) -> str:
    f = str(row.source_file).split(";")[0]
    tbl = ""
    if "rbi_hsis" in f:
        tbl = "RBI " + f.split("/")[-1].split("_")[0]
    elif "hces" in f:
        tbl = "HCES 2023-24"
    elif "trai" in f:
        tbl = "TRAI PIR"
    elif "registry" in f:
        tbl = "Forecast model"
    if row.quality == "derived":
        tbl = (tbl + ", derived") if tbl else "derived"
    return f"{tbl} · {row.period}".strip(" ·")


def reasons(res, sid: str, k: int = 3) -> tuple[list[str], list[str]]:
    g = res.indicators[(res.indicators.state_id == sid) & res.indicators.observed].copy()
    g["lever"] = (g.score - 50) * g.w_ind_eff * g.dim_weight
    g = g[(g.value != g.pilot_median) | g.pilot_median.isna()]  # ties with every pilot say nothing

    def line(r):
        return (f"{r.label}: {fmt(r.value, r.unit)} vs pilot median {fmt(r.pilot_median, r.unit)} "
                f"({source_tag(r)})")
    pos = [line(r) for r in g.sort_values("lever", ascending=False).head(k).itertuples() if r.lever > 0]
    neg = [line(r) for r in g.sort_values("lever").head(k).itertuples() if r.lever < 0]
    return pos, neg


def managerial(res) -> str:
    """Plain-language reading of the ranking, built from dimension scores."""
    s = spec()
    rk = res.ranking
    dims = [c[4:] for c in rk.columns if c.startswith("dim_")]
    lab = {d: s["dimensions"][d]["label"].lower() for d in dims}
    parts = []
    for i, r in enumerate(rk.head(3).itertuples()):
        row = pd.Series({d: getattr(r, f"dim_{d}") for d in dims}).dropna()
        best, worst = row.idxmax(), row.idxmin()
        lead = ["leads", "follows", "is third"][i]
        parts.append(f"{r.state} {lead} ({r.score:.1f}): strongest on {lab[best]} ({row[best]:.0f}/100), "
                     f"weakest on {lab[worst]} ({row[worst]:.0f}/100).")
    gap = rk.score.iloc[0] - rk.score.iloc[1] if len(rk) > 1 else float("nan")
    if gap == gap and gap < 2:
        parts.append(f"The top two are {gap:.1f} points apart, which is within what a modest change of weights "
                     "can reverse: treat them as a tie and compare on site visits.")
    parts.append("State averages hide corridor- and district-level differences; use this list to decide where to "
                 "look next, not where to sign.")
    return " ".join(parts)


def model_explanation(industry: str) -> tuple[str, bool]:
    s = spec()["industries"][industry]
    target = s.get("model_target")
    reg = registry().get(target or industry, {})
    if not target or reg.get("status") != "validated":
        why = reg.get("reason") or s.get("target_note", "")
        return (f"Ranking only. {why} The outlook dimension therefore uses historical growth momentum, labelled as "
                "such, and no forecast is shown."), False
    vm, hm = reg["validation_mae"], reg["holdout_mae"]
    return (f"Next-year forecast of {reg['target']}: {reg['selected_spec'].split('|')[0]} on lagged growth, trained "
            f"with expanding-window CV ({reg['trained_on']}). Validation MAE {vm['model']:.1f} pp vs "
            f"{vm[reg['best_baseline']]:.1f} pp for the {reg['best_baseline'].replace('mean3', '3-year mean')} "
            f"baseline; untouched FY 2024-25 hold-out MAE {hm['model']:.1f} pp vs "
            f"{min(hm['persistence'], hm['mean3']):.1f} pp for the best baseline. The bootstrap interval for the gain "
            "crosses zero and the 80% band is about ±12 pp, so read the forecast as a direction, not a promise. "
            "Drivers (last year's growth, 3-year mean, national growth) are model attributions, not causes."), True


def counter(res) -> str | None:
    return res.counter


def disclosure_lines(res) -> list[str]:
    out = []
    for r in res.ranking.itertuples():
        if r.disclosure:
            out.append(f"{r.state}: {r.disclosure}")
    for r in res.excluded.itertuples():
        out.append(f"{r.state} excluded: {r.reason}")
    return out


def state_name(sid: str) -> str:
    return name_of(sid)
