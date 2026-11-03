# India Business Expansion Intelligence

A state-screening web app for established Indian businesses deciding where to expand. It compares seven pilot
states (Maharashtra, Gujarat, Karnataka, Tamil Nadu, Telangana, Uttar Pradesh, Rajasthan) for six industries
(retail, manufacturing, IT/professional services, logistics, healthcare, hospitality). The output is the top
three states with a relative 0–100 suitability index, the evidence behind it, trade-offs, rank stability and data
caveats.

> **The index is a relative screening score. It is not a probability of commercial success, profit or survival,
> and not financial advice.** Weights are documented design defaults (`scoring/weights_v2.yaml`; v1 kept for the audit trail), not learned optima.

## Quick start

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py                 # uses the committed curated data
pytest                               # 86 tests: parsing, provenance, leakage, scoring, app pages
```

Two worked examples are one click away on the profile page: a UP manufacturer with ₹8 crore and
power/logistics/labour priorities, and an IT-services firm from Maharashtra opening a second centre.

## Rebuild everything from raw files

```bash
python scripts/download_sources.py --all     # official files -> data/raw/<source>/<vintage>/ + sha256 register
python -m etl.ingest_rbi_hsis                # 47 RBI Handbook tables -> fact_economic / fact_indicator_rbi
python -m etl.validate                       # checks + reports/validation_rbi_panel.md + coverage_heatmap.png
python -m etl.ingest_hces                    # HCES 2023-24 state MPCE (+ RSE), with page spot checks
python -m etl.ingest_trai_pir                # TRAI PIR Apr-Jun 2026 internet subscriptions by state
python -m etl.ingest_secondary               # admits research-extract values only if found in a saved source page
python -m etl.build_indicators               # derived ratios, fact_indicator, DuckDB warehouse
python -m features.build_panel               # leakage-safe model frame (as-of joins on release dates)
python -m models.train                       # expanding-window CV, baselines, registry, model card
python -m etl.eligibility                    # 7x6 eligibility matrix and coverage report
python scripts/build_curated.py              # CSV extracts, pilot_state_profile.csv, city_profile.csv
python scripts/audit_trace.py                # trace 20 random displayed numbers back to raw files
python scripts/ookla_district_speeds.py --year 2026 --quarter 3   # optional, ~1 GB download
```

## Data lineage

```
official file (XLSX/HTML/PDF) ──> data/raw/<source>/<vintage>/   immutable, sha256 in data/source_register.csv
        │ etl/ingest_*.py  (fixed state alias map, units converted once, '-' -> missing, footnotes stripped)
        ▼
data/curated/*.parquet  ──>  data/curated/warehouse.duckdb   (dim_state, fact_economic, fact_indicator)
        │ features/build_panel.py (as-of joins)    │ scoring/score.py (percentiles vs 30 states, weights v2)
        ▼                                          ▼
models/registry.json + forecast parquet  ───────>  Streamlit app (app.py, pages/)  ──> CSV / PDF export
```

Every value carries its raw file and checksum; derived values (per-capita ratios, shares, momentum) list every
component file. `reports/audit_report.md` re-reads 20 random displayed values from the raw files (20/20 pass).

| Source | Used for | Vintage |
|---|---|---|
| RBI Handbook of Statistics on Indian States 2024-25 (47 tables) | state accounts at 2011-12 prices, ASI, power, roads, rail, banking, CPI, rural wages, unemployment, tourism, health | released 11 Dec 2025; data to FY 2024-25 |
| HCES 2023-24 (NSS report 592) | rural/urban MPCE with RSE | Aug 2023 – Jul 2024 |
| TRAI Performance Indicator Report | internet subscriptions per 100 by state | Apr–Jun 2026 |
| geoBoundaries ADM1 | state outlines for the map only | gbOpen |
| Secondary pages (saved copies) | GST collections, minimum wages, private salary bands: displayed and labelled, never scored | 2025–2026 |

The RBI XLSX files are behind a browser check for scripts; the same tables' official HTML pages are used instead.
The ingest prefers XLSX automatically if you download them by hand into `data/raw/rbi_hsis/2025-12-11/`
(then run `python scripts/download_sources.py --register-manual`).

## Which sectors have a forecast

| Industry | Status | Why |
|---|---|---|
| Manufacturing | **Forecast validated** (ridge on lagged growth) | Real manufacturing GSVA (RBI T34) is a long, consistent state series. Validation MAE 9.6 pp vs 10.9 pp (3-year mean); FY 2024-25 hold-out 3.3 pp vs 3.9 pp. The bootstrap interval for the gain crosses zero; the app shows the 80% band (about ±12 pp). Gujarat gets no forecast because its accounts stop at FY 2022-23. |
| Retail | Ranking only | Trade & repair GSVA is not published by state |
| IT / professional services | Ranking only | No state IT output series |
| Logistics | Ranking only | Transport & storage GSVA not available as a consistent panel |
| Healthcare | Ranking only | Health output not separable by state |
| Hospitality | Ranking only | Hotels & restaurants bundled with trade |

Details: `reports/model_card_manufacturing.md`, `models/registry.json`, `reports/eligibility_matrix.csv`.

## Limitations

- State averages hide corridor and district differences. This is state screening, not site selection.
- One data vintage: the model backtest uses revised data, not real-time first estimates.
- Gujarat's official state accounts end in FY 2022-23 in the RBI handbook; its momentum and shares are older.
- Telangana has no published rural wage series; its cost score uses the other cost indicators (disclosed).
- Not obtainable by script, never estimated: PLFS 2025 state tables, ASI 2024-25 state annex, state youth
  unemployment source PDFs, MCA/OGD company counts (API key + CAPTCHA), rents, plot prices, tariffs, outages.
  See `reports/unavailable_sources.csv` and `reports/unverified_values.csv`.
- Unemployment is shown as labour-pool supply (higher = larger available pool), not as a negative.
- Internet subscriptions are not measured speed; Ookla speed data is CC BY-NC-SA 4.0 (non-commercial).
- The new 2022-23 base GDP series is not used: state back series were incomplete at the time of the build, and
  price bases are never mixed.

## Deploying (Streamlit Community Cloud)

The app needs only `app.py`, `pages/`, `ui/`, `scoring/`, `etl/` (imports), `data/curated/*.parquet`,
`data/source_register.csv`, `data/raw/geoboundaries_ind_adm1/` and `reports/`. Point Streamlit Cloud at `app.py`
with Python 3.11. No secrets are used; `.streamlit/secrets.toml` is git-ignored.

## Repository layout

```
data_sources.yaml          official URLs (extended with RBI tables 116-182 and boundaries)
data/raw/ data/curated/    immutable raw files, curated parquet + CSV, DuckDB warehouse
data/source_register.csv   one row per raw file: url, sha256, acquisition date, status
etl/                       ingest_*.py, validate.py, build_indicators.py, eligibility.py, states.py
features/ models/          build_panel.py; train.py, evaluate.py, registry.json
scoring/                   score.py, weights_v2.yaml, reference_v2.parquet (frozen national reference; v1 files kept)
app.py pages/ ui/          Streamlit app (Survey Ledger visual system, matches the design canvas)
tests/                     pytest, incl. fixtures
reports/                   validation, coverage heatmap, model card, eligibility matrix, audit report, audit log
```
