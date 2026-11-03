"""CSV and PDF exports of a ranking run (blueprint 8.4: source links, scoring version and caveats)."""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd
from fpdf import FPDF

from scoring.data import sources_url
from ui.narrative import fmt, managerial, model_explanation, reasons
from ui.state import describe

DISCLAIMER = ("Relative suitability index (0-100) for state screening. It is NOT a probability of commercial success, "
              "profit or survival, and not financial advice. Weights are design defaults (v1), not learned optima.")


def csv_bytes(res, profile: dict) -> bytes:
    t = res.indicators.copy()
    t["source_url"] = t.source_file.map(sources_url)
    out = t[["state", "dimension", "label", "value", "unit", "period", "quality", "source_file", "source_url",
             "score", "w_ind_eff", "dim_weight", "contribution", "proxy", "note"]].rename(columns={
                 "label": "indicator", "score": "national_percentile_score", "w_ind_eff": "indicator_weight_in_dimension",
                 "dim_weight": "dimension_weight", "contribution": "contribution_to_index", "proxy": "caveat"})
    rk = res.ranking[["state", "rank", "score"]].rename(columns={"score": "suitability_index"})
    out = rk.merge(out, on="state").sort_values(["rank", "dimension", "indicator"])
    head = (f"# India Expansion Intelligence export, {dt.date.today()}\n# Profile: {describe(profile)}\n"
            f"# Scoring version: weights_{res.weights_version}.yaml\n# {DISCLAIMER}\n")
    return (head + out.to_csv(index=False)).encode("utf-8")


def _latin(s: str) -> str:
    rep = {"₹": "Rs ", "–": "-", "—": "-", "·": "|", "±": "+/-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...",
           "≥": ">=", "≤": "<=", "×": "x", "→": "->"}
    for a, b in rep.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


class _PDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", size=8)
        self.set_text_color(90, 98, 110)
        self.cell(0, 6, _latin(f"India Expansion Intelligence | weights v1 | page {self.page_no()}"), align="R")


def pdf_bytes(res, profile: dict) -> bytes:
    pdf = _PDF(format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.add_page()
    pdf.set_margins(16, 16, 16)
    W = pdf.w - 32

    def h(text, size=14):
        pdf.set_font("Helvetica", "B", size)
        pdf.set_text_color(18, 22, 28)
        pdf.multi_cell(W, size * 0.5, _latin(text))
        pdf.ln(1)

    def p(text, size=10, color=(58, 66, 80)):
        pdf.set_font("Helvetica", size=size)
        pdf.set_text_color(*color)
        pdf.multi_cell(W, 5, _latin(text))
        pdf.ln(1)

    h("State expansion brief", 18)
    p(describe(profile) + f" | {dt.date.today():%d %b %Y}")
    pdf.set_fill_color(255, 244, 219)
    pdf.set_text_color(74, 51, 0)
    pdf.set_font("Helvetica", size=9)
    pdf.multi_cell(W, 5, _latin(DISCLAIMER), fill=True)
    pdf.ln(3)
    h("Ranking")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(18, 22, 28)
    dims = list(res.dim_weights)
    cols = [("Rank", 12), ("State", 34), ("Index", 16)] + [(d[:9].title(), (W - 62) / len(dims)) for d in dims]
    for c, w in cols:
        pdf.cell(w, 7, c, border="B")
    pdf.ln()
    pdf.set_font("Helvetica", size=9)
    for r in res.ranking.itertuples():
        vals = [str(r.rank), r.state, f"{r.score:.1f}"] + [
            "n/a" if pd.isna(getattr(r, f"dim_{d}")) else f"{getattr(r, f'dim_{d}'):.0f}" for d in dims]
        for (c, w), v in zip(cols, vals):
            pdf.cell(w, 6, _latin(v))
        pdf.ln()
    p("Dimension weights: " + ", ".join(f"{d} {100 * w:.0f}%" for d, w in res.dim_weights.items()), 8)
    for n in res.notes:
        p("- " + n, 8)
    pdf.ln(2)
    h("Top three: evidence")
    for r in res.ranking.head(3).itertuples():
        pos, neg = reasons(res, r.state_id, 3)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(18, 22, 28)
        pdf.multi_cell(W, 6, _latin(f"{r.rank}. {r.state} - {r.score:.1f} / 100 | data confidence {r.data_confidence}"))
        for x in pos:
            p("+ " + x, 9)
        for x in neg:
            p("- " + x, 9, (154, 61, 0))
        if r.disclosure:
            p("Data gaps: " + r.disclosure, 8, (107, 70, 0))
    h("Could the runner-up win?")
    p(res.counter or "n/a", 9)
    h("Model explanation")
    p(model_explanation(res.industry)[0], 9)
    h("Managerial interpretation")
    p(managerial(res), 9)
    h("Sources")
    for f in sorted({x.split(";")[0] for x in res.indicators.source_file if x})[:40]:
        p(f"{f}  {sources_url(f)}", 7)
    return bytes(pdf.output())
