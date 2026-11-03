"""Phase 4: scoring engine, incl. the blueprint section 11 acceptance tests."""
import numpy as np
import pandas as pd
import pytest

import scoring.score as sc
from scoring.data import PILOT_IDS, spec
from scoring.score import Profile, effective_weights, percentile, score


def test_weights_are_versioned_design_defaults():
    s = spec()
    assert s["version"] == "v1"
    for ind, prof in s["industries"].items():
        assert sum(prof["weights"].values()) == 100, ind
        assert set(prof["weights"]) == set(s["dimensions"]), ind


def test_percentile_midrank_and_direction():
    ref = np.array([1.0, 2.0, 3.0, 4.0])
    assert percentile(4.0, ref) == 87.5 and percentile(0.0, ref) == 0.0 and percentile(9, ref) == 100
    assert np.isnan(percentile(float("nan"), ref))
    t = sc.indicator_table(Profile("manufacturing"))
    cost = t[(t.indicator == "rural_wage_nonagri") & t.score.notna()]
    hi, lo = cost.loc[cost.value.idxmax()], cost.loc[cost.value.idxmin()]
    assert hi.score < lo.score  # higher wage cost -> lower score


def test_score_bounds_and_ranks():
    r = score(Profile("manufacturing"))
    assert r.ranking.score.between(0, 100).all()
    assert list(r.ranking["rank"]) == list(range(1, len(r.ranking) + 1))


# --- section 11: "Variable selected with no observed data" -> exclude or mark unavailable, never score as observed
def test_missing_value_is_not_filled_and_is_disclosed():
    r = score(Profile("manufacturing"))
    tg = r.indicators[(r.indicators.state_id == "TG") & (r.indicators.indicator == "rural_wage_nonagri")]
    assert tg.score.isna().all() and not tg.observed.any()
    assert tg.w_ind_eff.isna().all() or (tg.w_ind_eff.fillna(0) == 0).all()
    assert "Rural non-farm wage" in r.ranking.set_index("state_id").disclosure["TG"]
    # renormalisation: TG's observed cost-indicator weights still sum to 1
    obs = r.indicators[(r.indicators.state_id == "TG") & (r.indicators.dimension == "cost") & r.indicators.observed]
    assert obs.w_ind_eff.sum() == pytest.approx(1.0)


def test_missing_value_never_gets_a_favourable_fill(monkeypatch):
    """Removing a state's best indicator must not raise its dimension score above the observed-only average."""
    base = score(Profile("retail"), with_stability=False)
    orig = sc.indicator_table

    def drop(p, version="v1"):
        t = orig(p, version)
        m = (t.state_id == "KA") & (t.indicator == "mpce_urban")
        t.loc[m, ["value", "score"]] = np.nan
        return t
    monkeypatch.setattr(sc, "indicator_table", drop)
    r = score(Profile("retail"), with_stability=False)
    ka = r.indicators[(r.indicators.state_id == "KA") & (r.indicators.dimension == "demand") & r.indicators.observed]
    expect = (ka.score * ka.w_ind).sum() / ka.w_ind.sum()
    assert r.ranking.set_index("state_id").dim_demand["KA"] == pytest.approx(expect)
    assert "Urban household spending" in r.ranking.set_index("state_id").disclosure["KA"]
    assert base.ranking.set_index("state_id").disclosure["KA"] == ""


# --- section 11: "State missing mandatory ..." and "Insufficient eligible states"
def test_state_without_mandatory_dimension_is_excluded(monkeypatch):
    orig = sc.indicator_table

    def wipe(p, version="v1"):
        t = orig(p, version)
        t.loc[(t.state_id == "RJ") & (t.dimension == "infrastructure"), ["value", "score"]] = np.nan
        return t
    monkeypatch.setattr(sc, "indicator_table", wipe)
    r = score(Profile("manufacturing"), with_stability=False)
    assert "RJ" in set(r.excluded.state_id) and "RJ" not in set(r.ranking.state_id)


def test_insufficient_states_gives_no_ranking():
    r = score(Profile("manufacturing", states=["MH"]))
    assert r.ranking.empty and "Fewer than two" in r.message


# --- section 11: "Different user priorities" -> ranking changes only through disclosed, versioned weights
def test_priorities_change_weights_transparently():
    w0, _, n0 = effective_weights(Profile("retail"))
    w1, _, n1 = effective_weights(Profile("retail", priorities=["cost"]))
    assert w1["cost"] > w0["cost"] and abs(sum(w1.values()) - 1) < 1e-9
    assert any("cost" in n.lower() for n in n1) and not n0
    a = score(Profile("retail", priorities=["cost"]), with_stability=False).ranking
    b = score(Profile("retail", priorities=["cost"]), with_stability=False).ranking
    pd.testing.assert_frame_equal(a, b)  # deterministic


def test_policy_priority_does_not_change_scores():
    a = score(Profile("logistics"), with_stability=False).ranking.set_index("state_id").score
    b = score(Profile("logistics", priorities=["policy"]), with_stability=False)
    assert np.allclose(a.sort_index(), b.ranking.set_index("state_id").score.sort_index())
    assert any("policy" in n.lower() for n in b.notes)


def test_too_many_priorities_rejected():
    with pytest.raises(ValueError):
        effective_weights(Profile("retail", priorities=["demand", "cost", "labour", "growth"]))


def test_unsupported_operational_need_is_disclosed_not_applied():
    w0, _, _ = effective_weights(Profile("manufacturing"))
    w1, _, notes = effective_weights(Profile("manufacturing", needs=["digital_first"]))
    assert w0 == w1 and any("no supported indicator" in n for n in notes)


def test_frozen_reference_scores_do_not_depend_on_comparison_set():
    full = score(Profile("it_services"), with_stability=False).ranking.set_index("state_id").score
    sub = score(Profile("it_services", states=["KA", "TG", "MH"]), with_stability=False).ranking.set_index("state_id").score
    assert np.allclose(full[sub.index], sub)


def test_exclude_current_state():
    r = score(Profile("retail", current_state="UP", exclude_current=True), with_stability=False)
    assert "UP" not in set(r.ranking.state_id)


def test_budget_is_context_only():
    a = score(Profile("retail"), with_stability=False).ranking.score
    b = score(Profile("retail", capital_rs_crore=8), with_stability=False)
    assert np.allclose(a, b.ranking.score) and any("capital" in n.lower() for n in b.notes)


# --- section 11: "Sector lacks defensible target" -> ranking-only and no fabricated forecast
def test_no_forecast_factor_for_ranking_only_sectors():
    for ind in ["retail", "it_services", "logistics", "healthcare", "hospitality"]:
        r = score(Profile(ind), with_stability=False)
        assert not r.indicators.indicator.str.startswith("forecast").any()


def test_forecast_factor_only_when_validated():
    from scoring.data import registry
    r = score(Profile("manufacturing"), with_stability=False)
    has = r.indicators.indicator.eq("forecast_manufacturing").any()
    assert has == (registry()["manufacturing"]["status"] == "validated")
    if has:  # Gujarat has no forecast -> missing, not filled
        gj = r.indicators[(r.indicators.state_id == "GJ") & (r.indicators.indicator == "forecast_manufacturing")]
        assert gj.score.isna().all()


def test_stability_and_counter_explanation():
    r = score(Profile("manufacturing", priorities=["infrastructure", "labour"],
                      needs=["power_intensive", "logistics_heavy"]))
    st = r.stability
    assert set(st.state_id) == set(r.ranking.state_id)
    assert st.share_top3.between(0, 1).all() and (st.best_rank <= st["rank"]).all()
    assert r.counter and r.ranking.state.iloc[1] in r.counter


def test_all_industries_score_all_pilots():
    for ind in spec()["industries"]:
        r = score(Profile(ind), with_stability=False)
        assert len(r.ranking) + len(r.excluded) == len(PILOT_IDS)


def test_whatif_override_sets_final_dimension_weights():
    base = Profile("manufacturing", priorities=["infrastructure"], needs=["power_intensive"])
    w, _, _ = effective_weights(base)
    w2, inds2, notes = effective_weights(Profile(**{**base.__dict__, "dimension_weights": {k: v * 100 for k, v in w.items()}}))
    assert all(abs(w[k] - w2[k]) < 1e-9 for k in w)          # same starting point, no double multiplication
    assert inds2["infrastructure"]["power_shortage_pct"] == 4  # indicator boost from the need still applies
    a = score(base, with_stability=False).ranking.set_index("state_id").score
    b = score(Profile(**{**base.__dict__, "dimension_weights": {k: v * 100 for k, v in w.items()}}),
              with_stability=False).ranking.set_index("state_id").score
    assert np.allclose(a.sort_index(), b.sort_index())
