"""Phase 5: every page renders without exceptions for both demo scenarios (Streamlit AppTest, headless)."""
import pytest
from streamlit.testing.v1 import AppTest

from etl.common import ROOT
from scoring.data import PILOT_IDS
from ui.state import DEMOS

PAGES = ["pages/home.py", "pages/profile.py", "pages/eligibility.py", "pages/results.py", "pages/methods.py"]


def _run(page, profile=None):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    if profile:
        at.session_state["profile"] = profile
    at.run()
    if page != "pages/home.py":
        at.switch_page(page).run()
    return at


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("demo", list(DEMOS))
def test_pages_render(page, demo):
    at = _run(page, {**DEMOS[demo]["profile"], "states": list(PILOT_IDS)})
    assert not at.exception, [e.message for e in at.exception]


def test_results_never_call_score_a_probability():
    at = _run("pages/results.py", {**DEMOS["up_manufacturer"]["profile"], "states": list(PILOT_IDS)})
    text = " ".join(m.value for m in at.markdown).lower()
    assert "not a probability of success" in text
    assert "probability of success:" not in text


def test_ranking_only_industry_shows_no_forecast():
    at = _run("pages/results.py", {**DEMOS["it_services_mh"]["profile"], "states": list(PILOT_IDS)})
    text = " ".join(m.value for m in at.markdown)
    assert "Ranking only" in text and "Forecast · manufacturing" not in text


def test_insufficient_states_message():
    at = _run("pages/results.py", {**DEMOS["up_manufacturer"]["profile"], "states": ["UP", "MH"],
                                   "exclude_current": True})
    assert not at.exception
    assert any("Fewer than two" in m.value for m in at.markdown)
