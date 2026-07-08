from __future__ import annotations
import io
import re
import html as _html_mod
import time
import json
import socket
import random
import requests
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from pypdf import PdfWriter

try:
    from streamlit_searchbox import st_searchbox
    _SEARCHBOX_AVAILABLE = True
except ImportError:
    _SEARCHBOX_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────

def _get_secret(key: str, default=None):
    """Safely read a Streamlit secret, returning default if secrets aren't configured."""
    try:
        val = st.secrets.get(key, default)
        return val
    except Exception:
        return default

@st.cache_data(ttl=3600, show_spinner=False)
def locationiq_autocomplete(query: str, api_key: str) -> tuple[list[dict], str]:
    """Query LocationIQ Autocomplete API for city/country/region suggestions.

    Uses the LocationIQ /v1/autocomplete endpoint which returns place
    predictions for cities, countries, and administrative areas.

    Returns (suggestions, error_message). suggestions is a list of
    {"description": str, "place_id": str} dicts. error_message is "" on
    success, or a human-readable reason so the UI can tell the rep why
    nothing showed up instead of silently doing nothing.

    Cached per (query, api_key) for an hour — the dropdown feels slow
    mostly because it re-hits LocationIQ over the network on every
    keystroke, even for a prefix already looked up seconds earlier
    (typing, backspacing, retyping). Caching removes that repeat-call
    cost. The 3-character minimum below also cuts out the highest-volume,
    lowest-value calls (1-2 letter prefixes return the broadest, least
    useful matches anyway).
    """
    if not api_key:
        return [], "no_key"
    if not query or len(query.strip()) < 3:
        return [], ""
    try:
        resp = requests.get(
            "https://api.locationiq.com/v1/autocomplete",
            params={
                "key": api_key,
                "q": query.strip(),
                "limit": 5,
                "dedupe": 1,
                "tag": "place:city,place:country,place:state,place:region",
            },
            timeout=4,
        )
        if resp.status_code != 200:
            try:
                err = resp.json().get("error", resp.text[:200])
            except Exception:
                err = resp.text[:200]
            return [], f"HTTP {resp.status_code}: {err}"
        data = resp.json()
        suggestions = []
        for item in data:
            display = item.get("display_name", "")
            place_id = str(item.get("place_id", ""))
            if display:
                suggestions.append({"description": display, "place_id": place_id})
        return suggestions, ""
    except Exception as exc:
        return [], f"request_failed: {exc}"

def _location_searchbox_fn(searchterm: str):
    """Adapter for st_searchbox: turns LocationIQ suggestions into
    (label, value) tuples. The value half is a dict (not a bare string)
    on purpose — that's what lets the caller tell a real, clicked
    suggestion apart from text the user merely typed but never selected."""
    api_key = _get_secret("LOCATIONIQ_KEY")
    suggestions, _err = locationiq_autocomplete(searchterm, api_key)
    return [(s["description"], s) for s in suggestions]

def send_email_smtp(to_addr: str, subject: str, body: str) -> tuple[bool, str]:
    try:
        smtp_host   = _get_secret("SMTP_HOST", "smtp.gmail.com")
        smtp_port   = int(_get_secret("SMTP_PORT", 587))
        smtp_user   = _get_secret("SMTP_USER")
        smtp_pass   = _get_secret("SMTP_PASSWORD")
        if not smtp_user or not smtp_pass:
            return False, "SMTP credentials not configured. Add SMTP_USER and SMTP_PASSWORD to your secrets.toml."

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = smtp_user
        msg["To"]      = to_addr
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_addr, msg.as_string())
        return True, "Sent successfully"
    except KeyError:
        return False, "SMTP credentials not configured."
    except Exception as e:
        return False, str(e)

st.set_page_config(
    page_title="fast.site — Lead Finder",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# PROFESSIONAL LIGHT THEME CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ════════════════════════════════════════════════════════
   LIGHT THEME — fast.site Lead Finder
   Palette:
     Page bg        #F0F4FF  (cool lavender-white)
     Surface        #FFFFFF
     Surface-2      #F8FAFF
     Border         #E2E8F4
     Brand blue     #2563EB
     Brand purple   #7C3AED
     Text primary   #0F172A
     Text secondary #475569
     Text muted     #94A3B8
     Green          #059669
     Amber          #D97706
     Red            #DC2626
════════════════════════════════════════════════════════ */

/* ── Reset & Base ─────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}
.stApp {
    background: linear-gradient(160deg, #F8FAFF 0%, #F0F6FF 60%, #F5F8FF 100%) !important;
    min-height: 100vh !important;
}
header[data-testid="stHeader"] {
    background: transparent !important;
    box-shadow: none !important;
    height: 2.75rem !important;
}
header[data-testid="stHeader"] * { visibility: visible !important; }
#root > div:first-child { margin-top: 0 !important; }
.block-container {
    padding: 0 2.5rem 3rem 2.5rem !important;
    padding-top: 0.75rem !important;
    margin-top: 0 !important;
    max-width: 1180px !important;
}

/* ── Typography ───────────────────────────────────────── */
h1 {
    font-size: 1.75rem !important; font-weight: 800 !important;
    color: #0F172A !important; letter-spacing: -0.6px !important;
    margin-bottom: 0.2rem !important;
}
h2 { font-size: 1.2rem !important; font-weight: 700 !important; color: #1E293B !important; letter-spacing: -0.3px !important; }
h3 { font-size: 1rem !important; font-weight: 600 !important; color: #1E293B !important; }
h4 { font-size: 0.92rem !important; font-weight: 700 !important; color: #334155 !important;
     letter-spacing: 0.04em !important; text-transform: uppercase !important; margin-bottom: 0.6rem !important; }
p, li, label, .stMarkdown { color: #334155 !important; font-size: 0.93rem !important; line-height: 1.65 !important; }
small, .stCaption, [data-testid="stCaptionContainer"] { color: #64748B !important; font-size: 0.8rem !important; }

/* ── Inputs ───────────────────────────────────────────── */
/* Descendant selectors (not strict ">" child chains) on purpose: a
   text_input with both `key=` and `help=` set (e.g. the Query field)
   can end up one DOM level deeper than one with neither/only one of
   those props (e.g. the Categories field), because Streamlit adds an
   extra wrapper div for the key-scoped container and/or the help
   tooltip slot. A strict "> div > div > input" chain only matches the
   shallower case, so the deeper-nested field silently falls back to
   Streamlit's default (borderless-looking) input style. Matching on
   any depth, plus a data-testid fallback, makes every text/number
   input look the same regardless of which props it was given. */
.stTextInput input,
.stNumberInput input,
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    background: #FFFFFF !important;
    border: 1.5px solid #CBD5E1 !important;
    border-radius: 10px !important;
    color: #0F172A !important;
    font-size: 0.93rem !important;
    padding: 0.6rem 0.9rem !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
    box-shadow: 0 1px 3px rgba(15,23,42,0.06) !important;
}
.stTextInput input:focus,
.stNumberInput input:focus,
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus {
    border-color: #2563EB !important;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.12) !important;
    outline: none !important;
}
.stTextInput input:hover,
.stNumberInput input:hover,
[data-testid="stTextInput"] input:hover,
[data-testid="stNumberInput"] input:hover {
    border-color: #93C5FD !important;
}
.stTextInput input::placeholder,
.stNumberInput input::placeholder,
.stTextArea textarea::placeholder,
input::placeholder,
textarea::placeholder {
    color: #94A3B8 !important;
    opacity: 1 !important;
    font-weight: 400 !important;
}
.stTextInput label, .stNumberInput label, .stRadio > label {
    font-weight: 600 !important; font-size: 0.82rem !important;
    color: #475569 !important; letter-spacing: 0.02em !important;
    text-transform: uppercase !important; margin-bottom: 5px !important;
}
/* Location field (st_searchbox) — this is a custom component rendered
   inside its own iframe, so the .stTextInput rules above never reach
   its internal <input>. Border it from the outside instead, matching
   the look of the other fields, and let the focus glow apply whenever
   the iframe (or anything inside it) has focus. */
div[class*="st-key-area_query_searchbox"] {
    border: 1.5px solid #CBD5E1 !important;
    border-radius: 10px !important;
    background: #FFFFFF !important;
    box-shadow: 0 1px 3px rgba(15,23,42,0.06) !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
    overflow: hidden !important;
}
div[class*="st-key-area_query_searchbox"]:hover {
    border-color: #93C5FD !important;
}
div[class*="st-key-area_query_searchbox"]:focus-within {
    border-color: #2563EB !important;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.12) !important;
}
div[class*="st-key-area_query_searchbox"] iframe {
    border: none !important;
    display: block !important;
}
/* textarea */
.stTextArea textarea {
    background: #FFFFFF !important;
    border: 1.5px solid #CBD5E1 !important;
    border-radius: 10px !important;
    color: #0F172A !important;
    font-size: 0.9rem !important;
    box-shadow: 0 1px 3px rgba(15,23,42,0.06) !important;
}
.stTextArea textarea:focus {
    border-color: #2563EB !important;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.12) !important;
}

/* ── Buttons ──────────────────────────────────────────── */
.stButton, [data-testid="stDownloadButton"] {
    display: flex !important; align-items: stretch !important;
}
.stButton > button, [data-testid="stDownloadButton"] > button {
    width: 100% !important; min-height: 2.75rem !important;
    display: flex !important; align-items: center !important;
    justify-content: center !important; cursor: pointer !important;
    border-radius: 10px !important; font-weight: 700 !important;
    font-size: 0.92rem !important; letter-spacing: 0.01em !important;
    transition: all 0.18s cubic-bezier(0.4,0,0.2,1) !important;
}
.stButton > button p, .stButton > button span,
[data-testid="stDownloadButton"] > button p,
[data-testid="stDownloadButton"] > button span { color: inherit !important; }

/* PRIMARY — vivid blue gradient, always white text */
.stButton > button[kind="primary"],
button[data-testid="baseButton-primary"] {
    background: linear-gradient(135deg, #3B82F6 0%, #2563EB 50%, #1D4ED8 100%) !important;
    color: #FFFFFF !important; border: none !important;
    box-shadow: 0 4px 14px rgba(37,99,235,0.35), 0 1px 4px rgba(37,99,235,0.2) !important;
    text-shadow: 0 1px 2px rgba(0,0,0,0.12) !important;
}
.stButton > button[kind="primary"] p,
.stButton > button[kind="primary"] span,
button[data-testid="baseButton-primary"] p,
button[data-testid="baseButton-primary"] span { color: #FFFFFF !important; }
.stButton > button[kind="primary"]:hover,
button[data-testid="baseButton-primary"]:hover {
    background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 50%, #1E40AF 100%) !important;
    color: #FFFFFF !important;
    box-shadow: 0 8px 24px rgba(37,99,235,0.45), 0 2px 6px rgba(37,99,235,0.25) !important;
    transform: translateY(-2px) !important;
}
.stButton > button[kind="primary"]:hover p,
.stButton > button[kind="primary"]:hover span,
button[data-testid="baseButton-primary"]:hover p,
button[data-testid="baseButton-primary"]:hover span { color: #FFFFFF !important; }
.stButton > button[kind="primary"]:active,
button[data-testid="baseButton-primary"]:active {
    transform: translateY(0) !important;
    box-shadow: 0 2px 8px rgba(37,99,235,0.3) !important;
    color: #FFFFFF !important;
}
.stButton > button[kind="primary"]:disabled,
button[data-testid="baseButton-primary"]:disabled {
    background: #BFDBFE !important; color: #93C5FD !important;
    box-shadow: none !important; cursor: not-allowed !important;
}
.stButton > button[kind="primary"]:disabled p,
.stButton > button[kind="primary"]:disabled span { color: #93C5FD !important; }

/* SECONDARY — clean white card with blue border */
.stButton > button:not([kind="primary"]) {
    background: #FFFFFF !important;
    color: #2563EB !important;
    border: 1.5px solid #BFDBFE !important;
    box-shadow: 0 1px 4px rgba(37,99,235,0.08) !important;
}
.stButton > button:not([kind="primary"]) p,
.stButton > button:not([kind="primary"]) span { color: #2563EB !important; }
.stButton > button:not([kind="primary"]):hover {
    background: #EFF6FF !important;
    color: #1D4ED8 !important;
    border-color: #2563EB !important;
    box-shadow: 0 4px 16px rgba(37,99,235,0.18) !important;
    transform: translateY(-2px) !important;
}
.stButton > button:not([kind="primary"]):hover p,
.stButton > button:not([kind="primary"]):hover span { color: #1D4ED8 !important; }
.stButton > button:not([kind="primary"]):active {
    transform: translateY(0) !important;
    color: #1E40AF !important;
}
.stButton > button:not([kind="primary"]):active p,
.stButton > button:not([kind="primary"]):active span { color: #1E40AF !important; }
.stButton > button:not([kind="primary"]):disabled {
    background: #F8FAFC !important; color: #94A3B8 !important;
    border-color: #E2E8F0 !important; box-shadow: none !important;
}
.stButton > button:not([kind="primary"]):disabled p,
.stButton > button:not([kind="primary"]):disabled span { color: #94A3B8 !important; }

/* ── Single focus stroke (no blue+red double outline) ────────────────────
   Streamlit's built-in focus ring is red by default. Our own hover/active
   styles used to leave a blue box-shadow layered on top of that native red
   ring, producing a double outline plus a light-blue background wash on the
   currently-focused/active nav tab. The native red ring (it already has a
   nice transition) is now the ONLY focus indicator, on a clean background. */
.stButton > button:focus,
.stButton > button:focus-visible,
[data-testid="stDownloadButton"] > button:focus,
[data-testid="stDownloadButton"] > button:focus-visible {
    outline: none !important;
}
.stButton > button[kind="primary"]:focus,
.stButton > button[kind="primary"]:focus-visible,
button[data-testid="baseButton-primary"]:focus,
button[data-testid="baseButton-primary"]:focus-visible {
    box-shadow: 0 0 0 0.2rem rgba(255,75,75,0.45) !important;
}
.stButton > button:not([kind="primary"]):focus,
.stButton > button:not([kind="primary"]):focus-visible {
    background: #FFFFFF !important;
    border-color: #CBD5E1 !important;
    box-shadow: 0 0 0 0.2rem rgba(255,75,75,0.45) !important;
}

/* DOWNLOAD — same gradient as primary */
[data-testid="stDownloadButton"] > button {
    background: linear-gradient(135deg, #3B82F6 0%, #2563EB 50%, #1D4ED8 100%) !important;
    color: #FFFFFF !important; border: none !important;
    box-shadow: 0 4px 14px rgba(37,99,235,0.35) !important;
    text-shadow: 0 1px 2px rgba(0,0,0,0.12) !important;
}
[data-testid="stDownloadButton"] > button p,
[data-testid="stDownloadButton"] > button span { color: #FFFFFF !important; }
[data-testid="stDownloadButton"] > button:hover {
    background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%) !important;
    color: #FFFFFF !important;
    box-shadow: 0 8px 24px rgba(37,99,235,0.45) !important;
    transform: translateY(-2px) !important;
}
[data-testid="stDownloadButton"] > button:hover p,
[data-testid="stDownloadButton"] > button:hover span { color: #FFFFFF !important; }

/* ── Tooltip ──────────────────────────────────────────── */
[data-testid="stTooltipIcon"] { color: #2563EB !important; opacity: 1 !important; }
div[role="tooltip"],
[data-testid="stTooltipContent"],
[data-testid="stTooltipPopover"],
.stTooltipContent,
[data-radix-popper-content-wrapper] > div,
[data-radix-tooltip-content] {
    background: #1E293B !important;
    color: #F1F5F9 !important;
    font-size: 0.84rem !important;
    font-weight: 500 !important;
    border-radius: 8px !important;
    padding: 8px 12px !important;
    box-shadow: 0 8px 24px rgba(15,23,42,0.25) !important;
    max-width: 300px !important;
    line-height: 1.6 !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
}
div[role="tooltip"] *, [data-testid="stTooltipContent"] *,
[data-testid="stTooltipPopover"] *,
[data-radix-popper-content-wrapper] > div *,
[data-radix-tooltip-content] * {
    color: #F1F5F9 !important; background: transparent !important;
}

/* ── Layout helpers ───────────────────────────────────── */
[data-testid="column"] { display: flex !important; flex-direction: column !important; justify-content: flex-start !important; }
[data-testid="stHorizontalBlock"] { align-items: stretch !important; gap: 0.75rem !important; }

/* ── Radio Pills ──────────────────────────────────────── */
.stRadio > div { gap: 0.5rem !important; flex-direction: row !important; flex-wrap: wrap !important; }
.stRadio > div > label {
    background: #FFFFFF !important; border: 1.5px solid #CBD5E1 !important;
    border-radius: 9px !important; padding: 0.5rem 1.2rem !important;
    cursor: pointer !important;
    transition: all 0.17s !important;
    font-weight: 600 !important; font-size: 0.88rem !important; color: #475569 !important;
}
.stRadio > div > label:hover { border-color: #2563EB !important; color: #2563EB !important; background: #EFF6FF !important; }
.stRadio > div > label:has(input:checked) {
    border-color: #2563EB !important; background: #EFF6FF !important;
    color: #1D4ED8 !important; font-weight: 700 !important;
    box-shadow: 0 2px 8px rgba(37,99,235,0.15) !important;
}

/* ── Alerts ───────────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 10px !important; border-left-width: 4px !important;
    font-size: 0.9rem !important; box-shadow: 0 1px 6px rgba(15,23,42,0.06) !important;
}

/* ── Metrics ──────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: #FFFFFF !important;
    border: 1px solid #E2E8F4 !important;
    border-radius: 14px !important;
    padding: 1.1rem 1.4rem !important;
    box-shadow: 0 2px 8px rgba(37,99,235,0.06) !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.75rem !important; font-weight: 700 !important;
    color: #64748B !important; text-transform: uppercase !important; letter-spacing: 0.07em !important;
}
[data-testid="stMetricValue"] { font-size: 2.1rem !important; font-weight: 800 !important; color: #0F172A !important; }
[data-testid="stMetricDelta"] { font-size: 0.82rem !important; }

/* ── Expanders ────────────────────────────────────────── */
[data-testid="stExpander"] {
    background: #FFFFFF !important;
    border: 1px solid #E2E8F4 !important;
    border-radius: 12px !important;
    margin-bottom: 0.75rem !important;
    overflow: hidden !important;
    box-shadow: 0 2px 8px rgba(15,23,42,0.05) !important;
}
[data-testid="stExpander"] summary {
    font-weight: 600 !important; font-size: 0.93rem !important;
    color: #1E293B !important; padding: 0.9rem 1.2rem !important;
    background: #FAFBFF !important;
}
[data-testid="stExpander"] summary:hover { background: #EFF6FF !important; }

/* ── Dividers ─────────────────────────────────────────── */
hr { border: none !important; border-top: 1px solid #E2E8F4 !important; margin: 1.25rem 0 !important; }

/* ── Checkbox ─────────────────────────────────────────── */
.stCheckbox label { color: #334155 !important; font-weight: 500 !important; font-size: 0.92rem !important; }
/* Unselected checkbox: white background with a visible outline */
[data-testid="stCheckbox"] label span[data-baseweb="checkbox"] > div:first-child,
[data-testid="stCheckbox"] label div[role="checkbox"],
[data-testid="stCheckbox"] span[data-baseweb="checkbox"] div:first-child {
    background-color: #FFFFFF !important;
    border: 1.5px solid #CBD5E1 !important;
    box-shadow: none !important;
}
[data-testid="stCheckbox"] label span[data-baseweb="checkbox"] > div:first-child:hover,
[data-testid="stCheckbox"] label div[role="checkbox"]:hover {
    border-color: #2563EB !important;
}
[data-testid="stCheckbox"] input:checked ~ span[data-baseweb="checkbox"] > div:first-child,
[data-testid="stCheckbox"] label div[role="checkbox"][aria-checked="true"] {
    background-color: #2563EB !important;
    border-color: #2563EB !important;
}

/* ── Text cursor / caret visibility ──────────────────────
   Make sure the blinking typing caret is always visible in every text
   field (inputs, textareas, number inputs, and the search boxes inside
   selectboxes/multiselects). */
.stTextInput input,
.stNumberInput input,
.stTextArea textarea,
.stSelectbox input,
.stMultiSelect input,
input, textarea {
    caret-color: #0F172A !important;
}

/* ── Progress bar ─────────────────────────────────────── */
.stProgress > div > div {
    background: linear-gradient(90deg, #2563EB, #7C3AED) !important;
    border-radius: 99px !important;
}
.stProgress > div { border-radius: 99px !important; background: #E2E8F4 !important; }

/* ── Spinner ──────────────────────────────────────────── */
[data-testid="stSpinner"] p { color: #475569 !important; font-size: 0.88rem !important; }

/* ── Tech badges ──────────────────────────────────────── */
.tech-badge {
    display: inline-block; padding: 3px 10px; border-radius: 6px;
    font-size: 11px; font-weight: 700; margin: 2px 2px; letter-spacing: 0.03em;
}
.score-chip {
    display: inline-block; padding: 4px 14px; border-radius: 6px;
    font-size: 13px; font-weight: 700; margin: 0 4px;
}

/* ── Custom components ────────────────────────────────── */
.fs-tag {
    display: inline-flex; align-items: center; padding: 3px 10px;
    border-radius: 6px; font-size: 11px; font-weight: 600;
    background: #F1F5F9; color: #475569; border: 1px solid #CBD5E1;
    margin: 2px 3px 2px 0;
}
.fs-tag.cms { background: #EFF6FF; color: #1D4ED8; border-color: #BFDBFE; }

.fs-score-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(108px, 1fr));
    gap: 10px; margin-bottom: 0.5rem;
}
.fs-score-tile {
    background: #FAFBFF; border: 1.5px solid #E2E8F4; border-radius: 10px;
    padding: 0.85rem 0.6rem; text-align: center;
    box-shadow: 0 1px 4px rgba(15,23,42,0.04);
}
.fs-score-tile.highlight { border: 2px solid #2563EB; background: #EFF6FF; }
.fs-score-tile .fs-val { font-size: 1.6rem; font-weight: 800; line-height: 1; }
.fs-score-tile .fs-label {
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.07em; margin-top: 4px; color: #64748B;
}

.fs-alert-bar {
    display: flex; align-items: flex-start; gap: 12px;
    background: #FFFBEB; border: 1px solid #FDE68A;
    border-radius: 10px; padding: 14px 16px; margin-bottom: 1rem;
    font-size: 0.88rem; line-height: 1.6; color: #92400E;
}
.fs-alert-bar .fs-alert-icon { font-size: 1.1rem; flex-shrink: 0; margin-top: 1px; }

.fs-contact-card {
    background: #FAFBFF; border: 1px solid #E2E8F4; border-radius: 12px;
    padding: 1rem 1.25rem; margin-bottom: 0.75rem;
    box-shadow: 0 1px 4px rgba(15,23,42,0.04);
}
.fs-contact-card h4 {
    font-size: 0.78rem !important; font-weight: 700 !important; color: #64748B !important;
    text-transform: uppercase !important; letter-spacing: 0.07em !important; margin-bottom: 0.6rem !important;
}
.fs-contact-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
.fs-contact-item .fs-c-label { font-size: 11px; color: #94A3B8; margin-bottom: 2px; }
.fs-contact-item .fs-c-val { font-size: 0.88rem; color: #0F172A; font-weight: 600; }
.fs-contact-item .fs-c-val a { color: #2563EB; text-decoration: none; }
.fs-contact-item .fs-c-val a:hover { text-decoration: underline; color: #1D4ED8; }

/* ── App Header ───────────────────────────────────────── */
.app-header {
    display: flex; align-items: center; gap: 16px;
    margin-bottom: 1.75rem; padding: 1.4rem 2rem;
    background: linear-gradient(135deg, #1E40AF 0%, #2563EB 50%, #7C3AED 100%);
    border-radius: 0 0 16px 16px;
    position: relative; overflow: hidden;
    box-shadow: 0 4px 20px rgba(37,99,235,0.25);
}
.app-header::before {
    content: ''; position: absolute; top: -60px; right: -40px;
    width: 240px; height: 240px;
    background: radial-gradient(circle, rgba(255,255,255,0.12) 0%, transparent 70%);
    pointer-events: none;
}
.app-header-title {
    font-size: 1.35rem !important; font-weight: 800 !important;
    color: #FFFFFF !important; line-height: 1.2 !important; margin: 0 !important;
}
.app-header-sub { font-size: 0.8rem; color: rgba(255,255,255,0.75); margin: 3px 0 0 0; }
.app-header-pill {
    margin-left: auto; background: rgba(255,255,255,0.2);
    border: 1px solid rgba(255,255,255,0.35); border-radius: 99px;
    padding: 4px 14px; font-size: 0.75rem; font-weight: 600;
    color: #FFFFFF; letter-spacing: 0.03em; white-space: nowrap;
}

/* ── Section dividers ─────────────────────────────────── */
.section-label {
    display: inline-flex; align-items: center; gap: 7px;
    color: #64748B; font-size: 0.72rem; font-weight: 700;
    letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 0.35rem;
}
.section-divider {
    display: flex; align-items: center; gap: 10px;
    margin: 1.5rem 0 1rem 0;
}
.section-divider-line { flex: 1; height: 1px; background: #E2E8F4; }
.section-divider-label {
    font-size: 0.72rem; font-weight: 700; color: #475569;
    letter-spacing: 0.08em; text-transform: uppercase;
    background: #EFF6FF; padding: 3px 12px; border-radius: 99px;
    border: 1px solid #BFDBFE; color: #1D4ED8;
}

/* ── Cards ────────────────────────────────────────────── */
.result-card {
    background: #FFFFFF; border: 1px solid #E2E8F4; border-radius: 12px;
    padding: 1.1rem 1.4rem; margin-bottom: 0.6rem;
    box-shadow: 0 2px 8px rgba(15,23,42,0.05);
    transition: box-shadow 0.2s ease, border-color 0.2s ease, transform 0.15s ease;
}
.result-card:hover {
    box-shadow: 0 8px 24px rgba(37,99,235,0.12); border-color: #BFDBFE;
    transform: translateY(-2px);
}
.search-card {
    background: #FFFFFF; border: 1px solid #E2E8F4; border-radius: 14px;
    padding: 1.6rem 1.75rem; margin-bottom: 1.25rem;
    box-shadow: 0 2px 8px rgba(15,23,42,0.05);
}

/* ── Footer ───────────────────────────────────────────── */
.app-footer {
    margin-top: 3rem; padding-top: 1.25rem; border-top: 1px solid #E2E8F4;
    font-size: 0.78rem; color: #94A3B8; text-align: center; letter-spacing: 0.01em;
}

/* ── Tabs ─────────────────────────────────────────────── */
[data-testid="stTabs"] > div:first-child {
    background: #FFFFFF !important;
    border-radius: 14px 14px 0 0 !important;
    border: 1px solid #E2E8F4 !important;
    border-bottom: none !important;
    padding: 0 8px !important;
    box-shadow: 0 -1px 0 #E2E8F4 !important;
}
[data-testid="stTabs"] [role="tab"] {
    font-weight: 700 !important; font-size: 0.9rem !important;
    color: #64748B !important; padding: 0.85rem 1.5rem !important;
    border-radius: 10px 10px 0 0 !important;
    transition: all 0.18s ease !important; letter-spacing: 0.01em !important;
}
[data-testid="stTabs"] [role="tab"]:hover {
    color: #2563EB !important; background: #EFF6FF !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #1D4ED8 !important; background: #EFF6FF !important;
    border-bottom: 3px solid #2563EB !important;
}
[data-testid="stTabsContent"] {
    background: #FFFFFF !important;
    border: 1px solid #E2E8F4 !important;
    border-top: none !important;
    border-radius: 0 0 14px 14px !important;
    padding: 1.5rem 1.75rem !important;
    margin-bottom: 1.5rem !important;
    box-shadow: 0 4px 16px rgba(15,23,42,0.06) !important;
}

/* ── Sidebar ──────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1E3A8A 0%, #1E40AF 40%, #312E81 100%) !important;
    border-right: none !important;
    min-width: 260px !important; max-width: 260px !important;
    box-shadow: 4px 0 20px rgba(37,99,235,0.15) !important;
}
[data-testid="stSidebar"] > div:first-child { padding-top: 0 !important; }
[data-testid="stSidebarCollapseButton"] button {
    background: rgba(255,255,255,0.15) !important;
    color: white !important;
    border: 1px solid rgba(255,255,255,0.3) !important;
    border-radius: 6px !important;
}
[data-testid="stSidebarCollapsedControl"] button {
    background: #1E3A8A !important; color: white !important;
    border: 1px solid rgba(255,255,255,0.2) !important;
}
[data-testid="stSidebar"] * { color: rgba(255,255,255,0.9) !important; }
[data-testid="stSidebar"] .stButton > button {
    background: rgba(255,255,255,0.1) !important;
    color: #FFFFFF !important;
    border: 1px solid rgba(255,255,255,0.18) !important;
    box-shadow: none !important; border-radius: 8px !important;
    font-weight: 600 !important; font-size: 0.9rem !important;
    text-align: left !important; justify-content: flex-start !important;
    padding: 0.6rem 0.9rem !important; width: 100% !important;
    transition: all 0.15s ease !important;
}
[data-testid="stSidebar"] .stButton > button p,
[data-testid="stSidebar"] .stButton > button span { color: #FFFFFF !important; }
[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,0.22) !important;
    color: #FFFFFF !important;
    border-color: rgba(255,255,255,0.4) !important;
    transform: none !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2) !important;
}
[data-testid="stSidebar"] .stButton > button:hover p,
[data-testid="stSidebar"] .stButton > button:hover span { color: #FFFFFF !important; }
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: rgba(255,255,255,0.2) !important;
    color: #FFFFFF !important; border: 2px solid rgba(255,255,255,0.5) !important;
    font-weight: 800 !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
    background: rgba(255,255,255,0.32) !important;
    color: #FFFFFF !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover p,
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover span { color: #FFFFFF !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.15) !important; }
.sidebar-logo {
    padding: 1.25rem 0.9rem 0.5rem 0.9rem;
    border-bottom: 1px solid rgba(255,255,255,0.12);
    margin-bottom: 0.5rem;
}
.sidebar-section-label {
    font-size: 0.68rem !important; font-weight: 700 !important;
    color: rgba(255,255,255,0.45) !important; letter-spacing: 0.12em !important;
    text-transform: uppercase !important; padding: 0.8rem 0.9rem 0.3rem 0.9rem !important;
}
.sidebar-user-info {
    padding: 0.75rem 0.9rem;
    background: rgba(255,255,255,0.1);
    border-radius: 10px; margin: 0.5rem 0.5rem;
    font-size: 0.82rem; border: 1px solid rgba(255,255,255,0.15);
}
</style>
<script>
(function() {
  function tryOpenSidebar() {
    var btn = document.querySelector('[data-testid="stSidebarCollapsedControl"] button');
    if (btn) { btn.click(); return true; }
    return false;
  }
  // Try immediately and after short delays for initial load
  setTimeout(tryOpenSidebar, 300);
  setTimeout(tryOpenSidebar, 800);
  setTimeout(tryOpenSidebar, 1500);
  // Watch for sidebar being collapsed and reopen it
  var obs = new MutationObserver(function() {
    tryOpenSidebar();
  });
  document.addEventListener('DOMContentLoaded', function() {
    obs.observe(document.body, { childList: true, subtree: false });
    tryOpenSidebar();
  });
})();
</script>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# LANGUAGE SELECTION — shown once at startup, stored in session_state
# ─────────────────────────────────────────────────────────────────────────────
if "lang" not in st.session_state:
    st.markdown("""
<div style="display:flex;align-items:center;justify-content:center;min-height:58vh;flex-direction:column;gap:1.75rem;">
  <div style="text-align:center;">
    <div style="
      width:72px;height:72px;
      background:linear-gradient(135deg,#0D1526 0%,#1E3A7A 100%);
      border-radius:20px;margin:0 auto 1.25rem auto;
      display:flex;align-items:center;justify-content:center;
      font-size:32px;box-shadow:0 8px 24px rgba(37,99,235,0.35);">⚡</div>
    <div style="font-size:2.2rem;font-weight:800;color:#0F172A;margin-bottom:0.3rem;letter-spacing:-0.5px;">
      fast.site <span style="color:#3B82F6;font-weight:400;font-size:1.4rem;letter-spacing:0;">Lead Finder</span>
    </div>
    <div style="font-size:0.95rem;color:#94A3B8;margin-bottom:0.2rem;">
      Find slow websites · Extract contacts · Generate cold emails
    </div>
    <div style="display:inline-block;background:rgba(37,99,235,0.18);color:#93C5FD;border:1px solid rgba(59,130,246,0.35);
      border-radius:99px;padding:4px 16px;font-size:0.78rem;font-weight:700;letter-spacing:0.05em;
      text-transform:uppercase;margin-top:0.75rem;">Choose your language · Sprache wählen</div>
  </div>
</div>
""", unsafe_allow_html=True)

    col_l, col_mid, col_r = st.columns([2, 2, 2])
    with col_mid:
        st.markdown("<div style='height:1rem;'></div>", unsafe_allow_html=True)
        if st.button("🇬🇧  English", use_container_width=True, type="primary"):
            st.session_state["lang"] = "en"
            st.rerun()
        st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)
        if st.button("🇩🇪  Deutsch", use_container_width=True):
            st.session_state["lang"] = "de"
            st.rerun()
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# TRANSLATION HELPER
# ─────────────────────────────────────────────────────────────────────────────
_LANG: str = st.session_state.get("lang", "en")

def _t(en: str, de: str) -> str:
    return de if _LANG == "de" else en

# ─────────────────────────────────────────────────────────────────────────────
# URL VALIDATION
# ─────────────────────────────────────────────────────────────────────────────
_URL_RE = re.compile(
    r"^(?:https?://)?"           # optional scheme
    r"(?:[A-Za-z0-9-]+\.)+"     # one or more subdomain/domain labels
    r"[A-Za-z]{2,}"             # TLD (at least 2 letters)
    r"(?:[/?#][^\s]*)?"         # optional path/query/fragment
    r"$",
    re.IGNORECASE,
)

def _is_valid_url(raw: str) -> bool:
    """Return True only if raw looks like a real hostname/URL."""
    if not raw:
        return False
    # After stripping a leading scheme, there must be a dot-separated hostname
    stripped = re.sub(r"^https?://", "", raw.strip(), flags=re.I)
    if not _URL_RE.match(raw.strip()):
        return False
    # Must contain at least one dot in the host part
    host = stripped.split("/")[0].split("?")[0].split("#")[0]
    return "." in host

# ─────────────────────────────────────────────────────────────────────────────
# SEARCH — delegate entirely to search.py (no duplication)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from search import search as _search_engine
    SEARCH_AVAILABLE = True
except ImportError:
    SEARCH_AVAILABLE = False

def multi_engine_search(industry: str, area: str, max_results: int = 20, query: str = "") -> tuple[list[dict], list[str]]:
    """Delegate to search.py's search() function.

    industry = categories field, area = location field, query = free-text
    keywords — combined into one Google-style search string by search.py.
    """
    if not SEARCH_AVAILABLE:
        return [], [_t("search.py not found", "search.py nicht gefunden")]
    results, engine = _search_engine(industry, area, max_results, query=query)
    return results, [engine] if isinstance(engine, str) else engine

# ─────────────────────────────────────────────────────────────────────────────
# TECH DETECTION  — CMS signatures & plugin detection
# ─────────────────────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Edg/123.0.0.0",
]

def _headers():
    return {"User-Agent": random.choice(USER_AGENTS)}

CMS_SIGNATURES: dict[str, list[tuple[str, float]]] = {
    "WordPress": [
        (r"/wp-content/themes/", 2.0), (r"/wp-content/plugins/", 2.0),
        (r"/wp-includes/js/", 2.0), (r"/wp-json/", 1.5),
        (r"wp-embed\.min\.js", 1.5), (r'content="WordPress', 1.5),
        (r"xmlrpc\.php", 1.0), (r"/wp-content/uploads/", 1.0),
        (r"wp-block-", 0.8), (r"class=\"wp-", 0.7), (r"WordPress", 0.5),
    ],
    "Shopify": [
        (r"cdn\.shopify\.com", 2.0), (r"myshopify\.com", 2.0),
        (r"Shopify\.theme", 2.0), (r"shopify-section", 1.5),
        (r"shopify\.com/s/files/", 1.5), (r'"shopify"', 1.0),
        (r"Shopify\.shop", 1.0), (r"/collections/", 0.5),
    ],
    "Wix": [
        (r"wixstatic\.com", 2.0), (r"wix\.com/_api/", 2.0),
        (r"X-Wix-Published-Version", 2.0), (r"wix-code", 1.5),
        (r"\"wix\"", 1.0), (r"parastorage\.com", 1.0), (r"wixsite\.com", 1.5),
    ],
    "Squarespace": [
        (r"squarespace\.com", 2.0), (r"sqsp\.net", 2.0),
        (r"static1\.squarespace\.com", 2.0), (r'"squarespace"', 1.5),
        (r"Squarespace-Headers", 1.5), (r"sqs-layout", 1.0), (r"data-sqs-type", 1.0),
    ],
    "Webflow": [
        (r"webflow\.com", 2.0), (r"webflow\.io", 2.0),
        (r"data-wf-page", 2.0), (r"data-wf-site", 2.0),
        (r"webflow\.js", 1.5), (r'"webflow"', 1.0),
    ],
    "Joomla": [
        (r"/components/com_content", 2.0), (r"/components/com_", 1.5),
        (r'content="Joomla', 2.0), (r"joomla", 1.0),
        (r"/media/system/js/", 0.8), (r"Joomla!", 0.8), (r"/administrator/", 0.5),
    ],
    "Drupal": [
        (r"/sites/default/files/", 2.0), (r"Drupal\.settings", 2.0),
        (r'content="Drupal', 2.0), (r"drupal\.js", 1.5),
        (r"drupal", 0.8), (r"/misc/drupal\.js", 1.5), (r"X-Generator.*Drupal", 2.0),
    ],
    "Magento": [
        (r"Mage\.Cookies", 2.0), (r"/skin/frontend/", 2.0),
        (r"magento", 1.0), (r"var BLANK_URL", 1.0),
        (r"Magento_", 1.5), (r"/pub/static/frontend/", 1.5),
    ],
    "Ghost": [
        (r"content\.ghost\.io", 2.0), (r"ghost\.io", 1.5),
        (r'content="Ghost', 2.0), (r"ghost-theme", 1.5), (r"/ghost/api/", 2.0),
    ],
    "Next.js": [(r"_next/static/chunks/", 2.0), (r"__NEXT_DATA__", 2.0), (r"_next/image", 1.5)],
    "Nuxt.js": [(r"__nuxt", 2.0), (r"_nuxt/", 2.0), (r"nuxt-link", 1.5), (r"window\.__nuxt", 2.0)],
    "Gatsby":  [(r"gatsby-", 1.5), (r"/static/gatsby-", 2.0), (r"window\.___gatsby", 2.0)],
    "HubSpot CMS": [(r"hs-scripts\.com", 2.0), (r"hubspot\.com", 1.5), (r"hs-analytics", 1.5)],
    "Framer": [(r"framer\.com", 2.0), (r"framerusercontent\.com", 2.0)],
    "BigCommerce": [(r"bigcommerce\.com", 2.0), (r"cdn\.bigcommerce\.com", 2.0)],
}

HEADER_CMS_MAP: dict[str, str] = {
    "x-shopify-stage": "Shopify", "x-shopid": "Shopify",
    "x-wix-request-id": "Wix", "x-ghost-cache-status": "Ghost",
    "x-drupal-cache": "Drupal", "x-generator": None,
    "x-powered-by-squarespace": "Squarespace",
}

GENERATOR_MAP: dict[str, str] = {
    "wordpress": "WordPress", "joomla": "Joomla", "drupal": "Drupal",
    "ghost": "Ghost", "craft cms": "Craft CMS", "typo3": "TYPO3",
    "squarespace": "Squarespace", "webflow": "Webflow", "framer": "Framer",
    "wix": "Wix", "blogger": "Blogger", "hubspot": "HubSpot CMS",
    "bigcommerce": "BigCommerce", "prestashop": "PrestaShop",
    "opencart": "OpenCart", "magento": "Magento",
}

_INFRASTRUCTURE_LABELS: dict[str, str] = {
    "cloudflare": "Cloudflare CDN", "fastly": "Fastly CDN",
    "akamai": "Akamai CDN", "cloudfront": "AWS CloudFront",
    "bunnycdn": "BunnyCDN", "b-cdn": "BunnyCDN",
}

PLUGIN_SIGNATURES: dict[str, str] = {
    "WooCommerce": r"woocommerce", "Elementor": r"elementor",
    "Yoast SEO": r"yoast|yoast-schema", "Rank Math SEO": r"rank-math|rankmath",
    "Contact Form 7": r"wpcf7|contact-form-7", "Gravity Forms": r"gform_|gravityforms",
    "WPML": r"\bwpml\b", "Akismet": r"akismet", "Jetpack": r"jetpack",
    "WP Rocket": r"wp-rocket|wprocket", "All-in-One SEO": r"aioseo|all-in-one-seo",
    "Divi Builder": r"divi|et_pb_", "WPBakery": r"wpb_|vc_",
    "Beaver Builder": r"fl-builder|beaver-builder",
    "Google Analytics 4": r"G-[A-Z0-9]{6,}|gtag\(.*G-",
    "Google Analytics UA": r"UA-\d{5,}-\d+",
    "Google Tag Manager": r"googletagmanager\.com|GTM-[A-Z0-9]+",
    "Facebook Pixel": r"fbq\(|facebook\.net/en_US/fbevents",
    "Hotjar": r"hotjar\.com|hjid", "Clarity (Microsoft)": r"clarity\.ms|microsoft.*clarity",
    "Mixpanel": r"mixpanel\.com", "Segment": r"segment\.com|analytics\.js",
    "Intercom": r"intercom\.io|intercomcdn", "Tawk.to": r"tawk\.to",
    "Zendesk Chat": r"zendesk\.com|zopim\.com", "Crisp Chat": r"crisp\.chat",
    "Drift": r"drift\.com", "Tidio": r"tidio", "LiveChat": r"livechatinc\.com",
    "Cloudflare": r"cloudflare", "Fastly": r"fastly",
    "AWS CloudFront": r"cloudfront\.net", "Akamai": r"akamai",
    "reCAPTCHA": r"recaptcha", "hCaptcha": r"hcaptcha",
    "Bootstrap": r"bootstrap\.min\.css|bootstrap\.css|bootstrap\.min\.js",
    "Tailwind CSS": r"tailwind|tailwindcss", "jQuery": r"jquery\.min\.js|jquery-\d",
    "React": r"react\.production\.min|react-dom|__react",
    "Vue.js": r"vue\.global|vue\.esm|vue@\d|createApp\(",
    "Angular": r"angular\.min\.js|ng-version|zone\.js",
    "Alpine.js": r"alpine\.min\.js|x-data=",
    "Next.js": r"__NEXT_DATA__|_next/static",
    "Nuxt.js": r"__nuxt|_nuxt/", "Svelte": r"svelte-",
    "Stripe": r"stripe\.com/v3|js\.stripe\.com", "PayPal": r"paypal\.com/sdk",
    "HubSpot Forms": r"hsforms\.net|hbspt\.forms", "Mailchimp": r"mailchimp\.com|mc\.js",
    "Klaviyo": r"klaviyo\.com|kl-private", "ActiveCampaign": r"activecampaign\.com",
    "Cookiebot": r"cookiebot\.com", "OneTrust": r"onetrust\.com|onetrust-banner",
    "CookieYes": r"cookieyes\.com",
}

def _extract_generator_meta(soup) -> str | None:
    tag = soup.find("meta", attrs={"name": re.compile(r"^generator$", re.I)})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None

def _resolve_unknown_cms(t: dict) -> tuple[str, str | None]:
    plugins_lc = " ".join(t.get("plugins", [])).lower()
    svr_raw    = t.get("server") or ""
    svr_lc     = svr_raw.lower()
    if "next.js" in plugins_lc:   return "Next.js", "medium"
    if "nuxt.js" in plugins_lc:   return "Nuxt.js", "medium"
    if "react"   in plugins_lc:   return "Custom (React)", "low"
    if "angular" in plugins_lc:   return "Custom (Angular)", "low"
    if "vue.js"  in plugins_lc:   return "Custom (Vue)", "low"
    if "wordpress" in plugins_lc or "woocommerce" in plugins_lc: return "WordPress", "medium"
    if "shopify"    in plugins_lc: return "Shopify", "medium"
    if "wix"        in plugins_lc: return "Wix", "medium"
    if "squarespace"in plugins_lc: return "Squarespace", "medium"
    if "webflow"    in plugins_lc: return "Webflow", "medium"
    if "drupal"     in plugins_lc: return "Drupal", "medium"
    if "joomla"     in plugins_lc: return "Joomla", "medium"
    if "svelte"     in plugins_lc: return "Custom (Svelte)", "low"
    if "gatsby"     in plugins_lc: return "Gatsby", "low"
    if svr_lc:
        for infra_key, infra_label in _INFRASTRUCTURE_LABELS.items():
            if infra_key in svr_lc:
                return f"Hidden behind {infra_label}", "low"
        if "php" in svr_lc:
            return "Custom PHP site", "low"
        svr_label = svr_raw.split("/")[0].strip()[:20] or "Unknown server"
        return f"Custom site ({svr_label})", "low"
    return "Unknown", None

def detect_tech(url: str, timeout: int = 12) -> dict:
    result: dict = {
        "cms": "Unknown", "cms_confidence": None,
        "plugins": [], "frameworks": [],
        "server": None, "https": url.startswith("https"), "ip": None, "error": None,
    }
    try:
        resp     = requests.get(url, headers=_headers(), timeout=timeout, allow_redirects=True, stream=False)
        raw_html = resp.text
        html_lc  = raw_html.lower()
        hdrs     = resp.headers
        hdrs_lc  = {k.lower(): v.lower() for k, v in hdrs.items()}
        soup     = BeautifulSoup(raw_html, "lxml")

        result["server"] = (hdrs.get("Server") or hdrs.get("X-Powered-By") or hdrs.get("x-powered-by") or None)
        try:
            result["ip"] = socket.gethostbyname(urlparse(url).netloc)
        except Exception:
            pass

        cms_detected = "Unknown"
        confidence   = None

        gen = _extract_generator_meta(soup)
        if gen:
            gen_lc = gen.lower()
            for keyword, cms_name in GENERATOR_MAP.items():
                if keyword in gen_lc:
                    cms_detected = cms_name; confidence = "high"; break

        if cms_detected == "Unknown":
            for hdr_key, cms_name in HEADER_CMS_MAP.items():
                if hdr_key in hdrs_lc:
                    if cms_name:
                        cms_detected = cms_name; confidence = "high"; break
                    elif hdr_key == "x-generator":
                        val = hdrs_lc[hdr_key]
                        for keyword, cname in GENERATOR_MAP.items():
                            if keyword in val:
                                cms_detected = cname; confidence = "high"; break
                    if cms_detected != "Unknown":
                        break
            if cms_detected == "Unknown":
                xpb = hdrs_lc.get("x-powered-by", "")
                for keyword, cname in GENERATOR_MAP.items():
                    if keyword in xpb:
                        cms_detected = cname; confidence = "high"; break

        if cms_detected == "Unknown":
            best_cms = "Unknown"; best_score = 0.0
            combined = html_lc + " " + str(hdrs_lc)
            for cms_name, patterns in CMS_SIGNATURES.items():
                total = sum(w for pat, w in patterns if re.search(pat, combined, re.I))
                if total > best_score:
                    best_score = total; best_cms = cms_name
            if best_score >= 2.0:
                cms_detected = best_cms
                confidence   = "high" if best_score >= 3.0 else "medium"
            elif best_score >= 1.0:
                cms_detected = best_cms; confidence = "low"

        result["cms"]            = cms_detected
        result["cms_confidence"] = confidence
        found = [name for name, pat in PLUGIN_SIGNATURES.items() if re.search(pat, html_lc, re.I)]
        result["plugins"] = found
    except Exception as e:
        result["error"] = str(e)
    return result

# ─────────────────────────────────────────────────────────────────────────────
# AUDIT
# ─────────────────────────────────────────────────────────────────────────────
try:
    from audit import audit_website
    from audit_pdf import generate_audit_pdf
    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False
    def audit_website(url, progress_callback=None):
        try:
            start = time.time()
            r     = requests.get(url, headers=_headers(), timeout=15)
            ttfb  = round((time.time() - start) * 1000)
            soup  = BeautifulSoup(r.text, "lxml")
        except Exception:
            return {"url": url, "overall_score": 0, "breakdown": {}, "lighthouse_details": {}, "fastsite_projection": {}}
        score = 0; issues = []; strengths = []
        if url.startswith("https"):
            score += 15; strengths.append("HTTPS enabled")
        else:
            issues.append("No HTTPS")
        title = soup.find("title")
        if title and title.get_text(strip=True):
            score += 10; strengths.append("Title tag present")
        else:
            issues.append("Missing title tag")
        h1s = soup.find_all("h1")
        if len(h1s) == 1:   score += 10; strengths.append("Single H1 tag")
        elif not h1s:        issues.append("No H1 tag")
        meta = soup.find("meta", attrs={"name": re.compile("description", re.I)})
        if meta and meta.get("content", "").strip():
            score += 10; strengths.append("Meta description present")
        else:
            issues.append("No meta description")
        ttfb_score = 30 if ttfb < 500 else (20 if ttfb < 1000 else 5)
        score += ttfb_score
        if ttfb < 500: strengths.append(f"Fast TTFB: {ttfb}ms")
        else:          issues.append(f"Slow TTFB: {ttfb}ms")
        return {
            "url": url, "overall_score": min(score + 25, 100),
            "breakdown": {"seo": {"score": score, "issues": issues, "strengths": strengths, "details": {}}},
            "lighthouse_details": {}, "fastsite_projection": {},
        }

    def generate_audit_pdf(audit, lang="en"):
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph
            from reportlab.lib.styles import getSampleStyleSheet
            buf    = io.BytesIO()
            doc    = SimpleDocTemplate(buf, pagesize=A4)
            styles = getSampleStyleSheet()
            story  = [Paragraph(f"Audit: {audit.get('url')}", styles["Title"]),
                      Paragraph(f"Score: {audit.get('overall_score')}/100", styles["Normal"])]
            for cat, data in audit.get("breakdown", {}).items():
                story.append(Paragraph(f"{cat}: {data.get('score')}/100", styles["Heading2"]))
                for iss in data.get("issues", []):
                    story.append(Paragraph(f"[!] {iss}", styles["Normal"]))
            doc.build(story)
            return buf.getvalue()
        except Exception:
            return b"%PDF-placeholder"

# ─────────────────────────────────────────────────────────────────────────────
# CHECKED-COMPANIES HISTORY
# ─────────────────────────────────────────────────────────────────────────────
def _history_business_name(url: str) -> str:
    """Look up a business name for `url` from the current search results,
    falling back to the bare domain if nothing is found."""
    for item in st.session_state.get("results", []):
        if item.get("source_url") == url and item.get("business_name"):
            return item["business_name"]
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1) if m else url


def _record_history(url: str, audit: dict, name: str | None = None) -> None:
    """Add or update this site's entry in the persistent 'checked companies'
    history (survives re-checks, tab switches, and reruns for this session)."""
    if not url or not audit:
        return
    history  = st.session_state.setdefault("history", {})
    existing = history.get(url, {})
    bd       = audit.get("breakdown", {}) or {}
    now      = datetime.now().strftime("%Y-%m-%d %H:%M")

    history[url] = {
        "business_name": name or existing.get("business_name") or _history_business_name(url),
        "url":           url,
        "speed_score":   (bd.get("speed") or {}).get("score", 0),
        "overall_score": audit.get("overall_score", 0),
        "audit":         audit,
        "first_checked": existing.get("first_checked", now),
        "last_checked":  now,
        "check_count":   existing.get("check_count", 0) + 1,
    }

# ─────────────────────────────────────────────────────────────────────────────
# LIVE PREVIEW TRACKING  (record / unpreview / list active)
# ─────────────────────────────────────────────────────────────────────────────
_PREVIEW_TTL_SECONDS = 3600  # fast.site edge previews are shown as live for 1 hour


def _record_preview(url: str, result, name: str | None = None) -> None:
    """Track a live fast.site edge preview so it shows up next to this site
    in the History view with a link valid for one hour."""
    preview_url = getattr(result, "preview_url", "") if result is not None else ""
    if not url or not preview_url:
        return
    previews = st.session_state.setdefault("previews", {})
    now = datetime.now()
    ok = bool(getattr(result, "ok", False))
    # PageSpeed scores are only meaningful when the measurement actually
    # completed (status == "done"); on error/timeout, origin/preview are
    # just default-constructed zeros, so store None rather than a fake 0.
    previews[url] = {
        "url":           url,
        "business_name": name or _history_business_name(url),
        "preview_url":   preview_url,
        "created_at":    now.isoformat(),
        "expires_at":    (now + timedelta(seconds=_PREVIEW_TTL_SECONDS)).isoformat(),
        "ok":            ok,
        "inconclusive":  bool(getattr(result, "inconclusive", False)) if ok else False,
        "perf_origin":   getattr(result, "perf_score_origin", None) if ok else None,
        "perf_preview":  getattr(result, "perf_score_preview", None) if ok else None,
    }


def _remove_preview(url: str) -> None:
    """'Unpreview' a site — stop tracking/showing its preview in this app.
    Note: the fast.site edge preview itself simply expires on its own after
    its 1-hour TTL; this just forgets it locally so it drops off the list."""
    st.session_state.get("previews", {}).pop(url, None)
    _safe_key = url.replace("https://", "").replace("http://", "").replace("/", "_").strip("_")
    st.session_state.pop(f"preview_result_{_safe_key}", None)


def _active_previews() -> list[dict]:
    """Return tracked previews that are still within their 1-hour window,
    quietly dropping any that have expired."""
    previews = st.session_state.get("previews", {})
    now      = datetime.now()
    alive    = {}
    for u, p in previews.items():
        try:
            if datetime.fromisoformat(p["expires_at"]) > now:
                alive[u] = p
        except Exception:
            continue
    if len(alive) != len(previews):
        st.session_state["previews"] = alive
    return sorted(alive.values(), key=lambda p: p.get("created_at", ""), reverse=True)


def _preview_one_liner(preview: dict | None) -> str:
    """A single, score-free sentence describing what a live preview improved —
    used as a compact caption next to the preview link in History."""
    if not preview:
        return ""
    if preview.get("ok") is False:
        return _t("Preview link still live", "Vorschau-Link weiterhin aktiv")
    if preview.get("inconclusive"):
        return _t("Live preview ready — timing comparison inconclusive",
                   "Live-Vorschau bereit — Zeitvergleich nicht eindeutig")
    perf_origin  = preview.get("perf_origin")
    perf_preview = preview.get("perf_preview")
    if perf_origin is not None and perf_preview is not None:
        return _t(f"PageSpeed {perf_origin} → {perf_preview}",
                   f"PageSpeed {perf_origin} → {perf_preview}")
    return _t("Live preview ready", "Live-Vorschau bereit")

# ─── Lead generation tools ────────────────────────────────────────────────────
try:
    from lead_tools import (
        opportunity_score,
        opportunity_label,
        generate_cold_email,
        build_leads_csv,
    )
    LEAD_TOOLS_AVAILABLE = True
except ImportError:
    LEAD_TOOLS_AVAILABLE = False
    def opportunity_score(audit): return 0
    def opportunity_label(score): return ("—", "#888")
    def generate_cold_email(**kw): return "lead_tools.py not found"
    def build_leads_csv(*a, **kw): return b""

def _add_contacted_column(csv_bytes: bytes, contacted_map: dict) -> bytes:
    """Append 'Contacted' / 'Contacted At' columns to an exported leads CSV,
    matched against whichever column holds the site URL."""
    if not csv_bytes or not contacted_map:
        return csv_bytes
    try:
        df = pd.read_csv(io.BytesIO(csv_bytes))
        url_col = next((c for c in df.columns if "url" in c.lower()), None)
        if not url_col:
            return csv_bytes
        df["Contacted"]    = df[url_col].apply(lambda u: "Yes" if u in contacted_map else "No")
        df["Contacted At"] = df[url_col].apply(lambda u: contacted_map.get(u, {}).get("at", ""))
        return df.to_csv(index=False).encode("utf-8")
    except Exception:
        return csv_bytes

try:
    from contact_extractor import extract_contact_info, detect_cdn
    CONTACT_AVAILABLE = True
except ImportError:
    CONTACT_AVAILABLE = False
    def extract_contact_info(url): return {"emails": [], "phones": [], "contact_page": None, "primary_email": None}
    def detect_cdn(url): return {"has_cdn": False, "cdn_name": None, "is_hot_lead": True}

# ─── Preview Measurement API ──────────────────────────────────────────────────
try:
    from preview_api import run_preview_measurement, render_preview_results, get_preview_api_key
    PREVIEW_API_AVAILABLE = True
except ImportError:
    PREVIEW_API_AVAILABLE = False
    def get_preview_api_key(): return None

# ─────────────────────────────────────────────────────────────────────────────
# UI HELPERS
# ─────────────────────────────────────────────────────────────────────────────
_CMS_COLORS: dict[str, tuple[str, str]] = {
    "WordPress": ("#21759B", "#21759B18"), "Shopify": ("#5E8E3E", "#96BF4818"),
    "Wix": ("#B07D00", "#FAAD1418"), "Squarespace": ("#333333", "#33333318"),
    "Webflow": ("#2D3AC0", "#4353FF18"), "Joomla": ("#C03D1E", "#F44E2718"),
    "Drupal": ("#0678BE", "#0678BE18"), "Magento": ("#C24E12", "#EE672218"),
    "Ghost": ("#738A94", "#738A9418"), "PrestaShop": ("#DF0067", "#DF006718"),
    "Next.js": ("#000000", "#00000015"), "Nuxt.js": ("#00C58E", "#00C58E18"),
    "Gatsby": ("#663399", "#66339918"), "HubSpot CMS": ("#FF7A59", "#FF7A5918"),
    "Framer": ("#0099FF", "#0099FF18"), "BigCommerce": ("#34313F", "#34313F18"),
    "Unknown": ("#888888", "#88888815"),
}

def _cms_badge(cms: str, confidence: str | None = None) -> str:
    fg, bg = _CMS_COLORS.get(cms, ("#888888", "#88888815"))
    conf_icon = {"high": " ✓", "medium": " ~", "low": " "}.get(confidence or "", "")
    return (
        f'<span class="fs-tag cms" style="background:{bg};color:{fg};'
        f'border:1px solid {fg}55;font-weight:700;">{cms}{conf_icon}</span>'
    )

def _score_color(s):
    return "#2E7D32" if s >= 75 else ("#F57F17" if s >= 50 else "#C62828")

def _render_tech_badges(t: dict) -> str:
    cms  = t.get("cms", "Unknown")
    conf = t.get("cms_confidence")
    if cms == "Unknown":
        cms, conf = _resolve_unknown_cms(t)
    if cms == "Unknown":
        cms_html = '<span class="fs-tag">CMS not detected</span>'
    else:
        cms_html = _cms_badge(cms, conf)
    plug_html = " ".join(
        f'<span class="fs-tag cms">{p}</span>'
        for p in t.get("plugins", [])[:8]
    )
    svr_txt = t.get("server", "")
    svr = (
        f'<span class="fs-tag">🖥 {svr_txt[:30]}</span>'
        if svr_txt else ""
    )
    err_txt = t.get("error", "")
    err = (
        f'<span class="tech-badge" style="background:#ff000015;color:#c00;border:1px solid #ff000044;">⚠ {err_txt[:40]}</span>'
        if err_txt else ""
    )
    return cms_html + " " + plug_html + " " + svr + " " + err

# ─────────────────────────────────────────────────────────────────────────────
# REP LOGIN / IDENTITY GATE
# ─────────────────────────────────────────────────────────────────────────────
# Minimal access control: one or more shared team passwords, so anyone using
# the tool is identified and every email/PDF/CSV is branded with their name.
#
# secrets.toml can define passwords in either (or both) of these forms:
#
#   TEAM_PASSWORD = "single-shared-password"
#
#   [TEAM_PASSWORDS]
#   alex  = "alex-password"
#   jamie = "jamie-password"
#
# Any password that matches a value in either form is accepted.
_TEAM_PASSWORD  = _get_secret("TEAM_PASSWORD")
_TEAM_PASSWORDS_RAW = _get_secret("TEAM_PASSWORDS", {})
try:
    _TEAM_PASSWORDS = dict(_TEAM_PASSWORDS_RAW)
except Exception:
    _TEAM_PASSWORDS = {}

_VALID_PASSWORDS = set(_TEAM_PASSWORDS.values())
if _TEAM_PASSWORD:
    _VALID_PASSWORDS.add(_TEAM_PASSWORD)
_PASSWORD_REQUIRED = bool(_VALID_PASSWORDS)

if "_authenticated" not in st.session_state:
    st.session_state["_authenticated"] = not _PASSWORD_REQUIRED
if "rep_name" not in st.session_state:
    st.session_state["rep_name"] = ""

if not st.session_state["_authenticated"] or not st.session_state["rep_name"]:
    st.markdown(f"""
<div style="max-width:420px;margin:6rem auto 1rem auto;text-align:center;">
  <div style="font-size:2.2rem;">⚡</div>
  <h1 style="margin-bottom:0;">fast.site — Lead Finder</h1>
  <p style="color:#94A3B8;font-size:0.9rem;">{_t('Sign in to continue', 'Anmelden, um fortzufahren')}</p>
</div>
""", unsafe_allow_html=True)
    _form_col1, _form_col2, _form_col3 = st.columns([1, 1.4, 1])
    with _form_col2:
        with st.form("rep_login_form"):
            _rep_name_input = st.text_input(
                _t("Your name", "Ihr Name"),
                value=st.session_state.get("rep_name", ""),
                placeholder=_t("e.g. Alex Carter", "z. B. Alex Carter"),
            )
            _pwd_input = ""
            if _PASSWORD_REQUIRED:
                _pwd_input = st.text_input(_t("Team password", "Team-Passwort"), type="password")
            _submitted = st.form_submit_button(_t("Continue", "Weiter"), use_container_width=True, type="primary")
        if _submitted:
            if not _rep_name_input.strip():
                st.error(_t("Please enter your name.", "Bitte geben Sie Ihren Namen ein."))
            elif _PASSWORD_REQUIRED and _pwd_input not in _VALID_PASSWORDS:
                st.error(_t("Incorrect team password.", "Falsches Team-Passwort."))
            else:
                st.session_state["rep_name"]       = _rep_name_input.strip()
                st.session_state["_authenticated"] = True
                st.rerun()

    st.stop()

# ═════════════════════════════════════════════════════════════════════════════
# SINGLE-PAGE UI  (rebuilt)
# ─────────────────────────────────────────────────────────────────────────────
# ONE navigation system (persistent left sidebar) + ONE working canvas.
# ONE source of truth for data (never cleared on navigation) so results follow
# you between views. ONE unified "Opportunity" score with an expandable "why".
# Consistent red/amber/green severity. A real sortable results table instead of
# stacked cards. Responsive layout that reflows instead of overlapping.
# ═════════════════════════════════════════════════════════════════════════════

# ── Single source of truth: initialise once, NEVER cleared on navigation ──────
for _k, _default in [
    ("results", []), ("audits", {}), ("cdn_map", {}), ("tech", {}),
    ("contacts", {}), ("contacted", {}), ("history", {}), ("previews", {}),
    ("engines", []),
]:
    st.session_state.setdefault(_k, _default)

st.session_state.setdefault("view", "leads")          # leads | history | exports | settings
st.session_state.setdefault("search_mode", "search")  # search | direct
st.session_state.setdefault("detail_url", None)        # currently-open detail row

# ── Score glossary: one-line plain-English definition per metric ──────────────
def _score_defs() -> dict:
    return {
        "opportunity": _t(
            "How good a fast.site prospect this is. HIGHER = better lead (slow site / no CDN). Sort by this.",
            "Wie gut dieser fast.site-Interessent ist. HÖHER = besserer Lead (langsame Seite / kein CDN). Danach sortieren.",
        ),
        "speed": _t(
            "Server response & load speed (TTFB). HIGHER = faster site. A low speed is what makes a lead 'hot'.",
            "Serverantwort & Ladegeschwindigkeit (TTFB). HÖHER = schnellere Seite. Niedrig = heißer Lead.",
        ),
        "performance": _t(
            "Google PageSpeed / Core Web Vitals. HIGHER = better real-world experience.",
            "Google PageSpeed / Core Web Vitals. HÖHER = bessere reale Nutzererfahrung.",
        ),
        "overall": _t(
            "Weighted health of the whole site (SEO, speed, mobile, security…). HIGHER = healthier.",
            "Gewichtete Gesamtgesundheit der Seite (SEO, Speed, Mobil, Sicherheit…). HÖHER = gesünder.",
        ),
    }

# ── Traffic light: strictly one score → one colour (red = hottest lead) ───────
def _traffic_light(opp: int | None) -> tuple[str, str, str, str]:
    """Return (emoji, short_label, hex, one_line_meaning) for an opportunity score."""
    if opp is None:
        return ("⚪", _t("Not checked", "Nicht geprüft"), "#94A3B8",
                _t("Run a speed check to score this lead.", "Speed-Check ausführen, um zu bewerten."))
    if opp >= 65:
        return ("🔴", _t("Hot", "Heiß"), "#DC2626",
                _t("Slow site / weak CDN — strong prospect.", "Langsame Seite / schwaches CDN — starker Interessent."))
    if opp >= 42:
        return ("🟠", _t("Warm", "Warm"), "#D97706",
                _t("Some upside — worth a pitch.", "Etwas Potenzial — ein Pitch lohnt sich."))
    return ("🟢", _t("Cold", "Kalt"), "#059669",
            _t("Already fairly fast — low priority.", "Bereits recht schnell — niedrige Priorität."))

def _biz_name(url: str) -> str:
    return _history_business_name(url)

def _domain(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1) if m else (url or "")

def _audit_scores(url: str) -> dict:
    """Derive the display numbers for a URL from stored audit + cdn data."""
    a = st.session_state["audits"].get(url)
    if not a:
        return {"state": "none", "opp": None, "speed": None, "perf": None, "overall": None}
    if a.get("error"):
        return {"state": "error", "opp": None, "speed": None, "perf": None,
                "overall": None, "error": a.get("error")}
    bd = a.get("breakdown", {}) or {}
    return {
        "state":   "ok",
        "opp":     opportunity_score(a, cdn_info=st.session_state["cdn_map"].get(url, {})),
        "speed":   (bd.get("speed") or {}).get("score", 0),
        "perf":    (bd.get("performance") or {}).get("score", 0),
        "overall": a.get("overall_score", 0),
    }

def _run_audits(urls: list[str], label_ph, prog) -> None:
    """Audit each URL in place: store audit (+ business_name), CDN, and sync
    History — the single write path so every view sees the same data."""
    total = len(urls) or 1
    for i, url in enumerate(urls):
        if not url:
            continue
        label_ph.caption(f"⚡ {_t('Checking', 'Prüfe')} {_domain(url)} …")
        result = audit_website(url)
        result["business_name"] = _biz_name(url)
        st.session_state["audits"][url]  = result
        try:
            st.session_state["cdn_map"][url] = detect_cdn(url)
        except Exception:
            st.session_state["cdn_map"].setdefault(url, {"has_cdn": False})
        if not result.get("error"):
            _record_history(url, result, name=result["business_name"])
        prog.progress((i + 1) / total)


# ═════════════════════════════════════════════════════════════════════════════
# GLOBAL CSS  (responsive; no fixed widths; reflows instead of overlapping)
# ═════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
/* Let the main container breathe and never overflow horizontally */
.block-container { max-width: 1280px; padding-top: 1.2rem; }
* { box-sizing: border-box; }

/* App header — flex that WRAPS gracefully on narrow widths */
.fs-header {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  background: linear-gradient(135deg,#2563EB 0%,#1E40AF 100%);
  color: #fff; padding: 16px 20px; border-radius: 14px; margin-bottom: 1rem;
  box-shadow: 0 6px 24px rgba(37,99,235,0.20);
}
.fs-header .fs-logo { font-size: 1.7rem; line-height: 1; }
.fs-header .fs-title { font-size: 1.25rem; font-weight: 800; }
.fs-header .fs-sub { font-size: 0.8rem; color: rgba(255,255,255,0.78); }
.fs-header .fs-user {
  margin-left: auto; background: rgba(255,255,255,0.14);
  border: 1px solid rgba(255,255,255,0.22); border-radius: 99px;
  padding: 4px 13px; font-size: 0.75rem; font-weight: 600; white-space: nowrap;
}
@media (max-width: 620px) {
  .fs-header .fs-user { margin-left: 0; }
  .fs-header .fs-title { font-size: 1.05rem; }
}

/* Verdict card in the detail drawer */
.fs-verdict {
  display:flex; align-items:center; gap:16px; flex-wrap:wrap;
  border-radius:14px; padding:16px 20px; margin:2px 0 14px 0;
  border:1px solid #E2E8F4; background:#FFFFFF;
}
.fs-verdict .num { font-size:2.4rem; font-weight:800; line-height:1; }
.fs-verdict .meta { display:flex; flex-direction:column; gap:2px; }
.fs-verdict .badge {
  font-size:0.78rem; font-weight:800; padding:3px 10px; border-radius:99px;
  color:#fff; width:max-content;
}

/* Tech tag chips (only shown behind the Details expander) */
.fs-tag {
  display:inline-block; font-size:0.72rem; font-weight:600; padding:3px 9px;
  border-radius:7px; background:#F1F5F9; color:#475569; margin:2px 3px 2px 0;
}
.fs-tag.cms { font-weight:700; }

/* Sidebar nav labels */
.sidebar-section-label {
  font-size:0.68rem; font-weight:700; text-transform:uppercase;
  letter-spacing:0.08em; color:rgba(255,255,255,0.42);
  margin:0.4rem 0 0.2rem 0.2rem;
}
</style>
""", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
# PERSISTENT LEFT NAV  (the ONE navigation system)
# ═════════════════════════════════════════════════════════════════════════════
_VIEWS = [
    ("leads",    "🔍", _t("Leads",    "Leads")),
    ("history",  "🕘", _t("History",  "Verlauf")),
    ("exports",  "📤", _t("Exports",  "Export")),
    ("settings", "⚙️", _t("Settings", "Einstellungen")),
]

with st.sidebar:
    st.markdown("""
<div style="display:flex;align-items:center;gap:10px;padding:0.2rem 0.2rem 0.8rem;">
  <div style="width:36px;height:36px;background:linear-gradient(135deg,#2563EB,#1D4ED8);
    border-radius:9px;display:flex;align-items:center;justify-content:center;
    font-size:18px;box-shadow:0 3px 10px rgba(37,99,235,0.4);">⚡</div>
  <div>
    <div style="font-size:1.05rem;font-weight:800;color:#fff;line-height:1.1;">fast.site</div>
    <div style="font-size:0.72rem;color:rgba(255,255,255,0.45);">Lead Finder</div>
  </div>
</div>
""", unsafe_allow_html=True)

    for _vk, _icon, _vlabel in _VIEWS:
        if st.button(f"{_icon}  {_vlabel}", key=f"nav_{_vk}", use_container_width=True,
                     type="primary" if st.session_state["view"] == _vk else "secondary"):
            st.session_state["view"] = _vk
            st.session_state["detail_url"] = None
            st.rerun()

    st.markdown("---")
    st.markdown(f"""
<div style="padding:0.1rem 0.3rem;">
  <div style="font-size:0.68rem;color:rgba(255,255,255,0.4);font-weight:700;
    text-transform:uppercase;letter-spacing:0.06em;">{_t('Signed in as','Angemeldet als')}</div>
  <div style="font-size:0.9rem;font-weight:700;color:#fff;">👤 {st.session_state.get('rep_name','')}</div>
</div>
""", unsafe_allow_html=True)

    _other_lang = "🇩🇪  Deutsch" if _LANG == "en" else "🇬🇧  English"
    if st.button(_other_lang, key="lang_switch_sb", use_container_width=True):
        st.session_state["lang"] = "de" if _LANG == "en" else "en"
        st.rerun()
    if st.button(f"🚪  {_t('Log out','Abmelden')}", key="logout_sb", use_container_width=True):
        for k in list(st.session_state.keys()):
            st.session_state.pop(k, None)
        st.rerun()


# ── App header (responsive, wraps cleanly) ────────────────────────────────────
st.markdown(f"""
<div class="fs-header">
  <div class="fs-logo">⚡</div>
  <div>
    <div class="fs-title">fast.site — Lead Finder</div>
    <div class="fs-sub">{_t('Find slow websites · Extract contacts · Cold emails · Export leads',
                            'Langsame Websites finden · Kontakte · Kalt-E-Mails · Leads exportieren')}</div>
  </div>
  <div class="fs-user">👤 {st.session_state.get('rep_name','—')}</div>
</div>
""", unsafe_allow_html=True)

_view = st.session_state["view"]
DEFS = _score_defs()


# ═════════════════════════════════════════════════════════════════════════════
# DETAIL DRAWER  (rendered inline below the table for the selected lead)
# ═════════════════════════════════════════════════════════════════════════════
def _render_detail(url: str) -> None:
    a = st.session_state["audits"].get(url)
    name = _biz_name(url)
    sc = _audit_scores(url)

    st.markdown("---")
    top1, top2 = st.columns([6, 1])
    with top1:
        st.markdown(f"### {name}")
        st.caption(url)
    with top2:
        if st.button(_t("✕ Close", "✕ Schließen"), key="detail_close", use_container_width=True):
            st.session_state["detail_url"] = None
            st.rerun()

    if sc["state"] == "none":
        st.info(_t("This lead hasn't been speed-checked yet — use “Run speed checks”.",
                   "Dieser Lead wurde noch nicht geprüft — „Speed-Checks ausführen“."))
        return
    if sc["state"] == "error":
        st.error(f"⚠️ {sc.get('error','')}")
        return

    # ── Verdict: ONE primary number + traffic-light badge + plain meaning ─────
    emoji, tl_label, tl_hex, tl_mean = _traffic_light(sc["opp"])
    st.markdown(f"""
<div class="fs-verdict">
  <div class="num" style="color:{tl_hex};">{sc['opp']}</div>
  <div class="meta">
    <span class="badge" style="background:{tl_hex};">{emoji} {tl_label} {_t('lead','Lead')}</span>
    <span style="font-size:0.82rem;color:#475569;">{tl_mean}</span>
    <span style="font-size:0.72rem;color:#94A3B8;">{_t('Opportunity','Chance')} · {DEFS['opportunity']}</span>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Secondary scores, each with a one-line definition ─────────────────────
    m1, m2, m3 = st.columns(3)
    m1.metric(_t("Speed", "Speed"), f"{sc['speed']}/100", help=DEFS["speed"])
    m2.metric(_t("Performance", "Performance"), f"{sc['perf']}/100", help=DEFS["performance"])
    m3.metric(_t("Overall health", "Gesamt"), f"{sc['overall']}/100", help=DEFS["overall"])

    # ── Technical detail — hidden by default ─────────────────────────────────
    with st.expander(_t("🔧 Technical detail (tech stack, CDN, sub-scores)",
                        "🔧 Technische Details (Tech-Stack, CDN, Teilwerte)")):
        t = st.session_state["tech"].get(url)
        if t:
            st.markdown(_render_tech_badges(t), unsafe_allow_html=True)
        cdn = st.session_state["cdn_map"].get(url, {})
        st.caption(f"CDN: {'✅ ' + (cdn.get('cdn_name') or 'yes') if cdn.get('has_cdn') else '❌ ' + _t('none detected','keins erkannt')}")
        bd = (a or {}).get("breakdown", {}) or {}
        if bd:
            sub = pd.DataFrame(
                [{"Category": k.replace('_', ' ').title(), "Score": (v or {}).get("score", 0)}
                 for k, v in bd.items()]
            )
            st.dataframe(sub, hide_index=True, use_container_width=True)

    # ── Contact + outreach ───────────────────────────────────────────────────
    c = st.session_state["contacts"].get(url)
    cc1, cc2 = st.columns([1, 1])
    with cc1:
        if st.button(_t("📇 Extract contact info", "📇 Kontakt extrahieren"),
                     key="detail_contact", use_container_width=True):
            with st.spinner(_t("Scanning site for email & phone…", "Suche nach E-Mail & Telefon…")):
                st.session_state["contacts"][url] = extract_contact_info(url)
            st.rerun()
    if c:
        email = c.get("primary_email") or (c.get("emails") or [None])[0]
        phone = (c.get("phones") or [None])[0]
        st.markdown(
            f"**📧 {email or _t('no email found','keine E-Mail')}**  \n"
            f"📞 {phone or '—'}   ·   🔗 {c.get('contact_page') or '—'}"
        )

    # ── Cold email ───────────────────────────────────────────────────────────
    with st.expander(_t("✉️ Cold email", "✉️ Kalt-E-Mail"), expanded=False):
        cdn = st.session_state["cdn_map"].get(url, {})
        proj = (a or {}).get("fastsite_projection", {}) or {}
        cur = proj.get("current", {}) or {}
        email_text = generate_cold_email(
            business_name=name, url=url,
            overall_score=sc["overall"], speed_score=sc["speed"],
            performance_score=sc["perf"], opportunity_score=sc["opp"],
            primary_email=(c or {}).get("primary_email"),
            ttfb_ms=cur.get("ttfb_ms"), lcp_ms=cur.get("lcp_ms"),
            has_cdn=cdn.get("has_cdn", False),
        )
        # split subject / body
        subject_line = f"{_domain(url)} speed audit — {sc['overall']}/100"
        body = email_text
        if email_text.startswith("Subject:"):
            first_nl = email_text.find("\n")
            subject_line = email_text[len("Subject:"):first_nl].strip()
            body = email_text[first_nl:].lstrip("\n")
        rep = st.session_state.get("rep_name", "").strip()
        body = body.replace("[Your name]", rep or "[Your name]")
        edited = st.text_area(_t("Body", "Text"), value=body, height=240, key="detail_email_body")
        recipient = st.text_input(_t("Send to", "Senden an"),
                                  value=(c or {}).get("primary_email", "") or "",
                                  key="detail_email_to")
        sccol1, sccol2 = st.columns([1, 1])
        with sccol1:
            if st.button(_t("📤 Send email", "📤 E-Mail senden"), key="detail_send",
                         type="primary", use_container_width=True, disabled=not recipient):
                ok, msg = send_email_smtp(recipient, subject_line, edited)
                if ok:
                    st.session_state["contacted"][url] = {
                        "at": time.strftime("%Y-%m-%d %H:%M"),
                        "by": st.session_state.get("rep_name", ""),
                    }
                    st.success(_t("Sent!", "Gesendet!"))
                else:
                    st.error(msg)
        with sccol2:
            if url in st.session_state["contacted"]:
                st.success(f"✅ {_t('Contacted','Kontaktiert')} {st.session_state['contacted'][url].get('at','')}")

    # ── PDF + live preview ───────────────────────────────────────────────────
    pcol1, pcol2 = st.columns([1, 1])
    with pcol1:
        try:
            pdf_bytes = generate_audit_pdf(a, lang=_LANG)
            st.download_button(
                f"📄 {_t('Download audit PDF','Audit-PDF herunterladen')}",
                data=pdf_bytes, file_name=f"{_domain(url)}_audit.pdf",
                mime="application/pdf", use_container_width=True, key="detail_pdf",
            )
        except Exception:
            st.caption(_t("PDF unavailable", "PDF nicht verfügbar"))
    with pcol2:
        _safe_url_key = url.replace("https://", "").replace("http://", "").replace("/", "_").strip("_")
        _preview_session_key = f"preview_result_{_safe_url_key}"
        _cached_preview = st.session_state.get(_preview_session_key)
        if PREVIEW_API_AVAILABLE and st.button(
            f"🌐 {_t('Generate live preview','Live-Vorschau erstellen')}",
            key="detail_preview", use_container_width=True):
            _pk = get_preview_api_key() or _get_secret("PREVIEW_SERVICE_KEY")
            if not _pk:
                st.warning(_t("No PREVIEW_SERVICE_KEY configured.", "Kein PREVIEW_SERVICE_KEY konfiguriert."))
            else:
                _ph = st.empty()
                with st.spinner(_t("Measuring on fast.site edge…", "Messung am fast.site-Edge…")):
                    _res = run_preview_measurement(url=url, api_key=_pk,
                                                   progress_callback=lambda m: _ph.info(m))
                _ph.empty()
                st.session_state[_preview_session_key] = _res
                _record_preview(url, _res, name=name)
                st.rerun()
    if PREVIEW_API_AVAILABLE and _cached_preview is not None:
        render_preview_results(_cached_preview)
        if _cached_preview.ok and not _cached_preview.inconclusive:
            st.success(
                f"✅ **{_t('Real measurement complete','Echte Messung abgeschlossen')}** — "
                f"TTFB {_t('improved by','verbessert um')} **{_cached_preview.ttfb_improvement_pct}%**, "
                f"PageSpeed **{_cached_preview.perf_score_origin} → {_cached_preview.perf_score_preview}** "
                f"(+{_cached_preview.score_improvement} {_t('pts','Punkte')}). "
                f"[{_t('View live preview','Live-Vorschau ansehen')}]({_cached_preview.preview_url})"
            )
        if getattr(_cached_preview, "preview_url", ""):
            if st.button(
                f"🗑 {_t('Unpreview this site','Vorschau entfernen')}",
                key=f"unpreview_detail_{_safe_url_key}",
            ):
                _remove_preview(url)
                st.session_state.pop(_preview_session_key, None)
                st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# VIEW: LEADS  (search bar on top, live results table below)
# ═════════════════════════════════════════════════════════════════════════════
if _view == "leads":
    # ── One mode selector, present exactly once ──────────────────────────────
    _mode = st.radio(
        _t("Mode", "Modus"),
        options=["search", "direct"],
        format_func=lambda m: (f"🔍 {_t('Search businesses','Unternehmen suchen')}" if m == "search"
                               else f"🌐 {_t('Audit a URL','URL prüfen')}"),
        horizontal=True, label_visibility="collapsed", key="search_mode",
    )

    if _mode == "search":
        s1, s2, s3, s4, s5 = st.columns([2.2, 2.2, 2.2, 1, 1.2])
        with s1:
            industry = st.text_input(_t("Category", "Kategorie"),
                                     placeholder=_t("e.g. dentist", "z. B. Zahnarzt"), key="q_industry")
        with s2:
            area = st.text_input(_t("Location", "Standort"),
                                 placeholder=_t("e.g. Berlin, Germany", "z. B. Berlin"), key="q_area")
        with s3:
            search_query = st.text_input(_t("Keywords (optional)", "Stichworte (optional)"),
                                         placeholder=_t("family owned…", "familiengeführt…"), key="q_kw")
        with s4:
            max_results = st.number_input(_t("Max", "Max"), min_value=1, max_value=50, value=15, key="q_max")
        with s5:
            st.markdown("<div style='height:1.75rem;'></div>", unsafe_allow_html=True)
            do_search = st.button(f"🔍 {_t('Search','Suchen')}", type="primary",
                                  use_container_width=True, key="do_search")

        if do_search:
            if not industry.strip() or not area.strip():
                st.warning(_t("Enter a category and a location.", "Kategorie und Standort eingeben."))
            else:
                with st.spinner(_t("Searching the web…", "Suche im Web…")):
                    results, engines = multi_engine_search(industry, area, int(max_results), query=search_query)
                st.session_state["results"] = results
                st.session_state["engines"] = engines
                st.session_state["detail_url"] = None
                # tech + cdn detection for the new URLs
                if results:
                    prog = st.progress(0.0)
                    ph = st.empty()
                    urls = [r.get("source_url", "") for r in results if r.get("source_url")]
                    for i, u in enumerate(urls):
                        ph.caption(f"🧪 {_t('Detecting tech','Tech erkennen')} — {_domain(u)}")
                        st.session_state["tech"][u] = detect_tech(u)
                        st.session_state["cdn_map"][u] = detect_cdn(u)
                        prog.progress((i + 1) / (len(urls) or 1))
                    prog.empty(); ph.empty()
                st.rerun()

    else:  # direct URL mode
        d1, d2 = st.columns([5, 1.2])
        with d1:
            direct_url = st.text_input(_t("Website URL", "Website-URL"),
                                       placeholder="https://example.com", key="q_direct")
        with d2:
            st.markdown("<div style='height:1.75rem;'></div>", unsafe_allow_html=True)
            do_direct = st.button(f"⚡ {_t('Audit','Prüfen')}", type="primary",
                                  use_container_width=True, key="do_direct")
        if do_direct and direct_url.strip():
            u = direct_url.strip()
            if not u.startswith("http"):
                u = "https://" + u
            # add to the unified results list if not already present
            if not any(r.get("source_url") == u for r in st.session_state["results"]):
                st.session_state["results"].append(
                    {"source_url": u, "business_name": _domain(u), "source": "direct"})
            st.session_state["tech"][u] = detect_tech(u)
            prog = st.progress(0.0); ph = st.empty()
            _run_audits([u], ph, prog)
            prog.empty(); ph.empty()
            st.session_state["detail_url"] = u
            st.rerun()

    # ── Results table ────────────────────────────────────────────────────────
    results = st.session_state["results"]
    if not results:
        st.markdown(f"""
<div style="border:1px dashed #CBD5E1;border-radius:14px;padding:3rem 2rem;text-align:center;color:#64748B;">
  <div style="font-size:2.5rem;">🔍</div>
  <div style="font-weight:700;color:#0F172A;margin-top:0.5rem;">
    {_t('No leads yet','Noch keine Leads')}</div>
  <div style="font-size:0.88rem;max-width:420px;margin:0.4rem auto 0;">
    {_t('Search a category + location above, or audit a single URL. Results appear here as a sortable table.',
        'Oben Kategorie + Standort suchen oder eine einzelne URL prüfen. Ergebnisse erscheinen hier als sortierbare Tabelle.')}
  </div>
</div>
""", unsafe_allow_html=True)
    else:
        urls = [r.get("source_url", "") for r in results if r.get("source_url")]
        n_checked = sum(1 for u in urls if u in st.session_state["audits"])
        n_unchecked = len(urls) - n_checked

        # action bar: run speed checks + filters
        a1, a2, a3 = st.columns([1.6, 1.4, 2])
        with a1:
            if st.button(
                f"⚡ {_t('Run speed checks','Speed-Checks ausführen')}"
                + (f" ({n_unchecked})" if n_unchecked else ""),
                type="primary", use_container_width=True, key="run_checks",
                disabled=(n_unchecked == 0)):
                to_check = [u for u in urls if u not in st.session_state["audits"]]
                prog = st.progress(0.0); ph = st.empty()
                _run_audits(to_check, ph, prog)
                prog.empty(); ph.empty()
                st.rerun()
        with a2:
            min_opp = st.slider(_t("Min opportunity", "Min. Chance"), 0, 100, 0, key="filt_opp",
                                help=DEFS["opportunity"])
        with a3:
            needle = st.text_input(_t("Filter by name / URL", "Nach Name / URL filtern"),
                                   key="filt_text", placeholder="…")

        # build rows
        row_urls, rows = [], []
        for r in results:
            u = r.get("source_url", "")
            if not u:
                continue
            sc = _audit_scores(u)
            name = _biz_name(u)
            if needle and needle.lower() not in name.lower() and needle.lower() not in u.lower():
                continue
            if sc["state"] == "ok" and sc["opp"] < min_opp:
                continue
            emoji, tl_label, _hex, _mean = _traffic_light(sc["opp"] if sc["state"] == "ok" else None)
            row_urls.append(u)
            rows.append({
                "": emoji,
                _t("Business", "Unternehmen"): name,
                _t("Website", "Website"): _domain(u),
                _t("Opportunity", "Chance"): sc["opp"] if sc["state"] == "ok" else None,
                _t("Speed", "Speed"): sc["speed"] if sc["state"] == "ok" else None,
                _t("Overall", "Gesamt"): sc["overall"] if sc["state"] == "ok" else None,
                _t("Status", "Status"): (tl_label if sc["state"] == "ok"
                                         else (_t("error", "Fehler") if sc["state"] == "error"
                                               else _t("not checked", "ungeprüft"))),
                _t("Contacted", "Kontaktiert"): "✅" if u in st.session_state["contacted"] else "",
            })

        if not rows:
            st.info(_t("No leads match the current filters.", "Keine Leads passen zu den Filtern."))
        else:
            df = pd.DataFrame(rows)
            event = st.dataframe(
                df, hide_index=True, use_container_width=True, key="leads_table",
                on_select="rerun", selection_mode="single-row",
                column_config={
                    "": st.column_config.TextColumn("", width="small"),
                    _t("Opportunity", "Chance"): st.column_config.NumberColumn(
                        _t("Opportunity", "Chance"), help=DEFS["opportunity"], format="%d"),
                    _t("Speed", "Speed"): st.column_config.NumberColumn(
                        _t("Speed", "Speed"), help=DEFS["speed"], format="%d"),
                    _t("Overall", "Gesamt"): st.column_config.NumberColumn(
                        _t("Overall", "Gesamt"), help=DEFS["overall"], format="%d"),
                },
            )
            st.caption(_t(
                "🔴 Hot (65+) · 🟠 Warm (42–64) · 🟢 Cold (<42) — higher opportunity = better lead. Click a row for details.",
                "🔴 Heiß (65+) · 🟠 Warm (42–64) · 🟢 Kalt (<42) — höhere Chance = besserer Lead. Zeile anklicken für Details.",
            ))
            sel = event.selection.rows if event and event.selection else []
            if sel:
                st.session_state["detail_url"] = row_urls[sel[0]]

        if st.session_state.get("detail_url") in row_urls:
            _render_detail(st.session_state["detail_url"])


# ═════════════════════════════════════════════════════════════════════════════
# VIEW: HISTORY
# ═════════════════════════════════════════════════════════════════════════════
elif _view == "history":
    st.markdown(f"### 🕘 {_t('Checked companies','Geprüfte Unternehmen')}")
    history = st.session_state.get("history", {})
    if not history:
        st.info(_t("No companies checked yet.", "Noch keine Unternehmen geprüft."))
    else:
        needle = st.text_input(_t("Filter", "Filtern"), key="hist_filter", placeholder="…")
        items = [e for e in history.values()
                 if not needle
                 or needle.lower() in e.get("business_name", "").lower()
                 or needle.lower() in e.get("url", "").lower()]
        items.sort(key=lambda e: e.get("last_checked", ""), reverse=True)
        rows = []
        for e in items:
            u = e.get("url", "")
            opp = opportunity_score(e["audit"], cdn_info=st.session_state["cdn_map"].get(u, {})) \
                if e.get("audit") and not e["audit"].get("error") else None
            emoji, tl, _h, _m = _traffic_light(opp)
            rows.append({
                "": emoji,
                _t("Business", "Unternehmen"): e.get("business_name", u),
                _t("Website", "Website"): _domain(u),
                _t("Opportunity", "Chance"): opp,
                _t("Overall", "Gesamt"): e.get("overall_score", 0),
                _t("Checks", "Prüfungen"): e.get("check_count", 1),
                _t("Last checked", "Zuletzt"): e.get("last_checked", ""),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        # ── Per-site live preview + report ────────────────────────────────────
        st.markdown(f"#### 🌐 {_t('Live preview & reports','Live-Vorschau & Berichte')}")
        _hist_preview_key = get_preview_api_key() if PREVIEW_API_AVAILABLE else None
        _previews_by_url = {p["url"]: p for p in _active_previews()}
        for i, e in enumerate(items):
            u    = e.get("url", "")
            name = e.get("business_name", u)
            with st.container():
                hc1, hc2, hc3 = st.columns([2.2, 1.8, 1])
                with hc1:
                    st.markdown(f"**{name}**")
                    st.caption(_domain(u))
                with hc2:
                    _preview_for_url = _previews_by_url.get(u)
                    if _preview_for_url and _preview_for_url.get("preview_url"):
                        _one_liner = _preview_one_liner(_preview_for_url)
                        st.markdown(
                            f'<a href="{_preview_for_url["preview_url"]}" target="_blank" '
                            f'style="font-size:0.82rem;color:#2563EB;font-weight:600;word-break:break-all;">'
                            f'🌐 {_html_mod.escape(_preview_for_url["preview_url"])}</a>'
                            f'<div style="font-size:0.76rem;color:#059669;font-weight:600;margin-top:2px;">'
                            f'{_html_mod.escape(_one_liner)}</div>',
                            unsafe_allow_html=True,
                        )
                        if st.button(f"🗑 {_t('Unpreview', 'Entfernen')}",
                                     key=f"hist_unpreview_{i}", use_container_width=True):
                            _remove_preview(u)
                            st.rerun()
                    elif PREVIEW_API_AVAILABLE and _hist_preview_key:
                        _safe_hist_url = u.replace("https://", "").replace("http://", "").replace("/", "_").strip("_")
                        if st.button(f"🚀 {_t('Run preview', 'Vorschau starten')}",
                                     key=f"hist_run_preview_{i}_{_safe_hist_url}",
                                     use_container_width=True):
                            _status_ph = st.empty()
                            with st.spinner(_t("Provisioning edge preview…", "Edge-Vorschau wird bereitgestellt…")):
                                _hist_result = run_preview_measurement(
                                    url=u, api_key=_hist_preview_key,
                                    progress_callback=lambda m: _status_ph.info(m),
                                )
                            _status_ph.empty()
                            _record_preview(u, _hist_result, name=name)
                            st.rerun()
                    else:
                        st.caption(_t("No live preview yet", "Noch keine Live-Vorschau"))
                with hc3:
                    try:
                        _hist_pdf = generate_audit_pdf(e["audit"], lang=_LANG)
                        _safe_name = u.replace("https://", "").replace("http://", "").replace("/", "_").strip("_")
                        st.download_button(
                            f"⬇ {_t('Report', 'Bericht')}",
                            data=_hist_pdf, file_name=f"audit_{_safe_name}.pdf",
                            mime="application/pdf", use_container_width=True,
                            key=f"hist_pdf_{i}_{_safe_name}",
                        )
                    except Exception:
                        st.caption(_t("Report unavailable", "Bericht nicht verfügbar"))
                st.divider()

        if st.button(f"🗑 {_t('Clear history','Verlauf löschen')}", key="hist_clear"):
            st.session_state["history"] = {}
            st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# VIEW: EXPORTS
# ═════════════════════════════════════════════════════════════════════════════
elif _view == "exports":
    st.markdown(f"### 📤 {_t('Exports & reports','Export & Berichte')}")
    audits = st.session_state.get("audits", {})
    ok_audits = [a for a in audits.values() if not a.get("error")]
    if not ok_audits:
        st.info(_t("No audit data to export yet. Run some speed checks on the Leads view first.",
                   "Noch keine Auditdaten. Zuerst Speed-Checks in der Leads-Ansicht ausführen."))
    else:
        opps = [opportunity_score(a, cdn_info=st.session_state["cdn_map"].get(a.get("url", ""), {}))
                for a in ok_audits]
        n_hot = sum(1 for o in opps if o >= 65)
        k1, k2, k3 = st.columns(3)
        k1.metric(_t("Audited", "Geprüft"), len(ok_audits))
        k2.metric(_t("Hot leads", "Heiße Leads"), n_hot)
        k3.metric(_t("Avg opportunity", "Ø Chance"), round(sum(opps) / len(opps)) if opps else 0)

        csv_bytes = build_leads_csv(
            ok_audits, st.session_state.get("contacts", {}), st.session_state.get("cdn_map", {}))
        csv_bytes = _add_contacted_column(csv_bytes, st.session_state.get("contacted", {}))
        st.download_button(
            f"⬇ {_t('Download leads CSV','Leads-CSV herunterladen')}",
            data=csv_bytes, file_name="fastsite_leads.csv", mime="text/csv",
            type="primary", use_container_width=True, key="exp_csv")

        st.markdown(f"#### 📄 {_t('Audit PDFs','Audit-PDFs')}")
        for a in ok_audits:
            u = a.get("url", "")
            c1, c2 = st.columns([4, 1.4])
            c1.write(f"**{_biz_name(u)}** · {_domain(u)}")
            try:
                pdf_b = generate_audit_pdf(a, lang=_LANG)
                c2.download_button("📄 PDF", data=pdf_b, file_name=f"{_domain(u)}_audit.pdf",
                                   mime="application/pdf", key=f"exp_pdf_{u}", use_container_width=True)
            except Exception:
                c2.caption(_t("n/a", "n. v."))


# ═════════════════════════════════════════════════════════════════════════════
# VIEW: SETTINGS
# ═════════════════════════════════════════════════════════════════════════════
elif _view == "settings":
    st.markdown(f"### ⚙️ {_t('Settings','Einstellungen')}")
    st.markdown(f"**{_t('Signed in as','Angemeldet als')}:** {st.session_state.get('rep_name','—')}")
    st.markdown(f"**{_t('Language','Sprache')}:** {'English' if _LANG == 'en' else 'Deutsch'}")

    st.markdown(f"#### {_t('Integration status','Integrationsstatus')}")
    def _ok(v): return "✅" if v else "❌"
    st.markdown(
        f"- {_ok(bool(_get_secret('SMTP_USER')))} SMTP (email sending)\n"
        f"- {_ok(bool(_get_secret('PREVIEW_SERVICE_KEY')))} Preview service\n"
        f"- {_ok(bool(_get_secret('LOCATIONIQ_KEY')))} LocationIQ\n"
        f"- {_ok(LEAD_TOOLS_AVAILABLE)} Lead tools\n"
        f"- {_ok(CONTACT_AVAILABLE)} Contact extractor\n"
        f"- {_ok(PREVIEW_API_AVAILABLE)} Preview API"
    )

    st.markdown(f"#### {_t('Session data','Sitzungsdaten')}")
    st.markdown(
        f"- {len(st.session_state.get('results', []))} {_t('leads','Leads')}\n"
        f"- {len(st.session_state.get('audits', {}))} {_t('audits','Audits')}\n"
        f"- {len(st.session_state.get('history', {}))} {_t('in history','im Verlauf')}\n"
        f"- {len(st.session_state.get('contacted', {}))} {_t('contacted','kontaktiert')}"
    )
    if st.button(f"🧹 {_t('Reset all session data','Alle Sitzungsdaten zurücksetzen')}", key="reset_all"):
        for k in ["results", "audits", "cdn_map", "tech", "contacts", "contacted", "history", "previews", "engines"]:
            st.session_state[k] = [] if k in ("results", "engines") else {}
        st.session_state["detail_url"] = None
        st.rerun()


# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center;color:#94A3B8;font-size:0.78rem;padding:1.5rem 0 0.5rem;">
  <span style="font-weight:700;color:#2563EB;">⚡ fast.site</span> · Lead Finder ·
  {_t('Find · Audit · Contact · Export','Finden · Prüfen · Kontaktieren · Exportieren')}
</div>
""", unsafe_allow_html=True)
