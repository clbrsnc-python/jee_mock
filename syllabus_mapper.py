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


def strip_unit_number(unit_name: str) -> str:
    """Removes leading 'Unit 1:', 'Unit - II:', '1.' prefixes so only the clean unit name remains."""
    cleaned = re.sub(
        r"^(?:unit\s*[-–]?\s*(?:\d+|[ivxlcdm]+)|chapter\s*\d+|\d{1,2})\s*[:.\-–]+\s*",
        "",
        unit_name.strip(),
        flags=re.I,
    )
    return re.sub(r"\s+", " ", cleaned).strip(" :-–.")


def _format_unit_title(title: str) -> str:
    """Normalizes spacing and converts ALL-CAPS syllabus unit headings to clean readable Title Case."""
    title = strip_unit_number(title)
    # Fix missing spaces where pypdf joins words (e.g. 'ofpersons' left as-is, 'Unit3' handled above, 'd - and f-' -> 'd- and f-')
    title = re.sub(r"\s*,\s*", ", ", title)
    title = re.sub(r"\s+", " ", title).strip(" :-–.,")
    if not title:
        return ""

    letters = [c for c in title if c.isalpha()]
    upper_ratio = sum(1 for c in letters if c.isupper()) / max(1, len(letters))
    if upper_ratio > 0.65:
        small_words = {"and", "or", "of", "in", "to", "for", "with", "on", "the", "a", "an", "by", "from", "at", "as", "into"}
        preserve_upper = {"iupac", "dna", "rna", "em", "ac", "dc", "si", "ph", "3d", "2d"}
        words = title.split()
        out = []
        for i, w in enumerate(words):
            low = w.lower()
            # Keep chemical block prefixes like p-, d-, f-, s- lowercase
            if re.match(r"^[spdf]-?$", low):
                out.append(low)
            elif re.sub(r"[^a-z0-9]", "", low) in preserve_upper:
                out.append(w.upper())
            elif i > 0 and low in small_words:
                out.append(low)
            else:
                out.append(w.capitalize())
        title = " ".join(out)
    return title


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
    [{'subject': 'Physics', 'unit_name': 'Units and Measurements', 'keywords': [...]}]
    - Ignores Paper 2A (B.Arch) & Paper 2B (B.Planning) sections.
    - Keeps Physics/Chemistry/Mathematics strictly separated.
    - Prevents numbered sub-experiments (e.g. Unit 20 Experimental Skills items) from becoming fake units.
    - Strips unit numbers ('Unit 1:', 'Unit - II:') so Student UI shows clean unit names.
    """
    raw_lines = [re.sub(r"\s+", " ", ln).strip() for ln in raw_text.splitlines()]
    raw_lines = [ln for ln in raw_lines if ln]

    has_explicit_units = bool(re.search(r"\bunit\s*[-–]?\s*(?:\d+|[ivxlcdm]+)\b", raw_text, re.I))

    current_subject = "Physics"
    in_paper2 = False
    parsed: List[Dict] = []
    current_unit_title: Optional[str] = None
    current_body: List[str] = []

    paper2_stop_re = re.compile(
        r"\b(?:paper\s*[-–]?\s*2[ab]?|b\.?\s*arch|b\.?\s*planning|aptitude\s+test|drawing\s+test|"
        r"general\s+awareness|social\s+sciences|thinking\s+skills)\b",
        re.I,
    )
    paper1_resume_re = re.compile(r"\b(?:paper\s*[-–]?\s*1|b\.?\s*e\.?\s*/\s*b\.?\s*tech)\b", re.I)

    unit_prefix_re = re.compile(r"^unit\s*[-–]?\s*(?:\d+|[ivxlcdm]+)\s*[:.\-–]?\s*(.*)$", re.I)
    numbered_chapter_re = re.compile(r"^(?:chapter\s*)?\d{1,2}\.\s+([A-Z][A-Za-z0-9 ,&\-()/]+)$")
    subject_header_re = re.compile(
        r"^(?:(?:syllabus\s+for\s+jee\s*\(main\)\s*[-–:]?\s*)?"
        r"(?:part\s*[-–]?\s*(?:[abc]|i{1,3}|1|2|3)\s*[-–:]?\s*)?"
        r"(?:section\s*[-–]?\s*(?:[abc]|1|2|3)\s*[-–:]?\s*)?)"
        r"(physics|chemistry|mathematics|maths)\b",
        re.I,
    )

    def flush_unit():
        nonlocal current_unit_title, current_body
        if current_unit_title and not in_paper2:
            clean_title = _format_unit_title(current_unit_title)
            if clean_title and len(clean_title) >= 3:
                body_text = " ".join(current_body)
                kws = _clean_keywords(f"{clean_title} {body_text}")
                parsed.append({
                    "subject": current_subject,
                    "unit_name": clean_title,
                    "keywords": kws,
                })
        current_unit_title = None
        current_body = []

    i = 0
    while i < len(raw_lines):
        ln = raw_lines[i]

        # Resume only if explicit Paper 1 / B.E./B.Tech header appears
        if paper1_resume_re.search(ln) and len(ln) <= 90:
            in_paper2 = False

        # Stop/ignore Paper 2A (B.Arch) and Paper 2B (B.Planning) sections
        if paper2_stop_re.search(ln) and len(ln) <= 100 and not unit_prefix_re.match(ln):
            flush_unit()
            in_paper2 = True
            i += 1
            continue

        if in_paper2:
            i += 1
            continue

        # Handle case where pypdf merges Subject header and 'UNIT ...' onto the same line
        m_sub_inline = re.match(
            r"^(?:part\s*[-–]?\s*(?:[abc]|i{1,3}|1|2|3)\s*[-–:]?\s*)?"
            r"(physics|chemistry|mathematics|maths)\s+(unit\s*[-–]?\s*(?:\d+|[ivxlcdm]+)\b.*)$",
            ln,
            re.I,
        )
        if m_sub_inline:
            flush_unit()
            sub_word = m_sub_inline.group(1).lower()
            current_subject = "Mathematics" if sub_word in {"mathematics", "maths"} else sub_word.capitalize()
            ln = m_sub_inline.group(2).strip()

        # Check explicit UNIT heading first
        m_unit = unit_prefix_re.match(ln)
        if m_unit:
            flush_unit()
            title_part = (m_unit.group(1) or "").strip()
            # Handle case where 'UNIT 15:' is alone on a line and title is on the next line
            if not title_part and i + 1 < len(raw_lines):
                i += 1
                title_part = raw_lines[i].strip()
            # If pypdf merged body text onto a long UNIT line, trim before sentence body
            if len(title_part) > 95:
                # Split on colon or first lowercase-starting clause after uppercase heading
                m_split = re.match(r"^([A-Z0-9 ,&\-()/]+?)(?:\s+[A-Z][a-z]{2,}\b.*|$)", title_part)
                if m_split and len(m_split.group(1).strip()) >= 5:
                    remainder = title_part[len(m_split.group(1)):].strip()
                    title_part = m_split.group(1).strip()
                    if remainder:
                        current_body.append(remainder)
                else:
                    title_part = title_part[:95].rsplit(" ", 1)[0]
            current_unit_title = title_part
            i += 1
            continue

        # Check numbered chapter headings ONLY if file doesn't use UNIT prefixes
        if not has_explicit_units:
            m_num = numbered_chapter_re.match(ln)
            if m_num and len(ln) <= 100:
                flush_unit()
                current_unit_title = m_num.group(1).strip()
                i += 1
                continue

        # Check Subject header (short line like 'MATHEMATICS', 'PHYSICS', 'CHEMISTRY', 'PART A - PHYSICS')
        m_sub = subject_header_re.match(ln)
        if m_sub and len(ln.split()) <= 8 and len(ln) <= 75:
            flush_unit()
            sub_word = m_sub.group(1).lower()
            current_subject = "Mathematics" if sub_word in {"mathematics", "maths"} else sub_word.capitalize()
            i += 1
            continue

        # Fallback: short standalone line containing ONLY Physics / Chemistry / Mathematics
        if len(ln.split()) <= 5 and len(ln) <= 55:
            low_ln = ln.lower()
            if re.search(r"\b(?:mathematics|maths)\b", low_ln) and "aptitude" not in low_ln:
                flush_unit()
                current_subject = "Mathematics"
                i += 1
                continue
            if re.search(r"\bphysics\b", low_ln):
                flush_unit()
                current_subject = "Physics"
                i += 1
                continue
            if re.search(r"\bchemistry\b", low_ln) and "practical" not in low_ln and "concepts" not in low_ln:
                flush_unit()
                current_subject = "Chemistry"
                i += 1
                continue

        if current_unit_title:
            current_body.append(ln)
        i += 1

    flush_unit()

    # Fallback if user pasted simple "Subject: Unit1, Unit2" lines without UNIT prefixes
    if not parsed:
        for ln in raw_lines:
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
                    clean_u = _format_unit_title(u)
                    if clean_u:
                        parsed.append({
                            "subject": sub,
                            "unit_name": clean_u,
                            "keywords": _clean_keywords(clean_u),
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
