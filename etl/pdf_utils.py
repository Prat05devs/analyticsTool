"""Small helpers for PDF table extraction with pdfplumber, plus raw-text lookups used to verify values."""
from __future__ import annotations

import functools
import random
import re
from pathlib import Path

import pdfplumber


@functools.lru_cache(maxsize=32)
def page_text(path: str, page: int) -> str:
    with pdfplumber.open(path) as pdf:
        return pdf.pages[page - 1].extract_text() or ""


@functools.lru_cache(maxsize=64)
def full_text(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        with pdfplumber.open(p) as pdf:
            return "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    return re.sub(r"<[^>]+>", " ", p.read_text(errors="ignore"))


def find_page(path: str, pattern: str) -> int:
    """1-based page number of the first page whose text matches pattern (tables move between editions)."""
    with pdfplumber.open(path) as pdf:
        for i, pg in enumerate(pdf.pages):
            if re.search(pattern, pg.extract_text() or ""):
                return i + 1
    raise LookupError(f"{pattern!r} not found in {path}")


def num(s: str) -> float:
    s = s.replace(",", "").strip()
    return float("nan") if s in {"-", ""} else float(s)


def spot_check(rows: list[dict], k: int = 5, seed: int = 7) -> str:
    """Print k random cells next to their page numbers for a manual check against the PDF."""
    random.Random(seed).shuffle(rows := list(rows))
    lines = [f"  p{r['page']:>3}  {r['label']:<45} {r['value']}" for r in rows[:k]]
    return "Spot check (open the PDF at these pages):\n" + "\n".join(lines)


def digits_only(text: str) -> str:
    """'Rs 1,23,456.70' -> 'Rs 123456.70' so that values can be searched regardless of digit grouping."""
    return re.sub(r"(?<=\d),(?=\d)", "", text)
