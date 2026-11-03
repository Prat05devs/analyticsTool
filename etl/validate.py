"""Validation checks for the curated RBI panel and the indicator table.

    python -m etl.validate

Checks: duplicates, missingness by state x year, non-positive values, year-on-year changes beyond +-40%
(flagged, never dropped), mixed price bases, geography breaks, a fixture comparison against the 2023 edition
(each difference classified as parsing bug or edition revision by re-reading the raw file), and a comparison
with the research extracts in data/extracted/.
Writes reports/validation_rbi_panel.md, reports/coverage_heatmap.png and data/curated/validation_flags.parquet.
"""
from __future__ import annotations

import re
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from etl.common import CUR, REP, ROOT, write_parquet  # noqa: E402
from etl.states import PILOTS, dim_state, name_of, normalize_state  # noqa: E402

GROWTH_FLAG = 40.0
GEOGRAPHY_BREAKS = {("JK", "2019-20"): "J&K excludes Ladakh from 2019-20"}


def indian_format(x: float) -> str:
    """5070622 -> '50,70,622' (as printed in RBI tables)."""
    s = str(int(round(x)))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
    return f"{head},{tail}"


def check_duplicates(econ, ind):
    return {"fact_economic": int(econ.duplicated(["state_id", "fy", "activity_code"]).sum()),
            "fact_indicator_rbi": int(ind.duplicated(["state_id", "period", "feature_code"]).sum())}


def growth_flags(econ):
    e = econ.sort_values(["activity_code", "state_id", "fy"]).copy()
    e["growth_pct"] = e.groupby(["activity_code", "state_id"]).value_rs_lakh.pct_change(fill_method=None) * 100
    flags = e[e.growth_pct.abs() > GROWTH_FLAG].assign(flag="abs_growth_gt_40")
    geo = e[[(s, f) in GEOGRAPHY_BREAKS for s, f in zip(e.state_id, e.fy)]].assign(flag="geography_break")
    return pd.concat([flags, geo])[["state_id", "fy", "activity_code", "value_rs_lakh", "growth_pct", "flag"]]


def fixture_comparison(econ):
    fx = pd.read_csv(ROOT / "tests/fixtures/rbi_2023_mfg_gsva_reference.csv", comment="#", na_values=["NA"])
    fxl = fx.melt(id_vars="state", var_name="fy", value_name="ed2023")
    fxl["state_id"] = fxl.state.map(normalize_state)
    cur = econ[econ.activity_code == "manufacturing"][["state_id", "fy", "value_rs_lakh", "source_file"]]
    j = fxl.merge(cur, on=["state_id", "fy"], how="left")
    rows = []
    raw_text = {}
    for r in j.itertuples():
        if pd.isna(r.ed2023) and pd.isna(r.value_rs_lakh):
            continue
        if pd.isna(r.ed2023):
            cls = "now published (was not available in 2023 edition)"
        elif pd.isna(r.value_rs_lakh):
            cls = "missing in 2024-25 edition"
        elif r.ed2023 == r.value_rs_lakh:
            continue
        else:
            txt = raw_text.setdefault(r.source_file, (ROOT / r.source_file).read_text(errors="ignore"))
            cls = ("edition revision (parsed value matches raw file)" if indian_format(r.value_rs_lakh) in txt
                   else "PARSING BUG (parsed value not found in raw file)")
        rows.append({"state": r.state, "fy": r.fy, "ed2023": r.ed2023, "ed2024_25": r.value_rs_lakh,
                     "diff_pct": (r.value_rs_lakh / r.ed2023 - 1) * 100 if r.ed2023 and r.value_rs_lakh else np.nan,
                     "classification": cls})
    return pd.DataFrame(rows), len(j.dropna(subset=["ed2023", "value_rs_lakh"]))


def extract_comparison(econ):
    files = {"T26_gsva_total_constant.csv": "gsva_total", "T34_gsva_manufacturing_constant.csv": "manufacturing",
             "T38_gsva_construction_constant.csv": "construction", "T42_gsva_industry_constant.csv": "industry",
             "T46_gsva_financial_services_constant.csv": "financial_services",
             "T50_gsva_services_constant.csv": "services"}
    rows, n = [], 0
    for f, a in files.items():
        p = ROOT / "data/extracted/rbi_hsis_2024_25" / f
        if not p.exists():
            continue
        x = pd.read_csv(p, na_values=["NA"]).melt(id_vars="state", var_name="fy", value_name="extract")
        x["state_id"] = x.state.map(normalize_state)
        j = x.merge(econ[econ.activity_code == a][["state_id", "fy", "value_rs_lakh"]], on=["state_id", "fy"])
        n += len(j)
        d = j[~((j.extract == j.value_rs_lakh) | (j.extract.isna() & j.value_rs_lakh.isna()))]
        rows += [{"activity": a, "state": r.state, "fy": r.fy, "extract": r.extract, "raw_parsed": r.value_rs_lakh}
                 for r in d.itertuples()]
    return pd.DataFrame(rows), n


def coverage_heatmap(econ, path):
    acts = sorted(econ.activity_code.unique())
    states = dim_state()
    order = states[states.state_id.isin(econ.state_id.unique())].sort_values(["pilot_flag", "canonical_name"],
                                                                             ascending=[False, True])
    fig, axes = plt.subplots(1, len(acts), figsize=(2.1 * len(acts) + 2, 9), sharey=True)
    for ax, a in zip(axes, acts):
        m = (econ[econ.activity_code == a].pivot_table(index="state_id", columns="fy", values="value_rs_lakh",
                                                        aggfunc="count").reindex(order.state_id).fillna(0))
        ax.imshow(m.values, aspect="auto", cmap="Greens", vmin=0, vmax=1)
        ax.set_title(a.replace("_", "\n"), fontsize=8)
        ax.set_xticks(range(len(m.columns)), [c[2:] for c in m.columns], rotation=90, fontsize=6)
        ax.set_yticks(range(len(m.index)), [name_of(s) + (" ★" if s in order[order.pilot_flag].state_id.values
                                                              else "") for s in m.index], fontsize=6)
    fig.suptitle("RBI HSIS 2024-25: state x fiscal-year coverage, constant 2011-12 prices (green = value, white = '-')\n"
                 "★ = pilot state", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    econ = pd.read_parquet(CUR / "fact_economic.parquet")
    ind = pd.read_parquet(CUR / "fact_indicator_rbi.parquet")
    pid = {normalize_state(p) for p in PILOTS}
    out = ["# Validation: RBI HSIS 2024-25 panel\n",
           f"Source files: {econ.source_file.nunique() + ind.source_file.nunique()} raw tables in "
           "`data/raw/rbi_hsis/2025-12-11/` (official HTML pages; XLSX blocked by a browser check).\n"]

    dups = check_duplicates(econ, ind)
    out.append(f"\n## Duplicates\n- fact_economic: {dups['fact_economic']}\n- fact_indicator_rbi: {dups['fact_indicator_rbi']}\n")

    bases = econ.base_year.unique().tolist()
    q = pd.read_parquet(CUR / "quarantine_rbi.parquet")
    out.append(f"\n## Price bases\n- fact_economic bases: {bases} (must be exactly ['2011-12'])\n"
               f"- quarantined cells with another base: {len(q)}\n")

    miss = econ[econ.value_rs_lakh.isna()]
    out.append(f"\n## Missingness\n- {len(econ)} cells, {len(miss)} missing ('-' in source).\n")
    mp = miss[miss.state_id.isin(pid)].groupby(["state_id", "fy"]).activity_code.apply(lambda s: ", ".join(sorted(s)))
    out.append("- Pilot-state gaps:\n" + ("".join(f"  - {name_of(s)} {fy}: {a}\n" for (s, fy), a in mp.items())
                                         or "  - none\n"))
    by_state = (miss.groupby("state_id").size().sort_values(ascending=False).head(10))
    out.append("- Most gaps (all states): " + ", ".join(f"{name_of(s)} {n}" for s, n in by_state.items()) + "\n")

    nonpos = econ[econ.value_rs_lakh <= 0]
    out.append(f"\n## Non-positive value added\n- {len(nonpos)} cells\n")
    for r in nonpos.itertuples():
        out.append(f"  - {name_of(r.state_id)} {r.fy} {r.activity_code}: {r.value_rs_lakh}\n")

    flags = growth_flags(econ)
    write_parquet(flags, "validation_flags")
    g = flags[flags.flag == "abs_growth_gt_40"]
    out.append(f"\n## Year-on-year change beyond +-{GROWTH_FLAG:.0f}% (flagged, kept)\n- {len(g)} flags in all states; "
               f"pilot-state flags:\n")
    for r in g[g.state_id.isin(pid)].itertuples():
        out.append(f"  - {name_of(r.state_id)} {r.activity_code} {r.fy}: {r.growth_pct:+.1f}%\n")
    out.append("- Geography breaks: " + "; ".join(f"{name_of(s)} {fy} ({why})" for (s, fy), why in GEOGRAPHY_BREAKS.items())
               + " -> growth for that year is not used as a target.\n")

    fxc, nfx = fixture_comparison(econ)
    out.append(f"\n## Fixture: manufacturing GSVA, 2023 edition vs 2024-25 edition (pilot states)\n"
               f"- {nfx} comparable cells; {int((fxc.classification.str.startswith('edition')).sum()) if len(fxc) else 0} "
               f"differ (edition revisions), "
               f"{int(fxc.classification.str.startswith('PARSING').sum()) if len(fxc) else 0} parsing bugs.\n\n"
               "| State | FY | 2023 ed. | 2024-25 ed. | diff | classification |\n|---|---|---:|---:|---:|---|\n")
    for r in fxc.itertuples():
        out.append(f"| {r.state} | {r.fy} | {r.ed2023:,.0f} | {r.ed2024_25:,.0f} | {r.diff_pct:+.1f}% | {r.classification} |\n"
                   if pd.notna(r.ed2023) and pd.notna(r.ed2024_25) else
                   f"| {r.state} | {r.fy} | {r.ed2023 if pd.notna(r.ed2023) else '-'} | "
                   f"{'-' if pd.isna(r.ed2024_25) else f'{r.ed2024_25:,.0f}'} | | {r.classification} |\n")

    exc, nex = extract_comparison(econ)
    out.append(f"\n## Research extract (data/extracted) vs raw-file parse\n- {nex} cells compared, {len(exc)} differ. "
               "The raw file is the source of record; differences are transcription errors in the extract:\n")
    for r in exc.itertuples():
        out.append(f"  - {r.activity} {r.state} {r.fy}: extract {r.extract:,.0f} vs raw {r.raw_parsed:,.0f}\n")

    w = econ.pivot_table(index=["state_id", "fy"], columns="activity_code", values="value_rs_lakh")
    viol = w[(w.industry < w.manufacturing + w.construction - 1)].dropna(subset=["industry"])
    share = ((w.industry + w.services + w.agriculture) / w.gsva_total).dropna()
    out.append(f"\n## Identities\n- industry >= manufacturing + construction: {len(viol)} violations\n"
               f"- (agriculture + industry + services) / total GSVA: median {share.median():.3f}, range "
               f"{share.min():.3f}-{share.max():.3f}. RBI's 'agriculture' table is crop+livestock+forestry+fishing as "
               "published; the gap is not used anywhere.\n")

    coverage_heatmap(econ, REP / "coverage_heatmap.png")
    out.append("\n## Coverage heatmap\n![coverage](coverage_heatmap.png)\n")
    (REP / "validation_rbi_panel.md").write_text("".join(out))
    print("".join(out))
    ok = dups["fact_economic"] == 0 and dups["fact_indicator_rbi"] == 0 and bases == ["2011-12"] and \
        not (len(fxc) and fxc.classification.str.startswith("PARSING").any())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
