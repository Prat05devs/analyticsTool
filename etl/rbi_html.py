"""Parse RBI Handbook table pages (official HTML or XLSX) into a generic long format.

Each published table is split into continuation blocks ("(Contd.)", "(Concld.)"), each block a grid:
  unit / block-label rows, "State/Union Territory" + column headers (often 2 levels), state rows, footnote row.
`parse_html` and `parse_xlsx` both return rows of
  block, state_raw, header (tuple of column header labels, outermost first), value_raw
and `to_number` turns the published text into a float ('-' -> NaN, Indian digit grouping, footnote markers).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import lxml.html

NA_TOKENS = {"-", "–", "—", "..", ".", "", "NA", "N.A.", "n.a."}
STATE_HDR = re.compile(r"^(Region\s*/\s*)?States?\s*/?\s*(Union Territory|UT)|^Year$", re.I)


@dataclass
class Cell:
    block: str
    state_raw: str
    header: tuple
    value_raw: str


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def to_number(v):
    """'50,70,622' -> 5070622.0 ; '-' -> nan ; '12.4*' -> 12.4 ; '(3.2)' -> -3.2"""
    import math
    s = _clean(str(v)).replace("−", "-")
    s = re.sub(r"[*#@$†‡]+$", "", s).strip()
    if s in NA_TOKENS:
        return math.nan
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    try:
        x = float(s)
    except ValueError:
        return math.nan
    return -x if neg else x


def _expand(table) -> list[list[str]]:
    """Expand rowspan/colspan into a rectangular grid of text."""
    grid: list[list[str]] = []
    pending: dict[tuple[int, int], str] = {}
    for r, tr in enumerate(table.xpath("./tr|./thead/tr|./tbody/tr")):
        row: list[str] = []
        c = 0
        for cell in tr.xpath("./td|./th"):
            while (r, c) in pending:
                row.append(pending.pop((r, c)))
                c += 1
            txt = _clean(cell.text_content())
            cs = int(cell.get("colspan", "1") or 1)
            rs = int(cell.get("rowspan", "1") or 1)
            for k in range(cs):
                row.append(txt)
                for dr in range(1, rs):
                    pending[(r + dr, c + k)] = txt
            c += cs
        while (r, c) in pending:
            row.append(pending.pop((r, c)))
            c += 1
        grid.append(row)
    return [g for g in grid if any(g)]


def _block_label(rows_before_header: list[list[str]], title_hint: str) -> str:
    labels = []
    for row in rows_before_header:
        vals = {v for v in row if v}
        if len(vals) == 1:
            v = vals.pop()
            m = re.findall(r"\(([^()]*)\)\s*$", v)
            if v.upper().startswith("TABLE"):
                tail = re.sub(r"\((Contd|Concld)\.?\)", "", v)
                m2 = re.findall(r"\(([^()]*)\)", tail)
                labels += [x for x in m2 if not re.search(r"prices|lakh|crore|per thousand", x, re.I)]
            elif m and not re.search(r"lakh|crore|thousand|per cent|percent|number|million|mbps|as at|as on|kms?|mw|"
                                     r"units|rupees|₹|ratio|%", m[0], re.I):
                labels.append(m[0])
    return " | ".join(dict.fromkeys(labels)) or title_hint


UNIT_WORDS = re.compile(r"lakh|crore|thousand|per cent|percent|million|units|kms?\b|megawatt|kilowatt|usd|₹|rupees|number", re.I)


def _unit(rows_before_header: list[list[str]]) -> str:
    for row in rows_before_header:
        vals = {v for v in row if v}
        if len(vals) == 1:
            v = vals.pop()
            if v.startswith("(") and UNIT_WORDS.search(v):
                return v
    for row in rows_before_header:
        vals = {v for v in row if v}
        if len(vals) == 1:
            v = vals.pop()
            if v.startswith("(") and not v.upper().startswith("TABLE"):
                return v
    return ""


def _grid_cells(grid: list[list[str]]) -> tuple[list[Cell], str]:
    hdr_i = next((i for i, r in enumerate(grid) if r and STATE_HDR.match(r[0])), None)
    if hdr_i is None:
        return [], ""
    first_data = hdr_i + 1
    # header rows continue while col 0 is still the 'State/UT' label (rowspan) or row is shorter
    while first_data < len(grid) and (STATE_HDR.match(grid[first_data][0] or "") or
                                      all(to_number(v) != to_number(v) for v in grid[first_data][1:] if v)
                                      and not _looks_like_state(grid[first_data][0])):
        first_data += 1
    header_rows = grid[hdr_i:first_data]
    pre = grid[:hdr_i]
    block = _block_label(pre, "")
    unit = _unit(pre)
    ncol = max(len(r) for r in header_rows)
    headers = []
    for c in range(1, ncol):
        h = tuple(dict.fromkeys(r[c] for r in header_rows if c < len(r) and r[c] and not STATE_HDR.match(r[c])))
        headers.append(h)
    cells = []
    if grid[hdr_i][0].strip().lower() == "year":  # transposed layout (ASI tables): years down, states across
        states = [r for r in grid[hdr_i][1:]]
        for row in grid[first_data:]:
            if not row or len({v for v in row if v}) == 1 and len(row[0]) > 60:
                continue
            for c, v in enumerate(row[1:]):
                if c < len(states) and states[c]:
                    cells.append(Cell(block, states[c], (row[0],), v))
        return cells, unit
    for row in grid[first_data:]:
        name = row[0] if row else ""
        if not name or len({v for v in row if v}) == 1 and len(name) > 60:
            continue  # footnote row
        for c, v in enumerate(row[1:]):
            if c < len(headers):
                cells.append(Cell(block, name, headers[c], v))
    return cells, unit


def _looks_like_state(s: str) -> bool:
    return bool(s) and not re.match(r"^\(?\d{4}", s) and len(s) < 60


def parse_html(path: Path) -> tuple[list[Cell], str, str]:
    """Return (cells, unit, title) from an RBI PublicationsView HTML page."""
    doc = lxml.html.fromstring(Path(path).read_bytes())
    cells: list[Cell] = []
    unit = ""
    title = ""
    for t in doc.iter("table"):
        if t.xpath(".//table"):
            continue
        grid = _expand(t)
        if not title:
            title = next((r[0] for r in grid if r and r[0].upper().startswith("TABLE")), "")
        got, u = _grid_cells(grid)
        cells += got
        unit = unit or u
    if not title:
        h = doc.xpath("//*[contains(translate(text(),'table','TABLE'),'TABLE')]")
        title = next((_clean(x.text_content()) for x in h if re.match(r"^TABLE\s*\d+", _clean(x.text_content()), re.I)), "")
    return cells, unit, title


def parse_xlsx(path: Path) -> tuple[list[Cell], str, str]:
    """Same output from the XLSX edition (one or more sheets, blocks stacked vertically)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    cells: list[Cell] = []
    unit = title = ""
    for ws in wb.worksheets:
        rows = [[_clean("" if v is None else str(v)) for v in r] for r in ws.iter_rows(values_only=True)]
        # split into blocks at each 'State/Union Territory' header, carrying the rows just above it
        starts = [i for i, r in enumerate(rows) if r and STATE_HDR.match(r[0] or "")]
        for k, s in enumerate(starts):
            lo = starts[k - 1] if k else 0
            pre_lo = max(lo, s - 4)
            end = starts[k + 1] - 3 if k + 1 < len(starts) else len(rows)
            grid = [r for r in rows[pre_lo:end] if any(r)]
            # in XLSX the block label is a single text cell; mimic HTML's colspan
            grid = [[r[0]] * len(r) if sum(bool(v) for v in r) == 1 and not STATE_HDR.match(r[0]) else r for r in grid]
            got, u = _grid_cells(grid)
            cells += got
            unit = unit or u
        title = title or next((r[0] for r in rows if r and r[0].upper().startswith("TABLE")), "")
    return cells, unit, title
