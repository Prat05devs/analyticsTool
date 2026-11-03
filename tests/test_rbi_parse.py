"""Phase 1: parsing, state mapping and panel integrity for the RBI handbook tables."""
import math

import pandas as pd
import pytest

from etl.common import CUR, ROOT
from etl.rbi_html import parse_html, to_number
from etl.states import PILOTS, normalize_state
from etl.validate import fixture_comparison, indian_format

RAW = ROOT / "data/raw/rbi_hsis/2025-12-11"


@pytest.mark.parametrize("raw,expected", [
    ("50,70,622", 5070622.0), ("6,334", 6334.0), ("12.4*", 12.4), ("(3.2)", -3.2), ("1,08,01,71,70", 1080171 * 100 + 70),
])
def test_to_number(raw, expected):
    assert to_number(raw) == expected


@pytest.mark.parametrize("raw", ["-", "–", ".", "", "NA"])
def test_not_available_is_nan(raw):
    assert math.isnan(to_number(raw))


@pytest.mark.parametrize("raw,sid", [
    ("Odisha3", "OR"), ("Andaman & Nicobar Islands#", "AN"), ("UttarPradesh", "UP"), ("Telangana@", "TG"),
    ("Jammu & Kashmir*", "JK"), ("Jammu & Kashmir and Ladakh", "JK"), ("ALL INDIA2", "IN"), ("Tamil nadu", "TN"),
])
def test_state_aliases(raw, sid):
    assert normalize_state(raw) == sid


@pytest.mark.parametrize("raw", ["NORTHERN REGION", "Mumbai", "Others", "North East-II**", "Uttar Pradesh-(E&W)"])
def test_non_state_rows_are_dropped(raw):
    assert normalize_state(raw) is None


def test_unknown_label_fails_loudly():
    with pytest.raises(KeyError):
        normalize_state("Atlantis")


def test_every_raw_label_is_mapped():
    for p in RAW.glob("*.html"):
        cells, _, _ = parse_html(p)
        for c in cells:
            normalize_state(c.state_raw)  # raises on an unmapped label


def test_t34_known_cells_from_raw():
    cells, unit, title = parse_html(RAW / "T34_gsva_manufacturing_constant.html")
    assert "Lakh" in unit and "MANUFACTURING" in title.upper()
    d = {(normalize_state(c.state_raw), c.header[-1]): to_number(c.value_raw) for c in cells
         if normalize_state(c.state_raw)}
    assert d[("AP", "2011-12")] == 5070622
    assert d[("UP", "2011-12")] == 8763582
    assert math.isnan(d[("GJ", "2024-25")])  # '-' in source


@pytest.fixture(scope="module")
def econ():
    return pd.read_parquet(CUR / "fact_economic.parquet")


def test_single_price_base(econ):
    assert econ.base_year.unique().tolist() == ["2011-12"]
    assert (econ.real_nominal == "real").all()


def test_no_duplicates(econ):
    assert not econ.duplicated(["state_id", "fy", "activity_code"]).any()
    ind = pd.read_parquet(CUR / "fact_indicator_rbi.parquet")
    assert not ind.duplicated(["state_id", "period", "feature_code"]).any()


def test_every_row_traces_to_registered_raw_file(econ):
    reg = pd.read_csv(ROOT / "data/source_register.csv", dtype=str)
    assert set(econ.source_file) <= set(reg.local_path)
    assert set(zip(econ.source_file, econ.sha256)) <= set(zip(reg.local_path, reg.sha256))


def test_pilot_coverage(econ):
    m = econ[econ.activity_code == "manufacturing"]
    for p in PILOTS:
        sid = normalize_state(p)
        n = m[(m.state_id == sid)].value_rs_lakh.notna().sum()
        assert n >= 12, p  # Gujarat is the shortest at 12 (2011-12..2022-23)


def test_fixture_differences_are_revisions_not_parsing_bugs(econ):
    fx, n = fixture_comparison(econ)
    assert n >= 80
    assert not fx.classification.str.startswith("PARSING").any()
    # the research note's spot check: Gujarat 2021-22 was 43,722,492 in the 2023 edition and is revised now
    row = fx[(fx.state == "Gujarat") & (fx.fy == "2021-22")].iloc[0]
    assert row.ed2023 == 43722492 and row.classification.startswith("edition revision")


def test_indian_format():
    assert indian_format(5070622) == "50,70,622"
    assert indian_format(108017170) == "10,80,17,170"
    assert indian_format(999) == "999"


def test_units_converted_once():
    ind = pd.read_parquet(CUR / "fact_indicator_rbi.parquet")
    ur = ind[ind.feature_code == "ur_urban_us_adj"].value.dropna()
    assert ur.max() < 40  # per cent, not per thousand
    ftv = ind[(ind.feature_code == "foreign_tourist_visits") & (ind.state_id == "MH")].value.dropna()
    assert ftv.max() < 10  # million, not lakh
