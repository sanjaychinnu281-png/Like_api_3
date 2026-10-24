# CHINNU Free Fire API - Render-safe starter
# Provides player information and current likes count. It does NOT send automated likes.
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
TIMEOUT = int(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "30"))
UPSTREAM_API_URL = os.getenv("UPSTREAM_API_URL", "https://like-api-3-vng3.onrender.com").strip().rstrip("/")
UPSTREAM_PING_TIMEOUT = 6


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
        conn.execute("""CREATE TABLE IF NOT EXISTS like_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            job_id TEXT,
            uid TEXT NOT NULL,
            nickname TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL,
            status TEXT NOT NULL,
            likes_before INTEGER NOT NULL DEFAULT 0,
            likes_after INTEGER NOT NULL DEFAULT 0,
            likes_given INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL DEFAULT ''
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tracked_ids (
            uid TEXT NOT NULL,
            region TEXT NOT NULL,
            nickname TEXT NOT NULL DEFAULT '',
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            last_status TEXT NOT NULL DEFAULT 'waiting',
            last_likes INTEGER NOT NULL DEFAULT 0,
            total_likes_gained INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            fail_count INTEGER NOT NULL DEFAULT 0,
            limit_hits INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(uid, region)
        )""")
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


DASHBOARD_HTML = r"""<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CHINNU FF Advanced Monitor</title><style>
:root{color-scheme:dark;--bg:#080d19;--panel:#111b2d;--panel2:#0b1424;--text:#e7eefc;--muted:#93a4bd;--border:#26354e;--accent:#5b8cff;--good:#35d49a;--bad:#ff6b82;--warn:#ffc857}html[data-theme="light"]{color-scheme:light;--bg:#f1f5fb;--panel:#fff;--panel2:#eaf0f8;--text:#172033;--muted:#64748b;--border:#d5deea;--accent:#2563eb;--good:#15803d;--bad:#dc2626;--warn:#a16207}html[data-theme="neon"]{color-scheme:dark;--bg:#090611;--panel:#171127;--panel2:#100b20;--text:#f5edff;--muted:#b6a5d5;--border:#49316d;--accent:#d946ef;--good:#4ade80;--bad:#fb7185;--warn:#fde047}html[data-theme="ocean"]{color-scheme:dark;--bg:#041821;--panel:#0a2938;--panel2:#08222f;--text:#e0f7ff;--muted:#8fb9c8;--border:#1b4b60;--accent:#22b8d4;--good:#2dd4bf;--bad:#fb7185;--warn:#facc15}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 85% 10%,color-mix(in srgb,var(--accent) 19%,transparent),transparent 38%),radial-gradient(ellipse at 12% 80%,#7c3aed17,transparent 40%),var(--bg);font-family:Inter,system-ui,Arial,sans-serif;color:var(--text);min-height:100vh;overflow-x:hidden}.bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}.stars{position:absolute;inset:0;background-image:radial-gradient(circle at 18% 24%,#fff9 0 1px,transparent 2px),radial-gradient(circle at 70% 28%,#60a5fa9c 0 1.5px,transparent 3px),radial-gradient(circle at 42% 72%,#fff7 0 1px,transparent 2px);background-size:270px 270px,330px 330px,210px 210px;opacity:.35;animation:drift 34s linear infinite}.glow{position:absolute;right:5%;top:8%;width:44vw;height:44vw;border-radius:50%;background:radial-gradient(circle,color-mix(in srgb,var(--accent) 25%,transparent),transparent 68%);filter:blur(20px);animation:pulse 12s ease-in-out infinite}.anime{position:absolute;right:-3vw;bottom:-12vh;width:min(48vw,620px);opacity:.22;filter:drop-shadow(0 0 25px color-mix(in srgb,var(--accent) 35%,transparent));animation:float 14s ease-in-out infinite}main{position:relative;z-index:1;max-width:1400px;margin:auto;padding:22px}header{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:22px}.brand{display:flex;align-items:center;gap:12px}.logo{display:grid;place-items:center;width:48px;height:48px;border-radius:15px;background:var(--accent);color:white;font-size:24px}h1{font-size:clamp(22px,4vw,31px);margin:0}.muted{color:var(--muted)}.sub{font-size:13px;margin-top:5px}.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}select,input,button,.btn{font:inherit;border:1px solid var(--border);border-radius:10px;padding:10px 12px;background:var(--panel);color:var(--text)}button,.btn{cursor:pointer;text-decoration:none}button.primary{background:var(--accent);color:white;border-color:var(--accent)}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:13px}.card,.panel{background:color-mix(in srgb,var(--panel) 89%,transparent);backdrop-filter:blur(14px);border:1px solid var(--border);border-radius:16px;padding:17px;box-shadow:0 12px 32px #0002;min-width:0}.label{font-size:12px;color:var(--muted)}.num{font-size:clamp(25px,4vw,33px);font-weight:800;margin-top:9px;letter-spacing:-.04em}.small{font-size:12px;color:var(--muted);margin-top:5px}.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}.layout{display:grid;grid-template-columns:1fr;gap:16px}.section{display:flex;justify-content:space-between;align-items:end;gap:12px;flex-wrap:wrap;margin:25px 0 12px}.section h2{font-size:18px;margin:0}.tablewrap{overflow:auto;border:1px solid var(--border);border-radius:13px;background:color-mix(in srgb,var(--panel) 92%,transparent)}table{border-collapse:collapse;width:100%;min-width:760px;font-size:12px}th,td{text-align:left;padding:12px;border-bottom:1px solid var(--border);white-space:nowrap}th{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);background:var(--panel2)}tbody tr:last-child td{border-bottom:0}.pill{display:inline-block;border-radius:999px;padding:4px 8px;font-size:10px;font-weight:800;background:var(--panel2)}.regiongrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.region{background:var(--panel2);border:1px solid var(--border);border-radius:12px;padding:13px}.region strong{font-size:18px}.region div{font-size:11px;color:var(--muted);margin-top:4px}.note{margin-top:16px;padding:12px 14px;border:1px solid var(--border);background:var(--panel2);border-radius:12px;font-size:12px;color:var(--muted);line-height:1.6}.live{display:inline-flex;gap:6px;align-items:center;color:var(--good);font-size:12px}.dot{width:7px;height:7px;border-radius:50%;background:var(--good);box-shadow:0 0 12px var(--good)}footer{display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;margin:18px 0;color:var(--muted);font-size:11px}@keyframes float{0%,100%{transform:translateY(0) rotate(-.4deg)}50%{transform:translateY(-17px) rotate(.6deg)}}@keyframes pulse{0%,100%{opacity:.5;transform:scale(.97)}50%{opacity:1;transform:scale(1.05)}}@keyframes drift{to{transform:translateY(-65px)}}@media(prefers-reduced-motion:reduce){.anime,.glow,.stars{animation:none!important}}@media(max-width:650px){main{padding:13px}.anime{width:90vw;right:-30vw;opacity:.13}.actions{width:100%}.actions select{flex:1}.card,.panel{padding:14px}}

.logo{position:relative;isolation:isolate;overflow:visible;animation:clPulse 4.2s ease-in-out infinite;box-shadow:0 0 22px color-mix(in srgb,var(--accent) 48%,transparent),inset 0 0 14px #ffffff22;background:linear-gradient(135deg,var(--accent),#7c3aed)!important}
.logo::before{content:"";position:absolute;inset:-4px;border-radius:19px;border:2px solid color-mix(in srgb,var(--accent) 75%,white);opacity:.65;animation:clRing 7s linear infinite;pointer-events:none}
.logo::after{content:"✦";position:absolute;right:-7px;top:-8px;font-size:13px;color:#fde68a;text-shadow:0 0 10px #facc15;animation:clSpark 2.8s ease-in-out infinite}
.logo span{position:relative;z-index:2;font-size:17px;font-weight:950;letter-spacing:-1px;color:#fff;text-shadow:0 2px 9px #111827aa}
.hair-fringe{transform-origin:310px 220px;animation:hairSway 6s ease-in-out infinite}.chakra{animation:chakraPulse 4.8s ease-in-out infinite;transform-origin:center}.hair-back{transform-origin:310px 200px;animation:hairSway 8s ease-in-out infinite reverse}
@keyframes clPulse{0%,100%{transform:scale(1);filter:saturate(1)}50%{transform:scale(1.045);filter:saturate(1.3)}}@keyframes clRing{to{transform:rotate(360deg)}}@keyframes clSpark{0%,100%{transform:translateY(0) rotate(0);opacity:.65}50%{transform:translateY(-4px) rotate(18deg);opacity:1}}@keyframes hairSway{0%,100%{transform:rotate(-.5deg)}50%{transform:rotate(.8deg)}}@keyframes chakraPulse{0%,100%{opacity:.45;transform:scale(.97)}50%{opacity:1;transform:scale(1.04)}}

/* Rasengan chakra animation */
.rasengan-scene{position:absolute;right:17%;bottom:10%;width:clamp(105px,17vw,220px);aspect-ratio:1;opacity:.82;filter:drop-shadow(0 0 18px #38bdf8aa);animation:rasenganHover 5.8s ease-in-out infinite;transform-origin:center;}
.rasengan-core{position:absolute;inset:22%;border-radius:50%;background:radial-gradient(circle at 35% 30%,#fff 0 4%,#e0f2fe 9%,#7dd3fc 22%,#38bdf8 43%,#2563eb 63%,#172554 78%,transparent 80%);box-shadow:0 0 18px #7dd3fc,0 0 42px #38bdf8aa,inset 0 0 20px #fff9;animation:rasenganCore 1.15s ease-in-out infinite alternate;}
.rasengan-ring{position:absolute;inset:10%;border:3px solid #bae6fd;border-left-color:transparent;border-right-color:#38bdf8;border-radius:50%;box-shadow:0 0 12px #38bdf8aa;animation:rasenganSpin 1.3s linear infinite;}
.rasengan-ring.r2{inset:2%;border-width:2px;border-top-color:transparent;border-bottom-color:#fff;animation-duration:2.1s;animation-direction:reverse;}
.rasengan-ring.r3{inset:17%;border-width:5px;border-top-color:transparent;border-bottom-color:transparent;border-left-color:#60a5fa;animation-duration:.85s;}
.rasengan-spark{position:absolute;width:8px;height:8px;border-radius:50%;background:#fff;box-shadow:0 0 12px 4px #38bdf8;animation:sparkOrbit 1.8s linear infinite;}
.rasengan-spark.s1{left:4%;top:38%;}.rasengan-spark.s2{right:8%;top:22%;animation-delay:-.6s}.rasengan-spark.s3{left:28%;bottom:1%;animation-delay:-1.1s}
.sound-btn{border:1px solid #60a5fa88!important;background:linear-gradient(120deg,#0e7490,#1d4ed8)!important;color:#fff!important;font-weight:750;box-shadow:0 0 18px #38bdf833;white-space:nowrap}
@keyframes rasenganSpin{to{transform:rotate(360deg)}}@keyframes rasenganCore{from{transform:scale(.94);filter:brightness(.92)}to{transform:scale(1.08);filter:brightness(1.3)}}@keyframes rasenganHover{0%,100%{transform:translateY(0) rotate(-3deg)}50%{transform:translateY(-13px) rotate(4deg)}}@keyframes sparkOrbit{0%{transform:rotate(0) translateX(66px) scale(.7)}50%{transform:rotate(180deg) translateX(80px) scale(1.25)}100%{transform:rotate(360deg) translateX(66px) scale(.7)}}
@media(max-width:650px){.rasengan-scene{right:8%;bottom:7%;width:clamp(90px,27vw,145px);opacity:.62}.sound-btn{font-size:12px;padding:9px}}
@media(prefers-reduced-motion:reduce){.rasengan-scene,.rasengan-core,.rasengan-ring,.rasengan-spark{animation:none!important}}
.blink-lids{transform-box:fill-box;transform-origin:center;transform:scaleY(.04);opacity:0;animation:eyeBlink 6.4s ease-in-out infinite;pointer-events:none}.blink-lids path{transform-box:fill-box;transform-origin:center}@keyframes eyeBlink{0%,42%,45%,78%,81%,100%{transform:scaleY(.04);opacity:0}43.2%,44.2%,79.2%,80.2%{transform:scaleY(1);opacity:1}}
</style></head><body><div class="bg" aria-hidden="true"><div class="stars"></div><div class="glow"></div><svg class="anime" viewBox="0 0 620 850" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Animated Naruto-inspired ninja character">
<defs>
 <linearGradient id="nHair" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#fff2a8"/><stop offset=".42" stop-color="#ffd43b"/><stop offset="1" stop-color="#f59e0b"/></linearGradient>
 <linearGradient id="nOrange" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#fb923c"/><stop offset=".55" stop-color="#f97316"/><stop offset="1" stop-color="#c2410c"/></linearGradient>
 <linearGradient id="nMetal"><stop stop-color="#64748b"/><stop offset=".5" stop-color="#e2e8f0"/><stop offset="1" stop-color="#475569"/></linearGradient>
 <linearGradient id="nSkin" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#ffe0bd"/><stop offset="1" stop-color="#e9a779"/></linearGradient>
 <filter id="nGlow"><feGaussianBlur stdDeviation="8" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
<!-- chakra aura --> <ellipse cx="320" cy="570" rx="205" ry="255" fill="#38bdf8" opacity=".09" filter="url(#nGlow)"/>
<!-- back spikes --> <g class="hair-back" fill="url(#nHair)" stroke="#f59e0b" stroke-width="4" stroke-linejoin="round"><path d="M190 250L125 151L216 185L207 89L274 160L318 64L347 160L416 94L409 187L495 150L440 254Z"/><path d="M206 212L167 126L240 177L260 104L302 173L351 94L365 180L424 131L407 218Z"/></g>
<!-- torso and jacket --> <path d="M166 840Q161 675 208 573Q242 526 310 520Q386 523 423 573Q469 681 461 840Z" fill="url(#nOrange)" stroke="#fdba74" stroke-width="5"/><path d="M255 535L310 628L365 535L399 840H221Z" fill="#172033" stroke="#334155" stroke-width="5"/><path d="M255 535L310 628L365 535L339 662L310 690L280 662Z" fill="#f8fafc" opacity=".95"/><path d="M205 601L264 640L241 840H174Z" fill="#ea580c"/><path d="M414 600L356 641L380 840H451Z" fill="#ea580c"/>
<!-- neck --> <path d="M274 467L272 540Q310 580 349 540L347 466Z" fill="url(#nSkin)"/>
<!-- face --> <path d="M210 276Q206 174 310 164Q414 174 410 276L396 386Q375 465 310 484Q245 465 224 386Z" fill="url(#nSkin)" stroke="#b77955" stroke-width="3"/>
<!-- ears --> <path d="M218 310Q183 286 190 340Q197 371 226 365Z M402 310Q437 286 430 340Q423 371 394 365Z" fill="url(#nSkin)" stroke="#b77955" stroke-width="3"/>
<!-- forehead protector strap --> <path d="M207 245Q310 214 413 245L408 292Q310 269 212 292Z" fill="#1e293b" stroke="#0f172a" stroke-width="5"/><path d="M247 237Q310 224 373 237L369 274Q310 263 251 274Z" fill="url(#nMetal)" stroke="#cbd5e1" stroke-width="3"/><path d="M309 244C296 238 285 248 290 257C295 266 307 263 309 255C314 267 329 264 332 253C334 245 322 239 315 246L309 251L304 246" fill="none" stroke="#334155" stroke-width="4" stroke-linecap="round"/><path d="M303 249L313 260L323 249" fill="none" stroke="#334155" stroke-width="3"/>
<!-- eyes and brows --> <path d="M237 322Q263 296 292 322Q266 346 237 322Z M328 322Q357 296 383 322Q355 346 328 322Z" fill="#f8fafc" stroke="#7c4a35" stroke-width="3"/><ellipse cx="267" cy="322" rx="9" ry="13" fill="#38bdf8"/><ellipse cx="355" cy="322" rx="9" ry="13" fill="#38bdf8"/><ellipse cx="267" cy="323" rx="4" ry="8" fill="#111827"/><ellipse cx="355" cy="323" rx="4" ry="8" fill="#111827"/><circle cx="270" cy="318" r="3" fill="white"/><circle cx="358" cy="318" r="3" fill="white"/><path d="M234 305L292 313M329 313L386 305" stroke="#7c4a35" stroke-width="7" stroke-linecap="round"/>
<!-- Naruto cheek marks --> <g stroke="#9a5a42" stroke-width="5" stroke-linecap="round" opacity=".9"><path d="M225 354L257 362M224 369L254 377M365 362L397 354M367 377L396 369"/></g>
<!-- nose and grin --> <path d="M309 333L302 359L314 362" fill="none" stroke="#c08463" stroke-width="4" stroke-linecap="round"/><path d="M276 398Q310 417 344 398Q333 435 310 430Q287 435 276 398Z" fill="#7f1d1d"/><path d="M283 402Q310 414 337 402L332 411H288Z" fill="#fff7ed"/>
<!-- front hair fringe --> <g class="hair-fringe" fill="url(#nHair)" stroke="#f59e0b" stroke-width="4" stroke-linejoin="round"><path d="M207 260Q190 194 238 142L251 217L282 131L300 219L333 126L351 220L389 151L393 260Q356 238 328 253L306 235L283 254Q245 237 207 260Z"/></g>
<!-- collar --> <path d="M239 533L274 508L310 560L346 508L382 533L358 589L310 628L262 589Z" fill="#1e293b" stroke="#64748b" stroke-width="4"/>
<!-- small chakra sparks --> <g class="chakra" fill="#7dd3fc" filter="url(#nGlow)"><path d="M118 418l10 24 24 8-24 8-10 24-8-24-24-8 24-8Z"/><path d="M477 470l7 17 17 6-17 6-7 17-6-17-17-6 17-6Z"/><circle cx="160" cy="520" r="5"/><circle cx="452" cy="390" r="4"/></g>
<g class="blink-lids" aria-hidden="true"><path d="M234 322Q263 296 295 322Q266 350 234 322Z" fill="url(#nSkin)" stroke="#b77955" stroke-width="3"/><path d="M326 322Q357 296 386 322Q355 350 326 322Z" fill="url(#nSkin)" stroke="#b77955" stroke-width="3"/></g>
</svg><div class="rasengan-scene" aria-hidden="true"><div class="rasengan-ring r2"></div><div class="rasengan-ring"></div><div class="rasengan-ring r3"></div><div class="rasengan-core"></div><i class="rasengan-spark s1"></i><i class="rasengan-spark s2"></i><i class="rasengan-spark s3"></i></div></div><main><header><div class="brand"><div class="logo" aria-label="CL animated logo"><span>CL</span></div><div><h1>CHINNU FF Monitor</h1><div class="sub muted">Advanced likes & request control center · <span class="live"><i class="dot"></i> LIVE</span></div></div></div><div class="actions"><label class="muted" for="regionFilter">Region</label><select id="regionFilter"><option value="ALL">All regions</option><option>IND</option><option>BD</option><option>BR</option><option>US</option><option>SAC</option><option>NA</option></select><label class="muted" for="theme">Theme</label><select id="theme"><option value="dark">Dark</option><option value="light">Light</option><option value="neon">Neon</option><option value="ocean">Ocean</option></select><button type="button" class="sound-btn" id="rasenganSound">⚡ Play Rasengan FX</button><button type="button" class="sound-btn" id="ambientMusic">🎵 Play Anime Music</button><a class="btn" href="/dashboard/logout">Logout</a></div></header>
<div class="cards"><div class="card"><div class="label">Upstream API ping</div><div class="num" id="upstreamStatus">Checking…</div><div class="small" id="upstreamDetail">like-api-3-vng3.onrender.com</div></div><div class="card"><div class="label">Requests today</div><div class="num" id="reqToday">—</div><div class="small">API calls recorded today (India time)</div></div><div class="card"><div class="label">Successful jobs today</div><div class="num good" id="successToday">—</div><div class="small">Reported successful results</div></div><div class="card"><div class="label">Failed jobs today</div><div class="num bad" id="failedToday">—</div><div class="small">Reported failed results</div></div><div class="card"><div class="label">Likes gained today</div><div class="num" id="likesToday">—</div><div class="small">Confirmed likes from job results</div></div><div class="card"><div class="label">Limit-hit accounts</div><div class="num warn" id="limitsToday">—</div><div class="small">Unique UIDs reported limit reached today</div></div><div class="card"><div class="label">Tracked IDs</div><div class="num" id="idCount">—</div><div class="small">UIDs from ids.json and job history</div></div><div class="card"><div class="label">Avg API response</div><div class="num" id="avgMs">—</div><div class="small">Milliseconds</div></div><div class="card"><div class="label">Configured token files</div><div class="num" id="tokenCount">—</div><div class="small">File presence only; values never shown</div></div></div>
<div class="section"><h2>Region summary</h2><span class="muted" id="updatedAt">Waiting for data…</span></div><div class="regiongrid" id="regions"></div>
<div class="section"><h2>Tracked UID list</h2><span class="muted">IDs loaded from ids.json and observed jobs</span></div><div class="tablewrap"><table><thead><tr><th>UID</th><th>Nickname</th><th>Region</th><th>Last status</th><th>Likes now</th><th>Likes gained total</th><th>Success</th><th>Fail</th><th>Limit hits</th><th>Last seen</th></tr></thead><tbody id="idsRows"><tr><td colspan="10">Loading…</td></tr></tbody></table></div>
<div class="section"><h2>Recent like jobs</h2><span class="muted">Latest reported job outcomes</span></div><div class="tablewrap"><table><thead><tr><th>Time</th><th>Job ID</th><th>UID</th><th>Nickname</th><th>Region</th><th>Status</th><th>Before</th><th>After</th><th>Gained</th><th>Message</th></tr></thead><tbody id="jobsRows"><tr><td colspan="10">Loading…</td></tr></tbody></table></div>
<div class="section"><h2>Token file status</h2><span class="muted">Only configured / missing state is shown</span></div><div class="tablewrap"><table><thead><tr><th>Region</th><th>File</th><th>Status</th><th>Token entries</th></tr></thead><tbody id="tokensRows"><tr><td colspan="4">Loading…</td></tr></tbody></table></div>
<div class="section"><h2>Recent API requests</h2><span class="muted">Last 100 requests · no query strings or secrets</span></div><div class="tablewrap"><table><thead><tr><th>Time</th><th>Method</th><th>Endpoint</th><th>HTTP</th><th>Response ms</th></tr></thead><tbody id="requestsRows"><tr><td colspan="5">Loading…</td></tr></tbody></table></div>
<div class="note"><b>Important:</b> This dashboard records actual job outcomes only when your authorized like-service integration sends them to <code>POST /monitor/event</code> with your API key. The current player endpoint is read-only and does not send likes. Counts are not invented; until job events are received, likes/job metrics remain zero. Never upload real JWT tokens to a public GitHub repository.</div><footer><span>© CHINNU TEAM · Private monitoring</span><span>Auto refresh every 30 seconds while visible</span></footer></main><script>
const $=id=>document.getElementById(id);const theme=$('theme');theme.value=localStorage.getItem('chinnuTheme')||'dark';document.documentElement.dataset.theme=theme.value;theme.addEventListener('change',()=>{document.documentElement.dataset.theme=theme.value;localStorage.setItem('chinnuTheme',theme.value)});const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const n=v=>Number(v||0).toLocaleString();const statusPill=s=>{let c=s==='success'?'good':s==='fail'?'bad':s==='limit_reached'?'warn':'';return `<span class="pill ${c}">${esc(s||'waiting')}</span>`};function rows(id,arr,cols){$(id).innerHTML=arr.length?arr.map(r=>'<tr>'+cols.map(c=>'<td>'+c(r)+'</td>').join('')+'</tr>').join(''):`<tr><td colspan="${cols.length}">No records yet</td></tr>`}
let rasenganAudio=null;function playRasengan(){try{const AC=window.AudioContext||window.webkitAudioContext;if(!AC)return;rasenganAudio=rasenganAudio||new AC();if(rasenganAudio.state==='suspended')rasenganAudio.resume();const ctx=rasenganAudio,t=ctx.currentTime;const master=ctx.createGain();master.gain.setValueAtTime(.0001,t);master.gain.exponentialRampToValueAtTime(.16,t+.06);master.gain.exponentialRampToValueAtTime(.0001,t+1.25);master.connect(ctx.destination);const osc=ctx.createOscillator(),og=ctx.createGain();osc.type='sawtooth';osc.frequency.setValueAtTime(130,t);osc.frequency.exponentialRampToValueAtTime(620,t+.32);osc.frequency.exponentialRampToValueAtTime(95,t+1.15);og.gain.setValueAtTime(.0001,t);og.gain.exponentialRampToValueAtTime(.28,t+.1);og.gain.exponentialRampToValueAtTime(.0001,t+1.2);osc.connect(og);og.connect(master);osc.start(t);osc.stop(t+1.26);const length=Math.floor(ctx.sampleRate*.9),buf=ctx.createBuffer(1,length,ctx.sampleRate),data=buf.getChannelData(0);for(let i=0;i<length;i++)data[i]=(Math.random()*2-1)*(1-i/length);const noise=ctx.createBufferSource(),filter=ctx.createBiquadFilter(),ng=ctx.createGain();noise.buffer=buf;filter.type='bandpass';filter.frequency.setValueAtTime(450,t);filter.frequency.exponentialRampToValueAtTime(2400,t+.28);filter.frequency.exponentialRampToValueAtTime(250,t+.85);filter.Q.value=.8;ng.gain.setValueAtTime(.0001,t);ng.gain.exponentialRampToValueAtTime(.24,t+.08);ng.gain.exponentialRampToValueAtTime(.0001,t+.88);noise.connect(filter);filter.connect(ng);ng.connect(master);noise.start(t);noise.stop(t+.9);const ping=ctx.createOscillator(),pg=ctx.createGain();ping.type='sine';ping.frequency.setValueAtTime(900,t+.2);ping.frequency.exponentialRampToValueAtTime(180,t+.72);pg.gain.setValueAtTime(.0001,t);pg.gain.exponentialRampToValueAtTime(.13,t+.24);pg.gain.exponentialRampToValueAtTime(.0001,t+.8);ping.connect(pg);pg.connect(master);ping.start(t+.18);ping.stop(t+.82);const b=$('rasenganSound');if(b){b.textContent='🌀 Rasengan!';setTimeout(()=>{if(b.isConnected)b.textContent='⚡ Play Rasengan FX'},1400)}}catch(e){console.warn('Sound effect unavailable',e)}}const rasenganBtn=$('rasenganSound');if(rasenganBtn)rasenganBtn.addEventListener('click',playRasengan);
let musicCtx=null,musicMaster=null,musicTimer=null,musicStep=0,musicPlaying=false;const musicNotes=[392,440,523.25,587.33,523.25,440,349.23,392,440,523.25,659.25,587.33,523.25,440,392,329.63];function toggleAnimeMusic(buttonId){const b=$(buttonId);try{const AC=window.AudioContext||window.webkitAudioContext;if(!AC){if(b)b.textContent='Music unavailable';return}if(musicPlaying){musicPlaying=false;if(musicTimer)clearInterval(musicTimer);musicTimer=null;if(musicMaster&&musicCtx){const t=musicCtx.currentTime;musicMaster.gain.cancelScheduledValues(t);musicMaster.gain.setTargetAtTime(.0001,t,.08);setTimeout(()=>{try{musicCtx.close()}catch(e){}musicCtx=null;musicMaster=null},450)}if(b)b.textContent='🎵 Play Anime Music';return}musicCtx=new AC();musicCtx.resume();musicMaster=musicCtx.createGain();musicMaster.gain.value=.0001;musicMaster.connect(musicCtx.destination);musicMaster.gain.setTargetAtTime(.22,musicCtx.currentTime,.45);[130.81,196,261.63].forEach((hz,i)=>{const o=musicCtx.createOscillator(),g=musicCtx.createGain();o.type=i===0?'triangle':'sine';o.frequency.value=hz;g.gain.value=i===0?.16:.09;o.connect(g);g.connect(musicMaster);o.start()});musicPlaying=true;const playNote=()=>{if(!musicPlaying||!musicCtx||!musicMaster)return;const t=musicCtx.currentTime,hz=musicNotes[musicStep%musicNotes.length];musicStep++;const o=musicCtx.createOscillator(),g=musicCtx.createGain();o.type='sine';o.frequency.setValueAtTime(hz,t);g.gain.setValueAtTime(.0001,t);g.gain.linearRampToValueAtTime(.17,t+.06);g.gain.exponentialRampToValueAtTime(.0001,t+.62);o.connect(g);g.connect(musicMaster);o.start(t);o.stop(t+.65)};playNote();musicTimer=setInterval(playNote,520);if(b)b.textContent='⏸ Pause Anime Music'}catch(e){console.warn('Music unavailable',e)}}const musicBtn=$('ambientMusic');if(musicBtn)musicBtn.addEventListener('click',()=>toggleAnimeMusic('ambientMusic'));
async function refresh(){if(document.hidden)return;try{const r=await fetch('/dashboard/data',{cache:'no-store'});if(r.status===401){location.href='/dashboard/login';return}const d=await r.json();if(!d.ok)throw Error('Unable to load monitor data');const m=d.metrics;for(const [id,key] of [['reqToday','requests_today'],['successToday','success_today'],['failedToday','failed_today'],['likesToday','likes_gained_today'],['limitsToday','limit_accounts_today'],['idCount','tracked_ids'],['tokenCount','configured_token_files']])$(id).textContent=n(m[key]);$('avgMs').textContent=n(m.avg_ms)+' ms';const ping=d.upstream_ping||{};$('upstreamStatus').textContent=ping.online?'ONLINE':'OFFLINE';$('upstreamStatus').className='num '+(ping.online?'good':'bad');$('upstreamDetail').textContent=(ping.http_status?'HTTP '+ping.http_status+' · ':'')+(ping.latency_ms!=null?ping.latency_ms+' ms · ':'')+(ping.message||ping.url||'Ping unavailable');$('updatedAt').textContent='Updated '+new Date().toLocaleTimeString();const rg=d.regions||[];$('regions').innerHTML=rg.length?rg.map(x=>`<div class="region"><strong>${esc(x.region)}</strong><div>${n(x.jobs_today)} jobs today</div><div>${n(x.success_today)} success · ${n(x.failed_today)} fail</div><div>${n(x.likes_gained_today)} likes gained</div><div>${n(x.limit_accounts_today)} limit-hit UIDs</div></div>`).join(''):'<div class="region">No region activity yet</div>';const f=$('regionFilter').value;const filter=a=>f==='ALL'?a:a.filter(x=>x.region===f);rows('idsRows',filter(d.ids||[]),[x=>esc(x.uid),x=>esc(x.nickname||'—'),x=>esc(x.region),x=>statusPill(x.last_status),x=>n(x.last_likes),x=>n(x.total_likes_gained),x=>n(x.success_count),x=>n(x.fail_count),x=>n(x.limit_hits),x=>esc(x.last_seen||'—')]);rows('jobsRows',filter(d.jobs||[]),[x=>esc(x.timestamp),x=>esc(x.job_id||'—'),x=>esc(x.uid),x=>esc(x.nickname||'—'),x=>esc(x.region),x=>statusPill(x.status),x=>n(x.likes_before),x=>n(x.likes_after),x=>n(x.likes_given),x=>esc(x.message||'—')]);rows('tokensRows',d.tokens||[],[x=>esc(x.region),x=>esc(x.file),x=>`<span class="${x.configured?'good':'bad'}">${x.configured?'Configured':'Missing / empty'}</span>`,x=>n(x.entries)]);rows('requestsRows',d.requests||[],[x=>esc(x.timestamp),x=>esc(x.method),x=>esc(x.path),x=>`<span class="${x.status>=200&&x.status<300?'good':x.status>=400?'bad':'warn'}">${esc(x.status)}</span>`,x=>n(x.duration_ms)]);}catch(e){$('updatedAt').textContent='Monitor connection error';console.error(e)}}$('regionFilter').addEventListener('change',refresh);refresh();setInterval(refresh,30000);
</script></body></html>"""

LOGIN_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CHINNU Monitor Login</title><style>
:root{color-scheme:dark;--accent:#3b82f6}*{box-sizing:border-box}body{font-family:Inter,system-ui,-apple-system,Arial,sans-serif;background:radial-gradient(ellipse at 78% 20%,#2563eb36,transparent 40%),radial-gradient(ellipse at 10% 85%,#7c3aed28,transparent 38%),#070b16;color:#e5e7eb;display:grid;place-items:center;min-height:100vh;margin:0;overflow:hidden;padding:20px}.anime-bg{position:fixed;inset:0;pointer-events:none;overflow:hidden}.anime-glow{position:absolute;right:4%;top:8%;width:45vw;height:45vw;max-width:600px;max-height:600px;border-radius:50%;background:radial-gradient(circle,#2563eb44,transparent 68%);filter:blur(20px);animation:glowPulse 12s ease-in-out infinite}.anime-figure{position:absolute;right:-2vw;bottom:-14vh;width:min(55vw,700px);height:auto;opacity:.32;filter:drop-shadow(0 0 28px #3b82f64a);transform-origin:50% 80%;animation:animeFloat 14s ease-in-out infinite}.stars{position:absolute;inset:0;background-image:radial-gradient(circle at 18% 24%,#fff9 0 1px,transparent 2px),radial-gradient(circle at 70% 28%,#60a5fa9c 0 1.5px,transparent 3px),radial-gradient(circle at 42% 72%,#fff7 0 1px,transparent 2px);background-size:270px 270px,330px 330px,210px 210px;animation:starsDrift 32s linear infinite;opacity:.4}.box{position:relative;z-index:1;width:min(390px,94vw);background:#101827d9;backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border:1px solid #64748b55;padding:clamp(24px,6vw,34px);border-radius:22px;box-shadow:0 24px 80px #0008}.logo{width:52px;height:52px;border-radius:16px;background:linear-gradient(135deg,#2563eb,#9333ea);display:grid;place-items:center;font-size:27px;margin-bottom:18px;box-shadow:0 0 30px #3b82f644}h1{margin:0;font-size:25px}p{color:#9ca3af;line-height:1.55}.tag{display:inline-block;border:1px solid #3b82f655;color:#93c5fd;background:#1d4ed822;padding:5px 9px;border-radius:999px;font-size:11px;letter-spacing:.08em;margin:13px 0}input,button{font:inherit;box-sizing:border-box;width:100%;padding:13px 14px;margin:8px 0;border-radius:11px;border:1px solid #334155}input{background:#070d19;color:#f8fafc;outline:none}input:focus{border-color:#60a5fa;box-shadow:0 0 0 3px #3b82f622}button{background:linear-gradient(100deg,#2563eb,#7c3aed);color:white;border:0;font-weight:700;cursor:pointer;box-shadow:0 8px 24px #2563eb30}button:hover{filter:brightness(1.1)}.error{color:#fca5a5!important}@keyframes animeFloat{0%,100%{transform:translate3d(0,0,0) rotate(-.5deg)}50%{transform:translate3d(-10px,-18px,0) rotate(.7deg)}}@keyframes glowPulse{0%,100%{opacity:.55;transform:scale(.96)}50%{opacity:1;transform:scale(1.06)}}@keyframes starsDrift{from{transform:translateY(0)}to{transform:translateY(-70px)}}@media(max-width:700px){.anime-figure{width:90vw;right:-32vw;bottom:-3vh;opacity:.18}.anime-glow{width:85vw;height:85vw;right:-15vw;top:18%}}@media(prefers-reduced-motion:reduce){.anime-figure,.anime-glow,.stars{animation:none!important}}

.logo{position:relative;isolation:isolate;overflow:visible;animation:clPulse 4.2s ease-in-out infinite;background:linear-gradient(135deg,#2563eb,#9333ea)!important;box-shadow:0 0 30px #3b82f666,inset 0 0 14px #ffffff22}
.logo::before{content:"";position:absolute;inset:-4px;border-radius:19px;border:2px solid #93c5fd;opacity:.7;animation:clRing 7s linear infinite;pointer-events:none}
.logo::after{content:"✦";position:absolute;right:-7px;top:-8px;font-size:13px;color:#fde68a;text-shadow:0 0 10px #facc15;animation:clSpark 2.8s ease-in-out infinite}
.logo span{position:relative;z-index:2;font-size:18px;font-weight:950;letter-spacing:-1px;color:white;text-shadow:0 2px 9px #111827aa}
.hair-fringe{transform-origin:310px 220px;animation:hairSway 6s ease-in-out infinite}.chakra{animation:chakraPulse 4.8s ease-in-out infinite;transform-origin:center}.hair-back{transform-origin:310px 200px;animation:hairSway 8s ease-in-out infinite reverse}
@keyframes clPulse{0%,100%{transform:scale(1);filter:saturate(1)}50%{transform:scale(1.045);filter:saturate(1.3)}}@keyframes clRing{to{transform:rotate(360deg)}}@keyframes clSpark{0%,100%{transform:translateY(0) rotate(0);opacity:.65}50%{transform:translateY(-4px) rotate(18deg);opacity:1}}@keyframes hairSway{0%,100%{transform:rotate(-.5deg)}50%{transform:rotate(.8deg)}}@keyframes chakraPulse{0%,100%{opacity:.45;transform:scale(.97)}50%{opacity:1;transform:scale(1.04)}}

/* Rasengan animation and user-triggered synthesized sound */
.rasengan-scene{position:absolute;right:12%;bottom:13%;width:clamp(105px,19vw,230px);aspect-ratio:1;opacity:.85;filter:drop-shadow(0 0 22px #38bdf8aa);animation:rasenganHover 5.8s ease-in-out infinite;pointer-events:none}
.rasengan-core{position:absolute;inset:22%;border-radius:50%;background:radial-gradient(circle at 35% 30%,#fff 0 4%,#e0f2fe 9%,#7dd3fc 22%,#38bdf8 43%,#2563eb 63%,#172554 78%,transparent 80%);box-shadow:0 0 18px #7dd3fc,0 0 42px #38bdf8aa,inset 0 0 20px #fff9;animation:rasenganCore 1.15s ease-in-out infinite alternate}
.rasengan-ring{position:absolute;inset:10%;border:3px solid #bae6fd;border-left-color:transparent;border-right-color:#38bdf8;border-radius:50%;box-shadow:0 0 12px #38bdf8aa;animation:rasenganSpin 1.3s linear infinite}.rasengan-ring.r2{inset:2%;border-width:2px;border-top-color:transparent;border-bottom-color:#fff;animation-duration:2.1s;animation-direction:reverse}.rasengan-ring.r3{inset:17%;border-width:5px;border-top-color:transparent;border-bottom-color:transparent;border-left-color:#60a5fa;animation-duration:.85s}.rasengan-spark{position:absolute;width:8px;height:8px;border-radius:50%;background:#fff;box-shadow:0 0 12px 4px #38bdf8;animation:sparkOrbit 1.8s linear infinite}.rasengan-spark.s1{left:4%;top:38%}.rasengan-spark.s2{right:8%;top:22%;animation-delay:-.6s}.rasengan-spark.s3{left:28%;bottom:1%;animation-delay:-1.1s}.sound-btn{font:inherit;width:100%;padding:12px 14px;margin:8px 0;border-radius:11px;border:1px solid #60a5fa88;background:linear-gradient(120deg,#0e7490,#1d4ed8);color:#fff;font-weight:750;cursor:pointer;box-shadow:0 0 18px #38bdf833}
@keyframes rasenganSpin{to{transform:rotate(360deg)}}@keyframes rasenganCore{from{transform:scale(.94);filter:brightness(.92)}to{transform:scale(1.08);filter:brightness(1.3)}}@keyframes rasenganHover{0%,100%{transform:translateY(0) rotate(-3deg)}50%{transform:translateY(-13px) rotate(4deg)}}@keyframes sparkOrbit{0%{transform:rotate(0) translateX(66px) scale(.7)}50%{transform:rotate(180deg) translateX(80px) scale(1.25)}100%{transform:rotate(360deg) translateX(66px) scale(.7)}}
@media(max-width:700px){.rasengan-scene{right:3%;bottom:4%;width:clamp(90px,28vw,150px);opacity:.62}.box{z-index:2}}
@media(prefers-reduced-motion:reduce){.rasengan-scene,.rasengan-core,.rasengan-ring,.rasengan-spark{animation:none!important}}
.blink-lids{transform-box:fill-box;transform-origin:center;transform:scaleY(.04);opacity:0;animation:eyeBlink 6.4s ease-in-out infinite;pointer-events:none}.blink-lids path{transform-box:fill-box;transform-origin:center}@keyframes eyeBlink{0%,42%,45%,78%,81%,100%{transform:scaleY(.04);opacity:0}43.2%,44.2%,79.2%,80.2%{transform:scaleY(1);opacity:1}}
</style></head><body><div class="anime-bg" aria-hidden="true"><div class="stars"></div><div class="anime-glow"></div><svg class="anime-figure" viewBox="0 0 620 850" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Animated Naruto-inspired ninja character">
<defs>
 <linearGradient id="nHair" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#fff2a8"/><stop offset=".42" stop-color="#ffd43b"/><stop offset="1" stop-color="#f59e0b"/></linearGradient>
 <linearGradient id="nOrange" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#fb923c"/><stop offset=".55" stop-color="#f97316"/><stop offset="1" stop-color="#c2410c"/></linearGradient>
 <linearGradient id="nMetal"><stop stop-color="#64748b"/><stop offset=".5" stop-color="#e2e8f0"/><stop offset="1" stop-color="#475569"/></linearGradient>
 <linearGradient id="nSkin" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#ffe0bd"/><stop offset="1" stop-color="#e9a779"/></linearGradient>
 <filter id="nGlow"><feGaussianBlur stdDeviation="8" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
<!-- chakra aura --> <ellipse cx="320" cy="570" rx="205" ry="255" fill="#38bdf8" opacity=".09" filter="url(#nGlow)"/>
<!-- back spikes --> <g class="hair-back" fill="url(#nHair)" stroke="#f59e0b" stroke-width="4" stroke-linejoin="round"><path d="M190 250L125 151L216 185L207 89L274 160L318 64L347 160L416 94L409 187L495 150L440 254Z"/><path d="M206 212L167 126L240 177L260 104L302 173L351 94L365 180L424 131L407 218Z"/></g>
<!-- torso and jacket --> <path d="M166 840Q161 675 208 573Q242 526 310 520Q386 523 423 573Q469 681 461 840Z" fill="url(#nOrange)" stroke="#fdba74" stroke-width="5"/><path d="M255 535L310 628L365 535L399 840H221Z" fill="#172033" stroke="#334155" stroke-width="5"/><path d="M255 535L310 628L365 535L339 662L310 690L280 662Z" fill="#f8fafc" opacity=".95"/><path d="M205 601L264 640L241 840H174Z" fill="#ea580c"/><path d="M414 600L356 641L380 840H451Z" fill="#ea580c"/>
<!-- neck --> <path d="M274 467L272 540Q310 580 349 540L347 466Z" fill="url(#nSkin)"/>
<!-- face --> <path d="M210 276Q206 174 310 164Q414 174 410 276L396 386Q375 465 310 484Q245 465 224 386Z" fill="url(#nSkin)" stroke="#b77955" stroke-width="3"/>
<!-- ears --> <path d="M218 310Q183 286 190 340Q197 371 226 365Z M402 310Q437 286 430 340Q423 371 394 365Z" fill="url(#nSkin)" stroke="#b77955" stroke-width="3"/>
<!-- forehead protector strap --> <path d="M207 245Q310 214 413 245L408 292Q310 269 212 292Z" fill="#1e293b" stroke="#0f172a" stroke-width="5"/><path d="M247 237Q310 224 373 237L369 274Q310 263 251 274Z" fill="url(#nMetal)" stroke="#cbd5e1" stroke-width="3"/><path d="M309 244C296 238 285 248 290 257C295 266 307 263 309 255C314 267 329 264 332 253C334 245 322 239 315 246L309 251L304 246" fill="none" stroke="#334155" stroke-width="4" stroke-linecap="round"/><path d="M303 249L313 260L323 249" fill="none" stroke="#334155" stroke-width="3"/>
<!-- eyes and brows --> <path d="M237 322Q263 296 292 322Q266 346 237 322Z M328 322Q357 296 383 322Q355 346 328 322Z" fill="#f8fafc" stroke="#7c4a35" stroke-width="3"/><ellipse cx="267" cy="322" rx="9" ry="13" fill="#38bdf8"/><ellipse cx="355" cy="322" rx="9" ry="13" fill="#38bdf8"/><ellipse cx="267" cy="323" rx="4" ry="8" fill="#111827"/><ellipse cx="355" cy="323" rx="4" ry="8" fill="#111827"/><circle cx="270" cy="318" r="3" fill="white"/><circle cx="358" cy="318" r="3" fill="white"/><path d="M234 305L292 313M329 313L386 305" stroke="#7c4a35" stroke-width="7" stroke-linecap="round"/>
<!-- Naruto cheek marks --> <g stroke="#9a5a42" stroke-width="5" stroke-linecap="round" opacity=".9"><path d="M225 354L257 362M224 369L254 377M365 362L397 354M367 377L396 369"/></g>
<!-- nose and grin --> <path d="M309 333L302 359L314 362" fill="none" stroke="#c08463" stroke-width="4" stroke-linecap="round"/><path d="M276 398Q310 417 344 398Q333 435 310 430Q287 435 276 398Z" fill="#7f1d1d"/><path d="M283 402Q310 414 337 402L332 411H288Z" fill="#fff7ed"/>
<!-- front hair fringe --> <g class="hair-fringe" fill="url(#nHair)" stroke="#f59e0b" stroke-width="4" stroke-linejoin="round"><path d="M207 260Q190 194 238 142L251 217L282 131L300 219L333 126L351 220L389 151L393 260Q356 238 328 253L306 235L283 254Q245 237 207 260Z"/></g>
<!-- collar --> <path d="M239 533L274 508L310 560L346 508L382 533L358 589L310 628L262 589Z" fill="#1e293b" stroke="#64748b" stroke-width="4"/>
<!-- small chakra sparks --> <g class="chakra" fill="#7dd3fc" filter="url(#nGlow)"><path d="M118 418l10 24 24 8-24 8-10 24-8-24-24-8 24-8Z"/><path d="M477 470l7 17 17 6-17 6-7 17-6-17-17-6 17-6Z"/><circle cx="160" cy="520" r="5"/><circle cx="452" cy="390" r="4"/></g>
<g class="blink-lids" aria-hidden="true"><path d="M234 322Q263 296 295 322Q266 350 234 322Z" fill="url(#nSkin)" stroke="#b77955" stroke-width="3"/><path d="M326 322Q357 296 386 322Q355 350 326 322Z" fill="url(#nSkin)" stroke="#b77955" stroke-width="3"/></g>
</svg><div class="rasengan-scene" aria-hidden="true"><div class="rasengan-ring r2"></div><div class="rasengan-ring"></div><div class="rasengan-ring r3"></div><div class="rasengan-core"></div><i class="rasengan-spark s1"></i><i class="rasengan-spark s2"></i><i class="rasengan-spark s3"></i></div></div><form class="box" method="post"><div class="logo" aria-label="CL animated logo"><span>CL</span></div><h1>CHINNU Monitor</h1><span class="tag">PRIVATE CONTROL CENTER</span><p>Sign in to view API activity and monitoring.</p>{% if error %}<p class="error">{{ error }}</p>{% endif %}<input type="password" name="password" required autocomplete="current-password" placeholder="Dashboard password"><button type="submit">Unlock Dashboard →</button><button type="button" class="sound-btn" id="loginRasenganSound">⚡ Play Rasengan Sound</button><button type="button" class="sound-btn" id="loginAmbientMusic">🎵 Play Anime Music</button></form><script>let loginMusicCtx=null,loginMusicMaster=null,loginMusicTimer=null,loginMusicStep=0,loginMusicPlaying=false;function toggleLoginMusic(){const b=document.getElementById('loginAmbientMusic');try{const AC=window.AudioContext||window.webkitAudioContext;if(!AC)return;if(loginMusicPlaying){loginMusicPlaying=false;if(loginMusicTimer)clearInterval(loginMusicTimer);loginMusicTimer=null;if(loginMusicMaster&&loginMusicCtx){loginMusicMaster.gain.setTargetAtTime(.0001,loginMusicCtx.currentTime,.08);setTimeout(()=>{try{loginMusicCtx.close()}catch(e){}loginMusicCtx=null;loginMusicMaster=null},450)}b.textContent='🎵 Play Anime Music';return}loginMusicCtx=new AC();loginMusicCtx.resume();loginMusicMaster=loginMusicCtx.createGain();loginMusicMaster.gain.value=.0001;loginMusicMaster.connect(loginMusicCtx.destination);loginMusicMaster.gain.setTargetAtTime(.2,loginMusicCtx.currentTime,.45);[130.81,196,261.63].forEach((hz,i)=>{const o=loginMusicCtx.createOscillator(),g=loginMusicCtx.createGain();o.type=i?'sine':'triangle';o.frequency.value=hz;g.gain.value=i?.09:.16;o.connect(g);g.connect(loginMusicMaster);o.start()});loginMusicPlaying=true;const notes=[392,440,523.25,587.33,523.25,440,349.23,392,440,523.25,659.25,587.33,523.25,440,392,329.63];const play=()=>{if(!loginMusicPlaying)return;const t=loginMusicCtx.currentTime,o=loginMusicCtx.createOscillator(),g=loginMusicCtx.createGain();o.type='sine';o.frequency.value=notes[loginMusicStep++%notes.length];g.gain.setValueAtTime(.0001,t);g.gain.linearRampToValueAtTime(.17,t+.06);g.gain.exponentialRampToValueAtTime(.0001,t+.62);o.connect(g);g.connect(loginMusicMaster);o.start(t);o.stop(t+.65)};play();loginMusicTimer=setInterval(play,520);b.textContent='⏸ Pause Anime Music'}catch(e){console.warn(e)}}document.getElementById('loginAmbientMusic').addEventListener('click',toggleLoginMusic);let loginAudio=null;function playLoginRasengan(){try{const AC=window.AudioContext||window.webkitAudioContext;if(!AC)return;loginAudio=loginAudio||new AC();if(loginAudio.state==='suspended')loginAudio.resume();const c=loginAudio,t=c.currentTime,m=c.createGain();m.gain.setValueAtTime(.0001,t);m.gain.exponentialRampToValueAtTime(.16,t+.06);m.gain.exponentialRampToValueAtTime(.0001,t+1.25);m.connect(c.destination);const o=c.createOscillator(),g=c.createGain();o.type='sawtooth';o.frequency.setValueAtTime(130,t);o.frequency.exponentialRampToValueAtTime(620,t+.32);o.frequency.exponentialRampToValueAtTime(95,t+1.15);g.gain.setValueAtTime(.0001,t);g.gain.exponentialRampToValueAtTime(.28,t+.1);g.gain.exponentialRampToValueAtTime(.0001,t+1.2);o.connect(g);g.connect(m);o.start(t);o.stop(t+1.26);const len=Math.floor(c.sampleRate*.9),b=c.createBuffer(1,len,c.sampleRate),d=b.getChannelData(0);for(let i=0;i<len;i++)d[i]=(Math.random()*2-1)*(1-i/len);const n=c.createBufferSource(),f=c.createBiquadFilter(),ng=c.createGain();n.buffer=b;f.type='bandpass';f.frequency.setValueAtTime(450,t);f.frequency.exponentialRampToValueAtTime(2400,t+.28);f.frequency.exponentialRampToValueAtTime(250,t+.85);ng.gain.setValueAtTime(.0001,t);ng.gain.exponentialRampToValueAtTime(.24,t+.08);ng.gain.exponentialRampToValueAtTime(.0001,t+.88);n.connect(f);f.connect(ng);ng.connect(m);n.start(t);n.stop(t+.9);const btn=document.getElementById('loginRasenganSound');btn.textContent='🌀 Rasengan!';setTimeout(()=>{if(btn.isConnected)btn.textContent='⚡ Play Rasengan Sound'},1400)}catch(e){console.warn(e)}}document.getElementById('loginRasenganSound').addEventListener('click',playLoginRasengan);</script></body></html>"""

# Match the protocol constants used by the supplied project.
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
    "BD":  "https://client.ind.freefiremobile.com/GetPlayerPersonalShow",  # BD -> IND host
    "BR":  "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
    "US":  "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
    "SAC": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
    "NA":  "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
}
# कोई DEFAULT_URL fallback नहीं। अगर region unknown होगा, तो सीधे साफ़ error देगा।


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
    token = data[0].get("jwt_token") or data[0].get("token")
    if not token:
        raise ValueError(f"No jwt_token/token field found in {filename}.")
    return token


def fetch_player(uid: int, region: str) -> dict:
    token = load_token(region)
    url = REGION_URL.get(region)
    if not url:
        raise ValueError(f"Unsupported region '{region}'. Use IND, BD, BR, US, SAC, or NA.")
    
    headers = {
        "User-Agent": "Dalvik/2.1.0 (Linux; Android 9)",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.11f1",
        "ReleaseVersion": "OB55",
    }
    
    last_exc = None
    for attempt in range(2):  # 1 retry on network/timeout
        try:
            response = requests.post(
                url, 
                data=bytes.fromhex(encrypted_uid(uid)), 
                headers=headers, 
                timeout=TIMEOUT
            )
            break
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt == 0:
                time.sleep(1.5)
                continue
            raise
    else:
        raise last_exc

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


def read_ids_file():
    path = BASE_DIR / "ids.json"
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("ids", [])
        if not isinstance(raw, list):
            return []
        clean = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            uid = str(item.get("uid", "")).strip()
            region = str(item.get("region", "IND")).strip().upper()
            if uid.isdigit() and int(uid) > 0 and region in {"IND", "BD", "BR", "US", "SAC", "NA"}:
                clean.append({"uid": uid, "region": region, "nickname": str(item.get("nickname", ""))[:80]})
        return clean
    except (OSError, json.JSONDecodeError):
        app.logger.warning("ids.json could not be read")
        return []


def token_file_status():
    # Do not return token contents, account identifiers, or any credential fields.
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


@app.post("/monitor/event")
def monitor_event():
    # Receives results from an authorized upstream integration; it does not send likes.
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
    # Accept both normalized fields and the names used by the existing likes response.
    if "likes_before" not in payload and "LikesbeforeCommand" in payload:
        payload["likes_before"] = payload.get("LikesbeforeCommand")
    if "likes_after" not in payload and "LikesafterCommand" in payload:
        payload["likes_after"] = payload.get("LikesafterCommand")
    if "likes_given" not in payload and "LikesGivenByAPI" in payload:
        payload["likes_given"] = payload.get("LikesGivenByAPI")
    before = nonnegative_int("likes_before")
    after = nonnegative_int("likes_after")
    gained = nonnegative_int("likes_given")
    # Count only the confirmed delta; never trust a claimed likes_given above after-before.
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


def ping_upstream_api():
    """Check whether the configured upstream host responds; never sends JWT/API credentials."""
    started = time.perf_counter()
    try:
        response = requests.get(UPSTREAM_API_URL, timeout=UPSTREAM_PING_TIMEOUT, allow_redirects=True)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        # A 4xx response still proves the host is reachable; 5xx means service-side trouble.
        online = response.status_code < 500
        return {
            "url": UPSTREAM_API_URL,
            "online": online,
            "http_status": response.status_code,
            "latency_ms": latency_ms,
            "message": "Reachable" if online else "Upstream server error",
        }
    except requests.RequestException as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "url": UPSTREAM_API_URL,
            "online": False,
            "http_status": None,
            "latency_ms": latency_ms,
            "message": "Connection failed: " + type(exc).__name__,
        }


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
        region_names = ["IND", "BD", "BR", "US", "SAC", "NA"]
        regions = []
        for region in region_names:
            jj = conn.execute("SELECT SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) success,SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END) failed,COALESCE(SUM(likes_given),0) gained,COUNT(DISTINCT CASE WHEN status='limit_reached' THEN uid END) limits FROM like_jobs WHERE region=? AND date(timestamp, '+5 hours', '+30 minutes')=?", (region,today)).fetchone()
            region_jobs = conn.execute("SELECT COUNT(*) FROM like_jobs WHERE region=? AND date(timestamp, '+5 hours', '+30 minutes')=?", (region,today)).fetchone()[0]
            regions.append({"region":region,"jobs_today":region_jobs,"success_today":jj["success"] or 0,"failed_today":jj["failed"] or 0,"likes_gained_today":jj["gained"] or 0,"limit_accounts_today":jj["limits"] or 0})
    # Merge configured ids.json into the displayed UID list without pretending they have job history.
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


@app.get("/debug/token-status")
def debug_token_status():
    """Read-only diagnostic. Never returns token values, only shape and freshness."""
    if not authorized():
        return error("Invalid or missing API key.", 403)
    out = {}
    for region, filename in [("IND", "token_ind.json"), ("BD", "token_bd.json"), ("BR", "token_br.json")]:
        path = BASE_DIR / filename
        info = {"file": filename, "exists": path.is_file(), "entries": 0,
                "usable": 0, "expired": 0, "invalid": 0, "age_hours_max": None}
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
                            if iat:
                                ages.append((now_ts - iat) / 3600)
                            info["usable"] += 1
                        except Exception:
                            info["invalid"] += 1
                    if ages:
                        info["age_hours_max"] = round(max(ages), 1)
            except (OSError, json.JSONDecodeError) as exc:
                info["read_error"] = type(exc).__name__
        out[region] = info
    return jsonify({"ok": True, "regions": out,
                    "now_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})


def query_player():
    if not authorized():
        return None, error("Invalid or missing API key. Add &key=YOUR_API_KEY to the URL.", 403)

    uid_text = request.args.get("uid", "").strip()
    region = request.args.get("server_name", "IND").strip().upper()

    if not uid_text.isdigit() or int(uid_text) <= 0:
        return None, error("uid must be a positive numeric player UID.", 400)

    if region not in REGION_URL:
        return None, error(f"Unsupported region '{region}'. Use IND, BD, BR, US, SAC, or NA.", 400)

    try:
        return fetch_player(int(uid_text), region), None

    except FileNotFoundError as exc:
        return None, error(f"Token file missing: {exc}. Upload token_{region.lower()}.json to Render.", 503)

    except ValueError as exc:
        msg = str(exc)
        if "non-empty JSON list" in msg or "No jwt_token" in msg:
            return None, error(f"{msg} — token file must be a JSON list like [{{\"jwt_token\": \"eyJ...\"}}] with at least one valid entry.", 400)
        return None, error(msg, 400)

    except requests.Timeout:
        return None, error(f"Upstream game server timed out after {TIMEOUT}s (region {region}). Try again.", 504)

    except requests.ConnectionError:
        return None, error(f"Could not connect to Free Fire {region} server. Upstream may be blocked or down.", 502)

    except requests.RequestException:
        return None, error("Upstream network error. Try again later.", 502)

    except RuntimeError as exc:
        msg = str(exc)
        if "401" in msg or "403" in msg:
            return None, error(f"Token rejected by upstream (HTTP 401/403). Your JWT in token_{region.lower()}.json is expired — generate a fresh one.", 401)
        if "429" in msg:
            return None, error("Upstream rate-limited (HTTP 429). Wait a few minutes and retry.", 429)
        return None, error(msg, 502)

    except LookupError as exc:
        return None, error(f"{exc} — UID {uid_text} not found in region {region}. Check the UID or try a different region.", 404)

    except Exception as exc:
        app.logger.exception("Player lookup failed — uid=%s region=%s", uid_text, region)
        return None, error(f"Unexpected error: {type(exc).__name__}: {exc}", 500)


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
