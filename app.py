import os
import time
import bcrypt
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from dataclasses import dataclass

import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from dotenv import load_dotenv

# ---------- Load env ----------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ---------- OpenAI Client (new SDK) ----------
# If you use an older SDK, adjust accordingly.
try:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception:
    client = None

# ---------- App constants ----------
APP_TITLE = "MindMate — Personalized Mental Wellness"
DB_PATH = "mindmate.db"

# ---------- DB helpers ----------
def get_engine():
    return create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)

def init_db():
    eng = get_engine()
    with eng.begin() as conn:
        # Users table
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash BLOB NOT NULL,
            created_at TEXT NOT NULL
        );
        """))

        # Journals table
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS journals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            entry TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """))

        # Habits table
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """))

        # Habit logs table (done/not done per date)
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS habit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,   -- YYYY-MM-DD
            completed INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(habit_id) REFERENCES habits(id),
            UNIQUE(habit_id, log_date)
        );
        """))

        # Chat history (optional, nice for continuity)
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,       -- 'user' or 'assistant' or 'system'
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """))

# ---------- Auth helpers ----------
def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

def verify_password(password: str, password_hash: bytes) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash)
    except Exception:
        return False

def register_user(email: str, username: str, password: str):
    eng = get_engine()
    with eng.begin() as conn:
        password_hash = hash_password(password)
        now = datetime.utcnow().isoformat()
        try:
            conn.execute(
                text("INSERT INTO users (email, username, password_hash, created_at) VALUES (:e,:u,:p,:c)"),
                {"e": email, "u": username, "p": password_hash, "c": now}
            )
            return True, "Account created."
        except OperationalError as e:
            return False, f"DB error: {e}"
        except Exception as e:
            msg = str(e)
            if "UNIQUE constraint failed" in msg:
                return False, "Email or username already exists."
            return False, f"Error: {e}"

def get_user_by_email(email: str):
    eng = get_engine()
    with eng.begin() as conn:
        res = conn.execute(text("SELECT id, email, username, password_hash FROM users WHERE email=:e"), {"e": email}).fetchone()
    return res

# ---------- Journal helpers ----------
def add_journal(user_id: int, entry: str):
    eng = get_engine()
    with eng.begin() as conn:
        now = datetime.utcnow().isoformat()
        conn.execute(text("INSERT INTO journals (user_id, entry, created_at) VALUES (:uid,:entry,:c)"),
                     {"uid": user_id, "entry": entry, "c": now})

def get_journals(user_id: int, days_back: int = 30):
    eng = get_engine()
    since = (datetime.utcnow() - timedelta(days=days_back)).isoformat()
    with eng.begin() as conn:
        rows = conn.execute(
            text("SELECT id, entry, created_at FROM journals WHERE user_id=:uid AND created_at>=:since ORDER BY created_at DESC"),
            {"uid": user_id, "since": since}
        ).fetchall()
    return rows

# ---------- Habit helpers ----------
def create_habit(user_id: int, name: str):
    eng = get_engine()
    with eng.begin() as conn:
        now = datetime.utcnow().isoformat()
        conn.execute(text("INSERT INTO habits (user_id, name, created_at) VALUES (:uid,:n,:c)"),
                     {"uid": user_id, "n": name, "c": now})

def list_habits(user_id: int):
    eng = get_engine()
    with eng.begin() as conn:
        rows = conn.execute(text("SELECT id, name, created_at FROM habits WHERE user_id=:uid ORDER BY created_at"),
                            {"uid": user_id}).fetchall()
    return rows

def toggle_habit_for_date(habit_id: int, date_str: str, completed: bool):
    eng = get_engine()
    with eng.begin() as conn:
        # Upsert style: try update, if none updated insert
        updated = conn.execute(
            text("UPDATE habit_logs SET completed=:c WHERE habit_id=:hid AND log_date=:d"),
            {"c": 1 if completed else 0, "hid": habit_id, "d": date_str}
        )
        if updated.rowcount == 0:
            conn.execute(
                text("INSERT OR IGNORE INTO habit_logs (habit_id, log_date, completed) VALUES (:hid,:d,:c)"),
                {"hid": habit_id, "d": date_str, "c": 1 if completed else 0}
            )

def get_habit_logs(user_id: int, days: int = 30):
    """Return a dataframe of habit completion over the last N days."""
    eng = get_engine()
    since = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
    with eng.begin() as conn:
        df = pd.read_sql_query(
            text("""
                SELECT h.id AS habit_id, h.name, l.log_date, l.completed
                FROM habits h
                LEFT JOIN habit_logs l ON h.id = l.habit_id
                WHERE h.user_id = :uid AND (l.log_date >= :since OR l.log_date IS NULL)
            """),
            conn.connection, params={"uid": user_id, "since": since}
        )
    return df

# ---------- Chat helpers ----------
def save_chat(user_id: int, role: str, content: str):
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(
            text("INSERT INTO chats (user_id, role, content, created_at) VALUES (:uid,:r,:c,:t)"),
            {"uid": user_id, "r": role, "c": content, "t": datetime.utcnow().isoformat()}
        )

def load_recent_chat(user_id: int, limit: int = 12):
    eng = get_engine()
    with eng.begin() as conn:
        rows = conn.execute(
            text("SELECT role, content FROM chats WHERE user_id=:uid ORDER BY id DESC LIMIT :lim"),
            {"uid": user_id, "lim": limit}
        ).fetchall()
    # reverse chronological → chronological
    return list(reversed(rows))

# ---------- Personalization ----------
def build_personal_context(user_id: int):
    """Summarize last 7 days journals + habits into a compact context for the AI."""
    journals = get_journals(user_id, days_back=7)
    journal_points = []
    for _, entry, created_at in journals:
        # lightweight truncation for prompt budget
        snippet = entry.strip().replace("\n", " ")
        if len(snippet) > 220:
            snippet = snippet[:220] + "..."
        day = created_at.split("T")[0]
        journal_points.append(f"[{day}] {snippet}")

    habits_df = get_habit_logs(user_id, days=14)
    # Compute per-habit completion rate over last 7 days
    last7 = (datetime.utcnow() - timedelta(days=7)).date().isoformat()
    if not habits_df.empty:
        sub = habits_df[habits_df["log_date"].fillna(last7) >= last7].copy()
        rates = []
        for name, grp in sub.groupby("name"):
            # total days marked (completed or not)
            n = len(grp)
            if n == 0:
                continue
            comp = int(grp["completed"].fillna(0).sum())
            rate = int(round(100 * comp / max(n, 1)))
            rates.append(f"{name}: {rate}%")
        habit_summary = ", ".join(rates) if rates else "no recent habit data"
    else:
        habit_summary = "no habits yet"

    ctx = "Recent Journals:\n- " + ("\n- ".join(journal_points) if journal_points else "no journal entries") \
        + f"\n\nHabit Adherence (last 7 days): {habit_summary}"
    return ctx

def ask_ai(user_id: int, user_text: str):
    """Call OpenAI with personal context + recent chat for continuity."""
    if client is None or not OPENAI_API_KEY:
        return "OpenAI API key not set. Please configure your .env."

    personal_ctx = build_personal_context(user_id)
    history = load_recent_chat(user_id, limit=10)  # keep it short for speed

    messages = [
        {
            "role": "system",
            "content": (
                "You are MindMate, a friendly and empathetic wellness companion. "
                "Be supportive, non-judgmental, and concrete. Prefer short, practical suggestions (1–3 items). "
                "If user seems distressed, suggest a simple grounding exercise. Avoid medical diagnoses."
            )
        },
        {"role": "system", "content": f"User personal context:\n{personal_ctx}"},
    ]

    for r, c in history:
        messages.append({"role": r, "content": c})
    messages.append({"role": "user", "content": user_text})

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",  # use a small/fast model for hackathon speed/cost
            messages=messages,
            temperature=0.8,
            max_tokens=350,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"AI error: {e}"

# ---------- UI Components ----------
@dataclass
class UserSession:
    id: int
    email: str
    username: str

def login_ui():
    st.subheader("Login")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Login", type="primary", use_container_width=True):
        row = get_user_by_email(email)
        if row:
            uid, em, un, phash = row
            if verify_password(password, phash):
                st.session_state["user"] = UserSession(id=uid, email=em, username=un)
                st.success("Logged in! Use the sidebar to navigate.")
                time.sleep(0.6)
                st.rerun()
            else:
                st.error("Invalid email or password.")
        else:
            st.error("Invalid email or password.")

def signup_ui():
    st.subheader("Create Account")
    email = st.text_input("Email", key="su_email")
    username = st.text_input("Username", key="su_username")
    password = st.text_input("Password (min 6 chars)", type="password", key="su_pw")
    if st.button("Sign Up", use_container_width=True):
        if len(password) < 6:
            st.error("Password must be at least 6 characters.")
        else:
            ok, msg = register_user(email, username, password)
            if ok:
                st.success("Account created. You can log in now.")
            else:
                st.error(msg)

def chat_tab(user: UserSession):
    st.markdown("### 🗣️ AI Chat (personalized)")
    user_msg = st.text_area("Type how you're feeling or ask for help:", height=100, placeholder="e.g., I'm anxious about tomorrow's exam.")
    col1, col2 = st.columns([1, 6])
    with col1:
        send = st.button("Send", type="primary")
    with col2:
        st.caption("Tip: Your journaling and habits automatically personalize the response.")

    if send and user_msg.strip():
        save_chat(user.id, "user", user_msg.strip())
        reply = ask_ai(user.id, user_msg.strip())
        save_chat(user.id, "assistant", reply)
        st.markdown("**Assistant:** " + reply)

    # show last few exchanges
    st.divider()
    st.caption("Recent conversation")
    for r, c in load_recent_chat(user.id, limit=8):
        if r == "user":
            st.markdown(f"**You:** {c}")
        elif r == "assistant":
            st.markdown(f"**MindMate:** {c}")

def journal_tab(user: UserSession):
    st.markdown("### 📓 Journaling")
    entry = st.text_area("Write about your day:", height=160, placeholder="What happened today? How did you feel? Any triggers or wins?")
    if st.button("Save Journal", type="primary"):
        if entry.strip():
            add_journal(user.id, entry.strip())
            st.success("Saved!")
        else:
            st.warning("Please write something before saving.")

    st.divider()
    st.caption("Your recent entries")
    rows = get_journals(user.id, days_back=30)
    if not rows:
        st.info("No journal entries yet.")
        return
    for _id, entry, created_at in rows:
        day = created_at.split("T")[0]
        with st.expander(f"{day}"):
            st.write(entry)

def habits_tab(user: UserSession):
    st.markdown("### ✅ Habit Tracker")
    new_habit = st.text_input("Create a habit (e.g., 10-min walk, 2L water)")
    if st.button("Add Habit", type="primary"):
        if new_habit.strip():
            create_habit(user.id, new_habit.strip())
            st.success("Habit added!")
            st.rerun()
        else:
            st.warning("Please enter a habit name.")

    st.divider()
    rows = list_habits(user.id)
    if not rows:
        st.info("No habits yet. Add one above.")
        return

    today = datetime.utcnow().date().isoformat()
    st.markdown("#### Today")
    for hid, name, _ in rows:
        done = st.checkbox(name, value=False, key=f"tod_{hid}")
        if st.button(f"Save '{name}'", key=f"save_{hid}"):
            toggle_habit_for_date(hid, today, done)
            st.success("Saved!")
            time.sleep(0.3)
            st.rerun()

    st.divider()
    st.markdown("#### Progress (last 14 days)")
    df = get_habit_logs(user.id, days=14)
    if df.empty:
        st.info("No habit logs yet.")
        return

    # Build completion % per day
    # Create a date index
    start_date = (datetime.utcnow().date() - timedelta(days=13))
    date_list = [(start_date + timedelta(days=i)).isoformat() for i in range(14)]

    # plot: for each habit, completion across days
    fig, ax = plt.subplots()
    for name, grp in df.groupby("name"):
        series = []
        for d in date_list:
            row = grp[grp["log_date"] == d]
            val = 0
            if not row.empty:
                val = int(row["completed"].fillna(0).values[0])
            series.append(val)
        ax.plot(date_list, series, marker="o", label=name)

    ax.set_ylabel("Completed (1=yes, 0=no)")
    ax.set_xlabel("Date")
    ax.set_title("Habit completion over time")
    ax.legend()
    plt.xticks(rotation=45)
    st.pyplot(fig, clear_figure=True)

# ---------- Main ----------
def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="💙", layout="wide")
    init_db()

    st.sidebar.title("MindMate")
    page = st.sidebar.radio("Navigate", ["Home", "Login", "Sign Up", "Chat", "Journal", "Habits"])

    user: UserSession | None = st.session_state.get("user")

    # Header / CTA
    st.title(APP_TITLE)
    st.caption("On-demand support • Personal journaling • Build habits • Personalized AI suggestions")

    if page == "Home":
        st.markdown("""
        **Why this wins hackathons:**
        - Solves the *generic mental-health tools* problem with **true personalization**.
        - Triad experience: **Chat (mind)** + **Journal (reflection)** + **Habits (behavior)**.
        - Lightweight, fast, demoable. No heavy installs or sign-ups needed for judges.
        """)
        st.info("Use the sidebar to log in or sign up. Then explore Chat, Journal, and Habits.")

    elif page == "Login":
        if user:
            st.success(f"Logged in as **{user.username}**")
        else:
            login_ui()

    elif page == "Sign Up":
        if user:
            st.success(f"Logged in as **{user.username}**")
        else:
            signup_ui()

    elif page == "Chat":
        if not user:
            st.warning("Please log in first.")
        else:
            chat_tab(user)

    elif page == "Journal":
        if not user:
            st.warning("Please log in first.")
        else:
            journal_tab(user)

    elif page == "Habits":
        if not user:
            st.warning("Please log in first.")
        else:
            habits_tab(user)

    # Footer: quick SOS guidance
    st.divider()
    st.caption(
        "MindMate is not a medical device. If you feel unsafe or in crisis, contact local emergency services or a trusted person."
    )

if __name__ == "__main__":
    main()
