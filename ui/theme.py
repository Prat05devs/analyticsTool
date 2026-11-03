"""Survey Ledger visual system for the Streamlit app (matches the design canvas).

Ink #12161C on #F5F6F8, white surfaces, one evidence accent (blue #1F4FD1), amber only for caveats.
Space Grotesk display, Inter body, IBM Plex Mono figures.
"""
from __future__ import annotations

import html

import streamlit as st

INK, MUTED, LINE, SURFACE, GROUND = "#12161C", "#4A5361", "#DCE0E6", "#FFFFFF", "#F5F6F8"
BLUE, BLUE_DARK, BLUE_SOFT = "#1F4FD1", "#163A9E", "#E8EEFC"
AMBER_TEXT, AMBER_BG, AMBER_MARK = "#6B4600", "#FFF4DB", "#B5700B"
NEG = "#9A3D00"
SEQ = ["#DCE5FB", "#9DB4F2", "#5B82EA", "#2F5FE0", "#163A9E"]  # sequential blue, light -> dark

CSS = f"""
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"], .stMarkdown, .stText, button, input, select, textarea {{ font-family: Inter, system-ui, sans-serif; }}
h1, h2, h3, .ei-display {{ font-family: 'Space Grotesk', Inter, sans-serif !important; letter-spacing: -0.02em; color: {INK}; }}
h1 {{ font-weight: 700 !important; }}
.block-container {{ max-width: 1200px; padding-top: 4.5rem; padding-bottom: 4rem; }}
.ei-eyebrow {{ font-family: 'IBM Plex Mono', monospace; font-size: 13px; letter-spacing: .06em; text-transform: uppercase; color: {MUTED}; margin: 0 0 4px; }}
.ei-lead {{ font-size: 18px; color: #3A4250; max-width: 46em; }}
.ei-card {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 14px; padding: 22px 24px; height: 100%; }}
.ei-card.lead {{ border-color: {INK}; }}
.ei-mono {{ font-family: 'IBM Plex Mono', monospace; }}
.ei-score {{ font-family: 'IBM Plex Mono', monospace; font-size: 40px; line-height: 1; }}
.ei-badge {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 13px; font-weight: 600; margin: 0 6px 6px 0; }}
.ei-b-blue {{ background: {BLUE_SOFT}; color: {BLUE_DARK}; }}
.ei-b-grey {{ background: #EEF0F3; color: #3A4250; }}
.ei-b-amber {{ background: {AMBER_BG}; color: {AMBER_TEXT}; }}
.ei-caveat {{ background: {AMBER_BG}; color: #4A3300; border-radius: 10px; padding: 12px 16px; font-size: 15px; margin: 8px 0; }}
.ei-note {{ background: #EEF0F3; color: #3A4250; border-radius: 10px; padding: 12px 16px; font-size: 15px; margin: 8px 0; }}
.ei-row {{ display: grid; grid-template-columns: 1fr auto; gap: 12px; padding: 8px 0; border-bottom: 1px solid #EEF0F3; font-size: 14px; }}
.ei-src {{ display: block; font-size: 12px; color: {MUTED}; }}
.ei-why {{ font-size: 14px; margin: 4px 0; display: flex; gap: 8px; }}
.ei-why .p {{ color: {BLUE}; font-weight: 700; }} .ei-why .n {{ color: {NEG}; font-weight: 700; }}
.ei-fc {{ background: {GROUND}; border-radius: 10px; padding: 10px 14px; margin: 12px 0; }}
.ei-stat {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px; padding: 18px 20px; height: 100%; }}
.ei-stat .v {{ font-family: 'IBM Plex Mono', monospace; font-size: 30px; }}
.ei-stat .l {{ font-size: 14px; color: #3A4250; }}
div[data-testid="stMetricValue"] {{ font-family: 'IBM Plex Mono', monospace; }}
.stButton > button, .stDownloadButton > button, .stLinkButton > a {{ min-height: 44px; border-radius: 8px; font-weight: 600; }}
.ei-footer {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid {LINE}; font-size: 13px; color: {MUTED};
             display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; }}
</style>
"""


def apply():
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape(str(x))


def eyebrow(text: str):
    st.markdown(f'<p class="ei-eyebrow">{esc(text)}</p>', unsafe_allow_html=True)


def lead(text: str):
    st.markdown(f'<p class="ei-lead">{esc(text)}</p>', unsafe_allow_html=True)


def caveat(text: str, title: str | None = None):
    t = f"<strong style='color:{INK}'>{esc(title)}</strong><br>" if title else ""
    st.markdown(f'<div class="ei-caveat" role="note">{t}{esc(text)}</div>', unsafe_allow_html=True)


def note(text: str):
    st.markdown(f'<div class="ei-note">{esc(text)}</div>', unsafe_allow_html=True)


def badge(text: str, kind: str = "grey") -> str:
    return f'<span class="ei-badge ei-b-{kind}">{esc(text)}</span>'


def stat(value: str, label: str):
    st.markdown(f'<div class="ei-stat"><div class="v">{esc(value)}</div><div class="l">{esc(label)}</div></div>',
                unsafe_allow_html=True)


def footer():
    st.markdown('<div class="ei-footer"><span>Public data only: RBI, MoSPI, TRAI, CEA, MoRTH. No business data is '
                'stored.</span><span class="ei-mono">scoring weights v3 · data refreshed 3 Nov 2026</span></div>',
                unsafe_allow_html=True)


def seq_color(score: float) -> tuple[str, str]:
    """Sequential fill for a 0-100 index and a text colour that passes contrast on it."""
    bins = [50, 55, 60, 63]
    i = sum(score >= b for b in bins)
    return SEQ[i], ("#FFFFFF" if i >= 3 else INK)
