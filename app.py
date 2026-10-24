# CHINNU Free Fire Like API + Vercel Dashboard (Daily & Weekly Monitor)
import os
import json
import binascii
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
from sqlalchemy import create_engine, text

import uid_generator_pb2

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
API_KEY = os.getenv("API_KEY", "CHINNU").strip()
OWNER = os.getenv("OWNER_NAME", "CHINNU TEAM")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()
app.secret_key = os.getenv("FLASK_SECRET_KEY", "").strip() or os.urandom(32)
TIMEOUT = int(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "20"))
UPSTREAM_API_URL = os.getenv("UPSTREAM_API_URL", "https://like-api-3-vng3.onrender.com").strip().rstrip("/")

# --- DATABASE SETUP (Supabase PostgreSQL) ---
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True) if DATABASE_URL else None

def init_db():
    if not engine:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS like_jobs (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ DEFAULT NOW(),
                    uid VARCHAR(50) NOT NULL,
                    region VARCHAR(10) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    likes_given INTEGER DEFAULT 0,
                    message TEXT DEFAULT ''
                );
            """))
    except Exception as e:
        app.logger.error(f"DB Init Error: {e}")

init_db()

@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled exception: {str(e)}")
    return jsonify({"ok": False, "error": f"Internal Server Error: {str(e)}"}), 500

def dashboard_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("dashboard_logged_in"):
            return redirect(url_for("dashboard_login"))
        return fn(*args, **kwargs)
    return wrapper

# ---------------------------------------------------------
# DASHBOARD HTML (Naruto UI + Daily/Weekly Cards)
# ---------------------------------------------------------
DASHBOARD_HTML = r"""<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CHINNU FF Advanced Monitor</title><style>
:root{color-scheme:dark;--bg:#080d19;--panel:#111b2d;--panel2:#0b1424;--text:#e7eefc;--muted:#93a4bd;--border:#26354e;--accent:#5b8cff;--good:#35d49a;--bad:#ff6b82;--warn:#ffc857}html[data-theme="light"]{color-scheme:light;--bg:#f1f5fb;--panel:#fff;--panel2:#eaf0f8;--text:#172033;--muted:#64748b;--border:#d5deea;--accent:#2563eb;--good:#15803d;--bad:#dc2626;--warn:#a16207}html[data-theme="neon"]{color-scheme:dark;--bg:#090611;--panel:#171127;--panel2:#100b20;--text:#f5edff;--muted:#b6a5d5;--border:#49316d;--accent:#d946ef;--good:#4ade80;--bad:#fb7185;--warn:#fde047}html[data-theme="ocean"]{color-scheme:dark;--bg:#041821;--panel:#0a2938;--panel2:#08222f;--text:#e0f7ff;--muted:#8fb9c8;--border:#1b4b60;--accent:#22b8d4;--good:#2dd4bf;--bad:#fb7185;--warn:#facc15}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 85% 10%,color-mix(in srgb,var(--accent) 19%,transparent),transparent 38%),radial-gradient(ellipse at 12% 80%,#7c3aed17,transparent 40%),var(--bg);font-family:Inter,system-ui,Arial,sans-serif;color:var(--text);min-height:100vh;overflow-x:hidden}.bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}.stars{position:absolute;inset:0;background-image:radial-gradient(circle at 18% 24%,#fff9 0 1px,transparent 2px),radial-gradient(circle at 70% 28%,#60a5fa9c 0 1.5px,transparent 3px),radial-gradient(circle at 42% 72%,#fff7 0 1px,transparent 2px);background-size:270px 270px,330px 330px,210px 210px;opacity:.35;animation:drift 34s linear infinite}.glow{position:absolute;right:5%;top:8%;width:44vw;height:44vw;border-radius:50%;background:radial-gradient(circle,color-mix(in srgb,var(--accent) 25%,transparent),transparent 68%);filter:blur(20px);animation:pulse 12s ease-in-out infinite}.anime{position:absolute;right:-3vw;bottom:-12vh;width:min(48vw,620px);opacity:.22;filter:drop-shadow(0 0 25px color-mix(in srgb,var(--accent) 35%,transparent));animation:float 14s ease-in-out infinite}main{position:relative;z-index:1;max-width:1400px;margin:auto;padding:22px}header{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:22px}.brand{display:flex;align-items:center;gap:12px}.logo{display:grid;place-items:center;width:48px;height:48px;border-radius:15px;background:var(--accent);color:white;font-size:24px}h1{font-size:clamp(22px,4vw,31px);margin:0}.muted{color:var(--muted)}.sub{font-size:13px;margin-top:5px}.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}select,input,button,.btn{font:inherit;border:1px solid var(--border);border-radius:10px;padding:10px 12px;background:var(--panel);color:var(--text)}button,.btn{cursor:pointer;text-decoration:none}button.primary{background:var(--accent);color:white;border-color:var(--accent)}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:13px}.card,.panel{background:color-mix(in srgb,var(--panel) 89%,transparent);backdrop-filter:blur(14px);border:1px solid var(--border);border-radius:16px;padding:17px;box-shadow:0 12px 32px #0002;min-width:0}.label{font-size:12px;color:var(--muted)}.num{font-size:clamp(25px,4vw,33px);font-weight:800;margin-top:9px;letter-spacing:-.04em}.small{font-size:12px;color:var(--muted);margin-top:5px}.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}.layout{display:grid;grid-template-columns:1fr;gap:16px}.section{display:flex;justify-content:space-between;align-items:end;gap:12px;flex-wrap:wrap;margin:25px 0 12px}.section h2{font-size:18px;margin:0}.tablewrap{overflow:auto;border:1px solid var(--border);border-radius:13px;background:color-mix(in srgb,var(--panel) 92%,transparent)}table{border-collapse:collapse;width:100%;min-width:760px;font-size:12px}th,td{text-align:left;padding:12px;border-bottom:1px solid var(--border);white-space:nowrap}th{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);background:var(--panel2)}tbody tr:last-child td{border-bottom:0}.pill{display:inline-block;border-radius:999px;padding:4px 8px;font-size:10px;font-weight:800;background:var(--panel2)}.regiongrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.region{background:var(--panel2);border:1px solid var(--border);border-radius:12px;padding:13px}.region strong{font-size:18px}.region div{font-size:11px;color:var(--muted);margin-top:4px}.note{margin-top:16px;padding:12px 14px;border:1px solid var(--border);background:var(--panel2);border-radius:12px;font-size:12px;color:var(--muted);line-height:1.6}.live{display:inline-flex;gap:6px;align-items:center;color:var(--good);font-size:12px}.dot{width:7px;height:7px;border-radius:50%;background:var(--good);box-shadow:0 0 12px var(--good)}footer{display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;margin:18px 0;color:var(--muted);font-size:11px}@keyframes float{0%,100%{transform:translateY(0) rotate(-.4deg)}50%{transform:translateY(-17px) rotate(.6deg)}}@keyframes pulse{0%,100%{opacity:.5;transform:scale(.97)}50%{opacity:1;transform:scale(1.05)}}@keyframes drift{to{transform:translateY(-65px)}}@media(prefers-reduced-motion:reduce){.anime,.glow,.stars{animation:none!important}}@media(max-width:650px){main{padding:13px}.anime{width:90vw;right:-30vw;opacity:.13}.actions{width:100%}.actions select{flex:1}.card,.panel{padding:14px}}
.logo{position:relative;isolation:isolate;overflow:visible;animation:clPulse 4.2s ease-in-out infinite;box-shadow:0 0 22px color-mix(in srgb,var(--accent) 48%,transparent),inset 0 0 14px #ffffff22;background:linear-gradient(135deg,var(--accent),#7c3aed)!important}
.logo::before{content:"";position:absolute;inset:-4px;border-radius:19px;border:2px solid color-mix(in srgb,var(--accent) 75%,white);opacity:.65;animation:clRing 7s linear infinite;pointer-events:none}
.logo::after{content:"✦";position:absolute;right:-7px;top:-8px;font-size:13px;color:#fde68a;text-shadow:0 0 10px #facc15;animation:clSpark 2.8s ease-in-out infinite}
.logo span{position:relative;z-index:2;font-size:17px;font-weight:950;letter-spacing:-1px;color:#fff;text-shadow:0 2px 9px #111827aa}
@keyframes clPulse{0%,100%{transform:scale(1);filter:saturate(1)}50%{transform:scale(1.045);filter:saturate(1.3)}}@keyframes clRing{to{transform:rotate(360deg)}}@keyframes clSpark{0%,100%{transform:translateY(0) rotate(0);opacity:.65}50%{transform:translateY(-4px) rotate(18deg);opacity:1}}
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
</style></head><body><div class="bg" aria-hidden="true"><div class="stars"></div><div class="glow"></div>
<svg class="anime" viewBox="0 0 620 850" xmlns="http://www.w3.org/2000/svg"><defs>
 <linearGradient id="nHair" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#fff2a8"/><stop offset=".42" stop-color="#ffd43b"/><stop offset="1" stop-color="#f59e0b"/></linearGradient>
 <linearGradient id="nOrange" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#fb923c"/><stop offset=".55" stop-color="#f97316"/><stop offset="1" stop-color="#c2410c"/></linearGradient>
 <linearGradient id="nMetal"><stop stop-color="#64748b"/><stop offset=".5" stop-color="#e2e8f0"/><stop offset="1" stop-color="#475569"/></linearGradient>
 <linearGradient id="nSkin" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#ffe0bd"/><stop offset="1" stop-color="#e9a779"/></linearGradient>
 <filter id="nGlow"><feGaussianBlur stdDeviation="8" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
<ellipse cx="320" cy="570" rx="205" ry="255" fill="#38bdf8" opacity=".09" filter="url(#nGlow)"/>
<g class="hair-back" fill="url(#nHair)" stroke="#f59e0b" stroke-width="4" stroke-linejoin="round"><path d="M190 250L125 151L216 185L207 89L274 160L318 64L347 160L416 94L409 187L495 150L440 254Z"/><path d="M206 212L167 126L240 177L260 104L302 173L351 94L365 180L424 131L407 218Z"/></g>
<path d="M166 840Q161 675 208 573Q242 526 310 520Q386 523 423 573Q469 681 461 840Z" fill="url(#nOrange)" stroke="#fdba74" stroke-width="5"/><path d="M255 535L310 628L365 535L399 840H221Z" fill="#172033" stroke="#334155" stroke-width="5"/><path d="M255 535L310 628L365 535L339 662L310 690L280 662Z" fill="#f8fafc" opacity=".95"/><path d="M205 601L264 640L241 840H174Z" fill="#ea580c"/><path d="M414 600L356 641L380 840H451Z" fill="#ea580c"/>
<path d="M274 467L272 540Q310 580 349 540L347 466Z" fill="url(#nSkin)"/>
<path d="M210 276Q206 174 310 164Q414 174 410 276L396 386Q375 465 310 484Q245 465 224 386Z" fill="url(#nSkin)" stroke="#b77955" stroke-width="3"/>
<path d="M218 310Q183 286 190 340Q197 371 226 365Z M402 310Q437 286 430 340Q423 371 394 365Z" fill="url(#nSkin)" stroke="#b77955" stroke-width="3"/>
<path d="M207 245Q310 214 413 245L408 292Q310 269 212 292Z" fill="#1e293b" stroke="#0f172a" stroke-width="5"/><path d="M247 237Q310 224 373 237L369 274Q310 263 251 274Z" fill="url(#nMetal)" stroke="#cbd5e1" stroke-width="3"/><path d="M309 244C296 238 285 248 290 257C295 266 307 263 309 255C314 267 329 264 332 253C334 245 322 239 315 246L309 251L304 246" fill="none" stroke="#334155" stroke-width="4" stroke-linecap="round"/><path d="M303 249L313 260L323 249" fill="none" stroke="#334155" stroke-width="3"/>
<path d="M237 322Q263 296 292 322Q266 346 237 322Z M328 322Q357 296 383 322Q355 346 328 322Z" fill="#f8fafc" stroke="#7c4a35" stroke-width="3"/><ellipse cx="267" cy="322" rx="9" ry="13" fill="#38bdf8"/><ellipse cx="355" cy="322" rx="9" ry="13" fill="#38bdf8"/><ellipse cx="267" cy="323" rx="4" ry="8" fill="#111827"/><ellipse cx="355" cy="323" rx="4" ry="8" fill="#111827"/><circle cx="270" cy="318" r="3" fill="white"/><circle cx="358" cy="318" r="3" fill="white"/><path d="M234 305L292 313M329 313L386 305" stroke="#7c4a35" stroke-width="7" stroke-linecap="round"/>
<g stroke="#9a5a42" stroke-width="5" stroke-linecap="round" opacity=".9"><path d="M225 354L257 362M224 369L254 377M365 362L397 354M367 377L396 369"/></g>
<path d="M309 333L302 359L314 362" fill="none" stroke="#c08463" stroke-width="4" stroke-linecap="round"/><path d="M276 398Q310 417 344 398Q333 435 310 430Q287 435 276 398Z" fill="#7f1d1d"/><path d="M283 402Q310 414 337 402L332 411H288Z" fill="#fff7ed"/>
<g class="hair-fringe" fill="url(#nHair)" stroke="#f59e0b" stroke-width="4" stroke-linejoin="round"><path d="M207 260Q190 194 238 142L251 217L282 131L300 219L333 126L351 220L389 151L393 260Q356 238 328 253L306 235L283 254Q245 237 207 260Z"/></g>
<path d="M239 533L274 508L310 560L346 508L382 533L358 589L310 628L262 589Z" fill="#1e293b" stroke="#64748b" stroke-width="4"/>
<g class="chakra" fill="#7dd3fc" filter="url(#nGlow)"><path d="M118 418l10 24 24 8-24 8-10 24-8-24-24-8 24-8Z"/><path d="M477 470l7 17 17 6-17 6-7 17-6-17-17-6 17-6Z"/><circle cx="160" cy="520" r="5"/><circle cx="452" cy="390" r="4"/></g>
<g class="blink-lids" aria-hidden="true"><path d="M234 322Q263 296 295 322Q266 350 234 322Z" fill="url(#nSkin)" stroke="#b77955" stroke-width="3"/><path d="M326 322Q357 296 386 322Q355 350 326 322Z" fill="url(#nSkin)" stroke="#b77955" stroke-width="3"/></g>
</svg><div class="rasengan-scene" aria-hidden="true"><div class="rasengan-ring r2"></div><div class="rasengan-ring"></div><div class="rasengan-ring r3"></div><div class="rasengan-core"></div><i class="rasengan-spark s1"></i><i class="rasengan-spark s2"></i><i class="rasengan-spark s3"></i></div></div><main><header><div class="brand"><div class="logo" aria-label="CL animated logo"><span>CL</span></div><div><h1>CHINNU FF Monitor</h1><div class="sub muted">Advanced likes & request control center · <span class="live"><i class="dot"></i> LIVE</span></div></div></div><div class="actions"><label class="muted" for="theme">Theme</label><select id="theme"><option value="dark">Dark</option><option value="light">Light</option><option value="neon">Neon</option><option value="ocean">Ocean</option></select><button type="button" class="sound-btn" id="rasenganSound">⚡ Play Rasengan FX</button><a class="btn" href="/dashboard/logout">Logout</a></div></header>

<div class="cards">
  <div class="card"><div class="label">Today Requests</div><div class="num" id="todayTotal">—</div><div class="small">Total hits today</div></div>
  <div class="card"><div class="label">Today Success</div><div class="num good" id="todaySuccess">—</div><div class="small">Successful like jobs</div></div>
  <div class="card"><div class="label">Today Failed</div><div class="num bad" id="todayFailed">—</div><div class="small">Failed attempts</div></div>
  <div class="card"><div class="label">Today Likes</div><div class="num" id="todayLikes">—</div><div class="small">Likes given today</div></div>
  
  <div class="card"><div class="label">Weekly Requests</div><div class="num" id="weekTotal">—</div><div class="small">Last 7 days total</div></div>
  <div class="card"><div class="label">Weekly Success</div><div class="num good" id="weekSuccess">—</div><div class="small">Successful this week</div></div>
  <div class="card"><div class="label">Weekly Failed</div><div class="num bad" id="weekFailed">—</div><div class="small">Failed this week</div></div>
  <div class="card"><div class="label">Weekly Likes</div><div class="num" id="weekLikes">—</div><div class="small">Total likes given this week</div></div>
</div>

<div class="section"><h2>Recent like jobs</h2><span class="muted">Latest reported job outcomes</span></div>
<div class="tablewrap"><table><thead><tr><th>Time</th><th>UID</th><th>Region</th><th>Status</th><th>Gained</th><th>Message</th></tr></thead><tbody id="jobsRows"><tr><td colspan="6">Loading...</td></tr></tbody></table></div>

<div class="note"><b>Important:</b> This dashboard records actual job outcomes in Supabase Database. Daily & Weekly data updates in real-time. Never upload real JWT tokens to a public GitHub repository.</div><footer><span>© CHINNU TEAM · Private monitoring</span><span>Auto refresh every 30 seconds while visible</span></footer></main><script>
const $=id=>document.getElementById(id);const theme=$('theme');theme.value=localStorage.getItem('chinnuTheme')||'dark';document.documentElement.dataset.theme=theme.value;theme.addEventListener('change',()=>{document.documentElement.dataset.theme=theme.value;localStorage.setItem('chinnuTheme',theme.value)});const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const n=v=>Number(v||0).toLocaleString();const statusPill=s=>{let c=s==='success'?'good':s==='fail'?'bad':'warn';return `<span class="pill ${c}">${esc(s)}</span>`};function rows(id,arr,cols){$(id).innerHTML=arr.length?arr.map(r=>'<tr>'+cols.map(c=>'<td>'+c(r)+'</td>').join('')+'</tr>').join(''):`<tr><td colspan="${cols.length}">No records yet</td></tr>`}
let rasenganAudio=null;function playRasengan(){try{const AC=window.AudioContext||window.webkitAudioContext;if(!AC)return;rasenganAudio=rasenganAudio||new AC();if(rasenganAudio.state==='suspended')rasenganAudio.resume();const ctx=rasenganAudio,t=ctx.currentTime;const master=ctx.createGain();master.gain.setValueAtTime(.0001,t);master.gain.exponentialRampToValueAtTime(.16,t+.06);master.gain.exponentialRampToValueAtTime(.0001,t+1.25);master.connect(ctx.destination);const osc=ctx.createOscillator(),og=ctx.createGain();osc.type='sawtooth';osc.frequency.setValueAtTime(130,t);osc.frequency.exponentialRampToValueAtTime(620,t+.32);osc.frequency.exponentialRampToValueAtTime(95,t+1.15);og.gain.setValueAtTime(.0001,t);og.gain.exponentialRampToValueAtTime(.28,t+.1);og.gain.exponentialRampToValueAtTime(.0001,t+1.2);osc.connect(og);og.connect(master);osc.start(t);osc.stop(t+1.26);const length=Math.floor(ctx.sampleRate*.9),buf=ctx.createBuffer(1,length,ctx.sampleRate),data=buf.getChannelData(0);for(let i=0;i<length;i++)data[i]=(Math.random()*2-1)*(1-i/length);const noise=ctx.createBufferSource(),filter=ctx.createBiquadFilter(),ng=ctx.createGain();noise.buffer=buf;filter.type='bandpass';filter.frequency.setValueAtTime(450,t);filter.frequency.exponentialRampToValueAtTime(2400,t+.28);filter.frequency.exponentialRampToValueAtTime(250,t+.85);filter.Q.value=.8;ng.gain.setValueAtTime(.0001,t);ng.gain.exponentialRampToValueAtTime(.24,t+.08);ng.gain.exponentialRampToValueAtTime(.0001,t+.88);noise.connect(filter);filter.connect(ng);ng.connect(master);noise.start(t);noise.stop(t+.9);const ping=ctx.createOscillator(),pg=ctx.createGain();ping.type='sine';ping.frequency.setValueAtTime(900,t+.2);ping.frequency.exponentialRampToValueAtTime(180,t+.72);pg.gain.setValueAtTime(.0001,t);pg.gain.exponentialRampToValueAtTime(.13,t+.24);pg.gain.exponentialRampToValueAtTime(.0001,t+.8);ping.connect(pg);pg.connect(master);ping.start(t+.18);ping.stop(t+.82);const b=$('rasenganSound');if(b){b.textContent='🌀 Rasengan!';setTimeout(()=>{if(b.isConnected)b.textContent='⚡ Play Rasengan FX'},1400)}}catch(e){console.warn('Sound effect unavailable',e)}}const rasenganBtn=$('rasenganSound');if(rasenganBtn)rasenganBtn.addEventListener('click',playRasengan);
async function refresh(){if(document.hidden)return;try{const r=await fetch('/dashboard/data',{cache:'no-store'});if(r.status===401){location.href='/dashboard/login';return}const d=await r.json();if(!d.ok)throw Error('Unable to load data');
// DAILY
$('todayTotal').textContent=n(d.daily.total_jobs);$('todaySuccess').textContent=n(d.daily.success);$('todayFailed').textContent=n(d.daily.failed);$('todayLikes').textContent=n(d.daily.likes);
// WEEKLY
$('weekTotal').textContent=n(d.weekly.total_jobs);$('weekSuccess').textContent=n(d.weekly.success);$('weekFailed').textContent=n(d.weekly.failed);$('weekLikes').textContent=n(d.weekly.likes);
// JOBS
rows('jobsRows',d.jobs||[],[x=>esc(x.timestamp),x=>esc(x.uid),x=>esc(x.region),x=>statusPill(x.status),x=>n(x.likes_given),x=>esc(x.message||'—')]);
}catch(e){console.error(e)}}refresh();setInterval(refresh,30000);
</script></body></html>"""

LOGIN_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CHINNU Monitor Login</title><style>
:root{color-scheme:dark;--accent:#3b82f6}*{box-sizing:border-box}body{font-family:Inter,system-ui,-apple-system,Arial,sans-serif;background:radial-gradient(ellipse at 78% 20%,#2563eb36,transparent 40%),radial-gradient(ellipse at 10% 85%,#7c3aed28,transparent 38%),#070b16;color:#e5e7eb;display:grid;place-items:center;min-height:100vh;margin:0;overflow:hidden;padding:20px}.anime-bg{position:fixed;inset:0;pointer-events:none;overflow:hidden}.anime-glow{position:absolute;right:4%;top:8%;width:45vw;height:45vw;max-width:600px;max-height:600px;border-radius:50%;background:radial-gradient(circle,#2563eb44,transparent 68%);filter:blur(20px);animation:glowPulse 12s ease-in-out infinite}.stars{position:absolute;inset:0;background-image:radial-gradient(circle at 18% 24%,#fff9 0 1px,transparent 2px),radial-gradient(circle at 70% 28%,#60a5fa9c 0 1.5px,transparent 3px),radial-gradient(circle at 42% 72%,#fff7 0 1px,transparent 2px);background-size:270px 270px,330px 330px,210px 210px;animation:starsDrift 32s linear infinite;opacity:.4}.box{position:relative;z-index:1;width:min(390px,94vw);background:#101827d9;backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border:1px solid #64748b55;padding:clamp(24px,6vw,34px);border-radius:22px;box-shadow:0 24px 80px #0008}.logo{width:52px;height:52px;border-radius:16px;background:linear-gradient(135deg,#2563eb,#9333ea);display:grid;place-items:center;font-size:27px;margin-bottom:18px;box-shadow:0 0 30px #3b82f644}h1{margin:0;font-size:25px}p{color:#9ca3af;line-height:1.55}.tag{display:inline-block;border:1px solid #3b82f655;color:#93c5fd;background:#1d4ed822;padding:5px 9px;border-radius:999px;font-size:11px;letter-spacing:.08em;margin:13px 0}input,button{font:inherit;box-sizing:border-box;width:100%;padding:13px 14px;margin:8px 0;border-radius:11px;border:1px solid #334155}input{background:#070d19;color:#f8fafc;outline:none}input:focus{border-color:#60a5fa;box-shadow:0 0 0 3px #3b82f622}button{background:linear-gradient(100deg,#2563eb,#7c3aed);color:white;border:0;font-weight:700;cursor:pointer;box-shadow:0 8px 24px #2563eb30}button:hover{filter:brightness(1.1)}.error{color:#fca5a5!important}@keyframes animeFloat{0%,100%{transform:translate3d(0,0,0) rotate(-.5deg)}50%{transform:translate3d(-10px,-18px,0) rotate(.7deg)}}@keyframes glowPulse{0%,100%{opacity:.55;transform:scale(.96)}50%{opacity:1;transform:scale(1.06)}}@keyframes starsDrift{from{transform:translateY(0)}to{transform:translateY(-70px)}}@media(max-width:700px){.anime-glow{width:85vw;height:85vw;right:-15vw;top:18%}}@media(prefers-reduced-motion:reduce){.anime-glow,.stars{animation:none!important}}
</style></head><body><div class="anime-bg" aria-hidden="true"><div class="stars"></div><div class="anime-glow"></div></div><form class="box" method="post"><div class="logo" aria-label="CL animated logo"><span>CL</span></div><h1>CHINNU Monitor</h1><span class="tag">PRIVATE CONTROL CENTER</span><p>Sign in to view API activity and monitoring.</p>{% if error %}<p class="error">{{ error }}</p>{% endif %}<input type="password" name="password" required autocomplete="current-password" placeholder="Dashboard password"><button type="submit">Unlock Dashboard →</button></form></body></html>"""

# --- LIKE LOGIC ---
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

# --- ROUTES ---
@app.get("/")
def home():
    return jsonify({"ok": True, "message": "API running", "endpoints": ["/like?uid=...&region=IND&key=...", "/dashboard"]})

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

    if engine:
        try:
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO like_jobs (uid, region, status, likes_given, message)
                    VALUES (:uid, :region, :status, :given, :msg)
                """), {"uid": str(uid), "region": region, "status": result["status"], "given": result.get("given", 0), "msg": result.get("message", "")})
        except Exception as e:
            app.logger.error(f"Failed to save job: {e}")

    return jsonify({"ok": result["status"] == "success", "likes_given": result.get("given", 0), "message": result["message"]})

@app.get("/dashboard/data")
@dashboard_required
def dashboard_data():
    if not engine:
        return jsonify({"ok": False, "error": "Database not configured."})
    
    try:
        with engine.begin() as conn:
            today_query = text("""
                SELECT COUNT(*) as total_jobs,
                    COALESCE(SUM(CASE WHEN status='success' THEN 1 ELSE 0 END), 0) as success_jobs,
                    COALESCE(SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END), 0) as failed_jobs,
                    COALESCE(SUM(likes_given), 0) as total_likes
                FROM like_jobs WHERE timestamp >= CURRENT_DATE
            """)
            daily = conn.execute(today_query).fetchone()
            
            weekly_query = text("""
                SELECT COUNT(*) as total_jobs,
                    COALESCE(SUM(CASE WHEN status='success' THEN 1 ELSE 0 END), 0) as success_jobs,
                    COALESCE(SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END), 0) as failed_jobs,
                    COALESCE(SUM(likes_given), 0) as total_likes
                FROM like_jobs WHERE timestamp >= CURRENT_DATE - INTERVAL '7 days'
            """)
            weekly = conn.execute(weekly_query).fetchone()

            jobs = [dict(r._mapping) for r in conn.execute(text("SELECT * FROM like_jobs ORDER BY timestamp DESC LIMIT 50")).fetchall()]

            for j in jobs:
                j['timestamp'] = j['timestamp'].strftime("%Y-%m-%d %H:%M:%S")

        return jsonify({
            "ok": True,
            "daily": {"total_jobs": daily[0], "success": daily[1], "failed": daily[2], "likes": daily[3]},
            "weekly": {"total_jobs": weekly[0], "success": weekly[1], "failed": weekly[2], "likes": weekly[3]},
            "jobs": jobs
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.get("/dashboard")
@dashboard_required
def dashboard():
    return render_template_string(DASHBOARD_HTML, owner=OWNER)

@app.route("/dashboard/login", methods=["GET", "POST"])
def dashboard_login():
    if not DASHBOARD_PASSWORD:
        return "Set DASHBOARD_PASSWORD in environment variables.", 503
    message = None
    if request.method == "POST":
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

# VERCEL ENTRY POINT
handler = app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
