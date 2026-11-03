"""Phase 2: indicator table integrity, provenance and no-imputation guarantees."""
import duckdb
import pandas as pd
import pytest

from etl.common import CUR, REP, ROOT, WAREHOUSE
from etl.ingest_secondary import verify
from scoring.data import PILOT_IDS, spec


@pytest.fixture(scope="module")
def fact():
    return pd.read_parquet(CUR / "fact_indicator.parquet")


@pytest.fixture(scope="module")
def reg():
    return pd.read_csv(ROOT / "data/source_register.csv", dtype=str)


def test_schema(fact):
    for c in ["state_id", "period", "feature_code", "value", "unit", "source_id", "published_at", "source_file", "quality"]:
        assert c in fact.columns
    assert not fact.duplicated(["state_id", "period", "feature_code"]).any()
    assert fact.value.notna().all()  # missing values are absent rows, never filled


def test_every_value_traces_to_registered_raw_files(fact, reg):
    pairs = set(zip(reg.local_path, reg.sha256))
    for files, shas in fact[["source_file", "sha256"]].drop_duplicates().itertuples(index=False):
        for f, s in zip(files.split(";"), shas.split(";")):
            assert f.startswith("data/raw/"), f
            assert (f, s) in pairs, f


def test_quality_labels(fact):
    assert set(fact.quality) <= {"official", "derived", "secondary", "private"}


def test_secondary_values_are_verified_in_snapshot():
    """Re-running the verification reproduces exactly the admitted set (nothing added by hand)."""
    from etl.ingest_secondary import build
    stored = pd.read_parquet(CUR / "fact_indicator_secondary.parquet")
    fresh, rejected = build()
    assert len(stored) > 0
    key = ["state_id", "feature_code", "period", "value"]
    assert stored[key].sort_values(key).reset_index(drop=True).equals(fresh[key].sort_values(key).reset_index(drop=True))
    assert (rejected.reason.str.len() > 0).all()


def test_verify_requires_name_for_small_numbers():
    assert verify("Gujarat GST grew 17 per cent", 17, ["Gujarat"])
    assert not verify("Kerala grew 17 per cent", 17, ["Gujarat"])
    assert verify("collections were 3,61,777.65 crore", 361777.65, ["Nowhere"])  # long, specific figure


def test_hces_spot_values(fact):
    h = fact[fact.source_id == "hces_2023_24"].set_index(["state_id", "feature_code"]).value
    assert h[("GJ", "mpce_rural")] == 4116 and h[("UP", "mpce_urban")] == 5395 and h[("IN", "mpce_urban")] == 6996


def test_trai_spot_values(fact):
    t = fact[(fact.source_id == "trai_pir") & (fact.feature_code == "internet_subs_per_100")].set_index("state_id").value
    assert t["UP"] == 63.82 and t["TN"] == 88.43 and t["IN"] == 77.94 and t["AN"] == 113.36


def test_derived_population_is_plausible(fact):
    p = fact[(fact.feature_code == "population_derived") & (fact.period == "2024-25")].set_index("state_id").value
    assert 2.2e8 < p["UP"] < 2.6e8 and 3.5e7 < p["TG"] < 4.2e7


def test_no_imputation_for_telangana_rural_wage(fact):
    tg = fact[(fact.state_id == "TG") & fact.feature_code.str.startswith("rural_wage")]
    assert tg.empty


def test_eligibility_matrix_covers_7x6():
    m = pd.read_csv(REP / "eligibility_matrix.csv")
    assert len(m) == 7 * 6
    assert set(m.status) <= {"approve", "ranking-only", "exclude"}
    assert m.reason.notna().all()


def test_coverage_report_has_value_or_explicit_unavailable():
    c = pd.read_csv(REP / "indicator_coverage_pilots.csv")
    assert len(c) == 7 * len(spec()["indicators"])
    assert ((c.value.notna()) | (c.quality == "unavailable")).all()
    assert c[c.quality == "unavailable"].reason.notna().all()


def test_warehouse_tables():
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    names = {r[0] for r in con.execute("select table_name from information_schema.tables").fetchall()}
    assert {"dim_state", "fact_economic", "fact_indicator", "latest_indicator"} <= names
    con.close()


def test_pilots_in_reference():
    from scoring.data import reference_ids
    assert set(PILOT_IDS) <= set(reference_ids())
