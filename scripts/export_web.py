"""Export everything the static web app needs into web/data/ (the Vercel build).

    python scripts/export_web.py

The browser re-runs the same scoring logic as scoring/score.py (web/engine.js). This bundle holds only values
already in the curated tables, each with its period, quality, raw file and official URL, plus the frozen national
reference, forecasts, model registry and weights spec. tests/test_web_parity.py checks that the JS engine
reproduces the Python scores.
"""
import json
import math
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from etl.states import name_of  # noqa: E402
from scoring.data import PILOT_IDS, latest, registry, sources_url, spec  # noqa: E402
from scoring.score import Profile, reasons, reference, score  # noqa: E402
from ui.charts import geo  # noqa: E402
from ui.state import DEMOS  # noqa: E402

OUT = ROOT / "web" / "data"


def clean(x):
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = spec()
    codes = list(s["indicators"])
    lat = latest(codes)
    lat = lat[lat.state_id.isin(PILOT_IDS)]
    ind = [{"s": r.state_id, "c": r.feature_code, "v": clean(float(r.value)), "u": r.unit, "p": str(r.period),
            "q": r.quality, "f": r.source_file, "url": sources_url(r.source_file), "n": r.note}
           for r in lat.itertuples()]
    ref = reference()
    refd = {}
    for code in codes:  # raw values: each engine applies the same transform to both sides (exact ties survive)
        refd[code] = [clean(float(v)) for v in ref[ref.feature_code == code].value if v == v]
    fc = pd.read_parquet(ROOT / "data/curated/forecast_manufacturing.parquet") \
        if (ROOT / "data/curated/forecast_manufacturing.parquet").exists() else pd.DataFrame()
    fcs = {r.state_id: {"v": float(r.forecast), "lo": float(r.lo), "hi": float(r.hi), "p": r.forecast_fy,
                        "mae": float(r.holdout_mae)} for r in fc.itertuples()}
    elig = pd.read_csv(ROOT / "reports/eligibility_matrix.csv").fillna("").to_dict("records")
    unavailable = pd.read_csv(ROOT / "reports/unavailable_sources.csv").fillna("").to_dict("records")
    secondary = latest(quality=("secondary", "private"))
    sec = [{"s": r.state_id, "c": r.feature_code, "v": float(r.value), "u": r.unit, "p": str(r.period), "q": r.quality,
            "url": sources_url(r.source_file), "n": r.note} for r in secondary.itertuples() if r.state_id != "IN"]
    bundle = {
        "generated": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "spec": s, "states": {sid: name_of(sid) for sid in PILOT_IDS}, "pilots": list(PILOT_IDS),
        "indicators": ind, "reference": refd, "forecasts": fcs, "registry": registry(),
        "eligibility": elig, "unavailable": unavailable, "secondary": sec,
        "demos": {k: {**v, "profile": {**v["profile"], "states": list(PILOT_IDS)}} for k, v in DEMOS.items()},
        "model_card": (ROOT / "reports/model_card_manufacturing.md").read_text(),
    }
    (OUT / "bundle.json").write_text(json.dumps(bundle, separators=(",", ":"), default=str, allow_nan=False))
    g = geo()
    for f in g["features"]:  # round coordinates: 3 decimals (~100 m) is plenty at this zoom
        def rnd(c):
            return [rnd(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 3), round(c[1], 3)]
        f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
    (OUT / "india_adm1.json").write_text(json.dumps(g, separators=(",", ":")))
    (ROOT / "web" / "coverage_heatmap.png").write_bytes((ROOT / "reports/coverage_heatmap.png").read_bytes())

    # parity fixtures: Python results for a spread of profiles
    cases = [d["profile"] | {"states": list(PILOT_IDS)} for d in DEMOS.values()]
    for ind_code in s["industries"]:
        cases.append({"industry": ind_code, "priorities": [], "needs": [], "states": list(PILOT_IDS)})
    cases += [{"industry": "retail", "priorities": ["cost", "demand"], "needs": ["digital_first"], "states": ["KA", "TG", "MH"]},
              {"industry": "hospitality", "priorities": ["policy"], "needs": ["power_intensive"], "states": list(PILOT_IDS),
               "current_state": "RJ", "exclude_current": True},
              {"industry": "manufacturing", "priorities": [], "needs": [], "states": list(PILOT_IDS),
               "dimension_weights": {"demand": 10, "infrastructure": 10, "outlook": 50, "labour": 10, "ecosystem": 10, "cost": 10}}]
    exp = []
    for c in cases:
        p = Profile(industry=c["industry"], priorities=c.get("priorities", []), needs=c.get("needs", []),
                    states=c["states"], current_state=c.get("current_state"), exclude_current=c.get("exclude_current", False),
                    dimension_weights=c.get("dimension_weights"))
        r = score(p)
        exp.append({"profile": c, "ranking": [{"s": x.state_id, "score": x.score, "rank": int(x.rank)} for x in r.ranking.itertuples()],
                    "weights": r.dim_weights, "counter": r.counter,
                    "reasons": {sid: [[x["indicator"] for x in part] for part in reasons(r, sid, 3)]
                                for sid in r.ranking.state_id},
                    "stability": [{"s": x.state_id, "same": float(x.share_same_rank)} for x in r.stability.itertuples()]
                    if r.stability is not None else []})
    (ROOT / "tests" / "fixtures" / "web_parity.json").write_text(json.dumps(exp, default=str))
    kb = (OUT / "bundle.json").stat().st_size // 1024
    print(f"bundle.json {kb} KB, {len(ind)} indicator values, {len(cases)} parity cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
