"""Phase 3: leakage, temporal CV and the acceptance gate."""
import json

import numpy as np
import pandas as pd
import pytest

from etl.common import CUR, ROOT
from models.evaluate import acceptance, metrics
from models.train import expanding_predict


@pytest.fixture(scope="module")
def frame():
    return pd.read_parquet(CUR / "model_frame_manufacturing.parquet")


def test_no_future_release_in_features(frame):
    assert (frame.max_feature_pub <= frame.forecast_date).all()


def test_target_definition(frame):
    econ = pd.read_parquet(CUR / "fact_economic.parquet")
    m = econ[econ.activity_code == "manufacturing"].set_index(["state_id", "fy"]).value_rs_lakh
    r = frame.dropna(subset=["target"]).iloc[0]
    assert r.target == pytest.approx(100 * (m[(r.state_id, r.target_fy)] / m[(r.state_id, r.origin_fy)] - 1))


def test_geography_break_never_a_target(frame):
    assert frame[(frame.state_id == "JK") & (frame.target_fy == "2019-20")].target.isna().all()
    assert frame[(frame.state_id == "JK") & (frame.origin_fy == "2019-20")].g_lag1.isna().all() if \
        len(frame[(frame.state_id == "JK") & (frame.origin_fy == "2019-20")]) else True


class Recorder:
    """A model that records which origins it was trained on."""
    seen = []

    def fit(self, X, y):
        Recorder.seen.append(set(X.index))
        return self

    def predict(self, X):
        return np.zeros(len(X))


def test_expanding_window_trains_only_on_earlier_origins(frame):
    Recorder.seen = []
    lab = frame.dropna(subset=["target"])
    out = expanding_predict(frame, Recorder, ["g_lag1"], ["2019-20", "2022-23"])
    for idx_set, t in zip(Recorder.seen, ["2019-20", "2022-23"]):
        test_origin = lab[lab.target_fy == t].origin_fy.min()
        assert lab.loc[list(idx_set)].origin_fy.max() < test_origin
    assert set(out.target_fy) == {"2019-20", "2022-23"}


def _synthetic(model_noise, base_noise, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for t in ["2017-18", "2018-19", "2019-20", "2022-23", "2023-24", "2024-25"]:
        y = rng.normal(6, 4, 30)
        rows.append(pd.DataFrame({"target_fy": t, "covid_target": False, "target": y, "g_lag1": y + rng.normal(0, 5, 30),
                                  "model": y + rng.normal(0, model_noise, 30),
                                  "persistence": y + rng.normal(0, base_noise, 30),
                                  "mean3": y + rng.normal(0, base_noise, 30)}))
    d = pd.concat(rows)
    return d[d.target_fy != "2024-25"], d[d.target_fy == "2024-25"]


def test_no_improvement_over_baseline_is_rejected():
    val, hold = _synthetic(model_noise=6, base_noise=3)
    assert not acceptance(val, hold, "model", ["persistence", "mean3"])["accepted"]


def test_clear_improvement_is_accepted():
    val, hold = _synthetic(model_noise=1, base_noise=5)
    assert acceptance(val, hold, "model", ["persistence", "mean3"])["accepted"]


def test_metrics():
    m = metrics([1, 2, 3], [2, 2, 5], lag1=[0, 0, 0])
    assert m["mae"] == pytest.approx(1.0) and m["medae"] == 1.0 and m["directional_acc"] == 1.0


def test_registry_and_forecast_consistent():
    reg = json.loads((ROOT / "models/registry.json").read_text())
    assert reg["manufacturing"]["status"] in {"validated", "ranking_only"}
    for s in ["retail", "it_services", "logistics", "healthcare", "hospitality"]:
        assert reg[s]["status"] == "ranking_only"  # no defensible sector-specific target (rule 8)
    fc = CUR / "forecast_manufacturing.parquet"
    assert fc.exists() == (reg["manufacturing"]["status"] == "validated")
    if fc.exists():
        f = pd.read_parquet(fc)
        assert "GJ" not in set(f.state_id)  # Gujarat's series ends in 2022-23: no forecast can be issued
        assert (f.lo < f.forecast).all() and (f.forecast < f.hi).all()
