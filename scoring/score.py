"""Suitability scoring engine (blueprint section 7).

    S(state, industry, user) = sum_j w(industry, user, j) x normalised_indicator(state, j)

- Normalisation: percentile rank (mid-rank, 0-100) of the state's latest value within a FROZEN national reference
  (28 states + Delhi + J&K, scoring/reference_<version>.parquet), so a state's score does not move when the user changes
  the comparison set. Cost/risk indicators (direction -1) are scored 100 - percentile.
- Missing data: never filled. A missing indicator is dropped and the remaining indicator weights in its dimension are
  renormalised; a dimension with no observed indicator is dropped and dimension weights are renormalised. Both are
  disclosed per state. A missing MANDATORY dimension excludes the state (etl/eligibility.py rule).
- Forecast factor: only when models/registry.json marks the industry's model 'validated'; otherwise the outlook
  dimension uses historical momentum only.
- Weights are design defaults (scoring/weights_<version>.yaml; v2 is current), not learned optima. The score is a relative screening
  index, NOT a probability of success.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from etl.common import ROOT
from etl.states import name_of
from scoring.data import CURRENT_VERSION, PILOT_IDS, forecasts, latest, reference_ids, registry, spec

def reference_path(version: str = CURRENT_VERSION):
    return ROOT / "scoring" / f"reference_{version}.parquet"


REFERENCE_PATH = reference_path()
FORECAST_SOURCE = "models/registry.json; data/curated/forecast_manufacturing.parquet"


# ---------------------------------------------------------------- reference -------------------------------------------
def build_reference(version: str = CURRENT_VERSION) -> pd.DataFrame:
    """Freeze the national reference distribution for every catalogue indicator (run once per weights version)."""
    s = spec(version)
    lat = latest(s["indicators"].keys())
    ref = lat[lat.state_id.isin(reference_ids())][["state_id", "feature_code", "value", "period"]]
    fc = forecasts()
    if len(fc):
        ref = pd.concat([ref, fc[fc.state_id.isin(reference_ids())].assign(
            feature_code="forecast_manufacturing", value=fc.forecast, period=fc.forecast_fy)[ref.columns]])
    ref.to_parquet(reference_path(version), index=False)
    return ref


def reference(version: str = CURRENT_VERSION) -> pd.DataFrame:
    if not reference_path(version).exists():
        return build_reference(version)
    return pd.read_parquet(reference_path(version))


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


def effective_weights(p: Profile, version: str = CURRENT_VERSION) -> tuple[dict, dict, list[str]]:
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
        if d not in dims:
            notes.append(f"Priority '{pr}': {prof['label']} has no {s['dimensions'][d]['label'].lower()} dimension, "
                         "so it does not change the scores.")
            continue
        dims[d] = dims[d] * s["priorities"]["multiplier"]
        notes.append(f"Priority '{pr}': {s['dimensions'][d]['label']} weight x{s['priorities']['multiplier']}.")
    for need in p.needs:
        rule = s["operational_needs"][need]
        if rule["dimension"] not in dims:
            notes.append(f"Operational need '{need}' maps to a dimension the {prof['label']} profile does not have, "
                         "so it does not change the scores.")
            continue
        have = inds.setdefault(rule["dimension"], {})
        added = [i for i in rule.get("add", []) if i not in have]
        for i in added:  # the need brings its own indicators into a profile that lacks them
            have[i] = 1.0
        if added:
            notes.append(f"Operational need '{need}' adds {', '.join(added)} to "
                         f"{s['dimensions'][rule['dimension']]['label']}.")
        supported = [i for i in rule["boost"] if i in have]
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
def indicator_table(p: Profile, version: str = CURRENT_VERSION) -> pd.DataFrame:
    """Long table: state x indicator with raw value, period, provenance and normalised score (NaN if missing)."""
    s = spec(version)
    prof = s["industries"][p.industry]
    reg = registry()
    model_ok = reg.get(prof.get("model_target") or "", {}).get("status") == "validated"
    lat = latest().set_index(["state_id", "feature_code"])
    ref = reference(version)
    _, eff_inds, _ = effective_weights(p, version)   # industry profile plus indicators added by operational needs
    fc = forecasts().set_index("state_id") if model_ok else pd.DataFrame()
    rows = []
    for dim, inds in eff_inds.items():
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
    weights_version: str = CURRENT_VERSION
    profile: Profile | None = None


def score(p: Profile, version: str = CURRENT_VERSION, with_stability: bool = True) -> Result:
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
        return Result(p.industry, pd.DataFrame(), tab, dimw, notes, excluded, weights_version=version, profile=p,
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

    res = Result(p.industry, rk, t, dimw, notes, excluded, weights_version=version, profile=p)
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


def _lower_first(label: str) -> str:
    """'Manufacturing share of GSVA' -> 'manufacturing share of GSVA' (acronyms kept)."""
    return label if label[:2].isupper() else label[:1].lower() + label[1:]


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
    lab = _lower_first(s["indicators"][drv.index[0]]["label"]) if len(drv) else d
    lead = (f"{name_of(b)} scores {ds.loc[b, d]:.0f} vs {ds.loc[a, d]:.0f} for {name_of(a)} on "
            f"{s['dimensions'][d]['label'].lower()} (mainly {lab}).")
    if k < 1.15:
        return (f"{lead} The top two are close: raising that dimension's weight by about {100 * (k - 1):.0f}% would "
                f"put {name_of(b)} first, so treat them as a near-tie.")
    return f"{lead} If that dimension carried about {k:.1f}x its current weight, {name_of(b)} would rank first."


def reasons(res: Result, sid: str, k: int = 3) -> tuple[list[dict], list[dict]]:
    """Why a state ranks where it does: its strongest and weakest indicators RELATIVE TO THE OTHER COMPARED STATES.

    gap   = indicator score - median score of the other eligible states (percentile points); the raw difference from
            the peers' median must also be material (spec `reasons`), so a 0.03% vs 0.00% shortage is not a reason
    lever = gap x within-dimension weight x dimension weight (the user's effective weights)
    Strengths are the largest positive levers, watch-outs the largest negative ones; gaps under `min_gap` points are
    not reported. Each item carries the industry-specific reason the indicator is in the profile (`why`) and tags
    for the user's priorities and operational needs that raised its weight.
    """
    s = spec(res.weights_version)
    if res.ranking.empty:
        return [], []
    prof = s["industries"][res.industry]
    t = res.indicators[res.indicators.observed]
    me, others = t[t.state_id == sid], t[t.state_id != sid]
    p = res.profile or Profile(industry=res.industry)
    pri_dims = {s["priorities"]["map"].get(x) for x in p.priorities} - {None}
    if p.dimension_weights is not None:
        pri_dims = set()
    min_gap = s.get("reasons", {}).get("min_gap", 5)
    items = []
    for r in me.itertuples():
        o = others[others.indicator == r.indicator]
        if o.empty:
            continue
        gap = float(r.score - o.score.median())
        meta = s["indicators"][r.indicator]
        needs = [n for n in p.needs if r.indicator in s["operational_needs"][n]["boost"]
                 and s["operational_needs"][n]["dimension"] == r.dimension]
        why = prof.get("why", {}).get(r.indicator) or (s["operational_needs"][needs[0]]["why"] if needs else "")
        peer_med = float(o.value.median())
        floor = meta.get("min_diff", s.get("reasons", {}).get("min_rel_diff", 0.05) * abs(peer_med))
        if abs(r.value - peer_med) < floor:   # e.g. 0.03% vs 0.00% energy shortage: real but immaterial
            continue
        higher = gap * meta["direction"] > 0
        items.append({"indicator": r.indicator, "label": r.label, "dimension": r.dimension,
                      "dimension_label": s["dimensions"][r.dimension]["label"], "value": r.value, "unit": r.unit,
                      "period": r.period, "source_file": r.source_file, "quality": r.quality,
                      "peer_median": peer_med, "n_peers": int(o.state_id.nunique()),
                      "score": float(r.score), "gap": gap, "lever": gap * r.w_ind_eff * r.dim_weight,
                      "meaning": meta.get("hi" if higher else "lo", ""), "why": why,
                      "priority": r.dimension in pri_dims, "needs": needs})
    pos = sorted([x for x in items if x["gap"] >= min_gap and x["lever"] > 0], key=lambda x: -x["lever"])[:k]
    neg = sorted([x for x in items if x["gap"] <= -min_gap and x["lever"] < 0], key=lambda x: x["lever"])[:k]
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
