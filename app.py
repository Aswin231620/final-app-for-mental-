import streamlit as st
import json
import os
import hashlib
import datetime
import openai
import pandas as pd  # NEW: for the progress table

# ------------------ CONFIG ------------------
openai.api_key = os.getenv("OPENAI_API_KEY")  # set in terminal before run
USERS_FILE = "users.json"

# ------------------ HELPERS ------------------
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)

def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()

def add_user(username, password):
    users = load_users()
    if username in users:
        return False, "❌ Username already exists"
    users[username] = {
        "password": hash_pw(password),
        "journal": [],
        "habits": {}
    }
    save_users(users)
    return True, "✅ User created successfully"

def login_user(username, password):
    users = load_users()
    if username in users and users[username]["password"] == hash_pw(password):
        return True
    return False

# ------------------ AI CHAT ------------------
def chat_with_ai(prompt, username):
    users = load_users()
    user_data = users.get(username, {})
    journal = " ".join(user_data.get("journal", []))
    habits = user_data.get("habits", {})
    habit_summary = ", ".join([f"{h}:{'Done' if v else 'Missed'}" for h, v in habits.items()])

    context = f"User journal: {journal}\nUser habits: {habit_summary}\nNow respond to user in a friendly supportive way."

    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": context},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

# ------------------ CUSTOM CSS ------------------
st.markdown("""
    <style>
    /* Background gradient */
    [data-testid="stAppViewContainer"] {
        background: linear-gradient(135deg, #a8edea, #fed6e3);
    }

    /* Sidebar background */
    [data-testid="stSidebar"] {
        background: #ffffffdd;
        backdrop-filter: blur(10px);
    }

    /* Input fields */
    .stTextInput > div > div > input,
    .stPasswordInput > div > div > input {
        border-radius: 12px !important;
        padding: 10px !important;
        border: 1px solid #ccc !important;
    }

    /* Buttons */
    .stButton > button {
        background: linear-gradient(90deg,#ff6a00,#ee0979);
        color:white;
        border-radius: 20px;
        padding:10px 24px;
        font-size:16px;
        font-weight:bold;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        transform: translateY(-3px) scale(1.05);
        box-shadow: 0px 6px 20px rgba(0,0,0,0.3);
    }

    /* Tabs */
    .stTabs [role="tablist"] button {
        font-size:16px;
        font-weight:600;
        padding:10px 20px;
        border-radius: 10px;
        margin: 0 5px;
        background: #ffffffaa;
        transition: 0.3s;
    }
    .stTabs [role="tablist"] button:hover {
        background: linear-gradient(135deg, #6a11cb, #2575fc);
        color:white;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #6a11cb, #2575fc) !important;
        color:white !important;
    }
    </style>
""", unsafe_allow_html=True)

# ------------------ MAIN APP ------------------
st.markdown("""
    <div style="text-align:center; padding:20px;">
        <h1 style="color:#6a11cb;">🤖 MindMate- Your AI-Powered Mental Wellness 🧘 </h1>
        <p style="font-size:18px; color:#333;">
            Your personal AI-powered journaling & habit tracking buddy 
        </p>
    </div>
""", unsafe_allow_html=True)

menu = ["Login", "Sign Up"]
choice = st.sidebar.selectbox("Menu", menu)

if choice == "Sign Up":
    st.subheader("Create Account")
    new_user = st.text_input("Username")
    new_pw = st.text_input("Password", type="password")
    if st.button("Sign Up"):
        ok, msg = add_user(new_user.strip(), new_pw.strip())
        st.success(msg) if ok else st.error(msg)

elif choice == "Login":
    st.subheader("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if login_user(username.strip(), password.strip()):
            st.session_state["username"] = username.strip()
            st.success("✅ Logged in successfully!")
        else:
            st.error("❌ Invalid username or password")

# ------------------ AFTER LOGIN ------------------
if "username" in st.session_state:
    st.sidebar.success(f"Welcome, {st.session_state['username']}")

    tabs = st.tabs(["💬 AI Chat", "📓 Journaling", "✅ Habit Tracker"])

    # AI Chat
    with tabs[0]:
        st.header("Chat with AI")
        user_msg = st.text_area("Your message")
        if st.button("Send to AI"):
            if user_msg:
                reply = chat_with_ai(user_msg, st.session_state["username"])
                st.write("🤖:", reply)

    # Journaling
    with tabs[1]:
        st.header("Daily Journaling")
        journal_entry = st.text_area("Write about your day...")
        if st.button("Save Journal"):
            users = load_users()
            entry = f"{datetime.date.today()}: {journal_entry}"
            users[st.session_state["username"]]["journal"].append(entry)
            save_users(users)
            st.success("✍️ Journal saved!")

        st.subheader("Previous Entries")
        for j in load_users()[st.session_state["username"]]["journal"]:
            st.markdown(f"""
                <div style="background:#fff;padding:15px;margin:10px 0;
                            border-radius:12px;box-shadow:0 4px 10px rgba(0,0,0,0.1);">
                    📝 {j}
                </div>
            """, unsafe_allow_html=True)

    # Habit Tracker (UPDATED: hides JSON, shows Date + Progress table)
    with tabs[2]:
        st.header("Daily Habit Checker")
        users = load_users()
        habits = users[st.session_state["username"]]["habits"]

        new_habit = st.text_input("Add a new habit")
        if st.button("Add Habit"):
            if new_habit:
                habits[new_habit] = False
                users[st.session_state["username"]]["habits"] = habits
                save_users(users)
                st.success("✅ Habit added!")

        # Checkboxes for today's habits
        for habit, done in habits.items():
            checked = st.checkbox(habit, value=done, key=f"habit_{habit}")
            habits[habit] = checked

        if st.button("Save Progress"):
            users[st.session_state["username"]]["habits"] = habits
            save_users(users)
            st.success("📊 Habits updated!")

        # ---- Pretty table instead of white JSON box ----
        st.subheader("📅 Today's Habit Progress")
        if habits:
            today = str(datetime.date.today())
            rows = [{"Date": today, "Habit": h, "Status": "✅ Done" if v else "❌ Missed"} for h, v in habits.items()]
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True)

            # Progress Bar
            completed = sum(v for v in habits.values())
            total = len(habits)
            if total > 0:
                st.progress(completed / total)
                st.success(f"✅ {completed}/{total} habits done today!")
        else:
            st.info("No habits yet. Add one above ⬆️")
