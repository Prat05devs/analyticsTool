# India Business Expansion Intelligence — project instructions for Claude Code

## What we are building
A state-screening web app for established Indian businesses deciding where to expand.
Seven pilot states: Maharashtra, Gujarat, Karnataka, Tamil Nadu, Telangana, Uttar Pradesh, Rajasthan.
Six industries: Retail, Manufacturing, IT/professional services, Logistics, Healthcare, Hospitality.
Output: top 3 eligible states with a relative 0–100 suitability index, evidence, trade-offs and data caveats.

The full specification is `docs/blueprint.docx` (convert with `pandoc docs/blueprint.docx -t plain`).
Research notes on the latest data releases (checked 3 Nov 2026) are in `docs/research_notes.md`.
Every official source URL lives in `data_sources.yaml` — use it, extend it, never hardcode URLs elsewhere.

## Non-negotiable rules (from the blueprint)
1. A suitability score is NOT a probability of success. Never label it as one.
2. Never fabricate, impute-as-observed or hardcode a data value. Every number in the app must trace to a file in `data/raw/` with a row in `data/source_register.csv` (dataset_id, publisher, url, sha256, acquisition_date, release_date, observation_period, table, unit, price_base, caveat).
3. Raw files are immutable: `data/raw/<source_id>/<vintage>/`. Curated outputs go to `data/curated/` as Parquet.
4. Do not bypass CAPTCHAs or bot checks. If a download is blocked, stop and ask me to download the file manually into the right `data/raw/` folder.
5. Never merge series with different price bases. The 2011-12 base series (RBI Handbook 2024-25) and the new 2022-23 base series must stay in separate panels.
6. ML: time-ordered expanding-window CV only, never shuffle state-years. Always compare against persistence (last year's growth) and rolling-mean baselines. If the model doesn't beat them, the app must show "ranking only" for that sector.
7. Fit scalers/imputers inside sklearn Pipelines on training folds only. Features must have been published before the forecast date (keep `published_at`).
8. Never describe one broad target (e.g. "trade, repair, hotels") as a sector-specific forecast.
9. Ranking weights are design defaults, not learned optima — label them that way in the UI.

## Stack
Python 3.11+, pandas, numpy, pyarrow, duckdb, scikit-learn, statsmodels, plotly, streamlit, pydantic, pytest, openpyxl, requests, pyyaml.

## Repo layout (create as you go)
```
data_sources.yaml        official URLs + expected schema
data/raw/ data/curated/  immutable raw, versioned curated
data/source_register.csv
etl/ingest_*.py          one per source
etl/validate.py          schema, coverage, units, duplicates, implausible growth
features/build_panel.py  lags, as-of joins, targets
models/train.py models/evaluate.py
scoring/score.py         normalisation + industry weights
app.py pages/            Streamlit UI
tests/                   pytest, incl. tests/fixtures/
reports/                 model cards, coverage heatmap, audit report
```

## How to work
- Work phase by phase using the prompts in `prompts/`. Finish a phase's exit criterion before starting the next.
- After each phase: run `pytest`, update `reports/audit_log.md` with what was downloaded, what failed, and open questions.
- When a number looks surprising, check it against the source file and against `tests/fixtures/` reference values before using it.
- Keep units explicit: RBI GSVA tables are in ₹ lakh; convert once, in ETL.
