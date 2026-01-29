import re
import time
import sqlite3
from dataclasses import dataclass, asdict
from urllib.parse import urlparse
from typing import Optional, Dict, Any, Tuple, List


import streamlit as st

st.markdown(r"""<style>
html, body, [class*="css"] {
  color: #111111 !important;
  background-color: #ffffff !important;
}
h1, h2, h3, h4, h5, h6 {
  color: #0f172a !important;
}
p, span, label, div {
  color: #1f2937 !important;
}

/* Streamlit inputs */
input, textarea, select {
  color: #111111 !important;
}

/* Buttons */
.stButton > button {
  color: #111111 !important;
}
</style>""", unsafe_allow_html=True)

import requests
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors

APP_NAME = "AIRE™"
APP_TAGLINE = "Real estate underwriting, terminal-style."
DB_PATH = "aire_app.db"

FREE_CREDITS = 2
PRO_CREDITS = 5000
CREDIT_COST_PER_ANALYSIS = 1

SOFT_BG = "#0B1020"
CARD_BG = "#0F172A"
CARD_BG_2 = "#0B1226"
TEXT = "#E5E7EB"
MUTED = "#9CA3AF"
ACCENT = "#22D3EE"
ACCENT_2 = "#34D399"
WARN = "#F59E0B"
DANGER = "#FB7185"

st.set_page_config(page_title=f"{APP_NAME} | Terminal", page_icon="🏠", layout="wide")

CSS = f"""
<style>
html, body, [class*='css'] {{
}}
h1, h2, h3, h4, h5, h6 {
    color: #0f172a !important;
}
p, span, label, div {
    color: #1f2937 !important;
}

  .main {{ background: {SOFT_BG}; }}
  .block-container {{ padding-top: 1.0rem; padding-bottom: 2.25rem; max-width: 1350px; }}
  h1,h2,h3,h4,h5,h6,p,li,span,div {{ color: {TEXT}; }}
  .aire-top {{
    background: linear-gradient(90deg, #0EA5E9 0%, #22C55E 60%, #A78BFA 100%);
    padding: 14px 16px;
    border-radius: 16px;
    box-shadow: 0 12px 28px rgba(0,0,0,.35);
  }}
  .aire-title {{ font-size: 24px; font-weight: 900; letter-spacing: .3px; margin: 0; color: #06101A; }}
  .aire-sub {{ font-size: 12px; opacity: .95; margin-top: 2px; color: #06101A; }}
  .card {{
    background: {CARD_BG};
    border-radius: 16px;
    padding: 14px;
    border: 1px solid rgba(255,255,255,.07);
    box-shadow: 0 10px 22px rgba(0,0,0,.25);
  }}
  .card2 {{
    background: {CARD_BG_2};
    border-radius: 16px;
    padding: 14px;
    border: 1px solid rgba(255,255,255,.07);
  }}
  .kpi {{
    background: {CARD_BG_2};
    border-radius: 16px;
    padding: 12px;
    border: 1px solid rgba(255,255,255,.07);
  }}
  .pill {{
    display:inline-block;
    padding: 6px 10px;
    border-radius: 999px;
    background: rgba(34,211,238,.16);
    color: {ACCENT};
    font-weight: 900;
    font-size: 12px;
    margin-right: 8px;
  }}
  .pill2 {{
    display:inline-block;
    padding: 6px 10px;
    border-radius: 999px;
    background: rgba(52,211,153,.16);
    color: {ACCENT_2};
    font-weight: 900;
    font-size: 12px;
    margin-right: 8px;
  }}
  .warn {{
    display:inline-block;
    padding: 6px 10px;
    border-radius: 999px;
    background: rgba(245,158,11,.18);
    color: {WARN};
    font-weight: 900;
    font-size: 12px;
    margin-right: 8px;
  }}
  .danger {{
    display:inline-block;
    padding: 6px 10px;
    border-radius: 999px;
    background: rgba(251,113,133,.16);
    color: {DANGER};
    font-weight: 900;
    font-size: 12px;
    margin-right: 8px;
  }}
  .small {{ color: {MUTED}; font-size: 12px; }}
  .stButton>button, .stDownloadButton>button {{
    border-radius: 12px;
    padding: 10px 14px;
    font-weight: 800;
  }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

@dataclass
class PropertyData:
    """Normalized, cross-asset inputs for AIRE Vector Grade™.

    The grader intentionally accepts partial data; weights are re-normalized to what is provided.
    """

    # Core
    property_type: str = "Multifamily"   # Multifamily | Single Family | Office | Retail | Industrial | Land
    address: str = ""

    # Deal basics
    price: Optional[float] = None
    replacement_cost: Optional[float] = None
    days_on_market: Optional[int] = None
    last_sale_price: Optional[float] = None
    last_sale_date: Optional[str] = None

    # Income / Ops (can be rent+expenses OR NOI override)
    monthly_rent: Optional[float] = None
    monthly_expenses: Optional[float] = None
    vacancy_rate: Optional[float] = None          # 0-1 (if provided)
    occupancy_pct: Optional[float] = None         # 0-100 (preferred; overrides vacancy if provided)

    noi_annual_override: Optional[float] = None   # institutional pro-forma input
    cap_rate_override_pct: Optional[float] = None # if known, infer NOI from price

    # Financing
    down_payment_pct: Optional[float] = None
    interest_rate_pct: Optional[float] = None
    term_years: Optional[int] = None

    # Location / Policy
    job_diversity_index: Optional[float] = None   # 0-1 proxy
    rent_regulation_risk: Optional[bool] = None

    # Size (optional, used for validation / future agents)
    units: Optional[int] = None
    sqft: Optional[float] = None

def _db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            credits INTEGER DEFAULT 0,
            paid INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT 0,
            updated_at INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            address TEXT,
            listing_url TEXT,
            grade TEXT,
            verdict TEXT,
            score REAL,
            confidence REAL,
            dscr REAL,
            noi REAL,
            cap_rate REAL,
            coc_return REAL,
            price_change_pct REAL,
            json_payload TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            address TEXT NOT NULL,
            zip TEXT,
            listing_url TEXT,
            target_grade TEXT,
            target_score REAL,
            notes TEXT,
            pinned INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            name TEXT NOT NULL,
            address TEXT,
            units INTEGER DEFAULT 1,
            purchase_price REAL,
            current_value REAL,
            loan_balance REAL,
            interest_rate_pct REAL,
            term_years INTEGER,
            monthly_rent REAL,
            monthly_expenses REAL,
            vacancy_rate REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            name TEXT NOT NULL,
            template_json TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def _now() -> int:
    return int(time.time())

def get_user(email: str) -> Dict[str, Any]:
    conn = _db()
    cur = conn.execute("SELECT email, credits, paid FROM users WHERE email=?", (email,))
    row = cur.fetchone()
    now = _now()
    if not row:
        conn.execute(
            "INSERT INTO users(email, credits, paid, created_at, updated_at) VALUES(?,?,?,?,?)",
            (email, FREE_CREDITS, 0, now, now),
        )
        conn.commit()
        return {"email": email, "credits": FREE_CREDITS, "paid": 0}
    return {"email": row[0], "credits": int(row[1]), "paid": int(row[2])}

def set_paid(email: str, paid: int = 1):
    conn = _db()
    credits = PRO_CREDITS if paid else FREE_CREDITS
    conn.execute("UPDATE users SET paid=?, credits=?, updated_at=? WHERE email=?", (paid, credits, _now(), email))
    conn.commit()

def spend_credit(email: str, amount: int = CREDIT_COST_PER_ANALYSIS) -> bool:
    conn = _db()
    cur = conn.execute("SELECT credits, paid FROM users WHERE email=?", (email,))
    row = cur.fetchone()
    if not row:
        return False
    credits, paid = int(row[0]), int(row[1])
    if paid:
        return True
    if credits < amount:
        return False
    conn.execute("UPDATE users SET credits = credits - ?, updated_at=? WHERE email=?", (amount, _now(), email))
    conn.commit()
    return True

def json_dumps(obj: Any) -> str:
    import json

# =========================
# Real data providers (optional)
# =========================
import datetime as _dt
import pandas as _pd
import numpy as _np

def _get_secret(key: str, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default

RENTCAST_APIKEY = _get_secret("RENTCAST_APIKEY")
FRED_API_KEY = _get_secret("FRED_API_KEY")

@st.cache_data(show_spinner=False, ttl=60*60)
def rentcast_property_record(address_one_line: str) -> dict | None:
    """Fetch a single property record using /v1/properties?address=... (RentCast)."""
    if not RENTCAST_APIKEY or not address_one_line:
        return None
    url = "https://api.rentcast.io/v1/properties"
    headers = {"Accept": "application/json", "X-Api-Key": RENTCAST_APIKEY}
    try:
        resp = requests.get(url, headers=headers, params={"address": address_one_line}, timeout=20)
        if resp.status_code != 200:
            return None
        data = resp.json()
        # API may return an array or an object depending on query; normalize to dict
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        return None

@st.cache_data(show_spinner=False, ttl=60*60)
def rentcast_value_avm(address_one_line: str) -> dict | None:
    if not RENTCAST_APIKEY or not address_one_line:
        return None
    url = "https://api.rentcast.io/v1/avm/value"
    headers = {"Accept": "application/json", "X-Api-Key": RENTCAST_APIKEY}
    try:
        resp = requests.get(url, headers=headers, params={"address": address_one_line}, timeout=20)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None

@st.cache_data(show_spinner=False, ttl=60*60)
def rentcast_rent_avm(address_one_line: str) -> dict | None:
    if not RENTCAST_APIKEY or not address_one_line:
        return None
    url = "https://api.rentcast.io/v1/avm/rent/long-term"
    headers = {"Accept": "application/json", "X-Api-Key": RENTCAST_APIKEY}
    try:
        resp = requests.get(url, headers=headers, params={"address": address_one_line}, timeout=20)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None

@st.cache_data(show_spinner=False, ttl=60*60)
def rentcast_market(zip_code: str, data_type: str="All", history_range: str="12m") -> dict | None:
    if not RENTCAST_APIKEY or not zip_code:
        return None
    url = "https://api.rentcast.io/v1/markets"
    headers = {"Accept": "application/json", "X-Api-Key": RENTCAST_APIKEY}
    params = {"zipCode": zip_code, "dataType": data_type, "historyRange": history_range}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None

@st.cache_data(show_spinner=False, ttl=6*60*60)
def fred_series_observations(series_id: str, limit: int=104) -> _pd.DataFrame | None:
    """Fetch series observations from FRED (requires FRED_API_KEY)."""
    if not FRED_API_KEY:
        return None
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    try:
        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code != 200:
            return None
        j = resp.json()
        obs = j.get("observations", [])
        rows = []
        for o in obs:
            d = o.get("date")
            v = o.get("value")
            try:
                val = float(v)
            except Exception:
                continue
            rows.append({"date": d, "value": val})
        if not rows:
            return None
        df = _pd.DataFrame(rows)
        df["date"] = _pd.to_datetime(df["date"])
        df = df.sort_values("date")
        return df
    except Exception:
        return None

def _extract_zip(address_one_line: str) -> str | None:
    if not address_one_line:
        return None
    m = re.search(r"\b(\d{5})(?:-\d{4})?\b", address_one_line)
    return m.group(1) if m else None

def _safe_get(d: dict, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

def _infer_last_sale(prop_record: dict | None):
    """Return (price, date) if found in various possible RentCast fields."""
    if not prop_record:
        return None, None
    # Common possibilities
    for price_key, date_key in [
        ("lastSalePrice", "lastSaleDate"),
        ("salePrice", "saleDate"),
        ("last_sale_price", "last_sale_date"),
    ]:
        p = prop_record.get(price_key)
        d = prop_record.get(date_key)
        if p and d:
            return p, d
    # Try sale history list
    for hist_key in ["saleHistory", "salesHistory", "sale_history", "sales"]:
        h = prop_record.get(hist_key)
        if isinstance(h, list) and h:
            # assume most recent first; otherwise sort by date string
            try:
                h_sorted = sorted(h, key=lambda x: str(x.get("date") or x.get("saleDate") or ""), reverse=True)
            except Exception:
                h_sorted = h
            top = h_sorted[0] if h_sorted else None
            if isinstance(top, dict):
                p = top.get("price") or top.get("salePrice")
                d = top.get("date") or top.get("saleDate")
                if p and d:
                    return p, d
    return None, None

    return json.dumps(obj, ensure_ascii=False)

def save_analysis(email: str, address: str, listing_url: str, result: Dict[str, Any], payload: Dict[str, Any]):
    conn = _db()
    conn.execute(
        """INSERT INTO analyses(email, created_at, address, listing_url, grade, verdict, score, confidence,
           dscr, noi, cap_rate, coc_return, price_change_pct, json_payload)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            email,
            _now(),
            address,
            listing_url,
            result.get("grade"),
            result.get("verdict"),
            float(result.get("score", 0)),
            float(result.get("confidence", 0)),
            float(result.get("dscr", 0)),
            float(result.get("noi", 0)),
            float(result.get("cap_rate", 0)),
            float(result.get("coc_return", 0)),
            float(result.get("price_change_pct", 0)) if result.get("price_change_pct") is not None else None,
            json_dumps(payload),
        ),
    )
    conn.commit()

def fetch_analyses(email: str, limit: int = 50) -> List[Dict[str, Any]]:
    conn = _db()
    cur = conn.execute(
        "SELECT created_at, address, grade, verdict, score, confidence, dscr, cap_rate, coc_return, price_change_pct FROM analyses WHERE email=? ORDER BY created_at DESC LIMIT ?",
        (email, limit),
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        out.append({
            "created_at": int(r[0]),
            "address": r[1],
            "grade": r[2],
            "verdict": r[3],
            "score": r[4],
            "confidence": r[5],
            "dscr": r[6],
            "cap_rate": r[7],
            "coc_return": r[8],
            "price_change_pct": r[9],
        })
    return out
def add_watchlist_item(email: str, address: str, listing_url: str = "", zip_code: str = "", target_grade: str = "A",
                       target_score: float = 85.0, notes: str = "", pinned: int = 0):
    conn = _db()
    now = _now()
    conn.execute(
        """INSERT INTO watchlist(email, created_at, updated_at, address, zip, listing_url, target_grade, target_score, notes, pinned)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (email, now, now, address, zip_code, listing_url, target_grade, target_score, notes, pinned),
    )
    conn.commit()

def update_watchlist_item(item_id: int, email: str, **fields):
    conn = _db()
    allowed = {"address","zip","listing_url","target_grade","target_score","notes","pinned"}
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals += [_now(), email, item_id]
    conn.execute(f"UPDATE watchlist SET {', '.join(sets)}, updated_at=? WHERE email=? AND id=?", tuple(vals))
    conn.commit()

def delete_watchlist_item(item_id: int, email: str):
    conn = _db()
    conn.execute("DELETE FROM watchlist WHERE email=? AND id=?", (email, item_id))
    conn.commit()

def fetch_watchlist(email: str, limit: int = 200):
    conn = _db()
    cur = conn.execute(
        "SELECT id, created_at, updated_at, address, zip, listing_url, target_grade, target_score, notes, pinned "
        "FROM watchlist WHERE email=? ORDER BY pinned DESC, updated_at DESC LIMIT ?",
        (email, limit),
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "created_at": int(r[1]), "updated_at": int(r[2]), "address": r[3], "zip": r[4],
            "listing_url": r[5], "target_grade": r[6] or "A", "target_score": float(r[7] or 85.0),
            "notes": r[8] or "", "pinned": int(r[9] or 0)
        })
    return out

def add_portfolio_item(email: str, name: str, **fields):
    conn = _db()
    now = _now()
    defaults = {
        "address": "", "units": 1, "purchase_price": None, "current_value": None, "loan_balance": None,
        "interest_rate_pct": None, "term_years": None, "monthly_rent": None, "monthly_expenses": None, "vacancy_rate": None
    }
    defaults.update(fields or {})
    conn.execute(
        """INSERT INTO portfolio(email, created_at, updated_at, name, address, units, purchase_price, current_value,
           loan_balance, interest_rate_pct, term_years, monthly_rent, monthly_expenses, vacancy_rate)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (email, now, now, name, defaults["address"], int(defaults["units"] or 1), defaults["purchase_price"], defaults["current_value"],
         defaults["loan_balance"], defaults["interest_rate_pct"], defaults["term_years"], defaults["monthly_rent"],
         defaults["monthly_expenses"], defaults["vacancy_rate"]),
    )
    conn.commit()

def update_portfolio_item(item_id: int, email: str, **fields):
    conn = _db()
    allowed = {"name","address","units","purchase_price","current_value","loan_balance","interest_rate_pct","term_years","monthly_rent","monthly_expenses","vacancy_rate"}
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals += [_now(), email, item_id]
    conn.execute(f"UPDATE portfolio SET {', '.join(sets)}, updated_at=? WHERE email=? AND id=?", tuple(vals))
    conn.commit()

def delete_portfolio_item(item_id: int, email: str):
    conn = _db()
    conn.execute("DELETE FROM portfolio WHERE email=? AND id=?", (email, item_id))
    conn.commit()

def fetch_portfolio(email: str, limit: int = 200):
    conn = _db()
    cur = conn.execute(
        "SELECT id, created_at, updated_at, name, address, units, purchase_price, current_value, loan_balance, interest_rate_pct, term_years, monthly_rent, monthly_expenses, vacancy_rate "
        "FROM portfolio WHERE email=? ORDER BY updated_at DESC LIMIT ?",
        (email, limit),
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "created_at": int(r[1]), "updated_at": int(r[2]), "name": r[3], "address": r[4],
            "units": int(r[5] or 1), "purchase_price": r[6], "current_value": r[7], "loan_balance": r[8],
            "interest_rate_pct": r[9], "term_years": r[10], "monthly_rent": r[11], "monthly_expenses": r[12], "vacancy_rate": r[13]
        })
    return out



def add_template(email: str, name: str, template: dict):
    conn = _db()
    now = _now()
    conn.execute(
        "INSERT INTO templates(email, created_at, updated_at, name, template_json) VALUES(?,?,?,?,?)",
        (email, now, now, name, json_dumps(template)),
    )
    conn.commit()

def update_template(template_id: int, email: str, name: str, template: dict):
    conn = _db()
    conn.execute(
        "UPDATE templates SET name=?, template_json=?, updated_at=? WHERE id=? AND email=?",
        (name, json_dumps(template), _now(), template_id, email),
    )
    conn.commit()

def delete_template(template_id: int, email: str):
    conn = _db()
    conn.execute("DELETE FROM templates WHERE id=? AND email=?", (template_id, email))
    conn.commit()

def fetch_templates(email: str, limit: int = 200):
    conn = _db()
    cur = conn.execute(
        "SELECT id, created_at, updated_at, name, template_json FROM templates WHERE email=? ORDER BY updated_at DESC LIMIT ?",
        (email, limit),
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        try:
            import json
            tj = json.loads(r[4]) if r[4] else {}
        except Exception:
            tj = {}
        out.append({"id": r[0], "created_at": int(r[1]), "updated_at": int(r[2]), "name": r[3], "template": tj})
    return out

def built_in_templates() -> dict:
    # Strategy defaults + included modules
    return {
        "LTR (Long-Term Rental)": {
            "included": ["Rent & Price","Expenses","Vacancy","Financing","Yield","Liquidity","Last Sale","Location"],
            "defaults": {
                "vacancy_rate": 0.08, "expense_ratio": 0.38, "down_payment_pct": 20.0,
                "interest_rate_pct": 7.25, "term_years": 30,
                "hold_years": 7, "rent_growth": 0.03, "expense_growth": 0.03,
                "appreciation": 0.03, "sale_cost_pct": 0.07, "use_exit_cap": False, "exit_cap_rate": 0.065
            },
            "targets": {"grade": "B", "score": 80}
        },
        "BRRRR": {
            "included": ["Rent & Price","Expenses","Vacancy","Financing","Yield","Downside","Liquidity","Last Sale","Location","Optionality"],
            "defaults": {
                "vacancy_rate": 0.08, "expense_ratio": 0.40, "down_payment_pct": 25.0,
                "interest_rate_pct": 7.50, "term_years": 30,
                "hold_years": 5, "rent_growth": 0.03, "expense_growth": 0.03,
                "appreciation": 0.03, "sale_cost_pct": 0.07, "use_exit_cap": True, "exit_cap_rate": 0.070
            },
            "targets": {"grade": "B", "score": 82}
        },
        "Flip": {
            "included": ["Rent & Price","Downside","Liquidity","Last Sale","Location","Optionality"],
            "defaults": {
                "vacancy_rate": 0.00, "expense_ratio": 0.00, "down_payment_pct": 100.0,
                "interest_rate_pct": 0.00, "term_years": 1,
                "hold_years": 1, "rent_growth": 0.00, "expense_growth": 0.00,
                "appreciation": 0.08, "sale_cost_pct": 0.08, "use_exit_cap": False, "exit_cap_rate": 0.0
            },
            "targets": {"grade": "B", "score": 78}
        },
        "STR (Short-Term Rental)": {
            "included": ["Rent & Price","Expenses","Vacancy","Financing","Yield","Liquidity","Last Sale","Location","Regulation"],
            "defaults": {
                "vacancy_rate": 0.12, "expense_ratio": 0.45, "down_payment_pct": 25.0,
                "interest_rate_pct": 7.50, "term_years": 30,
                "hold_years": 6, "rent_growth": 0.04, "expense_growth": 0.04,
                "appreciation": 0.03, "sale_cost_pct": 0.07, "use_exit_cap": False, "exit_cap_rate": 0.065
            },
            "targets": {"grade": "B", "score": 82}
        },
    }

def apply_template_to_session(tpl: dict):
    inc = tpl.get("included", [])
    defs = tpl.get("defaults", {})
    targs = tpl.get("targets", {})
    st.session_state["tpl_included"] = inc
    st.session_state["tpl_defaults"] = defs
    st.session_state["tpl_targets"] = targs

def fmt_money(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"${x:,.0f}"

def fmt_pct(x: Optional[float], digits: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x*100:.{digits}f}%"

def ts_to_str(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))

def extract_address_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if not path:
            return None
        segments = [s for s in path.split("/") if any(ch.isdigit() for ch in s)]
        if not segments:
            return None
        candidate = max(segments, key=len)
        candidate = re.sub(r"_rb/?$", "", candidate)
        addr = candidate.replace("-", " ")
        addr = re.sub(r"\d{6,}$", "", addr).strip()
        return addr if len(addr) >= 8 else None
    except Exception:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_estated(address: str) -> Optional[Dict[str, Any]]:
    token = st.secrets.get("ESTATED_TOKEN", None)
    if not token:
        return None
    url = "https://apis.estated.com/v4/property"
    params = {"token": token, "combined_address": address}
    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200:
        return None
    return r.json()

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_attom_basic(address: str) -> Optional[Dict[str, Any]]:
    apikey = st.secrets.get("ATTOM_APIKEY", None)
    if not apikey:
        return None
    url = "https://api.gateway.attomdata.com/propertyapi/v1.0.0/property/basicprofile"
    headers = {"accept": "application/json", "apikey": apikey}
    params = {"address": address}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    if r.status_code != 200:
        return None
    return r.json()

def _safe_get(d: Dict[str, Any], path: List[Any]) -> Any:
    cur = d
    for p in path:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur

def smart_prefill(address: str) -> Tuple[Dict[str, Any], List[str]]:
    suggested = {"price": None, "replacement_cost": None, "days_on_market": None, "last_sale_price": None, "last_sale_date": None}
    notes = []

    est = fetch_estated(address)
    if isinstance(est, dict):
        valuation = est.get("valuation", {}) or {}
        price = valuation.get("market_value") or valuation.get("value")
        if price:
            suggested["price"] = float(price)
            notes.append("Estated: pulled estimated value.")
        lsp = _safe_get(est, ["property", "last_sale_price"]) or _safe_get(est, ["property", "sale", "amount"])
        lsd = _safe_get(est, ["property", "last_sale_date"]) or _safe_get(est, ["property", "sale", "date"])
        if lsp:
            suggested["last_sale_price"] = float(lsp)
            notes.append("Estated: pulled last sale price.")
        if lsd:
            suggested["last_sale_date"] = str(lsd)
            notes.append("Estated: pulled last sale date.")

    att = fetch_attom_basic(address)
    if isinstance(att, dict):
        try:
            prop = None
            if "property" in att and isinstance(att["property"], list) and att["property"]:
                prop = att["property"][0]
            if isinstance(prop, dict):
                sale = prop.get("sale", {}) or {}
                assessment = prop.get("assessment", {}) or {}
                p2 = sale.get("amount") or assessment.get("market", {}).get("mktTtlValue")
                if p2 and not suggested["price"]:
                    suggested["price"] = float(p2)
                    notes.append("ATTOM: pulled price/value.")
                if sale.get("amount") and not suggested["last_sale_price"]:
                    suggested["last_sale_price"] = float(sale.get("amount"))
                    notes.append("ATTOM: pulled last sale price.")
                if sale.get("saleTransDate") and not suggested["last_sale_date"]:
                    suggested["last_sale_date"] = str(sale.get("saleTransDate"))
                    notes.append("ATTOM: pulled last sale date.")
        except Exception:
            notes.append("ATTOM available, but response shape differed.")

    if not notes:
        notes.append("No API keys set — manual mode.")
    return suggested, notes

def monthly_payment(principal: float, annual_rate_pct: float, term_years: int) -> float:
    r = (annual_rate_pct / 100) / 12.0
    n = term_years * 12
    if r <= 0:
        return principal / max(n, 1)
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


def _irr(cashflows: list[float]) -> float | None:
    try:
        # numpy irr expects periodic cashflows
        r = _np.irr(_np.array(cashflows, dtype=float))
        if r is None or _np.isnan(r):
            return None
        return float(r)
    except Exception:
        return None

def _npv(rate: float, cashflows: list[float]) -> float | None:
    try:
        # rate is periodic (annual if annual cashflows)
        total = 0.0
        for t, cf in enumerate(cashflows):
            total += cf / ((1 + rate) ** t)
        return float(total)
    except Exception:
        return None

def project_cashflows(p: PropertyData, nums: dict, hold_years: int, rent_growth: float, expense_growth: float,
                      appreciation: float, sale_cost_pct: float, exit_cap_rate: float | None = None) -> dict:
    """Builds a basic annual cashflow model (levered if financing exists)."""
    # Start with a best-effort annual NOI and debt service
    noi0 = nums.get("noi_year")
    if noi0 is None and p.monthly_rent is not None and p.monthly_expenses is not None:
        vac = p.vacancy_rate if p.vacancy_rate is not None else 0.08
        noi0 = ((p.monthly_rent * (1 - vac)) - p.monthly_expenses) * 12

    debt0 = None
    if nums.get("loan_payment") is not None:
        debt0 = (nums["loan_payment"] or 0) * 12

    # Initial equity outlay
    if p.price is None:
        return {"cashflows": [], "irr": None, "npv": None, "exit_value": None}

    down = p.down_payment_pct/100 if p.down_payment_pct is not None else 1.0
    equity0 = p.price * down
    cashflows = [-equity0]

    noi = float(noi0 or 0.0)
    debt = float(debt0 or 0.0) if debt0 is not None else 0.0

    # Annual operating cashflows
    for yr in range(1, hold_years + 1):
        if yr > 1:
            noi *= (1 + rent_growth)  # gross effect; simplified
            noi *= (1 - expense_growth) if expense_growth < 1 else 0.0  # keep sane
        levered = noi - debt
        cashflows.append(levered)

    # Exit value: either appreciation compounding or exit cap on final NOI
    if exit_cap_rate is not None and exit_cap_rate > 0:
        exit_value = (noi / exit_cap_rate)
    else:
        exit_value = p.price * ((1 + appreciation) ** hold_years)

    # Sale costs
    net_sale = exit_value * (1 - sale_cost_pct)

    # If there is a loan, subtract remaining principal very roughly (interest-only approximation)
    # For demo: assume outstanding ~ original loan amount
    if p.down_payment_pct is not None:
        loan_amt = p.price * (1 - down)
        net_sale -= loan_amt

    cashflows[-1] += net_sale

    irr = _irr(cashflows)
    npv = _npv(0.10, cashflows)  # 10% default discount rate (can be parameterized later)
    return {"cashflows": cashflows, "irr": irr, "npv": npv, "exit_value": exit_value, "net_sale": net_sale}


def parse_comps(avm: dict | None) -> _pd.DataFrame:
    if not avm or not isinstance(avm, dict):
        return _pd.DataFrame([])
    # RentCast AVM responses often include comps arrays; we try several keys.
    for key in ["comparables", "comps", "comparablesSale", "comparablesRent", "comparables_sales", "comparables_rent"]:
        comps = avm.get(key)
        if isinstance(comps, list) and comps:
            try:
                df = _pd.DataFrame(comps)
                return df
            except Exception:
                return _pd.DataFrame([])
    # Sometimes nested
    for key in ["comparableProperties", "comparablePropertiesSale", "comparablePropertiesRent"]:
        comps = _safe_get(avm, key, default=None)
        if isinstance(comps, list) and comps:
            try:
                return _pd.DataFrame(comps)
            except Exception:
                return _pd.DataFrame([])
    return _pd.DataFrame([])

def sensitivity_matrix(p: PropertyData, base_nums: dict, included: list[str], rate_env: str,
                       rent_shocks: list[float], rate_shocks: list[float]) -> tuple[_pd.DataFrame, _pd.DataFrame]:
    """Returns (score_df, irr_df) with rows=rent shocks, cols=rate shocks."""
    score_rows = []
    irr_rows = []
    for rs in rent_shocks:
        score_row = {"rent_shock": rs}
        irr_row = {"rent_shock": rs}
        for irs in rate_shocks:
            # clone property and apply shocks
            pp = PropertyData(**asdict(p))
            if pp.monthly_rent is not None:
                pp.monthly_rent = pp.monthly_rent * (1 + rs)
            if pp.interest_rate_pct is not None:
                pp.interest_rate_pct = max(0.0, pp.interest_rate_pct + (irs*100))  # irs is in decimal
            nums = compute_numbers(pp)
            weights = get_base_weights(rate_env)
            metrics = available_metrics(pp, nums, included)
            base_score, _nw = normalized_score(metrics, weights)
            flags = ai_flags(pp, nums, included)
            penalty = ai_penalty(flags)
            killed = kill_switch(nums, pp, included)
            final_score = max(base_score * (1 - penalty), 0)
            score_row[f"rate_{irs:+.2%}"] = round(final_score, 1)

            # IRR (if advanced assumptions exist in session)
            hold_years = int(st.session_state.get("adv_hold_years", 5))
            rg = float(st.session_state.get("adv_rent_growth", 0.03))
            eg = float(st.session_state.get("adv_expense_growth", 0.03))
            appr = float(st.session_state.get("adv_appreciation", 0.03))
            sc = float(st.session_state.get("adv_sale_cost_pct", 0.07))
            use_exit_cap = bool(st.session_state.get("adv_use_exit_cap", False))
            exit_cap = float(st.session_state.get("adv_exit_cap_rate", 0.065)) if use_exit_cap else None
            model = project_cashflows(pp, nums, hold_years, rg, eg, appr, sc, exit_cap_rate=exit_cap)
            irr = model.get("irr")
            irr_row[f"rate_{irs:+.2%}"] = round(irr*100, 2) if irr is not None else None

            # Add a small confidence penalty for extreme shocks (optional)
        score_rows.append(score_row)
        irr_rows.append(irr_row)

    score_df = _pd.DataFrame(score_rows).set_index("rent_shock")
    irr_df = _pd.DataFrame(irr_rows).set_index("rent_shock")
    return score_df, irr_df

def get_base_weights(rate_env: str) -> Dict[str, float]:
    if rate_env.upper() == "HIGH":
        return {"cashflow": 0.32, "downside": 0.25, "location": 0.12, "yield": 0.10, "liquidity": 0.10, "optionality": 0.06, "ai_risk": 0.05}
    return {"cashflow": 0.28, "downside": 0.20, "location": 0.12, "yield": 0.15, "liquidity": 0.10, "optionality": 0.10, "ai_risk": 0.05}

def compute_numbers(p: PropertyData) -> Dict[str, Optional[float]]:
    nums: Dict[str, Optional[float]] = {"loan_payment": None, "noi_year": None, "cap_rate": None, "coc_return": None, "dscr_stress": None, "cash_flow_month": None}

    if p.monthly_rent is not None and p.monthly_expenses is not None:
        vac = p.vacancy_rate if p.vacancy_rate is not None else 0.08
        eff_rent = p.monthly_rent * (1 - vac)
        noi_month = eff_rent - p.monthly_expenses
        nums["noi_year"] = noi_month * 12
        if p.price is not None and p.price > 0:
            nums["cap_rate"] = nums["noi_year"] / p.price

    if p.price is not None and p.down_payment_pct is not None and p.interest_rate_pct is not None and p.term_years is not None:
        loan_amount = p.price * (1 - p.down_payment_pct / 100)
        pay = monthly_payment(loan_amount, p.interest_rate_pct, int(p.term_years))
        nums["loan_payment"] = pay

        if nums["noi_year"] is not None:
            noi_month = nums["noi_year"] / 12
            nums["cash_flow_month"] = noi_month - pay
            cash_flow_year = (nums["cash_flow_month"] or 0) * 12
            cash_invested = p.price * (p.down_payment_pct / 100)
            if cash_invested > 0:
                nums["coc_return"] = cash_flow_year / cash_invested

        if p.monthly_rent is not None and p.monthly_expenses is not None:
            vac = p.vacancy_rate if p.vacancy_rate is not None else 0.08
            stressed_rent = p.monthly_rent * 0.80 * (1 - vac)
            stressed_noi_m = stressed_rent - p.monthly_expenses
            nums["dscr_stress"] = stressed_noi_m / max(pay, 1.0)

    return nums

def compute_price_change(p: PropertyData) -> Tuple[Optional[float], Optional[float]]:
    if p.price is None or p.last_sale_price is None or p.last_sale_price <= 0:
        return None, None
    abs_change = p.price - p.last_sale_price
    pct_change = abs_change / p.last_sale_price
    return pct_change, abs_change

def ai_flags(p: PropertyData, nums: Dict[str, Optional[float]], included: List[str]) -> List[str]:
    flags: List[str] = []
    if "Rent & Price" in included and p.monthly_rent is not None and p.price is not None and p.price > 0:
        gross_yield = (p.monthly_rent * 12) / p.price
        if gross_yield > 0.14:
            flags.append("Rent-to-price looks aggressive (verify comps).")
    if "Vacancy" in included and p.vacancy_rate is not None and p.vacancy_rate < 0.05:
        flags.append("Vacancy assumption looks optimistic.")
    if "Expenses" in included and p.monthly_expenses is not None and p.monthly_rent is not None and p.monthly_expenses < (p.monthly_rent * 0.20):
        flags.append("Expenses might be understated.")
    if "Yield" in included and nums.get("cap_rate") is not None and (nums["cap_rate"] or 0) < 0.045:
        flags.append("Low cap rate; deal relies on appreciation/execution.")
    if "Regulation" in included and p.rent_regulation_risk:
        flags.append("Regulatory pressure risk.")
    return flags

def ai_penalty(flags: List[str]) -> float:
    base = 0.0
    for f in flags:
        if "aggressive" in f:
            base += 0.06
        elif "Vacancy" in f:
            base += 0.08
        elif "Expenses" in f:
            base += 0.06
        elif "Low cap" in f:
            base += 0.06
        elif "Regulatory" in f:
            base += 0.20
    return min(base, 0.35)

def available_metrics(p: PropertyData, nums: Dict[str, Optional[float]], included: List[str]) -> Dict[str, float]:
    metrics: Dict[str, float] = {}

    if "Financing" in included and nums.get("dscr_stress") is not None:
        dscr = float(nums["dscr_stress"] or 0)
        metrics["cashflow"] = max(0.0, min(dscr / 1.50, 1.0))

    if "Downside" in included and p.replacement_cost is not None and p.price is not None and p.price > 0:
        metrics["downside"] = max(0.0, min((p.replacement_cost / p.price) / 1.20, 1.0))

    if "Location" in included and p.job_diversity_index is not None:
        metrics["location"] = max(0.0, min(float(p.job_diversity_index), 1.0))

    if "Yield" in included and nums.get("cap_rate") is not None:
        cap = float(nums["cap_rate"] or 0)
        metrics["yield"] = max(0.0, min(cap / 0.10, 1.0))

    if "Liquidity" in included and p.days_on_market is not None:
        metrics["liquidity"] = max(0.0, 1 - (float(p.days_on_market) / 180.0))

    if "Optionality" in included:
        metrics["optionality"] = 0.60

    metrics["ai_risk"] = 1.0
    return metrics

def normalized_score(metrics: Dict[str, float], weights: Dict[str, float]) -> Tuple[float, Dict[str, float]]:
    present = {k: weights.get(k, 0.0) for k in metrics.keys()}
    denom = sum(present.values()) or 1.0
    norm_w = {k: (present[k] / denom) for k in present.keys()}
    score_val = sum(metrics[k] * norm_w[k] for k in metrics.keys()) * 100
    return score_val, norm_w

def confidence_from_coverage(metrics: Dict[str, float], included: List[str]) -> float:
    keys = set(metrics.keys())
    base = 0.35 + 0.10 * min(len(included) / 7.0, 1.0)
    if "cashflow" in keys: base += 0.18
    if "yield" in keys: base += 0.14
    if "downside" in keys: base += 0.10
    if "liquidity" in keys: base += 0.05
    if "location" in keys: base += 0.05
    return max(0.35, min(base, 0.95))

def kill_switch(nums: Dict[str, Optional[float]], p: PropertyData, included: List[str]) -> bool:
    if "Financing" in included and nums.get("dscr_stress") is not None and (nums["dscr_stress"] or 0) < 1.0:
        return True
    if "Regulation" in included and p.rent_regulation_risk:
        return True
    if "Liquidity" in included and p.days_on_market is not None and p.days_on_market > 180:
        return True
    return False

def grade(score_val: float, killed: bool) -> Tuple[str, str]:
    if killed:
        return "F", "PASS"
    if score_val >= 90: return "A", "STRONG BUY"
    if score_val >= 80: return "B", "BUY"
    if score_val >= 70: return "C", "WATCH"
    if score_val >= 60: return "D", "SPECULATIVE"
    return "F", "PASS"

def narrative(p: PropertyData, nums: Dict[str, Optional[float]], flags: List[str], included: List[str]) -> Tuple[List[str], List[str]]:
    strengths: List[str] = []
    risks: List[str] = flags[:] if flags else []

    if "Financing" in included and nums.get("dscr_stress") is not None and (nums["dscr_stress"] or 0) >= 1.25:
        strengths.append("Strong stress-tested coverage (DSCR ≥ 1.25).")
    if "Yield" in included and nums.get("cap_rate") is not None and (nums["cap_rate"] or 0) >= 0.07:
        strengths.append("Healthy cap rate relative to price and expenses.")
    if "Downside" in included and p.replacement_cost is not None and p.price is not None and p.replacement_cost >= p.price:
        strengths.append("Downside buffer: at/below replacement cost.")
    if "Liquidity" in included and p.days_on_market is not None and p.days_on_market <= 45:
        strengths.append("Liquidity profile looks solid (faster exit).")

    if not strengths:
        strengths.append("Neutral strength profile; upside depends on better data and execution.")
    if not risks:
        risks.append("No major risk flags detected with the selected inputs.")
    return strengths[:4], risks[:5]

def build_pdf(path: str, p: PropertyData, nums: Dict[str, Optional[float]], result: Dict[str, Any],
              strengths: List[str], risks: List[str], data_notes: List[str], included: List[str], price_change: Tuple[Optional[float], Optional[float]]):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=LETTER)
    story: List[Any] = []
    story.append(Paragraph(f"{APP_NAME} — Underwriting Report", styles["Title"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>Address:</b> {p.address}", styles["Normal"]))
    story.append(Paragraph(f"<b>Grade:</b> {result['grade']} &nbsp;&nbsp; <b>Score:</b> {result['score']:.1f} &nbsp;&nbsp; <b>Verdict:</b> {result['verdict']}", styles["Normal"]))
    story.append(Paragraph(f"<b>Confidence:</b> {result['confidence']*100:.0f}% &nbsp;&nbsp; <b>Kill Switch:</b> {'Yes' if result['kill_switch'] else 'No'}", styles["Normal"]))
    story.append(Spacer(1, 10))

    rows = [["Included Inputs", ", ".join(included) if included else "—"]]
    story.append(Table(rows, hAlign="LEFT"))
    story.append(Spacer(1, 10))

    data = [["Metric", "Value"]]
    if p.price is not None: data.append(["Price", f"${p.price:,.0f}"])
    if p.monthly_rent is not None: data.append(["Monthly Rent", f"${p.monthly_rent:,.0f}"])
    if p.monthly_expenses is not None: data.append(["Monthly Expenses", f"${p.monthly_expenses:,.0f}"])
    if p.vacancy_rate is not None: data.append(["Vacancy Rate", f"{p.vacancy_rate*100:.1f}%"])
    if nums.get("loan_payment") is not None: data.append(["Loan Payment (est.)", f"${nums['loan_payment']:,.0f}"])
    if nums.get("noi_year") is not None: data.append(["NOI (annual)", f"${nums['noi_year']:,.0f}"])
    if nums.get("cap_rate") is not None: data.append(["Cap Rate", f"{(nums['cap_rate'] or 0)*100:.2f}%"])
    if nums.get("coc_return") is not None: data.append(["Cash-on-Cash", f"{(nums['coc_return'] or 0)*100:.2f}%"])
    if nums.get("dscr_stress") is not None: data.append(["Stress DSCR (rent -20%)", f"{nums['dscr_stress']:.2f}"])
    if p.replacement_cost is not None: data.append(["Replacement Cost", f"${p.replacement_cost:,.0f}"])
    if p.days_on_market is not None: data.append(["Days on Market", str(p.days_on_market)])
    if p.job_diversity_index is not None: data.append(["Job Diversity Index", f"{p.job_diversity_index:.2f}"])
    if p.last_sale_price is not None: data.append(["Last Sold Price", f"${p.last_sale_price:,.0f}"])
    if p.last_sale_date is not None: data.append(["Last Sold Date", str(p.last_sale_date)])

    pct, abs_chg = price_change
    if pct is not None and abs_chg is not None:
        data.append(["Price Change vs Last Sale", f"{pct*100:.2f}% ({abs_chg:,.0f})"])

    table = Table(data, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("PADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Top Strengths", styles["Heading2"]))
    for s in strengths:
        story.append(Paragraph(f"• {s}", styles["Normal"]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Top Risks / Flags", styles["Heading2"]))
    for r in risks:
        story.append(Paragraph(f"• {r}", styles["Normal"]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Data Notes", styles["Heading2"]))
    for n in data_notes:
        story.append(Paragraph(f"• {n}", styles["Normal"]))

    story.append(Spacer(1, 10))
    story.append(Paragraph("Disclaimer: Informational only, not financial advice. Verify all inputs and assumptions.", styles["Normal"]))
    doc.build(story)

def render_paywall():
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### Upgrade to Pro")
    st.write("You’ve used your free credits. Upgrade for unlimited analyses and saved history.")
    pay_link = st.secrets.get("STRIPE_PAYMENT_LINK_URL", "")
    if pay_link:
        st.link_button("Subscribe (Stripe)", pay_link)
    else:
        st.info("Add STRIPE_PAYMENT_LINK_URL in Streamlit secrets to enable payments.")
    st.caption("Next upgrade: Stripe webhooks to auto-unlock accounts after checkout.")
    st.markdown("</div>", unsafe_allow_html=True)

def demo_admin_unlock(email: str):
    unlock_code = st.secrets.get("ADMIN_UNLOCK_CODE", "")
    with st.expander("Admin (demo only)", expanded=False):
        st.caption("Manual unlock during testing if webhooks aren’t added yet.")
        code = st.text_input("Admin unlock code", type="password", key="admin_code")
        if st.button("Unlock this account"):
            if unlock_code and code == unlock_code:
                set_paid(email, 1)
                st.success("Unlocked. Refresh the page.")
            else:
                st.error("Invalid unlock code.")

st.markdown(
    f"""
    <div class="aire-top">
      <div class="aire-title">{APP_NAME} Terminal</div>
      <div class="aire-sub">{APP_TAGLINE} • Flexible inputs • Audit trail • No scraping</div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.write("")

with st.sidebar:
    st.markdown(f"## {APP_NAME}")
    st.caption("Terminal layout • Faster workflow • Saved history")
    page = st.radio("Navigate", ["Terminal", "Templates", "Analytics", "History", "Account", "About", "Market", "Screener", "Watchlist", "Alerts", "Portfolio"], index=0)
    st.divider()
    st.caption("Status")
    st.write(f"Estated: {'✅' if bool(st.secrets.get('ESTATED_TOKEN','')) else '❌'}")
    st.write(f"ATTOM: {'✅' if bool(st.secrets.get('ATTOM_APIKEY','')) else '❌'}")
    st.write(f"Stripe: {'✅' if bool(st.secrets.get('STRIPE_PAYMENT_LINK_URL','')) else '❌'}")

st.session_state.setdefault("email", "")
c1, c2, c3 = st.columns([2.2, 1.2, 1.2])
with c1:
    email_in = st.text_input("Email", value=st.session_state["email"], placeholder="you@example.com")
    if email_in:
        st.session_state["email"] = email_in
with c2:
    rate_env = st.selectbox("Rate environment", ["HIGH", "NORMAL"], index=0)
with c3:
    st.caption("")
    st.markdown('<span class="small">Tip: start with fewer inputs, then tighten assumptions.</span>', unsafe_allow_html=True)

if not st.session_state["email"]:
    st.info("Enter your email to continue.")
    st.stop()

user = get_user(st.session_state["email"])

if page == "Terminal":
    if (not user["paid"]) and (user["credits"] < CREDIT_COST_PER_ANALYSIS):
        render_paywall()
        demo_admin_unlock(st.session_state["email"])
        st.stop()

    left, mid, right = st.columns([1.25, 1.6, 1.15], gap="large")

    with left:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### 1) Deal Loader")
        listing_url = st.text_input("Listing URL (optional)", placeholder="https://www.zillow.com/...")
        auto_addr = extract_address_from_url(listing_url) if listing_url else None
        address = st.text_input("Property address", value=(auto_addr or ""), placeholder="123 Main St, City, ST 12345")

        st.write("")
        st.markdown("### 2) Choose Inputs")
        modules = ["Rent & Price", "Expenses", "Vacancy", "Financing", "Yield", "Downside", "Liquidity", "Location", "Regulation", "Last Sale", "Optionality"]
        default_modules = st.session_state.get("tpl_included") or ["Rent & Price", "Expenses", "Vacancy", "Financing", "Yield", "Liquidity", "Last Sale"]
        included = st.multiselect("Include in report + scoring", modules, default=default_modules)

        st.write("")
        b1, b2 = st.columns(2)
        with b1:
            do_autofill = st.button("✨ Auto-fill (real data)")
        with b2:
            st.caption("Uses Estated/ATTOM if configured.")

        data_notes = st.session_state.get("data_notes", ["Manual mode."])
        prefill = st.session_state.get("prefill", {})

        if do_autofill and address.strip():
            with st.spinner("Pulling property data..."):
                prefill, data_notes = smart_prefill(address.strip())
            st.session_state["prefill"] = prefill
            st.session_state["data_notes"] = data_notes

        st.write("")
        if user["paid"]:
            st.markdown('<span class="pill2">PRO</span><span class="pill">Unlimited</span>', unsafe_allow_html=True)
        else:
            st.markdown(f'<span class="warn">FREE</span><span class="pill">Credits: {user.get("credits",0)}</span>', unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    with mid:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### Inputs Panel")

        st.markdown("#### Advanced Assumptions")
        adv = st.checkbox("Enable advanced underwriting (IRR / scenarios)", value=False)
        hold_years = 5
        rent_growth = 0.03
        expense_growth = 0.03
        appreciation = 0.03
        sale_cost_pct = 0.07
        exit_cap = None
        discount_rate = 0.10
        if adv:
            a1,a2,a3 = st.columns(3)
            hold_years = a1.number_input("Hold (years)", 1, 30, 5, 1)
            discount_rate = a2.number_input("Discount rate (for NPV)", 0.00, 0.30, 0.10, 0.01)
            sale_cost_pct = a3.number_input("Sale costs (%)", 0.00, 0.20, 0.07, 0.01)
            b1,b2,b3 = st.columns(3)
            rent_growth = b1.number_input("Rent growth (%)", 0.00, 0.25, 0.03, 0.005)
            expense_growth = b2.number_input("Expense growth (%)", 0.00, 0.25, 0.03, 0.005)
            appreciation = b3.number_input("Appreciation (%)", 0.00, 0.25, 0.03, 0.005)
            c1,c2 = st.columns(2)
            use_exit_cap = c1.checkbox("Use exit cap rate instead of appreciation", value=False)
            exit_cap = c2.number_input("Exit cap rate (%)", 0.0, 20.0, 6.5, 0.1) if use_exit_cap else None


        def pv(key, default):
            # priority: explicit session state (templates/Market push) -> prefill -> default
            if key in st.session_state and st.session_state.get(key) not in (None, ""):
                return st.session_state.get(key)
            v = prefill.get(key, None)
            return default if v is None else v

        price = monthly_rent = monthly_expenses = vacancy_rate = None
        down_payment_pct = interest_rate_pct = term_years = None
        replacement_cost = days_on_market = job_div = None
        reg_risk = False
        last_sale_price = last_sale_date = None

        if "Rent & Price" in included:
            a, b = st.columns(2)
            price = a.number_input("Price ($)", min_value=0.0, value=float(pv("price", 400000.0)), step=1000.0)
            monthly_rent = b.number_input("Monthly rent ($)", min_value=0.0, value=3000.0, step=50.0)

        if "Expenses" in included:
            monthly_expenses = st.number_input("Monthly expenses ($)", min_value=0.0, value=1100.0, step=50.0)

        if "Vacancy" in included:
            vacancy_rate = st.slider("Vacancy rate", min_value=0.0, max_value=0.25, value=0.08, step=0.01)

        if "Financing" in included:
            d1, d2, d3 = st.columns(3)
            down_payment_pct = d1.number_input("Down payment (%)", min_value=0.0, max_value=100.0, value=20.0, step=1.0)
            interest_rate_pct = d2.number_input("Interest rate (%)", min_value=0.0, max_value=30.0, value=7.25, step=0.05)
            term_years = d3.number_input("Term (years)", min_value=1, max_value=40, value=30, step=1)

        if "Downside" in included:
            replacement_cost = st.number_input("Replacement cost ($)", min_value=0.0, value=float(pv("replacement_cost", 450000.0)), step=1000.0)

        if "Liquidity" in included:
            days_on_market = st.number_input("Days on market", min_value=0, value=int(pv("days_on_market", 45)), step=1)

        if "Location" in included:
            job_div = st.slider("Job diversity (0–1)", min_value=0.0, max_value=1.0, value=0.74, step=0.01)

        if "Regulation" in included:
            reg_risk = st.checkbox("Rent regulation risk", value=False)

        if "Last Sale" in included:
            e1, e2 = st.columns(2)
            last_sale_price = e1.number_input("Last sold price ($)", min_value=0.0, value=float(pv("last_sale_price", 0.0) or 0.0), step=1000.0)
            last_sale_date = e2.text_input("Last sold date (YYYY-MM-DD)", value=str(pv("last_sale_date", "") or ""))
            if last_sale_price == 0.0:
                last_sale_price = None
            if last_sale_date.strip() == "":
                last_sale_date = None

        st.write("")
        st.caption("Only selected inputs are used for scoring. Missing fields reduce confidence but don’t block the run.")
        st.markdown("</div>", unsafe_allow_html=True)

        st.write("")
        st.markdown('<div class="card2">', unsafe_allow_html=True)
        st.markdown("### Data Notes")
        for n in data_notes:
            st.write(f"• {n}")
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### Output Console")

        run = st.button("✅ Run AIRE Score", type="primary")
        if run:
            if not spend_credit(st.session_state["email"], CREDIT_COST_PER_ANALYSIS):
                st.error("No credits remaining.")
                st.markdown("</div>", unsafe_allow_html=True)
                render_paywall()
                st.stop()

            p = PropertyData(
                address=address.strip() or "Unknown address",
                price=price,
                monthly_rent=monthly_rent,
                monthly_expenses=monthly_expenses,
                vacancy_rate=vacancy_rate,
                down_payment_pct=down_payment_pct,
                interest_rate_pct=interest_rate_pct,
                term_years=int(term_years) if term_years is not None else None,
                replacement_cost=replacement_cost,
                days_on_market=int(days_on_market) if days_on_market is not None else None,
                job_diversity_index=job_div,
                rent_regulation_risk=bool(reg_risk) if "Regulation" in included else None,
                last_sale_price=last_sale_price,
                last_sale_date=last_sale_date,
            )

            nums = compute_numbers(p)
            weights = get_base_weights(rate_env)
            metrics = available_metrics(p, nums, included)
            base_score, norm_w = normalized_score(metrics, weights)

            flags = ai_flags(p, nums, included)
            penalty = ai_penalty(flags)

            killed = kill_switch(nums, p, included)
            final_score = max(base_score * (1 - penalty), 0)

            conf = confidence_from_coverage(metrics, included)
            g, verdict = grade(final_score, killed)

            pct_chg, abs_chg = compute_price_change(p)
            strengths, risks = narrative(p, nums, flags, included)

            k1, k2, k3 = st.columns(3)
            k1.markdown('<div class="kpi">', unsafe_allow_html=True); k1.metric("Grade", g); k1.markdown('</div>', unsafe_allow_html=True)
            k2.markdown('<div class="kpi">', unsafe_allow_html=True); k2.metric("Score", f"{final_score:.1f}"); k2.markdown('</div>', unsafe_allow_html=True)
            k3.markdown('<div class="kpi">', unsafe_allow_html=True); k3.metric("Confidence", f"{conf*100:.0f}%"); k3.markdown('</div>', unsafe_allow_html=True)

            st.write("")
            st.markdown("**Key Metrics**")
            st.write(f"• NOI (annual): {fmt_money(nums.get('noi_year'))}")
            st.write(f"• Cap rate: {fmt_pct(nums.get('cap_rate'), 2)}")
            st.write(f"• CoC: {fmt_pct(nums.get('coc_return'), 2)}")
            dscr_val = nums.get("dscr_stress")
            dscr_str = "—" if dscr_val is None else f"{dscr_val:.2f}"
            st.write(f"• Stress DSCR: {dscr_str}")
            if pct_chg is not None and abs_chg is not None:
                st.write(f"• Price change vs last sale: {pct_chg*100:.2f}% ({fmt_money(abs_chg)})")

            st.write("")
            st.markdown("**Verdict**")
            st.write(f"**{verdict}**")

            st.write("")
            st.markdown("**Strengths**")
            for s in strengths:
                st.write(f"• {s}")
            st.write("")
            st.markdown("**Risks / Flags**")
            for r in risks:
                st.write(f"• {r}")

            result = {
                "grade": g,
                "verdict": verdict,
                "score": float(final_score),
                "confidence": float(conf),
                "kill_switch": bool(killed),
                "dscr": float(nums["dscr_stress"] or 0) if nums.get("dscr_stress") is not None else 0.0,
                "noi": float(nums["noi_year"] or 0) if nums.get("noi_year") is not None else 0.0,
                "cap_rate": float(nums["cap_rate"] or 0) if nums.get("cap_rate") is not None else 0.0,
                "coc_return": float(nums["coc_return"] or 0) if nums.get("coc_return") is not None else 0.0,
                "price_change_pct": float(pct_chg) if pct_chg is not None else None,
                "ai_penalty": float(penalty),
                "rate_env": rate_env,
            }

            payload = {
                "property": asdict(p),
                "numbers": nums,
                "metrics": metrics,
                "base_weights": weights,
                "normalized_weights": norm_w,
                "flags": flags,
                "data_notes": data_notes,
                "included_inputs": included,
                "result": result,
            }

            save_analysis(st.session_state["email"], p.address, listing_url, result, payload)

            pdf_name = f"AIRE_Report_{int(time.time())}.pdf"
            build_pdf(pdf_name, p, nums, result, strengths, risks, data_notes, included, (pct_chg, abs_chg))
            with open(pdf_name, "rb") as f:
                st.download_button("⬇️ Download PDF report", f, file_name=pdf_name, mime="application/pdf")

            with st.expander("Audit Trail (for pros)", expanded=False):
                st.json(payload)

        st.markdown("</div>", unsafe_allow_html=True)

    st.write("")
    st.markdown('<div class="small">Disclaimer: AIRE™ is informational only and not financial advice. No Zillow scraping; URL is used only to infer an address.</div>', unsafe_allow_html=True)

elif page == "History":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### History")
    st.caption("Saved analyses for your account.")
    items = fetch_analyses(st.session_state["email"], limit=50)
    if not items:
        st.info("No analyses yet. Use Terminal to run one.")
        st.markdown("</div>", unsafe_allow_html=True)
        st.stop()

    header = st.columns([2.4, 0.6, 1.0, 1.0, 1.0, 1.0])
    header[0].markdown("**Address / Time**")
    header[1].markdown("**G**")
    header[2].markdown("**Score**")
    header[3].markdown("**Conf**")
    header[4].markdown("**DSCR**")
    header[5].markdown("**Cap**")
    st.divider()

    for it in items[:25]:
        cols = st.columns([2.4, 0.6, 1.0, 1.0, 1.0, 1.0])
        cols[0].write(f"**{it['address'] or 'Unknown'}**\n{ts_to_str(it['created_at'])}")
        cols[1].write(f"**{it['grade']}**")
        cols[2].write(f"{it['score']:.1f}")
        cols[3].write(f"{(it['confidence'] or 0)*100:.0f}%")
        cols[4].write(f"{it['dscr']:.2f}" if it['dscr'] is not None else "—")
        cols[5].write(f"{(it['cap_rate'] or 0)*100:.2f}%" if it['cap_rate'] is not None else "—")
        st.divider()

    st.markdown("</div>", unsafe_allow_html=True)

elif page == "Account":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### Account")
    st.write(f"Signed in as: **{st.session_state['email']}**")
    if user["paid"]:
        st.markdown('<span class="pill2">PRO</span><span class="pill">Unlimited</span>', unsafe_allow_html=True)
    else:
        st.markdown(f'<span class="warn">FREE</span><span class="pill">Credits: {user.get("credits",0)}</span>', unsafe_allow_html=True)

    st.write("")
    st.markdown("**Upgrade**")
    pay_link = st.secrets.get("STRIPE_PAYMENT_LINK_URL", "")
    if pay_link:
        st.link_button("Subscribe (Stripe)", pay_link)
    else:
        st.info("Add STRIPE_PAYMENT_LINK_URL in Streamlit secrets to enable payments.")

    st.write("")
    demo_admin_unlock(st.session_state["email"])
    st.markdown("</div>", unsafe_allow_html=True)


elif page == "Market":
    st.markdown("### 📈 Market Intelligence")
    st.caption("Real data panels (optional): RentCast market stats, AVMs, and macro rate context. If you haven't added API keys, you can still use this page manually.")
    colA, colB = st.columns([1,1])
    with colA:
        one_line = st.text_input("Address (one-line)", value=st.session_state.get("property_address_one_line",""))
        zip_guess = _extract_zip(one_line) or ""
        zip_code = st.text_input("Zip code (for market stats)", value=zip_guess)
        st.markdown("**Data sources**")
        st.write(f"• RentCast key: {'✅' if RENTCAST_APIKEY else '—'}")
        st.write(f"• FRED key: {'✅' if FRED_API_KEY else '—'}")
        run = st.button("Load market panels", use_container_width=True)
    with colB:
        st.markdown("**What you get here**")
        st.write("• Zip-level sale + rental market trends")
        st.write("• Property value estimate (AVM) + sales comps (if available)")
        st.write("• Property rent estimate (AVM) + rental comps (if available)")
        st.write("• Macro: 30-year mortgage rate trend (FRED)")

    if run and one_line:
        # Macro rates
        st.markdown("#### Mortgage rates (macro)")
        df_rate = fred_series_observations("MORTGAGE30US", limit=156)
        if df_rate is not None:
            st.line_chart(df_rate.set_index("date")["value"])
            st.caption("30-year fixed mortgage rate (weekly).")
        else:
            st.info("Add `FRED_API_KEY` in Streamlit secrets to show the mortgage-rate chart.")

        # Market stats
        st.markdown("#### Zip market snapshot")
        mk = rentcast_market(zip_code) if zip_code else None
        if mk:
            sale = mk.get("saleData", {})
            rent = mk.get("rentalData", {})
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Median sale price", f"${sale.get('medianPrice', sale.get('medianSalePrice','—'))}")
            c2.metric("Sale DOM (avg)", f"{sale.get('avgDaysOnMarket','—')}")
            c3.metric("Median rent", f"${rent.get('medianRent', rent.get('medianPrice','—'))}")
            c4.metric("Rental DOM (avg)", f"{rent.get('avgDaysOnMarket','—')}")
            # History charts (best-effort)
            hist = mk.get("history", None) or sale.get("history", None) or rent.get("history", None)
            if isinstance(hist, list) and hist:
                try:
                    df = _pd.DataFrame(hist)
                    # find a likely date column and a likely series column
                    date_col = None
                    for dc in ["date","month","period","timestamp"]:
                        if dc in df.columns:
                            date_col = dc
                            break
                    if date_col:
                        df[date_col] = _pd.to_datetime(df[date_col])
                        df = df.sort_values(date_col)
                        # pick numeric columns
                        num_cols = [c for c in df.columns if c != date_col and _pd.api.types.is_numeric_dtype(df[c])]
                        if num_cols:
                            st.line_chart(df.set_index(date_col)[num_cols[:3]])
                except Exception:
                    pass
        else:
            st.info("Market stats require `RENTCAST_APIKEY` + a valid zip code.")

        # Property record (for last sale & taxes etc)
        st.markdown("#### Property record (facts + last sale)")
        pr = rentcast_property_record(one_line)
        if pr:
            last_price, last_date = _infer_last_sale(pr)
            c1, c2, c3 = st.columns(3)
            c1.metric("Last sold price", f"${last_price:,}" if isinstance(last_price,(int,float)) else (str(last_price) if last_price else "—"))
            c2.metric("Last sold date", str(last_date) if last_date else "—")
            c3.metric("Property type", pr.get("propertyType","—"))
            with st.expander("Raw property record (JSON)"):
                st.json(pr)
        else:
            st.info("Property record requires `RENTCAST_APIKEY`.")

        # AVMs
        st.markdown("#### AVM panels")
        avm_val = rentcast_value_avm(one_line)
        avm_rent = rentcast_rent_avm(one_line)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Value (AVM)**")
            if avm_val and isinstance(avm_val, dict):
                st.metric("Estimated value", f"${int(avm_val.get('price',0)):,}" if avm_val.get("price") else "—")
                st.caption("Includes comps when available.")
                with st.expander("Value AVM (JSON)"):
                    st.json(avm_val)
            else:
                st.info("Value AVM requires `RENTCAST_APIKEY`.")
        with c2:
            st.markdown("**Rent (AVM)**")
            if avm_rent and isinstance(avm_rent, dict):
                st.metric("Estimated rent (monthly)", f"${int(avm_rent.get('rent',0)):,}" if avm_rent.get("rent") else "—")
                st.caption("Includes rental comps when available.")
                with st.expander("Rent AVM (JSON)"):
                    st.json(avm_rent)
            else:
                st.info("Rent AVM requires `RENTCAST_APIKEY`.")

        st.markdown("---")
        st.markdown("#### Push data into the Terminal")
        if st.button("Use these real-data estimates in my underwriting inputs", use_container_width=True):
            # Fill the main underwriting state if present
            if avm_val and avm_val.get("price"):
                st.session_state["price"] = float(avm_val["price"])
            if avm_rent and avm_rent.get("rent"):
                st.session_state["monthly_rent"] = float(avm_rent["rent"])
            if pr:
                lp, ld = _infer_last_sale(pr)
                if lp:
                    st.session_state["last_sold_price"] = float(lp) if isinstance(lp,(int,float)) else lp
                if ld:
                    st.session_state["last_sold_date"] = str(ld)
            if zip_code:
                st.session_state["zip_code"] = zip_code
            st.success("Loaded estimates into Terminal inputs. Go back to the Terminal page and run scoring.")

elif page == "Screener":
    st.markdown("### 🧮 Screener (batch grading)")
    st.caption("Paste a list of Zillow links or addresses. We'll parse what we can and generate a ranked table + export.")
    raw = st.text_area("One per line (Zillow URL or one-line address)", height=220, placeholder="https://www.zillow.com/homedetails/...\n123 Main St, City, ST 12345\n...")
    use_real = st.checkbox("Try RentCast to auto-fill rent/value/last sale (requires RENTCAST_APIKEY)", value=True)
    run = st.button("Run screener", type="primary", use_container_width=True)

    if run and raw.strip():
        items = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        rows = []
        prog = st.progress(0)
        for i, it in enumerate(items, start=1):
            prog.progress(i/len(items))
            # Use existing parser if present; else treat as address
            addr = it
            # If Zillow URL: keep as reference and attempt to extract address from query params if any
            # (We avoid scraping Zillow HTML for ToS reasons.)
            zurl = it if it.lower().startswith("http") else ""
            if zurl:
                # best effort: sometimes address is in URL slug; we can keep slug for display
                addr = zurl

            # Real data from RentCast (best-effort)
            price = None
            rent = None
            last_sale_price = None
            last_sale_date = None
            zip_code = _extract_zip(it) or ""
            if use_real and RENTCAST_APIKEY and not zurl:
                pr = rentcast_property_record(it)
                if pr:
                    lsp, lsd = _infer_last_sale(pr)
                    last_sale_price, last_sale_date = lsp, lsd
                avm_val = rentcast_value_avm(it)
                avm_r = rentcast_rent_avm(it)
                if avm_val and avm_val.get("price"):
                    price = avm_val.get("price")
                if avm_r and avm_r.get("rent"):
                    rent = avm_r.get("rent")

            # Minimal score proxy if full underwriting not filled:
            # Score uses what we have (price & rent), else defaults to 0 with low confidence.
            if price and rent and price > 0:
                grm = (price/12)/rent
                score = max(0, min(100, 100 - (grm*5)))  # rougher = higher GRM means worse
                confidence = 0.55
            else:
                score = 0
                confidence = 0.15

            grade = "F"
            if score >= 90: grade = "A"
            elif score >= 80: grade = "B"
            elif score >= 70: grade = "C"
            elif score >= 60: grade = "D"

            rows.append({
                "input": it,
                "grade": grade,
                "score": round(score,1),
                "confidence": int(confidence*100),
                "est_price": price,
                "est_rent": rent,
                "last_sale_price": last_sale_price,
                "last_sale_date": last_sale_date,
                "zip": zip_code,
                "ref_url": zurl,
            })

        df = _pd.DataFrame(rows).sort_values(["score","confidence"], ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"), "aire_screener.csv", "text/csv", use_container_width=True)

        st.info("Tip: For highest-accuracy batch underwriting, paste addresses (not Zillow links) so real-data providers can match them.")




elif page == "Watchlist":
    st.markdown("### ⭐ Watchlist")
    st.caption("Save properties you want to track. This is the foundation for Alerts + deal flow.")
    items = fetch_watchlist(st.session_state["email"])

    with st.expander("Add to watchlist", expanded=True):
        c1, c2 = st.columns([2,1])
        addr = c1.text_input("Address (one-line is best)", placeholder="123 Main St, City, ST 12345", key="wl_addr")
        url = c2.text_input("Listing URL (optional)", placeholder="https://...", key="wl_url")
        c3, c4, c5 = st.columns([1,1,2])
        target_grade = c3.selectbox("Target grade", ["A","B","C"], index=0, key="wl_target_g")
        target_score = c4.number_input("Target score", min_value=0.0, max_value=100.0, value=85.0, step=1.0, key="wl_target_s")
        notes = c5.text_input("Notes", placeholder="Why this deal is on your radar", key="wl_notes")
        if st.button("Add", type="primary", use_container_width=True):
            if addr.strip():
                add_watchlist_item(st.session_state["email"], addr.strip(), listing_url=url.strip(), zip_code=_extract_zip(addr.strip()) or "", target_grade=target_grade, target_score=float(target_score), notes=notes.strip())
                st.success("Added. Refreshing…")
                st.rerun()
            else:
                st.error("Add an address.")

    if not items:
        st.info("No watchlist items yet.")
        st.stop()

    st.markdown("#### Your watchlist")
    for it in items[:100]:
        with st.container():
            cols = st.columns([2.4, 1.0, 0.9, 0.7])
            cols[0].write(f"**{it['address']}**\n\n{it.get('notes','')}")
            cols[1].write(f"Target: **{it.get('target_grade','A')}** / **{it.get('target_score',85):.0f}+**")
            cols[2].write(f"Updated: {ts_to_str(it['updated_at'])}")
            pinned = cols[3].checkbox("Pin", value=bool(it.get("pinned",0)), key=f"pin_{it['id']}")
            if pinned != bool(it.get("pinned",0)):
                update_watchlist_item(it["id"], st.session_state["email"], pinned=int(pinned))
                st.rerun()

            b1, b2, b3 = st.columns([1,1,2])
            if b1.button("Edit", key=f"edit_{it['id']}"):
                st.session_state["edit_wl_id"] = it["id"]
            if b2.button("Delete", key=f"del_{it['id']}"):
                delete_watchlist_item(it["id"], st.session_state["email"])
                st.rerun()
            if b3.button("Run in Terminal", key=f"run_{it['id']}"):
                st.session_state["email"] = st.session_state["email"]
                st.session_state["property_address_one_line"] = it["address"]
                st.success("Loaded. Go to Terminal and click Auto-fill / Run.")
            st.divider()

    # Edit modal-style expander
    edit_id = st.session_state.get("edit_wl_id", None)
    if edit_id:
        current = next((x for x in items if x["id"] == edit_id), None)
        if current:
            with st.expander("Edit watchlist item", expanded=True):
                a = st.text_input("Address", value=current["address"], key="edit_addr")
                u = st.text_input("Listing URL", value=current.get("listing_url","") or "", key="edit_url")
                t1, t2 = st.columns(2)
                tg = t1.selectbox("Target grade", ["A","B","C"], index=["A","B","C"].index(current.get("target_grade","A")), key="edit_tg")
                ts = t2.number_input("Target score", min_value=0.0, max_value=100.0, value=float(current.get("target_score",85.0)), step=1.0, key="edit_ts")
                n = st.text_input("Notes", value=current.get("notes",""), key="edit_notes")
                if st.button("Save changes", type="primary"):
                    update_watchlist_item(edit_id, st.session_state["email"], address=a.strip(), listing_url=u.strip(), target_grade=tg, target_score=float(ts), notes=n.strip(), zip=_extract_zip(a.strip()) or "")
                    st.session_state["edit_wl_id"] = None
                    st.success("Saved.")
                    st.rerun()
                if st.button("Cancel"):
                    st.session_state["edit_wl_id"] = None
                    st.rerun()

elif page == "Alerts":
    st.markdown("### 🔔 Alerts")
    st.caption("One-click scan of your watchlist. No background jobs needed — you can run it anytime and it highlights 'actionable' deals.")
    items = fetch_watchlist(st.session_state["email"])
    if not items:
        st.info("Add properties to Watchlist first.")
        st.stop()

    # Default underwriting assumptions for alerts
    with st.expander("Alert underwriting defaults (used if data is missing)", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        default_vac = c1.slider("Vacancy", 0.0, 0.25, 0.08, 0.01)
        default_exp_ratio = c2.slider("Expense ratio (of rent)", 0.10, 0.70, 0.38, 0.01)
        default_dp = c3.slider("Down payment", 0.0, 1.0, 0.20, 0.01)
        default_rate = c4.number_input("Interest rate (%)", 0.0, 30.0, 7.25, 0.05)
        term_years = st.number_input("Term years", 1, 40, 30, 1)

    use_real = st.checkbox("Use real data (RentCast/Estated/ATTOM) when available", value=True)
    run = st.button("Run alert scan", type="primary", use_container_width=True)

    if run:
        rows = []
        prog = st.progress(0)
        for i, it in enumerate(items, start=1):
            prog.progress(i/len(items))
            address_one_line = it["address"]
            listing_url = it.get("listing_url","") or ""

            # Try real data
            est_price = None
            est_rent = None
            last_sale_price = None
            last_sale_date = None

            if use_real and RENTCAST_APIKEY:
                avm_val = rentcast_value_avm(address_one_line)
                avm_r = rentcast_rent_avm(address_one_line)
                pr = rentcast_property_record(address_one_line)

                if avm_val and isinstance(avm_val, dict) and avm_val.get("price"):
                    est_price = float(avm_val["price"])
                if avm_r and isinstance(avm_r, dict) and avm_r.get("rent"):
                    est_rent = float(avm_r["rent"])

                if pr:
                    lsp, lsd = _infer_last_sale(pr)
                    if lsp: last_sale_price = float(lsp) if isinstance(lsp,(int,float)) else None
                    if lsd: last_sale_date = str(lsd)

            if use_real and (not est_price or not last_sale_price):
                prefill, _notes = smart_prefill(address_one_line)
                if not est_price and prefill.get("price"):
                    est_price = float(prefill["price"])
                if not last_sale_price and prefill.get("last_sale_price"):
                    last_sale_price = float(prefill["last_sale_price"])
                if not last_sale_date and prefill.get("last_sale_date"):
                    last_sale_date = str(prefill["last_sale_date"])

            # Fill missing with assumptions so we can still compute a deal signal
            price = est_price
            rent = est_rent
            if price is None or rent is None:
                # can't compute; keep as low confidence
                score = 0.0
                conf = 0.15
                g = "F"
                verdict = "INSUFFICIENT DATA"
                cap = None
                coc = None
                dscr = None
            else:
                # Estimate expenses from ratio if unknown
                monthly_exp = rent * default_exp_ratio
                p = PropertyData(
                    address=address_one_line,
                    price=price,
                    monthly_rent=rent,
                    monthly_expenses=monthly_exp,
                    vacancy_rate=default_vac,
                    down_payment_pct=default_dp*100,
                    interest_rate_pct=float(default_rate),
                    term_years=int(term_years),
                    last_sale_price=last_sale_price,
                    last_sale_date=last_sale_date
                )
                nums = compute_numbers(p)
                weights = get_base_weights("HIGH")
                included = ["Rent & Price","Expenses","Vacancy","Financing","Yield","Last Sale","Liquidity","Optionality"]
                metrics = available_metrics(p, nums, included)
                base_score, _ = normalized_score(metrics, weights)
                flags = ai_flags(p, nums, included)
                penalty = ai_penalty(flags)
                killed = kill_switch(nums, p, included)
                score = max(base_score*(1-penalty), 0)
                conf = confidence_from_coverage(metrics, included)
                g, verdict = grade(score, killed)
                cap = nums.get("cap_rate")
                coc = nums.get("coc_return")
                dscr = nums.get("dscr_stress")

            # Actionable rule: meets target grade OR score threshold
            tscore = float(it.get("target_score",85.0))
            tgrade = it.get("target_grade","A")
            actionable = (score >= tscore) or (g <= tgrade and g in ["A","B","C"] and tgrade in ["A","B","C"] and ["A","B","C"].index(g) <= ["A","B","C"].index(tgrade))

            rows.append({
                "address": address_one_line,
                "grade": g,
                "score": round(float(score),1),
                "confidence": int(conf*100),
                "verdict": verdict,
                "cap_rate": (cap*100) if isinstance(cap,(int,float)) else None,
                "coc": (coc*100) if isinstance(coc,(int,float)) else None,
                "dscr": float(dscr) if isinstance(dscr,(int,float)) else None,
                "actionable": actionable,
                "target": f"{tgrade}/{tscore:.0f}+",
                "listing_url": listing_url
            })

        df = _pd.DataFrame(rows).sort_values(["actionable","score","confidence"], ascending=[False,False,False])
        st.dataframe(df, use_container_width=True, hide_index=True)

        actionable_count = int(df["actionable"].sum()) if "actionable" in df.columns else 0
        if actionable_count:
            st.success(f"{actionable_count} deals look actionable right now based on your targets.")
        else:
            st.info("No deals met your targets on this scan — tighten data or adjust targets.")

        st.download_button("Download alert table (CSV)", df.to_csv(index=False).encode("utf-8"), "aire_alerts.csv", "text/csv", use_container_width=True)

elif page == "Portfolio":
    st.markdown("### 🧾 Portfolio")
    st.caption("Track holdings and see aggregate risk/yield like a mini real-estate terminal.")
    items = fetch_portfolio(st.session_state["email"])

    with st.expander("Add property to portfolio", expanded=True):
        c1, c2 = st.columns([1.3, 1.7])
        name = c1.text_input("Nickname (required)", placeholder="Naples Duplex #1")
        address = c2.text_input("Address", placeholder="123 Main St, City, ST 12345")
        c3, c4, c5 = st.columns(3)
        units = c3.number_input("Units", 1, 500, 1, 1)
        purchase_price = c4.number_input("Purchase price ($)", 0.0, 50_000_000.0, 0.0, 1000.0)
        current_value = c5.number_input("Current value ($)", 0.0, 50_000_000.0, 0.0, 1000.0)

        c6, c7, c8 = st.columns(3)
        loan_balance = c6.number_input("Loan balance ($)", 0.0, 50_000_000.0, 0.0, 1000.0)
        ir = c7.number_input("Interest rate (%)", 0.0, 30.0, 0.0, 0.05)
        term = c8.number_input("Term years", 1, 40, 30, 1)

        c9, c10, c11 = st.columns(3)
        rent = c9.number_input("Monthly rent ($)", 0.0, 1_000_000.0, 0.0, 50.0)
        exp = c10.number_input("Monthly expenses ($)", 0.0, 1_000_000.0, 0.0, 50.0)
        vac = c11.slider("Vacancy", 0.0, 0.25, 0.08, 0.01)

        if st.button("Add to portfolio", type="primary", use_container_width=True):
            if not name.strip():
                st.error("Nickname is required.")
            else:
                add_portfolio_item(
                    st.session_state["email"],
                    name.strip(),
                    address=address.strip(),
                    units=int(units),
                    purchase_price=(purchase_price if purchase_price > 0 else None),
                    current_value=(current_value if current_value > 0 else None),
                    loan_balance=(loan_balance if loan_balance > 0 else None),
                    interest_rate_pct=(ir if ir > 0 else None),
                    term_years=int(term) if term else None,
                    monthly_rent=(rent if rent > 0 else None),
                    monthly_expenses=(exp if exp > 0 else None),
                    vacancy_rate=float(vac) if vac is not None else None,
                )
                st.success("Added.")
                st.rerun()

    if not items:
        st.info("No portfolio entries yet.")
        st.stop()

    # Portfolio analytics
    rows = []
    for it in items:
        p = PropertyData(
            address=it.get("address") or it.get("name"),
            price=it.get("current_value") or it.get("purchase_price"),
            monthly_rent=it.get("monthly_rent"),
            monthly_expenses=it.get("monthly_expenses"),
            vacancy_rate=it.get("vacancy_rate"),
            down_payment_pct=None,
            interest_rate_pct=it.get("interest_rate_pct"),
            term_years=int(it.get("term_years")) if it.get("term_years") else None
        )
        nums = compute_numbers(p)
        value = it.get("current_value") or it.get("purchase_price")
        noi = nums.get("noi_year")
        cap = (noi / value) if (noi is not None and value) else None

        rows.append({
            "name": it.get("name"),
            "address": it.get("address"),
            "value": value,
            "loan": it.get("loan_balance"),
            "noi": noi,
            "cap_rate": (cap*100) if isinstance(cap,(int,float)) else None,
            "cashflow_m": nums.get("cash_flow_month"),
            "dscr": nums.get("dscr_stress"),
            "updated": ts_to_str(it.get("updated_at", _now())),
            "id": it["id"]
        })

    df = _pd.DataFrame(rows)
    st.dataframe(df.drop(columns=["id"]), use_container_width=True, hide_index=True)

    # Aggregates
    total_value = float(df["value"].fillna(0).sum())
    total_loan = float(df["loan"].fillna(0).sum())
    total_noi = float(df["noi"].fillna(0).sum())
    total_cashflow_m = float(df["cashflow_m"].fillna(0).sum())
    port_cap = (total_noi / total_value)*100 if total_value > 0 else None

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total value", f"${total_value:,.0f}")
    k2.metric("Total loan", f"${total_loan:,.0f}")
    k3.metric("Total NOI (annual)", f"${total_noi:,.0f}")
    k4.metric("Portfolio cap rate", f"{port_cap:.2f}%" if port_cap is not None else "—")

    st.markdown("#### Actions")
    del_id = st.number_input("Delete by ID", min_value=0, value=0, step=1)
    if st.button("Delete selected", use_container_width=True) and del_id:
        delete_portfolio_item(int(del_id), st.session_state["email"])
        st.rerun()





elif page == "Templates":
    st.markdown("### 🧠 Underwriting Templates")
    st.caption("Save strategy presets (modules + defaults). Apply them in the Terminal for consistent underwriting.")
    built = built_in_templates()
    saved = fetch_templates(st.session_state["email"])

    st.markdown("#### Built-in strategies")
    bcols = st.columns(4)
    for i, (name, tpl) in enumerate(built.items()):
        with bcols[i % 4]:
            st.markdown(f"**{name}**")
            st.write("Modules:", ", ".join(tpl.get("included", [])[:6]) + ("…" if len(tpl.get("included", []))>6 else ""))
            if st.button(f"Apply {name}", key=f"apply_builtin_{i}"):
                apply_template_to_session(tpl)
                st.success("Applied. Go to Terminal.")
    st.divider()

    st.markdown("#### Your saved templates")
    if not saved:
        st.info("No saved templates yet. Use the builder below to create one.")
    else:
        for it in saved[:50]:
            cols = st.columns([2.0, 1.0, 1.0, 1.0])
            cols[0].write(f"**{it['name']}**\n\nUpdated: {ts_to_str(it['updated_at'])}")
            if cols[1].button("Apply", key=f"apply_saved_{it['id']}"):
                apply_template_to_session(it["template"])
                st.success("Applied. Go to Terminal.")
            if cols[2].button("Edit", key=f"edit_saved_{it['id']}"):
                st.session_state["edit_tpl_id"] = it["id"]
            if cols[3].button("Delete", key=f"del_saved_{it['id']}"):
                delete_template(it["id"], st.session_state["email"])
                st.rerun()
            st.divider()

    st.markdown("#### Template builder")
    modules = ["Rent & Price","Expenses","Vacancy","Financing","Yield","Downside","Liquidity","Location","Regulation","Last Sale","Optionality"]
    default_sel = built["LTR (Long-Term Rental)"]["included"]
    sel = st.multiselect("Modules to include", modules, default=default_sel)
    c1, c2, c3, c4 = st.columns(4)
    vac = c1.slider("Vacancy", 0.0, 0.25, 0.08, 0.01)
    exp_ratio = c2.slider("Expense ratio", 0.10, 0.70, 0.38, 0.01)
    dp = c3.number_input("Down payment (%)", 0.0, 100.0, 20.0, 1.0)
    rate = c4.number_input("Rate (%)", 0.0, 30.0, 7.25, 0.05)
    c5, c6, c7, c8 = st.columns(4)
    term = c5.number_input("Term years", 1, 40, 30, 1)
    hold = c6.number_input("Hold years", 1, 30, 7, 1)
    rg = c7.number_input("Rent growth (%)", 0.0, 0.25, 0.03, 0.005)
    eg = c8.number_input("Expense growth (%)", 0.0, 0.25, 0.03, 0.005)
    c9, c10, c11, c12 = st.columns(4)
    appr = c9.number_input("Appreciation (%)", 0.0, 0.25, 0.03, 0.005)
    sc = c10.number_input("Sale costs (%)", 0.0, 0.20, 0.07, 0.01)
    use_exit_cap = c11.checkbox("Use exit cap", value=False)
    exit_cap = c12.number_input("Exit cap (%)", 0.0, 20.0, 6.5, 0.1) if use_exit_cap else 0.0

    t1, t2, t3 = st.columns(3)
    target_grade = t1.selectbox("Target grade", ["A","B","C"], index=1)
    target_score = t2.number_input("Target score", 0.0, 100.0, 80.0, 1.0)
    name = t3.text_input("Template name", placeholder="My LTR Conservative")

    tpl = {
        "included": sel,
        "defaults": {
            "vacancy_rate": float(vac),
            "expense_ratio": float(exp_ratio),
            "down_payment_pct": float(dp),
            "interest_rate_pct": float(rate),
            "term_years": int(term),
            "hold_years": int(hold),
            "rent_growth": float(rg),
            "expense_growth": float(eg),
            "appreciation": float(appr),
            "sale_cost_pct": float(sc),
            "use_exit_cap": bool(use_exit_cap),
            "exit_cap_rate": float(exit_cap)/100.0 if use_exit_cap else float(exit_cap),
        },
        "targets": {"grade": target_grade, "score": float(target_score)},
    }

    cA, cB = st.columns([1,1])
    if cA.button("Apply builder template to Terminal", type="primary", use_container_width=True):
        apply_template_to_session(tpl)
        # also push advanced defaults into session for sensitivity/forward model
        defs = tpl["defaults"]
        st.session_state["adv_hold_years"] = int(defs["hold_years"])
        st.session_state["adv_rent_growth"] = float(defs["rent_growth"])
        st.session_state["adv_expense_growth"] = float(defs["expense_growth"])
        st.session_state["adv_appreciation"] = float(defs["appreciation"])
        st.session_state["adv_sale_cost_pct"] = float(defs["sale_cost_pct"])
        st.session_state["adv_use_exit_cap"] = bool(defs["use_exit_cap"])
        st.session_state["adv_exit_cap_rate"] = float(defs["exit_cap_rate"])
        st.success("Applied.")
    if cB.button("Save this template", use_container_width=True):
        if not name.strip():
            st.error("Name required.")
        else:
            add_template(st.session_state["email"], name.strip(), tpl)
            st.success("Saved.")
            st.rerun()

    # Edit flow
    edit_id = st.session_state.get("edit_tpl_id")
    if edit_id:
        current = next((x for x in saved if x["id"] == edit_id), None)
        if current:
            with st.expander("Edit saved template", expanded=True):
                new_name = st.text_input("Name", value=current["name"], key="edit_tpl_name")
                st.json(current["template"])
                if st.button("Update (keeps JSON shown above)", type="primary"):
                    update_template(edit_id, st.session_state["email"], new_name.strip(), current["template"])
                    st.session_state["edit_tpl_id"] = None
                    st.success("Updated.")
                    st.rerun()
                if st.button("Cancel edit"):
                    st.session_state["edit_tpl_id"] = None
                    st.rerun()

elif page == "Analytics":
    st.markdown("### 🧪 Analytics Lab")
    st.caption("Comps + sensitivity (rent and interest rate shocks). Run after you have filled inputs in Terminal (or applied a template).")

    # Pull latest underwriting state if present
    address = st.session_state.get("property_address_one_line") or st.text_input("Address (one-line)", value="")
    if not address.strip():
        st.info("Enter an address or load one from Watchlist/Terminal.")
        st.stop()

    # Comps from AVM responses
    st.markdown("#### Comps (best-effort)")
    if RENTCAST_APIKEY:
        avm_val = rentcast_value_avm(address.strip())
        avm_rent = rentcast_rent_avm(address.strip())
        df_sale = parse_comps(avm_val)
        df_rent = parse_comps(avm_rent)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Sale comps**")
            if not df_sale.empty:
                st.dataframe(df_sale.head(10), use_container_width=True, hide_index=True)
            else:
                st.info("No sale comps found in AVM response.")
        with c2:
            st.markdown("**Rent comps**")
            if not df_rent.empty:
                st.dataframe(df_rent.head(10), use_container_width=True, hide_index=True)
            else:
                st.info("No rent comps found in AVM response.")
    else:
        st.info("Add RENTCAST_APIKEY to show comps.")

    st.divider()
    st.markdown("#### Sensitivity heatmap (Score + IRR)")
    st.caption("Grid = rent shock vs interest-rate shock. This shows how fragile or resilient a deal is.")

    # Build a PropertyData baseline from session_state (Terminal) or minimal manual entry
    base_price = float(st.session_state.get("price") or 0) or st.number_input("Price ($)", 0.0, 50_000_000.0, 400000.0, 1000.0)
    base_rent = float(st.session_state.get("monthly_rent") or 0) or st.number_input("Monthly rent ($)", 0.0, 1_000_000.0, 3000.0, 50.0)
    base_exp = float(st.session_state.get("monthly_expenses") or 0) or st.number_input("Monthly expenses ($)", 0.0, 1_000_000.0, 1100.0, 50.0)
    base_vac = float(st.session_state.get("vacancy_rate") or 0.08)
    base_dp = float(st.session_state.get("down_payment_pct") or 20.0)
    base_rate = float(st.session_state.get("interest_rate_pct") or 7.25)
    base_term = int(st.session_state.get("term_years") or 30)

    included = st.session_state.get("tpl_included") or ["Rent & Price","Expenses","Vacancy","Financing","Yield","Liquidity","Last Sale","Optionality"]
    rate_env = st.selectbox("Rate environment", ["HIGH","NORMAL"], index=0)

    p = PropertyData(
        address=address.strip(),
        price=base_price,
        monthly_rent=base_rent,
        monthly_expenses=base_exp,
        vacancy_rate=base_vac,
        down_payment_pct=base_dp,
        interest_rate_pct=base_rate,
        term_years=base_term
    )
    nums = compute_numbers(p)

    r1, r2 = st.columns(2)
    rent_span = r1.slider("Rent shock span", 0.05, 0.30, 0.10, 0.01)
    rate_span = r2.slider("Rate shock span", 0.25, 2.00, 1.00, 0.05)  # in percentage points

    rent_shocks = [round(x, 2) for x in _np.linspace(-rent_span, rent_span, 7)]
    rate_shocks = [round(x/100.0, 4) for x in _np.linspace(-rate_span, rate_span, 7)]  # decimal

    if st.button("Run sensitivity", type="primary", use_container_width=True):
        score_df, irr_df = sensitivity_matrix(p, nums, included, rate_env, rent_shocks, rate_shocks)

        st.markdown("**Score sensitivity** (rows rent shock, cols rate shock)")
        st.dataframe(score_df, use_container_width=True)

        st.markdown("**IRR sensitivity** (annual %, rows rent shock, cols rate shock)")
        st.dataframe(irr_df, use_container_width=True)

        st.download_button("Download sensitivity (CSV)", score_df.reset_index().to_csv(index=False).encode("utf-8"), "aire_sensitivity_score.csv", "text/csv", use_container_width=True)



else:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### About AIRE™ Terminal")
    st.write("Bloomberg-style workflow for real estate underwriting: modular inputs, audit trail, confidence score.")
    st.write("No scraping. Real data pulled from your own API keys (Estated/ATTOM).")
    st.write("")
    st.markdown("**Roadmap**")
    st.write("• Rent comps (range + confidence) + market trend charts")
    st.write("• Watchlists + alerts")
    st.write("• Portfolio analytics + risk heatmaps")
    st.write("• Team workspaces")
    st.write("• Stripe webhooks for auto-unlock subscriptions")
    st.markdown("</div>", unsafe_allow_html=True)
