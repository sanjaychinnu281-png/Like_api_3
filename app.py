# CHINNU Free Fire API - Render-safe starter
# Provides player information and current likes count. It does NOT send automated likes.
import os
import json
import binascii
from pathlib import Path
from datetime import datetime, timezone
import sqlite3
import time
from functools import wraps
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToDict

import like_count_pb2
import uid_generator_pb2

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
API_KEY = os.getenv("API_KEY", "").strip()
OWNER = os.getenv("OWNER_NAME", "CHINNU TEAM")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()
app.secret_key = os.getenv("FLASK_SECRET_KEY", "").strip() or os.urandom(32)
DB_PATH = Path(os.getenv("MONITOR_DB_PATH", str(BASE_DIR / "monitor.db")))
TIMEOUT = 15


def init_monitor_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            status INTEGER NOT NULL,
            duration_ms REAL NOT NULL
        )""")
        conn.commit()


init_monitor_db()


@app.before_request
def start_request_timer():
    request._started_at = time.perf_counter()


@app.after_request
def record_request(response):
    # Never store query strings, API keys, Authorization headers, or request bodies.
    if request.path not in {"/dashboard", "/dashboard/login", "/dashboard/logout"}:
        elapsed = (time.perf_counter() - getattr(request, "_started_at", time.perf_counter())) * 1000
        try:
            with sqlite3.connect(DB_PATH, timeout=3) as conn:
                conn.execute(
                    "INSERT INTO requests(timestamp, method, path, status, duration_ms) VALUES (?, ?, ?, ?, ?)",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"), request.method, request.path[:120], response.status_code, round(elapsed, 2)),
                )
                conn.commit()
        except sqlite3.Error:
            app.logger.exception("Could not save monitoring event")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def dashboard_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("dashboard_logged_in"):
            return redirect(url_for("dashboard_login"))
        return fn(*args, **kwargs)
    return wrapper


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CHINNU Advanced Monitor</title>
<style>
:root{color-scheme:dark;--bg:#0b1220;--panel:#151f32;--panel2:#101a2b;--text:#e5e7eb;--muted:#9ca3af;--border:#293449;--accent:#3b82f6;--accentText:#fff;--good:#22c55e;--bad:#f87171;--warn:#fbbf24;--shadow:0 12px 30px #0002}
html[data-theme="light"]{color-scheme:light;--bg:#f3f6fb;--panel:#fff;--panel2:#edf2f9;--text:#172033;--muted:#64748b;--border:#d7dfeb;--accent:#2563eb;--accentText:#fff;--good:#15803d;--bad:#dc2626;--warn:#a16207;--shadow:0 12px 30px #1720330d}
html[data-theme="neon"]{color-scheme:dark;--bg:#080711;--panel:#151126;--panel2:#100d20;--text:#f5f3ff;--muted:#b4a7d6;--border:#44316b;--accent:#c026d3;--accentText:#fff;--good:#4ade80;--bad:#fb7185;--warn:#fde047;--shadow:0 0 22px #a21caf20}
html[data-theme="ocean"]{color-scheme:dark;--bg:#061923;--panel:#0c2938;--panel2:#08222f;--text:#e0f7ff;--muted:#8fb9c8;--border:#1c4b60;--accent:#0891b2;--accentText:#fff;--good:#2dd4bf;--bad:#fb7185;--warn:#facc15;--shadow:0 12px 30px #00101855}
*{box-sizing:border-box}body{font-family:Inter,system-ui,-apple-system,Arial,sans-serif;margin:0;background:var(--bg);color:var(--text);transition:background .2s,color .2s}main{max-width:1180px;margin:auto;padding:clamp(14px,3vw,28px)}header{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:22px}.brand{display:flex;gap:12px;align-items:center}.logo{display:grid;place-items:center;width:48px;height:48px;border-radius:15px;background:var(--accent);color:white;font-size:23px;box-shadow:var(--shadow)}h1{font-size:clamp(22px,4vw,30px);margin:0}.muted{color:var(--muted)}.sub{margin:5px 0 0;font-size:14px}.actions{display:flex;align-items:center;gap:9px;flex-wrap:wrap}.theme-label{font-size:13px;color:var(--muted)}select,.btn,a.btn{font:inherit;border:1px solid var(--border);border-radius:10px;padding:10px 12px;background:var(--panel);color:var(--text);text-decoration:none}.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accentText)}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}.card{background:var(--panel);border:1px solid var(--border);border-radius:17px;padding:18px;box-shadow:var(--shadow);min-width:0}.card-top{display:flex;justify-content:space-between;align-items:center;gap:8px}.card-label{font-size:13px;color:var(--muted)}.card-icon{width:34px;height:34px;border-radius:11px;background:var(--panel2);display:grid;place-items:center}.num{font-size:clamp(25px,4vw,32px);font-weight:750;letter-spacing:-.04em;margin-top:9px}.unit{font-size:12px;color:var(--muted);margin-top:4px}.section-head{display:flex;justify-content:space-between;align-items:end;gap:12px;flex-wrap:wrap;margin:27px 0 12px}.section-head h2{margin:0;font-size:19px}.tablewrap{overflow:auto;background:var(--panel);border:1px solid var(--border);border-radius:15px;box-shadow:var(--shadow)}table{width:100%;border-collapse:collapse;font-size:13px;min-width:650px}th,td{text-align:left;padding:13px 14px;border-bottom:1px solid var(--border);white-space:nowrap}th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);background:var(--panel2)}tbody tr:hover{background:var(--panel2)}tbody tr:last-child td{border-bottom:0}.pill{display:inline-block;border-radius:999px;padding:4px 8px;font-weight:700;font-size:11px;background:var(--panel2)}.status-ok{color:var(--good)}.status-bad{color:var(--bad)}.status-other{color:var(--warn)}.notice{margin-top:16px;background:var(--panel2);border:1px solid var(--border);padding:13px 15px;border-radius:12px;font-size:12px;line-height:1.6;color:var(--muted)}footer{margin-top:20px;color:var(--muted);font-size:12px;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}@media(max-width:560px){main{padding:13px}.logo{width:42px;height:42px}.card{padding:15px}.actions{width:100%}.actions select{flex:1}}
</style></head><body><main>
<header><div class="brand"><div class="logo">✦</div><div><h1>CHINNU Advanced Monitor</h1><p class="muted sub">API activity overview · {{ owner }}</p></div></div><div class="actions"><label class="theme-label" for="themeSelect">Theme</label><select id="themeSelect" aria-label="Choose dashboard theme"><option value="dark">Dark</option><option value="light">Light</option><option value="neon">Neon</option><option value="ocean">Ocean</option></select><a class="btn primary" href="/dashboard">↻ Refresh</a><a class="btn" href="/dashboard/logout">Log out</a></div></header>
<section class="cards"><article class="card"><div class="card-top"><div class="card-label">Total logged requests</div><div class="card-icon">⇄</div></div><div class="num">{{ total }}</div><div class="unit">All recorded endpoints</div></article><article class="card"><div class="card-top"><div class="card-label">Successful responses</div><div class="card-icon">✓</div></div><div class="num">{{ success }}</div><div class="unit">HTTP 2xx</div></article><article class="card"><div class="card-top"><div class="card-label">Error responses</div><div class="card-icon">!</div></div><div class="num">{{ errors }}</div><div class="unit">HTTP 4xx / 5xx</div></article><article class="card"><div class="card-top"><div class="card-label">Average response time</div><div class="card-icon">◷</div></div><div class="num">{{ avg }}<span style="font-size:15px;font-weight:500"> ms</span></div><div class="unit">Across logged requests</div></article></section>
<div class="section-head"><div><h2>Recent request activity</h2><div class="muted sub">Latest 100 logged requests</div></div><span class="pill">LIVE DATA · refresh to update</span></div><div class="tablewrap"><table><thead><tr><th>Time (UTC)</th><th>Method</th><th>Endpoint</th><th>Status</th><th>Response time</th></tr></thead><tbody>{% for r in rows %}<tr><td>{{ r[1] }}</td><td>{{ r[2] }}</td><td>{{ r[3] }}</td><td>{% if r[4] >= 200 and r[4] < 300 %}<span class="pill status-ok">{{ r[4] }} · OK</span>{% elif r[4] >= 400 %}<span class="pill status-bad">{{ r[4] }} · ERROR</span>{% else %}<span class="pill status-other">{{ r[4] }}</span>{% endif %}</td><td>{{ r[5] }} ms</td></tr>{% else %}<tr><td colspan="5" class="muted">No requests logged yet. Call an API endpoint to see activity here.</td></tr>{% endfor %}</tbody></table></div>
<div class="notice"><strong>Data accuracy:</strong> This page tracks HTTP requests, status codes and response time. It does not currently record confirmed likes per UID or “limit reached” events. The current <code>/like</code> endpoint is read-only and does not send likes, so likes-given totals cannot be inferred from these logs. API keys, query values and tokens are not stored in the request log. Local SQLite data may reset on redeploy/restart unless persistent storage is configured.</div>
<footer><span>CHINNU TEAM · Private monitoring</span><span>Theme preference is saved in this browser</span></footer></main>
<script>(function(){const key='chinnu-monitor-theme';const select=document.getElementById('themeSelect');function apply(theme){if(!['dark','light','neon','ocean'].includes(theme))theme='dark';document.documentElement.setAttribute('data-theme',theme);select.value=theme;try{localStorage.setItem(key,theme)}catch(e){}}let saved='dark';try{saved=localStorage.getItem(key)||'dark'}catch(e){}apply(saved);select.addEventListener('change',()=>apply(select.value));})();</script>
</body></html>"""

LOGIN_HTML = """<!doctype html><html><head><meta name=viewport content="width=device-width,initial-scale=1"><title>CHINNU Monitor Login</title><style>body{font-family:system-ui;background:#0b1220;color:#e5e7eb;display:grid;place-items:center;min-height:100vh;margin:0}.box{width:min(340px,85vw);background:#151f32;padding:24px;border-radius:16px}input,button{box-sizing:border-box;width:100%;padding:12px;margin:8px 0;border-radius:8px;border:1px solid #334155}button{background:#2563eb;color:white;border:0}</style></head><body><form class=box method=post><h2>CHINNU Monitor</h2><p>Enter dashboard password.</p>{% if error %}<p style=color:#fca5a5>{{ error }}</p>{% endif %}<input type=password name=password required placeholder="Dashboard password"><button>Login</button></form></body></html>"""

# Match the protocol constants used by the supplied project. Do not expose credentials in source code.
AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'
REGION_FILE = {
    "IND": "token_ind.json",
    "BD": "token_bd.json",
    "BR": "token_br.json",
    "US": "token_br.json",
    "SAC": "token_br.json",
    "NA": "token_br.json",
}
REGION_URL = {
    "IND": "https://client.ind.freefiremobile.com/GetPlayerPersonalShow",
    "BR": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
    "US": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
    "SAC": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
    "NA": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
}
DEFAULT_URL = "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"


def error(message, status):
    return jsonify({"ok": False, "error": message}), status


def authorized():
    supplied = request.args.get("key", "").strip() or request.headers.get("X-API-Key", "").strip()
    return bool(API_KEY) and supplied and __import__("hmac").compare_digest(supplied, API_KEY)


def encrypt_message(data: bytes) -> str:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return binascii.hexlify(cipher.encrypt(pad(data, AES.block_size))).decode("ascii")


def encrypted_uid(uid: int) -> str:
    message = uid_generator_pb2.uid_generator()
    message.krishna_ = uid
    message.teamXdarks = 1
    return encrypt_message(message.SerializeToString())


def load_token(region: str) -> str:
    filename = REGION_FILE.get(region)
    if not filename:
        raise ValueError("Unsupported region. Use IND, BD, BR, US, SAC, or NA.")
    path = BASE_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Missing {filename}. Add your own authorized token file to the project.")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise ValueError(f"{filename} must contain a non-empty JSON list.")
    # The uploaded files use jwt_token; the original app incorrectly expected token.
    token = data[0].get("jwt_token") or data[0].get("token")
    if not token:
        raise ValueError(f"No jwt_token/token field found in {filename}.")
    return token


def fetch_player(uid: int, region: str) -> dict:
    token = load_token(region)
    url = REGION_URL.get(region, DEFAULT_URL)
    headers = {
        "User-Agent": "Dalvik/2.1.0 (Linux; Android 9)",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.11f1",
        "ReleaseVersion": "OB55",
    }
    response = requests.post(url, data=bytes.fromhex(encrypted_uid(uid)), headers=headers, timeout=TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(f"Upstream game service returned HTTP {response.status_code}.")
    info = like_count_pb2.Info()
    info.ParseFromString(response.content)
    data = MessageToDict(info, preserving_proto_field_name=False)
    account = data.get("AccountInfo", {})
    returned_uid = int(account.get("UID", 0) or 0)
    if not returned_uid:
        raise LookupError("Player was not found or the upstream response could not be read.")
    return {
        "uid": returned_uid,
        "nickname": str(account.get("PlayerNickname", "")),
        "likes": int(account.get("Likes", 0) or 0),
        "region": region,
    }


@app.route("/dashboard/login", methods=["GET", "POST"])
def dashboard_login():
    if not DASHBOARD_PASSWORD:
        return error("Monitoring dashboard is not configured. Set DASHBOARD_PASSWORD in Render environment variables.", 503)
    message = None
    if request.method == "POST":
        supplied = request.form.get("password", "")
        import hmac
        if hmac.compare_digest(supplied, DASHBOARD_PASSWORD):
            session.clear()
            session["dashboard_logged_in"] = True
            return redirect(url_for("dashboard"))
        message = "Incorrect password."
    return render_template_string(LOGIN_HTML, error=message)


@app.get("/dashboard/logout")
def dashboard_logout():
    session.clear()
    return redirect(url_for("dashboard_login"))


@app.get("/dashboard")
@dashboard_required
def dashboard():
    with sqlite3.connect(DB_PATH, timeout=3) as conn:
        total = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        success = conn.execute("SELECT COUNT(*) FROM requests WHERE status >= 200 AND status < 300").fetchone()[0]
        errors = conn.execute("SELECT COUNT(*) FROM requests WHERE status >= 400").fetchone()[0]
        avg = conn.execute("SELECT COALESCE(ROUND(AVG(duration_ms), 2), 0) FROM requests").fetchone()[0]
        rows = conn.execute("SELECT id, timestamp, method, path, status, duration_ms FROM requests ORDER BY id DESC LIMIT 100").fetchall()
    return render_template_string(DASHBOARD_HTML, total=total, success=success, errors=errors, avg=avg, rows=rows, owner=OWNER)


@app.get("/")
def home():
    return jsonify({
        "name": OWNER,
        "ok": True,
        "message": "Free Fire player API is running.",
        "endpoints": ["/health", "/player-info?uid=PLAYER_UID&server_name=IND&key=YOUR_API_KEY", "/like?uid=PLAYER_UID&server_name=IND&key=YOUR_API_KEY", "/dashboard"],
        "note": "The /like endpoint reports current likes only; it does not automate or send likes."
    })


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": OWNER, "time_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z"})


def query_player():
    if not authorized():
        return None, error("Invalid or missing API key.", 403)
    uid_text = request.args.get("uid", "").strip()
    region = request.args.get("server_name", "IND").strip().upper()
    if not uid_text.isdigit() or int(uid_text) <= 0:
        return None, error("uid must be a positive numeric player UID.", 400)
    try:
        return fetch_player(int(uid_text), region), None
    except ValueError as exc:
        return None, error(str(exc), 400)
    except FileNotFoundError as exc:
        return None, error(str(exc), 503)
    except LookupError as exc:
        return None, error(str(exc), 404)
    except requests.RequestException:
        return None, error("Could not connect to the upstream service. Try again later.", 502)
    except Exception as exc:
        app.logger.exception("Player lookup failed")
        return None, error("Player lookup failed. Check Render logs and token validity.", 502)


@app.get("/player-info")
def player_info():
    player, failure = query_player()
    if failure:
        return failure
    return jsonify({"ok": True, "player": player, "owner": OWNER})


@app.get("/like")
def like_info():
    # Safe, read-only likes lookup. The uploaded original attempted 1,100 requests per call;
    # that high-volume action has intentionally been removed.
    player, failure = query_player()
    if failure:
        return failure
    return jsonify({
        "ok": True,
        "UID": player["uid"],
        "PlayerNickname": player["nickname"],
        "LikesbeforeCommand": player["likes"],
        "LikesafterCommand": player["likes"],
        "LikesGivenByAPI": 0,
        "region": player["region"],
        "Owner": OWNER,
        "message": "Current likes count only; no likes were sent."
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
