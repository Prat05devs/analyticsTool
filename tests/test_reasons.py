"""Strengths and watch-outs must be relevant to the industry and explain the rank relative to the compared states."""
import pytest

from scoring.data import spec
from scoring.score import Profile, reasons, score

S = spec()
INDUSTRIES = list(S["industries"])


@pytest.mark.parametrize("industry", INDUSTRIES)
def test_every_profile_indicator_has_a_business_reason(industry):
    prof = S["industries"][industry]
    for dim, inds in prof["indicators"].items():
        for code in inds:
            assert prof["why"].get(code), (industry, code)
            assert S["indicators"][code].get("hi") and S["indicators"][code].get("lo"), code


def test_needs_have_reasons_and_known_indicators():
    for need, rule in S["operational_needs"].items():
        assert rule["why"], need
        assert set(rule["add"]) <= set(rule["boost"]) <= set(S["indicators"]), need


def test_healthcare_reasons_never_cite_internet_or_unemployment():
    """The user-reported case: healthcare strengths cited internet subscriptions, watch-outs urban unemployment."""
    r = score(Profile("healthcare"), with_stability=False)
    cited = {x["indicator"] for sid in r.ranking.state_id for part in reasons(r, sid, 3) for x in part}
    assert cited and not cited & {"internet_subs_per_100", "internet_subs_per_100_urban", "ur_urban_us_adj",
                                  "ur_rural_us_adj"}


def test_digital_first_need_brings_internet_into_healthcare_reasons():
    r = score(Profile("healthcare", needs=["digital_first"]), with_stability=False)
    items = [x for sid in r.ranking.state_id for part in reasons(r, sid, 5) for x in part]
    net = [x for x in items if x["indicator"].startswith("internet")]
    assert net and all(x["needs"] == ["digital_first"] and x["why"] == S["operational_needs"]["digital_first"]["why"]
                       for x in net)


@pytest.mark.parametrize("industry", INDUSTRIES)
def test_reasons_are_relative_to_the_other_compared_states(industry):
    r = score(Profile(industry), with_stability=False)
    for sid in r.ranking.state_id:
        pos, neg = reasons(r, sid, 3)
        for x in pos:
            assert x["gap"] >= S["reasons"]["min_gap"] and x["lever"] > 0
            assert (x["value"] - x["peer_median"]) * S["indicators"][x["indicator"]]["direction"] > 0, x
        for x in neg:
            assert x["gap"] <= -S["reasons"]["min_gap"] and x["lever"] < 0
            assert (x["value"] - x["peer_median"]) * S["indicators"][x["indicator"]]["direction"] < 0, x
        for x in pos + neg:  # every cited indicator belongs to this industry's profile
            assert x["indicator"] in S["industries"][industry]["indicators"][x["dimension"]]
            assert x["n_peers"] >= 1


def test_immaterial_differences_are_not_reasons():
    """0.03% vs 0.00% energy shortage scores far apart nationally but is not a business difference."""
    r = score(Profile("manufacturing"), with_stability=False)
    for sid in r.ranking.state_id:
        for x in sum(reasons(r, sid, 10), []):
            floor = S["indicators"][x["indicator"]].get("min_diff", S["reasons"]["min_rel_diff"] * abs(x["peer_median"]))
            assert abs(x["value"] - x["peer_median"]) >= floor, x


def test_priorities_tag_and_reweight_reasons():
    base = score(Profile("retail"), with_stability=False)
    pri = score(Profile("retail", priorities=["cost"]), with_stability=False)
    tagged = [x for sid in pri.ranking.state_id for x in sum(reasons(pri, sid, 3), []) if x["dimension"] == "cost"]
    assert tagged and all(x["priority"] for x in tagged)
    b = {x["indicator"]: x["lever"] for x in sum(reasons(base, "TG", 10), [])}
    p = {x["indicator"]: x["lever"] for x in sum(reasons(pri, "TG", 10), [])}
    common = [k for k in b if k in p and S["industries"]["retail"]["indicators"].get("cost", {}).get(k)]
    assert all(abs(p[k]) > abs(b[k]) for k in common)
