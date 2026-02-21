"""
HealthPilot AI - Advanced Healthcare Platform
pip install flask requests
Run: python app.py
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import requests
import json
import os
from datetime import datetime, timedelta
import re

app = Flask(__name__)
app.secret_key = "healthpilot_secret_2024"

# ──────────────────────────────────────────────
# GEMINI API CONFIG
# ──────────────────────────────────────────────
GEMINI_API_KEY = "AIzaSyA8VxxhW9tEcZWJQzpDIbtliLLcMTvkB6A"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

DB_PATH = "healthpilot.db"


# ──────────────────────────────────────────────
# DATABASE SETUP
# ──────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            age INTEGER,
            weight REAL,
            height REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS mood_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            mood INTEGER,
            note TEXT,
            date TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            time TEXT,
            type TEXT,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS health_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            steps INTEGER DEFAULT 0,
            water_ml INTEGER DEFAULT 0,
            sleep_hours REAL DEFAULT 0,
            date TEXT DEFAULT CURRENT_DATE
        );
    """)
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
# GEMINI HELPER
# ──────────────────────────────────────────────
def ask_gemini(prompt, system_context="You are HealthPilot AI, a professional medical assistant. Always be empathetic, clear, and evidence-based. Format responses with clear sections."):
    full_prompt = f"{system_context}\n\nUser: {prompt}"
    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024}
    }
    try:
        resp = requests.post(GEMINI_URL, json=payload, timeout=15)
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        return f"AI temporarily unavailable. Please try again. ({str(e)})"


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ──────────────────────────────────────────────
# ROUTES — AUTH
# ──────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        d = request.form
        hashed = generate_password_hash(d["password"])
        try:
            conn = get_db()
            conn.execute("INSERT INTO users (name,email,password,age,weight,height) VALUES (?,?,?,?,?,?)",
                         (d["name"], d["email"], hashed, d.get("age"), d.get("weight"), d.get("height")))
            conn.commit()
            conn.close()
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            return render_template("auth.html", error="Email already registered.", page="register")
    return render_template("auth.html", page="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (request.form["email"],)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], request.form["password"]):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))
        return render_template("auth.html", error="Invalid credentials.", page="login")
    return render_template("auth.html", page="login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ──────────────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    moods = conn.execute("SELECT mood, date FROM mood_logs WHERE user_id=? ORDER BY date DESC LIMIT 7", (uid,)).fetchall()
    reminders = conn.execute("SELECT * FROM reminders WHERE user_id=? AND active=1 LIMIT 5", (uid,)).fetchall()
    health = conn.execute("SELECT * FROM health_data WHERE user_id=? ORDER BY date DESC LIMIT 1", (uid,)).fetchone()
    conn.close()

    bmi = None
    bmi_cat = "N/A"
    if user["weight"] and user["height"]:
        h_m = user["height"] / 100
        bmi = round(user["weight"] / (h_m * h_m), 1)
        if bmi < 18.5: bmi_cat = "Underweight"
        elif bmi < 25: bmi_cat = "Normal"
        elif bmi < 30: bmi_cat = "Overweight"
        else: bmi_cat = "Obese"

    mood_data = [m["mood"] for m in moods]
    mood_labels = [m["date"][:10] for m in moods]

    return render_template("dashboard.html",
                           user=dict(user),
                           bmi=bmi, bmi_cat=bmi_cat,
                           mood_data=mood_data,
                           mood_labels=mood_labels,
                           reminders=[dict(r) for r in reminders],
                           health=dict(health) if health else {})


# ──────────────────────────────────────────────
# AI CHAT
# ──────────────────────────────────────────────
@app.route("/chat")
@login_required
def chat():
    uid = session["user_id"]
    conn = get_db()
    history = conn.execute("SELECT * FROM chat_history WHERE user_id=? ORDER BY timestamp DESC LIMIT 30", (uid,)).fetchall()
    conn.close()
    return render_template("chat.html", history=[dict(h) for h in reversed(history)])


@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    msg = request.json.get("message", "")
    uid = session["user_id"]
    system = """You are HealthPilot AI, an advanced medical assistant. When answering health questions, structure your response as:
**🔍 Assessment:** Brief analysis
**⚠️ Possible Causes:** Bullet list
**✅ Recommendations:** Actionable steps  
**💊 Precautions:** Safety notes
**🌿 Lifestyle Advice:** Holistic tips
**⚕️ Disclaimer:** Always end with medical disclaimer."""
    reply = ask_gemini(msg, system)
    conn = get_db()
    conn.execute("INSERT INTO chat_history (user_id,role,content) VALUES (?,?,?)", (uid, "user", msg))
    conn.execute("INSERT INTO chat_history (user_id,role,content) VALUES (?,?,?)", (uid, "ai", reply))
    conn.commit()
    conn.close()
    return jsonify({"reply": reply})


# ──────────────────────────────────────────────
# SYMPTOM ANALYZER
# ──────────────────────────────────────────────
@app.route("/symptoms")
@login_required
def symptoms():
    return render_template("symptoms.html")


@app.route("/api/analyze-symptoms", methods=["POST"])
@login_required
def analyze_symptoms():
    syms = request.json.get("symptoms", "")
    age = request.json.get("age", "")
    gender = request.json.get("gender", "")
    prompt = f"""Analyze these symptoms for a {age} year old {gender}: {syms}

Provide a structured analysis with:
1. **Possible Conditions** (list top 3 with brief explanation)
2. **Severity Level** (Low/Medium/High with reasoning)
3. **Immediate Actions** (what to do right now)
4. **Doctor Consultation** (urgency level: routine/soon/urgent/emergency)
5. **Red Flags** (warning signs to watch for)
6. **Home Care Tips** (safe self-care measures)

Format clearly with emojis and headers."""
    result = ask_gemini(prompt)
    severity = "Medium"
    if any(w in result.lower() for w in ["emergency", "severe", "high", "urgent"]):
        severity = "High"
    elif any(w in result.lower() for w in ["low", "mild", "minor"]):
        severity = "Low"
    return jsonify({"result": result, "severity": severity})


# ──────────────────────────────────────────────
# REPORT ANALYZER
# ──────────────────────────────────────────────
@app.route("/report")
@login_required
def report():
    return render_template("report.html")


@app.route("/api/analyze-report", methods=["POST"])
@login_required
def analyze_report():
    text = request.json.get("report_text", "")
    prompt = f"""Analyze this medical lab report and explain it in simple language:

{text}

Provide:
1. **📋 Report Summary** - What this test checks
2. **📊 Key Values Analysis** - Each value with normal range and status (normal/high/low)
3. **⚠️ Abnormal Values** - Highlight concerning values with explanation
4. **💡 What This Means** - Plain English interpretation
5. **🩺 Recommended Actions** - What patient should do
6. **❓ Questions to Ask Doctor** - Important follow-up questions

Use clear formatting with emojis."""
    result = ask_gemini(prompt)
    return jsonify({"result": result})


# ──────────────────────────────────────────────
# DIET & FITNESS
# ──────────────────────────────────────────────
@app.route("/diet")
@login_required
def diet():
    return render_template("diet.html")


@app.route("/api/diet-plan", methods=["POST"])
@login_required
def diet_plan():
    d = request.json
    prompt = f"""Create a personalized diet and fitness plan for:
- Goal: {d.get('goal')}
- Age: {d.get('age')} years
- Weight: {d.get('weight')} kg
- Height: {d.get('height')} cm
- Activity Level: {d.get('activity')}
- Dietary Preference: {d.get('diet_type', 'No restriction')}

Provide:
1. **🎯 Daily Calorie Target** with breakdown (protein/carbs/fat %)
2. **🌅 Breakfast Options** (3 choices with calories)
3. **☀️ Lunch Options** (3 choices with calories)
4. **🌙 Dinner Options** (3 choices with calories)
5. **🥜 Healthy Snacks** (2-3 options)
6. **💪 Weekly Workout Plan** (day-by-day)
7. **💧 Hydration Goal**
8. **📈 Expected Progress Timeline**"""
    result = ask_gemini(prompt)
    return jsonify({"result": result})


# ──────────────────────────────────────────────
# MENTAL WELLNESS
# ──────────────────────────────────────────────
@app.route("/wellness")
@login_required
def wellness():
    uid = session["user_id"]
    conn = get_db()
    moods = conn.execute("SELECT mood, note, date FROM mood_logs WHERE user_id=? ORDER BY date DESC LIMIT 14", (uid,)).fetchall()
    conn.close()
    return render_template("wellness.html", moods=[dict(m) for m in moods])


@app.route("/api/log-mood", methods=["POST"])
@login_required
def log_mood():
    uid = session["user_id"]
    mood = request.json.get("mood", 5)
    note = request.json.get("note", "")
    conn = get_db()
    conn.execute("INSERT INTO mood_logs (user_id,mood,note) VALUES (?,?,?)", (uid, mood, note))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.route("/api/wellness-advice", methods=["POST"])
@login_required
def wellness_advice():
    mood = request.json.get("mood", 5)
    note = request.json.get("note", "")
    prompt = f"""A person rated their mood {mood}/10 today. Their note: "{note}"

Provide compassionate mental wellness support:
1. **💙 Acknowledgment** - Validate their feelings
2. **🧘 Immediate Coping Strategies** (3-5 techniques)
3. **🌈 Mood-Boosting Activities** (personalized suggestions)
4. **🧠 Cognitive Reframing** - Positive perspective shift
5. **🌙 Tonight's Self-Care Ritual**
6. **📅 This Week's Mental Health Goals**

Be warm, empathetic, and encouraging."""
    result = ask_gemini(prompt)
    return jsonify({"result": result})


# ──────────────────────────────────────────────
# REMINDERS
# ──────────────────────────────────────────────
@app.route("/reminders")
@login_required
def reminders():
    uid = session["user_id"]
    conn = get_db()
    rems = conn.execute("SELECT * FROM reminders WHERE user_id=? ORDER BY time", (uid,)).fetchall()
    conn.close()
    return render_template("reminders.html", reminders=[dict(r) for r in rems])


@app.route("/api/reminder", methods=["POST"])
@login_required
def add_reminder():
    uid = session["user_id"]
    d = request.json
    conn = get_db()
    conn.execute("INSERT INTO reminders (user_id,title,time,type) VALUES (?,?,?,?)",
                 (uid, d["title"], d["time"], d["type"]))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.route("/api/reminder/<int:rid>", methods=["DELETE"])
@login_required
def delete_reminder(rid):
    conn = get_db()
    conn.execute("DELETE FROM reminders WHERE id=? AND user_id=?", (rid, session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────
# PHYSIOTHERAPY
# ──────────────────────────────────────────────
@app.route("/physio")
@login_required
def physio():
    return render_template("physio.html")


# ──────────────────────────────────────────────
# HEALTH SCORE API
# ──────────────────────────────────────────────
@app.route("/api/health-score")
@login_required
def health_score():
    uid = session["user_id"]
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    moods = conn.execute("SELECT AVG(mood) as avg_mood FROM mood_logs WHERE user_id=?", (uid,)).fetchone()
    health = conn.execute("SELECT * FROM health_data WHERE user_id=? ORDER BY date DESC LIMIT 1", (uid,)).fetchone()
    conn.close()

    score = 50
    if user["weight"] and user["height"]:
        h_m = user["height"] / 100
        bmi = user["weight"] / (h_m * h_m)
        if 18.5 <= bmi <= 24.9: score += 20

    if moods and moods["avg_mood"]:
        score += int(moods["avg_mood"] * 2)

    if health:
        if health["steps"] >= 8000: score += 15
        if health["water_ml"] >= 2000: score += 10
        if 7 <= health["sleep_hours"] <= 9: score += 5

    score = min(score, 100)
    return jsonify({"score": score})


# ──────────────────────────────────────────────
# UPDATE HEALTH DATA
# ──────────────────────────────────────────────
@app.route("/api/health-data", methods=["POST"])
@login_required
def update_health_data():
    uid = session["user_id"]
    d = request.json
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    existing = conn.execute("SELECT id FROM health_data WHERE user_id=? AND date=?", (uid, today)).fetchone()
    if existing:
        conn.execute("UPDATE health_data SET steps=?,water_ml=?,sleep_hours=? WHERE id=?",
                     (d.get("steps", 0), d.get("water_ml", 0), d.get("sleep_hours", 0), existing["id"]))
    else:
        conn.execute("INSERT INTO health_data (user_id,steps,water_ml,sleep_hours,date) VALUES (?,?,?,?,?)",
                     (uid, d.get("steps", 0), d.get("water_ml", 0), d.get("sleep_hours", 0), today))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    init_db()
    print("🏥 HealthPilot AI running at http://127.0.0.1:5000")
    app.run(debug=True)