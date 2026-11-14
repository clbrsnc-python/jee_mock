"""
app.py
JEE Main Mock Test & Admin Question Bank Platform
Stack: Streamlit + Supabase (PostgreSQL + Storage) + GitHub Deployment
"""

import hashlib
import hmac
import io
import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st
from supabase import Client, create_client

from syllabus_mapper import (
    SUBJECTS,
    estimate_difficulty,
    extract_syllabus_text,
    is_valid_mcq,
    map_questions_to_units,
    parse_syllabus_document,
    select_balanced_mcqs,
    strip_unit_number,
)

st.set_page_config(
    page_title="JEE Main Mock Test & Question Bank",
    page_icon="📘",
    layout="wide",
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


def render_option_content(sb: Client, opt_text: str):
    """Renders text option or embedded [Image: ...] PNG stored in Supabase Storage."""
    txt = (opt_text or "").strip()
    m = re.match(r"^\[Image:\s*(.+?)\]$", txt)
    if m:
        img_ref = m.group(1).strip()
        if img_ref.startswith("http://") or img_ref.startswith("https://"):
            st.image(img_ref, width=260)
            return
        fname = os.path.basename(img_ref)
        public_url = sb.storage.from_("question-images").get_public_url(fname)
        st.image(public_url, width=260)
        return
    st.markdown(txt if txt else "_(Blank option)_")


def fetch_all_questions(sb: Client, mcq_only: bool = False) -> List[Dict]:
    """Fetches all questions across Supabase 1,000-row pages (scales cleanly to 175+ PDFs)."""
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
# Admin Panel (CSV + Images Storage + Syllabus Upload & Auto-Mapping)
# ---------------------------------------------------------------------------
def render_admin_panel(sb: Client):
    st.header("Admin Question Bank & Syllabus Manager")

    if not st.session_state.get("is_admin"):
        with st.form("admin_login_form"):
            pwd = st.text_input("Admin Password", type="password")
            submitted = st.form_submit_button("Sign In as Admin")
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

    tab_syl, tab_upload, tab_bank = st.tabs([
        "1. Upload JEE Syllabus",
        "2. Upload Extracted CSV & Option Images",
        "3. Question Bank, Unit Mapping & Difficulty Override",
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
                "Upload Option PNGs (from option_images/)",
                type=["png", "jpg", "jpeg"],
                accept_multiple_files=True,
            )

        if img_files and st.button("Upload Option Images to Supabase Storage"):
            uploaded_cnt = 0
            for f in img_files:
                sb.storage.from_("question-images").upload(
                    f.name,
                    f.getvalue(),
                    {"content-type": f.type or "image/png", "upsert": "true"},
                )
                uploaded_cnt += 1
            sb.table("admin_uploads").insert({
                "upload_type": "option_images",
                "file_name": f"{uploaded_cnt} images",
                "storage_path": "question-images/",
                "rows_processed": uploaded_cnt,
            }).execute()
            st.success(f"Uploaded {uploaded_cnt} image(s) to Supabase Storage bucket `question-images`.")

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
                    "correct_answer": r.get("correct_answer", "Unknown").strip(),
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

                # Resolve [Image: option_images/foo.png] to live Supabase Storage public URL if stored
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

            # Upsert in chunks of 200
            for start in range(0, len(db_rows), 200):
                sb.table("questions").upsert(db_rows[start:start + 200], on_conflict="content_hash").execute()

            sb.table("admin_uploads").insert({
                "upload_type": "questions_csv",
                "file_name": csv_file.name,
                "storage_path": csv_storage_path,
                "rows_processed": len(db_rows),
            }).execute()
            st.success(f"Stored & mapped {len(db_rows)} unique questions in Supabase (with `unit` beside `Question`).")

    # --- Tab 3: Question Bank Editor & Mapped CSV Download ---
    with tab_bank:
        st.subheader("Manage Questions, Units & Difficulty Overrides")
        rows = fetch_all_questions(sb, mcq_only=False)
        if not rows:
            st.info("No questions in Supabase yet. Upload syllabus and CSV in Tabs 1 & 2.")
            return

        col_remap, col_dl = st.columns([1, 1])
        with col_remap:
            if st.button("Re-run Automatic Syllabus Mapping on All Questions"):
                syl_units = sb.table("syllabus_units").select("*").execute().data
                new_units = map_questions_to_units(rows, syl_units)
                for q_row, u_name in zip(rows, new_units):
                    if u_name != q_row["unit"]:
                        sb.table("questions").update({"unit": u_name}).eq("id", q_row["id"]).execute()
                st.success("Re-mapped all questions against current syllabus.")
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

        unit_options = sorted({u["unit_name"] for u in sb.table("syllabus_units").select("unit_name").execute().data} | {"Unmapped"})
        edit_cols = ["id", "subject", "question_no", "question", "unit", "difficulty", "correct_answer", "is_mcq"]
        edited = st.data_editor(
            df_bank[edit_cols],
            use_container_width=True,
            hide_index=True,
            disabled=["id", "subject", "question_no", "question"],
            column_config={
                "unit": st.column_config.SelectboxColumn("Unit", options=unit_options, required=True),
                "difficulty": st.column_config.SelectboxColumn("Difficulty", options=["Easy", "Medium", "Hard"], required=True),
                "correct_answer": st.column_config.SelectboxColumn("Key", options=["1", "2", "3", "4", "Unknown"]),
                "is_mcq": st.column_config.CheckboxColumn("MCQ?"),
            },
        )
        if st.button("Save Admin Edits to Supabase", type="primary"):
            orig_map = df_bank.set_index("id").to_dict("index")
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


# ---------------------------------------------------------------------------
# Student Registration / Login Gate
# ---------------------------------------------------------------------------
def render_student_auth(sb: Client):
    st.header("Student Sign In / Registration")
    tab_login, tab_reg = st.tabs(["Sign In", "New Student Registration"])

    with tab_login:
        with st.form("student_login_form"):
            email = st.text_input("Email").strip().lower()
            pwd = st.text_input("Password", type="password")
            if st.form_submit_button("Sign In", type="primary"):
                res = sb.table("students").select("*").eq("email", email).execute().data
                if res and verify_password(pwd, res[0]["password_hash"]):
                    st.session_state["student"] = res[0]
                    st.rerun()
                else:
                    st.error("Invalid email or password.")

    with tab_reg:
        with st.form("student_register_form"):
            full_name = st.text_input("Full Name").strip()
            email = st.text_input("Email Address").strip().lower()
            pwd = st.text_input("Create Password (min 6 chars)", type="password")
            if st.form_submit_button("Register & Start", type="primary"):
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
                        st.success("Registered successfully!")
                        st.rerun()


# ---------------------------------------------------------------------------
# Student Mock Test Builder, Runner & Submission Review
# ---------------------------------------------------------------------------
def finalize_and_score_test(sb: Client):
    test = st.session_state["active_test"]
    questions = test["questions"]
    responses = test["responses"]
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

    st.session_state["last_review"] = {
        "attempt": attempt_row,
        "rows": review_rows,
    }
    del st.session_state["active_test"]
    st.rerun(scope="app")


def render_submission_review(sb: Client):
    rev = st.session_state["last_review"]
    att = rev["attempt"]
    rows = rev["rows"]

    st.success("Mock Test Submitted & Saved to Performance History!")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Marks Obtained", f"{att['marks_obtained']} / {att['full_marks']}")
    c2.metric("Correct (+4)", att["correct_count"])
    c3.metric("Wrong (-1)", att["wrong_count"])
    c4.metric("Time Taken", f"{format_duration(att['time_taken_sec'])} / {format_duration(att['total_allotted_sec'])}")

    st.subheader("Question-by-Question Answer Review")
    for idx, item in enumerate(rows, start=1):
        q = item["question"]
        status = item["status"]
        sel = item["selected"]
        corr = item["correct"]

        with st.container(border=True):
            st.markdown(f"**Q{idx}. [{q['subject']} · {q['unit']} · {q['difficulty']}]** — {q['question']}")

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
                # For skip: show ONLY the correct answer
                st.warning(f"Skipped (0) — Correct Answer: ({corr})")
                render_option_content(sb, q[f"option_{corr}"])

    if st.button("Design Another Mock Test", type="primary"):
        del st.session_state["last_review"]
        st.rerun()


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
            st.rerun()

    # Active test runner takes priority
    if st.session_state.get("active_test"):
        test = st.session_state["active_test"]

        @st.fragment(run_every=1)
        def live_timer_banner():
            elapsed = int(time.time() - test["start_epoch"])
            remaining = test["total_allotted_sec"] - elapsed
            if remaining <= 0:
                st.error("Time is up! Submitting automatically...")
                finalize_and_score_test(sb)
            else:
                st.info(
                    f"⏱️ Remaining Time: **{format_duration(remaining)}** "
                    f"(Allotted: {format_duration(test['total_allotted_sec'])}) | "
                    f"Marking: **+4** Correct, **-1** Wrong, **0** Skip"
                )

        live_timer_banner()

        for idx, q in enumerate(test["questions"], start=1):
            qid = q["id"]
            with st.container(border=True):
                st.markdown(f"**Q{idx}. [{q['subject']} · {q['unit']} · {q['difficulty']}]**")
                st.markdown(q["question"])

                for opt_num in ("1", "2", "3", "4"):
                    c_lbl, c_body = st.columns([0.08, 0.92])
                    c_lbl.markdown(f"**({opt_num})**")
                    with c_body:
                        render_option_content(sb, q[f"option_{opt_num}"])

                choice_label = st.radio(
                    f"Select answer for Q{idx}",
                    options=["Skip (0)", "Option (1)", "Option (2)", "Option (3)", "Option (4)"],
                    key=f"ans_{qid}",
                    horizontal=True,
                )
                if choice_label.startswith("Option ("):
                    test["responses"][qid] = choice_label.split("(")[1][0]
                else:
                    test["responses"][qid] = None

        if st.button("Submit Mock Test", type="primary"):
            finalize_and_score_test(sb)
        return

    if st.session_state.get("last_review"):
        render_submission_review(sb)
        return

    tab_build, tab_history = st.tabs(["Design Custom Mock Test", "Performance Record"])

    with tab_build:
        st.subheader("Customize Your JEE Mock Test (35% Easy · 30% Medium · 35% Hard)")
        mcq_rows = fetch_all_questions(sb, mcq_only=True)
        if not mcq_rows:
            st.warning("No MCQ questions uploaded yet. Ask Admin to upload syllabus & CSV.")
            return

        avail_subjects = sorted({q["subject"] for q in mcq_rows})
        sel_subjects = st.multiselect("1. Select Subject(s)", options=avail_subjects, default=avail_subjects)
        if not sel_subjects:
            st.info("Select at least one subject.")
            return

        sub_filtered = [q for q in mcq_rows if q["subject"] in sel_subjects]
        avail_units = sorted({strip_unit_number(q["unit"]) or "Unmapped" for q in sub_filtered})
        sel_units = st.multiselect(
            "2. Select Unit(s) under selected Subject(s) (Mix & Match)",
            options=avail_units,
            default=avail_units,
        )
        if not sel_units:
            st.info("Select at least one unit.")
            return

        unit_pool = [q for q in sub_filtered if (strip_unit_number(q["unit"]) or "Unmapped") in sel_units]
        max_q = len(unit_pool)
        st.caption(
            f"Available MCQs matching selection: **{max_q}** "
            f"(Easy: {sum(q['difficulty']=='Easy' for q in unit_pool)}, "
            f"Medium: {sum(q['difficulty']=='Medium' for q in unit_pool)}, "
            f"Hard: {sum(q['difficulty']=='Hard' for q in unit_pool)})"
        )

        n_q = st.number_input(
            "3. Number of Questions (2 min per question · +4 / -1 / 0)",
            min_value=1,
            max_value=max_q,
            value=min(15, max_q),
            step=1,
        )

        allotted_min = int(n_q) * 2
        st.markdown(
            f"- **Total Time Allotted:** {allotted_min} minutes ({int(n_q)} × 2 min)\n"
            f"- **Full Marks:** {int(n_q) * 4} | **Difficulty Mix Target:** 35% Easy / 30% Medium / 35% Hard"
        )

        if st.button("Start Mock Test", type="primary"):
            chosen, diff_counts = select_balanced_mcqs(unit_pool, int(n_q))
            st.session_state["active_test"] = {
                "questions": chosen,
                "responses": {},
                "subjects": sel_subjects,
                "units": sel_units,
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
            for a in attempts:
                dt_str = a["test_date"][:16].replace("T", " ")
                table_rows.append({
                    "Date of Test": dt_str,
                    "Unit Covered": a["units_covered"],
                    "Full Marks": a["full_marks"],
                    "Marks Obtained": a["marks_obtained"],
                    "Correct Answers": a["correct_count"],
                    "Wrong Answers": a["wrong_count"],
                    "Skipped": a["skipped_count"],
                    "Time Taken / Total Allotted Time": (
                        f"{format_duration(a['time_taken_sec'])} / {format_duration(a['total_allotted_sec'])}"
                    ),
                })
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# App Navigation
# ---------------------------------------------------------------------------
def main():
    sb = get_supabase()
    with st.sidebar:
        st.title("JEE Prep Portal")
        mode = st.radio("Workspace", ["Student Mock Test", "Admin Console"])

    if mode == "Admin Console":
        render_admin_panel(sb)
    else:
        render_student_portal(sb)


if __name__ == "__main__":
    main()
