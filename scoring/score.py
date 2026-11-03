"""Suitability scoring engine (blueprint section 7).

    S(state, industry, user) = sum_j w(industry, user, j) x normalised_indicator(state, j)

- Normalisation: percentile rank (mid-rank, 0-100) of the state's latest value within a FROZEN national reference
  (28 states + Delhi + J&K, scoring/reference_v1.parquet), so a state's score does not move when the user changes
  the comparison set. Cost/risk indicators (direction -1) are scored 100 - percentile.
- Missing data: never filled. A missing indicator is dropped and the remaining indicator weights in its dimension are
  renormalised; a dimension with no observed indicator is dropped and dimension weights are renormalised. Both are
  disclosed per state. A missing MANDATORY dimension excludes the state (etl/eligibility.py rule).
- Forecast factor: only when models/registry.json marks the industry's model 'validated'; otherwise the outlook
  dimension uses historical momentum only.
- Weights are design defaults (scoring/weights_v1.yaml), not learned optima. The score is a relative screening
  index, NOT a probability of success.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from etl.common import ROOT
from etl.states import name_of
from scoring.data import PILOT_IDS, forecasts, latest, reference_ids, registry, spec

REFERENCE_PATH = ROOT / "scoring" / "reference_v1.parquet"
FORECAST_SOURCE = "models/registry.json; data/curated/forecast_manufacturing.parquet"


# ---------------------------------------------------------------- reference -------------------------------------------
def build_reference(version: str = "v1") -> pd.DataFrame:
    """Freeze the national reference distribution for every catalogue indicator (run once per weights version)."""
    s = spec(version)
    lat = latest(s["indicators"].keys())
    ref = lat[lat.state_id.isin(reference_ids())][["state_id", "feature_code", "value", "period"]]
    fc = forecasts()
    if len(fc):
        ref = pd.concat([ref, fc[fc.state_id.isin(reference_ids())].assign(
            feature_code="forecast_manufacturing", value=fc.forecast, period=fc.forecast_fy)[ref.columns]])
    ref.to_parquet(REFERENCE_PATH, index=False)
    return ref


def reference() -> pd.DataFrame:
    if not REFERENCE_PATH.exists():
        return build_reference()
    return pd.read_parquet(REFERENCE_PATH)


def _transform(x, how):
    if how == "log":
        return math.log(x) if x and x > 0 else float("nan")
    return x


def percentile(x: float, ref_values: np.ndarray) -> float:
    """Mid-rank percentile of x in the reference sample (0-100)."""
    r = ref_values[~np.isnan(ref_values)]
    if len(r) == 0 or x is None or (isinstance(x, float) and math.isnan(x)):
        return float("nan")
    return float(100 * ((r < x).sum() + 0.5 * (r == x).sum()) / len(r))


# ---------------------------------------------------------------- inputs ----------------------------------------------
@dataclass
class Profile:
    industry: str
    priorities: list[str] = field(default_factory=list)       # up to 3 of demand/infrastructure/labour/cost/growth/policy
    needs: list[str] = field(default_factory=list)            # power_intensive, digital_first, logistics_heavy, skilled_labour
    states: list[str] = field(default_factory=lambda: list(PILOT_IDS))
    current_state: str | None = None
    exclude_current: bool = False
    capital_rs_crore: float | None = None
    dimension_weights: dict | None = None                      # what-if override (raw, renormalised)


def effective_weights(p: Profile, version: str = "v1") -> tuple[dict, dict, list[str]]:
    """Return (dimension weights summing to 1, indicator weights per dimension, notes)."""
    s = spec(version)
    prof = s["industries"][p.industry]
    notes = []
    # a what-if override sets the FINAL dimension weights: priority / need multipliers are not applied on top
    override = p.dimension_weights is not None
    dims = dict(p.dimension_weights or prof["weights"])
    inds = {d: dict(v) for d, v in prof["indicators"].items()}
    if len(p.priorities) > s["priorities"]["max_selected"]:
        raise ValueError(f"choose at most {s['priorities']['max_selected']} priorities")
    if override:
        notes.append("What-if: dimension weights set by hand (priorities already reflected in the starting values).")
    for pr in [] if override else p.priorities:
        d = s["priorities"]["map"].get(pr)
        if d is None:
            notes.append(s["priorities"]["policy_note"])
            continue
        dims[d] = dims.get(d, 0) * s["priorities"]["multiplier"]
        notes.append(f"Priority '{pr}': {s['dimensions'][d]['label']} weight x{s['priorities']['multiplier']}.")
    for need in p.needs:
        rule = s["operational_needs"][need]
        supported = [i for i in rule["boost"] if i in inds.get(rule["dimension"], {})]
        if not supported:
            notes.append(f"Operational need '{need}' has no supported indicator in the {prof['label']} profile, "
                         "so it does not change the scores.")
            continue
        if not override:
            dims[rule["dimension"]] *= rule["dim_multiplier"]
        for i in supported:
            inds[rule["dimension"]][i] *= rule["indicator_multiplier"]
        notes.append(f"Operational need '{need}': {s['dimensions'][rule['dimension']]['label']} weight "
                     f"x{rule['dim_multiplier']}, {', '.join(supported)} x{rule['indicator_multiplier']}.")
    if p.capital_rs_crore is not None:
        notes.append("Investment capital is recorded as context only: no auditable state-level capex or rent data "
                     "exists, so the budget does not change scores.")
    tot = sum(dims.values())
    return {d: w / tot for d, w in dims.items()}, inds, notes


# ---------------------------------------------------------------- core ------------------------------------------------
def indicator_table(p: Profile, version: str = "v1") -> pd.DataFrame:
    """Long table: state x indicator with raw value, period, provenance and normalised score (NaN if missing)."""
    s = spec(version)
    prof = s["industries"][p.industry]
    reg = registry()
    model_ok = reg.get(prof.get("model_target") or "", {}).get("status") == "validated"
    lat = latest().set_index(["state_id", "feature_code"])
    ref = reference()
    fc = forecasts().set_index("state_id") if model_ok else pd.DataFrame()
    rows = []
    for dim, inds in prof["indicators"].items():
        for code in inds:
            meta = s["indicators"][code]
            if meta.get("requires_model") and not model_ok:
                continue
            how = meta.get("transform")
            refv = np.array([_transform(v, how) for v in ref[ref.feature_code == code].value], dtype=float)
            for sid in p.states:
                row = {"state_id": sid, "state": name_of(sid), "dimension": dim, "indicator": code,
                       "label": meta["label"], "unit": meta["unit"], "direction": meta["direction"],
                       "proxy": meta.get("proxy", ""), "value": np.nan, "period": "", "source_file": "",
                       "quality": "", "note": ""}
                if meta.get("requires_model"):
                    if sid in fc.index:
                        f = fc.loc[sid]
                        row.update(value=f.forecast, period=f.forecast_fy, source_file=FORECAST_SOURCE,
                                   quality="model", note=f"80% band {f.lo:+.1f} to {f.hi:+.1f} pp; hold-out MAE "
                                                         f"{f.holdout_mae:.2f} pp")
                elif (sid, code) in lat.index:
                    r = lat.loc[(sid, code)]
                    row.update(value=r.value, period=r.period, source_file=r.source_file, quality=r.quality,
                               note=r.note)
                x = _transform(row["value"], how) if not pd.isna(row["value"]) else np.nan
                pct = percentile(x, refv)
                row["score"] = pct if meta["direction"] > 0 or np.isnan(pct) else 100 - pct
                rows.append(row)
    return pd.DataFrame(rows)


@dataclass
class Result:
    industry: str
    ranking: pd.DataFrame          # one row per state: score, rank, dimension scores, coverage, confidence
    indicators: pd.DataFrame       # long indicator table with weights used
    dim_weights: dict
    notes: list[str]
    excluded: pd.DataFrame
    stability: pd.DataFrame | None = None
    counter: str | None = None
    message: str | None = None
    weights_version: str = "v1"


def score(p: Profile, version: str = "v1", with_stability: bool = True) -> Result:
    s = spec(version)
    prof = s["industries"][p.industry]
    states = [x for x in p.states if not (p.exclude_current and x == p.current_state)]
    p = Profile(**{**p.__dict__, "states": states})
    dimw, indw, notes = effective_weights(p, version)
    tab = indicator_table(p, version)
    tab["w_ind"] = [indw[d][i] for d, i in zip(tab.dimension, tab.indicator)]

    # eligibility: every mandatory dimension needs at least one observed indicator
    obs = tab[tab.score.notna()]
    excl = []
    for sid in states:
        have = set(obs[obs.state_id == sid].dimension)
        miss = [d for d in prof["mandatory_dimensions"] if d not in have]
        if miss:
            excl.append({"state_id": sid, "state": name_of(sid),
                         "reason": f"no observed data for mandatory dimension(s): {', '.join(miss)}"})
    excluded = pd.DataFrame(excl, columns=["state_id", "state", "reason"])
    elig = [x for x in states if x not in set(excluded.state_id)]
    if len(elig) < 2:
        return Result(p.industry, pd.DataFrame(), tab, dimw, notes, excluded,
                      message="Fewer than two comparable states pass the mandatory data gates, so no ranking is shown.")

    # within-dimension renormalisation over OBSERVED indicators only
    t = tab[tab.state_id.isin(elig)].copy()
    t["observed"] = t.score.notna()
    t["w_ind_eff"] = t.w_ind.where(t.observed, 0)
    t["w_ind_eff"] = t.w_ind_eff / t.groupby(["state_id", "dimension"]).w_ind_eff.transform("sum").replace(0, np.nan)
    dim_scores = (t.assign(c=t.score.fillna(0) * t.w_ind_eff.fillna(0))
                  .groupby(["state_id", "dimension"]).agg(dim_score=("c", "sum"), n_obs=("observed", "sum")))
    dim_scores.loc[dim_scores.n_obs == 0, "dim_score"] = np.nan
    ds = dim_scores.dim_score.unstack()

    def total(row, weights):
        w = {d: weights[d] for d in weights if d in row.index and not pd.isna(row[d])}
        tw = sum(w.values())
        return sum(row[d] * w[d] for d in w) / tw if tw else np.nan

    rk = pd.DataFrame({"state_id": ds.index})
    rk["state"] = rk.state_id.map(name_of)
    rk["score"] = [total(ds.loc[sid], dimw) for sid in ds.index]
    for d in dimw:
        rk[f"dim_{d}"] = ds[d].values if d in ds else np.nan
    # disclosure + data confidence (never a success probability)
    disc, conf, cov = [], [], []
    for sid in rk.state_id:
        g = t[t.state_id == sid]
        dropped_dims = [d for d in dimw if pd.isna(ds.loc[sid].get(d, np.nan))]
        miss_ind = g[~g.observed].label.tolist()
        weight_cov = float((g.assign(w=g.w_ind / g.groupby("dimension").w_ind.transform("sum")
                                     * g.dimension.map(dimw)).query("observed").w.sum()))
        cov.append(weight_cov)
        msg = []
        if miss_ind:
            msg.append("not available: " + "; ".join(miss_ind))
        if dropped_dims:
            msg.append("dimension dropped and weights renormalised: " + ", ".join(dropped_dims))
        disc.append(" | ".join(msg))
        old = g[g.observed & g.period.astype(str).str[:4].str.isdigit()].period.astype(str).str[:4].astype(int)
        stale = int((old <= 2022).sum())
        proxy = int((g.observed & (g.proxy != "")).sum())
        level = "High" if weight_cov >= 0.95 and stale <= 2 else "Medium" if weight_cov >= 0.8 else "Low"
        conf.append(f"{level}: {weight_cov:.0%} of weighted indicators observed; {stale} older than 2023; "
                    f"{proxy} proxies")
    rk["weight_coverage"], rk["disclosure"], rk["data_confidence"] = cov, disc, conf
    rk = rk.sort_values("score", ascending=False).reset_index(drop=True)
    rk["rank"] = np.arange(1, len(rk) + 1)
    t = t.merge(t.groupby("state_id").size().rename("n_ind"), on="state_id")
    t["dim_weight"] = t.dimension.map(dimw)
    t["contribution"] = t.score * t.w_ind_eff * t.dim_weight
    pilot_median = t.groupby("indicator").value.median()
    t["pilot_median"] = t.indicator.map(pilot_median)

    res = Result(p.industry, rk, t, dimw, notes, excluded, weights_version=version)
    if with_stability:
        res.stability = stability(ds.loc[rk.state_id], dimw, s["stability"])
    res.counter = counter_explanation(rk, ds, dimw, t, s)
    return res


def stability(ds: pd.DataFrame, dimw: dict, cfg: dict) -> pd.DataFrame:
    """Share of perturbed weightings (each dimension weight x U(0.8, 1.2)) in which each state keeps its rank."""
    rng = np.random.default_rng(cfg["seed"])
    lo, hi = cfg["perturbation"]
    dims = [d for d in dimw]
    base = np.array([dimw[d] for d in dims])
    M = ds[dims].to_numpy(dtype=float)
    mask = ~np.isnan(M)
    Mz = np.nan_to_num(M)
    ranks = []
    for _ in range(cfg["draws"]):
        w = base * rng.uniform(lo, hi, len(dims))
        tot = (Mz * w).sum(1) / (mask * w).sum(1)
        ranks.append((-tot).argsort().argsort() + 1)
    R = np.array(ranks)
    base_tot = (Mz * base).sum(1) / (mask * base).sum(1)
    base_rank = (-base_tot).argsort().argsort() + 1
    return pd.DataFrame({"state_id": ds.index, "state": [name_of(x) for x in ds.index], "rank": base_rank,
                         "share_same_rank": (R == base_rank).mean(0), "share_top3": (R <= 3).mean(0),
                         "share_top1": (R == 1).mean(0), "best_rank": R.min(0), "worst_rank": R.max(0)}
                        ).sort_values("rank").reset_index(drop=True)


def counter_explanation(rk, ds, dimw, t, s) -> str | None:
    """One reason the runner-up could outperform the leader under different preferences (blueprint 7.2)."""
    if len(rk) < 2:
        return None
    a, b = rk.state_id.iloc[0], rk.state_id.iloc[1]
    gaps = {d: ds.loc[b, d] - ds.loc[a, d] for d in dimw if not pd.isna(ds.loc[a, d]) and not pd.isna(ds.loc[b, d])}
    d, gap = max(gaps.items(), key=lambda kv: kv[1])
    if gap <= 0:
        return (f"{name_of(b)} does not score higher than {name_of(a)} on any dimension, so no re-weighting of these "
                f"dimensions would put it first.")
    common = [x for x in dimw if x in gaps]
    sa = sum(dimw[x] * ds.loc[a, x] for x in common)
    sb = sum(dimw[x] * ds.loc[b, x] for x in common)
    k = 1 + (sa - sb) / (dimw[d] * gap)
    drv = t[(t.dimension == d) & t.state_id.isin([a, b])].pivot_table(index="indicator", columns="state_id",
                                                                        values="score")
    drv = (drv[b] - drv[a]).sort_values(ascending=False) if a in drv and b in drv else pd.Series(dtype=float)
    lab = s["indicators"][drv.index[0]]["label"].lower() if len(drv) else d
    lead = (f"{name_of(b)} scores {ds.loc[b, d]:.0f} vs {ds.loc[a, d]:.0f} for {name_of(a)} on "
            f"{s['dimensions'][d]['label'].lower()} (mainly {lab}).")
    if k < 1.15:
        return (f"{lead} The top two are close: raising that dimension's weight by about {100 * (k - 1):.0f}% would "
                f"put {name_of(b)} first, so treat them as a near-tie.")
    return f"{lead} If that dimension carried about {k:.1f}x its current weight, {name_of(b)} would rank first."


def reasons(res: Result, sid: str, k: int = 3) -> tuple[list[str], list[str]]:
    """Evidence-linked 'why' and 'why not': strongest and weakest weighted indicators vs the pilot median."""
    g = res.indicators[(res.indicators.state_id == sid) & res.indicators.observed].copy()
    g["lever"] = (g.score - 50) * g.w_ind_eff * g.dim_weight
    fmt = lambda r: (f"{r.label}: {fmt_value(r.value, r.unit)} ({r.period}) vs pilot median "
                     f"{fmt_value(r.pilot_median, r.unit)}; national percentile score {r.score:.0f}")
    pos = [fmt(r) for r in g.sort_values("lever", ascending=False).head(k).itertuples() if r.lever > 0]
    neg = [fmt(r) for r in g.sort_values("lever").head(k).itertuples() if r.lever < 0]
    return pos, neg


def fmt_value(v, unit="") -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    a = abs(v)
    if "Rs crore" in unit or a >= 1e5:
        s = f"{v:,.0f}"
    elif a >= 100:
        s = f"{v:,.0f}"
    elif a >= 10:
        s = f"{v:.1f}"
    else:
        s = f"{v:.2f}"
    return s
