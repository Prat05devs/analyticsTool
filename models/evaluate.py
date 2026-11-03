"""Metrics, time-aware uncertainty and the pre-specified acceptance rule (blueprint 6.4-6.5)."""
from __future__ import annotations

import numpy as np
import pandas as pd

# Pre-specified BEFORE looking at any result (blueprint: no invented accuracy target; must beat simple baselines)
ACCEPTANCE = {
    "mae_improvement_vs_best_baseline": 0.05,  # validation MAE (non-COVID years) at least 5% below the better baseline
    "min_share_of_years_won": 0.6,             # beats the better baseline in >= 60% of non-COVID validation years
    "holdout_not_worse": True,                 # untouched hold-out MAE <= best baseline's hold-out MAE
}


def metrics(y, p, lag1=None) -> dict:
    y, p = np.asarray(y, float), np.asarray(p, float)
    e = p - y
    out = {"n": int(len(y)), "mae": float(np.mean(np.abs(e))), "rmse": float(np.sqrt(np.mean(e ** 2))),
           "medae": float(np.median(np.abs(e))), "bias": float(np.mean(e))}
    if lag1 is not None:
        lag1 = np.asarray(lag1, float)
        out["directional_acc"] = float(np.mean(np.sign(p - lag1) == np.sign(y - lag1)))
    return out


def by_group(df: pd.DataFrame, pred_col: str, group: str) -> pd.DataFrame:
    rows = []
    for g, d in df.groupby(group):
        m = metrics(d.target, d[pred_col], d.g_lag1)
        rows.append({group: g, **m})
    return pd.DataFrame(rows)


def year_block_bootstrap(df: pd.DataFrame, a: str, b: str, n: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """MAE(a) - MAE(b) with a 90% interval, resampling whole target years (states within a year are correlated)."""
    rng = np.random.default_rng(seed)
    years = df.target_fy.unique()
    err = df.assign(ea=(df[a] - df.target).abs(), eb=(df[b] - df.target).abs())
    per_year = err.groupby("target_fy")[["ea", "eb"]].agg(["sum", "count"])
    diffs = []
    for _ in range(n):
        s = rng.choice(years, size=len(years), replace=True)
        t = per_year.loc[s]
        diffs.append(t[("ea", "sum")].sum() / t[("ea", "count")].sum() - t[("eb", "sum")].sum() / t[("eb", "count")].sum())
    point = err.ea.mean() - err.eb.mean()
    return float(point), float(np.quantile(diffs, 0.05)), float(np.quantile(diffs, 0.95))


def acceptance(val: pd.DataFrame, hold: pd.DataFrame, model_col: str, baselines: list[str]) -> dict:
    """Apply ACCEPTANCE. val/hold contain target, target_fy, covid_target and prediction columns."""
    v = val[~val.covid_target]
    maes = {c: float((v[c] - v.target).abs().mean()) for c in [model_col] + baselines}
    best_base = min(baselines, key=lambda c: maes[c])
    yearly = v.groupby("target_fy").apply(lambda d: pd.Series({
        "model": (d[model_col] - d.target).abs().mean(), "base": (d[best_base] - d.target).abs().mean()}),
        include_groups=False)
    share_won = float((yearly.model < yearly.base).mean())
    improvement = 1 - maes[model_col] / maes[best_base]
    hold_mae = {c: float((hold[c] - hold.target).abs().mean()) for c in [model_col] + baselines}
    best_hold = min(hold_mae[c] for c in baselines)
    checks = {
        "improvement_vs_best_baseline": improvement,
        "share_of_years_won": share_won,
        "holdout_mae": hold_mae[model_col],
        "holdout_best_baseline_mae": best_hold,
        "pass_improvement": improvement >= ACCEPTANCE["mae_improvement_vs_best_baseline"],
        "pass_consistency": share_won >= ACCEPTANCE["min_share_of_years_won"],
        "pass_holdout": hold_mae[model_col] <= best_hold,
        "best_baseline": best_base, "validation_mae": maes, "holdout_mae_all": hold_mae,
        "yearly": yearly.reset_index().to_dict("records"),
    }
    checks["accepted"] = bool(checks["pass_improvement"] and checks["pass_consistency"] and checks["pass_holdout"])
    return checks
