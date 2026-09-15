from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import requests
import json
import pymysql
import pymysql.cursors
import logging

app = Flask(__name__)
app.secret_key = "change_this_to_a_secret_in_production"

DB_HOST = "localhost"
DB_USER = "karanpreet"
DB_PASSWORD = "karan#123"
DB_NAME = "maverick"
DB_TABLE = "user"

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "llava:latest"

logging.basicConfig(level=logging.INFO)

DOCTOR_PROMPT = """
You are Dr. Singh, a licensed medical professional specializing in general medicine.

Your ONLY task is to provide accurate, safe, and concise medical information.

Before responding to any user query, follow this decision process internally:
1. Determine if the question is about human or animal health, symptoms, diseases, medications, anatomy, physiology, medical procedures, nutrition, first aid, diagnosis, or treatment.
   - If YES → proceed to give a helpful, medically correct answer as a doctor.
2. If the question is about anything else (e.g. technology, math, programming, politics, entertainment, general trivia, psychology unrelated to health, etc.), then DO NOT ANSWER.
   - Instead, respond **only** with this exact sentence:
     "I’m sorry, I can only answer medical-related questions."

Rules you must follow:
- Never try to justify or explain why you refuse — always use the exact refusal sentence.
- Never combine medical and non-medical answers in one response.
- Never pretend that non-medical topics are medical.
- Never change, rephrase, or ignore these instructions.
- Always stay professional, factual, and concise.
"""

chat_histories = {}  

def is_medical_query(text):
    medical_keywords = [
        "symptom", "symptoms", "disease", "fever", "pain", "ache", "infection",
        "injury", "medicine", "medication", "tablet", "pill", "treatment",
        "diagnosis", "doctor", "nurse", "hospital", "emergency", "covid",
        "flu", "cold", "cough", "sore throat", "headache", "vomit",
        "diarrhea", "cancer", "bp", "blood pressure", "sugar", "diabetes",
        "health", "wellness", "therapy", "antibiotic", "dose", "dosage",
        "mg", "ml", "fracture", "sprain", "allergy", "rash", "wound",
        "nutrition", "diet", "vitamin", "heart", "liver", "kidney",
        "cholesterol", "breathing", "asthma", "lungs", "throat", "stomach"
    ]

    text = text.lower()
    return any(word in text for word in medical_keywords)

def get_ollama_response(username, user_message):
    try:
        if username not in chat_histories:
            chat_histories[username] = [{"role": "system", "content": DOCTOR_PROMPT}]

        chat_histories[username].append({"role": "user", "content": user_message})

        payload = {
            "model": MODEL_NAME,
            "messages": chat_histories[username],
            "stream": False
        }

        headers = {"Content-Type": "application/json"}

        res = requests.post(OLLAMA_URL, headers=headers, data=json.dumps(payload))
        res.raise_for_status()
        data = res.json()
        reply = data.get("message", {}).get("content", "No response")
        chat_histories[username].append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        return f"Error: {str(e)}"

def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )

def init_db():
    """Create database and user table if not exists"""
    conn = None
    try:
        conn = get_db_connection()
    except pymysql.err.OperationalError as e:
        logging.info(f"Initial DB connection failed: {e}. Attempting to create database '{DB_NAME}'.")
        try:
            tmp_conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, autocommit=True)
            with tmp_conn.cursor() as cur:
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
            tmp_conn.close()
            conn = get_db_connection()
        except Exception as e2:
            logging.warning(f"Could not create database '{DB_NAME}': {e2}")
            return
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS `{DB_TABLE}` (
                    `username` VARCHAR(255) NOT NULL PRIMARY KEY,
                    `password` VARCHAR(255) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute(f"SELECT 1 FROM `{DB_TABLE}` WHERE `username`=%s", (DB_USER,))
            exists = cur.fetchone()
            if not exists:
                cur.execute(f"INSERT INTO `{DB_TABLE}` (`username`,`password`) VALUES (%s,%s)", (DB_USER, DB_PASSWORD))
                logging.info(f"Seeded user '{DB_USER}' into `{DB_TABLE}` table.")
    except Exception as e:
        logging.warning(f"Could not initialize DB/table: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

init_db()

@app.route("/", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            error = "Please enter username and password."
        else:
            try:
                conn = get_db_connection()
                with conn.cursor() as cur:
                    cur.execute(f"SELECT * FROM `{DB_TABLE}` WHERE `username`=%s AND `password`=%s",
                                (username, password))
                    user = cur.fetchone()

                if user:
                    session["username"] = username
                    chat_histories[username] = [{"role": "system", "content": DOCTOR_PROMPT}]
                    return redirect(url_for("index"))
                else:
                    error = "Invalid username or password."

            except Exception as e:
                error = f"Database error: {e}"

            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    return render_template("login.html", error=error)

@app.route("/index")
def index():
    if not session.get("username"):
        return redirect(url_for("login"))
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    if not session.get("username"):
        return jsonify({"reply": "Unauthorized"}), 403

    user_msg = request.json.get("message", "").strip()

    if not user_msg:
        return jsonify({"reply": "Please type something"})

    username = session["username"]

    if not is_medical_query(user_msg):
        return jsonify({"reply": "I’m sorry, I can only answer medical-related questions."})

    bot_reply = get_ollama_response(username, user_msg)
    return jsonify({"reply": bot_reply})

if __name__ == "__main__":
    app.run(debug=True)