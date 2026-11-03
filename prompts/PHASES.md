# Prompts to paste into Claude Code, one phase at a time

Paste one prompt, let Claude Code finish, review what it reports, then move on.
Each phase ends with an exit check. Don't skip ahead if the check fails.

---

## Phase 0: Setup and data download
```
Read CLAUDE.md, docs/research_notes.md and data_sources.yaml. Convert docs/blueprint.docx to text and skim it.
Create the repo layout from CLAUDE.md, a Python venv, and install requirements.txt. Run git init.
Then run scripts/download_sources.py. For each file that comes back BLOCKED, give me the list of URLs
and target folders so I can download them in my browser. Don't try to bypass the check.
Finish by scraping the RBI handbook index page for tables 117 onwards and adding the power, roads,
telecom, banking-credit and foreign-tourist tables to data_sources.yaml. Then download those too.
```
**Exit check:** `data/raw/rbi_hsis/2025-12-11/` holds the XLSX files and `data/source_register.csv` has a row with a sha256 for each.

## Phase 1: Parse and validate the RBI panel
```
Write etl/ingest_rbi_hsis.py to parse each RBI XLSX into a long table:
state_id, fy, activity_code, value_rs_lakh, real_nominal, base_year, table_id, vintage.
Handle the multi-block layout (2004-05 base blocks vs 2011-12 base). KEEP ONLY the 2011-12 base for modelling,
'-' -> NaN, strip footnote markers (*), and build a fixed state alias map (J&K/Ladakh, Telangana pre-2014 handled explicitly).
Write etl/validate.py with checks: duplicates, missingness by state x year, non-positive values,
year-on-year changes beyond ±40% (flag, don't drop), mixed price bases.
Compare the parsed manufacturing table with tests/fixtures/rbi_2023_mfg_gsva_reference.csv and
list every difference as either a parsing bug or an edition revision. Save curated Parquet and write pytest tests.
```
**Exit check:** tests pass; `reports/coverage_heatmap.png` shows state × year coverage for each activity.

## Phase 2: The other indicators
```
Ingest the ranking indicators listed in data_sources.yaml: HCES 2023-24 state MPCE, PLFS 2025 state LFPR/WPR/UR,
ASI 2024-25 Annexure-II state tables, TRAI PIR (Apr-Jun 2026) by service area with an explicit documented LSA->state map,
tourism visits 2016-2025, CEA power shortage, MoRTH road length, MCA/OGD active companies by state, and RBI health/CPI/wage tables.
Each source gets its own etl/ingest_<source>.py and a row in source_register.csv with observation_period and published_at.
For PDFs use pdfplumber and print 5 random cells next to the page numbers so I can spot-check them.
Build fact_indicator (state, period, feature_code, value, unit, source_id, published_at) in DuckDB.
Produce reports/eligibility_matrix.csv: 7 pilot states x 6 sectors -> approve / ranking-only / exclude, with reasons.
```
**Exit check:** each pilot state has a value or an explicit 'unavailable' for every mandatory indicator; nothing is imputed.

## Phase 3: Manufacturing growth model (the first ML target)
```
Build features/build_panel.py: target g(s,t+1) = 100*(Y(t+1)/Y(t)-1) on real manufacturing GSVA, national state panel
(all states with consistent data, not just the 7 pilots). Lag-only features: 1y and 2y growth, 3y mean, volatility, per-capita NSDP,
industry share, and indicators only where published_at precedes the forecast date.
models/train.py: expanding-window CV by year, no shuffling. Baselines: persistence and 3-year mean.
Models: Ridge/ElasticNet in a Pipeline, then a depth-limited RandomForest. Report MAE, RMSE, median AE and directional accuracy,
per state and per year, with COVID years (2020-21, 2021-22) analysed separately. Run ablations.
Write reports/model_card_manufacturing.md. If no model beats persistence consistently, say so plainly and set
models/registry.json manufacturing.status = 'ranking_only'.
Then check whether trade/transport/real-estate sub-sector GSVA exists (MoSPI/DES) for enough states and years.
If it doesn't, mark those sectors ranking-only.
```
**Exit check:** a model card with honest numbers and a registry file that the app reads.

## Phase 4: Scoring engine
```
Implement scoring/score.py per blueprint section 7: industry weight profiles (demand 25, infra 20, outlook 20, labour 15,
competition 10, cost/policy 10 as defaults), robust percentile normalisation against a frozen national reference,
reversed direction for cost/risk, no favourable fill for missing data (renormalise and disclose). Add user priority adjustments,
operational-need adjustments, ±10-20% weight perturbation stability, and a counter-explanation for the runner-up.
Version the weights in scoring/weights_v1.yaml. Write tests for missing-data and priority-change behaviour,
covering the blueprint's section 11 acceptance tests.
```

## Phase 5: Streamlit app
```
Build app.py with pages matching blueprint section 8: landing, business profile form, eligibility/coverage screen,
results (top-3 cards, India map of the 7 states, comparison matrix, what-if weights, two-state compare, rank stability),
and methods/data lineage. Show source + vintage beside every number. Add CSV and PDF export.
Wherever the model is ranking-only, show that message and no forecast. Run it locally and fix errors.
Then add the two demo scenarios from the blueprint (UP manufacturer, ₹8 crore, power/logistics/labour priorities, plus one service business).
```

## Phase 6: QA and publish
```
Trace 20 random numbers shown in the app back to raw files and list them in reports/audit_report.md.
Write README.md (setup, data lineage, limitations, which sectors are ranking-only).
Prepare deployment to Streamlit Community Cloud: requirements, .streamlit/config.toml, no secrets in git.
Create a GitHub repo with gh and push.
```

---

## Phase 2b: 2026 data, internet speed, youth jobs and wages (added 3 Nov 2026)
Run this after Phase 2. Everything already extracted is in `data/extracted/` and summarised in `data/curated/`. Start from those and fill the gaps.
```
1. Run scripts/build_curated.py and read reports/validation_report.md.
2. INTERNET SPEED: run scripts/ookla_district_speeds.py for the latest published quarter (list the S3 bucket
   first to find it), then also for the same quarter a year earlier to get the change. Add TRAI Independent Drive
   Test results for pilot-state cities from 2025-2026 press releases (operator-wise 4G/5G download Mbps) as
   data/curated/internet_speed/trai_idt_cities.csv. Add TRAI PIR Apr-Jun 2026 internet subscribers per 100 by LSA,
   with a documented LSA->state map. Add NFHS-5 district "ever used internet" for pilot-state districts.
3. YOUTH UNEMPLOYMENT: parse the state annex of the PLFS Quarterly Bulletins (Apr-Jun 2025 to latest 2026) and
   the PLFS Annual Report 2025 state tables (UR 15+, UR 15-29, LFPR, NEET). Keep usual status and CWS in separate
   columns, store RSE, and never splice the pre-2025 July-June series with 2025+.
4. WAGES: replace every secondary value in data/extracted/latest_2026/wages_and_salaries_2026.csv with the state
   gazette notification (record the order number and URL). Build wages_by_state_zone_skill.csv with
   unskilled/semi-skilled/skilled/highly skilled x zone, and map each pilot city to its zone.
   Add PLFS 2025 state average earnings (regular/casual/self-employed, rural/urban) and ASI 2024-25 emoluments per employee.
   Add a private salary-band table (city x level x function) from Randstad 2025-26 and Michael Page 2026, labelled as private.
5. 2026 DEMAND: download GSTN monthly state-wise GST PDFs for Jan-Oct 2026 and build a state x month table
   (domestic GST, YoY growth). Add EPFO net payroll additions by state for 2026.
6. Rebuild pilot_state_profile.csv and add a city_profile.csv (28 cities: speed, minimum wage zone,
   private salary bands where available). Every value needs source_url and period.
```
**Exit check:** each pilot state and city has speed, youth UR (state level), wage floor by skill and at least one market salary benchmark, or an explicit "not available" with the reason.

### How the app should show this to an investor
- **Hiring cost card per city:** statutory floor by skill level (legal minimum), PLFS average for regular salaried workers (state, urban), and a private market band by experience. Keep the three separate and labelled.
- **Talent availability:** youth UR and youth LFPR (state, rural/urban). High youth unemployment means a larger available pool, so present it as supply, not as a negative.
- **Connectivity:** district median mobile and fixed speed (Ookla), plus TRAI drive-test results for the city if one exists.
