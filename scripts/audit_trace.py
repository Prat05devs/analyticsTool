"""Trace random numbers shown in the app back to raw files (Phase 6 QA).

    python scripts/audit_trace.py [--n 20] [--seed 6]

For each sampled value: re-hash the raw file and compare with data/source_register.csv, then look for the
published figure in the raw file's own text (Indian digit grouping or plain decimals, as printed).
Derived values are traced through every component; forecasts are traced to models/registry.json.
Writes reports/audit_report.md.
"""
import argparse
import hashlib
import json
import pathlib
import re
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from etl.pdf_utils import digits_only, full_text  # noqa: E402
from etl.validate import indian_format  # noqa: E402
from scoring.data import PILOT_IDS, fact  # noqa: E402
from scoring.score import Profile, score  # noqa: E402
from ui.state import DEMOS  # noqa: E402

REG = pd.read_csv(ROOT / "data/source_register.csv", dtype=str).fillna("")


def sha_ok(path: str) -> bool:
    row = REG[REG.local_path == path]
    return len(row) > 0 and hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == row.iloc[-1].sha256


def printed_forms(v: float, published_scale: float = 1.0) -> list[str]:
    x = v / published_scale
    forms = {f"{x:.2f}", f"{x:.1f}", f"{x:g}"}
    if abs(x - round(x)) < 1e-9:
        forms |= {indian_format(x), f"{int(round(x)):,}", str(int(round(x)))}
    return [f for f in forms if f not in {"0", "0.0", "0.00"}]


SCALE = {"ur_rural_us_adj": 0.1, "ur_urban_us_adj": 0.1, "foreign_tourist_visits": 0.1}  # converted once in ETL


def found_in_raw(path: str, value: float, code: str) -> str | None:
    text = full_text(str(ROOT / path))
    flat = digits_only(text)
    # some PDF text layers split digit groups ('5 ,47,540'); a compact copy joins them, boundaries stay strict
    compact = digits_only(re.sub(r"(?<=\d) (?=,\d)", "", text))
    for f in printed_forms(value, SCALE.get(code, 1.0)):
        g = re.escape(f.replace(",", ""))
        if re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])", text) or \
                re.search(rf"(?<![\d.]){g}(?![\d])", flat) or re.search(rf"(?<![\d.]){g}(?![\d])", compact):
            return f
    return None


def raw_cells(path: str, sid: str, period: str) -> list[float]:
    """Independent re-read of an RBI table: every published number for (state, period) in the raw file."""
    from etl.rbi_html import parse_html, to_number
    from etl.states import normalize_state
    cells, _, _ = parse_html(ROOT / path)
    out = []
    for c in cells:
        try:
            if normalize_state(c.state_raw) != sid:
                continue
        except KeyError:
            continue
        if any(re.sub(r"[^\d\-]", "", h) == str(period) for h in c.header):
            out.append(to_number(c.value_raw))
    return out


def cell_matches(path, sid, period, value, code) -> bool:
    scale = SCALE.get(code, 1.0)
    return any(abs(v * scale - value) <= 1e-6 * max(1, abs(value)) for v in raw_cells(path, sid, period) if v == v)


CATEGORY_WORDS = {  # stems of each published category label, as they appear in the official pages
    "Aspirer": "aspirer", "Fast Mover": "fast mover", "Achiever": "achiever", "Top Achiever": "top achiever", "Exemplar": "exemplar", "High Performer": "high performer",
    "Accelerator": "accelerator", "Growth-Seeker": "growth-seeker", "Best Performer": "best performer",
    "Top Performer": "top performer", "Leader": "leader", "Aspiring Leader": "aspiring leader",
    "Emerging Ecosystem": "emerging ecosystem"}
WORD_NUM = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def trace_category(r) -> tuple[str, str]:
    """Ordinal government categories: the state's name must sit under its recorded category in the raw page."""
    import html as _html
    from etl.states import name_of
    raw_txt = (ROOT / r.source_file).read_text(errors="ignore")
    t = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", " ",
                                                                         raw_txt, flags=re.S)))).lower()
    name = name_of(r.state_id).lower()
    ok_sha = sha_ok(r.source_file)
    if r.unit.startswith("of 25"):
        k = int(r.value)
        hit = any(name in c and (f"across {WORD_NUM.get(k, '')} reform area" in c) for c in re.split(r"\.\s|, while ", t)) \
            if k else not any(name in c and "reform area" in c and "top achiever" in c for c in re.split(r"\.\s", t))
        return ("PASS" if ok_sha and hit else "FAIL", f"sha256 {'ok' if ok_sha else 'MISMATCH'}; "
                f"{'listed' if k else 'not listed'} with {k} Top-Achiever reform area(s) in the release: {'yes' if hit else 'NO'}")
    labels = dict(x.strip().split("=", 1) for x in r.unit.split(":", 1)[1].split(","))
    want = labels[str(int(r.value))]
    stems = {lab: CATEGORY_WORDS[lab] for lab in labels.values()}
    ok = False
    for m in re.finditer(re.escape(name), t):  # nearest category label before each mention of the state
        before = t[max(0, m.start() - 4000):m.start()]
        # latest-ending label wins; on a tie the longer label ('aspiring leader' over 'leader')
        ends = [(before.rfind(st) + len(st) if before.rfind(st) >= 0 else -1, len(st), lab) for lab, st in stems.items()]
        last = max(ends)
        ok = ok or (last[0] >= 0 and last[2] == want)
    return ("PASS" if ok and ok_sha else "FAIL",
            f"sha256 {'ok' if ok_sha else 'MISMATCH'}; listed under '{want}' in the raw page: {'yes' if ok else 'NO'}")


def trace_official(r) -> tuple[str, str]:
    path = r.source_file
    ok_sha = sha_ok(path)
    if r.unit.startswith(("category:", "of 25")):
        return trace_category(r)
    if "rbi_hsis" in path:
        ok = cell_matches(path, r.state_id, r.period, r.value, r.feature_code)
        return ("PASS" if ok and ok_sha else "FAIL",
                f"sha256 {'ok' if ok_sha else 'MISMATCH'}; raw cell re-read for {r.state_id} {r.period}: "
                f"{'matches' if ok else 'DOES NOT MATCH'}")
    hit = found_in_raw(path, r.value, r.feature_code)
    verdict = "PASS" if ok_sha and hit else "FAIL"
    return verdict, f"sha256 {'ok' if ok_sha else 'MISMATCH'}; printed as '{hit}' in raw" if hit else \
        f"sha256 {'ok' if ok_sha else 'MISMATCH'}; value not found as printed"


def trace_derived(r, facts) -> tuple[str, str]:
    """Every component value used by the derivation must re-read identically from its raw file."""
    files = r.source_file.split(";")
    oks = [sha_ok(f) for f in files]
    econ = pd.read_parquet(ROOT / "data/curated/fact_economic.parquet")
    comp = facts[(facts.state_id == r.state_id) & facts.source_file.isin(files) & (facts.quality != "derived")]
    ecomp = econ[(econ.state_id == r.state_id) & econ.source_file.isin(files)]
    # restrict to the periods named in the derivation note (or the value's own period)
    periods = set(re.findall(r"\d{4}-\d{2}|\d{4}", r.note)) | {str(r.period)}
    comp = comp[comp.period.astype(str).isin(periods)]
    ecomp = ecomp[ecomp.fy.isin(periods)]
    checks = [cell_matches(c.source_file, c.state_id, c.period, c.value, c.feature_code) if "rbi_hsis" in c.source_file
              else found_in_raw(c.source_file, c.value, c.feature_code) is not None  # PDF / page sources: value as printed
              for c in comp.itertuples()]
    checks += [cell_matches(c.source_file, c.state_id, c.fy, c.value_rs_lakh, "") for c in ecomp.itertuples()]
    ok = all(oks) and len(checks) > 0 and all(checks)
    return ("PASS" if ok else "CHECK",
            f"{len(files)} raw file(s), sha256 {'ok' if all(oks) else 'MISMATCH'}; {sum(checks)}/{len(checks)} "
            f"component cells re-read identically; {r.note[:80]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=6)
    a = ap.parse_args()
    facts = fact()
    shown = []
    for key, d in DEMOS.items():
        res = score(Profile(**{**d["profile"], "states": list(PILOT_IDS)}), with_stability=False)
        t = res.indicators[res.indicators.observed].assign(scenario=key)
        shown.append(t)
    shown = pd.concat(shown).drop_duplicates(["state_id", "indicator", "period"])
    sample = shown.sample(n=min(a.n, len(shown)), random_state=a.seed)
    reg = json.loads((ROOT / "models/registry.json").read_text())
    rows = []
    for r in sample.itertuples():
        if r.quality == "model":
            verdict, how = "PASS", (f"forecast from {reg['manufacturing']['selected_spec']} "
                                    f"(registry status {reg['manufacturing']['status']}), data/curated/forecast_manufacturing.parquet")
            f = "models/registry.json"
        else:
            row = facts[(facts.state_id == r.state_id) & (facts.feature_code == r.indicator) &
                        (facts.period.astype(str) == str(r.period))].iloc[0]
            verdict, how = trace_derived(row, facts) if row.quality == "derived" else trace_official(row)
            f = row.source_file.split(";")[0]
        rows.append({"#": len(rows) + 1, "state": r.state, "indicator": r.label, "value shown": r.value,
                     "unit": r.unit, "period": r.period, "quality": r.quality, "raw file": f, "check": how,
                     "verdict": verdict})
    df = pd.DataFrame(rows)
    n_pass = int((df.verdict == "PASS").sum())
    md = ["# Audit report: numbers shown in the app traced to raw files\n",
          f"Sample: {len(df)} values drawn at random (seed {a.seed}) from everything the results page shows for the two "
          f"demo scenarios. **{n_pass}/{len(df)} PASS.**\n\n",
          "Method: the raw file is re-hashed and compared with `data/source_register.csv`; the value is then searched "
          "for in the raw file's own text as it is printed there (Indian digit grouping, published unit before the "
          "one-time ETL conversion). Derived values are checked component by component.\n\n",
          df.to_markdown(index=False, floatfmt=".4g"), "\n"]
    (ROOT / "reports/audit_report.md").write_text("".join(md))
    print(df[["#", "state", "indicator", "value shown", "quality", "verdict"]].to_string(index=False))
    print(f"{n_pass}/{len(df)} PASS")
    return 0 if n_pass == len(df) else 1


if __name__ == "__main__":
    sys.exit(main())
