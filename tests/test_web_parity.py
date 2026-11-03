"""The static web app's JS engine (web/engine.js) must reproduce the Python scoring engine."""
import json
import shutil
import subprocess

import pytest

from etl.common import ROOT

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


@pytest.fixture(scope="module")
def pair():
    exp = json.loads((ROOT / "tests/fixtures/web_parity.json").read_text())
    got = json.loads(subprocess.run(["node", str(ROOT / "tests/web_parity.js")], capture_output=True, text=True,
                                    check=True).stdout)
    return exp, got


def test_same_cases(pair):
    exp, got = pair
    assert len(exp) == len(got) >= 10


def test_scores_and_ranks_match(pair):
    for e, g in zip(*pair):
        assert [x["s"] for x in e["ranking"]] == [x["s"] for x in g["ranking"]], e["profile"]
        for a, b in zip(e["ranking"], g["ranking"]):
            assert a["score"] == pytest.approx(b["score"], abs=1e-9)
        for d, w in e["weights"].items():
            assert g["weights"][d] == pytest.approx(w, abs=1e-12)


def test_counter_explanation_matches(pair):
    for e, g in zip(*pair):
        assert e["counter"] == g["counter"], e["profile"]


def test_stability_close(pair):
    """Different PRNGs (NumPy vs mulberry32), so shares agree only within sampling error."""
    for e, g in zip(*pair):
        gs = {x["s"]: x["same"] for x in g["stability"]}
        for x in e["stability"]:
            assert abs(x["same"] - gs[x["s"]]) <= 0.08, (e["profile"], x)


def test_reasons_match(pair):
    """Strengths and watch-outs (indicator and order) are identical in the browser and in Python."""
    for e, g in zip(*pair):
        assert e["reasons"] == g["reasons"], e["profile"]
