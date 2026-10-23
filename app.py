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


DASHBOARD_HTML = r"""<!doctype html><html><head><meta name=viewport content="width=device-width,initial-scale=1"><title>CHINNU API Monitor</title>
<style>body{font-family:system-ui,Arial;margin:0;background:#0b1220;color:#e5e7eb}main{max-width:1050px;margin:auto;padding:20px}.muted{color:#9ca3af}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}.card{background:#151f32;border:1px solid #273449;border-radius:14px;padding:16px}.num{font-size:28px;font-weight:700}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:10px;border-bottom:1px solid #293449;word-break:break-word}.tablewrap{overflow:auto;background:#151f32;border-radius:12px}a,button{color:#fff;background:#2563eb;padding:9px 12px;border:0;border-radius:8px;text-decoration:none}header{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}</style></head><body><main>
<header><div><h1>📡 CHINNU API Monitor</h1><p class=muted>Request activity · refresh the page to update</p></div><a href="/dashboard/logout">Log out</a></header>
<div class=cards><div class=card><div class=muted>Total logged requests</div><div class=num>{{ total }}</div></div><div class=card><div class=muted>Successful (2xx)</div><div class=num>{{ success }}</div></div><div class=card><div class=muted>Errors (4xx/5xx)</div><div class=num>{{ errors }}</div></div><div class=card><div class=muted>Average response</div><div class=num>{{ avg }} ms</div></div></div>
<h2>Recent requests</h2><p class=muted>API keys, query values, tokens and request bodies are not stored here.</p><div class=tablewrap><table><thead><tr><th>Time (UTC)</th><th>Method</th><th>Endpoint</th><th>Status</th><th>Time</th></tr></thead><tbody>{% for r in rows %}<tr><td>{{ r[1] }}</td><td>{{ r[2] }}</td><td>{{ r[3] }}</td><td>{{ r[4] }}</td><td>{{ r[5] }} ms</td></tr>{% else %}<tr><td colspan=5>No requests logged yet.</td></tr>{% endfor %}</tbody></table></div>
<p class=muted>Monitor database is local to this Render instance. On free instances, data may reset or disappear after redeploy/restart. Use a persistent disk or external database for durable logs.</p></main></body></html>"""

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
    return render_template_string(DASHBOARD_HTML, total=total, success=success, errors=errors, avg=avg, rows=rows)


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
