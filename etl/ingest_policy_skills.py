"""Policy (ease of doing business) and educated-labour indicators from official releases.

    python -m etl.ingest_policy_skills

Policy
- DPIIT BRAP 2024 (PIB 11 Nov 2025): overall state category and the number of the 25 reform areas in which the state
  is a Top Achiever (score > 90%). Categories are ordinal; scored as ordinal codes (ties share a percentile).
- LEADS 2025 (PIB 13 May 2026): four logistics tiers.
- NITI Aayog Export Preparedness Index 2024 (14 Jan 2026): overall score 0-100.
- DPIIT States' Startup Ranking 5.0 (Jan 2026): five categories.

Educated labour
- PLFS 2023-24 Appendix A Table (8), rural+urban persons aged 15+: % whose highest completed level is diploma /
  certificate (col 7), graduate (col 8), post graduate & above (col 9), secondary & above (col 10).
- AISHE 2023-24: Table 19 GER in higher education (18-23), Table 4 colleges per lakh population (18-23), Table 33
  out-turn (UG and PG pass-outs, based on actual response).

Nothing is estimated: a state absent from a list gets no value, except BRAP reform-area counts, where the release
lists every Top Achiever and a state that was assessed (it appears in the category lists) but not listed has zero.
"""
from __future__ import annotations

import glob
import html
import re
import sys

import pandas as pd

from etl.common import FACT_INDICATOR_COLS, ROOT, reg_row, write_parquet
from etl.pdf_columns import column_rows, to_int
from etl.pdf_utils import page_text, spot_check
from etl.states import normalize_state

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
BRAP_CODES = {"Top Achiever": 4, "Achiever": 3, "Fast Mover": 2, "Aspirer": 1}
LEADS_CODES = {"Exemplars": 4, "High Performers": 3, "Accelerators": 2, "Growth-Seekers": 1}
SRF_CODES = {"Best Performers": 5, "Top Performers": 4, "Leader": 3, "Aspiring Leader": 2, "Emerging Ecosystems": 1}
FIX = {"NCT of Delhi": "Delhi", "Lakshadeep": "Lakshadweep", "Dadra Nagar and Haveli & Daman and Diu":
       "Dadra & Nagar Haveli and Daman & Diu", "Andaman & N. Island": "Andaman & Nicobar Islands",
       "D & N Haveli and Daman & Diu": "Dadra & Nagar Haveli and Daman & Diu"}
# AISHE 2023-24 serial order (Sl. No. 1-36), identical in Tables 4, 19 and 33; checked against Table 19 text below
AISHE_ORDER = ["Andaman & Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh",
               "Chhattisgarh", "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir",
               "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra",
               "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim",
               "Tamil Nadu", "Telangana", "Dadra & Nagar Haveli and Daman & Diu", "Tripura", "Uttar Pradesh",
               "Uttarakhand", "West Bengal"]


def raw(pattern: str) -> str:
    hits = glob.glob(str(ROOT / "data/raw" / pattern))
    if len(hits) != 1:
        raise FileNotFoundError(pattern)
    return hits[0]


def sid_of(name: str) -> str | None:
    name = re.sub(r"\s+", " ", name).strip(" ,.")
    return normalize_state(FIX.get(name, name))


def page_plain(path: str) -> str:
    s = open(path, encoding="utf-8", errors="ignore").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def names(seg: str) -> list[str]:
    seg = re.sub(r"\band\s+(?=[A-Z])", ",", seg.replace(", and ", ", "))
    parts = [p.strip(" ,.") for p in seg.split(",")]
    # 'Dadra & Nagar Haveli and Daman & Diu' and 'Jammu & Kashmir' must survive the 'and' split
    out, i = [], 0
    while i < len(parts):
        p = parts[i]
        if p.endswith("Nagar Haveli") and i + 1 < len(parts):
            p = p + " and " + parts[i + 1]
            i += 1
        if p:
            out.append(p)
        i += 1
    return out


def row(sid, period, code, value, unit, src, table, published, reg, note, quality="official"):
    return {"state_id": sid, "period": period, "period_type": "release", "feature_code": code, "value": float(value),
            "unit": unit, "source_id": src, "table_id": table, "published_at": pd.Timestamp(published),
            "first_pub_est": pd.Timestamp(published), "source_file": reg["local_path"], "sha256": reg["sha256"],
            "quality": quality, "note": note}


# ------------------------------------------------------------------------------------------------------------- policy
def brap():
    path = raw("dpiit_brap_2024/*/pib_2188992_brap_2024.html")
    reg, t = reg_row(path), page_plain(path)
    cat = {}
    m = re.search(r"Under Category Y \(.*?\), fast movers were (.*?)\. Aspirers under Category Y included (.*?)\. "
                  r"Under Category X \(.*?\), all States/UTs were classified as Aspirers, namely (.*?)\.", t)
    fm, asp_y, asp_x = (names(g) for g in m.groups())
    assert (len(fm), len(asp_y), len(asp_x)) == (10, 13, 12), (len(fm), len(asp_y), len(asp_x))
    for lst, lab, grp in [(fm, "Fast Mover", "Y"), (asp_y, "Aspirer", "Y"), (asp_x, "Aspirer", "X")]:
        for n in lst:
            cat[sid_of(n)] = (lab, grp, n)
    areas = {}
    para = t[t.index("Uttarakhand and Punjab were recognised"):t.index("DPIIT also presented")]
    for clause in re.split(r"\.\s+|,\s*while\s+", para):
        mm = re.search(r"^(.*?)\s+were (?:recognised as )?(?:top achievers |recognised )?across (\w+) reform areas?", clause)
        if mm:
            for n in names(mm.group(1)):
                areas[sid_of(n)] = WORDS[mm.group(2)]
    assert sorted(areas.values()) == sorted([5] * 2 + [4] * 10 + [3] * 6 + [2] * 3 + [1] * 2), areas
    rows = []
    for sid, (lab, grp, n) in cat.items():
        if sid is None:
            continue
        rows.append(row(sid, "2024", "brap_2024_category", BRAP_CODES[lab],
                        "category: 1=Aspirer, 2=Fast Mover, 3=Achiever, 4=Top Achiever", "dpiit_brap_2024",
                        "BRAP 2024 state categories", "2025-11-11", reg,
                        f"{lab}, Category {grp} ({'established' if grp == 'Y' else 'developing'} business systems); "
                        "no State/UT reached Achiever or Top Achiever overall"))
        k = areas.get(sid, 0)
        rows.append(row(sid, "2024", "brap_2024_top_achiever_areas", k, "of 25 reform areas", "dpiit_brap_2024",
                        "BRAP 2024 Top Achievers by reform area", "2025-11-11", reg,
                        f"Top Achiever (score > 90%) in {k} of 25 reform areas" +
                        ("" if k else "; assessed but not listed as Top Achiever in any reform area")))
    missing = set(areas) - set(cat)
    assert not missing, missing
    return rows


def leads():
    path = raw("leads_2025/*/pib_2260854_leads_2025.html")
    reg, t = reg_row(path), page_plain(path)
    t = t[t.index("The New Four-Tier Categorization"):t.index("Overall, LEADS marks")]
    rows, seen = [], set()
    tiers = list(LEADS_CODES)
    for i, tier in enumerate(tiers):
        a = t.index(tier + ":")
        b = t.index(tiers[i + 1] + ":") if i + 1 < len(tiers) else len(t)
        seg = t[a:b]
        for grp in re.finditer(r"(Coastal States|Landlocked States|North- ?Eastern States|Union Territories)\s*:\s*"
                               r"(.*?)(?=(?:Coastal States|Landlocked States|North- ?Eastern States|Union Territories)"
                               r"\s*:|$)", seg):
            for n in names(grp.group(2)):
                sid = sid_of(n)
                assert sid not in seen, n
                seen.add(sid)
                rows.append(row(sid, "2025", "leads_2025_tier", LEADS_CODES[tier],
                                "category: 1=Growth-Seeker, 2=Accelerator, 3=High Performer, 4=Exemplar", "leads_2025",
                                "LEADS 2025 four-tier classification", "2026-05-13", reg,
                                f"{tier.rstrip('s')} ({grp.group(1).replace('- ', '-')} peer group)"))
    assert len(rows) >= 34, len(rows)
    return rows


def startup():
    path = raw("startup_ranking_5/*/startup_ranking_5_results.html")
    reg, t = reg_row(path), page_plain(path)
    t = t[t.index("Best Performers 5"):t.index("State/UT Reports can be accessed")]
    rows = []
    heads = [(m.start(), m.group(1), int(m.group(2))) for m in
             re.finditer(r"(Best Performers|Top Performers|Leader|Aspiring Leader|Emerging Ecosystems) (\d+) ", t)]
    for i, (pos, lab, n) in enumerate(heads):
        seg = t[pos:heads[i + 1][0] if i + 1 < len(heads) else len(t)]
        found = re.findall(r"([A-Z][A-Za-z&\s]+?) Category (A1|A2|B)", seg[len(lab) + 3:])
        # the page's tier counter reads 'Best Performers 5' but lists 3 entities; the total (34) matches the
        # '34 participating entities' stated on the same page, so the listed names are used
        assert found and (len(found) == n or lab == "Best Performers"), (lab, n, found)
        for name, grp in found:
            rows.append(row(sid_of(name), "2026", "startup_ranking_5_category", SRF_CODES[lab],
                            "category: 1=Emerging Ecosystem, 2=Aspiring Leader, 3=Leader, 4=Top Performer, 5=Best Performer",
                            "startup_ranking_5", "States' Startup Ranking 5.0 results", "2026-01-16", reg,
                            f"{lab} (Category {grp})"))
    assert len(rows) == 34 and "34 participating entities" in page_plain(path), len(rows)
    return rows


def epi():
    path = raw("niti_epi_2024/*/Export_Preparedness_Index_2024.pdf")
    reg = reg_row(path)
    rows, checks = [], []
    pat = re.compile(r"^([A-Z][A-Za-z&\s]+?)\s+(\d{2}\.\d{2})\s+(\d{1,2})\s+(Large States|Small States, NE & UTs)$")
    for pg in (51, 52):
        for line in page_text(path, pg).splitlines():
            m = pat.match(line.strip())
            if m:
                rows.append(row(sid_of(m.group(1)), "2024", "epi_2024_score", float(m.group(2)), "score 0-100",
                                "niti_epi_2024", "EPI 2024 overall ranking (Figure 34)", "2026-01-14", reg,
                                f"overall rank {m.group(3)} of 36; peer group {m.group(4)}"))
                checks.append({"page": pg, "label": m.group(1), "value": m.group(2)})
    assert len(rows) == 36, len(rows)
    return rows, checks


# --------------------------------------------------------------------------------------------------- educated labour
def plfs_education():
    path = raw("plfs_annual_2023_24/*/AnnualReport_PLFS2023-24L2.pdf")
    reg = reg_row(path)
    page = 82  # Appendix A Table (8), rural+urban persons (printed page A-19)
    txt = page_text(path, page)
    assert "Table (8)" in txt and "rural+urban persons" in txt, "PLFS Table (8) persons page moved"
    rows, checks = [], []
    pat = re.compile(r"^([A-Za-z&.\s]+?)\s+((?:\d+\.\d\s+){10})([\d,]+)$")
    for line in txt.splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        name = m.group(1).strip()
        sid = sid_of("All India" if name.lower() == "all india" else name)
        v = [float(x) for x in m.group(2).split()]
        # printed columns (2)..(11): not literate, upto primary, middle, secondary, higher secondary, diploma/certificate,
        # graduate, post graduate & above, secondary & above, all
        assert abs(sum(v[:8]) - 100) <= 0.6 and v[9] == 100.0, (name, v)   # cols 2-9 add to 100
        assert abs(sum(v[3:8]) - v[8]) <= 0.4, (name, v)                   # cols 5-9 add to col 10
        note = "PLFS 2023-24 (Jul 2023-Jun 2024), persons aged 15+, rural+urban, highest level completed"
        for code, val, extra, q in [
            ("edu_graduate_pct", v[6], "graduate (col 8)", "official"),
            ("edu_postgraduate_pct", v[7], "post graduate & above (col 9)", "official"),
            ("edu_graduate_plus_pct", v[6] + v[7], "graduate (col 8) + post graduate & above (col 9)", "derived"),
            ("edu_secondary_plus_pct", v[8], "secondary & above (col 10)", "official"),
            ("edu_diploma_pct", v[5], "diploma / certificate course (col 7)", "official")]:
            if sid is None:
                continue
            rows.append(row(sid, "2023-24", code, round(val, 1), "% of persons aged 15+", "plfs_annual_2023_24",
                            "PLFS 2023-24 Appendix A Table (8), p. A-19", "2024-09-23", reg, f"{note}: {extra}", q))
        checks.append({"page": page, "label": name, "value": m.group(2).split()[8]})
    assert len({r["state_id"] for r in rows}) >= 35, len(rows)
    return rows, checks


def aishe():
    path = raw("aishe_2023_24/*/AISHE_2023-24_report.pdf")
    reg = reg_row(path)
    rows, checks = [], []
    # Table 19 GER (p. 161) and Table 4 college density (p. 89): parse text lines by serial number
    t19 = page_text(path, 161)
    assert "Table 19" in t19 and "Gross Enrolment Ratio" in t19
    ger = {}
    for line in t19.splitlines():
        m = re.match(r"^(\d{1,2})\s+([A-Za-z&\s]*?)\s*(\d+\.\d)\s+(\d+\.\d)\s+(\d+\.\d)\b", line.strip())
        if m and 1 <= int(m.group(1)) <= 36:
            ser, name = int(m.group(1)), m.group(2).strip()
            if name:
                assert sid_of(name) == sid_of(AISHE_ORDER[ser - 1]), (ser, name)
            ger[ser] = float(m.group(5))
    t4 = page_text(path, 89)
    assert "Table 4" in t4 and "Colleges per Lakh" in t4
    dens = {}
    for line in t4.splitlines():
        m = re.match(r"^(\d{1,2})\s+([A-Za-z&\s]*?)\s*([\d,]+)\s+(\d+)\s+([\d,]+)\s+([\d,]+)$", line.strip())
        if m and 1 <= int(m.group(1)) <= 36:
            dens[int(m.group(1))] = float(m.group(4))
    assert len(ger) == 36 and len(dens) == 36, (len(ger), len(dens))
    # Table 33 out-turn (pp. 189-190), column-true parse verified by male + female = total
    pg = column_rows(path, 189, [str(i) for i in range(1, 12)])
    ug = column_rows(path, 190, ["1", "2"] + [str(i) for i in range(12, 21)])
    out = {}
    for ser in range(1, 37):
        for lev, d, m_, f_, t_ in [("pg", pg.get(ser, {}), "9", "10", "11"), ("ug", ug.get(ser, {}), "12", "13", "14")]:
            M, F, T = to_int(d.get(m_)), to_int(d.get(f_)), to_int(d.get(t_))
            if T is None:
                continue
            assert M is not None and F is not None and abs(M + F - T) <= 2, (ser, M, F, T)
            out.setdefault(ser, {})[lev] = T
    for ser in range(1, 37):
        sid = sid_of(AISHE_ORDER[ser - 1])
        rows.append(row(sid, "2023-24", "ger_higher_education", ger[ser], "% (ages 18-23)", "aishe_2023_24",
                        "AISHE 2023-24 Table 19", "2026-07-01", reg,
                        "GER in higher education, all categories, total; based on 2011-census population projections"))
        rows.append(row(sid, "2023-24", "college_density", dens[ser], "colleges per lakh population aged 18-23",
                        "aishe_2023_24", "AISHE 2023-24 Table 4", "2026-07-01", reg, "colleges registered in AISHE"))
        lv = out.get(ser, {})
        for lev, code, lab in [("ug", "graduates_ug_outturn", "UG"), ("pg", "graduates_pg_outturn", "PG")]:
            if lev in lv:
                rows.append(row(sid, "2023-24", code, lv[lev], "persons a year", "aishe_2023_24", "AISHE 2023-24 Table 33",
                                "2026-07-01", reg, f"{lab} pass-outs (total), based on actual response"))
        if lv:
            rows.append(row(sid, "2023-24", "graduates_outturn", sum(lv.values()), "persons a year", "aishe_2023_24",
                            "AISHE 2023-24 Table 33", "2026-07-01", reg,
                            "UG + PG pass-outs in 2023-24 (sum of the printed totals), based on actual response "
                            "(non-responding institutions not counted)", "derived"))
        checks.append({"page": 161, "label": AISHE_ORDER[ser - 1], "value": f"{ger[ser]}"})
    return rows, checks


def build():
    rows, checks = [], []
    rows += brap() + leads() + startup()
    for f in (epi, plfs_education, aishe):
        r, c = f()
        rows += r
        checks += c
    df = pd.DataFrame(rows)
    df = df[df.state_id.notna()]
    dups = df.duplicated(["state_id", "feature_code"]).sum()
    assert not dups, df[df.duplicated(["state_id", "feature_code"], keep=False)]
    return df[FACT_INDICATOR_COLS], checks


def main():
    df, checks = build()
    write_parquet(df, "fact_indicator_policy")
    print(f"policy & skills: {df.state_id.nunique()} states/UTs, {len(df)} cells, "
          f"{df.feature_code.nunique()} features: {sorted(df.feature_code.unique())}")
    print(spot_check(checks[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
