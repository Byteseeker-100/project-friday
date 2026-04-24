from flask import Flask, request, jsonify, render_template
import requests
from flask_cors import CORS
import sqlite3
import os

app = Flask(__name__)
CORS(app)

API_KEY = os.getenv("API_KEY")

# ---------------- DATABASE ---------------- #

def init_db():
    conn = sqlite3.connect("friday.db")
    c = conn.cursor()

    # chat memory
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT,
            content TEXT
        )
    """)

    # profile (name etc.)
    c.execute("""
        CREATE TABLE IF NOT EXISTS profile (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # long memory (important facts)
    c.execute("""
        CREATE TABLE IF NOT EXISTS long_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT UNIQUE
        )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------------- MEMORY ---------------- #

def save_message(role, content):
    conn = sqlite3.connect("friday.db")
    c = conn.cursor()
    c.execute("INSERT INTO messages (role, content) VALUES (?, ?)", (role, content))
    conn.commit()
    conn.close()

def load_memory(limit=12):
    conn = sqlite3.connect("friday.db")
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

def clear_memory():
    conn = sqlite3.connect("friday.db")
    c = conn.cursor()
    c.execute("DELETE FROM messages")
    conn.commit()
    conn.close()

# ---------------- PROFILE ---------------- #

def save_profile(key, value):
    conn = sqlite3.connect("friday.db")
    c = conn.cursor()
    c.execute("REPLACE INTO profile (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def load_profile(key):
    conn = sqlite3.connect("friday.db")
    c = conn.cursor()
    c.execute("SELECT value FROM profile WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# ---------------- LONG MEMORY ---------------- #

def save_long_memory(text):
    conn = sqlite3.connect("friday.db")
    c = conn.cursor()
    try:
        c.execute("INSERT INTO long_memory (content) VALUES (?)", (text,))
    except:
        pass  # avoid duplicates
    conn.commit()
    conn.close()

def load_long_memory(limit=5):
    conn = sqlite3.connect("friday.db")
    c = conn.cursor()
    c.execute("SELECT content FROM long_memory ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

# ---------------- ROUTES ---------------- #

@app.route('/')
def home():
    return render_template("index.html")

@app.route('/chat', methods=["POST"])
def chat():
    data = request.get_json()

    if not data or "message" not in data:
        return jsonify({"reply": "Invalid request"}), 400

    user_message = data["message"]
    msg = user_message.lower()

    name = load_profile("name") or ""

    # ---- CLEAR MEMORY ----
    if msg == "clear memory":
        clear_memory()
        return jsonify({"reply": "Memory cleared ✅"})

    # ---- NAME DETECTION ----
    if "my name is" in msg:
        name = msg.split("my name is")[-1].strip().split()[0]
        save_profile("name", name.capitalize())

    elif msg.startswith("i am "):
        name = msg.replace("i am", "").strip().split()[0]
        save_profile("name", name.capitalize())

    # ---- DIRECT RESPONSE ----
    if msg in ["who am i", "what is my name"]:
        name = load_profile("name")
        if name:
            return jsonify({"reply": f"You are {name} 😊"})
        else:
            return jsonify({"reply": "I don't know your name yet."})

    # ---- SMART MEMORY (IMPORTANT FACTS) ----
    important_words = ["goal", "dream", "like", "love", "plan"]

    for word in important_words:
        if word in msg:
            save_long_memory(user_message)

    # ---- SAVE USER MESSAGE ----
    save_message("user", user_message)

    memory = load_memory()
    facts = load_long_memory()

    # ---- SYSTEM PROMPT ----
    system_prompt = {
        "role": "system",
        "content": (
            "You are FRIDAY, an intelligent assistant.\n"
            f"User name: {name}\n"
            f"Important facts:\n{chr(10).join(facts)}\n\n"
            "Rules:\n"
            "- Be natural and helpful\n"
            "- Do NOT repeat introductions\n"
            "- Do NOT say you remember conversations\n"
            "- Do NOT assume powers\n"
            "- Respond like ChatGPT\n"
            "Reply short unless user asks for detailed explanation."
            "Respond like ChatGPT. Be clear and helpful. Keep answers concise unless asked for detail."
        )
    }

    # ---- AI REQUEST ----
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "HTTP-Referer": "http://localhost:5000",
                "X-Title": "FRIDAY AI",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-5.2",
                "messages": [system_prompt] + memory,
                "temperature": 0.7,
                "max_tokens": 500
            },
            timeout=10
        )

        data = response.json()
        reply = data.get("choices", [{}])[0].get("message", {}).get("content", "Error")

    except Exception:
        reply = "⚠️ Network error. Try again."

    # ---- SAVE AI RESPONSE ----
    save_message("assistant", reply)

    return jsonify({"reply": reply})

# ---------------- RUN ---------------- #

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)