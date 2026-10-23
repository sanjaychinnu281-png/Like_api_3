# CHINNU Free Fire API - Render-safe starter
# Provides player information and current likes count. It does NOT send automated likes.
import os
import json
import binascii
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request, jsonify
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToDict

import like_count_pb2
import uid_generator_pb2

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
API_KEY = os.getenv("API_KEY", "CHINNU").strip()
OWNER = os.getenv("OWNER_NAME", "CHINNU TEAM")
TIMEOUT = 15

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


@app.get("/")
def home():
    return jsonify({
        "name": OWNER,
        "ok": True,
        "message": "Free Fire player API is running.",
        "endpoints": ["/health", "/player-info?uid=PLAYER_UID&server_name=IND&key=YOUR_API_KEY", "/like?uid=PLAYER_UID&server_name=IND&key=YOUR_API_KEY"],
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
