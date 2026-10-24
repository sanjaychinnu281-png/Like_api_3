# CHINNU Free Fire API - Fast & Fixed Version
import os
import json
import binascii
import time
import hmac
from pathlib import Path
from datetime import datetime
import requests
from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from sqlalchemy import create_engine, text

import uid_generator_pb2

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent

# --- CONFIG ---
API_KEY = "CHINNU"
DASHBOARD_PASSWORD = "CHINNU"
app.secret_key = "chinnu_secret_key_123"
TIMEOUT = 20

# --- DATABASE (Supabase) ---
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL, pool_pre_ping=True) if DATABASE_URL else None

def init_db():
    if not engine: return
    try:
        with engine.begin() as conn:
            conn.execute(text("""CREATE TABLE IF NOT EXISTS like_jobs (
                id SERIAL PRIMARY KEY, timestamp TIMESTAMPTZ DEFAULT NOW(),
                uid VARCHAR(50) NOT NULL, region VARCHAR(10) NOT NULL,
                status VARCHAR(20) NOT NULL, likes_given INTEGER DEFAULT 0, message TEXT DEFAULT '')"""))
    except Exception as e: print("DB Error:", e)

init_db()

# --- HTML UI ---
DASHBOARD_HTML = """
<!DOCTYPE html>
<html><head><title>CHINNU Monitor</title>
<style>body{font-family:sans-serif;background:#0f172a;color:white;padding:20px}h1{color:#38bdf8}
.card{background:#1e293b;padding:15px;margin:10px 0;border-radius:8px}.good{color:#4ade80}.bad{color:#f87171}</style>
</head><body>
<h1>CHINNU Monitor Dashboard</h1>
<button onclick="fetchData()">Refresh Data</button> | <a href="/dashboard/logout" style="color:white">Logout</a>
<div class="card">
  <h3>Today's Stats</h3>
  <p>Total Jobs: <span id="t_jobs">0</span> | Success: <span id="t_succ" class="good">0</span> | Failed: <span id="t_fail" class="bad">0</span> | Likes: <span id="t_likes">0</span></p>
</div>
<div class="card">
  <h3>Weekly Stats</h3>
  <p>Total Jobs: <span id="w_jobs">0</span> | Success: <span id="w_succ" class="good">0</span> | Failed: <span id="w_fail" class="bad">0</span> | Likes: <span id="w_likes">0</span></p>
</div>
<script>
async function fetchData(){
  const r = await fetch('/dashboard/data'); const d = await r.json();
  if(d.ok){
    document.getElementById('t_jobs').innerText = d.daily.total_jobs;
    document.getElementById('t_succ').innerText = d.daily.success;
    document.getElementById('t_fail').innerText = d.daily.failed;
    document.getElementById('t_likes').innerText = d.daily.likes;
    document.getElementById('w_jobs').innerText = d.weekly.total_jobs;
    document.getElementById('w_succ').innerText = d.weekly.success;
    document.getElementById('w_fail').innerText = d.weekly.failed;
    document.getElementById('w_likes').innerText = d.weekly.likes;
  }
}
fetchData(); setInterval(fetchData, 10000);
</script></body></html>
"""

LOGIN_HTML = """
<!DOCTYPE html><html><body style="background:#0f172a;color:white;text-align:center;padding-top:100px">
<h2>CHINNU Dashboard Login</h2>
<form method="POST">
  <input type="password" name="password" placeholder="Enter Password" style="padding:10px">
  <button type="submit" style="padding:10px">Login</button>
</form>
{% if error %}<p style="color:red">{{ error }}</p>{% endif %}
</body></html>
"""

# --- FREE FIRE LOGIC ---
AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'
REGION_FILE = {"IND": "token_ind.json", "BD": "token_bd.json", "BR": "token_br.json"}
LIKE_URL = {"IND": "https://client.ind.freefiremobile.com/LikeProfile", "BD": "https://client.ind.freefiremobile.com/LikeProfile", "BR": "https://client.us.freefiremobile.com/LikeProfile"}

def authorized():
    return request.args.get("key") == API_KEY or request.headers.get("X-API-Key") == API_KEY

def encrypt_message(data: bytes) -> str:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return binascii.hexlify(cipher.encrypt(pad(data, AES.block_size))).decode("ascii")

def send_likes(uid: int, region: str):
    filename = REGION_FILE.get(region)
    if not filename: return {"status": "fail", "message": "Bad Region"}
    path = BASE_DIR / filename
    if not path.is_file(): return {"status": "fail", "message": "Token file missing"}
    try:
        data = json.loads(path.read_text())
        tokens = [x.get("jwt_token") or x.get("token") for x in data if x.get("jwt_token") or x.get("token")]
    except: return {"status": "fail", "message": "Token file error"}
    if not tokens: return {"status": "fail", "message": "Token file empty"}
    
    url = LIKE_URL.get(region)
    total = 0
    for token in tokens:
        headers = {"Authorization": f"Bearer {token}", "User-Agent": "Dalvik/2.1.0", "X-Unity-Version": "2018.4.11f1", "ReleaseVersion": "OB55"}
        msg = uid_generator_pb2.uid_generator()
        msg.krishna_ = uid
        msg.teamXdarks = 1
        payload = bytes.fromhex(encrypt_message(msg.SerializeToString()))
        try:
            r = requests.post(url, data=payload, headers=headers, timeout=TIMEOUT)
            if r.status_code == 200: total += 1
        except: pass
    return {"status": "success", "given": total, "message": f"{total} likes sent"} if total > 0 else {"status": "fail", "message": "All tokens failed"}

# --- ROUTES ---
@app.get("/")
def home(): return jsonify({"ok": True, "msg": "API Running"})

@app.get("/like")
def like_endpoint():
    if not authorized(): return jsonify({"ok": False, "error": "Invalid Key"}), 403
    uid = request.args.get("uid", "").strip()
    region = request.args.get("region", "IND").strip().upper()
    if not uid.isdigit(): return jsonify({"ok": False, "error": "Invalid UID"}), 400
    res = send_likes(int(uid), region)
    if engine:
        try:
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO like_jobs (uid, region, status, likes_given, message) VALUES (:u, :r, :s, :g, :m)"),
                             {"u": uid, "r": region, "s": res["status"], "g": res.get("given", 0), "m": res["message"]})
        except: pass
    return jsonify({"ok": res["status"] == "success", "likes": res.get("given", 0), "msg": res["message"]})

@app.get("/dashboard")
def dashboard():
    if not session.get("logged_in"): return redirect("/dashboard/login")
    return render_template_string(DASHBOARD_HTML)

@app.route("/dashboard/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == DASHBOARD_PASSWORD:
            session["logged_in"] = True
            return redirect("/dashboard")
        return render_template_string(LOGIN_HTML, error="Wrong Password")
    return render_template_string(LOGIN_HTML)

@app.get("/dashboard/logout")
def logout():
    session.clear(); return redirect("/dashboard/login")

@app.get("/dashboard/data")
def dash_data():
    if not session.get("logged_in"): return jsonify({"ok": False}), 401
    if not engine: return jsonify({"ok": False, "error": "No DB"})
    try:
        with engine.begin() as conn:
            d = conn.execute(text("SELECT COUNT(*), SUM(CASE WHEN status='success' THEN 1 ELSE 0 END), SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END), COALESCE(SUM(likes_given),0) FROM like_jobs WHERE timestamp >= CURRENT_DATE")).fetchone()
            w = conn.execute(text("SELECT COUNT(*), SUM(CASE WHEN status='success' THEN 1 ELSE 0 END), SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END), COALESCE(SUM(likes_given),0) FROM like_jobs WHERE timestamp >= CURRENT_DATE - INTERVAL '7 days'")).fetchone()
        return jsonify({"ok": True, "daily": {"total_jobs": d[0], "success": d[1] or 0, "failed": d[2] or 0, "likes": d[3]}, "weekly": {"total_jobs": w[0], "success": w[1] or 0, "failed": w[2] or 0, "likes": w[3]}})
    except Exception as e: return jsonify({"ok": False, "error": str(e)})

if __name__ == "__main__":
    app.run(port=10000)
