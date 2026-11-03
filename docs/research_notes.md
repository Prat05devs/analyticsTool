# Research notes — latest public data (checked 3 Nov 2026)

## 1. The big finding: GDP base-year change
- MoSPI moved national accounts to **base year 2022-23** (new GDP series released 27 Feb 2026).
- The uniform guideline for **state** GSVA on the 2022-23 base was finalised in May 2026; states were still being onboarded, and joint discussions covered only current-price 2022-23 to 2024-25. A full back series was expected around Dec 2026.
- **Implication:** the only long, comparable, constant-price state-sector panel available today is the **2011-12 base** series (RBI Handbook 2024-25, data 2011-12 to 2024-25 → about 13 growth observations per state). Train the ML on that. Show the new-series figures (when available) as context only, in a separate panel. Re-check before launch.

## 2. Best single source: RBI Handbook of Statistics on Indian States 2024-25
- Released 11 Dec 2025, the 10th edition. It has HTML, XLSX and PDF for every table (links in `data_sources.yaml`).
- Constant-price GSVA by activity is available for: agriculture, manufacturing, construction, industry, financial services, services, plus total GSVA/GSDP/NSDP and per-capita NSDP.
- It also has unemployment (rural/urban), domestic and foreign tourist visits, health infrastructure, public health spending, CPI by state, rural wages, number of factories, and infrastructure tables.
- Note: the handbook does **not** split services into trade/hotels/transport/real estate. For Retail, Logistics, IT services and Hospitality targets, get the detailed activity GSVA from MoSPI or the state DES. Otherwise those sectors stay **ranking-only**, as the blueprint expects.
- Spot check (2023 edition, manufacturing GSVA, constant 2011-12 prices, ₹ lakh): Gujarat 2021-22 = 43,722,492; Maharashtra 2021-22 = 34,115,536; Gujarat and Maharashtra 2022-23 were "not available" in that edition. Reference values are in `tests/fixtures/rbi_2023_mfg_gsva_reference.csv`. Values can be revised between editions, so treat a difference as a revision to log, not automatically an error.

## 3. Latest releases for ranking indicators
| Dimension | Source | Latest | Notes |
|---|---|---|---|
| Demand | HCES 2023-24 | Aug 2023–Jul 2024 | State rural/urban MPCE. A snapshot: don't interpolate. |
| Labour | PLFS Annual Report 2025 | Jan–Dec 2025 (released Mar 2026) | All-India LFPR 59.3%, UR 3.1%. New design + calendar year means a **series break** with earlier July–June reports. |
| Industry | ASI 2024-25 | FY 2024-25 (released 30 Sep 2026) | State factories, workers, capital, GVA in Annexure-II. Tamil Nadu leads on establishments and employment, Maharashtra on GVA. |
| Digital | TRAI PIR | Apr–Jun 2026 (12 Oct 2026); yearly 2025-26 (5 Oct 2026) | By licensed service area, not state, so it needs a documented mapping. |
| Tourism | Tourism ministry | State DTV/FTV 2016–2025 (Lok Sabha answer, Mar 2026); compendium 2025 | UP 2025 visits are inflated by the Kumbh Mela. |
| Power | CEA power supply position | FY 2025-26 | Shortage %, which is not outage hours or tariffs. |
| Roads | MoRTH Basic Road Statistics | confirm latest | Road density. |
| Formal firms | MCA / OGD company master | snapshot | CAPTCHA on MCA, so use OGD. |
| Policy | DPIIT States' Startup Ranking 5th ed. | Jan 2026 | Ordinal, so informational only. |

## 4. Access notes
- The government portals block some automated clients. `rbidocs.rbi.org.in` showed a browser check to a bot during research. If a script gets HTML instead of XLSX, download the file in a browser and put it in `data/raw/<source_id>/<vintage>/`.
- RBI's new website (website.rbi.org.in) redirected during research; the `www.rbi.org.in/scripts/PublicationsView.aspx?id=...` pages worked.

## 5. Sector → target feasibility (initial view, to be confirmed by audit)
| Sector | Target candidate | Expectation |
|---|---|---|
| Manufacturing | RBI T34 manufacturing GSVA, constant | **Most likely to pass**. Start here. |
| Retail | Trade & repair GSVA (MoSPI/DES) | Proxy at best; likely ranking-only. |
| IT/professional | Real estate & professional services GSVA | Mixed aggregate; ranking-only. |
| Logistics | Transport & storage GSVA | Check availability; else ranking-only. |
| Healthcare | Health GSVA rarely separable | Ranking-only. |
| Hospitality | Hotels & restaurants (often bundled with trade) | Tourism-context ranking-only. |


## 6. Added 3 Nov 2026: latest-first data, internet, youth jobs, wages
### What's newest (2026)
- **PLFS monthly** (all-India, CWS): July 2026 UR 5.1%, LFPR 55.4%. The August 2026 bulletin is out.
- **PLFS quarterly Apr-Jun 2026** (released 10 Aug 2026): LFPR 54.6%, urban UR 6.7%, rural UR 4.8%. Youth (15-29) CWS UR was reported as 15.9%, up from 15.0% in Jan-Mar. **State-level estimates for selected states are in the bulletin**, so parse them on the laptop.
- **PLFS Annual 2025** (Jan-Dec 2025): youth UR (usual status) 9.9%; 25% of 15-29 year olds are NEET; regular salaried earnings ₹24,217 a month for men and ₹18,353 for women.
- **TRAI** Apr-Jun 2026: 1,114.17 million internet subscribers.
- **GST** FY2025-26 state totals and Sept 2026 growth (UP and Telangana +18%, Gujarat +17%, Karnataka +16%, Maharashtra +15%). These came from secondary compilations; swap in the official GSTN files.
- **ASI 2024-25** (released 30 Sep 2026) and **RBI Handbook 2024-25** (state GSVA to FY2024-25) are the freshest structural data.

### Internet availability and speed at district/city level
- **Ookla open data** gives quarterly ~610 m tiles of measured fixed and mobile speed, which aggregate to districts and cities. The script is in `scripts/`. **The licence is CC BY-NC-SA (non-commercial)**, so a commercial app needs Ookla's permission.
- **TRAI Independent Drive Tests** give official, city-specific 4G/5G throughput by operator. Many were run in 2026, including Ahmedabad/Gandhinagar in Feb 2026, Rajasthan, and UP districts in Sep 2026.
- **Availability:** TRAI subscribers per 100 by service area; NFHS-5 district internet use (2019-21, old).

### Youth unemployment
- State-level is the finest official grain: annual by state, and quarterly by state since 2025 for selected states. **No official district youth unemployment exists.** The app must say so instead of estimating it.
- State youth UR 2023-24 (usual status) for the pilots: Gujarat 3.1, Uttar Pradesh 9.1, Karnataka 10.2, Maharashtra 10.8, Rajasthan 12.4, Tamil Nadu 15.3, Telangana 16.6 (All India 10.2). This is in `data/extracted/labour/`.

### Salaries and hiring cost
- **Legal floor:** state minimum wages by zone and skill level, revised in 2026. Secondary compilers disagree, so verify every figure against the state notification.
- **Official averages:** PLFS earnings by state (annual report 2025); ASI emoluments per factory employee; Labour Bureau rural wages.
- **Market bands by city and level:** private surveys only (Indeed PayMap, Randstad 2025-26, Michael Page 2026). For example, Indeed PayMap puts 0-2 years' experience in Chennai at ₹30,100 a month versus ₹27,200 in Pune. Label these as private.
- **District salaries:** no official or reliable public source. Use the zone minimum wage plus the state urban/rural PLFS average.

### Data revisions to watch
- Comparing the 2023 and 2024-25 RBI editions: 17 of 82 pilot-state manufacturing cells were revised, for example Telangana 2022-23 down 20.1%, UP 2022-23 down 12.9% and Tamil Nadu 2022-23 down 9.0%. **Model training must use a single vintage**, and forecast backtests should ideally use real-time vintages.
- Gujarat has no 2023-24 or 2024-25 GSVA in the RBI handbook. Take it from the Gujarat DES / Socio-Economic Review, and label it as a different source.
