# India Business Expansion Intelligence
## State Segmentation & Suitability Scoring — End-to-End Technical and Business Documentation

**Prepared for:** MBA (Big Data Analytics) evaluation panel
**Role:** Lead Analytics Solution Architect & Project Lead
**Build date / data refresh:** 3 November 2026 · **Scoring version:** `weights_v1` · **Live app:** https://india-expansion-intel.vercel.app

---

### Executive summary

| Question the business asked | What we built | Headline result |
|---|---|---|
| *Where should an established Indian business expand next?* | A state-screening decision app: 7 pilot states × 6 industries, scored against a 30-state national reference | A relative 0–100 suitability index with evidence, trade-offs, rank stability and data caveats for every recommendation |
| *Can we predict which states will grow?* | A leakage-controlled, one-year-ahead forecast of real manufacturing GSVA growth | Validated: 12% lower error than the best naive baseline; hold-out error 3.3 pp vs 3.9 pp. Other five sectors are **ranking-only** because no defensible state-level target exists |
| *Which states are structurally alike?* | Unsupervised segmentation of 30 states on 15 de-correlated indicators | 5 state baskets (k = 5), from "Mature industrial & services cores" to "Remote frontier economies" |
| *How much should we trust the ranking?* | ±20% weight perturbation, equal-weight and PCA-weight challengers, counter-explanations | Rankings are robust in 4 of 6 industries; manufacturing's default top-3 is a **near-tie** (63.2 / 63.0 / 62.7) and the app says so |

> **Governing principle.** The index is a *relative screening score*. It is **not** a probability of commercial success, profit or survival. Every number shown to a user traces to a raw government file with a recorded SHA-256 checksum. Nothing is imputed.

**Two architecture decisions shape everything below:**

1. **Honest scope over impressive scope.** Five of six industries have no state-level sector output series, so we refused to train "five forecasts" on the same broad services aggregate (a common analytics anti-pattern). They are ranking-only by design.
2. **Governance as a feature.** Each value carries its source table, period and checksum on screen. In a decision product, auditability builds executive trust, and with it adoption.

---

## 1. Data Sourcing, Governance & Recency

### 1.1 Primary data sources

All scored data is from **official Indian government publications**. **No synthetic or mock data** is used anywhere. No commercial APIs are used. Ingestion means direct download of published files, never scraping behind logins or CAPTCHAs.

| Tier | Source | Publisher | What it feeds | Format ingested | Vintage |
|---|---|---|---|---|---|
| **Core** | Handbook of Statistics on Indian States 2024-25 (47 tables) | **RBI** (data from NSO/**MoSPI**, CEA, MoRTH, Labour Bureau, ASI) | State accounts at constant 2011-12 prices; ASI factories/workers; power; roads & rail; bank credit; CPI; rural wages; unemployment; tourism; health | Official HTML table pages (XLSX blocked by a bot check, so not bypassed) | Released 11 Dec 2025; data to FY 2024-25 |
| Core | Household Consumption Expenditure Survey 2023-24, NSS Report 592 | **MoSPI** | Rural/urban MPCE (consumer demand) with relative standard errors | PDF (tables parsed with `pdfplumber`, spot-checked by page) | Aug 2023 – Jul 2024 |
| Core | Telecom Performance Indicator Report | **TRAI** | Internet subscriptions per 100 by State/UT | PDF | Apr–Jun 2026 (released 12 Oct 2026) |
| Supporting | Ookla Open Data (speed tiles) | Ookla (CC BY-NC-SA) | District and city fixed/mobile speeds, 2025Q3 vs 2026Q3 | Parquet (≈1 GB) + geoBoundaries ADM2 | 2026 Q3 |
| Display-only | GST collections, minimum wages, private salary surveys | Press/aggregator pages | Context cards, **never scored** | Saved page snapshots | 2025–2026 |
| Map only | geoBoundaries ADM1 | William & Mary geoLab (CC BY 4.0) | State outlines | GeoJSON | gbOpen |

**Sources attempted and transparently not used**

| Source | Status | Governance decision |
|---|---|---|
| RBI XLSX files (`rbidocs.rbi.org.in`) | Browser bot-check | Not bypassed. The identical official HTML tables were used, and the XLSX remains a manual-download option |
| data.gov.in / MCA company master | API key + CAPTCHA | Not bypassed. Company-density feature excluded |
| PLFS Annual Report 2025 state tables | Not reachable by script | PLFS 2023-24 state unemployment (via RBI) used instead |
| State youth unemployment PDFs (DGE, eparlib) | HTTP 404 / DNS failure | Hand-transcribed values exist but cannot be traced to a raw file, so **excluded** |
| NITI Aayog indices | Not used | Composite indices of other agencies embed their own weights; we score from primary indicators to keep weighting transparent and avoid double-weighting |

**Managerial lens.** The binding constraint was traceability, not data volume. A recommendation an investment committee cannot audit is a liability. This is why every value is stored with its provenance in `data/source_register.csv`, which holds 83 registered raw files, each with URL, SHA-256, acquisition date and status.

### 1.2 Recency & time lag

State macro data in India has a **structural reporting lag of 12–24 months**, and series are revised between editions.

| Data family | Latest period used | Approx. publication lag | Implication |
|---|---|---|---|
| State GSVA/GSDP (constant prices) | FY 2024-25 | ~9 months after FY end | Freshest structural signal |
| Gujarat state accounts | **FY 2022-23** | not yet in the handbook | Gujarat is ranked, but receives **no forecast**; disclosed on screen |
| ASI (factories, workers) | FY 2023-24 | ~18 months | Ecosystem/labour features lag one year |
| PLFS unemployment (state) | Jul 2023 – Jun 2024 | ~4 months, but state annual only | Labour pool measured, not district |
| HCES consumption | Aug 2023 – Jul 2024 | ~6 months | **Snapshot; never interpolated** |
| TRAI internet | Jun 2026 | ~4 months | Freshest digital signal |
| Road length (state) | 2020 | ~3 years | Replaced by national highways (2024) in scoring |

**How temporal discrepancies were reconciled**

1. **Latest observation per indicator, with its period displayed.** Each value is shown with its own period, never relabelled as "current".
2. **Explicit as-of joins for ratios.** For example, highway km at end-March *Y* is divided by population for FY (*Y*−1)–*Y*. Where a state's population is not yet published (Gujarat), the latest earlier FY is used, and the note on that value says so.
3. **Release-date control for the model (no look-ahead bias).** Every observation carries an estimated first-publication date `first_pub_est`. A feature enters a forecast only if it had been published by the forecast date, and the build asserts this (`max_feature_pub ≤ forecast_date`).
4. **Single price base.** The new 2022-23 base GDP series (Feb 2026) had incomplete state back-series. Mixing it with the 2011-12 base would corrupt growth rates, so it is quarantined and the 2011-12 base is used.
5. **Revision tracking.** Against the 2023 edition, 19 of 82 pilot manufacturing cells were revised (e.g. Telangana 2022-23 −20.1%, UP 2022-23 −12.9%). Each was logged as an *edition revision* after confirming the parsed value is printed in the raw file. **Limitation disclosed:** the model backtest uses revised data, not real-time first estimates.

**Managerial lens.** Lag is unavoidable at state level, so the product treats freshness as a visible attribute rather than hiding it. Each state gets a **data-confidence label** (High/Medium/Low) based on observed-weight coverage and the number of pre-2023 indicators. Gujarat is labelled *Medium*: the system flags it, so the executive doesn't have to discover it.

### 1.3 Data quality, auditability & imputation

**Imputation policy: none.** A missing indicator is dropped and its weight is redistributed within its dimension. A state missing a *mandatory* dimension is excluded with a stated reason. This is a deliberate governance stance: imputing a favourable value would let missing data improve a state's rank.

| Control | Implementation | Result on this build |
|---|---|---|
| Immutable raw layer | `data/raw/<source>/<vintage>/`, SHA-256 in register, re-hash check on every read | 0 mismatches |
| Duplicate detection | Hard failure on duplicate (state, period, indicator) | 0 duplicates |
| Price-base check | Pipeline quarantines any non-2011-12 cell | 0 quarantined |
| Outliers | YoY growth beyond ±40% **flagged, not dropped** | 35 flags (pilots: UP manufacturing 2016-17 +47%; Telangana agriculture 2019-20 +55%) |
| Geography breaks | Fixed alias map; J&K excludes Ladakh from 2019-20, so that growth year is never a target | Handled explicitly |
| Fixture comparison | Parsed values vs 2023-edition reference | 0 parsing bugs; 19 edition revisions |
| Multi-source reconciliation | Hand-transcribed research extracts checked against parsed raw files | **2 transcription errors found** in the extracts (TN GSVA 2018-19; RJ services 2018-19); raw file is source of record |
| Secondary values | Admitted only if the number is found next to the state name in a saved copy of the cited page | 31 admitted (display only), 78 rejected with reasons |
| End-to-end audit | 20 random numbers shown in the app re-read independently from raw files | **20 / 20 pass** |
| Survey precision | HCES relative standard errors carried with each value | e.g. Telangana urban MPCE RSE 16.9%, disclosed |

**Managerial lens.** These controls are cheap relative to the cost of one wrong recommendation, and they make the system defensible under due-diligence questioning. The audit trail (`reports/audit_report.md`) is a deliverable in its own right.

---

## 2. Business Feature Engineering & Selection

### 2.1 Feature families (business constructs → measurable proxies)

| Business pillar | Indicators (examples) | Proxy caveat stated in the app |
|---|---|---|
| Market demand | Real GSDP (log), per-capita NSDP, urban/rural MPCE, personal loans per person, exports, tourist visits | High state demand ≠ store-site demand |
| Infrastructure | Energy shortage %, peak demand not met, power per person, national highways & rail per lakh people, internet subscriptions per 100, govt hospital beds per lakh | Subscriptions ≠ measured speed; shortage ≠ plant outages |
| Economic outlook | 3-year real growth momentum (sector or aggregate); validated manufacturing forecast | Services aggregate is broad, not sector-specific |
| Labour availability | Urban/rural unemployment rate (as *available pool*), factory workers, public specialists | Pool size ≠ job-specific talent |
| Business ecosystem | Factories, manufacturing/services/financial share of GSVA, credit to industry, bank offices | Density can mean cluster **or** saturation |
| Operating cost & policy | Rural wages, CPI, urban housing inflation, power T&D losses | No auditable policy metric, so policy is informational only |

**Derived features (computed, never imputed).** Population is derived as NSDP ÷ per-capita NSDP, which is the definition of per-capita NSDP. Every ratio carries all its component files. Power shortage % is (requirement − availability) / requirement, floored at 0.

### 2.2 Transformation & normalisation

The pilots differ by orders of magnitude in scale (UP: ~239 m people; Telangana: ~38 m), and the national reference includes states with ~0.7 m people. The normalisation choice therefore drives the result.

| Technique | Considered for | Decision & reasoning |
|---|---|---|
| **Percentile rank vs a frozen national reference (mid-rank)** | **Scoring (production)** | **Chosen.** Bounded 0–100, robust to outliers, and directly explainable ("better than 75% of states"). Freezing the 30-state reference means a state's score does not change when a user narrows the comparison set, a property tested in CI |
| Min–Max | Scoring | Rejected: one extreme state (e.g. Arunachal's 278 km of highway per lakh people) compresses everyone else |
| Z-score | Scoring | Rejected for scoring (unbounded, assumes symmetry); **used** for VIF and PCA where centring/variance matter |
| Robust scaling (median/IQR) | Segmentation, first specification | **Tested and rejected:** produced singleton clusters (Mizoram, Arunachal) and failed the pre-stated cluster-size rule (§3.3) |
| `log`/`log1p` | Skewed size counts (GSDP, exports, factories, workers, loans) | Applied before ranking/scaling so size differences don't swamp ratios |
| Per-capita / per-lakh ratios | Absolute stocks (highways, beds, loans, bank offices) | Converts "big state" into "well-served state" |
| Direction reversal | Cost/risk indicators | Score = 100 − percentile, so higher always means more attractive |

Normalised indicator (production):

$$
p_{s,j} \;=\; 100 \cdot \frac{\#\{\,r \in R_j : r < x_{s,j}\} \;+\; \tfrac12\,\#\{\,r \in R_j : r = x_{s,j}\}}{|R_j|},
\qquad
\tilde p_{s,j} \;=\;
\begin{cases} p_{s,j} & \text{benefit indicator} \\ 100 - p_{s,j} & \text{cost / risk indicator}\end{cases}
$$

where $R_j$ is the frozen national reference sample for indicator $j$ (latest value for 28 states + Delhi + J&K, transformed identically).

### 2.3 Excluded / dropped features

Feature selection ran on the 30-state panel with both **statistical** and **domain** screens. Full log: `reports/segmentation/feature_screen.csv`, VIF rounds in `vif_rounds.csv`.

**Statistical screen (segmentation feature set)**

| Feature | Statistic | Decision | Business logic |
|---|---|---|---|
| Urban MPCE | coverage 18/30 | Dropped (segmentation) | No imputation; kept in industry scoring where pilots are covered |
| Rural non-farm wage | coverage 19/30 | Dropped (segmentation) | Same; Telangana is genuinely unpublished |
| CPI inflation, rail route per lakh | coverage 29/30 | Dropped (segmentation) | One missing state would force imputation |
| Peak demand not met | 100% of states share one value (0) | Dropped: zero variance | India's peak deficit is now negligible, so it cannot discriminate |
| Real GSDP (log) | **VIF 505** | Dropped | Size is already carried by exports and credit depth |
| Per-capita NSDP | **VIF 124** | Dropped | Collinear with loans per capita and power per capita (affluence) |
| Factory workers (log) | VIF 76 | Dropped | Duplicates factory count and exports |
| Bank offices per lakh | VIF 73 | Dropped | Collinear with credit depth |
| Internet subs per 100 | VIF 17.6 | Dropped | Tracks affluence and urbanisation |
| Manufacturing share | VIF 13.4 | Dropped | Captured by credit-to-industry share |
| Factories (log) | VIF 10.7 | Dropped | Last to exceed threshold |
| 15 retained features | all VIF ≤ 5.4 | Kept | Services/financial share, growth momentum, power, shortage, highways, credit share, CD ratio, loans, urban & rural UR, T&D losses, exports, beds |

The rule was iterative: remove the highest-VIF feature, recompute, and stop when the maximum VIF is 10 or below.

**Domain-driven exclusions (all models)**

| Excluded factor | Why |
|---|---|
| Commercial rents, plot prices, industrial tariffs, outage hours | No comparable public state series; **never estimated** |
| Policy incentives / DPIIT Startup ranking | Ordinal and methodology-dependent; shown as information, not scored |
| Company registrations (MCA) | Not obtainable without bypassing a CAPTCHA; registered office ≠ operating site |
| District youth unemployment | No official series exists; the app says so instead of estimating |
| Six separate "sector forecasts" from the services aggregate | Would mislabel one broad target as six independent forecasts (rule 8 of the blueprint) |

**Managerial lens on VIF in the scoring engine.** The production index *does* keep some correlated indicators (e.g. GSDP and per-capita NSDP inside "Demand"). This is deliberate: within a dimension, correlated indicators are weighted to a fixed dimension total, so redundancy cannot inflate a pillar's influence. VIF matters most in segmentation, where every feature contributes to distance, and that is where it was enforced.

---

## 3. Machine Learning Models & State Segmentation

The project uses two complementary model types. The **supervised forecast** answers *"will this state's sector grow?"* The **unsupervised segmentation** answers *"which states are structurally alike?"* A third component, the suitability index, answers *"which state best fits this business?"* and is covered in §4.

### 3.1 Supervised: one-year-ahead manufacturing growth forecast

**Target**

$$
g_{s,t+1} = 100 \times \left(\frac{Y_{s,t+1}}{Y_{s,t}} - 1\right),\qquad Y = \text{real manufacturing GSVA (RBI T34, 2011-12 prices)}
$$

**Design.** The panel is national: 30 states, 351 labelled state-years, origins FY 2012-13 to 2023-24. Features are lag-only: last-year and 2-year growth, 3-year mean, volatility, whole-economy growth, log per-capita income, manufacturing share and national mean growth. Business and infrastructure lags (ASI, credit, power) were tested in ablations.

| Model | Why considered | Validation MAE (pp, non-COVID) |
|---|---|---|
| Persistence (last year's growth) | Must-beat baseline | 13.37 |
| 3-year mean | Stable baseline | 10.87 |
| **Ridge (α = 100), macro lags** | Regularised, interpretable, suited to small panels | **9.56 (selected)** |
| ElasticNet (α = 0.5) | Sparse alternative | 9.73 |
| Random Forest (depth 3, leaf 10) | Non-linearity check | 9.92 |
| Gradient boosting (depth 2) | Flexible check | 10.43 |

**Protocol.** The CV is an expanding window by year and is never shuffled. Validation target years run 2017-18 to 2023-24, with COVID years reported separately. FY 2024-25 is an **untouched hold-out**, scored once. Scalers and imputers sit inside sklearn Pipelines, so they are fitted on training folds only.

**Acceptance rule (fixed before results).** The model must be ≥5% better than the best baseline, win in ≥60% of non-COVID years, and be no worse on the hold-out.

| Check | Result | Pass |
|---|---|---|
| MAE improvement vs 3-year mean | +12.1% | ✅ |
| Non-COVID validation years won | 4 / 5 | ✅ |
| Hold-out FY 2024-25 MAE | 3.31 vs 3.88 pp | ✅ |
| Year-block bootstrap of the gain | −1.31 pp (90% CI −2.89 to +0.20) | ⚠️ interval crosses zero, disclosed |

**Managerial lens.** Deep learning, LSTMs and XGBoost were deliberately **not** used: with ~13 years per state, complexity would overfit, and the ablations confirm that added features did not help. The forecast is shown with its 80% band (≈ ±12 pp) and its error history, so a strategist reads it as a *direction*, not a promise.

### 3.2 Unsupervised: algorithm selection

| Algorithm | Fit for 30 macro-units | Decision |
|---|---|---|
| **K-Means** (100 initialisations) | Fast, centroid profiles map naturally to business personas | **Primary** |
| **Ward hierarchical** | Deterministic, gives a dendrogram for explaining nesting; Ward minimises within-cluster variance like K-Means | **Cross-validation of K-Means** (agreement ARI 0.76 at k = 5) |
| DBSCAN | Density-based; flags outliers | **Tested and rejected:** across an ε grid it found 1–2 clusters with 0–10 states labelled noise. With 30 points in 15 dimensions density is too thin, and calling a state "noise" is not actionable |
| Gaussian mixtures / spectral | Need more data for stable covariances | Not justified at n = 30 |

### 3.3 Evaluation & hyperparameter decisions (choosing k)

**Pre-stated selection rule:** k must be in 3–6 (k = 2 is not a segmentation; above 6 is unusable for 30 states), every cluster must hold at least 3 states, and bootstrap stability must be ARI ≥ 0.6. Among the qualifying k, the highest silhouette wins.

**Primary specification: percentile-rank features**

| k | Inertia | Silhouette (K-Means) | Davies-Bouldin | K-Means vs Ward (ARI) | Min. cluster | Bootstrap ARI | Rule |
|---|---|---|---|---|---|---|---|
| 2 | 28.7 | 0.180 | 1.75 | 0.19 | 12 | 0.49 | ✗ (k range) |
| 3 | 22.9 | 0.192 | 1.50 | 0.81 | 9 | **0.73** | ✓ |
| 4 | 20.2 | 0.201 | 1.41 | 0.76 | 3 | 0.68 | ✓ |
| **5** | **17.8** | **0.213** | **1.31** | **0.76** | **3** | **0.66** | **✓ chosen** |
| 6 | 16.2 | 0.175 | 1.37 | 0.65 | 3 | 0.54 | ✗ (stability) |

Figures: `reports/segmentation/k_selection.png` (elbow, silhouette, Davies-Bouldin), `dendrogram.png`, `pca_clusters.png`.

**Statistical optimality vs business interpretability**

- The elbow is shallow, with no sharp knee. Silhouette peaks at k = 5 and Davies-Bouldin is lowest at k = 5, so the statistics and the rule agree.
- **k = 3 is the "stable" alternative** (bootstrap ARI 0.73) but merges three very different small-state groups into one basket. Business value comes from separating hill industrial enclaves from remote frontier economies, because their expansion logic differs completely.
- **Transparency note.** The first specification (robust scaling) produced a degenerate 28 / 1 / 1 split and failed the rule. We switched to percentile-rank scaling *after* seeing that result. It is the same normalisation the suitability index uses, and the rejected run is saved (`k_selection_robust_rejected.csv`). Rank vs z-score K-Means agreement is ARI 0.84, so the solution is not an artefact of scaling.
- **Honest limitation.** A silhouette of 0.21 means the structure is real but **weak**: Indian states lie on a continuum. The baskets are a *descriptive lens* for portfolio thinking and are not used to score states.

### 3.4 State baskets & business personas

Medians of raw values per cluster (national median in the last column). Source: `reports/segmentation/cluster_profiles.csv`.

| Indicator | C1 | C2 | C3 | C4 | C5 | National median |
|---|---|---|---|---|---|---|
| Per-capita NSDP (₹, 2011-12 prices) | 1,87,046 | 1,62,275 | 1,51,676 | 82,781 | 81,554 | 1,28,805 |
| Real GSDP (₹ crore) | 8,50,056 | 1,45,207 | 24,902 | 5,31,372 | 22,849 | 5,22,407 |
| Manufacturing share of GSVA | 16.2% | **32.1%** | 3.0% | 14.7% | 2.4% | 14.7% |
| Credit–deposit ratio (utilisation) | **86.9%** | 39.2% | 45.4% | 54.3% | 53.5% | 61.0% |
| Exports (US$ mn) | **19,953** | 228 | 12 | 7,165 | 2 | 2,115 |
| Power per person (kWh) | 1,725 | **1,803** | 568 | 714 | 607 | 1,274 |
| Internet subs per 100 | **99.5** | 97.7 | 88.2 | 66.0 | 74.6 | 81.4 |
| Personal loans per person (₹) | **69,965** | 42,485 | 48,071 | 20,595 | 33,888 | 41,137 |
| Urban unemployment (labour pool) | 4.7% | 8.2% | 3.2% | 6.8% | **11.4%** | 6.3% |
| Power T&D losses | 14.5% | 14.2% | 27.7% | 21.3% | 22.1% | 18.8% |

| Basket | States | Persona | Strategic read |
|---|---|---|---|
| **C1 · Mature Industrial & Services Cores** | Andhra Pradesh, Delhi, **Gujarat**, Haryana, **Karnataka**, Kerala, **Maharashtra**, Punjab, **Telangana**, **Tamil Nadu** | High income, deepest credit markets, export hubs, reliable power and digital access | Default destination for scale and skilled operations; competition and costs are higher; differentiate on corridor and city choice |
| **C2 · Hill Industrial Enclaves** | Goa, Himachal Pradesh, Uttarakhand | Highest manufacturing share and power per person, but low credit utilisation and small markets | Niche plants (pharma, packaged goods) using power and incentives; little local demand, so plan for outbound logistics |
| **C3 · Small High-Income Service States** | Mizoram, Sikkim, Tripura | Above-median income, low unemployment, tiny industrial base, high T&D losses | Consumer services and tourism on a small footprint; not for manufacturing scale |
| **C4 · Large Emerging Growth Markets** | Assam, Bihar, Chhattisgarh, Jharkhand, Madhya Pradesh, Odisha, **Rajasthan**, **Uttar Pradesh**, West Bengal | Large economies with low per-capita income and credit, weaker power and digital penetration | Volume and cost plays; early-mover advantage; infrastructure risk must be priced in |
| **C5 · Remote Frontier Economies** | Arunachal Pradesh, Jammu & Kashmir, Manipur, Meghalaya, Nagaland | Services-dominated (government), highest urban unemployment, minimal industry | Policy-led or public-sector-linked opportunities; very high execution risk |

**Pilot-state placement.** Five pilots (GJ, KA, MH, TG, TN) sit in the *Mature Cores*; RJ and UP are *Emerging Growth Markets*. This explains a recurring pattern in the industry rankings: UP and RJ trail on infrastructure but lead on growth momentum. That is the classic cost-of-entry vs growth-option trade-off.

---

## 4. Multi-Criteria Weighting & Scoring Framework

### 4.1 Weighting methodology

**Production weights are heuristic design defaults, not learned optima.** This is a deliberate MCDA (multi-criteria decision analysis) choice. They come from the project blueprint's expert-style pillar split (demand 25, infrastructure 20, outlook 20, labour 15, ecosystem 10, cost/policy 10), tilted per industry using documented domain rationale. For example, manufacturing upweights infrastructure and ecosystem, and hospitality upweights tourist demand.

| Industry | Demand | Infra. | Outlook | Labour | Ecosystem | Cost |
|---|---|---|---|---|---|---|
| Manufacturing | 15 | **25** | 20 | 15 | 15 | 10 |
| Retail | **30** | 15 | 20 | 15 | 10 | 10 |
| IT / professional | 20 | **25** | 20 | 20 | 10 | 5 |
| Logistics | 20 | **30** | 20 | 10 | 10 | 10 |
| Healthcare | **30** | 20 | 15 | 15 | 10 | 10 |
| Hospitality | **35** | 20 | 15 | 10 | 10 | 10 |

**Why not purely statistical (PCA/factor) weights in production?** PCA weights *variance*, not *business relevance*. An indicator that varies a lot can be strategically minor. AHP pairwise elicitation was not run because no expert panel was convened; that is listed as the next step. Instead we treat **PCA and equal weights as challenger models** to stress-test the design weights:

| Industry | PC1 share of variance | ρ (design vs equal) | ρ (design vs PCA) | Top-3 overlap with equal | Top-3 overlap with PCA |
|---|---|---|---|---|---|
| Manufacturing | 46% | 0.99 | 0.97 | 2 / 3 | 1 / 3 |
| Retail | 41% | 0.94 | 0.92 | 2 / 3 | 2 / 3 |
| IT / professional | 36% | 0.89 | 0.92 | 2 / 3 | 2 / 3 |
| Logistics | 37% | 0.93 | **0.66** | 2 / 3 | 2 / 3 |
| Healthcare | 36% | 0.86 | 0.96 | 2 / 3 | 2 / 3 |
| Hospitality | 26% | 0.79 | 0.77 | 3 / 3 | 3 / 3 |

*(Spearman rank correlations across all 30 states; source `reports/segmentation/weighting_comparison.csv`.)*

**Interpretation.** Across 30 states, the national ordering is largely weight-insensitive (ρ ≥ 0.86 in five industries). The fine top-3 order is not, and that is exactly where user priorities should matter. Logistics diverges most under PCA weights because PCA puts 31% on ecosystem against the design's 10%. A manager who believes clustering effects dominate logistics should raise that weight, and the what-if panel lets them.

### 4.2 Composite index formulation

1. **Indicator score**: $\tilde p_{s,j}$ as defined in §2.2.

2. **Dimension score.** Only *observed* indicators count, and indicator weights renormalise over what is observed:

$$
D_{s,d} \;=\; \sum_{j \in J_d \cap O_s} \frac{v_j}{\sum_{k \in J_d \cap O_s} v_k}\;\tilde p_{s,j}
$$

   Here $J_d$ is the set of indicators in dimension $d$, $O_s$ the set of indicators observed for state $s$, and $v_j$ the within-dimension indicator weight.

3. **User-adjusted dimension weights.** Each of up to three chosen priorities applies $m_{\text{pri}} = 1.6$; each supported operational need applies $m_{\text{need}} \in \{1.15, 1.25\}$:

$$
w'_d = w_d \cdot \prod_{\text{priorities}\,\to d} m_{\text{pri}} \cdot \prod_{\text{needs}\,\to d} m_{\text{need}},
\qquad \hat w_d = \frac{w'_d}{\sum_{d'} w'_{d'}}
$$

4. **Composite suitability index.** Missing dimensions are dropped and the remaining weights renormalised:

$$
S_s \;=\; \frac{\sum_{d \in \mathcal{D}_s} \hat w_d\, D_{s,d}}{\sum_{d \in \mathcal{D}_s} \hat w_d}\;\in[0,100],
\qquad \mathcal{D}_s = \{d : D_{s,d}\ \text{observed}\}
$$

5. **Eligibility gate.** A state is excluded (not scored low) if any *mandatory* dimension for the industry is empty. With fewer than 2 eligible states, no ranking is produced.

6. **Forecast factor.** The forecast enters "Outlook" **only** if the industry's model passed validation and the state has current data. Otherwise outlook uses historical momentum, labelled as such.

### 4.3 Sensitivity & robustness

**Method.** For each of 500 draws, every dimension weight is multiplied by $U(0.8, 1.2)$ and renormalised, and the pilots are re-ranked. In the app each state shows the share of draws in which it keeps its rank, plus its best and worst rank.

| Industry (default weights) | Leader | Gap 1st–2nd (pts) | Leader kept in draws | Mean ρ vs base | Worst ρ |
|---|---|---|---|---|---|
| Healthcare | Karnataka | 6.1 | **100%** | 1.00 | 1.00 |
| Hospitality | Karnataka | 2.4 | **100%** | 1.00 | 1.00 |
| Logistics | Maharashtra | 0.7 | 82% | 0.97 | 0.89 |
| IT / professional | Karnataka | 0.9 | 82% | 0.99 | 0.96 |
| Retail | Telangana | 0.3 | 59% | 0.98 | 0.93 |
| **Manufacturing** | Telangana | **0.2** | **51%** | 0.91 | 0.64 |

**Counter-explanation.** For every result the engine computes what would make the runner-up win. Example (UP manufacturer demo, power/logistics/labour priorities): *"Gujarat scores 95 vs 63 for Telangana on business ecosystem (mainly manufacturing share of GSVA). If that dimension carried about 1.5× its current weight, Gujarat would rank first."*

**Policy & strategic allocation implications**

- **Robust leaders** (healthcare, hospitality → Karnataka) can support a *concentrated* bet.
- **Near-ties** (manufacturing default: Telangana 63.2, Maharashtra 63.0, Tamil Nadu 62.7) argue for a **shortlist and site visits**, not a single-state commitment. The app states this explicitly.
- Personalisation helps: once the UP manufacturer's priorities are applied, Telangana's lead becomes stable (same rank in 99% of draws). The engine converts stated strategy into a clearer answer.
- For policymakers, weight-insensitive *weakness* (e.g. UP's infrastructure dimension at 30/100 under every reasonable weighting) is a robust intervention target, unlike rank changes driven by weighting choices.

---

## 5. Deployment, Business Delivery & Decision Architecture

### 5.1 Production tech stack

| Layer | Technology | Role |
|---|---|---|
| Language & environment | Python 3.11 (venv), Node 24 | Pipeline; web engine parity tests |
| Ingestion | `requests`, `lxml`, `pdfplumber`, `openpyxl` | Download, HTML/XLSX/PDF table extraction |
| Data layer | `pandas`, `pyarrow` (Parquet), **DuckDB** (SQL warehouse) | `dim_state`, `fact_economic`, `fact_indicator`, `latest_indicator` view |
| Geospatial | `geopandas`, `shapely`, DuckDB spatial | Ookla tiles → districts; state map |
| Modelling | `scikit-learn` (Ridge, ElasticNet, RF, HGB, K-Means, Ward, DBSCAN, PCA), `statsmodels` (VIF), `scipy` | Forecast, segmentation, weighting challengers |
| Scoring | `scoring/score.py` + versioned `weights_v1.yaml` | Deterministic, testable MCDA engine |
| Apps | **Streamlit** (analyst app), **static HTML/JS on Vercel** (public app) | Decision interfaces |
| Visualisation | Plotly (palette validated for colour-blind separation) | Map, bars, stability |
| Quality | `pytest` (**91 tests**), Playwright browser checks, audit-trace script | Regression, leakage, parity, provenance |
| Versioning | Git (local), source register with SHA-256 | Reproducibility |

**Pipeline.** The flow runs in this order:
`download_sources` → `ingest_rbi_hsis` / `ingest_hces` / `ingest_trai_pir` / `ingest_secondary` → `validate` → `build_indicators` → DuckDB → `build_panel` → `train` → `eligibility` → `score` → apps.

### 5.2 Serving & consumption

| Channel | Audience | How it works |
|---|---|---|
| **Public web app** (Vercel, static) | Executives, expansion teams | The JavaScript port of the scoring engine runs **in the browser**, so no user input leaves the device. Python-vs-JS parity is enforced by tests on 11 profiles (identical scores) |
| **Streamlit app** | Analysts | Same journey plus full indicator drill-down and server-side PDF brief |
| **Exports** | Investment committee packs | CSV with every indicator's value, period, source file + URL, weights and scoring version; PDF/print brief with caveats |
| **Reports** | Auditors, panel | Model card, validation report, eligibility matrix, coverage heatmap, audit trace, segmentation outputs |

**Deliberately not built.** There is no Power BI dashboard and no FastAPI endpoint. A Power BI layer would duplicate the scoring logic outside version control. A REST API is the natural next step once a second consuming system exists, and the engine is already a pure function (profile → ranking), so wrapping it is low-risk.

**User journey (5 screens).** The journey has five screens:

1. **Landing:** scope and what the index is not.
2. **Business profile:** industry, current state, capital (context only), up to 3 priorities, operational needs, with a live weights preview.
3. **Eligibility:** which states can be compared, data gaps, source vintages.
4. **Results:** top-3 cards with evidence and watch-outs, map, matrix, what-if sliders, stability, two-state compare, model vs managerial interpretation.
5. **Methods & lineage.**

### 5.3 Managerial takeaways & strategic actionability

**How a corporate strategist uses it**

| Decision stage | Use of the system | Example from this build |
|---|---|---|
| Portfolio framing | Start from the **basket**, not the state | A cost-led plant looks first at *Emerging Growth Markets* (UP, RJ); a skilled-services centre at *Mature Cores* |
| Shortlisting | Top-3 index with priorities applied | UP manufacturer (power, logistics, labour) → Telangana 64.5, Gujarat 62.8, Tamil Nadu 61.9 |
| Stress-testing | Stability panel + counter-explanation | Telangana keeps rank 1 in 99% of draws; Gujarat wins only if ecosystem weight rises ~1.5× |
| Due diligence | Watch-outs + data confidence | Telangana: no rural wage series (cost uses other indicators); Gujarat: accounts end FY 2022-23, *Medium* confidence |
| Capital allocation | Concentrate where robust, stage where near-tied | Manufacturing default is a three-way near-tie: phase capex behind site-level diligence in all three |

**How a policymaker uses it**

- **Diagnose robust gaps.** Dimension scores that stay low under every weighting (e.g. UP and RJ infrastructure) are investment-attraction bottlenecks.
- **Benchmark within baskets.** Compare a state with its structural peers, not with the national leader. That gives fairer targets for, say, Rajasthan versus Madhya Pradesh or Odisha.
- **Prioritise data infrastructure.** The data gaps the system discloses (state youth unemployment, Gujarat's lagged accounts, rural wages) are themselves policy findings: missing data raises investors' perceived risk.

**What the business gets (ROI)**

- **Time.** First-pass state screening drops from weeks of analyst desk research to minutes, with a full evidence pack.
- **Risk.** Visible caveats, confidence labels and near-tie warnings reduce the chance of over-committing on a fragile ranking.
- **Defensibility.** Every figure is audit-traceable (20/20 random checks pass) and weights are versioned. The recommendation can be challenged and reproduced.

**Limitations the panel should weigh**

1. State averages hide corridor and district variation; this is *screening*, not site selection.
2. One data vintage: the forecast backtest uses revised data.
3. Weights are expert-style defaults, not AHP-elicited or learned.
4. Segmentation structure is weak (silhouette 0.21): useful for framing, not for hard rules.
5. Ookla speed data is non-commercial (CC BY-NC-SA). A commercial deployment needs a licence.

**Recommended next steps**

1. **AHP weight elicitation** with 5–7 industry experts, and a consistency ratio below 0.1.
2. Add Gujarat DES figures for FY 2023-25 as a separately labelled panel.
3. District layer (Ookla speeds already extracted for 28 cities) for second-stage site screening.
4. Real-time-vintage archive of RBI editions for a true out-of-sample forecast test.
5. A REST API around the pure scoring function for CRM/ERP integration.

---

### Appendix A — Reproducibility

```bash
python -m etl.ingest_rbi_hsis && python -m etl.validate && python -m etl.ingest_hces \
 && python -m etl.ingest_trai_pir && python -m etl.ingest_secondary && python -m etl.build_indicators \
 && python -m features.build_panel && python -m models.train && python -m etl.eligibility \
 && python -m analysis.segmentation && python scripts/audit_trace.py && pytest
```

### Appendix B — Evidence files

| Claim | File |
|---|---|
| Source register (83 files, SHA-256) | `data/source_register.csv` |
| Validation, revisions, outliers | `reports/validation_rbi_panel.md`, `reports/coverage_heatmap.png` |
| Model metrics & acceptance | `reports/model_card_manufacturing.md`, `models/registry.json` |
| Eligibility (7 × 6) | `reports/eligibility_matrix.csv` |
| Segmentation, VIF, k-selection, PCA, weighting challengers, sensitivity | `reports/segmentation/` |
| Audit trace (20/20) | `reports/audit_report.md` |
| Unavailable / unverified data | `reports/unavailable_sources.csv`, `reports/unverified_values.csv` |
