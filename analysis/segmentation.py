"""State segmentation and weighting robustness on the national reference panel (30 states).

    python -m analysis.segmentation

Complements the screening engine (which ranks states for one industry and one user) with an unsupervised view:
which states look structurally alike? Everything is computed from fact_indicator (raw-traceable), no imputation.

Steps
1. Feature screen: keep indicators observed for all 30 reference states; log1p skewed counts; drop near-constant
   indicators (>= 80% of states share one value); drop multicollinear ones by iterative VIF > 10.
2. Scaling. First specification: robust scaling (median / IQR). It produced singleton clusters driven by small
   hill states' extreme per-person ratios and failed the pre-stated k rule, so the primary specification uses
   percentile ranks (the same normalisation as the suitability index). This switch was made AFTER seeing the
   robust-scaling result and is disclosed as such; both runs are saved.
3. K-Means (k = 2..8, 100 inits) and Ward hierarchical clustering: inertia, silhouette, Davies-Bouldin,
   Calinski-Harabasz, K-Means vs Ward agreement (ARI) and bootstrap stability (ARI over 300 resamples).
   DBSCAN over an eps grid as a density-based check.
4. Cluster profiles (medians of raw values) and pilot-state membership.
5. Weighting robustness: for each industry, rank the 30 states with the design weights (v1), equal dimension
   weights and PCA-derived dimension weights; Spearman correlations and top-3 overlap. Stability of the pilot
   ranking under +-20% weight perturbations (500 draws).
Outputs: reports/segmentation/*.csv, *.png and summary.json.
"""
from __future__ import annotations

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.cluster.hierarchy import dendrogram, linkage  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402
from sklearn.cluster import DBSCAN, AgglomerativeClustering, KMeans  # noqa: E402
from sklearn.decomposition import PCA  # noqa: E402
from sklearn.metrics import (adjusted_rand_score, calinski_harabasz_score, davies_bouldin_score,  # noqa: E402
                             silhouette_score)
from sklearn.preprocessing import RobustScaler, StandardScaler  # noqa: E402
from statsmodels.stats.outliers_influence import variance_inflation_factor  # noqa: E402

from etl.common import REP  # noqa: E402
from etl.states import name_of  # noqa: E402
from scoring.data import PILOT_IDS, latest, reference_ids, spec  # noqa: E402
from scoring.score import Profile, score  # noqa: E402

OUT = REP / "segmentation"
SEED = 2026
CANDIDATES = {  # code -> transform
    "per_capita_nsdp_real": None, "gsdp_rs_crore": "log", "share_manufacturing": None, "share_services": None,
    "share_financial_services": None, "momentum_gsva_total": None, "momentum_manufacturing": None,
    "per_capita_power_availability": None, "power_shortage_pct": None, "peak_unmet_pct": None,
    "internet_subs_per_100": None, "nh_km_per_lakh_pop": None, "rail_km_per_lakh_pop": None,
    "credit_industry_share": None, "cd_ratio_utilisation": None, "bank_offices_per_lakh_pop": None,
    "personal_loans_per_capita": "log", "ur_urban_us_adj": None, "ur_rural_us_adj": None,
    "cpi_inflation_general": None, "td_losses_pct": None, "asi_workers": "log", "asi_factories": "log",
    "exports_usd_mn": "log", "govt_beds_per_lakh_pop": None, "rural_wage_nonagri": None, "mpce_urban": None,
}


def feature_screen():
    ids = reference_ids()
    lat = latest(CANDIDATES)
    lat = lat[lat.state_id.isin(ids)]
    raw = lat.pivot(index="state_id", columns="feature_code", values="value").reindex(ids)
    log = []
    cov = raw.notna().sum()
    for c in CANDIDATES:
        n = int(cov.get(c, 0))
        if n < len(ids):
            log.append({"feature": c, "decision": "dropped", "reason": f"coverage {n}/{len(ids)} states (no imputation)"})
    keep = [c for c in CANDIDATES if cov.get(c, 0) == len(ids)]
    X = raw[keep].copy()
    for c in keep:
        if CANDIDATES[c] == "log":
            X[c] = np.log1p(X[c])
        top_share = X[c].round(6).value_counts(normalize=True).iloc[0]
        if top_share >= 0.8:
            log.append({"feature": c, "decision": "dropped", "reason": f"near-constant: {top_share:.0%} of states share one value"})
    keep = [c for c in keep if c not in {r["feature"] for r in log}]
    X = X[keep]
    # iterative VIF on standardised data
    vif_rounds = []
    while True:
        Z = StandardScaler().fit_transform(X)
        v = pd.Series([variance_inflation_factor(Z, i) for i in range(Z.shape[1])], index=X.columns)
        vif_rounds.append(v.rename(f"round_{len(vif_rounds) + 1}"))
        if v.max() <= 10:
            break
        worst = v.idxmax()
        log.append({"feature": worst, "decision": "dropped", "reason": f"VIF {v.max():.1f} > 10 (multicollinear)"})
        X = X.drop(columns=worst)
    for c in X.columns:
        log.append({"feature": c, "decision": "kept", "reason": f"VIF {vif_rounds[-1][c]:.1f}" +
                    (" (log1p)" if CANDIDATES[c] == "log" else "")})
    return raw, X, pd.DataFrame(log), pd.concat(vif_rounds, axis=1)


def bootstrap_ari(Z, k, n=300):
    rng = np.random.default_rng(SEED)
    base = KMeans(k, n_init=50, random_state=SEED).fit_predict(Z)
    out = []
    for _ in range(n):
        idx = rng.choice(len(Z), size=len(Z), replace=True)
        lab = KMeans(k, n_init=10, random_state=SEED).fit(Z[idx]).predict(Z)
        out.append(adjusted_rand_score(base, lab))
    return float(np.mean(out))


def cluster_k(Z):
    rows = []
    for k in range(2, 9):
        km = KMeans(k, n_init=100, random_state=SEED).fit(Z)
        wd = AgglomerativeClustering(k, linkage="ward").fit_predict(Z)
        sizes = np.bincount(km.labels_)
        rows.append({"k": k, "inertia": km.inertia_, "silhouette_kmeans": silhouette_score(Z, km.labels_),
                     "davies_bouldin_kmeans": davies_bouldin_score(Z, km.labels_),
                     "calinski_harabasz_kmeans": calinski_harabasz_score(Z, km.labels_),
                     "silhouette_ward": silhouette_score(Z, wd), "davies_bouldin_ward": davies_bouldin_score(Z, wd),
                     "ari_kmeans_vs_ward": adjusted_rand_score(km.labels_, wd), "min_cluster_size": int(sizes.min()),
                     "bootstrap_ari": bootstrap_ari(Z, k)})
    return pd.DataFrame(rows)


def choose_k(ks):
    """Pre-stated rule: k in 3..6 (fewer is not a segmentation, more is not usable with 30 states), every cluster
    >= 3 states, bootstrap ARI >= 0.6; among those the highest silhouette."""
    ok = ks[(ks.k.between(3, 6)) & (ks.min_cluster_size >= 3) & (ks.bootstrap_ari >= 0.6)]
    pool = ok if len(ok) else ks[ks.k.between(3, 6)]
    return int(pool.sort_values("silhouette_kmeans", ascending=False).iloc[0].k), len(ok) > 0


def dbscan_check(Z):
    from sklearn.neighbors import NearestNeighbors
    d = np.sort(NearestNeighbors(n_neighbors=4).fit(Z).kneighbors(Z)[0][:, -1])
    rows = []
    for eps in np.quantile(d, [0.25, 0.5, 0.75, 0.9]):
        lab = DBSCAN(eps=eps, min_samples=3).fit_predict(Z)
        rows.append({"eps": eps, "clusters": len(set(lab) - {-1}), "noise_states": int((lab == -1).sum())})
    return pd.DataFrame(rows)


def weighting_comparison():
    s = spec()
    ids = reference_ids()
    rows, stab = [], []
    for ind, prof in s["industries"].items():
        res = score(Profile(ind, states=ids), with_stability=False)
        rk = res.ranking
        dims = list(res.dim_weights)
        D = rk.set_index("state_id")[[f"dim_{d}" for d in dims]]
        Dc = D.dropna()
        design = rk.set_index("state_id").score
        equal = D.mean(axis=1, skipna=True)
        pca = PCA(1).fit(StandardScaler().fit_transform(Dc))
        load = np.abs(pca.components_[0])
        w_pca = load / load.sum()
        pca_score = (D.fillna(D.mean()) * w_pca).sum(axis=1)  # only for this comparison; never shown in the app
        r = {"industry": prof["label"], "states_ranked": len(rk),
             "pc1_variance_share": float(pca.explained_variance_ratio_[0]),
             "rho_design_vs_equal": spearmanr(design, equal[design.index]).statistic,
             "rho_design_vs_pca": spearmanr(design, pca_score[design.index]).statistic}
        top_d = set(design.sort_values(ascending=False).index[:3])
        top_e = set(equal.sort_values(ascending=False).index[:3])
        top_p = set(pca_score.sort_values(ascending=False).index[:3])
        r["top3_overlap_equal"] = len(top_d & top_e)
        r["top3_overlap_pca"] = len(top_d & top_p)
        for d, w in zip(dims, w_pca):
            r[f"pca_w_{d}"] = float(w)
            r[f"design_w_{d}"] = float(res.dim_weights[d])
        rows.append(r)
        # pilot-ranking sensitivity under +-20%
        pres = score(Profile(ind), with_stability=True)
        st = pres.stability
        rng = np.random.default_rng(SEED)
        P = pres.ranking.set_index("state_id")[[f"dim_{d}" for d in dims]].to_numpy(float)
        base = np.array([pres.dim_weights[d] for d in dims])
        mask = ~np.isnan(P)
        base_tot = (np.nan_to_num(P) * base).sum(1) / (mask * base).sum(1)
        rhos, top1 = [], []
        for _ in range(500):
            w = base * rng.uniform(0.8, 1.2, len(dims))
            tot = (np.nan_to_num(P) * w).sum(1) / (mask * w).sum(1)
            rhos.append(spearmanr(base_tot, tot).statistic)
            top1.append(np.argmax(tot) == np.argmax(base_tot))
        stab.append({"industry": prof["label"], "pilot_leader": pres.ranking.state.iloc[0],
                     "leader_kept_share": float(np.mean(top1)), "mean_spearman_vs_base": float(np.mean(rhos)),
                     "min_spearman_vs_base": float(np.min(rhos)),
                     "gap_1st_2nd_points": float(pres.ranking.score.iloc[0] - pres.ranking.score.iloc[1]),
                     "states_always_same_rank": int((st.share_same_rank == 1).sum())})
    return pd.DataFrame(rows), pd.DataFrame(stab)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    raw, X, screen, vif = feature_screen()
    screen.to_csv(OUT / "feature_screen.csv", index=False)
    vif.to_csv(OUT / "vif_rounds.csv")
    Zrob = RobustScaler().fit_transform(X)
    ks_rob = cluster_k(Zrob)
    ks_rob.to_csv(OUT / "k_selection_robust_rejected.csv", index=False)
    k_rob, rob_met = choose_k(ks_rob)
    rob_sizes = np.bincount(KMeans(k_rob, n_init=100, random_state=SEED).fit_predict(Zrob)).tolist()
    Zr = X.rank(pct=True).to_numpy()  # primary: percentile ranks in [0, 1]
    Zs = StandardScaler().fit_transform(X)
    ks = cluster_k(Zr)
    ks.to_csv(OUT / "k_selection.csv", index=False)
    k, rule_met = choose_k(ks)
    km = KMeans(k, n_init=100, random_state=SEED).fit(Zr)
    wd = AgglomerativeClustering(k, linkage="ward").fit_predict(Zr)
    km_z = KMeans(k, n_init=100, random_state=SEED).fit_predict(Zs)
    labels = pd.Series(km.labels_, index=X.index, name="cluster")
    # order clusters by median per-capita income so cluster ids are stable and readable
    order = raw.loc[X.index, "per_capita_nsdp_real"].groupby(labels).median().sort_values(ascending=False).index
    remap = {old: i + 1 for i, old in enumerate(order)}
    labels = labels.map(remap)
    members = pd.DataFrame({"state_id": X.index, "state": [name_of(s) for s in X.index], "cluster": labels.values,
                            "ward_cluster": wd, "pilot": [s in PILOT_IDS for s in X.index]})
    members.to_csv(OUT / "clusters.csv", index=False)
    prof_cols = [c for c in CANDIDATES if c in raw.columns]
    prof = raw.loc[X.index, prof_cols].groupby(labels).median().T
    prof.columns = [f"cluster_{c}" for c in prof.columns]
    prof["national_median"] = raw.loc[X.index, prof_cols].median()
    prof.to_csv(OUT / "cluster_profiles.csv")
    db = dbscan_check(Zr)
    db.to_csv(OUT / "dbscan_check.csv", index=False)
    pca = PCA().fit(Zs)
    load = pd.DataFrame(pca.components_[:3].T, index=X.columns, columns=["PC1", "PC2", "PC3"])
    load.to_csv(OUT / "pca_loadings.csv")
    wc, sens = weighting_comparison()
    wc.to_csv(OUT / "weighting_comparison.csv", index=False)
    sens.to_csv(OUT / "sensitivity.csv", index=False)

    # figures
    fig, ax = plt.subplots(1, 3, figsize=(14, 3.6))
    ax[0].plot(ks.k, ks.inertia, "o-", color="#1F4FD1"); ax[0].set_title("Elbow: K-Means inertia")
    ax[1].plot(ks.k, ks.silhouette_kmeans, "o-", color="#1F4FD1", label="K-Means")
    ax[1].plot(ks.k, ks.silhouette_ward, "s--", color="#B5700B", label="Ward"); ax[1].legend(); ax[1].set_title("Silhouette (higher = better)")
    ax[2].plot(ks.k, ks.davies_bouldin_kmeans, "o-", color="#1F4FD1", label="K-Means")
    ax[2].plot(ks.k, ks.davies_bouldin_ward, "s--", color="#B5700B", label="Ward"); ax[2].legend(); ax[2].set_title("Davies-Bouldin (lower = better)")
    for a in ax:
        a.axvline(k, color="#9A3D00", lw=1, ls=":"); a.set_xlabel("k"); a.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(OUT / "k_selection.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(12, 4))
    dendrogram(linkage(Zr, "ward"), labels=[name_of(s) for s in X.index], leaf_rotation=90, ax=ax, color_threshold=None)
    ax.set_title("Ward dendrogram (percentile-rank features)"); fig.tight_layout(); fig.savefig(OUT / "dendrogram.png", dpi=150); plt.close(fig)
    P = pca.transform(Zs)[:, :2]
    fig, ax = plt.subplots(figsize=(8, 6))
    pal = ["#1F4FD1", "#B5700B", "#2A9D8F", "#7B2CBF", "#9A3D00", "#5B6472"]
    for c in sorted(labels.unique()):
        m = labels.values == c
        ax.scatter(P[m, 0], P[m, 1], s=60, color=pal[(c - 1) % len(pal)], label=f"Cluster {c}", edgecolor="white")
    for (x, y), sid in zip(P, X.index):
        ax.annotate(sid, (x, y), fontsize=8, xytext=(3, 3), textcoords="offset points",
                    fontweight="bold" if sid in PILOT_IDS else "normal")
    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]:.0%})"); ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]:.0%})")
    ax.legend(); ax.grid(alpha=.3); ax.set_title("States on the first two principal components (pilots in bold)")
    fig.tight_layout(); fig.savefig(OUT / "pca_clusters.png", dpi=150); plt.close(fig)

    summary = {"n_states": len(X), "features_kept": list(X.columns), "k": k, "selection_rule_met": rule_met,
               "chosen_row": ks[ks.k == k].iloc[0].to_dict(), "ari_kmeans_rank_vs_zscore": adjusted_rand_score(km.labels_, km_z),
               "rejected_robust_spec": {"k": k_rob, "rule_met": rob_met, "cluster_sizes": rob_sizes},
               "pca_variance": pca.explained_variance_ratio_[:5].tolist(),
               "clusters": members.groupby("cluster").state.apply(list).to_dict()}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    print(screen.to_string(index=False)); print(ks.round(3).to_string(index=False)); print(json.dumps(summary, indent=1, default=float))
    print(prof.round(2).to_string()); print(db.round(2).to_string()); print(wc.round(3).to_string()); print(sens.round(3).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
