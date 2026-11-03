# Model card: manufacturing real GSVA growth (one year ahead)
**Status: VALIDATED**. Passed the pre-specified acceptance rule.

## Target
- g(s, t+1) = 100 x (Y(t+1)/Y(t) - 1), Y = real manufacturing GSVA, RBI Handbook of Statistics on Indian States 2024-25, Table 34, constant 2011-12 prices (Rs lakh). Single vintage (11 Dec 2025).
- This is a state-level macro outcome. It is not a forecast of any firm's revenue, profit or survival.

## Data
- National panel: 30 states (28 states + Delhi + J&K), 351 labelled state-years, origins 2012-13..2023-24.
- J&K 2019-20 excluded (geography break). Growth beyond +-40% is kept (flagged in validation).
- Features are lag-only and joined as of the forecast date using each observation's estimated first-release date (`first_pub_est`); the build asserts that no feature was published after its forecast date.
- Limitation: only one data vintage is available, so the backtest uses revised data, not the real-time first estimates a forecaster would have had (17-19 pilot cells were revised between the 2023 and 2024-25 editions).

## Protocol
- Expanding-window CV by target year, never shuffled. Validation target years 2017-18..2023-24; hold-out 2024-25 scored once after selection.
- Imputer and scaler inside sklearn Pipelines (fitted on each training fold only).
- Baselines: persistence (last year's growth) and 3-year mean.
- Acceptance rule, fixed before results: {"mae_improvement_vs_best_baseline": 0.05, "min_share_of_years_won": 0.6, "holdout_not_worse": true}

## Model comparison (validation, non-COVID target years, percentage points of growth)
| model                                    |   n |   mae |   rmse |   medae |   bias |   directional_acc |
|:-----------------------------------------|----:|------:|-------:|--------:|-------:|------------------:|
| ridge(a=100)|macro                       | 148 |  9.56 |  12.66 |    8.02 |   5.83 |              0.76 |
| ridge(a=100)|macro+business              | 148 |  9.71 |  12.78 |    8.39 |   5.87 |              0.77 |
| enet(a=0.5)|macro                        | 148 |  9.73 |  12.83 |    8.13 |   5.95 |              0.76 |
| enet(a=0.5)|macro+business               | 148 |  9.84 |  12.94 |    8.70 |   6.02 |              0.77 |
| ridge(a=100)|macro+business+infra        | 148 |  9.85 |  12.91 |    8.49 |   6.08 |              0.76 |
| rf(depth=3,leaf=10)|macro+business+infra | 148 |  9.92 |  14.56 |    7.36 |   6.42 |              0.76 |
| enet(a=0.5)|macro+business+infra         | 148 |  9.96 |  13.07 |    8.95 |   6.23 |              0.76 |
| rf(depth=3,leaf=10)|macro+business       | 148 |  9.96 |  14.58 |    7.19 |   6.21 |              0.76 |
| rf(depth=3,leaf=10)|macro                | 148 | 10.00 |  14.73 |    7.48 |   6.40 |              0.74 |
| enet(a=0.1)|macro                        | 148 | 10.21 |  13.19 |    8.47 |   5.87 |              0.72 |
| ridge(a=10)|macro                        | 148 | 10.23 |  13.19 |    8.51 |   5.84 |              0.72 |
| ridge(a=1)|macro                         | 148 | 10.37 |  13.37 |    8.54 |   5.85 |              0.72 |
| hgb(depth=2)|macro+business+infra        | 148 | 10.43 |  14.98 |    8.00 |   5.48 |              0.73 |
| enet(a=0.1)|macro+business               | 148 | 10.53 |  13.45 |    9.21 |   5.95 |              0.72 |
| ridge(a=10)|macro+business               | 148 | 10.59 |  13.48 |    9.36 |   5.92 |              0.71 |

Selected specification: `ridge(a=100)|macro`. Best baseline: `mean3`.

## Acceptance
| check | value | pass |
|---|---|---|
| MAE improvement vs mean3 | +12.1% | True |
| share of non-COVID validation years won | 80% | True |
| hold-out 2024-25 MAE (model vs best baseline) | 3.31 vs 3.88 | True |

Year-block bootstrap of MAE(model) - MAE(mean3): -1.31 pp (90% interval -2.89 to +0.20). With 5 non-COVID validation years the uncertainty is wide: the rule is passed, but the interval does not exclude zero, so the gain over the baseline is not statistically clear. The app shows the forecast with its 80% band and these error figures, never as a point promise.
- Forecast band: 10th-90th percentile of non-COVID validation residuals across all 30 states, so it is wide (about +-12 pp); small, volatile states dominate it. Positive bias = the model over-predicted on average during the 2017-2020 slowdown.
- Penalty alpha=100 is the top of the pre-set grid; it was not extended afterwards, to keep the hold-out untouched.

## Per target year (all validation years)
| target_fy   |   n |   mae |   medae |   directional_acc |   mean3_mae |
|:------------|----:|------:|--------:|------------------:|------------:|
| 2017-18     |  30 |  9.53 |    8.14 |              0.67 |       14.29 |
| 2018-19     |  30 |  8.85 |    8.01 |              0.70 |       10.18 |
| 2019-20     |  29 | 13.77 |   10.35 |              0.66 |       14.72 |
| 2020-21     |  29 | 11.81 |    7.24 |              0.69 |       12.04 |
| 2021-22     |  30 | 14.78 |    7.61 |              0.77 |       17.43 |
| 2022-23     |  30 | 11.03 |   11.12 |              0.90 |        8.81 |
| 2023-24     |  29 |  4.59 |    3.73 |              0.90 |        6.34 |

## COVID target years (2020-21, 2021-22), reported separately
|             |     n |   mae |   rmse |   medae |
|:------------|------:|------:|-------:|--------:|
| model       | 59.00 | 13.32 |  22.38 |    7.46 |
| persistence | 59.00 | 17.72 |  32.13 |   10.01 |
| mean3       | 59.00 | 14.78 |  25.44 |    8.96 |

## Pilot states (non-COVID validation years)
| state         |   n |   mae |   medae |   mean3_mae |
|:--------------|----:|------:|--------:|------------:|
| Gujarat       |   4 |  3.56 |    3.52 |        2.96 |
| Karnataka     |   5 |  7.84 |    7.07 |        9.29 |
| Maharashtra   |   5 | 10.55 |   10.50 |        5.68 |
| Rajasthan     |   5 |  4.96 |    2.44 |        4.89 |
| Telangana     |   5 |  9.27 |    7.17 |        6.47 |
| Tamil Nadu    |   5 |  5.50 |    8.25 |        5.95 |
| Uttar Pradesh |   5 | 12.32 |   11.84 |       15.57 |

## Ablation: best validation MAE by model family and feature set
| family   |   macro |   macro+business |   macro+business+infra |
|:---------|--------:|-----------------:|-----------------------:|
| enet     |    9.73 |             9.84 |                   9.96 |
| hgb      |  nan    |           nan    |                  10.43 |
| rf       |   10.00 |             9.96 |                   9.92 |
| ridge    |    9.56 |             9.71 |                   9.85 |

Adding business (ASI, credit) and infrastructure (power) features is only worthwhile where the MAE falls; differences of a few hundredths of a point are noise at this sample size.

## Permutation importance (model attribution, not causation)
|             |   mae_increase |
|:------------|---------------:|
| g_lag1      |          0.191 |
| g_mean3     |          0.177 |
| nat_g_lag1  |          0.170 |
| gsva_g_lag1 |          0.079 |
| g_lag2      |          0.052 |
| log_pc_nsdp |          0.034 |
| g_vol       |          0.008 |
| mfg_share   |         -0.076 |

## Sub-sector targets for other industries
The RBI handbook publishes constant-price GSVA for agriculture, manufacturing, construction, industry, financial services and services only. Trade & repair, hotels & restaurants, transport & storage, real estate & professional services and health are not published by state in a consistent 2011-12 base panel in any file obtained. Retail, IT/professional services, logistics, healthcare and hospitality are therefore ranking-only, and the broad services aggregate is shown as context, never as a sector forecast (rule 8).
