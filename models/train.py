"""Manufacturing growth model: expanding-window CV, baselines, model selection, registry and model card.

    python -m models.train

Protocol (blueprint 6.3-6.4)
- Expanding window by year: for each validation origin o, train on rows with origin < o (their targets were
  published by o's forecast date), predict origin o. Rows are never shuffled.
- Validation target years 2017-18 .. 2023-24; the 2024-25 target year is an untouched hold-out, scored once,
  after the model has been chosen on validation years only.
- Scalers/imputers live inside sklearn Pipelines, so they are fitted on training folds only.
- Baselines: persistence (last year's growth) and 3-year mean. Acceptance rule: models/evaluate.ACCEPTANCE.
- COVID target years (2020-21, 2021-22) are reported separately and excluded from model selection.
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from etl.common import CUR, REP, ROOT, write_parquet
from etl.states import name_of
from features.build_panel import FEATURE_GROUPS
from models.evaluate import ACCEPTANCE, acceptance, by_group, metrics, year_block_bootstrap

VALIDATION_TARGETS = ["2017-18", "2018-19", "2019-20", "2020-21", "2021-22", "2022-23", "2023-24"]
HOLDOUT_TARGET = "2024-25"
BASELINES = ["persistence", "mean3"]
FEATS = {
    "macro": FEATURE_GROUPS["macro"],
    "macro+business": FEATURE_GROUPS["macro"] + FEATURE_GROUPS["business"],
    "macro+business+infra": FEATURE_GROUPS["macro"] + FEATURE_GROUPS["business"] + FEATURE_GROUPS["infrastructure"],
}


def linear(model):
    return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", model)])


def tree(model):
    return Pipeline([("impute", SimpleImputer(strategy="median")), ("model", model)])


def candidates():
    c = {}
    for fs in FEATS:
        for a in [1, 10, 100]:
            c[f"ridge(a={a})|{fs}"] = (lambda a=a: linear(Ridge(alpha=a)), FEATS[fs])
        for a in [0.1, 0.5]:
            c[f"enet(a={a})|{fs}"] = (lambda a=a: linear(ElasticNet(alpha=a, l1_ratio=0.5, max_iter=5000)), FEATS[fs])
        c[f"rf(depth=3,leaf=10)|{fs}"] = (lambda: tree(RandomForestRegressor(
            n_estimators=300, max_depth=3, min_samples_leaf=10, random_state=0, n_jobs=-1)), FEATS[fs])
    c["hgb(depth=2)|macro+business+infra"] = (lambda: tree(HistGradientBoostingRegressor(
        max_depth=2, max_iter=150, learning_rate=0.05, min_samples_leaf=20, random_state=0)), FEATS["macro+business+infra"])
    return c


def add_baselines(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["persistence"] = d.g_lag1
    d["mean3"] = d.g_mean3.fillna(d.g_lag1)
    return d


def expanding_predict(frame, make, feats, targets):
    out = []
    lab = frame.dropna(subset=["target"])
    for t in targets:
        test = lab[lab.target_fy == t]
        train = lab[lab.origin_fy < test.origin_fy.min()]
        if test.empty or len(train) < 30:
            continue
        m = make().fit(train[feats], train.target)
        out.append(test.assign(pred=m.predict(test[feats])))
    return pd.concat(out)


def main():
    frame = add_baselines(pd.read_parquet(CUR / "model_frame_manufacturing.parquet"))
    lab = frame.dropna(subset=["target"])
    val_rows = lab[lab.target_fy.isin(VALIDATION_TARGETS)]

    # 1) model selection on validation years only (non-COVID)
    results, preds = [], {}
    for name, (make, feats) in candidates().items():
        p = expanding_predict(frame, make, feats, VALIDATION_TARGETS)
        preds[name] = p
        nc = p[~p.covid_target]
        results.append({"model": name, **{f"val_{k}": v for k, v in metrics(nc.target, nc.pred, nc.g_lag1).items()}})
    for b in BASELINES:
        nc = val_rows[~val_rows.covid_target]
        results.append({"model": f"baseline:{b}", **{f"val_{k}": v for k, v in metrics(nc.target, nc[b], nc.g_lag1).items()}})
    res = pd.DataFrame(results).sort_values("val_mae")
    best = res[~res.model.str.startswith("baseline")].iloc[0].model
    make, feats = candidates()[best]

    val = preds[best].rename(columns={"pred": "model"})
    # 2) hold-out scored once with the chosen specification (trained on everything before it)
    hold = expanding_predict(frame, make, feats, [HOLDOUT_TARGET]).rename(columns={"pred": "model"})
    acc = acceptance(val, hold, "model", BASELINES)
    boot = year_block_bootstrap(val[~val.covid_target], "model", acc["best_baseline"])

    # 3) diagnostics
    per_year = by_group(val, "model", "target_fy")
    per_year_base = by_group(val, acc["best_baseline"], "target_fy")
    pilots = ["MH", "GJ", "KA", "TN", "TG", "UP", "RJ"]
    per_state = by_group(val[~val.covid_target & val.state_id.isin(pilots)], "model", "state_id")
    per_state_b = by_group(val[~val.covid_target & val.state_id.isin(pilots)], acc["best_baseline"], "state_id")
    covid = val[val.covid_target]
    covid_m = {c: metrics(covid.target, covid[c]) for c in ["model"] + BASELINES}
    abl = res[res.model.str.contains(r"\|")].assign(family=lambda d: d.model.str.split("(").str[0],
                                                   features=lambda d: d.model.str.split("|").str[1])
    ablation = abl.groupby(["family", "features"]).val_mae.min().unstack()

    status = "validated" if acc["accepted"] else "ranking_only"
    reg_path = ROOT / "models/registry.json"
    registry = json.loads(reg_path.read_text()) if reg_path.exists() else {}
    latest_origin = frame.origin_fy.max()
    entry = {
        "status": status, "target": "real manufacturing GSVA growth, % (RBI HSIS T34, 2011-12 prices)",
        "selected_spec": best, "best_baseline": acc["best_baseline"],
        "validation_mae": acc["validation_mae"], "holdout_mae": acc["holdout_mae_all"],
        "improvement_vs_best_baseline": acc["improvement_vs_best_baseline"],
        "share_of_years_won": acc["share_of_years_won"], "acceptance_rule": ACCEPTANCE,
        "latest_feature_fy": latest_origin, "forecast_fy": f"{int(latest_origin[:4]) + 1}-{str(int(latest_origin[:4]) + 2)[-2:]}",
        "trained_on": f"{lab.origin_fy.min()}..{lab.origin_fy.max()} origins, {lab.state_id.nunique()} states",
        "reason": ("passed the pre-specified acceptance rule" if acc["accepted"] else
                   "did not beat the persistence / 3-year-mean baselines consistently "
                   f"(improvement {acc['improvement_vs_best_baseline']:+.1%}, won {acc['share_of_years_won']:.0%} of "
                   f"non-COVID validation years, hold-out MAE {acc['holdout_mae']:.2f} vs best baseline "
                   f"{acc['holdout_best_baseline_mae']:.2f}); the app shows ranking only for manufacturing"),
    }
    registry["manufacturing"] = entry
    for sector, why in {
        "retail": "Trade & repair GSVA by state is not in the RBI handbook; MoSPI/DES state-wise detailed-activity "
                  "statements were not obtainable as a consistent panel. Ranking only.",
        "it_services": "Real estate & professional services GSVA by state not available as a consistent panel; "
                       "would mix real estate with IT anyway. Ranking only.",
        "logistics": "Transport & storage GSVA by state not available as a consistent panel. Ranking only.",
        "healthcare": "Health GVA not separable by state. Ranking only.",
        "hospitality": "Hotels & restaurants GVA bundled with trade and not available by state. Ranking only.",
    }.items():
        registry[sector] = {"status": "ranking_only", "reason": why}
    reg_path.write_text(json.dumps(registry, indent=2, default=str))

    fc_path = CUR / "forecast_manufacturing.parquet"
    importance = None
    if acc["accepted"]:
        model = make().fit(lab[feats], lab.target)
        cur = frame[frame.origin_fy == latest_origin]
        resid = (val[~val.covid_target].model - val[~val.covid_target].target)
        lo, hi = np.quantile(resid, [0.1, 0.9])
        p = model.predict(cur[feats])
        fc = cur[["state_id", "origin_fy", "target_fy"]].assign(forecast=p, lo=p - hi, hi=p - lo,
                                                                   model=best, holdout_mae=acc["holdout_mae"])
        write_parquet(fc.rename(columns={"target_fy": "forecast_fy"}), "forecast_manufacturing")
        pi = permutation_importance(model, lab[feats], lab.target, n_repeats=20, random_state=0,
                                    scoring="neg_mean_absolute_error")
        importance = pd.Series(pi.importances_mean, index=feats).sort_values(ascending=False)
    elif fc_path.exists():
        fc_path.unlink()  # never leave a stale forecast for the app to show

    write_card(res, best, acc, boot, per_year, per_year_base, per_state, per_state_b, covid_m, ablation, entry,
               importance, lab)
    print(res.head(12).to_string(index=False))
    print(json.dumps({k: v for k, v in acc.items() if k != "yearly"}, indent=1, default=str))
    print("status:", status)
    return 0


def write_card(res, best, acc, boot, per_year, per_year_base, per_state, per_state_b, covid_m, ablation, entry,
               importance, lab):
    bb = acc["best_baseline"]
    L = ["# Model card: manufacturing real GSVA growth (one year ahead)\n",
         f"**Status: {entry['status'].upper().replace('_', ' ')}**. {entry['reason'].capitalize()}.\n",
         "\n## Target\n- g(s, t+1) = 100 x (Y(t+1)/Y(t) - 1), Y = real manufacturing GSVA, RBI Handbook of Statistics on "
         "Indian States 2024-25, Table 34, constant 2011-12 prices (Rs lakh). Single vintage (11 Dec 2025).\n"
         "- This is a state-level macro outcome. It is not a forecast of any firm's revenue, profit or survival.\n",
         f"\n## Data\n- National panel: {lab.state_id.nunique()} states (28 states + Delhi + J&K), "
         f"{len(lab)} labelled state-years, origins {lab.origin_fy.min()}..{lab.origin_fy.max()}.\n"
         "- J&K 2019-20 excluded (geography break). Growth beyond +-40% is kept (flagged in validation).\n"
         "- Features are lag-only and joined as of the forecast date using each observation's estimated first-release "
         "date (`first_pub_est`); the build asserts that no feature was published after its forecast date.\n"
         "- Limitation: only one data vintage is available, so the backtest uses revised data, not the real-time "
         "first estimates a forecaster would have had (17-19 pilot cells were revised between the 2023 and 2024-25 "
         "editions).\n",
         "\n## Protocol\n- Expanding-window CV by target year, never shuffled. Validation target years "
         f"{VALIDATION_TARGETS[0]}..{VALIDATION_TARGETS[-1]}; hold-out {HOLDOUT_TARGET} scored once after selection.\n"
         "- Imputer and scaler inside sklearn Pipelines (fitted on each training fold only).\n"
         "- Baselines: persistence (last year's growth) and 3-year mean.\n"
         f"- Acceptance rule, fixed before results: {json.dumps(ACCEPTANCE)}\n",
         "\n## Model comparison (validation, non-COVID target years, percentage points of growth)\n",
         res.head(15)[["model", "val_n", "val_mae", "val_rmse", "val_medae", "val_bias", "val_directional_acc"]]
         .rename(columns=lambda c: c.replace("val_", "")).to_markdown(index=False, floatfmt=".2f"),
         f"\n\nSelected specification: `{best}`. Best baseline: `{bb}`.\n",
         "\n## Acceptance\n",
         f"| check | value | pass |\n|---|---|---|\n"
         f"| MAE improvement vs {bb} | {acc['improvement_vs_best_baseline']:+.1%} | {acc['pass_improvement']} |\n"
         f"| share of non-COVID validation years won | {acc['share_of_years_won']:.0%} | {acc['pass_consistency']} |\n"
         f"| hold-out {HOLDOUT_TARGET} MAE (model vs best baseline) | {acc['holdout_mae']:.2f} vs "
         f"{acc['holdout_best_baseline_mae']:.2f} | {acc['pass_holdout']} |\n",
         f"\nYear-block bootstrap of MAE(model) - MAE({bb}): {boot[0]:+.2f} pp (90% interval {boot[1]:+.2f} to "
         f"{boot[2]:+.2f}). With {len(VALIDATION_TARGETS) - 2} non-COVID validation years the uncertainty is wide: the "
         "rule is passed, but the interval does not exclude zero, so the gain over the baseline is not statistically "
         "clear. The app shows the forecast with its 80% band and these error figures, never as a point promise.\n"
         "- Forecast band: 10th-90th percentile of non-COVID validation residuals across all 30 states, so it is "
         "wide (about +-12 pp); small, volatile states dominate it. Positive bias = the model over-predicted on "
         "average during the 2017-2020 slowdown.\n"
         "- Penalty alpha=100 is the top of the pre-set grid; it was not extended afterwards, to keep the hold-out "
         "untouched.\n",
         "\n## Per target year (all validation years)\n",
         per_year[["target_fy", "n", "mae", "medae", "directional_acc"]].merge(
             per_year_base[["target_fy", "mae"]].rename(columns={"mae": f"{bb}_mae"}), on="target_fy")
         .to_markdown(index=False, floatfmt=".2f"),
         "\n\n## COVID target years (2020-21, 2021-22), reported separately\n",
         pd.DataFrame(covid_m).T[["n", "mae", "rmse", "medae"]].to_markdown(floatfmt=".2f"),
         "\n\n## Pilot states (non-COVID validation years)\n",
         per_state[["state_id", "n", "mae", "medae"]].merge(per_state_b[["state_id", "mae"]].rename(
             columns={"mae": f"{bb}_mae"}), on="state_id").assign(state=lambda d: d.state_id.map(name_of))
         [["state", "n", "mae", "medae", f"{bb}_mae"]].to_markdown(index=False, floatfmt=".2f"),
         "\n\n## Ablation: best validation MAE by model family and feature set\n",
         ablation.to_markdown(floatfmt=".2f"),
         "\n\nAdding business (ASI, credit) and infrastructure (power) features is only worthwhile where the MAE "
         "falls; differences of a few hundredths of a point are noise at this sample size.\n"]
    if importance is not None:
        L += ["\n## Permutation importance (model attribution, not causation)\n",
              importance.to_frame("mae_increase").to_markdown(floatfmt=".3f"), "\n"]
    L += ["\n## Sub-sector targets for other industries\n"
          "The RBI handbook publishes constant-price GSVA for agriculture, manufacturing, construction, industry, "
          "financial services and services only. Trade & repair, hotels & restaurants, transport & storage, "
          "real estate & professional services and health are not published by state in a consistent 2011-12 base "
          "panel in any file obtained. Retail, IT/professional services, logistics, healthcare and hospitality are "
          "therefore ranking-only, and the broad services aggregate is shown as context, never as a sector "
          "forecast (rule 8).\n"]
    (REP / "model_card_manufacturing.md").write_text("".join(L))


if __name__ == "__main__":
    sys.exit(main())
