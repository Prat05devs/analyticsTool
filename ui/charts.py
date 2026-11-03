"""Plotly charts in the Survey Ledger style (sequential blue for magnitude; blue/amber for a two-state compare)."""
from __future__ import annotations

import functools
import glob
import json
import unicodedata

import plotly.graph_objects as go

from etl.common import ROOT
from etl.states import normalize_state
from scoring.data import spec
from ui.narrative import fmt
from ui.theme import AMBER_MARK, BLUE, INK, LINE, MUTED, SEQ, SURFACE

FONT = dict(family="Inter, system-ui, sans-serif", color=INK, size=13)


def _layout(fig, h, **kw):
    fig.update_layout(height=h, margin=dict(l=8, r=8, t=8, b=8), paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
                      font=FONT, hoverlabel=dict(bgcolor=SURFACE, bordercolor=LINE, font=FONT), **kw)
    return fig


@functools.lru_cache(maxsize=1)
def geo():
    """State outlines (geoBoundaries ADM1, registered raw file), simplified for the browser, keyed by state_id."""
    from shapely.geometry import MultiPolygon, Polygon, mapping, shape
    from shapely.geometry.polygon import orient
    path = sorted(glob.glob(str(ROOT / "data/raw/geoboundaries_ind_adm1/*/geoBoundaries-IND-ADM1_simplified.geojson")))[-1]
    g = json.loads(open(path, encoding="utf-8").read())
    feats = []
    for f in g["features"]:
        name = unicodedata.normalize("NFKD", f["properties"]["shapeName"]).encode("ascii", "ignore").decode()
        sid = normalize_state(name)
        geom = shape(f["geometry"]).simplify(0.02, preserve_topology=True)
        # plotly's d3-geo wants clockwise exterior rings (the reverse of RFC 7946), else a state fills the globe
        if isinstance(geom, Polygon):
            geom = orient(geom, sign=-1.0)
        elif isinstance(geom, MultiPolygon):
            geom = MultiPolygon([orient(g, sign=-1.0) for g in geom.geoms])
        feats.append({"type": "Feature", "id": sid, "properties": {"name": name}, "geometry": mapping(geom)})
    return {"type": "FeatureCollection", "features": feats}


def india_map(res, facts: dict, height: int = 520):
    """Choropleth of the index for the compared states; other states drawn in neutral grey (no data shown)."""
    g = geo()
    rk = res.ranking.set_index("state_id")
    others = [f["id"] for f in g["features"] if f["id"] not in rk.index]
    fig = go.Figure()
    fig.add_trace(go.Choropleth(geojson=g, locations=others, z=[0] * len(others), featureidkey="id",
                                colorscale=[[0, "#E6E9EF"], [1, "#E6E9EF"]], showscale=False, hoverinfo="skip",
                                marker_line_color=SURFACE, marker_line_width=0.6))
    hover = []
    for sid, r in rk.iterrows():
        lines = [f"<b>{r.state}</b>", f"Index {r.score:.1f} / 100 · rank {int(r['rank'])}"]
        lines += [f"{lab}: {val}" for lab, val in facts.get(sid, [])]
        hover.append("<br>".join(lines))
    lo, hi = 40, 70
    fig.add_trace(go.Choropleth(
        geojson=g, locations=list(rk.index), z=list(rk.score), featureidkey="id", zmin=lo, zmax=hi,
        colorscale=[[i / (len(SEQ) - 1), c] for i, c in enumerate(SEQ)], marker_line_color=SURFACE,
        marker_line_width=1.2, text=hover, hovertemplate="%{text}<extra></extra>",
        colorbar=dict(title=dict(text="Index", font=FONT), thickness=10, len=0.55, outlinewidth=0,
                      tickfont=dict(family="IBM Plex Mono, monospace", size=11, color=MUTED))))
    fig.update_geos(visible=False, bgcolor=SURFACE, projection_type="mercator",
                    lonaxis_range=[67.5, 89.5], lataxis_range=[7.5, 31.5])
    return _layout(fig, height)


def dimension_bars(res, sid: str, height: int = 230):
    s = spec()
    r = res.ranking.set_index("state_id").loc[sid]
    dims = [d for d in res.dim_weights]
    labels = [f"{s['dimensions'][d]['label']} · {100 * res.dim_weights[d]:.0f}%" for d in dims]
    vals = [r[f"dim_{d}"] for d in dims]
    fig = go.Figure(go.Bar(x=vals, y=labels, orientation="h", marker_color=BLUE, marker_line_color=SURFACE,
                           marker_line_width=2, width=0.55,
                           text=[f"{v:.0f}" if v == v else "n/a" for v in vals], textposition="outside",
                           textfont=dict(family="IBM Plex Mono, monospace", color=INK),
                           hovertemplate="%{y}: %{x:.1f} / 100<extra></extra>", cliponaxis=False))
    fig.update_xaxes(range=[0, 108], showgrid=True, gridcolor="#EEF0F3", zeroline=False, tickfont=dict(color=MUTED))
    fig.update_yaxes(autorange="reversed", tickfont=dict(color=INK))
    return _layout(fig, height, showlegend=False, bargap=0.35)


def compare_bars(res, a: str, b: str, height: int = 320):
    s = spec()
    rk = res.ranking.set_index("state_id")
    dims = list(res.dim_weights)
    labels = [s["dimensions"][d]["label"] for d in dims]
    fig = go.Figure()
    for sid, color in [(a, BLUE), (b, AMBER_MARK)]:
        vals = [rk.loc[sid, f"dim_{d}"] for d in dims]
        fig.add_trace(go.Bar(name=rk.loc[sid, "state"], x=vals, y=labels, orientation="h", marker_color=color,
                             marker_line_color=SURFACE, marker_line_width=2,
                             text=[f"{v:.0f}" if v == v else "n/a" for v in vals], textposition="outside",
                             textfont=dict(family="IBM Plex Mono, monospace", color=INK), cliponaxis=False,
                             hovertemplate="%{fullData.name} · %{y}: %{x:.1f}<extra></extra>"))
    fig.update_xaxes(range=[0, 110], showgrid=True, gridcolor="#EEF0F3", zeroline=False, tickfont=dict(color=MUTED))
    fig.update_yaxes(autorange="reversed")
    return _layout(fig, height, barmode="group", bargap=0.3, bargroupgap=0.08,
                   legend=dict(orientation="h", y=1.08, x=0, font=FONT))


def stability_bars(stab, height: int = 260):
    lab = [f"{r.state}  (rank {r.best_rank}–{r.worst_rank})" if r.best_rank != r.worst_rank else
           f"{r.state}  (rank {r.best_rank})" for r in stab.itertuples()]
    fig = go.Figure(go.Bar(x=list(100 * stab.share_same_rank), y=lab, orientation="h", marker_color=BLUE,
                           marker_line_color=SURFACE, marker_line_width=2, width=0.55,
                           text=[f"{int(100 * v)}%" for v in stab.share_same_rank], textposition="outside",
                           textfont=dict(family="IBM Plex Mono, monospace", color=INK), cliponaxis=False,
                           hovertemplate="%{y}: same rank in %{x:.0f}% of draws<extra></extra>"))
    fig.update_xaxes(range=[0, 112], ticksuffix="%", showgrid=True, gridcolor="#EEF0F3", tickfont=dict(color=MUTED))
    fig.update_yaxes(autorange="reversed")
    return _layout(fig, height, showlegend=False)


def map_facts(res) -> dict:
    """Comparable macro indicators per state for the map hover (value + period)."""
    want = ["per_capita_nsdp_real", "per_capita_power_availability", "nh_km_per_lakh_pop", "internet_subs_per_100"]
    from scoring.data import latest
    lat = latest(want)
    s = spec()["indicators"]
    out = {}
    for r in lat.itertuples():
        out.setdefault(r.state_id, []).append((s[r.feature_code]["label"], f"{fmt(r.value, r.unit)} ({r.period})"))
    return out
