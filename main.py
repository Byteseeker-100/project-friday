from flask import Flask, request, jsonify, render_template
import requests
from flask_cors import CORS
import sqlite3
import os

app = Flask(__name__)
CORS(app)

API_KEY = os.getenv("API_KEY")
print("API KEY LOADED:", bool(API_KEY), "length:", len(API_KEY) if API_KEY else 0, flush=True)

# ---------------- DATABASE ---------------- #

def init_db():
    conn = sqlite3.connect("friday.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT,
            content TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS profile (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

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
    except sqlite3.IntegrityError:
        pass
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

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()

    if not data or "message" not in data:
        return jsonify({"reply": "Invalid request"}), 400

    user_message = data["message"].strip()
    msg = user_message.lower()

    if not user_message:
        return jsonify({"reply": "Please type something."})

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
        possible_name = msg.replace("i am", "").strip().split()[0]
        if possible_name not in ["fine", "good", "tired", "sad", "happy", "okay"]:
            name = possible_name
            save_profile("name", name.capitalize())

    # ---- DIRECT RESPONSE ----
    if "who am i" in msg or "what is my name" in msg:
        name = load_profile("name")
        if name:
            return jsonify({"reply": f"Your name is {name} 😊"})
        return jsonify({"reply": "I don't know your name yet."})

    # ---- SMART MEMORY ----
    important_words = ["goal", "dream", "like", "love", "plan", "want", "project"]

    for word in important_words:
        if word in msg:
            save_long_memory(user_message)

    # ---- SAVE USER MESSAGE ----
    save_message("user", user_message)

    memory = load_memory()
    facts = load_long_memory()

    system_prompt = {
        "role": "system",
        "content": (
            "You are FRIDAY, an intelligent assistant.\n"
            f"User name: {name}\n"
            f"Important facts:\n{chr(10).join(facts)}\n\n"
            "Rules:\n"
            "- Be natural and helpful.\n"
            "- Do NOT repeat introductions.\n"
            "- Do NOT say you remember conversations.\n"
            "- Do NOT assume tools or powers you do not have.\n"
            "- Reply short unless the user asks for detailed explanation.\n"
            "- Respond like ChatGPT: clear, useful, and friendly.\n"
        )
    }

    # ---- AI REQUEST WITH FALLBACK ----
    models = [
        "openai/gpt-oss-120b:free",
        "openrouter/auto"
    ]

    reply = None

    for model in models:
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "HTTP-Referer": "https://friday-ai-qk9a.onrender.com",
                    "X-Title": "FRIDAY AI",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [system_prompt] + memory,
                    "temperature": 0.7,
                    "max_tokens": 500
                },
                timeout=15
            )

            data = response.json()

            if response.status_code == 200 and "choices" in data:
                reply = data["choices"][0]["message"]["content"]
                print(f"✅ Used model: {model}", flush=True)
                break
            else:
                print(f"❌ {model} failed:", data, flush=True)

        except Exception as e:
            print(f"⚠️ Error with {model}: {e}", flush=True)

    if not reply:
        reply = "⚠️ AI is temporarily unavailable. Try again."

    save_message("assistant", reply)

    return jsonify({"reply": reply})

# ---------------- RUN ---------------- #

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)