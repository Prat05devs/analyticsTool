# Audit log

## Phase 0 — setup and download (3 Nov 2026)
- Repo layout created, Python 3.11 venv, requirements installed, `git init`.
- `scripts/download_sources.py`: all RBI Handbook XLSX files on `rbidocs.rbi.org.in` returned a **browser check**
  (HTML instead of XLSX). Not bypassed. The same tables' official HTML pages on `www.rbi.org.in` (listed in
  `data_sources.yaml` as `html`) were saved instead; the script now does this automatically and records it in the
  register `status`. Manual XLSX download remains optional (folder `data/raw/rbi_hsis/2025-12-11/`).
- Index page scraped: tables T30 and T116–T182 (ASI, power, roads, rail, telecom, banking/credit, exports, foreign
  tourists) plus T24 (NSDP) added to `data_sources.yaml`; 47 RBI tables downloaded with sha256.
- Downloaded: ASI 2024-25 factsheet + press note, PLFS Annual 2025 press note, HCES 2023-24 report + factsheet,
  TRAI PIR Apr–Jun 2026 + yearly 2025-26, PLFS monthly Aug 2026 + quarterly bulletins, MoSPI 2022-23 base notes,
  geoBoundaries ADM1/ADM2.
- **Failed**: Tourism compendium 2025 and the 2016–2025 Lok Sabha series (HTTP 404); DGE youth-UR PDF (404);
  eparlib PDFs (DNS failure); data.gov.in company master (API key + CAPTCHA); MCA portal (unreachable).
- Exit check: `data/raw/rbi_hsis/2025-12-11/` holds the tables (HTML form) and every file has a register row with
  sha256. ✔

## Phase 1 — RBI panel
- `etl/rbi_html.py` parses continuation blocks, rowspan/colspan headers, transposed ASI tables, Indian digit
  grouping, `-`/`.` as missing, footnote markers. `etl/states.py` is the fixed alias map (J&K/Ladakh break from
  2019-20, Telangana back-cast, DNHDD merge, telecom circles and regions dropped).
- Only the 2011-12 base is present in this edition; 0 cells quarantined. 0 duplicates.
- Fixture (2023 edition) comparison: 82 pilot cells, 19 differ, **all classified as edition revisions** (the parsed
  value is printed in the raw file), 0 parsing bugs.
- The research extracts in `data/extracted/` had **2 transcription errors** (TN total GSVA 2018-19, RJ services
  2018-19, one digit each). The raw file is the source of record; `scripts/build_curated.py` now reads only
  parsed raw data.
- 35 growth rates beyond ±40% flagged and kept (pilots: UP manufacturing 2016-17 +47%, Telangana agriculture
  2019-20 +55%). Exit check: tests pass, `reports/coverage_heatmap.png`. ✔

## Phase 2 — indicators
- HCES Table 3.17 + C1 (RSE), TRAI PIR Table 1.43 (state/UT, not LSA; LSA map documented in
  `etl/lsa_state_map.csv`), 46 RBI indicator series, derived ratios (population = NSDP / per-capita NSDP).
- PDF spot checks printed with page numbers (HCES p69, TRAI p76) and matched by eye.
- Secondary research values admitted only when the number appears in a saved copy of the cited page: 31 admitted
  (official 9, secondary 19, private 3), 78 rejected → `reports/unverified_values.csv`.
- Exit check: every pilot has a value or an explicit 'unavailable' for every indicator
  (`reports/indicator_coverage_pilots.csv`); nothing imputed. Telangana rural wages: not published. ✔

## Phase 2b — 2026 data
- Ookla Open Data reachable; 2026 Q3 (latest) and 2025 Q3 extraction runs on download (~1 GB, slow link).
  `city_profile.csv` fills speed columns when it completes; until then each city says "not available" with reason.
- PLFS quarterly/monthly bulletins downloaded do not contain the state annex; state youth UR stays unavailable.
- Wages: gazette notifications not obtained; minimum wages shown as labelled **secondary, state-level** values
  only where verified in a saved page. GSTN monthly state files: listing page 404 → secondary FY 2025-26 totals.

## Phase 3 — model
- Ridge (α=100, lag features) passed the pre-specified rule: −12.1% MAE vs 3-year mean on non-COVID validation
  years, won 4/5 years, hold-out FY 2024-25 MAE 3.31 vs 3.88 pp. Year-bootstrap interval for the gain crosses zero
  (−2.9 to +0.2 pp) — disclosed in the card and the app.
- Other five sectors: ranking only (no consistent state sub-sector GSVA). Exit check: model card + registry. ✔

## Phase 4–5 — scoring and app
- `scoring/score.py` with frozen national reference, no favourable fill, priorities, needs, ±20% stability,
  counter-explanation; tests cover blueprint §11. Streamlit app with five pages, map, matrix, what-if, compare,
  CSV/PDF export, both demo scenarios. Design canvas published as a separate artifact.

## Phase 6 — QA
- `reports/audit_report.md`: 20 random displayed values traced to raw files, 20/20 PASS.
- **Not done without your go-ahead**: creating a GitHub repository and pushing (outward-facing).

## Scoring v2 — industry-relevant reasons (3 Nov 2026)
- User report: healthcare results cited internet subscriptions as a strength and urban unemployment as a watch-out,
  and reasons looked the same whatever the industry or choices. Causes: v1 profiles contained generic indicators,
  and reasons were ranked against the national median (50) rather than the compared states.
- `scoring/weights_v2.yaml` (v1 kept): every industry indicator has a written business rationale (`why`, enforced
  by `tests/test_reasons.py`); healthcare drops internet and unemployment, gains PHC doctors per lakh (new derived
  ratio, `etl/build_indicators.py`, RBI T16 / population) and population, and reads public beds as a care gap;
  IT drops household spending; healthcare and hospitality have no ecosystem dimension. Operational needs now add
  their indicators to profiles that lack them.
- Reasons = gap vs the median of the other compared states x effective weights, with a materiality floor; tagged
  with the user's priorities and needs. Python and browser engines produce identical reasons (parity test).
- New frozen reference `scoring/reference_v2.parquet`; eligibility, web bundle, parity fixtures and the
  weighting/sensitivity outputs regenerated; panel documentation updated. 109 tests pass; audit trace 20/20.

## Open questions
1. Download the RBI XLSX files by hand? Optional: the HTML tables are the same official data.
2. Gujarat FY 2023-24/2024-25 GSVA from Gujarat DES — different source; add as a separate, labelled panel?
3. Confirm the scoring weights with a domain expert (they are design defaults).
4. Ookla data is non-commercial (CC BY-NC-SA); a commercial deployment needs Ookla's permission.
