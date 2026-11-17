"""
app.py
JEE Main Mock Test & Admin Question Bank Platform
Stack: Streamlit + Supabase (PostgreSQL + Storage) + GitHub Deployment
"""

import hashlib
import hmac
import html
import io
import os
import random
import re
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import pandas as pd
import streamlit as st
from fpdf import FPDF
from supabase import Client, create_client

from syllabus_mapper import (
    SUBJECTS,
    compute_subject_quotas,
    estimate_difficulty,
    extract_syllabus_text,
    is_valid_mcq,
    map_questions_to_units,
    parse_syllabus_document,
    select_subject_divided_mcqs,
    strip_unit_number,
)

st.set_page_config(
    page_title="JEE Main Mock Test & Question Bank",
    page_icon="📘",
    layout="wide",
)

FLAG_REASON_OPTIONS = [
    "Wrong Subject (e.g. Math Q in Chemistry)",
    "Wrong Syllabus Unit / Beyond Syllabus",
    "Improper Symbols / Broken Math",
    "Incomplete Options / Missing Image",
    "Suspected Wrong Answer Key",
    "Other",
]

MOTIVATIONAL_QUOTES = [
    "Yes, you can!",
    "Mistakes are proof that you are learning something new.",
    "Every question you solve today builds tomorrow's rank.",
    "Small daily progress adds up to big JEE results.",
    "Stay calm, read carefully, and trust your preparation.",
    "Focus on accuracy first — speed follows naturally.",
    "One tough problem cracked is confidence earned.",
    "Consistency beats intensity. Keep showing up!",
    "Your future self will thank you for today's practice.",
    "Don't fear hard questions — let them sharpen your mind.",
    "Believe in your preparation and give this test your best.",
    "Every mock test turns weak spots into strong topics.",
    "Stay curious, stay steady, and keep moving forward.",
    "Success is built one concept and one practice set at a time.",
    "Breathe deep, stay sharp, and solve with confidence.",
    "Progress, not perfection — learn something from every question.",
]


def _pick_login_quote(prev_quote: Optional[str] = None) -> str:
    choices = [q for q in MOTIVATIONAL_QUOTES if q != prev_quote]
    return random.choice(choices or MOTIVATIONAL_QUOTES)


# ---------------------------------------------------------------------------
# Custom Theme & Typography (Crisp White Test Canvas + Energetic Light UI)
# ---------------------------------------------------------------------------
def inject_custom_theme(is_active_test: bool = False):
    app_bg = "#FFFFFF" if is_active_test else "#F4F7FB"
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap');

        html, body, h1, h2, h3, h4, p, label, input, textarea, button,
        .stApp, [data-testid="stMarkdownContainer"] {{
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
            color: #0F172A;
        }}
        [data-testid="stIconMaterial"], .material-symbols-rounded, .material-icons {{
            font-family: 'Material Symbols Rounded', 'Material Icons', sans-serif !important;
        }}
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{
            background-color: {app_bg} !important;
        }}
        #MainMenu, footer {{
            visibility: hidden;
        }}
        [data-testid="stSidebar"] {{
            background-color: #FFFFFF !important;
            border-right: 1px solid #E2E8F0;
        }}
        /* Card Containers & Auth Forms */
        [data-testid="stForm"] {{
            background-color: #FFFFFF !important;
            border: 1px solid #E2E8F0 !important;
            border-radius: 16px !important;
            padding: 24px !important;
            box-shadow: 0 4px 18px rgba(15, 23, 42, 0.05) !important;
        }}
        [data-testid="stMetric"] {{
            background-color: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 12px 16px;
            box-shadow: 0 1px 4px rgba(15, 23, 42, 0.04);
        }}
        /* Styled Pill / Card Tabs (replaces default Streamlit gray/red tabs) */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 8px;
            background-color: #EEF2FF;
            padding: 6px;
            border-radius: 12px;
            border: 1px solid #DBEAFE;
        }}
        .stTabs [data-baseweb="tab"] {{
            height: 42px;
            border-radius: 8px;
            padding: 0 20px;
            font-weight: 600;
            font-size: 0.93rem;
            color: #334155;
            background-color: transparent;
            border: none !important;
        }}
        .stTabs [aria-selected="true"] {{
            background-color: #FFFFFF !important;
            color: #1D4ED8 !important;
            box-shadow: 0 2px 6px rgba(37, 99, 235, 0.12);
        }}
        .stTabs [data-baseweb="tab-highlight"],
        .stTabs [data-baseweb="tab-border"] {{
            display: none !important;
        }}
        /* Primary & Secondary Buttons */
        .stButton > button[kind="primary"] {{
            background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%);
            border: none;
            color: #FFFFFF;
            font-weight: 600;
            border-radius: 10px;
            padding: 0.55rem 1.3rem;
            box-shadow: 0 3px 10px rgba(37, 99, 235, 0.22);
        }}
        .stButton > button[kind="primary"]:hover {{
            background: linear-gradient(135deg, #1D4ED8 0%, #1E40AF 100%);
        }}
        .stButton > button {{
            border-radius: 10px;
            font-weight: 600;
        }}
        /* Hero, Showcase & Subject Badges */
        .jee-hero {{
            background: linear-gradient(135deg, #EFF6FF 0%, #FFFFFF 55%, #FEF3C7 100%);
            border: 1px solid #DBEAFE;
            border-radius: 16px;
            padding: 24px 28px;
            margin-bottom: 18px;
        }}
        .jee-hero h2 {{
            margin: 0 0 6px 0;
            color: #1E3A8A;
            font-weight: 800;
            letter-spacing: -0.02em;
        }}
        .jee-hero p {{
            margin: 0;
            color: #475569;
            font-size: 0.96rem;
        }}
        .jee-quote-box {{
            margin-top: 12px;
            background: linear-gradient(90deg, #FEF3C7 0%, #FFFBEB 100%);
            border: 1px solid #FCD34D;
            border-left: 5px solid #D97706;
            border-radius: 12px;
            padding: 12px 18px;
            color: #78350F;
            font-size: 1.02rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 10px;
            box-shadow: 0 2px 8px rgba(217, 119, 6, 0.08);
        }}
        .jee-auth-showcase {{
            background: linear-gradient(155deg, #EFF6FF 0%, #FFFFFF 60%, #FEF3C7 100%);
            border: 1px solid #DBEAFE;
            border-radius: 16px;
            padding: 28px;
            height: 100%;
        }}
        .jee-auth-showcase h3 {{
            margin: 0 0 10px 0;
            color: #1E3A8A;
            font-weight: 800;
        }}
        .jee-feature-pill {{
            background-color: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-left: 4px solid #2563EB;
            border-radius: 10px;
            padding: 10px 14px;
            margin-top: 10px;
            font-size: 0.9rem;
            color: #334155;
        }}
        .jee-sub-badge {{
            border-radius: 10px;
            padding: 8px 14px;
            font-weight: 700;
            font-size: 0.95rem;
            margin-bottom: 6px;
            border: 1px solid #E2E8F0;
        }}
        .jee-sub-phy {{ background-color: #EFF6FF; color: #1D4ED8; border-left: 4px solid #2563EB; }}
        .jee-sub-chem {{ background-color: #ECFDF5; color: #047857; border-left: 4px solid #059669; }}
        .jee-sub-math {{ background-color: #FFFBEB; color: #B45309; border-left: 4px solid #D97706; }}
        .jee-rules-card {{
            background-color: #FFFFFF;
            border: 1px solid #BFDBFE;
            border-left: 5px solid #2563EB;
            border-radius: 12px;
            padding: 16px 20px;
            margin: 12px 0 16px 0;
        }}
        /* High-visibility bordered surrounding for ALL checkboxes (Options, Flags, PDF toggle) */
        [data-testid="stCheckbox"] {{
            background-color: #EFF6FF !important;
            border: 1.5px solid #60A5FA !important;
            border-radius: 10px !important;
            padding: 6px 10px !important;
            display: inline-flex !important;
            align-items: center !important;
            width: fit-content !important;
        }}
        [data-testid="stCheckbox"] label {{
            margin-bottom: 0 !important;
        }}
        [data-testid="stCheckbox"] [data-baseweb="checkbox"] > span:first-child,
        [data-testid="stCheckbox"] [data-baseweb="checkbox"] > div:first-child {{
            border: 2px solid #1D4ED8 !important;
            background-color: #FFFFFF !important;
            border-radius: 5px !important;
        }}
        /* Fixed floating countdown clock visible even when scrolling down */
        .jee-timer-bar {{
            position: fixed;
            top: 56px;
            right: 24px;
            z-index: 9999;
            background-color: #FFFFFF;
            border: 2px solid #2563EB;
            border-radius: 12px;
            padding: 10px 16px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.9rem;
            color: #0F172A;
            box-shadow: 0 8px 24px rgba(37, 99, 235, 0.16);
            max-width: calc(100vw - 48px);
        }}
        .jee-timer-spacer {{
            height: 44px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Supabase Connection & Security Helpers
# ---------------------------------------------------------------------------
@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def hash_password(password: str, salt_hex: Optional[str] = None) -> str:
    if salt_hex is None:
        salt_hex = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 120_000)
    return f"{salt_hex}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, expected_hex = stored_hash.split("$", 1)
        computed = hash_password(password, salt_hex)
        return hmac.compare_digest(computed, f"{salt_hex}${expected_hex}")
    except Exception:
        return False


def compute_content_hash(row: Dict) -> str:
    raw = "|".join([
        str(row.get("subject", "")),
        str(row.get("question", "")),
        str(row.get("option_1", "")),
        str(row.get("option_2", "")),
        str(row.get("option_3", "")),
        str(row.get("option_4", "")),
    ])
    norm = re.sub(r"\s+", "", raw.lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs}h {mins:02d}m {secs:02d}s"
    return f"{mins:02d}m {secs:02d}s"


def extract_option_image_url(sb: Client, opt_text: str) -> Optional[str]:
    txt = (opt_text or "").strip()
    m = re.match(r"^\[Image:\s*(.+?)\]$", txt)
    if not m:
        return None
    img_ref = m.group(1).strip()
    if img_ref.startswith("http://") or img_ref.startswith("https://"):
        return img_ref
    fname = os.path.basename(img_ref)
    return sb.storage.from_("question-images").get_public_url(fname)


def render_option_content(sb: Client, opt_text: str):
    """Renders text option or embedded [Image: ...] PNG stored in Supabase Storage."""
    img_url = extract_option_image_url(sb, opt_text)
    if img_url:
        st.image(img_url, width=260)
        return
    txt = (opt_text or "").strip()
    st.markdown(txt if txt else "_(Blank option)_")


def fetch_all_questions(sb: Client, mcq_only: bool = False) -> List[Dict]:
    """Fetches all questions across Supabase 1,000-row pages (scales cleanly to 14,000+ rows)."""
    all_rows: List[Dict] = []
    offset = 0
    page_size = 1000
    while True:
        q = sb.table("questions").select("*")
        if mcq_only:
            q = q.eq("is_mcq", True)
        batch = q.order("subject").order("question_no").range(offset, offset + page_size - 1).execute().data
        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return all_rows


# ---------------------------------------------------------------------------
# Question Booklet PDF Generator (Option 2A + Performance Board Integration)
# ---------------------------------------------------------------------------
_UNICODE_FALLBACK_MAP = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "Δ": "Delta",
    "ε": "epsilon", "θ": "theta", "λ": "lambda", "μ": "mu", "ν": "nu",
    "π": "pi", "ρ": "rho", "σ": "sigma", "τ": "tau", "φ": "phi", "ω": "omega", "Ω": "Omega",
    "√": "sqrt", "∫": "integral", "∑": "sum", "∏": "prod", "∞": "infinity",
    "≤": "<=", "≥": ">=", "≠": "!=", "≈": "~=", "±": "+/-", "×": "x", "÷": "/",
    "·": "*", "→": "->", "⇒": "=>", "⇔": "<=>", "∈": "in", "∉": "not in",
    "∪": "U", "∩": "intersect", "⊂": "subset", "°": " deg", "²": "^2", "³": "^3",
    "¹": "^1", "⁰": "^0", "⁻¹": "^-1", "⁻": "^-", "⁺": "^+",
    "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...",
}


def _find_unicode_ttf() -> Optional[str]:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _clean_latex_for_pdf(s: str) -> str:
    """Converts common LaTeX fragments (including nested powers) into clean readable plain text for PDF output."""
    for _ in range(2):
        s = re.sub(r"\^\{([^{}]+)\}", r"^(\1)", s)
        s = re.sub(r"_\{([^{}]+)\}", r"_(\1)", s)
        s = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1)/(\2)", s)
        s = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"sqrt(\1)", s)
    s = s.replace(r"\sqrt", "sqrt")
    latex_tokens = {
        r"\in": " in ", r"\notin": " not in ", r"\le": "<=", r"\leq": "<=",
        r"\ge": ">=", r"\geq": ">=", r"\neq": "!=", r"\approx": "~=",
        r"\pm": "+/-", r"\times": " x ", r"\cdot": "*", r"\div": "/",
        r"\to": " -> ", r"\rightarrow": " -> ", r"\Rightarrow": " => ",
        r"\Leftrightarrow": " <=> ", r"\infty": "infinity", r"\cup": " U ",
        r"\cap": " intersect ", r"\subset": " subset ", r"\mathbb{R}": "R",
        r"\mathbb{N}": "N", r"\mathbb{Z}": "Z", r"\mathbb{Q}": "Q",
        r"\alpha": "alpha", r"\beta": "beta", r"\gamma": "gamma", r"\delta": "delta",
        r"\theta": "theta", r"\lambda": "lambda", r"\mu": "mu", r"\pi": "pi",
        r"\sigma": "sigma", r"\phi": "phi", r"\omega": "omega", r"\Delta": "Delta",
        r"\Omega": "Omega", r"\left": "", r"\right": "",
    }
    for tok, rep in latex_tokens.items():
        s = s.replace(tok, rep)
    s = s.replace("$", "")
    return s


def _pdf_text(text: str, use_unicode: bool) -> str:
    s = _clean_latex_for_pdf(str(text or ""))
    s = re.sub(r"\s+", " ", s).strip()
    if use_unicode:
        return s
    for k, v in _UNICODE_FALLBACK_MAP.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _safe_multicell(pdf: FPDF, h: float, txt: str):
    """Safely wraps text across full printable page width without ever losing horizontal margin."""
    pdf.set_x(pdf.l_margin)
    w = max(40.0, pdf.w - pdf.l_margin - pdf.r_margin)
    safe_txt = txt if txt else " "
    try:
        pdf.multi_cell(w, h, safe_txt, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
    except TypeError:
        pdf.multi_cell(w, h, safe_txt)
    pdf.set_x(pdf.l_margin)


def build_question_booklet_pdf(
    sb: Client,
    student_name: str,
    attempt: Dict,
    review_rows: List[Dict],
    hide_skipped_answers: bool = False,
) -> bytes:
    """Generates a clean downloadable Question Booklet PDF for any submitted/past mock test."""
    pdf = FPDF()
    pdf.set_margins(12, 12, 12)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    ttf_path = _find_unicode_ttf()
    use_unicode = False
    if ttf_path:
        try:
            pdf.add_font("CustomSans", "", ttf_path, uni=True)
            use_unicode = True
        except Exception:
            use_unicode = False

    font_name = "CustomSans" if use_unicode else "Helvetica"

    def set_f(size: int, bold: bool = False):
        style = "" if use_unicode else ("B" if bold else "")
        pdf.set_font(font_name, style=style, size=size)

    full_marks = max(1, int(attempt.get("full_marks", 1)))
    obtained = int(attempt.get("marks_obtained", 0))
    pct = round((obtained / full_marks) * 100.0, 1)
    dt_str = str(attempt.get("test_date", ""))[:16].replace("T", " ")

    # Header Block (Visually distinct for Practice Mode vs Answer & Revision Mode)
    usable_w = max(40.0, pdf.w - pdf.l_margin - pdf.r_margin)
    if hide_skipped_answers:
        header_title = "JEE Main Mock Test - Practice Booklet (Answers Hidden)"
        mode_note = "Mode: Practice Booklet — Correct answers hidden for wrong & unattempted questions"
        pdf.set_fill_color(254, 243, 199)  # Soft Warm Amber
        title_rgb = (180, 83, 9)           # Deep Amber
    else:
        header_title = "JEE Main Mock Test - Answer & Revision Booklet"
        mode_note = "Mode: Answer & Revision Booklet — Complete answer keys shown"
        pdf.set_fill_color(239, 246, 255)  # Soft Royal Blue
        title_rgb = (30, 58, 138)          # Deep Blue

    pdf.rect(pdf.l_margin, 10, usable_w, 33, "F")
    pdf.set_xy(pdf.l_margin + 3, 13)
    set_f(14, bold=True)
    pdf.set_text_color(*title_rgb)
    pdf.cell(usable_w - 6, 7, _pdf_text(header_title, use_unicode), new_x="LMARGIN", new_y="NEXT")

    pdf.set_x(pdf.l_margin + 3)
    set_f(9, bold=True)
    pdf.cell(usable_w - 6, 5, _pdf_text(mode_note, use_unicode), new_x="LMARGIN", new_y="NEXT")

    pdf.set_x(pdf.l_margin + 3)
    set_f(10)
    pdf.set_text_color(51, 65, 85)
    pdf.cell(
        usable_w - 6,
        5,
        _pdf_text(f"Student: {student_name}  |  Date: {dt_str}  |  Subjects: {attempt.get('subjects_covered', '')}", use_unicode),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_x(pdf.l_margin + 3)
    pdf.cell(
        usable_w - 6,
        5,
        _pdf_text(
            f"Score: {obtained}/{full_marks} ({pct}%)  |  Correct: {attempt.get('correct_count', 0)}  |  "
            f"Wrong: {attempt.get('wrong_count', 0)}  |  Skipped: {attempt.get('skipped_count', 0)}  |  "
            f"Time: {format_duration(attempt.get('time_taken_sec', 0))} / {format_duration(attempt.get('total_allotted_sec', 0))}",
            use_unicode,
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_xy(pdf.l_margin, 47)

    for idx, item in enumerate(review_rows, start=1):
        q = item["question"]
        sel = item.get("selected")
        status = str(item.get("status", "")).strip().lower()
        if not sel and status not in ("correct", "wrong"):
            status = "skipped"
        corr = str(item.get("correct", q.get("correct_answer", ""))).strip()
        unit_clean = strip_unit_number(q.get("unit", "Unmapped"))

        pdf.set_text_color(15, 23, 42)
        set_f(11, bold=True)
        _safe_multicell(
            pdf,
            6,
            _pdf_text(f"Q{idx}. [{q.get('subject', '')} - {unit_clean}] {q.get('question', '')}", use_unicode),
        )
        pdf.ln(1)

        set_f(10)
        pdf.set_text_color(51, 65, 85)
        for opt_num in ("1", "2", "3", "4"):
            opt_val = str(q.get(f"option_{opt_num}", "")).strip()
            img_url = extract_option_image_url(sb, opt_val)
            if img_url:
                y_pos = pdf.get_y()
                if y_pos > 245:
                    pdf.add_page()
                    y_pos = pdf.get_y()
                try:
                    with urllib.request.urlopen(img_url, timeout=4) as resp:
                        img_bytes = resp.read()
                    pdf.set_x(pdf.l_margin)
                    pdf.cell(12, 6, f"({opt_num})")
                    pdf.image(io.BytesIO(img_bytes), x=pdf.l_margin + 14, y=y_pos, w=45)
                    pdf.set_xy(pdf.l_margin, y_pos + 24)
                except Exception:
                    _safe_multicell(pdf, 5.5, _pdf_text(f"  ({opt_num}) [Option Diagram]", use_unicode))
            else:
                _safe_multicell(pdf, 5.5, _pdf_text(f"  ({opt_num}) {opt_val}", use_unicode))

        # Outcome line: Practice Mode hides correct answer for BOTH wrong & unattempted questions
        set_f(10, bold=True)
        if status == "correct":
            pdf.set_text_color(5, 150, 105)
            verdict = f"Result: CORRECT (+4)  |  Your Attempted Option: ({sel})"
        elif status == "wrong":
            pdf.set_text_color(220, 38, 38)
            if hide_skipped_answers:
                verdict = f"Result: WRONG (-1)  |  Your Attempted Option: ({sel})  |  Correct answer hidden for re-practice"
            else:
                verdict = f"Result: WRONG (-1)  |  Your Attempted Option: ({sel})  |  Correct Answer: ({corr})"
        else:
            pdf.set_text_color(217, 119, 6)
            if hide_skipped_answers:
                verdict = "Result: UNATTEMPTED (0)  |  Correct answer hidden for re-practice"
            else:
                verdict = f"Result: SKIPPED (0)  |  Correct Answer: ({corr})"

        _safe_multicell(pdf, 6, _pdf_text(verdict, use_unicode))
        pdf.set_draw_color(226, 232, 240)
        y_line = pdf.get_y() + 1
        pdf.line(pdf.l_margin, y_line, pdf.w - pdf.r_margin, y_line)
        pdf.set_x(pdf.l_margin)
        pdf.ln(4)

    out = pdf.output()
    return bytes(out) if isinstance(out, (bytes, bytearray)) else out.encode("latin-1")


# ---------------------------------------------------------------------------
# Admin Panel (CSV + Images Storage + Syllabus Mapping + Flag Review)
# ---------------------------------------------------------------------------
def render_admin_panel(sb: Client):
    st.markdown(
        '<div class="jee-hero"><h2>Admin Question Bank & Syllabus Manager</h2>'
        '<p>Upload JEE syllabus, question CSVs, option images, and review student-flagged questions.</p></div>',
        unsafe_allow_html=True,
    )

    if not st.session_state.get("is_admin"):
        with st.form("admin_login_form"):
            pwd = st.text_input("Admin Password", type="password")
            submitted = st.form_submit_button("Sign In as Admin", type="primary")
            if submitted:
                if hmac.compare_digest(pwd, st.secrets["ADMIN_PASSWORD"]):
                    st.session_state["is_admin"] = True
                    st.rerun()
                else:
                    st.error("Invalid admin password.")
        return

    if st.button("Lock Admin Session", key="admin_logout"):
        st.session_state["is_admin"] = False
        st.rerun()

    tab_syl, tab_upload, tab_bank, tab_flags = st.tabs([
        "1. Upload JEE Syllabus",
        "2. Upload Extracted CSV & Option Images",
        "3. Question Bank & Overrides",
        "4. Flagged Questions Review",
    ])

    # --- Tab 1: Upload Syllabus PDF / TXT ---
    with tab_syl:
        st.subheader("Upload JEE Main Syllabus (PDF or TXT)")
        st.caption("Parsed units are stored in Supabase and used to auto-map every uploaded question.")
        syl_file = st.file_uploader("Choose Syllabus PDF or TXT", type=["pdf", "txt"])
        replace_existing = st.checkbox(
            "Replace existing syllabus units before saving (clears old/wrong units)",
            value=True,
        )
        if syl_file and st.button("Parse & Save Syllabus to Supabase", type="primary"):
            raw_bytes = syl_file.getvalue()
            storage_path = f"syllabus/{int(time.time())}_{syl_file.name}"
            sb.storage.from_("raw-uploads").upload(
                storage_path,
                raw_bytes,
                {"content-type": syl_file.type or "application/octet-stream"},
            )
            raw_text = extract_syllabus_text(raw_bytes, syl_file.name)
            units = parse_syllabus_document(raw_text)
            if not units:
                st.error("No units detected. Ensure headings follow 'PHYSICS / UNIT 1: ...' format.")
            else:
                if replace_existing:
                    sb.table("syllabus_units").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
                payload = [
                    {
                        "subject": u["subject"],
                        "unit_name": u["unit_name"],
                        "keywords": u["keywords"],
                        "source_file": syl_file.name,
                    }
                    for u in units
                ]
                sb.table("syllabus_units").upsert(payload, on_conflict="subject,unit_name").execute()
                sb.table("admin_uploads").insert({
                    "upload_type": "syllabus",
                    "file_name": syl_file.name,
                    "storage_path": storage_path,
                    "rows_processed": len(payload),
                }).execute()
                st.success(f"Saved {len(payload)} clean syllabus units across Physics, Chemistry, and Mathematics.")

        existing_units = sb.table("syllabus_units").select("subject, unit_name, keywords, source_file").order("subject").execute().data
        if existing_units:
            st.markdown(f"**Stored Syllabus Units ({len(existing_units)}):**")
            df_u = pd.DataFrame(existing_units)
            df_u["keywords"] = df_u["keywords"].apply(lambda k: ", ".join(k[:10]) if isinstance(k, list) else str(k))
            st.dataframe(df_u, use_container_width=True, hide_index=True)

    # --- Tab 2: Upload Extracted CSV & Option Images ---
    with tab_upload:
        st.subheader("Upload Extracted CSV + Option Diagrams")
        col1, col2 = st.columns(2)
        with col1:
            csv_file = st.file_uploader("Upload consolidated_questions_fixed.csv", type=["csv"])
        with col2:
            img_files = st.file_uploader(
                "Upload Option Images (.zip of option_images/ recommended for 100+ files, or PNG/JPG)",
                type=["zip", "png", "jpg", "jpeg"],
                accept_multiple_files=True,
            )
            skip_existing = st.checkbox(
                "Skip images already uploaded to Supabase (fast resume)",
                value=True,
            )

        if img_files and st.button("Upload Option Images to Supabase Storage"):
            items_to_process = []
            for f in img_files:
                low_name = f.name.lower()
                if low_name.endswith(".zip"):
                    with zipfile.ZipFile(io.BytesIO(f.getvalue())) as zf:
                        for info in zf.infolist():
                            if info.is_dir():
                                continue
                            base = os.path.basename(info.filename)
                            if not base or base.startswith(".") or "__MACOSX" in info.filename:
                                continue
                            ext = os.path.splitext(base)[1].lower()
                            if ext not in {".png", ".jpg", ".jpeg"}:
                                continue
                            ctype = "image/jpeg" if ext in {".jpg", ".jpeg"} else "image/png"
                            items_to_process.append((base, zf.read(info.filename), ctype))
                else:
                    ext = os.path.splitext(f.name)[1].lower()
                    ctype = f.type or ("image/jpeg" if ext in {".jpg", ".jpeg"} else "image/png")
                    items_to_process.append((os.path.basename(f.name), f.getvalue(), ctype))

            existing_names: Set[str] = set()
            if skip_existing:
                try:
                    offset = 0
                    while True:
                        batch = sb.storage.from_("question-images").list("", {"limit": 1000, "offset": offset})
                        if not batch:
                            break
                        for obj in batch:
                            if isinstance(obj, dict) and obj.get("name"):
                                existing_names.add(obj["name"])
                        if len(batch) < 1000:
                            break
                        offset += 1000
                except Exception:
                    existing_names = set()

            total = len(items_to_process)
            prog = st.progress(0, text=f"Preparing {total} image(s)...")
            uploaded_cnt = 0
            skipped_cnt = 0
            failed_files: List[str] = []

            for idx, (fname, data, ctype) in enumerate(items_to_process, start=1):
                if skip_existing and fname in existing_names:
                    skipped_cnt += 1
                else:
                    ok = False
                    last_err = ""
                    for attempt in range(3):
                        try:
                            sb.storage.from_("question-images").upload(
                                fname,
                                data,
                                {"content-type": ctype, "upsert": "true"},
                            )
                            ok = True
                            break
                        except Exception as exc:
                            last_err = str(exc)
                            time.sleep(0.4 * (attempt + 1))
                    if ok:
                        uploaded_cnt += 1
                        existing_names.add(fname)
                    else:
                        failed_files.append(f"{fname} ({last_err})")

                if idx % 20 == 0 or idx == total:
                    prog.progress(
                        idx / max(1, total),
                        text=f"Processed {idx}/{total} — Uploaded: {uploaded_cnt}, Skipped: {skipped_cnt}, Failed: {len(failed_files)}",
                    )

            sb.table("admin_uploads").insert({
                "upload_type": "option_images",
                "file_name": f"{uploaded_cnt} uploaded ({skipped_cnt} skipped)",
                "storage_path": "question-images/",
                "rows_processed": uploaded_cnt,
            }).execute()

            if failed_files:
                st.warning(
                    f"Uploaded {uploaded_cnt}, skipped {skipped_cnt} already in Supabase, "
                    f"and **{len(failed_files)}** failed."
                )
                with st.expander(f"View {len(failed_files)} failed image(s)"):
                    st.text("\n".join(failed_files))
                st.download_button(
                    "Download Failed Image List (.txt)",
                    data="\n".join(failed_files).encode("utf-8"),
                    file_name="failed_images.txt",
                    mime="text/plain",
                )
            else:
                st.success(
                    f"Done! Uploaded {uploaded_cnt} new image(s) to Supabase `question-images` "
                    f"({skipped_cnt} already existed and were skipped)."
                )

        if csv_file and st.button("Map Units, Auto-Tag Difficulty & Store CSV in Supabase", type="primary"):
            raw_csv_bytes = csv_file.getvalue()
            csv_storage_path = f"csv/{int(time.time())}_{csv_file.name}"
            sb.storage.from_("raw-uploads").upload(csv_storage_path, raw_csv_bytes, {"content-type": "text/csv"})

            df = pd.read_csv(io.BytesIO(raw_csv_bytes), dtype=str).fillna("")
            syllabus_units = sb.table("syllabus_units").select("*").execute().data

            records_to_prep = []
            for _, r in df.iterrows():
                rec = {
                    "source_file": r.get("source_file", csv_file.name),
                    "subject": r.get("subject", "Physics") if r.get("subject") in SUBJECTS else "Physics",
                    "question_no": r.get("Question no.", r.get("question_no", "")),
                    "question": r.get("Question", r.get("question", "")),
                    "option_1": r.get("option 1", r.get("option_1", "")),
                    "option_2": r.get("option 2", r.get("option_2", "")),
                    "option_3": r.get("option 3", r.get("option_3", "")),
                    "option_4": r.get("option 4", r.get("option_4", "")),
                    "correct_answer": (r.get("correct_answer", "").strip() or "Unknown"),
                    "csv_difficulty": r.get("difficulty", "").strip(),
                    "csv_unit": r.get("unit", "").strip(),
                }
                records_to_prep.append(rec)

            auto_units = map_questions_to_units(records_to_prep, syllabus_units)

            db_rows = []
            seen_batch_hashes = set()
            for rec, auto_u in zip(records_to_prep, auto_units):
                c_hash = compute_content_hash(rec)
                if c_hash in seen_batch_hashes:
                    continue
                seen_batch_hashes.add(c_hash)

                for ok in ("option_1", "option_2", "option_3", "option_4"):
                    m_img = re.match(r"^\[Image:\s*(.+?)\]$", rec[ok])
                    if m_img and not m_img.group(1).startswith("http"):
                        fname = os.path.basename(m_img.group(1).strip())
                        pub_url = sb.storage.from_("question-images").get_public_url(fname)
                        rec[ok] = f"[Image: {pub_url}]"

                diff = rec["csv_difficulty"] if rec["csv_difficulty"] in {"Easy", "Medium", "Hard"} else estimate_difficulty(
                    rec["question"], [rec["option_1"], rec["option_2"], rec["option_3"], rec["option_4"]]
                )
                unit_val = rec["csv_unit"] or auto_u
                db_rows.append({
                    "source_file": rec["source_file"],
                    "subject": rec["subject"],
                    "question_no": rec["question_no"],
                    "question": rec["question"],
                    "unit": unit_val,
                    "difficulty": diff,
                    "option_1": rec["option_1"],
                    "option_2": rec["option_2"],
                    "option_3": rec["option_3"],
                    "option_4": rec["option_4"],
                    "correct_answer": rec["correct_answer"],
                    "is_mcq": is_valid_mcq(rec),
                    "content_hash": c_hash,
                })

            total_rows = len(db_rows)
            mcq_count = sum(1 for r in db_rows if r["is_mcq"])
            non_mcq_count = total_rows - mcq_count
            up_prog = st.progress(0, text=f"Saving {total_rows} unique questions to Supabase...")
            for start in range(0, total_rows, 200):
                batch = db_rows[start:start + 200]
                sb.table("questions").upsert(batch, on_conflict="content_hash").execute()
                done = min(start + len(batch), total_rows)
                up_prog.progress(done / max(1, total_rows), text=f"Saved {done}/{total_rows} questions...")

            sb.table("admin_uploads").insert({
                "upload_type": "questions_csv",
                "file_name": csv_file.name,
                "storage_path": csv_storage_path,
                "rows_processed": total_rows,
            }).execute()
            st.success(
                f"Stored & mapped **{total_rows}** unique questions in Supabase "
                f"(**{mcq_count}** valid 1–4 MCQs active for tests · **{non_mcq_count}** numerical/5/Unknown archived with `is_mcq=False`)."
            )

    # --- Tab 3: Question Bank Editor & Mapped CSV Download ---
    with tab_bank:
        st.subheader("Manage Questions, Units & Difficulty Overrides")
        rows = fetch_all_questions(sb, mcq_only=False)
        if not rows:
            st.info("No questions in Supabase yet. Upload syllabus and CSV in Tabs 1 & 2.")
        else:
            col_remap, col_dl = st.columns([1, 1])
            with col_remap:
                if st.button("Re-run Automatic Syllabus Mapping on All Questions"):
                    syl_units = sb.table("syllabus_units").select("*").execute().data
                    new_units = map_questions_to_units(rows, syl_units)
                    remap_prog = st.progress(0, text="Updating mapped units...")
                    changed_cnt = 0
                    for idx, (q_row, u_name) in enumerate(zip(rows, new_units), start=1):
                        if u_name != q_row["unit"]:
                            sb.table("questions").update({"unit": u_name}).eq("id", q_row["id"]).execute()
                            changed_cnt += 1
                        if idx % 100 == 0 or idx == len(rows):
                            remap_prog.progress(idx / max(1, len(rows)), text=f"Checked {idx}/{len(rows)} questions...")
                    st.success(f"Re-mapped all questions against current syllabus ({changed_cnt} updated).")
                    st.rerun()

            df_bank = pd.DataFrame(rows)
            export_cols = [
                "source_file", "subject", "question_no", "question", "unit", "difficulty",
                "option_1", "option_2", "option_3", "option_4", "correct_answer", "is_mcq",
            ]
            export_df = df_bank[export_cols].rename(columns={
                "question_no": "Question no.",
                "question": "Question",
                "option_1": "option 1",
                "option_2": "option 2",
                "option_3": "option 3",
                "option_4": "option 4",
            })
            with col_dl:
                st.download_button(
                    "Download Mapped CSV (with `unit` beside `Question`)",
                    data=export_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name="mapped_questions_with_units.csv",
                    mime="text/csv",
                )

            st.caption(
                f"Total in DB: **{len(df_bank)}** | Valid MCQs (`1–4`): **{int(df_bank['is_mcq'].sum())}** | "
                f"Non-MCQ / Numerical / Unknown: **{int((~df_bank['is_mcq']).sum())}**"
            )
            f1, f2, f3 = st.columns(3)
            with f1:
                f_sub = st.selectbox("Filter Subject", ["All"] + sorted(df_bank["subject"].unique().tolist()))
            with f2:
                f_mcq = st.selectbox("Filter Type", ["All", "MCQs Only", "Non-MCQ / Unknown"])
            with f3:
                f_limit = st.selectbox("Max Rows in Editor", [100, 250, 500], index=0)

            view_df = df_bank
            if f_sub != "All":
                view_df = view_df[view_df["subject"] == f_sub]
            if f_mcq == "MCQs Only":
                view_df = view_df[view_df["is_mcq"] == True]
            elif f_mcq == "Non-MCQ / Unknown":
                view_df = view_df[view_df["is_mcq"] == False]
            view_df = view_df.head(int(f_limit))

            unit_options = sorted({u["unit_name"] for u in sb.table("syllabus_units").select("unit_name").execute().data} | {"Unmapped"})
            edit_cols = ["id", "subject", "question_no", "question", "unit", "difficulty", "correct_answer", "is_mcq"]
            edited = st.data_editor(
                view_df[edit_cols],
                use_container_width=True,
                hide_index=True,
                disabled=["id", "subject", "question_no", "question"],
                column_config={
                    "unit": st.column_config.SelectboxColumn("Unit", options=unit_options, required=True),
                    "difficulty": st.column_config.SelectboxColumn("Difficulty", options=["Easy", "Medium", "Hard"], required=True),
                    "correct_answer": st.column_config.TextColumn("Key"),
                    "is_mcq": st.column_config.CheckboxColumn("MCQ?"),
                },
            )
            if st.button("Save Admin Edits to Supabase", type="primary"):
                orig_map = view_df.set_index("id").to_dict("index")
                changed = 0
                for _, row in edited.iterrows():
                    qid = row["id"]
                    orig = orig_map[qid]
                    if (
                        row["unit"] != orig["unit"]
                        or row["difficulty"] != orig["difficulty"]
                        or row["correct_answer"] != orig["correct_answer"]
                        or bool(row["is_mcq"]) != bool(orig["is_mcq"])
                    ):
                        sb.table("questions").update({
                            "unit": row["unit"],
                            "difficulty": row["difficulty"],
                            "correct_answer": row["correct_answer"],
                            "is_mcq": bool(row["is_mcq"]),
                        }).eq("id", qid).execute()
                        changed += 1
                st.success(f"Updated {changed} question(s) in Supabase.")

    # --- Tab 4: Student-Flagged Questions Review ---
    with tab_flags:
        st.subheader("Student-Flagged Questions for Cross Verification")
        status_filter = st.selectbox("Flag Status", ["open", "resolved", "dismissed", "All"], index=0)
        try:
            q_flags = sb.table("question_flags").select("*").order("created_at", desc=True)
            if status_filter != "All":
                q_flags = q_flags.eq("status", status_filter)
            flags = q_flags.limit(200).execute().data
        except Exception:
            st.warning(
                "Table `question_flags` was not found in Supabase yet. Run the `question_flags` SQL snippet in Supabase SQL Editor."
            )
            return

        if not flags:
            st.info(f"No `{status_filter}` flagged questions found.")
            return

        q_ids = list({f["question_id"] for f in flags if f.get("question_id")})
        q_lookup: Dict[str, Dict] = {}
        for start in range(0, len(q_ids), 100):
            batch_qs = sb.table("questions").select("*").in_("id", q_ids[start:start + 100]).execute().data
            for item in batch_qs:
                q_lookup[item["id"]] = item

        unit_choices = sorted({u["unit_name"] for u in sb.table("syllabus_units").select("unit_name").execute().data} | {"Unmapped"})

        for fl in flags:
            qid = fl["question_id"]
            q_obj = q_lookup.get(qid)
            if not q_obj:
                continue
            fid = fl["id"]
            with st.container(border=True):
                st.markdown(
                    f"**Flag ({fl['status'].upper()})** · Reported: **{fl['reasons']}** · "
                    f"Source: `{q_obj.get('source_file', '')}` ({q_obj.get('question_no', '')})"
                )
                if fl.get("note"):
                    st.caption(f"Student Note: {fl['note']}")

                c_sub, c_unit, c_key, c_mcq = st.columns([1.2, 2.2, 0.8, 0.8])
                new_sub = c_sub.selectbox(
                    "Subject",
                    options=list(SUBJECTS),
                    index=list(SUBJECTS).index(q_obj["subject"]) if q_obj["subject"] in SUBJECTS else 0,
                    key=f"fl_sub_{fid}",
                )
                curr_unit = strip_unit_number(q_obj.get("unit", "Unmapped")) or "Unmapped"
                if curr_unit not in unit_choices:
                    unit_choices_local = [curr_unit] + unit_choices
                else:
                    unit_choices_local = unit_choices
                new_unit = c_unit.selectbox(
                    "Unit",
                    options=unit_choices_local,
                    index=unit_choices_local.index(curr_unit),
                    key=f"fl_unit_{fid}",
                )
                new_key = c_key.text_input("Answer Key", value=str(q_obj.get("correct_answer", "")), key=f"fl_key_{fid}")
                new_mcq = c_mcq.checkbox("Active MCQ?", value=bool(q_obj.get("is_mcq", True)), key=f"fl_mcq_{fid}")

                new_qtext = st.text_area("Question Text (edit to fix symbols/formulas if needed)", value=q_obj.get("question", ""), key=f"fl_qtxt_{fid}", height=90)
                st.caption("Live Formula Preview:")
                st.markdown(new_qtext or "_(Empty)_")

                o_c1, o_c2 = st.columns(2)
                new_o1 = o_c1.text_input("Option (1)", value=str(q_obj.get("option_1", "")), key=f"fl_o1_{fid}")
                new_o2 = o_c2.text_input("Option (2)", value=str(q_obj.get("option_2", "")), key=f"fl_o2_{fid}")
                o_c3, o_c4 = st.columns(2)
                new_o3 = o_c3.text_input("Option (3)", value=str(q_obj.get("option_3", "")), key=f"fl_o3_{fid}")
                new_o4 = o_c4.text_input("Option (4)", value=str(q_obj.get("option_4", "")), key=f"fl_o4_{fid}")

                b1, b2, _ = st.columns([1.3, 1, 3])
                if b1.button("Save Fix & Resolve", key=f"fl_save_{fid}", type="primary"):
                    sb.table("questions").update({
                        "subject": new_sub,
                        "unit": new_unit,
                        "question": new_qtext,
                        "option_1": new_o1,
                        "option_2": new_o2,
                        "option_3": new_o3,
                        "option_4": new_o4,
                        "correct_answer": new_key.strip() or "Unknown",
                        "is_mcq": bool(new_mcq),
                    }).eq("id", qid).execute()
                    sb.table("question_flags").update({"status": "resolved"}).eq("id", fid).execute()
                    st.success("Question updated and flag marked resolved.")
                    st.rerun()
                if b2.button("Dismiss Flag", key=f"fl_dis_{fid}"):
                    sb.table("question_flags").update({"status": "dismissed"}).eq("id", fid).execute()
                    st.rerun()


# ---------------------------------------------------------------------------
# Student Registration / Login Gate
# ---------------------------------------------------------------------------
def render_student_auth(sb: Client):
    st.markdown(
        '<div class="jee-hero">'
        '<h2>JEE Main PrepVibe</h2>'
        '<p>Personalized Physics, Chemistry & Mathematics Tests with Performance Monitor.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    col_info, col_auth = st.columns([1.05, 1.25], gap="large")
    with col_info:
        st.markdown(
            """
            <div class="jee-auth-showcase">
                <h3>Built for Focused JEE Practice</h3>
                <div class="jee-feature-pill"><strong>Unit-Wise Mix & Match:</strong> Pick specific units or Select All across Physics, Chemistry & Mathematics.</div>
                <div class="jee-feature-pill"><strong>Real Exam Interface:</strong> Clean white canvas, 1 question at a time, 2 min/question timer, +4 / -1 / 0 scoring.</div>
                <div class="jee-feature-pill"><strong>Scorecard & PDF Booklet:</strong> Instant answer analysis, Score % tracking, and printable Question Booklets.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_auth:
        tab_login, tab_reg = st.tabs(["Sign In", "New Student Registration"])

        with tab_login:
            with st.form("student_login_form"):
                email = st.text_input("Email Address").strip().lower()
                pwd = st.text_input("Password", type="password")
                if st.form_submit_button("Sign In to Portal", type="primary", use_container_width=True):
                    res = sb.table("students").select("*").eq("email", email).execute().data
                    if res and verify_password(pwd, res[0]["password_hash"]):
                        st.session_state["student"] = res[0]
                        st.session_state["login_quote"] = _pick_login_quote(st.session_state.get("last_login_quote"))
                        st.session_state["last_login_quote"] = st.session_state["login_quote"]
                        st.rerun()
                    else:
                        st.error("Invalid email or password.")

        with tab_reg:
            with st.form("student_register_form"):
                full_name = st.text_input("Full Name").strip()
                email = st.text_input("Email Address").strip().lower()
                pwd = st.text_input("Create Password (min 6 chars)", type="password")
                if st.form_submit_button("Create Account & Start", type="primary", use_container_width=True):
                    if not full_name or "@" not in email or len(pwd) < 6:
                        st.error("Please enter valid name, email, and at least 6-character password.")
                    else:
                        existing = sb.table("students").select("id").eq("email", email).execute().data
                        if existing:
                            st.error("An account with this email already exists. Please Sign In.")
                        else:
                            created = sb.table("students").insert({
                                "full_name": full_name,
                                "email": email,
                                "password_hash": hash_password(pwd),
                            }).execute().data[0]
                            st.session_state["student"] = created
                            st.session_state["login_quote"] = _pick_login_quote(st.session_state.get("last_login_quote"))
                            st.session_state["last_login_quote"] = st.session_state["login_quote"]
                            st.success("Registered successfully!")
                            st.rerun()


# ---------------------------------------------------------------------------
# Student Mock Test Builder, Runner & Submission Review
# ---------------------------------------------------------------------------
def finalize_and_score_test(sb: Client):
    test = st.session_state["active_test"]
    questions = test["questions"]
    responses = test["responses"]
    flags = test.get("flags", {})
    total_allotted = test["total_allotted_sec"]
    elapsed = int(time.time() - test["start_epoch"])
    time_taken = min(max(1, elapsed), total_allotted)

    correct_cnt = 0
    wrong_cnt = 0
    skipped_cnt = 0
    marks_obtained = 0
    review_rows = []

    for q in questions:
        qid = q["id"]
        sel = responses.get(qid)
        corr = str(q["correct_answer"]).strip()
        if sel is None:
            skipped_cnt += 1
            status = "skipped"
            delta = 0
        elif sel == corr:
            correct_cnt += 1
            status = "correct"
            delta = 4
        else:
            wrong_cnt += 1
            status = "wrong"
            delta = -1
        marks_obtained += delta
        review_rows.append({
            "question": q,
            "selected": sel,
            "correct": corr,
            "status": status,
            "delta": delta,
        })

    student = st.session_state["student"]
    attempt_row = sb.table("test_attempts").insert({
        "student_id": student["id"],
        "test_date": datetime.now(timezone.utc).isoformat(),
        "subjects_covered": ", ".join(test["subjects"]),
        "units_covered": ", ".join(test["units"]),
        "total_questions": len(questions),
        "full_marks": len(questions) * 4,
        "marks_obtained": marks_obtained,
        "correct_count": correct_cnt,
        "wrong_count": wrong_cnt,
        "skipped_count": skipped_cnt,
        "time_taken_sec": time_taken,
        "total_allotted_sec": total_allotted,
    }).execute().data[0]

    ans_payload = [
        {
            "attempt_id": attempt_row["id"],
            "question_id": r["question"]["id"],
            "selected_option": r["selected"],
            "correct_answer": r["correct"],
            "status": r["status"],
            "marks_awarded": r["delta"],
        }
        for r in review_rows
    ]
    if ans_payload:
        sb.table("attempt_answers").insert(ans_payload).execute()

    # Batch-save any student flags collected instantly in session memory (zero test-time delay!)
    if flags:
        flag_payload = [
            {
                "question_id": qid,
                "student_id": student["id"],
                "attempt_id": attempt_row["id"],
                "reasons": ", ".join(finfo.get("reasons", [])) or "Reported Issue",
                "note": finfo.get("note", ""),
                "status": "open",
            }
            for qid, finfo in flags.items()
            if finfo.get("reasons") or finfo.get("note")
        ]
        if flag_payload:
            try:
                sb.table("question_flags").insert(flag_payload).execute()
            except Exception:
                pass

    st.session_state["last_review"] = {
        "attempt": attempt_row,
        "rows": review_rows,
        "flagged_count": len(flags),
    }
    del st.session_state["active_test"]
    st.rerun(scope="app")


def _on_option_checkbox_change(qid: str, opt_num: str):
    """Enforces single-select checkbox behavior beside options (1)-(4); unchecking resets to Skipped."""
    test = st.session_state.get("active_test")
    if not test:
        return
    is_checked = bool(st.session_state.get(f"chk_{qid}_{opt_num}", False))
    if is_checked:
        test["responses"][qid] = opt_num
        for other in ("1", "2", "3", "4"):
            if other != opt_num:
                st.session_state[f"chk_{qid}_{other}"] = False
    else:
        if test["responses"].get(qid) == opt_num:
            test["responses"][qid] = None


def _on_skip_click(qid: str, idx: int, total_q: int):
    """Clears current response & checkboxes safely BEFORE rerun renders widgets."""
    test = st.session_state.get("active_test")
    if not test:
        return
    test["responses"][qid] = None
    for opt_num in ("1", "2", "3", "4"):
        st.session_state[f"chk_{qid}_{opt_num}"] = False
    if idx < total_q - 1:
        test["current_idx"] = idx + 1


def _on_nav_click(target_idx: int):
    test = st.session_state.get("active_test")
    if test:
        test["current_idx"] = target_idx


def _on_flag_checkbox_change(qid: str):
    """Updates student flags instantly in session state as checkboxes are toggled."""
    test = st.session_state.get("active_test")
    if not test:
        return
    reasons = [
        reason
        for i, reason in enumerate(FLAG_REASON_OPTIONS)
        if st.session_state.get(f"flg_chk_{qid}_{i}", False)
    ]
    if reasons:
        test.setdefault("flags", {})[qid] = {"reasons": reasons, "note": ""}
    else:
        test.setdefault("flags", {}).pop(qid, None)


def _clear_flag_click(qid: str):
    test = st.session_state.get("active_test")
    if test:
        test.setdefault("flags", {}).pop(qid, None)
    for i in range(len(FLAG_REASON_OPTIONS)):
        st.session_state[f"flg_chk_{qid}_{i}"] = False


def _exit_review_to_home():
    st.session_state.pop("last_review", None)


def _mark_booklet_downloaded(sb: Client, attempt_id: str):
    """Records booklet download timestamp in Supabase test_attempts and updates active review state."""
    if not attempt_id:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("test_attempts").update({"booklet_downloaded_at": now_iso}).eq("id", attempt_id).execute()
    except Exception:
        pass
    last_rev = st.session_state.get("last_review")
    if isinstance(last_rev, dict) and last_rev.get("attempt", {}).get("id") == attempt_id:
        last_rev["attempt"]["booklet_downloaded_at"] = now_iso


def render_submission_review(sb: Client):
    rev = st.session_state["last_review"]
    att = rev["attempt"]
    rows = rev["rows"]
    student = st.session_state["student"]

    full_marks = max(1, int(att["full_marks"]))
    pct = round((int(att["marks_obtained"]) / full_marks) * 100.0, 1)

    top_msg, top_home = st.columns([3.5, 1.3])
    top_msg.success("Mock Test Submitted & Saved to Your Performance Record!")
    top_home.button("⬅️ Back to Home / Test Builder", on_click=_exit_review_to_home, use_container_width=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Marks Obtained", f"{att['marks_obtained']} / {att['full_marks']}")
    c2.metric("Score %", f"{pct}%")
    c3.metric("Correct (+4)", att["correct_count"])
    c4.metric("Wrong (-1)", att["wrong_count"])
    c5.metric("Time Taken", f"{format_duration(att['time_taken_sec'])} / {format_duration(att['total_allotted_sec'])}")

    if rev.get("flagged_count"):
        st.info(f"Sent {rev['flagged_count']} flagged question(s) to Admin for cross verification.")

    col_pdf_opt, col_pdf_btn = st.columns([2, 1.5])
    hide_skipped_pdf = col_pdf_opt.checkbox(
        "Practice Mode: Hide correct answers for Wrong & Unattempted questions in PDF",
        value=False,
        key="rev_pdf_hide_skip",
    )
    try:
        pdf_bytes = build_question_booklet_pdf(
            sb=sb,
            student_name=student["full_name"],
            attempt=att,
            review_rows=rows,
            hide_skipped_answers=hide_skipped_pdf,
        )
        pdf_label = (
            "📄 Download Practice Booklet PDF"
            if hide_skipped_pdf
            else "📄 Download Answer & Revision Booklet PDF"
        )
        pdf_filename = (
            f"JEE_Practice_Booklet_{att['test_date'][:10]}.pdf"
            if hide_skipped_pdf
            else f"JEE_Answer_Revision_Booklet_{att['test_date'][:10]}.pdf"
        )
        col_pdf_btn.download_button(
            pdf_label,
            data=pdf_bytes,
            file_name=pdf_filename,
            mime="application/pdf",
            type="primary",
            key=f"rev_dl_pdf_{att['id']}_{'prac' if hide_skipped_pdf else 'ans'}",
            on_click=_mark_booklet_downloaded,
            args=(sb, att["id"]),
        )
        if att.get("booklet_downloaded_at"):
            col_pdf_btn.caption("✅ Booklet download recorded on your Performance Board.")
    except Exception as exc:
        col_pdf_btn.warning(f"Could not generate PDF ({exc}). You can still review below or download from Performance Record.")

    st.subheader("Question-by-Question Answer Review")
    for idx, item in enumerate(rows, start=1):
        q = item["question"]
        status = item["status"]
        sel = item["selected"]
        corr = item["correct"]
        unit_clean = strip_unit_number(q.get("unit", "Unmapped"))

        with st.container(border=True):
            st.markdown(f"**Q{idx}. [{q['subject']} · {unit_clean}]** — {q['question']}")

            if status == "correct":
                # For correct: show ONLY student's attempted option
                st.success(f"Correct (+4) — Your Attempted Option: ({sel})")
                render_option_content(sb, q[f"option_{sel}"])
            elif status == "wrong":
                # For wrong: show BOTH attempted option and correct answer
                st.error(f"Wrong (-1) — Attempted: ({sel}) | Correct Answer: ({corr})")
                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown(f"**Your Attempted Option ({sel}):**")
                    render_option_content(sb, q[f"option_{sel}"])
                with col_b:
                    st.markdown(f"**Correct Answer ({corr}):**")
                    render_option_content(sb, q[f"option_{corr}"])
            else:
                # For skip: show ONLY the correct answer (Option 2A)
                st.warning(f"Skipped (0) — Correct Answer: ({corr})")
                render_option_content(sb, q[f"option_{corr}"])

    if st.button("Design Another Mock Test", type="primary"):
        del st.session_state["last_review"]
        st.rerun()


def render_active_test(sb: Client):
    test = st.session_state["active_test"]
    questions = test["questions"]
    total_q = len(questions)
    idx = min(max(0, test.get("current_idx", 0)), total_q - 1)
    test["current_idx"] = idx
    q = questions[idx]
    qid = q["id"]

    # Live countdown fragment (fixed floating bar visible even when scrolling down)
    @st.fragment(run_every=1)
    def live_timer_banner():
        elapsed = int(time.time() - test["start_epoch"])
        remaining = test["total_allotted_sec"] - elapsed
        if remaining <= 0:
            st.error("Time is up! Submitting automatically...")
            finalize_and_score_test(sb)
        else:
            ans_cnt = sum(1 for item in questions if test["responses"].get(item["id"]) is not None)
            flg_cnt = len(test.get("flags", {}))
            st.markdown(
                f'<div class="jee-timer-bar">'
                f'⏱️ <strong>{format_duration(remaining)}</strong> left '
                f'<span style="color:#64748B;">/ {format_duration(test["total_allotted_sec"])}</span> &nbsp;|&nbsp; '
                f'Q<strong>{idx + 1}/{total_q}</strong> &nbsp;|&nbsp; '
                f'Ans: <strong>{ans_cnt}</strong> &nbsp;|&nbsp; '
                f'Flag: <strong>{flg_cnt}</strong>'
                f'</div><div class="jee-timer-spacer"></div>',
                unsafe_allow_html=True,
            )

    live_timer_banner()

    # Clickable Question Number Palette (jump directly to any question)
    if st.toggle(f"Show Question Palette ({total_q} Questions)", value=False, key="pal_toggle"):
        cols_per_row = 10
        for row_start in range(0, total_q, cols_per_row):
            row_cols = st.columns(cols_per_row)
            for offset in range(cols_per_row):
                q_num = row_start + offset
                if q_num >= total_q:
                    break
                item_id = questions[q_num]["id"]
                is_curr = q_num == idx
                is_ans = test["responses"].get(item_id) is not None
                is_flg = item_id in test.get("flags", {})
                prefix = "●" if is_curr else ("✓" if is_ans else "")
                suffix = "🚩" if is_flg else ""
                label = f"{prefix}{q_num + 1}{suffix}".strip()
                row_cols[offset].button(
                    label,
                    key=f"pal_{q_num}",
                    type="primary" if is_curr else "secondary",
                    on_click=_on_nav_click,
                    args=(q_num,),
                    use_container_width=True,
                )

    # Pure White Single-Question Card (NO Easy / Medium / Hard shown!)
    unit_clean = strip_unit_number(q.get("unit", "Unmapped"))
    existing_flag = test.get("flags", {}).get(qid)

    with st.container(border=True):
        hdr_l, hdr_r = st.columns([4, 1.3])
        with hdr_l:
            st.markdown(f"### Q{idx + 1}. &nbsp; `{q['subject']} · {unit_clean}`")
        with hdr_r:
            btn_lbl = "🚩 Flagged ✓" if existing_flag else "🚩 Flag Issue"
            with st.popover(btn_lbl, use_container_width=True):
                st.caption("Select one or more issues (auto-saved immediately):")
                saved_reasons = set(existing_flag.get("reasons", [])) if existing_flag else set()
                for r_idx, reason_txt in enumerate(FLAG_REASON_OPTIONS):
                    flg_key = f"flg_chk_{qid}_{r_idx}"
                    if flg_key not in st.session_state:
                        st.session_state[flg_key] = reason_txt in saved_reasons
                    st.checkbox(
                        reason_txt,
                        key=flg_key,
                        on_change=_on_flag_checkbox_change,
                        args=(qid,),
                    )
                if existing_flag:
                    st.button("Clear Flag", key=f"flg_clr_{qid}", on_click=_clear_flag_click, args=(qid,))

        if existing_flag:
            st.caption(f"🚩 Marked for Admin verification: {', '.join(existing_flag.get('reasons', []))}")

        st.markdown(q["question"])
        st.divider()

        # Sync checkbox keys with stored response before rendering options
        curr_sel = test["responses"].get(qid)
        for opt_num in ("1", "2", "3", "4"):
            chk_key = f"chk_{qid}_{opt_num}"
            desired = curr_sel == opt_num
            if chk_key not in st.session_state:
                st.session_state[chk_key] = desired

        # Single-select Checkboxes directly beside options (1)-(4)
        for opt_num in ("1", "2", "3", "4"):
            c_chk, c_lbl, c_body = st.columns([0.06, 0.07, 0.87])
            with c_chk:
                st.checkbox(
                    f"Option {opt_num}",
                    key=f"chk_{qid}_{opt_num}",
                    label_visibility="collapsed",
                    on_change=_on_option_checkbox_change,
                    args=(qid, opt_num),
                )
            with c_lbl:
                st.markdown(f"**({opt_num})**")
            with c_body:
                render_option_content(sb, q[f"option_{opt_num}"])

    # Navigation Bar: Previous | Skip | Next | Submit Mock Test
    nav1, nav2, nav3, nav_spacer, nav4 = st.columns([1.1, 1.1, 1.1, 1.4, 1.5])
    nav1.button(
        "⬅️ Previous",
        disabled=(idx == 0),
        on_click=_on_nav_click,
        args=(idx - 1,),
        use_container_width=True,
    )
    nav2.button(
        "⏭️ Skip",
        on_click=_on_skip_click,
        args=(qid, idx, total_q),
        use_container_width=True,
    )
    nav3.button(
        "Next ➡️",
        disabled=(idx >= total_q - 1),
        on_click=_on_nav_click,
        args=(idx + 1,),
        use_container_width=True,
    )

    if nav4.button("✅ Submit Mock Test", type="primary", use_container_width=True):
        finalize_and_score_test(sb)


def render_student_portal(sb: Client):
    if not st.session_state.get("student"):
        render_student_auth(sb)
        return

    student = st.session_state["student"]
    top_l, top_r = st.columns([4, 1])
    with top_l:
        st.markdown(f"Signed in as **{student['full_name']}** ({student['email']})")
    with top_r:
        if st.button("Sign Out"):
            st.session_state.pop("student", None)
            st.session_state.pop("active_test", None)
            st.session_state.pop("last_review", None)
            st.session_state.pop("login_quote", None)
            st.rerun()

    if st.session_state.get("active_test"):
        render_active_test(sb)
        return

    if st.session_state.get("last_review"):
        render_submission_review(sb)
        return

    if not st.session_state.get("login_quote"):
        st.session_state["login_quote"] = _pick_login_quote(st.session_state.get("last_login_quote"))
        st.session_state["last_login_quote"] = st.session_state["login_quote"]

    quote_html = html.escape(st.session_state["login_quote"])
    name_html = html.escape(student["full_name"])
    st.markdown(
        '<div class="jee-hero">'
        f'<h2>Welcome back, {name_html}!</h2>'
        f'<div class="jee-quote-box"><span>✨</span><span>“{quote_html}”</span></div>'
        '</div>',
        unsafe_allow_html=True,
    )

    tab_build, tab_history = st.tabs(["Design Custom Mock Test", "Performance Record"])

    with tab_build:
        st.subheader("1. Select Subject Units (Leave a subject empty to exclude it)")
        mcq_rows = fetch_all_questions(sb, mcq_only=True)
        if not mcq_rows:
            st.warning("No MCQ questions uploaded yet. Ask Admin to upload syllabus & CSV.")
        else:
            # Group available units by subject (clean names without unit numbers)
            units_by_sub: Dict[str, List[str]] = {}
            for sub in SUBJECTS:
                sub_units = sorted({
                    strip_unit_number(q["unit"]) or "Unmapped"
                    for q in mcq_rows
                    if q["subject"] == sub
                })
                units_by_sub[sub] = sub_units

            c_phy, c_chem, c_math = st.columns(3)
            selected_units_by_sub: Dict[str, List[str]] = {}
            badge_styles = {
                "Physics": ("jee-sub-phy", "Physics"),
                "Chemistry": ("jee-sub-chem", "Chemistry"),
                "Mathematics": ("jee-sub-math", "Mathematics"),
            }

            for col_widget, sub in ((c_phy, "Physics"), (c_chem, "Chemistry"), (c_math, "Mathematics")):
                with col_widget:
                    css_cls, lbl = badge_styles[sub]
                    st.markdown(f'<div class="jee-sub-badge {css_cls}">{lbl}</div>', unsafe_allow_html=True)
                    opts = ["Select All"] + units_by_sub[sub]
                    picked = st.multiselect(
                        f"{sub} Units",
                        options=opts,
                        default=[],
                        placeholder=f"Choose {sub} units (optional)",
                        label_visibility="collapsed",
                        key=f"pick_units_{sub}",
                    )
                    if "Select All" in picked:
                        selected_units_by_sub[sub] = units_by_sub[sub]
                    else:
                        selected_units_by_sub[sub] = picked

            unit_pool = [
                q for q in mcq_rows
                if (strip_unit_number(q["unit"]) or "Unmapped") in selected_units_by_sub.get(q["subject"], [])
            ]
            avail_by_sub = {
                sub: sum(1 for q in unit_pool if q["subject"] == sub)
                for sub in SUBJECTS
                if selected_units_by_sub.get(sub)
            }
            active_subs = [sub for sub in SUBJECTS if avail_by_sub.get(sub, 0) > 0]
            max_q = len(unit_pool)

            if max_q == 0:
                st.info("Select **Select All** or one or more units in at least one subject above to configure your test.")
            else:
                st.subheader("2. Set Total Number of Questions & Review Test Rules")
                n_q = st.number_input(
                    "Total Questions",
                    min_value=1,
                    max_value=max_q,
                    value=min(15, max_q),
                    step=1,
                )

                quotas = compute_subject_quotas(avail_by_sub, int(n_q))
                split_summary = " · ".join(f"{sub}: <strong>{quotas[sub]} Qs</strong>" for sub in SUBJECTS if quotas.get(sub, 0) > 0)
                allotted_min = int(n_q) * 2
                full_marks = int(n_q) * 4

                st.markdown(
                    f"""
                    <div class="jee-rules-card">
                        <strong>Mock Test Details & Process:</strong><br/>
                        • <strong>Question Distribution ({int(n_q)} Total):</strong> {split_summary} &nbsp;<em>(Selected across {sum(len(selected_units_by_sub[s]) for s in active_subs)} unit(s))</em><br/>
                        • <strong>Time Allotted:</strong> {allotted_min} minutes ({int(n_q)} × 2 minutes per question) with automatic submission when time ends.<br/>
                        • <strong>Marking Scheme:</strong> <strong>+4</strong> for Correct, <strong>-1</strong> for Wrong, <strong>0</strong> for Skipped.<br/>
                        • <strong>Test Interface:</strong> One question at a time on a clean white canvas with checkboxes beside options (1)–(4), <strong>Previous / Skip / Next</strong> navigation, and an instant <strong>🚩 Flag Issue</strong> option to report subject, unit, or symbol issues.<br/>
                        • <strong>Score Publication:</strong> Immediate answer review + downloadable <strong>Question Booklet PDF</strong> linked to your Performance Record.
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if st.button(f"Start Mock Test ({int(n_q)} Questions · {full_marks} Marks)", type="primary"):
                    chosen, diff_counts, _ = select_subject_divided_mcqs(unit_pool, int(n_q))
                    selected_unit_names = sorted({
                        u for s in active_subs for u in selected_units_by_sub[s]
                    })
                    st.session_state["active_test"] = {
                        "questions": chosen,
                        "responses": {},
                        "flags": {},
                        "current_idx": 0,
                        "subjects": active_subs,
                        "units": selected_unit_names,
                        "diff_counts": diff_counts,
                        "start_epoch": time.time(),
                        "total_allotted_sec": int(n_q) * 120,
                    }
                    st.rerun()

    with tab_history:
        st.subheader("Your Performance Record")
        attempts = (
            sb.table("test_attempts")
            .select("*")
            .eq("student_id", student["id"])
            .order("test_date", desc=True)
            .execute()
            .data
        )
        if not attempts:
            st.info("No test attempts recorded yet.")
        else:
            table_rows = []
            attempt_labels = []
            for a in attempts:
                dt_str = a["test_date"][:16].replace("T", " ")
                full_m = max(1, int(a["full_marks"]))
                obt_m = int(a["marks_obtained"])
                pct = round((obt_m / full_m) * 100.0, 1)
                dl_raw = a.get("booklet_downloaded_at")
                dl_status = f"✅ {str(dl_raw)[:16].replace('T', ' ')}" if dl_raw else "Not yet"
                table_rows.append({
                    "Date of Test": dt_str,
                    "Subjects": a.get("subjects_covered", ""),
                    "Unit Covered": a["units_covered"],
                    "Full Marks": full_m,
                    "Marks Obtained": obt_m,
                    "Score %": f"{pct}%",
                    "Correct Answers": a["correct_count"],
                    "Wrong Answers": a["wrong_count"],
                    "Skipped": a["skipped_count"],
                    "Time Taken / Total Allotted Time": (
                        f"{format_duration(a['time_taken_sec'])} / {format_duration(a['total_allotted_sec'])}"
                    ),
                    "Booklet Downloaded": dl_status,
                })
                attempt_labels.append(
                    f"{dt_str} · {a.get('subjects_covered', '')} · {obt_m}/{full_m} ({pct}%)"
                )

            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

            st.divider()
            st.subheader("Download Question Booklet PDF for Any Past Test")
            col_pick, col_chk = st.columns([2.2, 1.5])
            picked_idx = col_pick.selectbox(
                "Select Test Attempt",
                options=list(range(len(attempts))),
                format_func=lambda i: attempt_labels[i],
            )
            hide_skip_hist = col_chk.checkbox(
                "Practice Mode: Hide correct answers for Wrong & Unattempted questions in PDF",
                value=False,
                key="hist_pdf_hide_skip",
            )

            chosen_att = attempts[picked_idx]
            if st.button("📄 Prepare Question Booklet PDF", type="primary", key="hist_prepare_pdf_btn"):
                st.session_state["hist_pdf_attempt_id"] = chosen_att["id"]

            if st.session_state.get("hist_pdf_attempt_id") == chosen_att["id"]:
                ans_rows = (
                    sb.table("attempt_answers")
                    .select("*")
                    .eq("attempt_id", chosen_att["id"])
                    .execute()
                    .data
                )
                q_ids = [ar["question_id"] for ar in ans_rows]
                q_map: Dict[str, Dict] = {}
                for start in range(0, len(q_ids), 100):
                    q_batch = sb.table("questions").select("*").in_("id", q_ids[start:start + 100]).execute().data
                    for q_item in q_batch:
                        q_map[q_item["id"]] = q_item

                hist_review = [
                    {
                        "question": q_map[ar["question_id"]],
                        "selected": ar.get("selected_option"),
                        "correct": ar.get("correct_answer", ""),
                        "status": ar.get("status", "skipped"),
                        "delta": ar.get("marks_awarded", 0),
                    }
                    for ar in ans_rows
                    if ar["question_id"] in q_map
                ]
                if not hist_review:
                    st.warning("Question details were not found for this attempt.")
                else:
                    try:
                        pdf_data = build_question_booklet_pdf(
                            sb=sb,
                            student_name=student["full_name"],
                            attempt=chosen_att,
                            review_rows=hist_review,
                            hide_skipped_answers=hide_skip_hist,
                        )
                        hist_dl_label = (
                            "⬇️ Download Practice Booklet PDF (Wrong & Unattempted Answers Hidden)"
                            if hide_skip_hist
                            else "⬇️ Download Answer & Revision Booklet PDF"
                        )
                        hist_filename = (
                            f"JEE_Practice_Booklet_{chosen_att['test_date'][:10]}.pdf"
                            if hide_skip_hist
                            else f"JEE_Answer_Revision_Booklet_{chosen_att['test_date'][:10]}.pdf"
                        )
                        st.download_button(
                            hist_dl_label,
                            data=pdf_data,
                            file_name=hist_filename,
                            mime="application/pdf",
                            type="primary",
                            key=f"hist_dl_pdf_{chosen_att['id']}_{'prac' if hide_skip_hist else 'ans'}",
                            on_click=_mark_booklet_downloaded,
                            args=(sb, chosen_att["id"]),
                        )
                    except Exception as exc:
                        st.error(f"Could not generate PDF: {exc}")


# ---------------------------------------------------------------------------
# App Navigation
# ---------------------------------------------------------------------------
def main():
    inject_custom_theme(is_active_test=bool(st.session_state.get("active_test")))
    sb = get_supabase()
    with st.sidebar:
        st.title("Selection Panel")
        mode = st.radio("Workspace", ["Student", "Admin"])

    if mode == "Admin Console":
        render_admin_panel(sb)
    else:
        render_student_portal(sb)


if __name__ == "__main__":
    main()
