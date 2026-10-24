# CHINNU Free Fire API - Render-safe starter (UPDATED)
import os
import json
import binascii
from pathlib import Path
from datetime import datetime, timezone
import sqlite3
import time
import base64
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
API_KEY = os.getenv("API_KEY", "CHINNU").strip()
OWNER = os.getenv("OWNER_NAME", "CHINNU TEAM")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()
app.secret_key = os.getenv("FLASK_SECRET_KEY", "").strip() or os.urandom(32)
DB_PATH = Path(os.getenv("MONITOR_DB_PATH", str(BASE_DIR / "monitor.db")))
TIMEOUT = int(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "15"))
UPSTREAM_API_URL = os.getenv("UPSTREAM_API_URL", "https://like-api-3-vng3.onrender.com").strip().rstrip("/")
UPSTREAM_PING_TIMEOUT = 6

# ---------------------------------------------------------
# GLOBAL ERROR HANDLERS (Prevents HTML 500 crashes)
# ---------------------------------------------------------
@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled exception: {str(e)}")
    return jsonify({"ok": False, "error": f"Internal Server Error: {str(e)}"}), 500

@app.errorhandler(404)
def handle_404(e):
    return jsonify({"ok": False, "error": "Endpoint not found"}), 404

@app.errorhandler(405)
def handle_405(e):
    return jsonify({"ok": False, "error": "Method not allowed"}), 405

# ---------------------------------------------------------
# DATABASE & MONITORING SETUP
# ---------------------------------------------------------
def init_monitor_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, method TEXT NOT NULL, 
            path TEXT NOT NULL, status INTEGER NOT NULL, duration_ms REAL NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS like_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, job_id TEXT, 
            uid TEXT NOT NULL, nickname TEXT NOT NULL DEFAULT '', region TEXT NOT NULL, 
            status TEXT NOT NULL, likes_before INTEGER NOT NULL DEFAULT 0, 
            likes_after INTEGER NOT NULL DEFAULT 0, likes_given INTEGER NOT NULL DEFAULT 0, 
            message TEXT NOT NULL DEFAULT '')""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tracked_ids (
            uid TEXT NOT NULL, region TEXT NOT NULL, nickname TEXT NOT NULL DEFAULT '', 
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, last_status TEXT NOT NULL DEFAULT 'waiting', 
            last_likes INTEGER NOT NULL DEFAULT 0, total_likes_gained INTEGER NOT NULL DEFAULT 0, 
            success_count INTEGER NOT NULL DEFAULT 0, fail_count INTEGER NOT NULL DEFAULT 0, 
            limit_hits INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(uid, region))""")
        conn.commit()

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
                conn.execute(
                    "INSERT INTO requests(timestamp, method, path, status, duration_ms) VALUES (?, ?, ?, ?, ?)",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"), request.method, request.path[:120], response.status_code, round(elapsed, 2)),
                )
                conn.commit()
        except sqlite3.Error:
            pass
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

# (DASHBOARD_HTML and LOGIN_HTML remain the same as your original code - kept out for brevity)
DASHBOARD_HTML = r"""YOUR_ORIGINAL_DASHBOARD_HTML_HERE"""
LOGIN_HTML = r"""YOUR_ORIGINAL_LOGIN_HTML_HERE"""

# ---------------------------------------------------------
# PROTOCOL & API LOGIC
# ---------------------------------------------------------
AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'
REGION_FILE = {
    "IND": "token_ind.json", "BD": "token_bd.json", "BR": "token_br.json",
    "US": "token_br.json", "SAC": "token_br.json", "NA": "token_br.json",
}
REGION_URL = {
    "IND": "https://client.ind.freefiremobile.com/GetPlayerPersonalShow",
    "BD":  "https://client.ind.freefiremobile.com/GetPlayerPersonalShow",
    "BR":  "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
    "US":  "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
    "SAC": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
    "NA":  "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
}

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
        raise ValueError("Unsupported region.")
    path = BASE_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Missing {filename}.")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise ValueError(f"{filename} is empty. Add a valid JWT token.")
    token = data[0].get("jwt_token") or data[0].get("token")
    if not token:
        raise ValueError(f"No jwt_token found in {filename}.")
    return token

def fetch_player_direct(uid: int, region: str) -> dict:
    """Attempts to fetch directly from Free Fire servers"""
    token = load_token(region)
    url = REGION_URL.get(region)
    if not url:
        raise ValueError(f"Unsupported region '{region}'.")
    
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
        print(f"[DIRECT API ERROR] Status: {response.status_code}, Body: {response.text[:200]}")
        raise RuntimeError(f"HTTP {response.status_code}")
        
    info = like_count_pb2.Info()
    info.ParseFromString(response.content)
    data = MessageToDict(info, preserving_proto_field_name=False)
    account = data.get("AccountInfo", {})
    returned_uid = int(account.get("UID", 0) or 0)
    if not returned_uid:
        raise LookupError("Player not found.")
        
    return {
        "uid": returned_uid,
        "nickname": str(account.get("PlayerNickname", "")),
        "likes": int(account.get("Likes", 0) or 0),
        "region": region,
    }

def fetch_player_fallback(uid: int, region: str) -> dict:
    """Attempts to fetch from your secondary UPSTREAM_API_URL if direct fails"""
    if not UPSTREAM_API_URL:
        raise RuntimeError("No fallback API configured.")
    
    # We try to hit the fallback API. Adjust the endpoint if needed (e.g., /player-info)
    url = f"{UPSTREAM_API_URL}/player-info"
    params = {"uid": str(uid), "server_name": region, "key": API_KEY}
    
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            # Handle different possible JSON structures from your secondary API
            player_data = data.get("player") or data.get("data") or data
            if isinstance(player_data, dict) and player_data.get("uid"):
                return {
                    "uid": int(player_data.get("uid", uid)),
                    "nickname": str(player_data.get("nickname") or player_data.get("PlayerNickname") or "Unknown"),
                    "likes": int(player_data.get("likes") or player_data.get("Likes") or 0),
                    "region": region
                }
        raise RuntimeError(f"Fallback API returned {resp.status_code}")
    except Exception as e:
        print(f"[FALLBACK ERROR] {str(e)}")
        raise

def query_player():
    if not authorized():
        return None, error("Invalid or missing API key.", 403)

    uid_text = request.args.get("uid", "").strip()
    region = request.args.get("server_name", "IND").strip().upper()

    if not uid_text.isdigit() or int(uid_text) <= 0:
        return None, error("uid must be a positive numeric player UID.", 400)
    if region not in REGION_URL:
        return None, error(f"Unsupported region '{region}'.", 400)

    uid = int(uid_text)

    # STEP 1: Try Direct Free Fire API
    try:
        return fetch_player_direct(uid, region), None
    except Exception as direct_err:
        app.logger.warning(f"Direct API failed ({str(direct_err)}). Trying fallback...")
        
        # STEP 2: Try Fallback API (like-api-3-vng3)
        try:
            return fetch_player_fallback(uid, region), None
        except Exception as fallback_err:
            # Both failed. Return a safe, clean JSON error.
            return None, error(f"All APIs failed. Direct: {str(direct_err)}. Fallback: {str(fallback_err)}", 502)

# ---------------------------------------------------------
# ROUTES
# ---------------------------------------------------------
@app.get("/")
def home():
    return jsonify({
        "name": OWNER, "ok": True, "message": "Free Fire player API is running.",
        "endpoints": ["/health", "/player-info?uid=PLAYER_UID&server_name=IND&key=YOUR_API_KEY", "/like?uid=PLAYER_UID&server_name=IND&key=YOUR_API_KEY", "/dashboard"]
    })

@app.get("/health")
def health():
    return jsonify({"ok": True, "service": OWNER, "time_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z"})

@app.get("/player-info")
def player_info():
    player, failure = query_player()
    if failure: return failure
    return jsonify({"ok": True, "player": player, "owner": OWNER})

@app.get("/like")
def like_info():
    player, failure = query_player()
    if failure: return failure
    return jsonify({
        "ok": True, "UID": player["uid"], "PlayerNickname": player["nickname"],
        "LikesbeforeCommand": player["likes"], "LikesafterCommand": player["likes"],
        "LikesGivenByAPI": 0, "region": player["region"], "Owner": OWNER,
        "message": "Current likes count only; no likes were sent."
    })

# ---------------------------------------------------------
# DASHBOARD ROUTES (Keeping your original logic)
# ---------------------------------------------------------
@app.route("/dashboard/login", methods=["GET", "POST"])
def dashboard_login():
    if not DASHBOARD_PASSWORD:
        return error("Monitoring dashboard is not configured. Set DASHBOARD_PASSWORD.", 503)
    message = None
    if request.method == "POST":
        import hmac
        if hmac.compare_digest(request.form.get("password", ""), DASHBOARD_PASSWORD):
            session.clear()
            session["dashboard_logged_in"] = True
            return redirect(url_for("dashboard"))
        message = "Incorrect password."
    return render_template_string(LOGIN_HTML, error=message)

@app.get("/dashboard/logout")
def dashboard_logout():
    session.clear()
    return redirect(url_for("dashboard_login"))

@app.get("/dashboard/data")
@dashboard_required
def dashboard_data():
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    with sqlite3.connect(DB_PATH, timeout=5) as conn:
        conn.row_factory = sqlite3.Row
        req_today = conn.execute("SELECT COUNT(*) c, COALESCE(ROUND(AVG(duration_ms),2),0) avg FROM requests WHERE date(timestamp, '+5 hours', '+30 minutes')=?", (today,)).fetchone()
        jobs_today = conn.execute("SELECT COUNT(*) total, SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) success, SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END) failed, COALESCE(SUM(likes_given),0) gained FROM like_jobs WHERE date(timestamp, '+5 hours', '+30 minutes')=?", (today,)).fetchone()
        limits = conn.execute("SELECT COUNT(DISTINCT uid || ':' || region) c FROM like_jobs WHERE status='limit_reached' AND date(timestamp, '+5 hours', '+30 minutes')=?", (today,)).fetchone()[0]
        ids_rows = [dict(r) for r in conn.execute("SELECT * FROM tracked_ids ORDER BY last_seen DESC LIMIT 1000").fetchall()]
        jobs = [dict(r) for r in conn.execute("SELECT * FROM like_jobs ORDER BY id DESC LIMIT 100").fetchall()]
        requests_rows = [dict(r) for r in conn.execute("SELECT id,timestamp,method,path,status,duration_ms FROM requests ORDER BY id DESC LIMIT 100").fetchall()]
        regions = []
        for region in ["IND", "BD", "BR", "US", "SAC", "NA"]:
            jj = conn.execute("SELECT SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) success,SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END) failed,COALESCE(SUM(likes_given),0) gained,COUNT(DISTINCT CASE WHEN status='limit_reached' THEN uid END) limits FROM like_jobs WHERE region=? AND date(timestamp, '+5 hours', '+30 minutes')=?", (region,today)).fetchone()
            region_jobs = conn.execute("SELECT COUNT(*) FROM like_jobs WHERE region=? AND date(timestamp, '+5 hours', '+30 minutes')=?", (region,today)).fetchone()[0]
            regions.append({"region":region,"jobs_today":region_jobs,"success_today":jj["success"] or 0,"failed_today":jj["failed"] or 0,"likes_gained_today":jj["gained"] or 0,"limit_accounts_today":jj["limits"] or 0})
    
    seen={(str(x["uid"]),x["region"]) for x in ids_rows}
    for item in read_ids_file():
        if (item["uid"],item["region"]) not in seen:
            ids_rows.append({"uid":item["uid"],"region":item["region"],"nickname":item["nickname"],"last_status":"waiting","last_likes":0,"total_likes_gained":0,"success_count":0,"fail_count":0,"limit_hits":0,"last_seen":"—"})
    
    tokens = token_file_status()
    return jsonify({"ok":True,"metrics":{"requests_today":req_today["c"],"success_today":jobs_today["success"] or 0,"failed_today":jobs_today["failed"] or 0,"likes_gained_today":jobs_today["gained"] or 0,"limit_accounts_today":limits,"tracked_ids":len(ids_rows),"avg_ms":req_today["avg"],"configured_token_files":sum(1 for t in tokens if t["configured"])},"upstream_ping":ping_upstream_api(),"regions":regions,"ids":ids_rows[:1000],"jobs":jobs,"requests":requests_rows,"tokens":tokens})

@app.get("/dashboard")
@dashboard_required
def dashboard():
    return render_template_string(DASHBOARD_HTML, owner=OWNER)

@app.post("/monitor/event")
def monitor_event():
    supplied = request.headers.get("X-API-Key", "").strip()
    import hmac
    if not API_KEY or not supplied or not hmac.compare_digest(supplied, API_KEY):
        return error("Invalid or missing API key.", 403)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error("Send a JSON object.", 400)
    uid = str(payload.get("uid", "")).strip()
    region = str(payload.get("region", "IND")).strip().upper()
    status = str(payload.get("status", "")).strip().lower()
    if not uid.isdigit() or int(uid) <= 0:
        return error("uid must be a positive numeric UID.", 400)
    if region not in {"IND", "BD", "BR", "US", "SAC", "NA"}:
        return error("Unsupported region.", 400)
    if status not in {"success", "fail", "limit_reached"}:
        return error("status must be success, fail, or limit_reached.", 400)
    def nonnegative_int(key):
        try:
            return max(0, min(int(payload.get(key, 0) or 0), 2_000_000_000))
        except (ValueError, TypeError):
            return 0
    if "likes_before" not in payload and "LikesbeforeCommand" in payload:
        payload["likes_before"] = payload.get("LikesbeforeCommand")
    if "likes_after" not in payload and "LikesafterCommand" in payload:
        payload["likes_after"] = payload.get("LikesafterCommand")
    if "likes_given" not in payload and "LikesGivenByAPI" in payload:
        payload["likes_given"] = payload.get("LikesGivenByAPI")
    before = nonnegative_int("likes_before")
    after = nonnegative_int("likes_after")
    gained = nonnegative_int("likes_given")
    if status == "success":
        gained = min(gained, max(0, after - before)) if after >= before else 0
    else:
        gained = 0
    nickname = str(payload.get("nickname", ""))[:80]
    job_id = str(payload.get("job_id", ""))[:100]
    message = str(payload.get("message", ""))[:300]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH, timeout=5) as conn:
        conn.execute("INSERT INTO like_jobs(timestamp,job_id,uid,nickname,region,status,likes_before,likes_after,likes_given,message) VALUES(?,?,?,?,?,?,?,?,?,?)", (now, job_id, uid, nickname, region, status, before, after, gained, message))
        row = conn.execute("SELECT first_seen,total_likes_gained,success_count,fail_count,limit_hits FROM tracked_ids WHERE uid=? AND region=?", (uid, region)).fetchone()
        if row:
            conn.execute("UPDATE tracked_ids SET nickname=CASE WHEN ?='' THEN nickname ELSE ? END,last_seen=?,last_status=?,last_likes=MAX(last_likes,?),total_likes_gained=total_likes_gained+?,success_count=success_count+?,fail_count=fail_count+?,limit_hits=limit_hits+? WHERE uid=? AND region=?", (nickname,nickname,now,status,after,gained,int(status=="success"),int(status=="fail"),int(status=="limit_reached"),uid,region))
        else:
            conn.execute("INSERT INTO tracked_ids(uid,region,nickname,first_seen,last_seen,last_status,last_likes,total_likes_gained,success_count,fail_count,limit_hits) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (uid,region,nickname,now,now,status,after,gained,int(status=="success"),int(status=="fail"),int(status=="limit_reached")))
        conn.commit()
    return jsonify({"ok": True, "recorded": True, "uid": uid, "region": region, "status": status, "confirmed_likes_gained": gained})

def read_ids_file():
    path = BASE_DIR / "ids.json"
    if not path.is_file(): return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict): raw = raw.get("ids", [])
        if not isinstance(raw, list): return []
        clean = []
        for item in raw:
            if not isinstance(item, dict): continue
            uid = str(item.get("uid", "")).strip()
            region = str(item.get("region", "IND")).strip().upper()
            if uid.isdigit() and int(uid) > 0 and region in {"IND", "BD", "BR", "US", "SAC", "NA"}:
                clean.append({"uid": uid, "region": region, "nickname": str(item.get("nickname", ""))[:80]})
        return clean
    except (OSError, json.JSONDecodeError):
        return []

def token_file_status():
    out = []
    for region, filename in [("IND", "token_ind.json"), ("BD", "token_bd.json"), ("BR", "token_br.json")]:
        path = BASE_DIR / filename
        entries = 0
        configured = False
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    entries = sum(1 for x in data if isinstance(x, dict) and bool(x.get("jwt_token") or x.get("token")))
                    configured = entries > 0
            except (OSError, json.JSONDecodeError):
                pass
        out.append({"region": region, "file": filename, "configured": configured, "entries": entries})
    return out

def ping_upstream_api():
    started = time.perf_counter()
    try:
        response = requests.get(UPSTREAM_API_URL, timeout=UPSTREAM_PING_TIMEOUT, allow_redirects=True)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        online = response.status_code < 500
        return {"url": UPSTREAM_API_URL, "online": online, "http_status": response.status_code, "latency_ms": latency_ms, "message": "Reachable" if online else "Upstream server error"}
    except requests.RequestException as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {"url": UPSTREAM_API_URL, "online": False, "http_status": None, "latency_ms": latency_ms, "message": "Connection failed: " + type(exc).__name__}

@app.get("/debug/token-status")
def debug_token_status():
    if not authorized(): return error("Invalid or missing API key.", 403)
    out = {}
    for region, filename in [("IND", "token_ind.json"), ("BD", "token_bd.json"), ("BR", "token_br.json")]:
        path = BASE_DIR / filename
        info = {"file": filename, "exists": path.is_file(), "entries": 0, "usable": 0, "expired": 0, "invalid": 0, "age_hours_max": None}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    info["entries"] = len(data)
                    ages = []
                    for entry in data:
                        if not isinstance(entry, dict):
                            info["invalid"] += 1
                            continue
                        tok = entry.get("jwt_token") or entry.get("token")
                        if not tok or not isinstance(tok, str):
                            info["invalid"] += 1
                            continue
                        parts = tok.split(".")
                        if len(parts) != 3:
                            info["invalid"] += 1
                            continue
                        try:
                            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
                            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                            exp = payload.get("exp")
                            iat = payload.get("iat")
                            now_ts = int(time.time())
                            if exp and exp < now_ts:
                                info["expired"] += 1
                                continue
                            if iat: ages.append((now_ts - iat) / 3600)
                            info["usable"] += 1
                        except Exception:
                            info["invalid"] += 1
                    if ages: info["age_hours_max"] = round(max(ages), 1)
            except (OSError, json.JSONDecodeError) as exc:
                info["read_error"] = type(exc).__name__
        out[region] = info
    return jsonify({"ok": True, "regions": out, "now_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
