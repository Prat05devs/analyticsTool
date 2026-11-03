"""Policy (ease of doing business) and educated-labour indicators: values match the official documents."""
import pandas as pd
import pytest

from etl.common import CUR
from scoring.data import spec
from scoring.score import Profile, effective_weights, score
from ui.narrative import fmt

F = pd.read_parquet(CUR / "fact_indicator.parquet")


def v(sid, code):
    g = F[(F.state_id == sid) & (F.feature_code == code)]
    assert len(g) == 1, (sid, code, len(g))
    return g.iloc[0]


@pytest.mark.parametrize("sid,code,value", [
    # values as printed in the source documents
    ("TN", "brap_2024_top_achiever_areas", 4), ("GJ", "brap_2024_top_achiever_areas", 2),   # PIB 11 Nov 2025
    ("KA", "brap_2024_category", 2), ("MH", "brap_2024_category", 1),                      # Fast Mover / Aspirer
    ("TN", "leads_2025_tier", 4), ("RJ", "leads_2025_tier", 1), ("KA", "leads_2025_tier", 2),  # PIB 13 May 2026
    ("MH", "epi_2024_score", 68.01), ("RJ", "epi_2024_score", 47.31),                     # NITI EPI 2024 p. 35
    ("GJ", "startup_ranking_5_category", 5), ("TG", "startup_ranking_5_category", 3),     # Startup Ranking 5.0
    ("KA", "ger_higher_education", 41.9), ("TN", "ger_higher_education", 52.3),           # AISHE T-19
    ("KA", "college_density", 69), ("MH", "graduates_outturn", 702798 + 209285),          # AISHE T-4, T-33
    ("MH", "edu_secondary_plus_pct", 51.8), ("TG", "edu_graduate_plus_pct", 14.4 + 3.8),  # PLFS 2023-24 T(8)
    ("TN", "edu_diploma_pct", 4.5),
])
def test_values_match_official_documents(sid, code, value):
    assert v(sid, code).value == pytest.approx(value, abs=0.051)


def test_every_new_value_traces_to_a_registered_raw_file():
    reg = pd.read_csv("data/source_register.csv", dtype=str)
    codes = ["brap_2024_category", "leads_2025_tier", "epi_2024_score", "startup_ranking_5_category",
             "ger_higher_education", "graduates_per_lakh_pop", "edu_graduate_plus_pct"]
    for f in F[F.feature_code.isin(codes)].source_file:
        for part in str(f).split(";"):
            assert part in set(reg.local_path), part


def test_all_pilots_covered_for_policy_and_education():
    pilots = ["MH", "GJ", "KA", "TN", "TG", "UP", "RJ"]
    for code in ["brap_2024_category", "brap_2024_top_achiever_areas", "leads_2025_tier", "epi_2024_score",
                 "startup_ranking_5_category", "edu_graduate_plus_pct", "edu_secondary_plus_pct", "edu_diploma_pct",
                 "ger_higher_education", "graduates_per_lakh_pop"]:
        assert set(pilots) <= set(F[F.feature_code == code].state_id), code


def test_every_industry_scores_policy_and_education():
    s = spec()
    for ind, prof in s["industries"].items():
        assert "policy" in prof["weights"] and prof["indicators"]["policy"], ind
        edu = {"edu_graduate_plus_pct", "edu_secondary_plus_pct", "edu_diploma_pct", "ger_higher_education",
               "graduates_per_lakh_pop"}
        if ind != "logistics":  # logistics labour = drivers / warehouse pool; education enters via skilled-labour need
            assert edu & set(prof["indicators"]["labour"]), ind
    _, inds, _ = effective_weights(Profile("logistics", needs=["skilled_labour"]))
    assert "edu_graduate_plus_pct" in inds["labour"]


def test_ordinal_categories_display_as_labels():
    u = spec()["indicators"]["brap_2024_category"]["unit"]
    assert fmt(2.0, u) == "Fast Mover" and fmt(1.0, u) == "Aspirer"
    assert fmt(4.0, spec()["indicators"]["leads_2025_tier"]["unit"]) == "Exemplar"


def test_policy_reasons_use_category_labels_and_industry_reasons():
    r = score(Profile("logistics", priorities=["policy"]), with_stability=False)
    from scoring.score import reasons
    items = [x for sid in r.ranking.state_id for x in sum(reasons(r, sid, 5), []) if x["dimension"] == "policy"]
    assert items and all(x["why"] and x["priority"] for x in items)
