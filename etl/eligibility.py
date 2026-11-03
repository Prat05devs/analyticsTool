"""Industry-state eligibility matrix: approve / ranking-only / exclude, with reasons.

    python -m etl.eligibility

approve       mandatory dimensions observed AND a validated forecast model exists for the industry AND the
              state's target series reaches the latest panel year (so a forecast can be issued)
ranking-only  mandatory dimensions observed but no validated forecast for this industry/state
exclude       a mandatory dimension has no observed official indicator for the state
"""
from __future__ import annotations

import sys

import pandas as pd

from etl.common import CUR, REP
from etl.states import name_of
from scoring.data import PILOT_IDS, latest, registry, spec


def matrix() -> pd.DataFrame:
    s = spec()
    reg = registry()
    econ = pd.read_parquet(CUR / "fact_economic.parquet")
    lat = latest()
    rows = []
    for ind_code, prof in s["industries"].items():
        target = prof.get("model_target")
        model = reg.get(target, {}) if target else {}
        for sid in PILOT_IDS:
            have = set(lat[lat.state_id == sid].feature_code)
            missing_dims, notes = [], []
            for dim, inds in prof["indicators"].items():
                obs = [i for i in inds if i in have and not s["indicators"][i].get("requires_model")]
                if not obs and dim in prof["mandatory_dimensions"]:
                    missing_dims.append(dim)
                gaps = [i for i in inds if i not in have and not s["indicators"][i].get("requires_model")]
                if gaps:
                    notes.append(f"{dim}: no data for {', '.join(gaps)}")
            if missing_dims:
                status, reason = "exclude", f"mandatory dimension(s) without observed data: {', '.join(missing_dims)}"
            elif not target:
                status, reason = "ranking-only", prof.get("target_note", "no defensible sector target")
            elif model.get("status") != "validated":
                status, reason = "ranking-only", model.get("reason", "forecast model not validated (Phase 3 pending)")
            else:
                t = econ[(econ.state_id == sid) & (econ.activity_code == target)].dropna(subset=["value_rs_lakh"])
                last = t.fy.max()
                if last != model.get("latest_feature_fy"):
                    status, reason = "ranking-only", (f"validated model, but {name_of(sid)}'s {target} series ends in "
                                                      f"{last}, so no forecast can be issued for "
                                                      f"{model.get('forecast_fy')}")
                else:
                    status, reason = "approve", f"validated {target} model; latest observation {last}"
            rows.append({"industry": ind_code, "state_id": sid, "state": name_of(sid), "status": status,
                         "reason": reason, "data_gaps": "; ".join(notes)})
    return pd.DataFrame(rows)


# Ranking indicators the prompts asked for that no script could obtain (reason recorded, never estimated)
UNAVAILABLE_SOURCES = {
    "plfs_2025_state_lfpr_wpr_ur": "PLFS Annual Report 2025 state tables: press note has all-India only; full report not "
                                   "reachable by script (mospi.gov.in is a JavaScript app). Latest official state UR used "
                                   "instead: PLFS 2023-24 via RBI T08/T09.",
    "asi_2024_25_state": "ASI 2024-25 factsheet/press note have no Annexure-II state tables; ASI 2023-24 state data used "
                         "via RBI T116-T132.",
    "tourism_2016_2025": "Tourism compendium 2025 and Lok Sabha 2016-2025 series return HTTP 404; RBI T13/T182 (to 2024) used.",
    "mca_ogd_companies": "data.gov.in company master needs an API key and a CAPTCHA; MCA portal unreachable. Not bypassed.",
    "plfs_youth_ur_state": "DGE/eparlib PDFs return 404 / DNS failure; values in data/extracted cannot be traced to a raw file.",
    "district_youth_unemployment": "No official district-level youth unemployment series exists.",
}


def coverage() -> pd.DataFrame:
    s = spec()
    lat = latest(quality=("official", "derived", "secondary", "private")).set_index(["state_id", "feature_code"])
    rows = []
    for code, meta in s["indicators"].items():
        for sid in PILOT_IDS:
            if (sid, code) in lat.index:
                r = lat.loc[(sid, code)]
                rows.append({"state": name_of(sid), "indicator": code, "value": r.value, "unit": r.unit,
                             "period": r.period, "quality": r.quality, "source_file": r.source_file.split(";")[0]})
            elif meta.get("requires_model"):
                rows.append({"state": name_of(sid), "indicator": code, "value": None, "quality": "unavailable",
                             "period": "", "unit": meta["unit"], "source_file": "",
                             "reason": "only shown if the forecast model passes validation"})
            else:
                rows.append({"state": name_of(sid), "indicator": code, "value": None, "quality": "unavailable",
                             "period": "", "unit": meta["unit"], "source_file": "",
                             "reason": "not published for this state in the source table"})
    return pd.DataFrame(rows)


def main():
    m = matrix()
    m.to_csv(REP / "eligibility_matrix.csv", index=False)
    cov = coverage()
    cov.to_csv(REP / "indicator_coverage_pilots.csv", index=False)
    pd.DataFrame([{"source": k, "reason": v} for k, v in UNAVAILABLE_SOURCES.items()]).to_csv(
        REP / "unavailable_sources.csv", index=False)
    print(f"coverage: {int(cov.value.notna().sum())} values, {int(cov.value.isna().sum())} explicit 'unavailable'")
    print(cov[cov.value.isna()][["state", "indicator", "reason"]].to_string())
    print(m.pivot(index="state", columns="industry", values="status").to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
