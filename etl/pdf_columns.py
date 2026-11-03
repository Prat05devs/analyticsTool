"""Column-true table extraction for PDFs whose text layer splits digit groups ('1 ,60,821').

Characters are assigned to columns by x-position, using the printed column-number row ('(1) (2) ...' or '1 2 12 13')
as anchors, and grouped into rows by their serial number. Callers must verify the result with an internal identity
(e.g. male + female = total), because a wrong column assignment would otherwise go unnoticed.
"""
from __future__ import annotations

import re

import pdfplumber


def column_rows(path: str, page_no: int, header_labels: list[str], serial_col: str = "1") -> dict[int, dict[str, str]]:
    """Return {serial: {column label: text}} for one page. `header_labels` are the printed column numbers in order."""
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[page_no - 1]
        words = page.extract_words(x_tolerance=1.5)
        chars = page.chars
    # header row: the line whose words are exactly the printed column numbers
    lines = {}
    for w in words:
        lines.setdefault(round(w["top"]), []).append(w)
    head = None
    for top, ws in sorted(lines.items()):
        txt = [w["text"] for w in sorted(ws, key=lambda w: w["x0"])]
        if txt == header_labels:
            head = (top, sorted(ws, key=lambda w: w["x0"]))
            break
    if head is None:
        raise ValueError(f"column-number row {header_labels} not found on page {page_no}")
    top0, hw = head
    centers = [((w["x0"] + w["x1"]) / 2, w["text"]) for w in hw]
    bounds = [(centers[i][0] + centers[i + 1][0]) / 2 for i in range(len(centers) - 1)]

    def col_of(x):
        for i, b in enumerate(bounds):
            if x < b:
                return centers[i][1]
        return centers[-1][1]

    # data characters below the header; rows keyed by vertical position
    body = [c for c in chars if c["top"] > top0 + 4 and re.match(r"[\d,.\-]", c["text"])]
    rows: dict[int, dict[str, list]] = {}
    for c in sorted(body, key=lambda c: (round(c["top"]), c["x0"])):
        key = round(c["top"] / 2)  # 2-pt buckets
        rows.setdefault(key, {}).setdefault(col_of((c["x0"] + c["x1"]) / 2), []).append(c)
    out = {}
    for key in sorted(rows):
        cols = {k: "".join(ch["text"] for ch in sorted(v, key=lambda ch: ch["x0"])) for k, v in rows[key].items()}
        ser = cols.get(serial_col, "")
        if ser.isdigit():
            out[int(ser)] = cols
    return out


def to_int(s: str) -> int | None:
    s = (s or "").replace(",", "").strip()
    return int(s) if s.isdigit() else None
