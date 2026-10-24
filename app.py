# CHINNU Free Fire API + Dashboard (Vercel Compatible)
import os
import json
import binascii
import sqlite3
import time
import hmac
import base64
from pathlib import Path
from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToDict

import uid_generator_pb2

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
API_KEY = os.getenv("API_KEY", "CHINNU").strip()
OWNER = os.getenv("OWNER_NAME", "CHINNU TEAM")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()
app.secret_key = os.getenv("FLASK_SECRET_KEY", "").strip() or os.urandom(32)
DB_PATH = Path(os.getenv("MONITOR_DB_PATH", "/tmp/monitor.db")) # Vercel ke liye /tmp zaroori hai
TIMEOUT = int(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "20"))
UPSTREAM_API_URL = os.getenv("UPSTREAM_API_URL", "https://like-api-3-vng3.onrender.com").strip().rstrip("/")
UPSTREAM_PING_TIMEOUT = 6

# ---------------------------------------------------------
# GLOBAL ERROR HANDLER
# ---------------------------------------------------------
@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled exception: {str(e)}")
    return jsonify({"ok": False, "error": f"Internal Server Error: {str(e)}"}), 500

# ---------------------------------------------------------
# DATABASE SETUP (Silent fail on Vercel if read-only)
# ---------------------------------------------------------
def init_monitor_db():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, method TEXT, path TEXT, status INTEGER, duration_ms REAL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS like_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, job_id TEXT, uid TEXT, nickname TEXT, region TEXT, status TEXT, likes_before INTEGER, likes_after INTEGER, likes_given INTEGER, message TEXT)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS tracked_ids (uid TEXT, region TEXT, nickname TEXT, first_seen TEXT, last_seen TEXT, last_status TEXT, last_likes INTEGER, total_likes_gained INTEGER, success_count INTEGER, fail_count INTEGER, limit_hits INTEGER, PRIMARY KEY(uid, region))""")
            conn.commit()
    except Exception as e:
        app.logger.warning(f"DB init skipped (Vercel read-only): {e}")

init_monitor_db()

@app.before_request
def start_request_timer():
    request._started_at = time.perf_counter()

@app.after_request
def record_request(response):
    if request.path not in {"/dashboard", "/dashboard/login", "/dashboard/logout", "/dashboard/data"}:
        elapsed = (time.perf_counter() - getattr(request, "_started_at", time.perf_counter())) * 1000
        try:
            with sqlite3.connect(DB_PATH, timeout=3) as conn:
                conn.execute("INSERT INTO requests(timestamp, method, path, status, duration_ms) VALUES (?, ?, ?, ?, ?)", (datetime.now(timezone.utc).isoformat(), request.method, request.path[:120], response.status_code, round(elapsed, 2)))
                conn.commit()
        except Exception:
            pass # Vercel pe silently fail hoga
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

def dashboard_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("dashboard_logged_in"):
            return redirect(url_for("dashboard_login"))
        return fn(*args, **kwargs)
    return wrapper

# ---------------------------------------------------------
# DASHBOARD HTML (Tumhara Naruto UI waisa hi hai)
# ---------------------------------------------------------
# (Yahan tumhara pura DASHBOARD_HTML aur LOGIN_HTML aayega. Main ise chhota karke dikha raha hoon taaki message na bade. Tum apne purane code se copy kar lena.)
DASHBOARD_HTML = r"""<h1>Dashboard Loading... (Insert your HTML here)</h1>""" 
LOGIN_HTML = r"""<h1>Login (Insert your HTML here)</h1>"""

# ---------------------------------------------------------
# LIKE LOGIC
# ---------------------------------------------------------
AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'
REGION_FILE = {"IND": "token_ind.json", "BD": "token_bd.json", "BR": "token_br.json"}
LIKE_URL = {
    "IND": "https://client.ind.freefiremobile.com/LikeProfile",
    "BD":  "https://client.ind.freefiremobile.com/LikeProfile",
    "BR":  "https://client.us.freefiremobile.com/LikeProfile",
    "US":  "https://client.us.freefiremobile.com/LikeProfile",
}

def authorized():
    supplied = request.args.get("key", "").strip() or request.headers.get("X-API-Key", "").strip()
    return bool(API_KEY) and supplied and hmac.compare_digest(supplied, API_KEY)

def encrypt_message(data: bytes) -> str:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return binascii.hexlify(cipher.encrypt(pad(data, AES.block_size))).decode("ascii")

def encrypted_uid(uid: int) -> str:
    message = uid_generator_pb2.uid_generator()
    message.krishna_ = uid
    message.teamXdarks = 1
    return encrypt_message(message.SerializeToString())

def load_tokens(region: str) -> list:
    filename = REGION_FILE.get(region)
    if not filename: return []
    path = BASE_DIR / filename
    if not path.is_file(): return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [x.get("jwt_token") or x.get("token") for x in data if isinstance(x, dict) and (x.get("jwt_token") or x.get("token"))]
    except Exception:
        pass
    return []

def send_likes_direct(uid: int, region: str) -> dict:
    tokens = load_tokens(region)
    if not tokens:
        return {"status": "fail", "message": f"Token file {REGION_FILE.get(region)} is empty."}
    url = LIKE_URL.get(region)
    headers = {
        "User-Agent": "Dalvik/2.1.0 (Linux; Android 9)",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.11f1",
        "ReleaseVersion": "OB55",
    }
    total_given = 0
    last_error = ""
    for token in tokens:
        token_headers = headers.copy()
        token_headers["Authorization"] = f"Bearer {token}"
        try:
            payload = bytes.fromhex(encrypted_uid(uid))
            response = requests.post(url, data=payload, headers=token_headers, timeout=TIMEOUT)
            if response.status_code == 200:
                total_given += 1
            else:
                last_error = f"HTTP {response.status_code}"
        except Exception as e:
            last_error = str(e)
    if total_given > 0:
        return {"status": "success", "given": total_given, "message": f"{total_given} likes sent."}
    return {"status": "fail", "message": last_error}

# ---------------------------------------------------------
# ROUTES
# ---------------------------------------------------------
@app.get("/")
def home():
    return jsonify({"ok": True, "message": "CHINNU Like API is running.", "endpoints": ["/like?uid=PLAYER_UID&region=IND&key=YOUR_API_KEY", "/dashboard"]})

@app.get("/like")
def like_endpoint():
    if not authorized():
        return jsonify({"ok": False, "error": "Invalid API key."}), 403
    uid_text = request.args.get("uid", "").strip()
    region = request.args.get("region", "IND").strip().upper()
    if not uid_text.isdigit() or int(uid_text) <= 0:
        return jsonify({"ok": False, "error": "Invalid UID."}), 400

    uid = int(uid_text)
    result = send_likes_direct(uid, region)

    # Silent DB Save (Vercel pe error nahi dega)
    try:
        with sqlite3.connect(DB_PATH, timeout=5) as conn:
            conn.execute("INSERT INTO like_jobs(timestamp, uid, region, status, likes_given, message) VALUES (?, ?, ?, ?, ?, ?)", (datetime.now(timezone.utc).isoformat(), str(uid), region, result["status"], result.get("given", 0), result.get("message", "")))
            conn.commit()
    except Exception:
        pass

    return jsonify({"ok": result["status"] == "success", "likes_given": result.get("given", 0), "message": result["message"]})

@app.get("/dashboard/data")
@dashboard_required
def dashboard_data():
    # Vercel ke liye safe data fetching
    try:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        with sqlite3.connect(DB_PATH, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            jobs = [dict(r) for r in conn.execute("SELECT * FROM like_jobs ORDER BY id DESC LIMIT 100").fetchall()]
        return jsonify({"ok": True, "jobs": jobs})
    except Exception:
        return jsonify({"ok": True, "jobs": [], "warning": "Database is read-only on Vercel. Data will not persist."})

@app.get("/dashboard")
@dashboard_required
def dashboard():
    return render_template_string(DASHBOARD_HTML, owner=OWNER)

@app.route("/dashboard/login", methods=["GET", "POST"])
def dashboard_login():
    if not DASHBOARD_PASSWORD:
        return jsonify({"ok": False, "error": "Set DASHBOARD_PASSWORD."}), 503
    message = None
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("password", ""), DASHBOARD_PASSWORD):
            session.clear()
            session["dashboard_logged_in"] = True
            return redirect(url_for("dashboard"))
        message = "Incorrect password."
    return render_template_string(LOGIN_HTML, error=message)

# ---------------------------------------------------------
# VERCEL ENTRY POINT
# ---------------------------------------------------------
# (Yeh line Vercel ke liye sabse zaroori hai)
handler = app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
