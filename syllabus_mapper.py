"""
syllabus_mapper.py
Parses uploaded JEE Main syllabus PDFs/text into subject units, automatically maps
questions to their matching syllabus unit (adding a `unit` column beside Question),
auto-tags Easy / Medium / Hard difficulty, and selects 35% Easy / 30% Medium / 35% Hard MCQs.
"""

import io
import random
import re
from typing import List, Dict, Tuple, Optional

from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

SUBJECTS = ("Physics", "Chemistry", "Mathematics")

STOPWORDS = {
    "the", "and", "of", "in", "to", "a", "an", "for", "with", "on", "by", "from",
    "is", "are", "be", "as", "at", "its", "their", "using", "based", "simple",
    "properties", "concept", "basic", "law", "laws", "applications", "elementary",
    "idea", "ideas", "unit", "units", "chapter", "jee", "main", "syllabus",
}


def extract_syllabus_text(file_bytes: bytes, filename: str) -> str:
    """Extracts plain text from an uploaded PDF or TXT syllabus file."""
    low = filename.lower()
    if low.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)
    return file_bytes.decode("utf-8", errors="replace")


def _clean_keywords(text: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", text.lower())
    seen = []
    for tok in tokens:
        if tok not in STOPWORDS and tok not in seen:
            seen.append(tok)
    return seen[:60]


def parse_syllabus_document(raw_text: str) -> List[Dict]:
    """
    Parses JEE Main syllabus text (NTA / coaching PDF or plain text) into structured units:
    [{'subject': 'Physics', 'unit_name': 'Unit 1: Physics and Measurement', 'keywords': [...]}]
    Supports formats like:
      - SECTION A / PHYSICS / CHEMISTRY / MATHEMATICS headings
      - UNIT 1: Kinematics / Unit-2: Laws of Motion / 1. Electrostatics
    """
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in raw_text.splitlines()]
    lines = [ln for ln in lines if ln]

    current_subject = "Physics"
    parsed: List[Dict] = []
    current_unit_title = None
    current_body: List[str] = []

    subject_re = re.compile(r"^(?:part\s*[abc]\s*[-–:]\s*)?(physics|chemistry|mathematics|maths)\b", re.I)
    unit_re = re.compile(
        r"^(?:unit\s*[-–]?\s*(?:\d+|[IVXLCDM]+)\s*[:.\-–]?\s*(.+)|"
        r"(?:chapter\s*)?\d{1,2}\.\s+([A-Z][A-Za-z0-9 ,&\-()/]+))$",
        re.I,
    )

    def flush_unit():
        if current_unit_title:
            body_text = " ".join(current_body)
            kws = _clean_keywords(f"{current_unit_title} {body_text}")
            parsed.append({
                "subject": current_subject,
                "unit_name": current_unit_title.strip(" :-–."),
                "keywords": kws,
            })

    for ln in lines:
        m_sub = subject_re.match(ln)
        if m_sub and len(ln) <= 60:
            flush_unit()
            current_unit_title = None
            current_body = []
            sub_word = m_sub.group(1).lower()
            current_subject = "Mathematics" if sub_word in {"mathematics", "maths"} else sub_word.capitalize()
            continue

        m_unit = unit_re.match(ln)
        if m_unit and len(ln) <= 110:
            flush_unit()
            title_part = (m_unit.group(1) or m_unit.group(2) or ln).strip()
            # Keep clean normalized unit label
            prefix_m = re.match(r"^(unit\s*[-–]?\s*(?:\d+|[IVXLCDM]+))\s*[:.\-–]?\s*(.*)$", ln, re.I)
            if prefix_m and prefix_m.group(2):
                current_unit_title = f"{prefix_m.group(1).title()}: {prefix_m.group(2).strip()}"
            else:
                current_unit_title = title_part
            current_body = []
            continue

        if current_unit_title:
            current_body.append(ln)

    flush_unit()

    # Fallback if user pasted simple "Subject: Unit1, Unit2" lines without UNIT prefixes
    if not parsed:
        for ln in lines:
            if ":" in ln:
                head, tail = ln.split(":", 1)
                sub_low = head.strip().lower()
                sub = (
                    "Mathematics" if "math" in sub_low
                    else "Chemistry" if "chem" in sub_low
                    else "Physics" if "phy" in sub_low
                    else current_subject
                )
                for u in [x.strip() for x in re.split(r"[,;|]", tail) if x.strip()]:
                    parsed.append({
                        "subject": sub,
                        "unit_name": u,
                        "keywords": _clean_keywords(u),
                    })

    # Deduplicate by (subject, unit_name)
    unique_map: Dict[Tuple[str, str], Dict] = {}
    for item in parsed:
        key = (item["subject"], item["unit_name"])
        if key not in unique_map:
            unique_map[key] = item
        else:
            merged = list(dict.fromkeys(unique_map[key]["keywords"] + item["keywords"]))
            unique_map[key]["keywords"] = merged[:60]

    return list(unique_map.values())


def map_questions_to_units(
    questions: List[Dict],
    syllabus_units: List[Dict],
) -> List[str]:
    """
    Maps each question dict ({subject, question, option_1..4}) to its best-matching
    syllabus unit under the same subject using TF-IDF cosine similarity + keyword bonus.
    """
    by_subject: Dict[str, List[Dict]] = {s: [] for s in SUBJECTS}
    for u in syllabus_units:
        if u["subject"] in by_subject:
            by_subject[u["subject"]].append(u)

    # Pre-fit TF-IDF vectorizer per subject
    vectorizers: Dict[str, Tuple[Optional[TfidfVectorizer], object, List[Dict]]] = {}
    for sub, units in by_subject.items():
        if not units:
            continue
        docs = [f"{u['unit_name']} {' '.join(u.get('keywords', []))}" for u in units]
        try:
            vec = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
            mat = vec.fit_transform(docs)
        except ValueError:
            vec, mat = None, None
        vectorizers[sub] = (vec, mat, units)

    mapped_units: List[str] = []
    for q in questions:
        sub = q.get("subject", "Physics")
        if sub not in vectorizers:
            mapped_units.append("Unmapped")
            continue

        vec, mat, units = vectorizers[sub]
        q_blob = " ".join([
            str(q.get("question", "")),
            str(q.get("option_1", "")),
            str(q.get("option_2", "")),
            str(q.get("option_3", "")),
            str(q.get("option_4", "")),
        ])
        q_low = q_blob.lower()
        sims = cosine_similarity(vec.transform([q_blob]), mat).flatten() if vec is not None else [0.0] * len(units)

        best_idx = 0
        best_score = -1.0
        for idx, u in enumerate(units):
            kw_hits = sum(1 for kw in u.get("keywords", []) if len(kw) >= 4 and kw in q_low)
            score = float(sims[idx]) + 0.08 * min(kw_hits, 5)
            if score > best_score:
                best_score = score
                best_idx = idx

        mapped_units.append(units[best_idx]["unit_name"] if best_score > 0.01 else units[0]["unit_name"])

    return mapped_units


def estimate_difficulty(question_text: str, options: List[str]) -> str:
    """
    Auto-tags each question as Easy, Medium, or Hard based on structural & math complexity.
    Admin can override any tag inside the Admin Question Editor.
    """
    blob = f"{question_text} {' '.join(options)}"
    words = len(re.findall(r"\S+", question_text))
    score = 0

    if words >= 45:
        score += 2
    elif words >= 25:
        score += 1

    hard_markers = ["∫", "∑", "∏", "differential", "matrix", "matrices", "determinant",
                    "statement", "both", "equilibrium", "thermodynamic", "electrostatic",
                    "magnetic", "hybrid", "isomer", "locus", "ellipse", "hyperbola"]
    med_markers = ["/", "√", "²", "³", "⁻", "sin", "cos", "tan", "log", "ln", "lim", "mol", "ph"]

    low = blob.lower()
    score += min(sum(1 for m in hard_markers if m in low), 3)
    score += 1 if sum(1 for m in med_markers if m in low) >= 2 else 0

    if "[image:" in low:
        score += 1

    if score <= 1:
        return "Easy"
    if score <= 3:
        return "Medium"
    return "Hard"


def is_valid_mcq(row: Dict) -> bool:
    """Returns True only for MCQ rows with valid 1-4 answer key and non-empty options."""
    ans = str(row.get("correct_answer", "")).strip()
    if ans not in {"1", "2", "3", "4"}:
        return False
    filled_opts = sum(1 for k in ("option_1", "option_2", "option_3", "option_4") if str(row.get(k, "")).strip())
    return filled_opts >= 2


def select_balanced_mcqs(
    pool: List[Dict],
    n_questions: int,
    seed: int = None,
) -> Tuple[List[Dict], Dict[str, int]]:
    """
    Selects n_questions MCQs aiming for exact 35% Easy / 30% Medium / 35% Hard split.
    Gracefully backfills from remaining buckets if a small unit selection lacks enough
    questions in one difficulty tier.
    """
    rng = random.Random(seed)
    if n_questions >= len(pool):
        chosen = list(pool)
        rng.shuffle(chosen)
        counts = {
            "Easy": sum(1 for q in chosen if q.get("difficulty") == "Easy"),
            "Medium": sum(1 for q in chosen if q.get("difficulty") == "Medium"),
            "Hard": sum(1 for q in chosen if q.get("difficulty") == "Hard"),
        }
        return chosen, counts

    target_easy = round(0.35 * n_questions)
    target_med = round(0.30 * n_questions)
    target_hard = max(0, n_questions - target_easy - target_med)
    targets = {"Easy": target_easy, "Medium": target_med, "Hard": target_hard}

    buckets = {"Easy": [], "Medium": [], "Hard": []}
    for q in pool:
        d = q.get("difficulty", "Medium")
        buckets[d if d in buckets else "Medium"].append(q)

    for b in buckets.values():
        rng.shuffle(b)

    selected: List[Dict] = []
    used_ids = set()
    for tier in ("Easy", "Medium", "Hard"):
        take = buckets[tier][:targets[tier]]
        for q in take:
            selected.append(q)
            used_ids.add(q["id"])

    # Backfill if any tier had fewer questions than target
    if len(selected) < n_questions:
        leftover = [q for q in pool if q["id"] not in used_ids]
        rng.shuffle(leftover)
        selected.extend(leftover[: n_questions - len(selected)])

    rng.shuffle(selected)
    counts = {
        "Easy": sum(1 for q in selected if q.get("difficulty") == "Easy"),
        "Medium": sum(1 for q in selected if q.get("difficulty") == "Medium"),
        "Hard": sum(1 for q in selected if q.get("difficulty") == "Hard"),
    }
    return selected, counts
