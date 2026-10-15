import os
import re
import ssl
import zlib
import json
import time
import uuid
import hmac
import math
import hashlib
import secrets
import sqlite3
import base64
import socket
import struct
import random
import threading
import unicodedata
from collections import deque, defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from urllib.parse import urlparse, unquote

import requests
from requests.adapters import HTTPAdapter
try:
    from Crypto.Cipher import AES
except ImportError:
    try:
        from Cryptodome.Cipher import AES
    except ImportError:
        from cryptography.hazmat.primitives.ciphers import Cipher as _Cipher, algorithms as _alg, modes as _modes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM

        class AES:
            MODE_CBC = 2
            MODE_GCM = 11
            block_size = 16

            @staticmethod
            def new(key, mode, iv_or_nonce=None, nonce=None):
                if mode == 2:
                    iv = iv_or_nonce if iv_or_nonce is not None else bytes(16)
                    class _CBCWrap:
                        def __init__(self, k, i):
                            self._c = _Cipher(_alg.AES(k), _modes.CBC(i))
                        def encrypt(self, data):
                            enc = self._c.encryptor()
                            return enc.update(data) + enc.finalize()
                        def decrypt(self, data):
                            dec = self._c.decryptor()
                            return dec.update(data) + dec.finalize()
                    return _CBCWrap(key, iv)
                else:
                    nc = nonce if nonce is not None else iv_or_nonce
                    class _GCMWrap:
                        def __init__(self, k, n):
                            self._g = _AESGCM(k)
                            self._n = n
                            self._aad = b""
                        def update(self, aad):
                            self._aad += aad
                        def decrypt_and_verify(self, ct, tag):
                            return self._g.decrypt(self._n, ct + tag, self._aad or None)
                        def decrypt(self, ct):
                            return self._g.decrypt(self._n, ct, self._aad or None)
                    return _GCMWrap(key, nc)

from flask import (
    Flask, request, jsonify, session, redirect, Response, send_from_directory, render_template_string
)
from werkzeug.utils import secure_filename

# ============================================================
# CẤU HÌNH HỆ THỐNG & BẢO MẬT WEB — NOEL
# ============================================================
APP_TITLE = "NOEL"
SECRET_KEY = os.environ.get("SECRET_KEY", "noel-secret-key-2026-secure")
ACCESS_KEY = os.environ.get("WEB_KEY", "anhba")
DEFAULT_ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
DEFAULT_ADMIN_PASS = os.environ.get("ADMIN_PASS", "anhba")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
LOGO_DIR = os.path.join(UPLOAD_DIR, "brand")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(LOGO_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024
app.config["JSON_AS_ASCII"] = False
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ============================================================
# LÁ CHẮN BẢO MẬT WEB (CHỐNG BRUTE-FORCE, RATE-LIMIT API, HEADERS)
# ============================================================
LOGIN_ATTEMPTS = defaultdict(lambda: {"fails": 0, "lock_until": 0.0})
API_RATE_BUCKETS = defaultdict(lambda: deque(maxlen=260))
SECURITY_LOCK = threading.Lock()


def get_client_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def check_ip_bruteforce(ip):
    now = time.time()
    with SECURITY_LOCK:
        st = LOGIN_ATTEMPTS[ip]
        if now < st["lock_until"]:
            return False, int(st["lock_until"] - now)
        return True, 0


def record_login_result(ip, success):
    now = time.time()
    with SECURITY_LOCK:
        st = LOGIN_ATTEMPTS[ip]
        if success:
            st["fails"] = 0
            st["lock_until"] = 0.0
        else:
            st["fails"] += 1
            if st["fails"] >= 8:
                st["lock_until"] = now + min(300, 20 * (st["fails"] - 7))


def hash_password_secure(raw_pw):
    salt = secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", raw_pw.encode("utf-8"), salt.encode("utf-8"), 100000).hex()
    return f"pbkdf2${salt}${h}"


def verify_password_secure(stored_pw, provided_pw):
    if not stored_pw or not provided_pw:
        return False
    if stored_pw.startswith("pbkdf2$"):
        parts = stored_pw.split("$")
        if len(parts) == 3:
            _, salt, h = parts
            calc = hashlib.pbkdf2_hmac("sha256", provided_pw.encode("utf-8"), salt.encode("utf-8"), 100000).hex()
            return hmac.compare_digest(h, calc)
    return hmac.compare_digest(str(stored_pw), str(provided_pw))


@app.before_request
def security_middleware():
    if request.path.startswith("/api/"):
        ip = get_client_ip()
        now = time.time()
        with SECURITY_LOCK:
            dq = API_RATE_BUCKETS[ip]
            while dq and now - dq[0] > 10.0:
                dq.popleft()
            if len(dq) >= 240:
                return jsonify({"ok": False, "error": "Thao tác quá nhanh, vui lòng thử lại sau vài giây"}), 429
            dq.append(now)


@app.after_request
def add_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp


# ============================================================
# BỘ LỌC ẨN LOG TÀI KHOẢN NHẠY CẢM (STEALTH ACCOUNT LOG MASKING)
# ============================================================
def mask_sensitive_id(val, keep_tail=3):
    s = str(val or "").strip()
    if not s:
        return "***"
    if len(s) <= keep_tail + 2:
        return "***"
    return f"***{s[-keep_tail:]}"


def mask_account_name(name):
    s = str(name or "").strip()
    if not s:
        return "Acc_***"
    if len(s) <= 3:
        return s[0] + "**"
    return f"{s[:2]}***{s[-1:]}"


def sanitize_log_text(txt):
    if not txt:
        return ""
    s = str(txt)
    s = re.sub(r"[A-Za-z0-9_\-]{23,28}\.[A-Za-z0-9_\-]{6,7}\.[A-Za-z0-9_\-]{27,45}", "[HIDDEN_TOKEN]", s)
    s = re.sub(r"(https?://[^\s]+)", "[STEALTH_ROUTE]", s)
    return s[:220]


# ============================================================
# KHỞI TẠO & ĐỒNG BỘ CƠ SỞ DỮ LIỆU SQLITE TỐC ĐỘ CAO
# ============================================================
_ACTIVE_DB_PATH = DB_PATH


def db():
    global _ACTIVE_DB_PATH
    try:
        conn = sqlite3.connect(_ACTIVE_DB_PATH, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA temp_store=MEMORY;")
        return conn
    except sqlite3.OperationalError:
        import tempfile
        _ACTIVE_DB_PATH = os.path.join(tempfile.gettempdir(), "noel_database.db")
        conn = sqlite3.connect(_ACTIVE_DB_PATH, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn


def init_db():
    global _ACTIVE_DB_PATH
    try:
        conn = db()
        conn.execute("CREATE TABLE IF NOT EXISTS _lock_test (id INT)")
    except sqlite3.OperationalError:
        import tempfile
        _ACTIVE_DB_PATH = os.path.join(tempfile.gettempdir(), "noel_database.db")
        conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        created_at REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        imei TEXT,
        cookies TEXT,
        platform TEXT DEFAULT 'zalo',
        token TEXT,
        is_bot INTEGER DEFAULT 0,
        uid TEXT DEFAULT '',
        chat_cmd_enabled INTEGER DEFAULT 1,
        cmd_prefix TEXT DEFAULT '.',
        allow_all_cmd INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1,
        created_at REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS authorized_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid TEXT UNIQUE,
        name TEXT,
        added_by_acc INTEGER,
        added_at REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    cur.execute("PRAGMA table_info(accounts)")
    cols = [c[1] for c in cur.fetchall()]
    migrations = [
        ("platform", "ALTER TABLE accounts ADD COLUMN platform TEXT DEFAULT 'zalo'"),
        ("token", "ALTER TABLE accounts ADD COLUMN token TEXT"),
        ("is_bot", "ALTER TABLE accounts ADD COLUMN is_bot INTEGER DEFAULT 0"),
        ("uid", "ALTER TABLE accounts ADD COLUMN uid TEXT DEFAULT ''"),
        ("chat_cmd_enabled", "ALTER TABLE accounts ADD COLUMN chat_cmd_enabled INTEGER DEFAULT 1"),
        ("cmd_prefix", "ALTER TABLE accounts ADD COLUMN cmd_prefix TEXT DEFAULT '.'"),
        ("allow_all_cmd", "ALTER TABLE accounts ADD COLUMN allow_all_cmd INTEGER DEFAULT 0"),
        ("enabled", "ALTER TABLE accounts ADD COLUMN enabled INTEGER DEFAULT 1"),
    ]
    for col_name, sql_stmt in migrations:
        if col_name not in cols:
            try:
                cur.execute(sql_stmt)
            except Exception:
                pass

    cur.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT,
        filepath TEXT,
        lines_count INTEGER,
        created_at REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        type TEXT,
        meta TEXT,
        status TEXT,
        started_at REAL,
        stats TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        acc_id INTEGER,
        thread_id TEXT,
        sender_id TEXT,
        cmd_text TEXT,
        action_taken TEXT,
        created_at REAL
    )
    """)

    existing_admin = cur.execute("SELECT id FROM users WHERE username = ?", (DEFAULT_ADMIN_USER,)).fetchone()
    if not existing_admin:
        cur.execute(
            "INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
            (DEFAULT_ADMIN_USER, hash_password_secure(DEFAULT_ADMIN_PASS), time.time())
        )

    conn.commit()
    conn.close()


init_db()


def get_setting(key, default_val=""):
    try:
        conn = db()
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else default_val
    except Exception:
        return default_val


def set_setting(key, val):
    try:
        conn = db()
        conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, str(val)))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ============================================================
# TRẠNG THÁI RUNTIME TOÀN CỤC & CHỐNG TỰ KÍCH HOẠT LỆNH (.MENU FIX)
# ============================================================
ACTIVE_TASKS = {}
ACTIVE_LISTENERS = {}

BOT_RUNTIME_CONFIG = {
    "delay": 1.0,
    "color_mode": "rainbow",
    "fixed_color": "red",
    "icon_count": 3,
    "use_emoji": True,
    "is_heading": True,
    "antiband": True,
    "antidieall": True,
    "strip_line_num": True,
    "hide_acc_log": True,
}
BOT_CFG_LOCK = threading.Lock()

BOT_SENT_IDS = deque(maxlen=1500)
BOT_SENT_TEXT_HASHES = deque(maxlen=1500)
BOT_SENT_LOCK = threading.Lock()


def _normalize_for_echo_hash(s):
    if not s:
        return ""
    for zw in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"):
        s = s.replace(zw, "")
    return re.sub(r"\s+", " ", s.strip()).lower()[:240]


def register_bot_sent_message(msg_id=None, client_id=None, text=None):
    now = time.time()
    with BOT_SENT_LOCK:
        if msg_id:
            BOT_SENT_IDS.append((str(msg_id), now))
        if client_id:
            BOT_SENT_IDS.append((str(client_id), now))
        if text:
            nh = _normalize_for_echo_hash(text)
            if nh:
                BOT_SENT_TEXT_HASHES.append((nh, now))
                first_line = _normalize_for_echo_hash(text.split("\n")[0])
                if first_line:
                    BOT_SENT_TEXT_HASHES.append((first_line, now))


def is_bot_echo_message(msg_id=None, client_id=None, text=None):
    now = time.time()
    with BOT_SENT_LOCK:
        for mid, ts in list(BOT_SENT_IDS):
            if now - ts <= 95.0:
                if (msg_id and str(msg_id) == mid) or (client_id and str(client_id) == mid):
                    return True
        if text:
            nh = _normalize_for_echo_hash(text)
            first_line = _normalize_for_echo_hash(text.split("\n")[0])
            for h_saved, ts in list(BOT_SENT_TEXT_HASHES):
                if now - ts <= 65.0 and h_saved and (nh == h_saved or first_line == h_saved):
                    return True
    return False


def new_tid(p):
    return f"{p}_{int(time.time() * 1000)}_{random.randint(100, 999)}"


def utf16_len(s):
    if not s:
        return 0
    return len(s.encode("utf-16-le")) // 2


def remove_vn_accents(s):
    if not s:
        return ""
    s = s.replace("đ", "d").replace("Đ", "D")
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


# ============================================================
# QUẢN LÝ PHÂN QUYỀN NGƯỜI DÙNG TRÊN KHUNG CHAT ZALO & DISCORD
# ============================================================
OWNER_UIDS_CACHE = set()
GLOBAL_USER_NAME_CACHE = {}


def refresh_owner_uids():
    global OWNER_UIDS_CACHE
    try:
        conn = db()
        rows = conn.execute("SELECT uid FROM accounts").fetchall()
        conn.close()
        s = set()
        for r in rows:
            if r["uid"]:
                for part in str(r["uid"]).split(","):
                    if part.strip():
                        s.add(part.strip())
        OWNER_UIDS_CACHE = s
    except Exception:
        pass


def is_user_authorized_for_cmd(sender_uid, client_uid=None, client_send2me_id=None, allow_all=False):
    s_uid = str(sender_uid or "").strip()
    if s_uid in ("0", ""):
        return True
    if client_uid and s_uid == str(client_uid).strip():
        return True
    if client_send2me_id and s_uid == str(client_send2me_id).strip():
        return True
    if s_uid in OWNER_UIDS_CACHE:
        return True
    if allow_all:
        return True

    try:
        conn = db()
        row = conn.execute("SELECT id FROM authorized_users WHERE uid = ?", (s_uid,)).fetchone()
        conn.close()
        return bool(row)
    except Exception:
        return False


def add_authorized_user(uid, name="", acc_id=0):
    uid_str = str(uid or "").strip()
    if not uid_str or uid_str in ("0", "-1"):
        return False
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO authorized_users (uid, name, added_by_acc, added_at) VALUES (?, ?, ?, ?)",
        (uid_str, name or f"User_{uid_str[-4:]}", acc_id, time.time())
    )
    conn.commit()
    conn.close()
    return True


def remove_authorized_user(uid):
    uid_str = str(uid or "").strip()
    conn = db()
    cur = conn.execute("DELETE FROM authorized_users WHERE uid = ?", (uid_str,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


def list_authorized_users():
    conn = db()
    rows = conn.execute("SELECT uid, name, added_at FROM authorized_users ORDER BY id ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# BỘ ICON & EMOJI CHUẨN ZALO 100% (ĐÃ FIX TRIỆT ĐỂ LỖI CHỮ THÔ ':-')
# ============================================================
ZALO_PALETTE = [
    {"id": "red",    "name": "Đỏ Rực",        "hex": "#db342e", "zcode": "db342e"},
    {"id": "yellow", "name": "Vàng Hoàng Kim", "hex": "#f7b503", "zcode": "f7b503"},
    {"id": "green",  "name": "Xanh Ngọc Lục",  "hex": "#15a85f", "zcode": "15a85f"},
    {"id": "orange", "name": "Cam Rực Lửa",    "hex": "#f27806", "zcode": "f27806"},
]

ZALO_NATIVE_ZCODES = ["db342e", "f7b503", "15a85f", "f27806"]
ZALO_COLOR_MAP = {
    "red": "db342e", "do": "db342e", "đỏ": "db342e",
    "yellow": "f7b503", "vang": "f7b503", "vàng": "f7b503",
    "green": "15a85f", "xanh": "15a85f", "xanhla": "15a85f",
    "orange": "f27806", "cam": "f27806",
    "ocean": "15a85f", "blue": "f7b503", "purple": "db342e", "pink": "f27806",
}

ZALO_ICON_VIP = [
    "😂", "🤣", "😝", "😜", "😎",
    "😡", "🤬", "😤", "😈", "🤡",
    "🔥", "💥", "⚡", "💪", "👊",
    "👍", "👎", "❤️", "💔", "🌹",
    "💩", "💣", "🎉", "✨", "👑",
    "💎", "🚀", "🎯", "👻", "💀"
]

LEGACY_SHORTCUT_TO_ICON_MAP = {
    ";-A": "😝", ";-!": "😤", ";f": "😜", ";;)": "😎", ";)": "😉",
    "=))": "🤣", ":))": "😂", ":)": "😊", ":(": "😢", ":((": "😭",
    "b-)": "😎", "8-)": "😎", "x-)": "😆", "=d>": "👏",
    ":-R": "😡", ":-L": "😤", ":-F": "🤬", ":-h": "👋", ":-*": "😘",
    ":-?": "🤔", ":-s": "😖", ":-t": "😠", ":-bd": "👍", ":-d": "😄",
    ":-p": "😜", ":-o": "😮", ":-x": "😍", ":-w": "⏳", ":-<": "😣",
    ":d": "😄", ":p": "😜", ":v": "✌️", ":3": "😺", ":>": "😏",
    ":$": "😳", ":x": "😍", ":o": "😮",
    "/-strong": "💪", "/-weak": "👎", "/-punch": "👊", "/-shit": "💩",
    "/-bome": "💣", "/-rose": "🌹", "/-heart": "❤️", "/-ok": "👌",
    "/-li": "⚡", "/-fade": "💔", "/-bd": "👍", "/-break": "💔", "/-no": "🙅",
}

BROKEN_COLON_DASH_RE = re.compile(
    r"(?<!\S)(?:[:;]\-[A-Za-z0-9\*\?\!\(\)\<\>\/\\]+|\/-[a-zA-Z]+|;;?\)|=d>|=?\)\)|;f)(?!\S)"
)


def get_icon_hard(prev_icons=None):
    pool = [ic for ic in ZALO_ICON_VIP if not prev_icons or ic not in prev_icons]
    if not pool:
        pool = ZALO_ICON_VIP
    return random.choice(pool)


def build_unique_zalo_icons(count):
    if count <= 0:
        return ""
    chosen = []
    for _ in range(count):
        chosen.append(get_icon_hard(chosen[-2:]))
    return " ".join(chosen)


def clean_corrupted_shortcuts(text):
    if not text:
        return ""
    for zw in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"):
        text = text.replace(zw, "")

    def _replace_broken(match):
        token = match.group(0)
        if token in LEGACY_SHORTCUT_TO_ICON_MAP:
            return LEGACY_SHORTCUT_TO_ICON_MAP[token]
        if token.lower() in LEGACY_SHORTCUT_TO_ICON_MAP:
            return LEGACY_SHORTCUT_TO_ICON_MAP[token.lower()]
        return get_icon_hard()

    text = BROKEN_COLON_DASH_RE.sub(_replace_broken, text)
    text = re.sub(r"(?<!\S)[:;]\-[A-Za-z0-9\*\?\!]*", lambda _: get_icon_hard(), text)
    return text


def _is_emoji_or_zalo_shortcut_token(tk):
    if not tk:
        return False
    if tk in ZALO_ICON_VIP or tk in LEGACY_SHORTCUT_TO_ICON_MAP:
        return True
    if BROKEN_COLON_DASH_RE.fullmatch(tk):
        return True
    if all((ord(ch) > 0x2000 or ch in ("\ufe0f", "\u200d")) for ch in tk):
        return True
    return False


# ============================================================
# BỘ LỌC TỰ ĐỘNG XOÁ SỐ THỨ TỰ ĐẦU DÒNG ("1. ", "2. ", "3) ") & TẢI FILE NHANH
# ============================================================
FILE_MEMORY_CACHE = {}
FILE_CACHE_LOCK = threading.Lock()

LEADING_NUMBER_RE = re.compile(
    r"^\s*(?:câu\s*\d+[\.\:\)\-]+|\(\d+\)|#?\d+[\.\)\:\-]+)\s*",
    re.IGNORECASE
)


def strip_leading_line_number(line):
    if not line:
        return ""
    cleaned = LEADING_NUMBER_RE.sub("", line.strip()).strip()
    cleaned = clean_corrupted_shortcuts(cleaned)
    return cleaned if cleaned else line.strip()


def parse_file_stream_fast(filepath, strip_numbers=True):
    if not filepath or not os.path.exists(filepath):
        return {"blocks": [], "lines": [], "raw_lines": [], "size": 0, "block_count": 0, "line_count": 0}

    st = os.stat(filepath)
    mtime = st.st_mtime
    fsize = st.st_size
    cache_key = (filepath, bool(strip_numbers))

    with FILE_CACHE_LOCK:
        cached = FILE_MEMORY_CACHE.get(cache_key)
        if cached and cached["mtime"] == mtime and cached["size"] == fsize:
            return cached

    blocks = []
    all_lines = []
    raw_non_empty_lines = []
    current_block = []

    with open(filepath, "rb") as f:
        raw_bytes = f.read()

    text = raw_bytes.decode("utf-8", errors="ignore").replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = text.split("\n")

    for ln in raw_lines:
        stripped = ln.strip()
        if stripped:
            raw_non_empty_lines.append(stripped)
            clean_ln = strip_leading_line_number(stripped) if strip_numbers else clean_corrupted_shortcuts(stripped)
            all_lines.append(clean_ln)
            current_block.append(clean_ln)
        else:
            if current_block:
                blocks.append("\n".join(current_block))
                current_block = []
    if current_block:
        blocks.append("\n".join(current_block))

    if not blocks and all_lines:
        blocks = list(all_lines)

    result = {
        "mtime": mtime,
        "size": fsize,
        "blocks": blocks,
        "lines": all_lines,
        "raw_lines": raw_non_empty_lines,
        "block_count": len(blocks),
        "line_count": len(all_lines),
    }

    with FILE_CACHE_LOCK:
        if len(FILE_MEMORY_CACHE) > 40:
            oldest_key = next(iter(FILE_MEMORY_CACHE))
            FILE_MEMORY_CACHE.pop(oldest_key, None)
        FILE_MEMORY_CACHE[cache_key] = result

    return result


def get_ordered_files_with_display_num():
    conn = db()
    rows = conn.execute("SELECT * FROM files ORDER BY id ASC").fetchall()
    conn.close()
    out = []
    for idx, r in enumerate(rows, start=1):
        d = dict(r)
        d["display_num"] = idx
        out.append(d)
    return out


def resolve_file_record(query_val):
    if query_val is None:
        return None
    q = str(query_val).strip()
    if not q:
        return None

    files = get_ordered_files_with_display_num()
    if not files:
        return None

    num_match = re.match(r"^#?(\d+)$", q)
    if num_match:
        num = int(num_match.group(1))
        by_disp = next((f for f in files if f["display_num"] == num), None)
        if by_disp:
            return by_disp
        by_id = next((f for f in files if f["id"] == num), None)
        if by_id:
            return by_id

    if q.lower() in ("auto", "default", "moinhat", "latest"):
        return files[-1]

    q_low = q.lower()
    for f in files:
        if f["filename"].lower() == q_low or q_low in f["filename"].lower():
            return f
    return None


def get_blocks_from_file_query(query_val, mode="fast"):
    rec = resolve_file_record(query_val)
    if not rec:
        return []
    parsed = parse_file_stream_fast(rec["filepath"], strip_numbers=True)
    if mode == "treo_nhay":
        return parsed["lines"] if parsed["lines"] else parsed["blocks"]
    return parsed["blocks"]


# ============================================================
# HẠ TẦNG ANTI-BAN & ANTI-DIE-ALL SIÊU ĐỈNH CHO CẢ 2 APP (ZALO & DISCORD)
# ============================================================
ZERO_WIDTH_ZALO_POOL = ["\u200b", "\u200c", "\u2060"]
ZERO_WIDTH_DISCORD_POOL = ["\u200b", "\u200c", "\u200d", "\u2060"]
_ANTIBAN_COUNTER = 0
_ANTIBAN_LOCK = threading.Lock()


class ZaloSmartAntiBanEngine:
    """Hạ tầng Anti-Ban thế hệ mới chuyên biệt cho Zalo:
    - Zero-Shift Polymorphic Tail Signature: Mã hóa vi chữ ký tàng hình ở cuối chuỗi.
    - Biometric Human Cadence: Mô phỏng nhịp gõ bàn phím sinh học (Weibull + Gaussian jitter + Micro-break).
    - Zalo Session Shield: Bảo vệ Cookie & khóa zpw_enk trước các mã phạt -112, -114, 300, 301, 429."""

    RATELIMIT_CODES = {-2, -108, -112, -114, 112, 114, 300, 301, 302, 429, 500, 1001, 2001}
    AUTH_CODES = {-401, 401, -102, 102, -30, -13, 3003}

    BROWSER_PROFILES = [
        {
            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "platform": '"Windows"'
        },
        {
            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
            "sec_ch_ua": '"Microsoft Edge";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "platform": '"Windows"'
        },
        {
            "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "platform": '"macOS"'
        },
    ]

    @classmethod
    def get_session_headers(cls, imei):
        idx = zlib.crc32(str(imei or "zalo").encode("utf-8")) % len(cls.BROWSER_PROFILES)
        prof = cls.BROWSER_PROFILES[idx]
        return {
            "User-Agent": prof["ua"],
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": "https://chat.zalo.me",
            "Referer": "https://chat.zalo.me/",
            "Sec-Ch-Ua": prof["sec_ch_ua"],
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": prof["platform"],
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }

    @staticmethod
    def generate_zero_shift_tail(thread_id=""):
        global _ANTIBAN_COUNTER
        with _ANTIBAN_LOCK:
            _ANTIBAN_COUNTER = (_ANTIBAN_COUNTER + 1) & 0xFFFFFF
            seq = _ANTIBAN_COUNTER
        t_hash = zlib.crc32(str(thread_id).encode("utf-8")) & 0xFFF
        salt = ((int(time.time() * 1000) & 0x1FFF) ^ (seq << 2) ^ t_hash ^ random.randint(1, 0xFFFF)) & 0xFFFF
        chars = []
        val = salt
        for _ in range(9):
            chars.append(ZERO_WIDTH_ZALO_POOL[val % len(ZERO_WIDTH_ZALO_POOL)])
            val = (val // len(ZERO_WIDTH_ZALO_POOL)) ^ random.randint(0, 2)
        return "".join(chars)

    @classmethod
    def append_tail(cls, final_msg, thread_id=""):
        if not final_msg:
            return final_msg
        return final_msg + " " + cls.generate_zero_shift_tail(thread_id)

    @staticmethod
    def compute_human_cadence_delay(base_delay, burst_cnt, risk_score, adaptive_bonus, text_len=20):
        d = float(base_delay) + adaptive_bonus + (risk_score * 0.016)
        typing_factor = min(0.28, max(0.03, (text_len / 220.0) * 0.14))
        gaussian_jitter = abs(random.gauss(0.11, 0.06))
        micro_break = 0.0
        if burst_cnt > 0 and burst_cnt % 15 == 0:
            micro_break = random.uniform(0.45, 1.15)
        elif burst_cnt > 0 and burst_cnt % 42 == 0:
            micro_break = random.uniform(1.2, 2.3)
        return max(0.24, d + typing_factor + gaussian_jitter + micro_break)


class DiscordStealthAntiBanEngine:
    """Hạ tầng Anti-Scan, Anti-Ban & Anti-Die-All chuyên sâu cho Discord:
    1. Locked Device Identity & Session UUIDs (`launch_signature`, `client_heartbeat_session_id`):
       Mỗi Token được cấp cố định cặp UUIDv4 phiên khởi chạy và phiên heartbeat giống hệt Discord Web Client thật.
    2. Context Properties Spoofing (`X-Context-Properties`): Gắn ngữ cảnh thao tác từ khung chat thật.
    3. Multi-Tier Rate-Limit & Slowmode Shield: Đọc trực tiếp `X-RateLimit-Remaining`, `X-RateLimit-Reset-After`,
       xử lý mã Slowmode (`20016`), Channel Write Limit (`20028`), Cloudflare (`1015`) và phối hợp cùng `AntiDieAllEngine`
       để chống chết chùm tài khoản (Anti-Chain-Ban).
    4. Browser Cookie Jar (`__dcfduid`, `__sdcfduid`, `_cfuvid`, `locale=vi`) + Snowflake 64-bit Nonce."""

    DISCORD_EPOCH = 1420070400000
    STEALTH_API_BASES = [
        "https://discord.com/api/v10",
        "https://discord.com/api/v9",
        "https://canary.discord.com/api/v10",
        "https://ptb.discord.com/api/v10",
    ]

    CLIENT_PROFILES = [
        {
            "os": "Windows",
            "browser": "Chrome",
            "os_version": "10",
            "browser_version": "131.0.0.0",
            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "build_number": 351420,
        },
        {
            "os": "Windows",
            "browser": "Chrome",
            "os_version": "11",
            "browser_version": "131.0.0.0",
            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "build_number": 351890,
        },
        {
            "os": "Mac OS X",
            "browser": "Chrome",
            "os_version": "10.15.7",
            "browser_version": "131.0.0.0",
            "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "build_number": 351420,
        },
    ]

    _CHANNEL_BUCKETS = {}
    _LAST_TYPING_TS = defaultdict(float)
    _FINGERPRINT_CACHE = {}
    _SESSION_UUID_CACHE = {}
    _LOCK = threading.Lock()

    @classmethod
    def get_deterministic_profile(cls, token):
        h = zlib.crc32(str(token or "discord").encode("utf-8"))
        return cls.CLIENT_PROFILES[h % len(cls.CLIENT_PROFILES)]

    @classmethod
    def get_deterministic_session_uuids(cls, token):
        key = str(token or "discord")[:24]
        with cls._LOCK:
            if key not in cls._SESSION_UUID_CACHE:
                seed = hashlib.sha256(key.encode("utf-8")).digest()
                u1 = str(uuid.UUID(bytes=seed[:16], version=4))
                u2 = str(uuid.UUID(bytes=seed[16:32], version=4))
                cls._SESSION_UUID_CACHE[key] = (u1, u2)
            return cls._SESSION_UUID_CACHE[key]

    @classmethod
    def get_deterministic_cookies(cls, token):
        seed = hashlib.sha256(str(token or "discord").encode("utf-8")).hexdigest()
        dcf = f"{seed[:8]}-{seed[8:12]}-4{seed[13:16]}-a{seed[17:20]}-{seed[20:32]}"
        sdcf = hashlib.sha512((seed + "_sdcf").encode("utf-8")).hexdigest()[:64]
        cfuv = hashlib.md5((seed + "_cfuv").encode("utf-8")).hexdigest()
        return {
            "__dcfduid": dcf,
            "__sdcfduid": sdcf,
            "_cfuvid": cfuv,
            "locale": "vi",
        }

    @classmethod
    def build_super_properties_b64(cls, token):
        prof = cls.get_deterministic_profile(token)
        launch_sig, hb_sess = cls.get_deterministic_session_uuids(token)
        props = {
            "os": prof["os"],
            "browser": prof["browser"],
            "device": "",
            "system_locale": "vi-VN",
            "browser_user_agent": prof["ua"],
            "browser_version": prof["browser_version"],
            "os_version": prof["os_version"],
            "referrer": "",
            "referring_domain": "",
            "referrer_current": "",
            "referring_domain_current": "",
            "release_channel": "stable",
            "client_build_number": prof["build_number"],
            "client_event_source": None,
            "has_client_mods": False,
            "launch_signature": launch_sig,
            "client_heartbeat_session_id": hb_sess,
        }
        raw_json = json.dumps(props, separators=(",", ":"))
        return base64.b64encode(raw_json.encode("utf-8")).decode("utf-8")

    @classmethod
    def build_context_properties_b64(cls, guild_id=None, channel_id=None):
        ctx = {"location": "Guild Channel" if guild_id else "DM Channel"}
        return base64.b64encode(json.dumps(ctx, separators=(",", ":")).encode("utf-8")).decode("utf-8")

    @classmethod
    def build_stealth_headers(cls, token, is_bot=False, channel_id=None, guild_id=None):
        auth_val = f"Bot {token}" if is_bot else token
        if is_bot:
            return {
                "Authorization": auth_val,
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://discord.com, 10.0)",
            }
        prof = cls.get_deterministic_profile(token)
        if guild_id and channel_id:
            ref = f"https://discord.com/channels/{guild_id}/{channel_id}"
        elif channel_id:
            ref = f"https://discord.com/channels/@me/{channel_id}"
        else:
            ref = "https://discord.com/channels/@me"

        headers = {
            "Authorization": auth_val,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "User-Agent": prof["ua"],
            "X-Super-Properties": cls.build_super_properties_b64(token),
            "X-Context-Properties": cls.build_context_properties_b64(guild_id, channel_id),
            "X-Discord-Locale": "vi",
            "X-Discord-Timezone": "Asia/Ho_Chi_Minh",
            "X-Debug-Options": "bugReporterEnabled",
            "Origin": "https://discord.com",
            "Referer": ref,
            "Sec-Ch-Ua": prof["sec_ch_ua"],
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": f'"{prof["os"]}"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        fp = cls._FINGERPRINT_CACHE.get(str(token)[:18])
        if fp:
            headers["X-Fingerprint"] = fp
        return headers

    @classmethod
    def pick_stealth_endpoint(cls, token, path_suffix, rotate_step=0):
        h = (zlib.crc32(str(token or "").encode("utf-8")) + rotate_step) % 2
        base = cls.STEALTH_API_BASES[h]
        return f"{base}{path_suffix}"

    @classmethod
    def generate_snowflake_nonce(cls):
        now_ms = int(time.time() * 1000)
        ts_part = max(0, now_ms - cls.DISCORD_EPOCH)
        rand_part = random.randint(1, 0x3FFFFF)
        return str((ts_part << 22) | rand_part)

    @classmethod
    def append_stealth_tail(cls, text, channel_id=""):
        if not text:
            return text
        global _ANTIBAN_COUNTER
        with _ANTIBAN_LOCK:
            _ANTIBAN_COUNTER = (_ANTIBAN_COUNTER + 1) & 0xFFFFFF
            seq = _ANTIBAN_COUNTER
        salt = ((int(time.time() * 1000) & 0xFFF) ^ (seq << 3) ^ random.randint(1, 0xFFFF)) & 0xFFFF
        zw = "".join(ZERO_WIDTH_DISCORD_POOL[(salt >> (i * 2)) & 0x3] for i in range(6))
        return text + zw

    @classmethod
    def record_bucket_headers(cls, channel_id, resp_headers):
        if not channel_id or not resp_headers:
            return
        try:
            rem = resp_headers.get("X-RateLimit-Remaining")
            reset_after = resp_headers.get("X-RateLimit-Reset-After")
            if rem is not None and reset_after is not None:
                with cls._LOCK:
                    cls._CHANNEL_BUCKETS[str(channel_id)] = {
                        "remaining": int(rem),
                        "reset_at": time.time() + float(reset_after),
                    }
        except Exception:
            pass

    @classmethod
    def set_channel_cooldown(cls, channel_id, wait_sec):
        if not channel_id:
            return
        with cls._LOCK:
            cls._CHANNEL_BUCKETS[str(channel_id)] = {
                "remaining": 0,
                "reset_at": time.time() + float(wait_sec),
            }

    @classmethod
    def get_channel_bucket_wait(cls, channel_id):
        with cls._LOCK:
            b = cls._CHANNEL_BUCKETS.get(str(channel_id))
            if not b:
                return 0.0
            now = time.time()
            if b["remaining"] <= 1 and now < b["reset_at"]:
                return max(0.20, (b["reset_at"] - now) + random.uniform(0.12, 0.35))
            return 0.0

    @classmethod
    def should_trigger_typing(cls, channel_id):
        now = time.time()
        with cls._LOCK:
            last_t = cls._LAST_TYPING_TS[str(channel_id)]
            if now - last_t >= random.uniform(22.0, 38.0):
                cls._LAST_TYPING_TS[str(channel_id)] = now
                return True
            return False


def append_antiband_tail(final_msg, platform="zalo", thread_id=""):
    if not final_msg:
        return final_msg
    if platform == "discord":
        return DiscordStealthAntiBanEngine.append_stealth_tail(final_msg, thread_id)
    return ZaloSmartAntiBanEngine.append_tail(final_msg, thread_id)


class AntiDieAllEngine:
    """Động cơ Anti-Die-All Thế Hệ Mới (Chống Chết Chùm & Điều Phối Nhịp Sinh Học Cho Zalo + Discord):
    - Phân tách độc lập ngưỡng an toàn cho Zalo (45 RPM) và Discord (38 RPM / 4 msgs per 5s bucket).
    - Khi bất kỳ tài khoản Discord hoặc Zalo nào gặp RateLimit (429 / Slowmode 20016 / WriteLimit 20028),
      tự động kích hoạt Phase-Shift Stagger cho toàn bộ các tài khoản đang chạy song song để Discord/Zalo
      không bao giờ quét trúng cụm IP/Tài khoản cùng lúc."""

    ZALO_RATELIMIT_CODES = ZaloSmartAntiBanEngine.RATELIMIT_CODES
    ZALO_AUTH_CODES = ZaloSmartAntiBanEngine.AUTH_CODES

    def __init__(self):
        self.lock = threading.Lock()
        self.state = defaultdict(lambda: {
            "platform": "zalo",
            "circuit": "CLOSED",
            "cooldown_until": 0.0,
            "fail_streak": 0,
            "ratelimit_streak": 0,
            "ok_total": 0,
            "fail_total": 0,
            "risk_score": 0.0,
            "last_error": "",
            "last_active": 0.0,
            "timestamps": deque(maxlen=120),
            "adaptive_delay_bonus": 0.0,
            "burst_counter": 0,
        })
        self.global_cooldown_until = 0.0

    def can_send(self, acc_id, max_rpm=44, channel_id=None, platform="zalo"):
        now = time.time()
        if platform == "discord" and channel_id:
            ch_wait = DiscordStealthAntiBanEngine.get_channel_bucket_wait(channel_id)
            if ch_wait > 0:
                return False, round(ch_wait, 2)

        with self.lock:
            if now < self.global_cooldown_until:
                return False, round(self.global_cooldown_until - now, 2)

            st = self.state[acc_id]
            st["platform"] = platform
            if st["circuit"] == "OPEN":
                if now < st["cooldown_until"]:
                    return False, round(st["cooldown_until"] - now, 2)
                else:
                    st["circuit"] = "HALF_OPEN"
                    st["adaptive_delay_bonus"] = max(0.65, st["adaptive_delay_bonus"])

            while st["timestamps"] and now - st["timestamps"][0] > 60.0:
                st["timestamps"].popleft()

            rpm_cap = 38 if platform == "discord" else max_rpm
            rpm = len(st["timestamps"])
            effective_limit = rpm_cap if st["circuit"] == "CLOSED" else max(14, rpm_cap // 2)
            if rpm >= effective_limit:
                wait_s = max(0.8, 60.0 - (now - st["timestamps"][0]) + random.uniform(0.25, 0.85))
                return False, round(wait_s, 2)

            # Bảo vệ ngưỡng 5 tin nhắn / 5 giây của Discord Channel Bucket
            if platform == "discord":
                burst_5s = sum(1 for t in st["timestamps"] if now - t <= 4.8)
                if burst_5s >= 4:
                    return False, round(random.uniform(0.85, 1.45), 2)

            recent_burst = sum(1 for t in st["timestamps"] if now - t <= 1.2)
            if recent_burst >= 4:
                return False, round(random.uniform(0.38, 0.78), 2)

            if st["timestamps"] and (now - st["timestamps"][-1]) < 0.22:
                return False, round(0.24 - (now - st["timestamps"][-1]), 2)

            return True, 0.0

    def get_adaptive_delay(self, acc_id, base_delay, antiband=True, platform="zalo", text_len=24):
        with self.lock:
            st = self.state[acc_id]
            bonus = st["adaptive_delay_bonus"]
            risk = st["risk_score"]
            st["burst_counter"] += 1
            b_cnt = st["burst_counter"]

        if not antiband:
            return max(0.22, float(base_delay) + bonus)

        if platform == "discord":
            d = float(base_delay) + bonus + (risk * 0.018)
            typing_sim = min(0.25, max(0.04, (text_len / 200.0) * 0.12))
            jitter = abs(random.gauss(0.14, 0.07))
            if b_cnt % 12 == 0:
                jitter += random.uniform(0.55, 1.25)
            elif b_cnt % 35 == 0:
                jitter += random.uniform(1.40, 2.60)
            return max(0.28, d + typing_sim + jitter)

        return ZaloSmartAntiBanEngine.compute_human_cadence_delay(
            base_delay, b_cnt, risk, bonus, text_len=text_len
        )

    def report_success(self, acc_id):
        now = time.time()
        with self.lock:
            st = self.state[acc_id]
            st["timestamps"].append(now)
            st["ok_total"] += 1
            st["last_active"] = now
            st["fail_streak"] = 0
            if st["circuit"] == "HALF_OPEN":
                st["circuit"] = "CLOSED"
                st["ratelimit_streak"] = max(0, st["ratelimit_streak"] - 1)
            st["adaptive_delay_bonus"] = max(0.0, st["adaptive_delay_bonus"] * 0.82 - 0.04)
            st["risk_score"] = max(0.0, st["risk_score"] - 2.0)

    def report_rate_limit(self, acc_id, retry_after=None, reason="Rate Limit 429", channel_id=None):
        now = time.time()
        if channel_id:
            DiscordStealthAntiBanEngine.set_channel_cooldown(channel_id, float(retry_after or 8.0))
        with self.lock:
            st = self.state[acc_id]
            st["ratelimit_streak"] += 1
            st["fail_total"] += 1
            st["last_error"] = sanitize_log_text(reason)
            streak = min(st["ratelimit_streak"], 6)
            base_cd = float(retry_after) if retry_after else (10.0 * (1.65 ** (streak - 1)))
            cooldown = min(220.0, max(5.0, base_cd + random.uniform(1.2, 4.2)))
            st["circuit"] = "OPEN"
            st["cooldown_until"] = now + cooldown
            st["adaptive_delay_bonus"] = min(4.5, st["adaptive_delay_bonus"] + 0.65)
            st["risk_score"] = min(100.0, st["risk_score"] + 22.0)

            # Kích hoạt Anti-Die-All Phase-Shift cho các tài khoản cùng nền tảng đang chạy
            plat = st["platform"]
            for other_id, other_st in self.state.items():
                if other_id != acc_id and other_st["platform"] == plat:
                    other_st["adaptive_delay_bonus"] = min(3.5, other_st["adaptive_delay_bonus"] + 0.35)

            open_count = sum(1 for v in self.state.values() if v["circuit"] == "OPEN" and v["cooldown_until"] > now)
            if open_count >= 1 and len(self.state) >= 2 and open_count >= len(self.state) * 0.5:
                self.global_cooldown_until = max(self.global_cooldown_until, now + random.uniform(2.5, 5.5))

    def report_error(self, acc_id, err_msg="", is_auth_error=False):
        now = time.time()
        with self.lock:
            st = self.state[acc_id]
            st["fail_streak"] += 1
            st["fail_total"] += 1
            st["last_error"] = sanitize_log_text(err_msg)
            if is_auth_error:
                st["circuit"] = "OPEN"
                st["cooldown_until"] = now + 180.0
                st["risk_score"] = min(100.0, st["risk_score"] + 40.0)
            elif st["fail_streak"] >= 3:
                backoff = min(140.0, 10.0 * (2 ** min(st["fail_streak"] - 3, 4)) + random.uniform(1.2, 3.5))
                st["circuit"] = "OPEN"
                st["cooldown_until"] = now + backoff
                st["adaptive_delay_bonus"] = min(3.5, st["adaptive_delay_bonus"] + 0.42)
                st["risk_score"] = min(100.0, st["risk_score"] + 14.0)
            else:
                st["risk_score"] = min(100.0, st["risk_score"] + 4.0)

    def get_snapshot(self, acc_id=None):
        now = time.time()
        with self.lock:
            if acc_id is not None:
                st = self.state[acc_id]
                while st["timestamps"] and now - st["timestamps"][0] > 60.0:
                    st["timestamps"].popleft()
                rem = max(0, int(st["cooldown_until"] - now)) if st["circuit"] == "OPEN" else 0
                return {
                    "circuit": st["circuit"] if rem > 0 or st["circuit"] != "OPEN" else "HALF_OPEN",
                    "cooldown_remaining": rem,
                    "ok_total": st["ok_total"],
                    "fail_total": st["fail_total"],
                    "rpm": len(st["timestamps"]),
                    "risk_score": round(st["risk_score"], 1),
                    "last_error": st["last_error"]
                }
            return {k: self.get_snapshot(k) for k in list(self.state.keys())}


HEALTH_MGR = AntiDieAllEngine()
refresh_owner_uids()

GROUP_MEMBERS_CACHE = {}
GROUP_CACHE_LOCK = threading.Lock()
KNOWN_GROUPS_BY_ACC = defaultdict(set)


# ============================================================
# CLIENT GIAO THỨC ZALO (ĐÃ FIX TRIỆT ĐỂ TAG THẬT BẰNG ENDPOINT /api/group/mention)
# ============================================================
class Zalo:
    def __init__(self, imei, cookies):
        self.imei = str(imei).strip()
        self.cookies_dict = cookies if isinstance(cookies, dict) else json.loads(cookies)
        self.s = requests.Session()
        adapter = HTTPAdapter(pool_connections=40, pool_maxsize=80, max_retries=2)
        self.s.mount("https://", adapter)
        self.s.mount("http://", adapter)
        self.s.headers.update(ZaloSmartAntiBanEngine.get_session_headers(self.imei))
        self.s.cookies.update(self.cookies_dict)
        self.secret_key = None
        self.uid = None
        self.send2me_id = None
        self.display_name = None
        self.zalo_name = None
        self.username = None
        self.ws_urls = []
        self._login()

    def _login(self):
        r = self.s.get(
            "https://wpa.chat.zalo.me/api/login/getLoginInfo",
            params={
                "imei": self.imei,
                "type": 30,
                "client_version": 645,
                "computer_name": "Web",
                "ts": int(time.time() * 1000)
            },
            timeout=15,
        )
        d = r.json()
        ud = d.get("data")
        if not isinstance(ud, dict):
            raise Exception("Phiên đăng nhập Zalo hết hạn hoặc Cookie không hợp lệ")
        self.uid = str(ud.get("uid") or ud.get("userId") or ud.get("send2me_id") or "")
        self.send2me_id = str(ud.get("send2me_id") or "")
        self.secret_key = ud.get("zpw_enk")
        self.display_name = ud.get("displayName") or ud.get("zaloName")
        self.zalo_name = ud.get("zaloName")
        self.username = ud.get("username")

        if self.uid:
            OWNER_UIDS_CACHE.add(self.uid)
        if self.send2me_id:
            OWNER_UIDS_CACHE.add(self.send2me_id)

        ws_candidates = []
        for k in ("zpw_ws", "ws", "websocket"):
            val = ud.get(k)
            if isinstance(val, list):
                ws_candidates.extend(val)
            elif isinstance(val, str) and val:
                ws_candidates.append(val)
        if not ws_candidates:
            ws_candidates = [
                "wss://ws1.chat.zalo.me",
                "wss://ws2.chat.zalo.me",
                "wss://ws3.chat.zalo.me",
                "wss://ws4.chat.zalo.me"
            ]
        self.ws_urls = ws_candidates

        if not self.secret_key:
            raise Exception("Không thể lấy khóa giải mã bảo mật (zpw_enk)")

    def _enc(self, params):
        key = base64.b64decode(self.secret_key)
        cipher = AES.new(key, AES.MODE_CBC, bytes(16))
        pt = json.dumps(params, ensure_ascii=False).encode("utf-8")
        pad = AES.block_size - len(pt) % AES.block_size
        pt += bytes([pad]) * pad
        return base64.b64encode(cipher.encrypt(pt)).decode()

    def _dec(self, enc):
        if not enc:
            return "{}"
        key = base64.b64decode(self.secret_key)
        cipher = AES.new(key, AES.MODE_CBC, bytes(16))
        raw = base64.b64decode(unquote(enc) if "%" in enc else enc)
        d = cipher.decrypt(raw)
        pad_len = d[-1]
        if 1 <= pad_len <= 16:
            d = d[:-pad_len]
        return d.decode("utf-8", "ignore")

    def groups(self):
        r = self.s.get(
            "https://tt-group-wpa.chat.zalo.me/api/group/getlg/v4",
            params={"zpw_ver": 645, "zpw_type": 30}, timeout=15,
        )
        dec = self._dec(r.json().get("data", ""))
        grid = json.loads(dec).get("data", {}).get("gridVerMap", {})
        all_gids = [str(g) for g in grid.keys()]
        for gid in all_gids:
            KNOWN_GROUPS_BY_ACC[self.uid].add(gid)

        out = []
        for chunk in [all_gids[i:i + 50] for i in range(0, len(all_gids), 50)]:
            try:
                enc = self._enc({"gridVerMap": json.dumps({gid: 0 for gid in chunk})})
                r_info = self.s.post(
                    "https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2",
                    params={"zpw_ver": 645, "zpw_type": 30},
                    data={"params": enc}, timeout=15,
                )
                dec_info = self._dec(r_info.json().get("data", ""))
                info_map = json.loads(dec_info).get("data", {}).get("gridInfoMap", {})
                for gid in chunk:
                    g_obj = info_map.get(gid) or {}
                    out.append({
                        "id": gid,
                        "name": g_obj.get("name") or f"Nhóm Zalo {gid[-6:]}",
                        "type": "group",
                        "members": g_obj.get("totalMember", "?")
                    })
            except Exception:
                for gid in chunk:
                    out.append({"id": gid, "name": f"Nhóm Zalo {gid[-6:]}", "type": "group", "members": "?"})
        return out

    def get_grid_ver_map(self):
        r = self.s.get(
            "https://tt-group-wpa.chat.zalo.me/api/group/getlg/v4",
            params={"zpw_ver": 645, "zpw_type": 30}, timeout=12,
        )
        dec = self._dec(r.json().get("data", ""))
        gmap = json.loads(dec).get("data", {}).get("gridVerMap", {})
        for gid in gmap:
            KNOWN_GROUPS_BY_ACC[self.uid].add(str(gid))
        return gmap

    def friends(self):
        try:
            enc = self._enc({"offset": 0, "count": 500})
            r = self.s.post(
                "https://profile-wpa.chat.zalo.me/api/social/friend/getfriends",
                params={"zpw_ver": 645, "zpw_type": 30},
                data={"params": enc}, timeout=15,
            )
            dec = self._dec(r.json()["data"])
            d = json.loads(dec).get("data", [])
            users = d if isinstance(d, list) else d.get("users", [])
            res = []
            for u in users:
                uid = str(u.get("userId") or "").strip()
                if not uid:
                    continue
                uname = u.get("displayName") or u.get("zaloName") or f"Bạn_{uid[-6:]}"
                GLOBAL_USER_NAME_CACHE[uid] = uname
                res.append({"id": uid, "name": uname, "type": "user"})
            return res
        except Exception:
            return []

    def get_members_full(self, gid, use_cache=True):
        gid_str = str(gid)
        if use_cache:
            with GROUP_CACHE_LOCK:
                c = GROUP_MEMBERS_CACHE.get(gid_str)
                if c and time.time() - c["ts"] < 180:
                    return c["members"]

        try:
            self.get_recent_group_messages(gid_str)
        except Exception:
            pass

        enc = self._enc({"gridVerMap": json.dumps({gid_str: 0})})
        r = self.s.post(
            "https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2",
            params={"zpw_ver": 645, "zpw_type": 30},
            data={"params": enc}, timeout=20,
        )
        dec = self._dec(r.json().get("data", ""))
        info = json.loads(dec).get("data", {}).get("gridInfoMap", {}).get(gid_str, {})

        members_dict = {}
        for list_key in ("currentMems", "memInfoList", "members", "updateMems"):
            mem_list = info.get(list_key, [])
            if isinstance(mem_list, list):
                for m in mem_list:
                    if isinstance(m, dict):
                        uid = str(m.get("userId") or m.get("id") or m.get("uid") or "").strip()
                        name = (m.get("dName") or m.get("displayName") or m.get("zaloName") or m.get("name") or "").strip()
                        if uid and name:
                            members_dict[uid] = name
                            GLOBAL_USER_NAME_CACHE[uid] = name

        mem_ver_list = info.get("memVerList", [])
        uids = [str(m).split("_")[0] for m in mem_ver_list if m]
        for extra_k in ("creatorId",):
            cid = str(info.get(extra_k) or "").strip()
            if cid and cid not in uids:
                uids.append(cid)
        for aid in (info.get("adminIds") or []):
            s_aid = str(aid).strip()
            if s_aid and s_aid not in uids:
                uids.append(s_aid)
        for k_uid in members_dict:
            if k_uid not in uids:
                uids.append(k_uid)

        for u in uids:
            if u not in members_dict and u in GLOBAL_USER_NAME_CACHE:
                members_dict[u] = GLOBAL_USER_NAME_CACHE[u]

        missing_uids = [u for u in uids if u not in members_dict]

        if missing_uids:
            for chunk in [missing_uids[i:i + 50] for i in range(0, len(missing_uids), 50)]:
                try:
                    enc_prof = self._enc({
                        "phonebook_version": int(time.time()),
                        "friend_pversion_map": [f"{u}_0" for u in chunk],
                        "avatar_size": 120,
                        "language": "vi",
                        "show_online_status": 1,
                        "imei": self.imei
                    })
                    r_prof = self.s.post(
                        "https://profile-wpa.chat.zalo.me/api/social/friend/getprofiles/v2",
                        params={"zpw_ver": 645, "zpw_type": 30},
                        data={"params": enc_prof},
                        timeout=12,
                    )
                    rj_prof = r_prof.json()
                    if rj_prof.get("data"):
                        dec_prof = json.loads(self._dec(rj_prof["data"])).get("data", {})
                        changed = dec_prof.get("changed_profiles", {}) if isinstance(dec_prof, dict) else {}
                        for uid in chunk:
                            p = changed.get(uid) or changed.get(f"{uid}_0") or {}
                            pname = (p.get("displayName") or p.get("zaloName") or p.get("dName") or p.get("username") or "").strip()
                            if pname:
                                members_dict[uid] = pname
                                GLOBAL_USER_NAME_CACHE[uid] = pname
                except Exception:
                    pass

        still_missing = [u for u in uids if u not in members_dict]
        if still_missing:
            for chunk in [still_missing[i:i + 50] for i in range(0, len(still_missing), 50)]:
                try:
                    enc2 = self._enc({"grid": gid_str, "userIds": chunk, "friendId": chunk})
                    r2 = self.s.post(
                        "https://tt-group-wpa.chat.zalo.me/api/group/getuserinfo",
                        params={"zpw_ver": 645, "zpw_type": 30},
                        data={"params": enc2}, timeout=12,
                    )
                    dec2 = self._dec(r2.json().get("data", ""))
                    profiles_data = json.loads(dec2).get("data", {})
                    profiles = profiles_data.get("profiles", {}) if isinstance(profiles_data, dict) else {}
                    if not profiles and isinstance(profiles_data, dict):
                        profiles = profiles_data
                    for uid in chunk:
                        p = profiles.get(uid) or profiles.get(f"{uid}_0") or {}
                        if isinstance(p, dict):
                            pname = (p.get("displayName") or p.get("zaloName") or p.get("dName") or p.get("username") or "").strip()
                            if pname:
                                members_dict[uid] = pname
                                GLOBAL_USER_NAME_CACHE[uid] = pname
                except Exception:
                    pass

        out = []
        for uid in uids:
            real_name = members_dict.get(uid) or GLOBAL_USER_NAME_CACHE.get(uid) or f"Thành viên {uid[-4:]}"
            out.append({"id": str(uid), "uid": str(uid), "name": real_name})

        with GROUP_CACHE_LOCK:
            GROUP_MEMBERS_CACHE[gid_str] = {"ts": time.time(), "members": out}
        return out

    def get_recent_group_messages(self, gid):
        for ep in (
            "https://tt-group-wpa.chat.zalo.me/api/group/getrecentv2",
            "https://tt-group-wpa.chat.zalo.me/api/group/getrecent",
            "https://tt-group-wpa.chat.zalo.me/api/group/history",
        ):
            try:
                enc = self._enc({"grid": str(gid), "groupId": str(gid), "imed": 0, "count": 20})
                r = self.s.post(
                    ep,
                    params={"zpw_ver": 645, "zpw_type": 30},
                    data={"params": enc},
                    timeout=8,
                )
                rj = r.json()
                if rj.get("data"):
                    dec = self._dec(rj["data"])
                    parsed = json.loads(dec)
                    data_obj = parsed.get("data") if isinstance(parsed, dict) else {}
                    if isinstance(data_obj, dict):
                        msgs = data_obj.get("groupMsgs") or data_obj.get("msgs") or []
                        if msgs:
                            for m in msgs:
                                if isinstance(m, dict):
                                    u_f = str(m.get("uidFrom") or "").strip()
                                    d_n = str(m.get("dName") or "").strip()
                                    if u_f and d_n and u_f != "0":
                                        GLOBAL_USER_NAME_CACHE[u_f] = d_n
                            return msgs
            except Exception:
                continue
        return []

    def _pick_distinct_zcode(self, color_mode, fixed_color, step_index, prev_zcode=None):
        if color_mode == "none":
            return None
        if color_mode == "fixed" and fixed_color:
            return ZALO_COLOR_MAP.get(fixed_color, "db342e")
        if color_mode == "random":
            candidates = [c for c in ZALO_NATIVE_ZCODES if c != prev_zcode]
            return random.choice(candidates)
        chosen = ZALO_NATIVE_ZCODES[step_index % len(ZALO_NATIVE_ZCODES)]
        if chosen == prev_zcode:
            chosen = ZALO_NATIVE_ZCODES[(step_index + 1) % len(ZALO_NATIVE_ZCODES)]
        return chosen

    def build_colored_message_with_vip_icons(
        self, raw_text, color_mode="rainbow", fixed_color="red",
        is_heading=True, color_offset=0, antiband=True,
        use_emoji=True, icon_count=3, strip_line_num=False
    ):
        raw_clean = clean_corrupted_shortcuts(raw_text)
        lines = raw_clean.split("\n")

        core_lines = []
        collected_tail_icons = []
        styles = []
        current_u16_pos = 0
        active_line_idx = color_offset
        prev_line_zcode = None
        first_color = "db342e"

        for ln in lines:
            stripped = ln.strip()
            if not stripped:
                core_lines.append("")
                current_u16_pos += 1
                continue

            force_line_heading = False
            if stripped.startswith("#"):
                stripped = re.sub(r"^#+\s*", "", stripped).strip() or stripped
                force_line_heading = True

            if strip_line_num:
                stripped = strip_leading_line_number(stripped)

            tokens = stripped.split(" ")
            line_tail_icons = []
            while tokens and _is_emoji_or_zalo_shortcut_token(tokens[-1]):
                tk = tokens.pop()
                if tk in ZALO_ICON_VIP:
                    line_tail_icons.insert(0, tk)
                elif tk in LEGACY_SHORTCUT_TO_ICON_MAP:
                    line_tail_icons.insert(0, LEGACY_SHORTCUT_TO_ICON_MAP[tk])
                else:
                    line_tail_icons.insert(0, get_icon_hard(line_tail_icons))

            core_text = " ".join(tokens).strip()
            if not core_text and line_tail_icons:
                core_text = " ".join(line_tail_icons)
                line_tail_icons = []

            if line_tail_icons:
                collected_tail_icons.extend(line_tail_icons)

            core_lines.append(core_text)
            core_u16_len = utf16_len(core_text)
            use_big_font = is_heading or force_line_heading

            if color_mode == "word_rainbow":
                words = core_text.split(" ")
                w_offset = current_u16_pos
                prev_w_zcode = prev_line_zcode
                w_step = active_line_idx
                for w in words:
                    w_len = utf16_len(w)
                    if w_len > 0:
                        zcode = self._pick_distinct_zcode("rainbow", fixed_color, w_step, prev_w_zcode)
                        if w_step == color_offset and zcode:
                            first_color = zcode
                        prev_w_zcode = zcode
                        w_step += 1
                        st_parts = ["b"]
                        if use_big_font:
                            st_parts.append("f_18")
                        if zcode:
                            st_parts.append(f"c_{zcode}")
                        styles.append({
                            "start": w_offset,
                            "len": w_len,
                            "st": ",".join(st_parts)
                        })
                    w_offset += w_len + 1
                prev_line_zcode = prev_w_zcode
                active_line_idx += 1
            else:
                zcode = self._pick_distinct_zcode(color_mode, fixed_color, active_line_idx, prev_line_zcode)
                if active_line_idx == color_offset and zcode:
                    first_color = zcode
                prev_line_zcode = zcode
                active_line_idx += 1

                st_parts = []
                if use_big_font:
                    st_parts.extend(["b", "f_18"])
                elif color_mode != "none":
                    st_parts.append("b")
                if zcode:
                    st_parts.append(f"c_{zcode}")

                if st_parts and core_u16_len > 0:
                    styles.append({
                        "start": current_u16_pos,
                        "len": core_u16_len,
                        "st": ",".join(st_parts)
                    })

            current_u16_pos += core_u16_len + 1

        core_msg = "\n".join(core_lines)
        tail_icon_str = ""
        if use_emoji and icon_count > 0:
            if collected_tail_icons:
                tail_icon_str = " ".join(collected_tail_icons[:max(icon_count, 3)])
            else:
                tail_icon_str = build_unique_zalo_icons(icon_count)
        elif collected_tail_icons:
            tail_icon_str = " ".join(collected_tail_icons[:3])

        return core_msg, styles, first_color, tail_icon_str

    def attach_mentions_real_zalo(self, core_msg, mentions=None, tag_all=False, group_id=None):
        """Gắn Tag Thật 100% chuẩn giao thức Zalo Group (`/api/group/mention`):
        - Tính chính xác vị trí `pos` và độ dài `len` theo UTF-16LE code units.
        - Trả về `final` và mảng `m_arr` chuẩn `[{"pos": pos, "len": len, "uid": str(uid), "type": 0}]`."""
        final = core_msg if core_msg else ""
        m_arr = []

        if tag_all:
            tag_token = "@All"
            idx_existing = final.find("@All")
            if idx_existing != -1:
                pos = utf16_len(final[:idx_existing])
                t_len = utf16_len(tag_token)
            else:
                sep = " " if (final and not final.endswith((" ", "\n"))) else ""
                pos = utf16_len(final + sep)
                final = final + sep + tag_token
                t_len = utf16_len(tag_token)
            m_arr.append({
                "pos": int(pos),
                "len": int(t_len),
                "uid": "-1",
                "type": 1
            })

        if mentions:
            seen_uids = set()
            for m in mentions:
                if not isinstance(m, dict):
                    continue
                uid = str(m.get("uid") or m.get("id") or m.get("userId") or "").strip()
                if not uid or uid in ("0",) or uid in seen_uids:
                    continue
                if uid == "-1":
                    if not any(x["uid"] == "-1" for x in m_arr):
                        sep = " " if (final and not final.endswith((" ", "\n"))) else ""
                        pos = utf16_len(final + sep)
                        final = final + sep + "@All"
                        m_arr.append({"pos": int(pos), "len": 4, "uid": "-1", "type": 1})
                    continue

                seen_uids.add(uid)

                raw_name = str(m.get("name") or m.get("dName") or m.get("displayName") or "").strip().lstrip("@")
                if not raw_name or raw_name.startswith(("Thành viên ", "Người dùng ", "User_")):
                    if uid in GLOBAL_USER_NAME_CACHE:
                        raw_name = GLOBAL_USER_NAME_CACHE[uid]
                    elif group_id:
                        try:
                            mems = self.get_members_full(group_id, use_cache=True)
                            fm = next((x for x in mems if str(x.get("uid") or x.get("id")) == uid), None)
                            if fm and fm.get("name"):
                                raw_name = fm["name"]
                        except Exception:
                            pass

                name = raw_name.split(" (")[0].strip() if " (" in raw_name else raw_name.strip()
                if not name:
                    name = f"User_{uid[-4:]}"

                tag_token = f"@{name}"
                existing_idx = final.find(tag_token)
                if existing_idx != -1:
                    pos = utf16_len(final[:existing_idx])
                    t_len = utf16_len(tag_token)
                else:
                    sep = " " if (final and not final.endswith((" ", "\n"))) else ""
                    pos = utf16_len(final + sep)
                    final = final + sep + tag_token
                    t_len = utf16_len(tag_token)

                m_arr.append({
                    "pos": int(pos),
                    "len": int(t_len),
                    "uid": str(uid),
                    "type": 0
                })

        return final, m_arr

    def _send_raw_payload(self, final_msg, thread_id, is_group, m_arr, styles, first_color="db342e"):
        """Gửi gói tin mã hóa tới Zalo WPA v645:
        ĐẶC BIỆT QUAN TRỌNG:
        - Khi gửi tin nhắn nhóm CÓ TAG (`is_group and m_arr`), Zalo Web WPA bắt buộc dùng endpoint riêng:
          `https://tt-group-wpa.chat.zalo.me/api/group/mention` (vì `/api/group/sendmsg` chỉ là endpoint văn bản thường,
          nó bỏ qua `mentionInfo` khiến `@Tên` chỉ hiện ra như chữ trắng thường!).
        - Nhờ gọi đúng `/api/group/mention`, Zalo kích hoạt 100% thẻ Tag Xanh Dương và thông báo rung máy!"""
        if is_group:
            url = (
                "https://tt-group-wpa.chat.zalo.me/api/group/mention"
                if m_arr
                else "https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
            )
        else:
            url = "https://tt-chat2-wpa.chat.zalo.me/api/message/sms"

        client_id = int(time.time() * 1000) + random.randint(1, 99)
        register_bot_sent_message(client_id=client_id, text=final_msg)

        pl = {
            "message": final_msg,
            "clientId": client_id,
            "imei": self.imei,
            "ttl": 0,
        }

        if is_group:
            pl["visibility"] = 0
            pl["grid"] = str(thread_id)
            if m_arr:
                mention_json = json.dumps(m_arr, separators=(",", ":"), ensure_ascii=False)
                pl["mentionInfo"] = mention_json
        else:
            pl["toid"] = str(thread_id)

        if styles and not (is_group and m_arr):
            params_obj = {"styles": styles, "ver": 0}
            params_json = json.dumps(params_obj, separators=(",", ":"), ensure_ascii=False)
            pl["textProperties"] = params_json
            pl["params"] = params_json
            if first_color:
                pl["msgColor"] = first_color

        enc = self._enc(pl)
        r = self.s.post(
            url,
            params={"zpw_ver": 645, "zpw_type": 30},
            data={"params": enc},
            timeout=15
        )
        try:
            rj = r.json()
            if rj.get("data"):
                dec = json.loads(self._dec(rj["data"]))
                if isinstance(dec, dict):
                    sent_mid = (dec.get("data") or {}).get("msgId") or dec.get("msgId")
                    if sent_mid:
                        register_bot_sent_message(msg_id=sent_mid, client_id=client_id, text=final_msg)
        except Exception:
            pass
        return r

    def send_adv(self, raw_text, thread_id, color_mode="rainbow", fixed_color="red",
                 is_group=True, mentions=None, tag_all=False, is_heading=True,
                 color_offset=0, antiband=True, use_emoji=False, icon_count=0,
                 auto_retry_thread_type=False, strip_line_num=False):
        eff_mentions = list(mentions) if mentions else []
        eff_tag_all = bool(tag_all)
        working_text = raw_text

        if eff_mentions or eff_tag_all:
            is_group = True

        if is_group and "@" in str(raw_text or ""):
            stripped_txt, auto_m, auto_all = extract_trailing_tags_and_resolve(
                raw_text, incoming_mentions=None, zalo_client=self, group_id=thread_id
            )
            if auto_m or auto_all:
                working_text = stripped_txt if stripped_txt else raw_text
                if auto_all:
                    eff_tag_all = True
                for am in auto_m:
                    if not any(str(x.get("uid") or x.get("id")) == str(am["uid"]) for x in eff_mentions):
                        eff_mentions.append(am)

        core_msg, styles, first_color, tail_icon_str = self.build_colored_message_with_vip_icons(
            working_text,
            color_mode=color_mode,
            fixed_color=fixed_color,
            is_heading=is_heading,
            color_offset=color_offset,
            antiband=antiband,
            use_emoji=use_emoji,
            icon_count=icon_count,
            strip_line_num=strip_line_num
        )

        msg_with_tags, m_arr = self.attach_mentions_real_zalo(
            core_msg,
            mentions=(eff_mentions if is_group else None),
            tag_all=(eff_tag_all if is_group else False),
            group_id=(thread_id if is_group else None)
        )

        if tail_icon_str:
            sep_ic = " " if (msg_with_tags and not msg_with_tags.endswith(" ")) else ""
            final_msg = f"{msg_with_tags}{sep_ic}{tail_icon_str}"
        else:
            final_msg = msg_with_tags

        if antiband:
            final_msg = ZaloSmartAntiBanEngine.append_tail(final_msg, thread_id=str(thread_id))

        r = self._send_raw_payload(final_msg, thread_id, is_group, m_arr, styles, first_color=first_color)

        if r.status_code == 429:
            raise Exception("429:RateLimit:30")

        try:
            resp_json = r.json()
            err_code = resp_json.get("error_code", 0)
            inner_err = 0
            if resp_json.get("data"):
                try:
                    dec_resp = json.loads(self._dec(resp_json["data"]))
                    if isinstance(dec_resp, dict):
                        inner_err = dec_resp.get("error_code", 0)
                except Exception:
                    pass

            if auto_retry_thread_type and (err_code != 0 or inner_err != 0):
                r2 = self._send_raw_payload(final_msg, thread_id, not is_group, [], styles, first_color=first_color)
                return r2

            if err_code in AntiDieAllEngine.ZALO_RATELIMIT_CODES or inner_err in AntiDieAllEngine.ZALO_RATELIMIT_CODES:
                code_hit = err_code or inner_err
                raise Exception(f"429:RateLimit:25:ZaloCode_{code_hit}")
            if err_code in AntiDieAllEngine.ZALO_AUTH_CODES:
                self._login()
                raise Exception(f"AuthError:ZaloCode_{err_code}")
        except Exception as check_ex:
            if "429:RateLimit" in str(check_ex) or "AuthError" in str(check_ex):
                raise check_ex

        return r


# ============================================================
# BỘ PHÂN TÍCH & TỰ ĐỘNG KHỚP TAG THẬT 100% CHUẨN KHUNG CHAT ZALO & DISCORD
# ============================================================
def _clean_alnum_words(s):
    if not s:
        return ""
    no_acc = remove_vn_accents(s)
    return re.sub(r"[^a-z0-9\s]+", " ", no_acc).strip()


def _smart_match_member_by_query(query_str, members, zalo_client=None, group_id=None):
    q_raw = (query_str or "").strip().lstrip("@").strip("[]").strip()
    if not q_raw:
        return None

    if q_raw.isdigit() and len(q_raw) >= 8:
        if members:
            by_uid = next((m for m in members if str(m.get("uid") or m.get("id")) == q_raw), None)
            if by_uid:
                return by_uid
        name_cached = GLOBAL_USER_NAME_CACHE.get(q_raw) or f"User_{q_raw[-4:]}"
        return {"id": q_raw, "uid": q_raw, "name": name_cached}

    def _search_in_list(mem_list):
        if not mem_list:
            return None
        valid_mems = [
            m for m in mem_list
            if m.get("name") and not str(m["name"]).startswith(("Thành viên ", "Người dùng "))
        ]
        q_low = q_raw.lower()
        q_no_acc = remove_vn_accents(q_raw)
        q_alnum = _clean_alnum_words(q_raw)
        q_tokens = [t for t in q_alnum.split() if len(t) >= 2]

        for m in valid_mems:
            n_low = m["name"].strip().lower()
            n_no_acc = remove_vn_accents(m["name"])
            n_alnum = _clean_alnum_words(m["name"])
            if q_low == n_low or (q_no_acc and q_no_acc == n_no_acc) or (q_alnum and q_alnum == n_alnum):
                return m

        sorted_mems = sorted(valid_mems, key=lambda x: len(x.get("name", "")), reverse=True)
        for m in sorted_mems:
            n_low = m["name"].strip().lower()
            n_no_acc = remove_vn_accents(m["name"])
            n_alnum = _clean_alnum_words(m["name"])
            if n_low.startswith(q_low) or n_low.endswith(q_low) or q_low.startswith(n_low):
                return m
            if len(q_no_acc) >= 2 and (n_no_acc.startswith(q_no_acc) or n_no_acc.endswith(q_no_acc) or q_no_acc.startswith(n_no_acc)):
                return m
            if len(q_alnum) >= 3 and len(n_alnum) >= 3 and (q_alnum in n_alnum or n_alnum in q_alnum):
                return m

        for m in sorted_mems:
            n_low = m["name"].strip().lower()
            n_no_acc = remove_vn_accents(m["name"])
            n_alnum = _clean_alnum_words(m["name"])
            if q_low in n_low or (len(q_no_acc) >= 2 and q_no_acc in n_no_acc):
                return m
            if q_tokens and all(tk in n_alnum for tk in q_tokens):
                return m
        return None

    found = _search_in_list(members)
    if found:
        return found

    if zalo_client and group_id:
        try:
            fresh_members = zalo_client.get_members_full(group_id, use_cache=False)
            found = _search_in_list(fresh_members)
            if found:
                return found
            others = [m for m in fresh_members if str(m.get("id") or m.get("uid")) != str(zalo_client.uid)]
            if len(others) == 1:
                uid_other = str(others[0].get("id") or others[0].get("uid"))
                GLOBAL_USER_NAME_CACHE[uid_other] = q_raw
                return {"id": uid_other, "uid": uid_other, "name": q_raw}
        except Exception:
            pass

    return None


def extract_trailing_tags_and_resolve(
    raw_text, incoming_mentions=None, zalo_client=None, group_id=None,
    prefix_u16_offset=0, discord_client=None, discord_channel_id=None, full_original_msg=None
):
    if not raw_text and not incoming_mentions:
        return "", [], False

    text = (raw_text or "").strip()
    resolved_mentions = []
    tag_all = False

    members = []
    if zalo_client and group_id:
        try:
            members = zalo_client.get_members_full(group_id, use_cache=True)
        except Exception:
            members = []
    elif discord_client and discord_channel_id:
        try:
            members = discord_client.get_box_members(discord_channel_id)
        except Exception:
            members = []

    if incoming_mentions and isinstance(incoming_mentions, list):
        sorted_m = sorted(incoming_mentions, key=lambda x: int(x.get("pos", x.get("start", 0))), reverse=True)
        for m in sorted_m:
            if not isinstance(m, dict):
                continue
            uid = str(m.get("uid") or m.get("id") or m.get("userId") or "").strip()
            mtype = int(m.get("type", 0))
            raw_pos = int(m.get("pos", m.get("start", m.get("offset", -1))))
            mlen = int(m.get("len", m.get("length", 0)))

            adj_pos = (raw_pos - prefix_u16_offset) if (raw_pos >= prefix_u16_offset and prefix_u16_offset > 0) else raw_pos

            if uid == "-1" or mtype == 1:
                tag_all = True
                if adj_pos >= 0 and mlen > 0:
                    try:
                        u16 = text.encode("utf-16-le")
                        if (adj_pos + mlen) * 2 <= len(u16):
                            text = (u16[:adj_pos * 2] + u16[(adj_pos + mlen) * 2:]).decode("utf-16-le", errors="ignore").strip()
                    except Exception:
                        pass
                continue

            if uid and uid != "0":
                m_name = str(m.get("name") or m.get("dName") or m.get("global_name") or m.get("username") or "").strip().lstrip("@")

                if full_original_msg and raw_pos >= 0 and mlen > 0:
                    try:
                        orig_u16 = full_original_msg.encode("utf-16-le")
                        if (raw_pos + mlen) * 2 <= len(orig_u16):
                            sub_orig = orig_u16[raw_pos * 2:(raw_pos + mlen) * 2].decode("utf-16-le", errors="ignore").strip()
                            if sub_orig.startswith("@"):
                                extracted_orig = sub_orig.lstrip("@").strip()
                                if extracted_orig:
                                    m_name = extracted_orig
                                idx_in_txt = text.rfind(sub_orig)
                                if idx_in_txt != -1:
                                    text = (text[:idx_in_txt] + text[idx_in_txt + len(sub_orig):]).strip()
                    except Exception:
                        pass

                if adj_pos >= 0 and mlen > 0:
                    try:
                        u16_bytes = text.encode("utf-16-le")
                        if (adj_pos + mlen) * 2 <= len(u16_bytes):
                            sub = u16_bytes[adj_pos * 2:(adj_pos + mlen) * 2].decode("utf-16-le", errors="ignore").strip()
                            if sub.startswith("@"):
                                extracted_label = sub.lstrip("@").strip()
                                if extracted_label:
                                    m_name = extracted_label
                                text = (u16_bytes[:adj_pos * 2] + u16_bytes[(adj_pos + mlen) * 2:]).decode("utf-16-le", errors="ignore").strip()
                            else:
                                at_idx = text.rfind("@")
                                if at_idx != -1:
                                    at_u16 = utf16_len(text[:at_idx])
                                    sub2 = u16_bytes[at_u16 * 2:(at_u16 + mlen) * 2].decode("utf-16-le", errors="ignore").strip()
                                    if sub2.startswith("@"):
                                        m_name = sub2.lstrip("@").strip() or m_name
                                        text = (u16_bytes[:at_u16 * 2] + u16_bytes[(at_u16 + mlen) * 2:]).decode("utf-16-le", errors="ignore").strip()
                    except Exception:
                        pass

                if members:
                    found_mem = next((x for x in members if str(x.get("id") or x.get("uid")) == uid), None)
                    if found_mem and found_mem.get("name") and not str(found_mem["name"]).startswith(("Người dùng ", "Thành viên ")):
                        if not m_name or len(found_mem["name"]) >= len(m_name):
                            m_name = found_mem["name"]

                if (not m_name or m_name.startswith(("Người dùng ", "Thành viên "))) and zalo_client and group_id:
                    try:
                        fresh_mems = zalo_client.get_members_full(group_id, use_cache=False)
                        fm2 = next((x for x in fresh_mems if str(x.get("id") or x.get("uid")) == uid), None)
                        if fm2 and fm2.get("name"):
                            m_name = fm2["name"]
                    except Exception:
                        pass

                if m_name and not m_name.startswith(("Người dùng ", "Thành viên ")):
                    GLOBAL_USER_NAME_CACHE[uid] = m_name
                elif uid in GLOBAL_USER_NAME_CACHE:
                    m_name = GLOBAL_USER_NAME_CACHE[uid]

                if not any(x["uid"] == uid for x in resolved_mentions):
                    resolved_mentions.append({
                        "uid": uid,
                        "id": uid,
                        "name": m_name or f"User_{uid[-4:]}"
                    })

    bracket_matches = list(re.finditer(r"@\[([^\]]+)\]", text))
    if bracket_matches:
        for bm in reversed(bracket_matches):
            b_query = bm.group(1).strip()
            if b_query.lower() in ("all", "tất cả", "tat ca", "everyone", "here"):
                tag_all = True
                text = (text[:bm.start()] + text[bm.end():]).strip()
            else:
                matched_m = _smart_match_member_by_query(b_query, members, zalo_client=zalo_client, group_id=group_id)
                if matched_m:
                    muid = str(matched_m.get("uid") or matched_m.get("id"))
                    if not any(x["uid"] == muid for x in resolved_mentions):
                        resolved_mentions.append({"uid": muid, "id": muid, "name": matched_m["name"]})
                    text = (text[:bm.start()] + text[bm.end():]).strip()

    discord_tag_matches = list(re.finditer(r"<@!?(\d+)>", text))
    if discord_tag_matches:
        for dm in reversed(discord_tag_matches):
            d_uid = dm.group(1)
            d_name = GLOBAL_USER_NAME_CACHE.get(d_uid)
            if not d_name and members:
                f_m = next((x for x in members if str(x.get("id")) == d_uid), None)
                if f_m:
                    d_name = f_m.get("name")
            if not any(x["uid"] == d_uid for x in resolved_mentions):
                resolved_mentions.append({"uid": d_uid, "id": d_uid, "name": d_name or f"User_{d_uid[-4:]}"})
            text = (text[:dm.start()] + text[dm.end():]).strip()

    all_pattern = re.compile(r"(?:\s+|^)(?:@all|@tất\s*cả|@tat\s*ca|@mọi\s*người|@everyone|@here)\s*$", re.IGNORECASE)
    while True:
        m_all = all_pattern.search(text)
        if not m_all:
            break
        tag_all = True
        text = text[:m_all.start()].rstrip()

    if "@" in text:
        if members:
            sorted_members = sorted(members, key=lambda x: len(x.get("name", "")), reverse=True)
            changed = True
            while changed:
                changed = False
                text_low = text.lower().rstrip()
                text_no_acc = remove_vn_accents(text_low)
                for mem in sorted_members:
                    mname = (mem.get("name") or "").strip()
                    if not mname or mname.startswith(("Người dùng ", "Thành viên ")):
                        continue
                    token_low = "@" + mname.lower()
                    token_no_acc = "@" + remove_vn_accents(mname)
                    matched_len = 0
                    if text_low.endswith(token_low):
                        matched_len = len(token_low)
                    elif len(token_no_acc) > 2 and text_no_acc.endswith(token_no_acc):
                        matched_len = len(token_low)

                    if matched_len > 0:
                        cut_pos = len(text) - matched_len
                        if cut_pos >= 0 and (cut_pos == 0 or text[cut_pos - 1].isspace()):
                            m_uid = str(mem.get("id") or mem.get("uid"))
                            if not any(x["uid"] == m_uid for x in resolved_mentions):
                                resolved_mentions.append({
                                    "uid": m_uid,
                                    "id": m_uid,
                                    "name": mname
                                })
                            text = text[:cut_pos].rstrip()
                            changed = True
                            break

        tail_at_match = re.search(r"(?:\s+|^)@([^\s@][^@]{0,45})$", text)
        if tail_at_match:
            partial_raw = tail_at_match.group(1).strip()
            partial_low = partial_raw.lower()
            if partial_low in ("all", "tất cả", "tat ca", "everyone", "here"):
                tag_all = True
                text = text[:tail_at_match.start()].rstrip()
            else:
                matched_mem = _smart_match_member_by_query(
                    partial_raw, members, zalo_client=zalo_client, group_id=group_id
                )
                if matched_mem:
                    m_uid = str(matched_mem.get("id") or matched_mem.get("uid"))
                    real_label = partial_raw if len(partial_raw) >= len(matched_mem.get("name", "")) else matched_mem["name"]
                    if real_label.startswith(("Người dùng ", "Thành viên ")):
                        real_label = partial_raw
                    existing = next((x for x in resolved_mentions if x["uid"] == m_uid), None)
                    if existing:
                        if len(real_label) > len(existing.get("name", "")):
                            existing["name"] = real_label
                    else:
                        resolved_mentions.append({
                            "uid": m_uid,
                            "id": m_uid,
                            "name": real_label
                        })
                    text = text[:tail_at_match.start()].rstrip()
                elif resolved_mentions:
                    if len(resolved_mentions) == 1 and len(partial_raw) > len(resolved_mentions[0]["name"]):
                        resolved_mentions[0]["name"] = partial_raw
                    text = text[:tail_at_match.start()].rstrip()

    for rm in resolved_mentions:
        rname = rm.get("name", "").strip()
        if rname and text.lower().endswith("@" + rname.lower()):
            text = text[:-(len(rname) + 1)].rstrip()

    resolved_mentions.reverse()
    return text.strip(), resolved_mentions, tag_all


# ============================================================
# HỆ THỐNG REG & KHỞI TẠO PHIÊN DISCORD STEALTH CHỐNG QUÉT 100%
# ============================================================
DISCORD_TOKEN_REGEX = re.compile(r"([A-Za-z0-9_\-]{23,28}\.[A-Za-z0-9_\-]{6,7}\.[A-Za-z0-9_\-]{27,45}|mfa\.[A-Za-z0-9_\-]{80,})")


def extract_discord_tokens_from_reg_or_raw(raw_input):
    if not raw_input:
        return []
    txt = str(raw_input).strip()
    found = []
    for m in DISCORD_TOKEN_REGEX.finditer(txt):
        tk = m.group(1).strip()
        if tk and tk not in found:
            found.append(tk)
    if not found and "|" in txt:
        for part in txt.split("|"):
            p = part.strip().strip('"').strip("'")
            if len(p) >= 50 and "." in p and " " not in p:
                found.append(p)
    if not found and ":" in txt:
        for part in txt.split(":"):
            p = part.strip().strip('"').strip("'")
            if len(p) >= 50 and "." in p and " " not in p:
                found.append(p)
    if not found and len(txt) >= 50 and " " not in txt:
        found.append(txt.strip('"').strip("'"))
    return found


def warmup_discord_stealth_token(token):
    dc = DiscordBot(token, is_bot=False)
    try:
        r_exp = dc.s.get("https://discord.com/api/v10/experiments", timeout=8)
        if r_exp.status_code == 200:
            fp = r_exp.json().get("fingerprint")
            if fp:
                DiscordStealthAntiBanEngine._FINGERPRINT_CACHE[str(dc.token)[:18]] = fp
                dc._apply_headers()
    except Exception:
        pass

    if dc.check():
        return {
            "ok": True,
            "token": dc.token,
            "username": dc.display_name or dc.username,
            "uid": dc.user_id,
            "is_bot": dc.is_bot,
            "fingerprint_locked": True,
        }
    return {"ok": False, "error": "Token không hợp lệ hoặc đã hết hạn"}


def login_discord_reg_session(login_email, password, two_fa_code=""):
    seed_key = f"{login_email}:{password[:4]}"
    s = requests.Session()
    s.cookies.update(DiscordStealthAntiBanEngine.get_deterministic_cookies(seed_key))
    headers = DiscordStealthAntiBanEngine.build_stealth_headers(seed_key, is_bot=False)
    headers["Referer"] = "https://discord.com/login"
    s.headers.update(headers)

    try:
        r_fp = s.get("https://discord.com/api/v10/experiments", timeout=10)
        if r_fp.status_code == 200:
            fp = r_fp.json().get("fingerprint")
            if fp:
                s.headers["X-Fingerprint"] = fp
    except Exception:
        pass

    pl = {
        "login": login_email.strip(),
        "password": password,
        "undelete": False,
        "login_source": None,
        "gift_code_sku_id": None,
    }
    r = s.post("https://discord.com/api/v10/auth/login", json=pl, timeout=15)
    d = r.json() if r.content else {}

    if r.status_code == 200 and d.get("token"):
        tk = d["token"]
        if s.headers.get("X-Fingerprint"):
            DiscordStealthAntiBanEngine._FINGERPRINT_CACHE[str(tk)[:18]] = s.headers["X-Fingerprint"]
        return {"ok": True, "token": tk}

    if d.get("mfa") and d.get("ticket"):
        if not two_fa_code:
            return {"ok": False, "need_2fa": True, "error": "Tài khoản có bật 2FA, hãy nhập mã 6 số 2FA vào ô bên dưới"}
        r_mfa = s.post(
            "https://discord.com/api/v10/auth/mfa/totp",
            json={
                "code": str(two_fa_code).strip(),
                "ticket": d["ticket"],
                "login_source": None,
                "gift_code_sku_id": None,
            },
            timeout=15
        )
        d_mfa = r_mfa.json() if r_mfa.content else {}
        if r_mfa.status_code == 200 and d_mfa.get("token"):
            tk = d_mfa["token"]
            if s.headers.get("X-Fingerprint"):
                DiscordStealthAntiBanEngine._FINGERPRINT_CACHE[str(tk)[:18]] = s.headers["X-Fingerprint"]
            return {"ok": True, "token": tk}
        return {"ok": False, "error": f"Mã 2FA không đúng hoặc hết hạn: {d_mfa.get('message', '')}"}

    if d.get("captcha_key"):
        return {
            "ok": False,
            "error": "IP máy chủ bị Discord yêu cầu xác minh Captcha khi đăng nhập bằng mật khẩu. Hãy dùng ô 'Dán Chuỗi Reg / mail:pass:token / Header' ở trên để nạp Token trực tiếp không dính Captcha!"
        }

    return {"ok": False, "error": d.get("message") or f"Không thể đăng nhập (HTTP {r.status_code})"}


# ============================================================
# CLIENT GIAO THỨC DISCORD STEALTH EDITION (CHUYÊN SÂU ANTI-DIE-ALL)
# ============================================================
class DiscordBot:
    def __init__(self, token, is_bot=False):
        raw_tok = str(token or "").strip()
        if raw_tok.lower().startswith("bot "):
            raw_tok = raw_tok[4:].strip()
            is_bot = True
        extracted = extract_discord_tokens_from_reg_or_raw(raw_tok)
        if extracted:
            raw_tok = extracted[0]
        self.token = raw_tok
        self.is_bot = bool(is_bot)
        self.s = requests.Session()
        adapter = HTTPAdapter(pool_connections=30, pool_maxsize=60, max_retries=2)
        self.s.mount("https://", adapter)
        self.s.mount("http://", adapter)
        if not self.is_bot:
            self.s.cookies.update(DiscordStealthAntiBanEngine.get_deterministic_cookies(self.token))
        self.route_step = 0
        self._apply_headers()
        self.user_id = None
        self.username = None
        self.display_name = None

    def _apply_headers(self, channel_id=None):
        self.s.headers.update(
            DiscordStealthAntiBanEngine.build_stealth_headers(
                self.token, is_bot=self.is_bot, channel_id=channel_id
            )
        )

    def check(self):
        ep = DiscordStealthAntiBanEngine.pick_stealth_endpoint(self.token, "/users/@me", 0)
        r = self.s.get(ep, timeout=12)
        if r.status_code == 401:
            self.is_bot = not self.is_bot
            self._apply_headers()
            r = self.s.get(ep, timeout=12)

        if r.status_code == 200:
            d = r.json()
            self.user_id = str(d.get("id") or "")
            self.username = d.get("username") or ""
            self.display_name = d.get("global_name") or d.get("username") or "Discord User"
            if self.user_id:
                OWNER_UIDS_CACHE.add(self.user_id)
                GLOBAL_USER_NAME_CACHE[self.user_id] = self.display_name
            return True
        return False

    def get_dm_and_group_boxes(self):
        out = []
        try:
            ep = DiscordStealthAntiBanEngine.pick_stealth_endpoint(self.token, "/users/@me/channels", 0)
            r = self.s.get(ep, timeout=15)
            if r.status_code == 200:
                channels = r.json()
                if isinstance(channels, list):
                    channels.sort(key=lambda c: int(c.get("last_message_id") or 0), reverse=True)
                    for c in channels:
                        cid = str(c.get("id") or "")
                        ctype = c.get("type")
                        recipients = c.get("recipients") or []
                        for rec in recipients:
                            ruid = str(rec.get("id") or "")
                            rname = rec.get("global_name") or rec.get("username") or ""
                            if ruid and rname:
                                GLOBAL_USER_NAME_CACHE[ruid] = rname

                        if ctype == 3:
                            g_name = c.get("name")
                            if not g_name:
                                r_names = [x.get("global_name") or x.get("username") or "User" for x in recipients]
                                g_name = ", ".join(r_names[:4]) if r_names else f"Box Nhóm {cid[-5:]}"
                            out.append({
                                "id": cid,
                                "name": f"[Box Nhóm] {g_name}",
                                "type": "discord_channel",
                                "sub_type": "group_dm",
                                "members": len(recipients) + 1
                            })
                        elif ctype == 1:
                            rec = recipients[0] if recipients else {}
                            dm_name = rec.get("global_name") or rec.get("username") or f"User {cid[-5:]}"
                            out.append({
                                "id": cid,
                                "name": f"[Chat Riêng] {dm_name}",
                                "type": "discord_channel",
                                "sub_type": "dm",
                                "members": 2
                            })
        except Exception:
            pass
        return out

    def get_guilds(self):
        try:
            ep = DiscordStealthAntiBanEngine.pick_stealth_endpoint(self.token, "/users/@me/guilds", 0)
            r = self.s.get(ep, timeout=15)
            if r.status_code == 200:
                return [{"id": str(g["id"]), "name": g.get("name", "Server"), "type": "discord_guild"} for g in r.json()]
        except Exception:
            pass
        return []

    def get_channels(self, guild_id, guild_name=""):
        try:
            ep = DiscordStealthAntiBanEngine.pick_stealth_endpoint(self.token, f"/guilds/{guild_id}/channels", 0)
            r = self.s.get(ep, timeout=12)
            if r.status_code == 200:
                channels = r.json()
                prefix = f"[{guild_name}] " if guild_name else ""
                return [{
                    "id": str(c["id"]),
                    "name": f"{prefix}# {c.get('name', 'channel')}",
                    "type": "discord_channel",
                    "sub_type": "guild_channel",
                    "guild_id": str(guild_id)
                } for c in channels if c.get("type") in (0, 5)]
        except Exception:
            pass
        return []

    def get_all_boxes(self):
        all_boxes = []
        dm_boxes = self.get_dm_and_group_boxes()
        all_boxes.extend(dm_boxes)

        guilds = self.get_guilds()
        if guilds:
            def _fetch_g(g):
                return self.get_channels(g["id"], g.get("name", ""))

            with ThreadPoolExecutor(max_workers=8) as ex:
                results = list(ex.map(_fetch_g, guilds[:25]))
            for ch_list in results:
                all_boxes.extend(ch_list)

        return all_boxes

    def get_box_members(self, channel_id):
        members = []
        seen = set()
        try:
            ep = DiscordStealthAntiBanEngine.pick_stealth_endpoint(self.token, f"/channels/{channel_id}", 0)
            r = self.s.get(ep, timeout=10)
            if r.status_code == 200:
                ch = r.json()
                for rec in (ch.get("recipients") or []):
                    uid = str(rec.get("id") or "")
                    name = rec.get("global_name") or rec.get("username") or f"User_{uid[-4:]}"
                    if uid and uid not in seen:
                        seen.add(uid)
                        GLOBAL_USER_NAME_CACHE[uid] = name
                        members.append({"id": uid, "uid": uid, "name": name})
        except Exception:
            pass

        try:
            ep_m = DiscordStealthAntiBanEngine.pick_stealth_endpoint(self.token, f"/channels/{channel_id}/messages?limit=40", 0)
            r_msgs = self.s.get(ep_m, timeout=10)
            if r_msgs.status_code == 200 and isinstance(r_msgs.json(), list):
                for m in r_msgs.json():
                    auth = m.get("author") or {}
                    uid = str(auth.get("id") or "")
                    name = auth.get("global_name") or auth.get("username") or ""
                    if uid and name and uid not in seen:
                        seen.add(uid)
                        GLOBAL_USER_NAME_CACHE[uid] = name
                        members.append({"id": uid, "uid": uid, "name": name})
        except Exception:
            pass
        return members

    def format_unframed_discord_text(self, raw_text, is_heading=True, style_mode="rainbow"):
        lines = [ln.strip() for ln in str(raw_text or "").split("\n")]
        out_lines = []
        for ln in lines:
            if not ln:
                out_lines.append("")
                continue
            clean_ln = re.sub(r"^#+\s*", "", ln).strip()
            if is_heading:
                out_lines.append(f"# **{clean_ln}**")
            elif style_mode != "none":
                out_lines.append(f"**{clean_ln}**")
            else:
                out_lines.append(clean_ln)
        return "\n".join(out_lines)

    def send_message(self, channel_id, content, color_mode="rainbow", fixed_color=None,
                     antiband=True, mentions=None, tag_all=False, strip_line_num=False,
                     is_heading=True):
        self.route_step = (self.route_step + 1) & 0xFFFF
        self._apply_headers(channel_id=channel_id)

        if antiband and not self.is_bot and DiscordStealthAntiBanEngine.should_trigger_typing(channel_id):
            try:
                typing_ep = DiscordStealthAntiBanEngine.pick_stealth_endpoint(
                    self.token, f"/channels/{channel_id}/typing", self.route_step
                )
                self.s.post(typing_ep, timeout=4)
            except Exception:
                pass

        raw = clean_corrupted_shortcuts(content)
        if strip_line_num:
            raw = "\n".join(strip_leading_line_number(ln) for ln in raw.split("\n"))

        tag_tokens = []
        if tag_all:
            tag_tokens.append("@everyone")
        if mentions:
            seen_u = set()
            for m in mentions:
                uid = str(m.get("uid") or m.get("id") or "").strip()
                if uid and uid not in ("0", "-1") and uid not in seen_u:
                    seen_u.add(uid)
                    if uid.isdigit():
                        tag_tokens.append(f"<@{uid}>")
                    else:
                        tag_tokens.append(f"@{m.get('name', uid)}")
        tag_suffix = (" " + " ".join(tag_tokens)) if tag_tokens else ""

        unframed_body = self.format_unframed_discord_text(
            raw, is_heading=is_heading, style_mode=color_mode
        )
        formatted_content = f"{unframed_body}{tag_suffix}".strip()

        if antiband:
            formatted_content = DiscordStealthAntiBanEngine.append_stealth_tail(
                formatted_content, channel_id=str(channel_id)
            )

        register_bot_sent_message(text=formatted_content)
        register_bot_sent_message(text=raw)

        url = DiscordStealthAntiBanEngine.pick_stealth_endpoint(
            self.token, f"/channels/{channel_id}/messages", self.route_step
        )
        pl = {
            "content": formatted_content,
            "nonce": DiscordStealthAntiBanEngine.generate_snowflake_nonce(),
            "tts": False,
            "flags": 0,
        }
        r = self.s.post(url, json=pl, timeout=15)
        DiscordStealthAntiBanEngine.record_bucket_headers(channel_id, r.headers)

        if r.status_code == 429:
            try:
                rj = r.json()
                retry_after = float(rj.get("retry_after", 8.0))
                err_code = int(rj.get("code", 0))
            except Exception:
                retry_after = 8.0
                err_code = 0
            DiscordStealthAntiBanEngine.set_channel_cooldown(channel_id, retry_after)
            raise Exception(f"429:RateLimit:{retry_after}:DiscordCode_{err_code}")

        if r.status_code == 401 or r.status_code == 403:
            try:
                err_code = int(r.json().get("code", 0))
            except Exception:
                err_code = 0
            if r.status_code == 401 or err_code in (40001, 40002):
                raise Exception(f"AuthError:Discord_{r.status_code}_{err_code}")
            raise Exception(f"HTTP {r.status_code}:Code_{err_code}")

        if r.status_code not in (200, 201):
            raise Exception(f"HTTP {r.status_code}")

        resp_data = r.json()
        if isinstance(resp_data, dict) and resp_data.get("id"):
            register_bot_sent_message(msg_id=resp_data["id"], text=formatted_content)
        return resp_data


# ============================================================
# ĐỘNG CƠ ĐA LUỒNG CHẠY 2-5+ ĐOẠN CHAT SONG SONG ỔN ĐỊNH KHÔNG LAG
# ============================================================
def box_target_worker(client, acc_id, plat, target, blocks, runtime_opts,
                      stop_ev, counter, lock, stagger_sec=0.0):
    if stagger_sec > 0:
        stop_ev.wait(stagger_sec)

    target_type = target.get("type", "group")
    target_id = str(target.get("id"))
    is_discord_target = (target_type == "discord_channel")
    if (plat == "zalo" and is_discord_target) or (plat == "discord" and not is_discord_target):
        return

    is_group = (target_type == "group") or bool(runtime_opts.get("tag_users")) or bool(runtime_opts.get("tag_all"))
    b_idx = 0
    color_counter = random.randint(0, 3)
    target_parsed_cache = {}

    while not stop_ev.is_set():
        if not blocks:
            break

        antiband = bool(runtime_opts.get("antiband", True))
        antidieall = bool(runtime_opts.get("antidieall", True))
        delay = float(runtime_opts.get("delay", 1.0))
        use_emoji = bool(runtime_opts.get("use_emoji", True))
        icon_count = int(runtime_opts.get("icon_count", 3))
        is_heading = bool(runtime_opts.get("is_heading", True))
        mode = runtime_opts.get("mode", "fast")
        color_mode = runtime_opts.get("color_mode", "rainbow")
        fixed_color = runtime_opts.get("fixed_color", "red")
        tag_users = runtime_opts.get("tag_users") or []
        tag_all = bool(runtime_opts.get("tag_all", False))
        strip_line_num = bool(runtime_opts.get("strip_line_num", True)) or (mode == "treo_nhay")

        if antidieall:
            ok_send, wait_sec = HEALTH_MGR.can_send(acc_id, channel_id=target_id, platform=plat)
            if not ok_send:
                stop_ev.wait(min(2.0, max(0.25, wait_sec)))
                continue

        raw = blocks[b_idx % len(blocks)]
        b_idx += 1

        eff_mentions = list(tag_users)
        eff_tag_all = tag_all
        clean_raw = raw

        if "@" in raw:
            cache_key = (plat, target_id, raw[:100], raw[-80:])
            if cache_key not in target_parsed_cache:
                if plat == "zalo":
                    stripped_txt, auto_m, auto_all = extract_trailing_tags_and_resolve(
                        raw, incoming_mentions=None, zalo_client=client, group_id=target_id
                    )
                else:
                    stripped_txt, auto_m, auto_all = extract_trailing_tags_and_resolve(
                        raw, incoming_mentions=None, discord_client=client, discord_channel_id=target_id
                    )
                target_parsed_cache[cache_key] = (stripped_txt or raw, auto_m, auto_all)
            c_txt, auto_m, auto_all = target_parsed_cache[cache_key]
            clean_raw = c_txt
            if auto_all:
                eff_tag_all = True
                is_group = True
            for am in auto_m:
                is_group = True
                if not any(str(x.get("uid") or x.get("id")) == str(am["uid"]) for x in eff_mentions):
                    eff_mentions.append(am)

        try:
            if mode == "treo_ngon":
                text = clean_raw.replace("\r\n", "\n").replace("\r", "\n")
                if plat == "zalo":
                    client.send_adv(
                        text, target_id, color_mode=color_mode, fixed_color=fixed_color,
                        is_group=is_group, mentions=(eff_mentions if is_group else None),
                        tag_all=(eff_tag_all if is_group else False), is_heading=is_heading,
                        color_offset=color_counter, antiband=antiband,
                        use_emoji=use_emoji, icon_count=icon_count,
                        auto_retry_thread_type=True, strip_line_num=False
                    )
                else:
                    if use_emoji and icon_count > 0:
                        text = text + " " + build_unique_zalo_icons(icon_count)
                    client.send_message(
                        target_id, text, color_mode=color_mode,
                        fixed_color=fixed_color, antiband=antiband,
                        mentions=eff_mentions, tag_all=eff_tag_all,
                        strip_line_num=False, is_heading=is_heading
                    )

                color_counter += 1
                with lock:
                    counter["sent"] += 1
                HEALTH_MGR.report_success(acc_id)

            elif mode == "treo_nhay":
                lines = []
                for raw_ln in clean_raw.split("\n"):
                    s_ln = raw_ln.strip()
                    if s_ln:
                        c_ln = strip_leading_line_number(s_ln)
                        if c_ln:
                            lines.append(c_ln)

                for ln in lines:
                    if stop_ev.is_set():
                        break
                    delay = float(runtime_opts.get("delay", delay))
                    color_mode = runtime_opts.get("color_mode", color_mode)
                    fixed_color = runtime_opts.get("fixed_color", fixed_color)
                    icon_count = int(runtime_opts.get("icon_count", icon_count))
                    use_emoji = bool(runtime_opts.get("use_emoji", use_emoji))
                    is_heading = bool(runtime_opts.get("is_heading", is_heading))
                    antiband = bool(runtime_opts.get("antiband", antiband))

                    if antidieall:
                        ok_s, w_s = HEALTH_MGR.can_send(acc_id, channel_id=target_id, platform=plat)
                        if not ok_s:
                            stop_ev.wait(min(1.8, max(0.25, w_s)))
                            continue

                    if plat == "zalo":
                        client.send_adv(
                            ln, target_id, color_mode=color_mode, fixed_color=fixed_color,
                            is_group=is_group, mentions=(eff_mentions if is_group else None),
                            tag_all=(eff_tag_all if is_group else False), is_heading=is_heading,
                            color_offset=color_counter, antiband=antiband,
                            use_emoji=use_emoji, icon_count=icon_count,
                            auto_retry_thread_type=True, strip_line_num=True
                        )
                    else:
                        msg_ln = (ln + " " + build_unique_zalo_icons(icon_count)) if (use_emoji and icon_count > 0) else ln
                        client.send_message(
                            target_id, msg_ln, color_mode=color_mode,
                            fixed_color=fixed_color, antiband=antiband,
                            mentions=eff_mentions, tag_all=eff_tag_all,
                            strip_line_num=True, is_heading=is_heading
                        )

                    color_counter += 1
                    with lock:
                        counter["sent"] += 1
                    HEALTH_MGR.report_success(acc_id)
                    step_d = HEALTH_MGR.get_adaptive_delay(
                        acc_id, delay, antiband=antiband, platform=plat, text_len=len(ln)
                    )
                    stop_ev.wait(max(0.24, step_d))
                continue

            else:
                text = strip_leading_line_number(clean_raw) if strip_line_num else clean_raw
                if plat == "zalo":
                    client.send_adv(
                        text, target_id, color_mode=color_mode, fixed_color=fixed_color,
                        is_group=is_group, mentions=(eff_mentions if is_group else None),
                        tag_all=(eff_tag_all if is_group else False), is_heading=is_heading,
                        color_offset=color_counter, antiband=antiband,
                        use_emoji=use_emoji, icon_count=icon_count,
                        auto_retry_thread_type=True, strip_line_num=strip_line_num
                    )
                else:
                    if use_emoji and icon_count > 0:
                        text = text + " " + build_unique_zalo_icons(icon_count)
                    client.send_message(
                        target_id, text, color_mode=color_mode,
                        fixed_color=fixed_color, antiband=antiband,
                        mentions=eff_mentions, tag_all=eff_tag_all,
                        strip_line_num=strip_line_num, is_heading=is_heading
                    )

                color_counter += 1
                with lock:
                    counter["sent"] += 1
                HEALTH_MGR.report_success(acc_id)

        except Exception as e:
            err_str = str(e)
            if "429:RateLimit:" in err_str:
                parts = err_str.split(":")
                try:
                    retry_after = float(parts[2])
                except Exception:
                    retry_after = 15.0
                HEALTH_MGR.report_rate_limit(acc_id, retry_after, reason=err_str, channel_id=target_id)
            elif "AuthError" in err_str:
                HEALTH_MGR.report_error(acc_id, err_str, is_auth_error=True)
            else:
                HEALTH_MGR.report_error(acc_id, err_str, is_auth_error=False)

        actual_delay = HEALTH_MGR.get_adaptive_delay(
            acc_id, delay, antiband=antiband, platform=plat, text_len=len(clean_raw)
        )
        stop_ev.wait(max(0.24, actual_delay))


def single_acc_multi_box_dispatcher(acc_dict, targets, blocks, runtime_opts, stop_ev, counter, lock):
    acc_id = acc_dict["id"]
    plat = acc_dict.get("platform") or "zalo"

    client = None
    if plat == "zalo":
        try:
            client = Zalo(acc_dict["imei"], json.loads(acc_dict["cookies"]))
            HEALTH_MGR.report_success(acc_id)
        except Exception as e:
            HEALTH_MGR.report_error(acc_id, str(e), is_auth_error=True)
            return
    else:
        try:
            client = DiscordBot(acc_dict["token"], is_bot=bool(acc_dict.get("is_bot", 0)))
            if not client.check():
                raise Exception("Token Discord không hợp lệ hoặc đã hết hạn")
            HEALTH_MGR.report_success(acc_id)
        except Exception as e:
            HEALTH_MGR.report_error(acc_id, str(e), is_auth_error=True)
            return

    box_threads = []
    for idx, target in enumerate(targets):
        stagger = idx * 0.16
        bt = threading.Thread(
            target=box_target_worker,
            args=(client, acc_id, plat, target, blocks, runtime_opts, stop_ev, counter, lock, stagger),
            daemon=True
        )
        box_threads.append(bt)
        bt.start()

    while not stop_ev.is_set():
        if not any(bt.is_alive() for bt in box_threads):
            break
        stop_ev.wait(0.8)

    for bt in box_threads:
        bt.join(timeout=0.2)


def task_supervisor(tid, targets, blocks, runtime_opts, multi_acc, stop_ev, specific_acc_id=None):
    conn = db()
    if specific_acc_id:
        accs = conn.execute("SELECT * FROM accounts WHERE id = ?", (specific_acc_id,)).fetchall()
    else:
        accs = conn.execute("SELECT * FROM accounts WHERE enabled = 1").fetchall()
        if not accs:
            accs = conn.execute("SELECT * FROM accounts").fetchall()
    conn.close()

    if not accs:
        conn = db()
        conn.execute(
            "UPDATE tasks SET status = 'stopped', stats = ? WHERE id = ?",
            (json.dumps({"error": "Không có tài khoản khả dụng"}), tid)
        )
        conn.commit()
        conn.close()
        ACTIVE_TASKS.pop(tid, None)
        return

    counter = {"sent": 0}
    lock = threading.Lock()
    threads = []

    selected_accs = accs if (multi_acc and not specific_acc_id) else [accs[0]]
    for a in selected_accs:
        t = threading.Thread(
            target=single_acc_multi_box_dispatcher,
            args=(dict(a), targets, blocks, runtime_opts, stop_ev, counter, lock),
            daemon=True
        )
        threads.append(t)
        t.start()

    last_db_sync = time.time()
    while not stop_ev.is_set():
        alive = [t for t in threads if t.is_alive()]
        if not alive:
            break
        if time.time() - last_db_sync >= 2.0:
            try:
                conn = db()
                conn.execute(
                    "UPDATE tasks SET stats = ? WHERE id = ?",
                    (json.dumps({"sent": counter["sent"]}), tid)
                )
                conn.commit()
                conn.close()
            except Exception:
                pass
            last_db_sync = time.time()
        time.sleep(0.6)

    for th in threads:
        th.join(timeout=0.3)

    conn = db()
    conn.execute(
        "UPDATE tasks SET status = 'stopped', stats = ? WHERE id = ?",
        (json.dumps({"sent": counter["sent"]}), tid)
    )
    conn.commit()
    conn.close()
    ACTIVE_TASKS.pop(tid, None)


def start_task_programmatic(targets, blocks, delay=1.0, use_emoji=True, icon_count=3,
                            tag_users=None, tag_all=False, is_heading=True, multi_acc=True,
                            mode="fast", color_mode="rainbow", fixed_color="red",
                            antiband=True, antidieall=True, specific_acc_id=None, source_label="web"):
    tid = new_tid("cmd" if source_label == "chat" else "task")
    stop_ev = threading.Event()
    tag_users = tag_users or []

    clean_blocks = []
    for b in blocks:
        if mode == "treo_nhay":
            lines_b = [strip_leading_line_number(ln) for ln in str(b).split("\n") if ln.strip()]
            clean_blocks.extend([x for x in lines_b if x])
        else:
            clean_blocks.append(clean_corrupted_shortcuts(str(b)))
    if not clean_blocks:
        clean_blocks = list(blocks)

    runtime_opts = {
        "delay": float(delay),
        "use_emoji": bool(use_emoji),
        "icon_count": int(icon_count),
        "tag_users": list(tag_users),
        "tag_all": bool(tag_all),
        "is_heading": bool(is_heading),
        "mode": mode,
        "color_mode": color_mode,
        "fixed_color": fixed_color,
        "antiband": bool(antiband),
        "antidieall": bool(antidieall),
        "strip_line_num": (mode == "treo_nhay") or True,
    }

    th = threading.Thread(
        target=task_supervisor,
        args=(tid, targets, clean_blocks, runtime_opts, multi_acc, stop_ev, specific_acc_id),
        daemon=True
    )

    meta_info = {
        "source": source_label,
        "multi_acc": multi_acc,
        "color_mode": color_mode,
        "delay": delay,
        "targets": [str(t.get("id")) for t in targets],
        "target_names": [t.get("name", str(t.get("id"))) for t in targets],
        "box_count": len(targets),
        "tag_count": len(tag_users),
        "tag_all": tag_all
    }

    conn = db()
    conn.execute(
        "INSERT INTO tasks (id, type, meta, status, started_at, stats) VALUES (?, ?, ?, ?, ?, ?)",
        (tid, mode, json.dumps(meta_info, ensure_ascii=False), "running", time.time(), '{"sent":0}')
    )
    conn.commit()
    conn.close()

    ACTIVE_TASKS[tid] = {
        "stop": stop_ev,
        "thread": th,
        "targets": [str(t.get("id")) for t in targets],
        "opts": runtime_opts,
        "acc_id": specific_acc_id,
        "source": source_label
    }
    th.start()
    return tid


def update_running_tasks_config(thread_id=None, **kwargs):
    updated = 0
    with BOT_CFG_LOCK:
        for k, v in kwargs.items():
            if k in BOT_RUNTIME_CONFIG:
                BOT_RUNTIME_CONFIG[k] = v

    for tid, info in list(ACTIVE_TASKS.items()):
        if thread_id is None or str(thread_id) in info.get("targets", []):
            opts = info.get("opts")
            if isinstance(opts, dict):
                opts.update(kwargs)
                updated += 1
    return updated


def stop_tasks_for_thread(thread_id=None):
    stopped = 0
    for tid, info in list(ACTIVE_TASKS.items()):
        if thread_id is None or str(thread_id) in info.get("targets", []):
            info["stop"].set()
            stopped += 1
    return stopped


# ============================================================
# HỆ THỐNG SELF-BOT LỆNH KHUNG CHAT ZALO & DISCORD 24/7
# ============================================================
def log_bot_command(acc_id, thread_id, sender_id, cmd_text, action_taken):
    try:
        conn = db()
        conn.execute(
            "INSERT INTO bot_logs (acc_id, thread_id, sender_id, cmd_text, action_taken, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                acc_id,
                mask_sensitive_id(thread_id, 4),
                mask_sensitive_id(sender_id, 4),
                sanitize_log_text(cmd_text)[:240],
                sanitize_log_text(action_taken)[:240],
                time.time()
            )
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def strip_invisible_chars(s):
    if not s:
        return ""
    for zw in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"):
        s = s.replace(zw, "")
    return s.strip()


def parse_and_execute_inchat_command(
    zalo_client, acc_row, thread_id, is_group, sender_id, raw_msg,
    raw_mentions=None, discord_client=None, platform="zalo"
):
    if not raw_msg:
        return False

    if is_bot_echo_message(text=raw_msg):
        return False

    text = strip_invisible_chars(str(raw_msg))
    if not text:
        return False

    if "<nội dung>" in text or "<số thứ tự file>" in text or "[@Tên / @All]" in text or "• .spam" in text:
        return False

    custom_prefix = (acc_row.get("cmd_prefix") or ".").strip()
    valid_prefixes = tuple(set([custom_prefix, ".", "/", "!"]))
    if not text.startswith(valid_prefixes):
        return False

    s_uid = str(sender_id or "").strip()
    if platform == "zalo" and zalo_client:
        my_uid = str(zalo_client.uid or acc_row.get("uid") or "").strip()
        my_s2m = str(getattr(zalo_client, "send2me_id", "") or "").strip()
    elif discord_client:
        my_uid = str(discord_client.user_id or acc_row.get("uid") or "").strip()
        my_s2m = ""
    else:
        my_uid = str(acc_row.get("uid") or "").strip()
        my_s2m = ""

    is_owner = (s_uid in ("0", "", my_uid, my_s2m)) or (s_uid in OWNER_UIDS_CACHE)
    allow_all = bool(acc_row.get("allow_all_cmd", 0))

    if not is_user_authorized_for_cmd(s_uid, my_uid, my_s2m, allow_all=allow_all):
        return False

    first_space = text.find(" ")
    if first_space == -1:
        cmd_token = text[1:].lower().strip()
        arg_body = ""
        prefix_u16_offset = utf16_len(text)
    else:
        cmd_token = text[1:first_space].lower().strip()
        raw_after_space = text[first_space + 1:]
        arg_body = raw_after_space.strip()
        leading_sp = len(raw_after_space) - len(raw_after_space.lstrip())
        prefix_u16_offset = utf16_len(text[:first_space + 1 + leading_sp])

    if not cmd_token:
        return False

    acc_id = acc_row["id"]
    if platform == "discord":
        target_obj = [{
            "id": str(thread_id),
            "name": f"Discord_{str(thread_id)[-5:]}",
            "type": "discord_channel"
        }]
    else:
        target_obj = [{
            "id": str(thread_id),
            "name": f"Chat_{str(thread_id)[-6:]}",
            "type": "group" if is_group else "user"
        }]

    def _send_reply(msg_txt):
        try:
            register_bot_sent_message(text=msg_txt)
            if platform == "zalo" and zalo_client:
                zalo_client.send_adv(
                    msg_txt, thread_id, color_mode="rainbow",
                    is_group=is_group, is_heading=True, antiband=True,
                    use_emoji=False, icon_count=0, auto_retry_thread_type=True
                )
            elif platform == "discord" and discord_client:
                discord_client.send_message(
                    thread_id, msg_txt, color_mode="rainbow", antiband=True, is_heading=False
                )
        except Exception:
            pass

    if cmd_token in ("menu", "help", "lenh", "bot", "hdsd"):
        with BOT_CFG_LOCK:
            cur_d = BOT_RUNTIME_CONFIG["delay"]
            cur_c = BOT_RUNTIME_CONFIG["color_mode"]
            cur_ic = BOT_RUNTIME_CONFIG["icon_count"]
        help_txt = (
            "• .spam <nội dung> [@Tên / @All]\n"
            "• .nhay <nội dung hoặc số file> [@Tên / @All]\n"
            "• .ngon <nội dung hoặc số file> [@Tên / @All]\n"
            "• .file <số thứ tự file> [@Tên / @All]\n"
            "• .files (Xem số thứ tự file)\n"
            f"• .delay <giây> (Hiện tại: {cur_d}s)\n"
            f"• .mau <rainbow|word|random|do|vang|xanh|cam|tat> ({cur_c})\n"
            f"• .icon <số lượng> (Hiện tại: {cur_ic})\n"
            "• .chuto <on|off> | .antiband <on|off>\n"
            "• .chophep @Tên | .xoaquyen @Tên | .dsquyen\n"
            "• .stop (Dừng box này) | .stopall (Dừng hết)"
        )
        _send_reply(help_txt)
        log_bot_command(acc_id, thread_id, sender_id, text, f"Hiển thị .menu ({platform})")
        return True

    if cmd_token in ("chophep", "capquyen", "adduser", "add", "admin"):
        if not is_owner:
            return False
        _, target_mentions, _ = extract_trailing_tags_and_resolve(
            arg_body, incoming_mentions=raw_mentions,
            zalo_client=zalo_client if platform == "zalo" else None,
            group_id=thread_id if platform == "zalo" else None,
            prefix_u16_offset=prefix_u16_offset,
            discord_client=discord_client if platform == "discord" else None,
            discord_channel_id=thread_id if platform == "discord" else None,
            full_original_msg=text
        )
        added_names = []
        if target_mentions:
            for tm in target_mentions:
                if add_authorized_user(tm["uid"], tm["name"], acc_id):
                    added_names.append(tm["name"])
        elif arg_body.strip().isdigit():
            uid_ = arg_body.strip()
            if add_authorized_user(uid_, f"UID_{uid_[-4:]}", acc_id):
                added_names.append(uid_)

        reply_txt = ("Đã cấp quyền dùng lệnh cho: " + ", ".join(added_names)) if added_names else "Hãy tag người cần cấp quyền: .chophep @Tên"
        _send_reply(reply_txt)
        log_bot_command(acc_id, thread_id, sender_id, text, reply_txt)
        return True

    if cmd_token in ("xoaquyen", "thuhoi", "deluser", "del", "cam"):
        if not is_owner:
            return False
        if arg_body.strip().lower() in ("all", "tatca", "het"):
            conn = db()
            conn.execute("DELETE FROM authorized_users")
            conn.commit()
            conn.close()
            reply_txt = "Đã thu hồi quyền của tất cả người dùng phụ"
        else:
            _, target_mentions, _ = extract_trailing_tags_and_resolve(
                arg_body, incoming_mentions=raw_mentions,
                zalo_client=zalo_client if platform == "zalo" else None,
                group_id=thread_id if platform == "zalo" else None,
                prefix_u16_offset=prefix_u16_offset,
                discord_client=discord_client if platform == "discord" else None,
                discord_channel_id=thread_id if platform == "discord" else None,
                full_original_msg=text
            )
            removed_names = []
            for tm in target_mentions:
                if remove_authorized_user(tm["uid"]):
                    removed_names.append(tm["name"])
            if not removed_names and arg_body.strip().isdigit():
                if remove_authorized_user(arg_body.strip()):
                    removed_names.append(arg_body.strip())
            reply_txt = ("Đã xóa quyền: " + ", ".join(removed_names)) if removed_names else "Hãy tag người cần xóa quyền: .xoaquyen @Tên"
        _send_reply(reply_txt)
        log_bot_command(acc_id, thread_id, sender_id, text, reply_txt)
        return True

    if cmd_token in ("dsquyen", "listuser", "quyen"):
        users = list_authorized_users()
        if not users:
            reply_txt = "Chỉ mình chủ tài khoản đang có quyền điều khiển"
        else:
            reply_txt = "\n".join(f"• {u['name']} ({mask_sensitive_id(u['uid'], 4)})" for u in users)
        _send_reply(reply_txt)
        return True

    if cmd_token in ("delay", "tocdo", "time"):
        try:
            val_str = arg_body.strip().lower().replace("s", "")
            new_d = max(0.2, min(120.0, float(val_str)))
            cnt = update_running_tasks_config(thread_id=None, delay=new_d)
            reply_txt = f"Đã chỉnh delay thành {new_d}s (Áp dụng cho {cnt} tiến trình đang chạy)"
        except Exception:
            reply_txt = "Cú pháp đúng: .delay <số giây> (Ví dụ: .delay 0.5 hoặc .delay 1.5)"
        _send_reply(reply_txt)
        log_bot_command(acc_id, thread_id, sender_id, text, reply_txt)
        return True

    if cmd_token in ("mau", "color", "doimau"):
        arg_c = remove_vn_accents(arg_body.strip())
        if arg_c in ("rainbow", "dong", "cauvong"):
            update_running_tasks_config(color_mode="rainbow")
            reply_txt = "Đã bật tự động phối màu từng dòng"
        elif arg_c in ("word", "word_rainbow", "tu", "tungtu"):
            update_running_tasks_config(color_mode="word_rainbow")
            reply_txt = "Đã bật phối màu từng từ"
        elif arg_c in ("random", "ngaunhien"):
            update_running_tasks_config(color_mode="random")
            reply_txt = "Đã bật phối màu ngẫu nhiên"
        elif arg_c in ("none", "tat", "off"):
            update_running_tasks_config(color_mode="none")
            reply_txt = "Đã tắt đổi màu chữ"
        elif arg_c in ZALO_COLOR_MAP:
            c_map_id = {"do": "red", "red": "red", "vang": "yellow", "yellow": "yellow", "xanh": "green", "xanhla": "green", "green": "green", "cam": "orange", "orange": "orange"}.get(arg_c, "red")
            update_running_tasks_config(color_mode="fixed", fixed_color=c_map_id)
            reply_txt = f"Đã khóa cố định màu chữ: {c_map_id}"
        else:
            reply_txt = "Chọn màu: .mau rainbow | .mau word | .mau random | .mau do | .mau vang | .mau xanh | .mau cam | .mau tat"
        _send_reply(reply_txt)
        log_bot_command(acc_id, thread_id, sender_id, text, reply_txt)
        return True

    if cmd_token in ("icon", "emoji"):
        try:
            ic_n = max(0, min(10, int(arg_body.strip())))
            update_running_tasks_config(icon_count=ic_n, use_emoji=(ic_n > 0))
            reply_txt = f"Đã chỉnh số lượng Icon VIP: {ic_n}"
        except Exception:
            reply_txt = "Cú pháp: .icon <số lượng từ 0 đến 10>"
        _send_reply(reply_txt)
        return True

    if cmd_token in ("chuto", "heading"):
        on_val = arg_body.strip().lower() not in ("off", "tat", "0")
        update_running_tasks_config(is_heading=on_val)
        reply_txt = "Đã BẬT chữ lớn in đậm" if on_val else "Đã TẮT chữ lớn in đậm"
        _send_reply(reply_txt)
        return True

    if cmd_token in ("antiband", "antiban"):
        on_val = arg_body.strip().lower() not in ("off", "tat", "0")
        update_running_tasks_config(antiband=on_val)
        reply_txt = "Đã BẬT Anti-Ban thông minh" if on_val else "Đã TẮT Anti-Ban"
        _send_reply(reply_txt)
        return True

    if cmd_token in ("stop", "dung", "dừng", "tat", "tắt", "off"):
        cnt = stop_tasks_for_thread(thread_id)
        if cnt == 0:
            cnt = stop_tasks_for_thread(None)
        log_bot_command(acc_id, thread_id, sender_id, text, f"Đã dừng {cnt} tiến trình")
        _send_reply(f"Đã dừng {cnt} tiến trình chạy tự động")
        return True

    if cmd_token in ("stopall", "dunghet", "tathet"):
        cnt = stop_tasks_for_thread(None)
        log_bot_command(acc_id, thread_id, sender_id, text, f"Dừng toàn bộ ({cnt} tiến trình)")
        _send_reply(f"Đã dừng toàn bộ {cnt} tiến trình trên hệ thống")
        return True

    if cmd_token in ("files", "dsfile", "listfile"):
        f_list = get_ordered_files_with_display_num()
        if not f_list:
            msg_out = "Chưa có file nào trên hệ thống"
        else:
            msg_out = "\n".join(f"File số {f['display_num']}: {f['filename']} ({f['lines_count']} dòng)" for f in f_list)
        _send_reply(msg_out)
        log_bot_command(acc_id, thread_id, sender_id, text, "Hiển thị danh sách số thứ tự file")
        return True

    mode_map = {
        "spam": "fast",
        "fast": "fast",
        "nhanh": "fast",
        "nhay": "treo_nhay",
        "treonhay": "treo_nhay",
        "treo_nhay": "treo_nhay",
        "ngon": "treo_ngon",
        "treongon": "treo_ngon",
        "treo_ngon": "treo_ngon",
        "file": "file_cmd",
        "chay": "file_cmd",
        "tag": "fast",
        "all": "fast",
    }

    direct_file_num = None
    if cmd_token.isdigit():
        chosen_mode = "file_cmd"
        direct_file_num = cmd_token
    elif cmd_token in mode_map:
        chosen_mode = mode_map[cmd_token]
    else:
        return False

    with BOT_CFG_LOCK:
        delay_val = float(BOT_RUNTIME_CONFIG["delay"])
        color_mode = BOT_RUNTIME_CONFIG["color_mode"]
        fixed_color = BOT_RUNTIME_CONFIG["fixed_color"]
        use_emoji = bool(BOT_RUNTIME_CONFIG["use_emoji"])
        icon_count = int(BOT_RUNTIME_CONFIG["icon_count"])
        is_heading = bool(BOT_RUNTIME_CONFIG["is_heading"])
        antiband_flag = bool(BOT_RUNTIME_CONFIG["antiband"])

    cleaned_body, extracted_mentions, extracted_tag_all = extract_trailing_tags_and_resolve(
        arg_body,
        incoming_mentions=raw_mentions,
        zalo_client=zalo_client if platform == "zalo" else None,
        group_id=thread_id if platform == "zalo" else None,
        prefix_u16_offset=prefix_u16_offset,
        discord_client=discord_client if platform == "discord" else None,
        discord_channel_id=thread_id if platform == "discord" else None,
        full_original_msg=text
    )

    if cmd_token == "all":
        extracted_tag_all = True

    if platform == "zalo" and (extracted_mentions or extracted_tag_all):
        target_obj[0]["type"] = "group"

    tokens = cleaned_body.split()
    consumed = 0
    file_query = direct_file_num

    if chosen_mode == "file_cmd":
        chosen_mode = "treo_nhay"
        if not file_query and tokens:
            file_query = tokens[0]
            consumed = 1

    for tk in tokens[consumed:]:
        tk_low = tk.lower()
        if tk_low.startswith("delay=") or tk_low.startswith("d="):
            try:
                delay_val = max(0.25, float(tk_low.split("=", 1)[1].replace("s", "")))
                consumed += 1
            except Exception:
                break
        elif tk_low.startswith("color=") or tk_low.startswith("mau="):
            c_val = tk_low.split("=", 1)[1]
            if c_val in ("rainbow", "word_rainbow", "random", "none"):
                color_mode = c_val
            elif c_val in ZALO_COLOR_MAP:
                color_mode = "fixed"
                fixed_color = c_val
            consumed += 1
        elif tk_low.startswith("icon="):
            try:
                icon_count = max(0, int(tk_low.split("=", 1)[1]))
                use_emoji = (icon_count > 0)
                consumed += 1
            except Exception:
                break
        elif tk_low in ("nhay", "treonhay", "treo_nhay"):
            chosen_mode = "treo_nhay"
            consumed += 1
        elif tk_low in ("ngon", "treongon", "treo_ngon"):
            chosen_mode = "treo_ngon"
            consumed += 1
        elif tk_low in ("fast", "nhanh"):
            chosen_mode = "fast"
            consumed += 1
        elif tk_low.startswith("file="):
            file_query = tk.split("=", 1)[1]
            consumed += 1
        else:
            break

    remaining_content = " ".join(tokens[consumed:]).strip() if consumed > 0 else cleaned_body.strip()

    blocks = []
    if file_query:
        blocks = get_blocks_from_file_query(file_query, mode=chosen_mode)
    elif remaining_content and (remaining_content.isdigit() or remaining_content.endswith(".txt")):
        blocks = get_blocks_from_file_query(remaining_content, mode=chosen_mode)

    if not blocks and remaining_content and not file_query:
        if chosen_mode == "treo_nhay":
            if ";" in remaining_content:
                blocks = [strip_leading_line_number(x.strip()) for x in remaining_content.split(";") if x.strip()]
            elif "\n" in remaining_content:
                blocks = [strip_leading_line_number(x.strip()) for x in remaining_content.split("\n") if x.strip()]
            else:
                blocks = [strip_leading_line_number(remaining_content)]
        elif chosen_mode == "treo_ngon":
            blocks = [remaining_content.replace(";", "\n")]
        else:
            blocks = [x.strip() for x in remaining_content.split(";") if x.strip()] if ";" in remaining_content else [remaining_content]

    if not blocks and not remaining_content:
        blocks = get_blocks_from_file_query("latest", mode=chosen_mode)

    if not blocks:
        _send_reply("Không tìm thấy nội dung hoặc file. Hãy tải file lên web hoặc gõ .files để xem số thứ tự file.")
        return False

    stop_tasks_for_thread(thread_id)

    tid = start_task_programmatic(
        targets=target_obj,
        blocks=blocks,
        delay=delay_val,
        use_emoji=use_emoji,
        icon_count=icon_count,
        tag_users=extracted_mentions,
        tag_all=extracted_tag_all,
        is_heading=is_heading,
        multi_acc=True,
        mode=chosen_mode,
        color_mode=color_mode,
        fixed_color=fixed_color,
        antiband=antiband_flag,
        antidieall=True,
        specific_acc_id=acc_id,
        source_label="chat"
    )

    tag_desc = "@All" if extracted_tag_all else (", ".join("@" + m["name"] for m in extracted_mentions) if extracted_mentions else "Không tag")
    log_bot_command(acc_id, thread_id, sender_id, text, f"[{platform.upper()}] Chạy {chosen_mode} (Task {tid[-6:]}) | Tag: {tag_desc}")
    return True


# ============================================================
# LISTENER 24/7 TRÊN ZALO (WEBSOCKET + HTTP FALLBACK)
# ============================================================
class ZaloSelfBotListener:
    def __init__(self, acc_id):
        self.acc_id = acc_id
        self.platform = "zalo"
        self.stop_ev = threading.Event()
        self.seen_msg_ids = deque(maxlen=1000)
        self.ws_cipher_key = None
        self.ws_status = "Đang khởi tạo Zalo Shield..."
        self.last_event_ts = 0.0
        self.thread = threading.Thread(target=self._run_loop, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_ev.set()

    def _get_acc_row(self):
        conn = db()
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (self.acc_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def _recv_exact(sock, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    @staticmethod
    def _send_ws_frame(sock, payload_bytes, opcode=0x2):
        mask_key = os.urandom(4)
        length = len(payload_bytes)
        header = bytearray([0x80 | (opcode & 0x0F)])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", length))
        header.extend(mask_key)
        masked_payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload_bytes))
        sock.sendall(bytes(header) + masked_payload)

    def _try_decompress_or_json(self, raw_bytes):
        if not raw_bytes:
            return None
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS, 16 + zlib.MAX_WBITS):
            try:
                decomp = zlib.decompress(raw_bytes, wbits)
                txt = decomp.decode("utf-8", errors="ignore").strip()
                if txt.startswith("{") or txt.startswith("["):
                    return json.loads(txt)
            except Exception:
                pass
        try:
            txt = raw_bytes.decode("utf-8", errors="ignore").strip()
            if txt.startswith("{") or txt.startswith("["):
                return json.loads(txt)
        except Exception:
            pass
        return None

    def _decode_ws_payload(self, client, raw_data_str, encrypt_type):
        if not raw_data_str:
            return None
        try:
            if encrypt_type == 0:
                return json.loads(raw_data_str) if isinstance(raw_data_str, str) else raw_data_str

            b_data = base64.b64decode(unquote(raw_data_str) if "%" in str(raw_data_str) else raw_data_str)

            key_candidates = []
            for k_str in (self.ws_cipher_key, client.secret_key):
                if not k_str:
                    continue
                try:
                    kb = base64.b64decode(k_str)
                    if len(kb) in (16, 24, 32):
                        key_candidates.append(kb)
                except Exception:
                    pass
                try:
                    kb_utf = str(k_str).encode("utf-8")
                    if len(kb_utf) in (16, 24, 32):
                        key_candidates.append(kb_utf)
                except Exception:
                    pass

            if len(b_data) > 32:
                iv = b_data[:16]
                aad = b_data[16:32]
                for kb in key_candidates:
                    if len(b_data) >= 48:
                        try:
                            cipher = AES.new(kb, AES.MODE_GCM, nonce=iv)
                            cipher.update(aad)
                            pt = cipher.decrypt_and_verify(b_data[32:-16], b_data[-16:])
                            res = self._try_decompress_or_json(pt)
                            if res is not None:
                                return res
                        except Exception:
                            pass
                        try:
                            cipher = AES.new(kb, AES.MODE_GCM, nonce=iv)
                            pt = cipher.decrypt(b_data[32:-16])
                            res = self._try_decompress_or_json(pt)
                            if res is not None:
                                return res
                        except Exception:
                            pass
                    for sl in (b_data[32:], b_data[16:-16], b_data[16:]):
                        if not sl:
                            continue
                        try:
                            cipher = AES.new(kb, AES.MODE_GCM, nonce=iv)
                            pt = cipher.decrypt(sl)
                            res = self._try_decompress_or_json(pt)
                            if res is not None:
                                return res
                        except Exception:
                            pass

            for kb in key_candidates:
                for iv_cand, body_cand in ((bytes(16), b_data), (b_data[:16], b_data[16:])):
                    if not body_cand or len(body_cand) % 16 != 0:
                        continue
                    try:
                        cipher = AES.new(kb, AES.MODE_CBC, iv_cand)
                        dec_bytes = cipher.decrypt(body_cand)
                        pad_v = dec_bytes[-1]
                        if 1 <= pad_v <= 16:
                            dec_bytes = dec_bytes[:-pad_v]
                        res = self._try_decompress_or_json(dec_bytes)
                        if res is not None:
                            return res
                    except Exception:
                        pass

            for cand in (b_data, b_data[16:], b_data[32:], b_data[4:]):
                res = self._try_decompress_or_json(cand)
                if res is not None:
                    return res
        except Exception:
            pass
        return None

    def _extract_msg_dicts(self, obj, parent_is_group=False):
        found = []
        if isinstance(obj, dict):
            has_content = ("content" in obj) or ("msg" in obj and ("uidFrom" in obj or "idTo" in obj))
            if has_content and any(k in obj for k in ("uidFrom", "idTo", "msgId", "cliMsgId", "toid", "fromUid")):
                item = dict(obj)
                if parent_is_group:
                    item["_is_group_hint"] = True
                found.append(item)
            for k, v in obj.items():
                is_grp_branch = parent_is_group or (k in ("groupMsgs", "group_msgs", "grid"))
                if isinstance(v, (dict, list)):
                    found.extend(self._extract_msg_dicts(v, parent_is_group=is_grp_branch))
        elif isinstance(obj, list):
            for elem in obj:
                if isinstance(elem, (dict, list)):
                    found.extend(self._extract_msg_dicts(elem, parent_is_group=parent_is_group))
        return found

    def _extract_raw_mentions_from_msg_obj(self, msg_obj):
        def _parse_candidate(val):
            if isinstance(val, list) and val:
                return val
            if isinstance(val, dict):
                if "mentions" in val:
                    return _parse_candidate(val["mentions"])
                if "mentionInfo" in val:
                    return _parse_candidate(val["mentionInfo"])
                if "uid" in val or "pos" in val:
                    return [val]
            if isinstance(val, str):
                s = val.strip()
                if s.startswith("[") or s.startswith("{"):
                    try:
                        return _parse_candidate(json.loads(s))
                    except Exception:
                        pass
            return None

        for key in ("mentions", "mentionInfo", "propertyExt", "params"):
            res = _parse_candidate(msg_obj.get(key))
            if res:
                return res
        return None

    def _process_msg_item(self, client, acc_row, msg_obj, default_is_group=False, fallback_thread_id=None):
        if not isinstance(msg_obj, dict):
            return

        msg_id = str(msg_obj.get("msgId") or msg_obj.get("globalMsgId") or "")
        cli_msg_id = str(msg_obj.get("cliMsgId") or "")
        raw_content = msg_obj.get("content")
        if isinstance(raw_content, dict):
            raw_content = (
                raw_content.get("title")
                or raw_content.get("text")
                or raw_content.get("msg")
                or raw_content.get("description")
                or ""
            )
        elif not isinstance(raw_content, str):
            raw_content = str(msg_obj.get("msg") or msg_obj.get("message") or "")

        if is_bot_echo_message(msg_id=msg_id, client_id=cli_msg_id, text=raw_content):
            return

        content = strip_invisible_chars(raw_content)
        if not content:
            return

        dedupe_key = f"{msg_id}_{cli_msg_id}_{content[:40]}" if (msg_id or cli_msg_id) else f"{int(time.time() // 3)}_{content[:40]}"
        if dedupe_key in self.seen_msg_ids:
            return
        self.seen_msg_ids.append(dedupe_key)

        uid_from = str(msg_obj.get("uidFrom") or msg_obj.get("fromUid") or "")
        d_name = str(msg_obj.get("dName") or "").strip()
        if uid_from and d_name and uid_from != "0":
            GLOBAL_USER_NAME_CACHE[uid_from] = d_name

        id_to = str(msg_obj.get("idTo") or msg_obj.get("toid") or fallback_thread_id or "")
        cmd_num = int(msg_obj.get("cmd") or 0)
        raw_mentions = self._extract_raw_mentions_from_msg_obj(msg_obj)

        known_gids = KNOWN_GROUPS_BY_ACC.get(client.uid, set())
        is_group = bool(
            default_is_group
            or msg_obj.get("_is_group_hint")
            or msg_obj.get("isGroup")
            or (cmd_num in (521, 522))
            or (id_to in known_gids)
            or (uid_from in known_gids)
            or bool(raw_mentions)
        )

        my_uid = str(client.uid or acc_row.get("uid") or "")
        if is_group:
            if id_to in known_gids:
                thread_id = id_to
            elif uid_from in known_gids:
                thread_id = uid_from
            else:
                thread_id = id_to if (id_to and id_to not in ("0", my_uid)) else (fallback_thread_id or uid_from)
        else:
            if uid_from in ("0", my_uid, ""):
                thread_id = id_to if id_to not in ("0", "") else my_uid
            else:
                thread_id = uid_from

        if not thread_id or thread_id == "0":
            return

        parse_and_execute_inchat_command(
            zalo_client=client,
            acc_row=acc_row,
            thread_id=thread_id,
            is_group=is_group,
            sender_id=uid_from,
            raw_msg=content,
            raw_mentions=raw_mentions,
            platform="zalo"
        )

    def _run_ws_session(self, client, acc_row, ws_url):
        parsed = urlparse(ws_url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        raw_sock = socket.create_connection((host, port), timeout=12)
        if parsed.scheme == "wss":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(raw_sock, server_hostname=host)
        else:
            sock = raw_sock

        ws_key = base64.b64encode(os.urandom(16)).decode()
        cookie_str = "; ".join(f"{k}={v}" for k, v in client.cookies_dict.items())
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {ws_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"Origin: https://chat.zalo.me\r\n"
            f"User-Agent: {client.s.headers.get('User-Agent')}\r\n"
            f"Cookie: {cookie_str}\r\n\r\n"
        )
        sock.sendall(handshake.encode("utf-8"))

        resp_buf = bytearray()
        while not resp_buf.endswith(b"\r\n\r\n"):
            b1 = sock.recv(1)
            if not b1:
                sock.close()
                return
            resp_buf.extend(b1)
            if len(resp_buf) > 8192:
                sock.close()
                return

        if b"101" not in resp_buf.split(b"\r\n")[0]:
            sock.close()
            return

        self.ws_status = "Zalo Quantum Shield Active"
        sock.settimeout(0.5)
        last_ping = time.time()

        try:
            while not self.stop_ev.is_set():
                acc_now = self._get_acc_row()
                if not acc_now or not acc_now.get("chat_cmd_enabled", 1):
                    self.ws_status = "Đã tắt nhận lệnh"
                    break

                if time.time() - last_ping >= 18.0:
                    hb_payload = struct.pack("<BHB", 1, 2, 1) + json.dumps({"eventId": int(time.time() * 1000)}).encode("utf-8")
                    self._send_ws_frame(sock, hb_payload, opcode=0x2)
                    last_ping = time.time()

                try:
                    hdr = self._recv_exact(sock, 2)
                    if not hdr:
                        break
                    opcode = hdr[0] & 0x0F
                    masked = (hdr[1] & 0x80) != 0
                    payload_len = hdr[1] & 0x7F

                    if payload_len == 126:
                        ext = self._recv_exact(sock, 2)
                        if not ext:
                            break
                        payload_len = struct.unpack(">H", ext)[0]
                    elif payload_len == 127:
                        ext = self._recv_exact(sock, 8)
                        if not ext:
                            break
                        payload_len = struct.unpack(">Q", ext)[0]

                    mask_bytes = self._recv_exact(sock, 4) if masked else b""
                    data = self._recv_exact(sock, payload_len) if payload_len > 0 else b""
                    if data is None:
                        break

                    if masked and mask_bytes:
                        data = bytes(b ^ mask_bytes[i % 4] for i, b in enumerate(data))

                    if opcode == 0x8:
                        break
                    if opcode == 0x9:
                        self._send_ws_frame(sock, data, opcode=0xA)
                        continue

                    if opcode in (0x1, 0x2) and len(data) >= 4:
                        cmd_id = 0
                        json_part = data
                        if data[0] != ord("{"):
                            cmd_id = struct.unpack("<H", data[1:3])[0]
                            json_part = data[4:]

                        txt_frame = json_part.decode("utf-8", errors="ignore").strip()
                        if not txt_frame.startswith("{"):
                            continue
                        outer = json.loads(txt_frame)

                        if outer.get("key"):
                            self.ws_cipher_key = outer["key"]
                            self.ws_status = "Zalo Quantum Shield Active"
                        elif isinstance(outer.get("data"), dict) and outer["data"].get("key"):
                            self.ws_cipher_key = outer["data"]["key"]
                            self.ws_status = "Zalo Quantum Shield Active"

                        if cmd_id == 3000:
                            self.ws_status = "Đang đồng bộ phiên..."
                            break

                        enc_type = int(outer.get("encrypt", 0))
                        raw_d = outer.get("data")
                        if not raw_d or (cmd_id in (1, 2) and not isinstance(raw_d, str)):
                            continue

                        inner = self._decode_ws_payload(client, raw_d, enc_type)
                        if inner is not None:
                            self.last_event_ts = time.time()
                            is_grp_cmd = (cmd_id in (521, 522))
                            msg_items = self._extract_msg_dicts(inner, parent_is_group=is_grp_cmd)
                            for m in msg_items:
                                m["cmd"] = cmd_id
                                self._process_msg_item(client, acc_now, m, default_is_group=is_grp_cmd)
                except socket.timeout:
                    continue
                except Exception:
                    break
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _run_loop(self):
        ws_idx = 0
        while not self.stop_ev.is_set():
            acc_row = self._get_acc_row()
            if not acc_row or (acc_row.get("platform") or "zalo") != "zalo":
                break
            if not acc_row.get("chat_cmd_enabled", 1):
                self.ws_status = "Đã tắt nhận lệnh"
                self.stop_ev.wait(4.0)
                continue

            try:
                client = Zalo(acc_row["imei"], json.loads(acc_row["cookies"]))
                try:
                    client.get_grid_ver_map()
                except Exception:
                    pass

                if client.ws_urls:
                    ws_url = client.ws_urls[ws_idx % len(client.ws_urls)]
                    ws_idx += 1
                    if "zpw_ver=" not in ws_url:
                        sep = "&" if "?" in ws_url else "?"
                        ws_url = f"{ws_url}{sep}zpw_ver=645&zpw_type=30&t={int(time.time() * 1000)}"
                    self._run_ws_session(client, acc_row, ws_url)

                known_gids = list(KNOWN_GROUPS_BY_ACC.get(client.uid, set()))[:8]
                for gid in known_gids:
                    if self.stop_ev.is_set():
                        break
                    for m in client.get_recent_group_messages(gid)[-4:]:
                        self._process_msg_item(client, acc_row, m, default_is_group=True, fallback_thread_id=str(gid))
                self.stop_ev.wait(2.0)
            except Exception:
                self.ws_status = "Đang kết nối lại..."
                self.stop_ev.wait(5.0)


# ============================================================
# LISTENER 24/7 TRÊN DISCORD ACC CHÍNH CHỦ & BOT (ANTI-SCAN GATEWAY v10)
# ============================================================
class DiscordSelfBotListener:
    def __init__(self, acc_id):
        self.acc_id = acc_id
        self.platform = "discord"
        self.stop_ev = threading.Event()
        self.seen_msg_ids = deque(maxlen=1000)
        self.ws_status = "Đang kết nối Discord Anti-Scan..."
        self.last_event_ts = 0.0
        self.last_seq = None
        self.thread = threading.Thread(target=self._run_loop, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_ev.set()

    def _get_acc_row(self):
        conn = db()
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (self.acc_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def _handle_discord_message_event(self, client, acc_row, msg_data):
        if not isinstance(msg_data, dict):
            return
        msg_id = str(msg_data.get("id") or "")
        content = str(msg_data.get("content") or "")
        if not content:
            return

        if is_bot_echo_message(msg_id=msg_id, text=content):
            return

        if msg_id in self.seen_msg_ids:
            return
        if msg_id:
            self.seen_msg_ids.append(msg_id)

        channel_id = str(msg_data.get("channel_id") or "")
        author = msg_data.get("author") or {}
        sender_id = str(author.get("id") or "")
        sender_name = author.get("global_name") or author.get("username") or ""
        if sender_id and sender_name:
            GLOBAL_USER_NAME_CACHE[sender_id] = sender_name

        if not channel_id:
            return

        raw_mentions = []
        for m in (msg_data.get("mentions") or []):
            muid = str(m.get("id") or "")
            mname = m.get("global_name") or m.get("username") or ""
            if muid:
                if mname:
                    GLOBAL_USER_NAME_CACHE[muid] = mname
                raw_mentions.append({"uid": muid, "id": muid, "name": mname})

        parse_and_execute_inchat_command(
            zalo_client=None,
            acc_row=acc_row,
            thread_id=channel_id,
            is_group=True,
            sender_id=sender_id,
            raw_msg=content,
            raw_mentions=raw_mentions,
            discord_client=client,
            platform="discord"
        )

    def _run_gateway_session(self, client, acc_row):
        host = "gateway.discord.gg"
        port = 443
        path = "/?encoding=json&v=10"

        raw_sock = socket.create_connection((host, port), timeout=12)
        ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(raw_sock, server_hostname=host)

        ws_key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {ws_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"Origin: https://discord.com\r\n"
            f"User-Agent: {client.s.headers.get('User-Agent')}\r\n\r\n"
        )
        sock.sendall(handshake.encode("utf-8"))

        resp_buf = bytearray()
        while not resp_buf.endswith(b"\r\n\r\n"):
            b1 = sock.recv(1)
            if not b1:
                sock.close()
                return
            resp_buf.extend(b1)
            if len(resp_buf) > 8192:
                sock.close()
                return

        if b"101" not in resp_buf.split(b"\r\n")[0]:
            sock.close()
            return

        sock.settimeout0.5)
        hb_interval = 38.0
        last_hb = time.time()
        identified = False
        prof = DiscordStealthAntiBanEngine.get_deterministic_profile(client.token)
        launch_sig, hb_sess = DiscordStealthAntiBanEngine.get_deterministic_session_uuids(client.token)

        try:
            while not self.stop_ev.is_set():
                acc_now = self._get_acc_row()
                if not acc_now or not acc_now.get("chat_cmd_enabled", 1):
                    self.ws_status = "Đã tắt nhận lệnh"
                    break

                if identified and (time.time() - last_hb >= hb_interval):
                    hb_pkt = json.dumps({"op": 1, "d": self.last_seq}).encode("utf-8")
                    ZaloSelfBotListener._send_ws_frame(sock, hb_pkt, opcode=0x1)
                    last_hb = time.time()

                try:
                    hdr = ZaloSelfBotListener._recv_exact(sock, 2)
                    if not hdr:
                        break
                    opcode = hdr[0] & 0x0F
                    masked = (hdr[1] & 0x80) != 0
                    payload_len = hdr[1] & 0x7F

                    if payload_len == 126:
                        ext = ZaloSelfBotListener._recv_exact(sock, 2)
                        if not ext:
                            break
                        payload_len = struct.unpack(">H", ext)[0]
                    elif payload_len == 127:
                        ext = ZaloSelfBotListener._recv_exact(sock, 8)
                        if not ext:
                            break
                        payload_len = struct.unpack(">Q", ext)[0]

                    mask_bytes = ZaloSelfBotListener._recv_exact(sock, 4) if masked else b""
                    data = ZaloSelfBotListener._recv_exact(sock, payload_len) if payload_len > 0 else b""
                    if data is None:
                        break
                    if masked and mask_bytes:
                        data = bytes(b ^ mask_bytes[i % 4] for i, b in enumerate(data))

                    if opcode == 0x8:
                        break
                    if opcode == 0x9:
                        ZaloSelfBotListener._send_ws_frame(sock, data, opcode=0xA)
                        continue

                    if opcode == 0x1 and data:
                        pkt = json.loads(data.decode("utf-8", errors="ignore"))
                        op = pkt.get("op")
                        seq = pkt.get("s")
                        if seq is not None:
                            self.last_seq = seq
                        t_ev = pkt.get("t")
                        d_ev = pkt.get("d")

                        if op == 10 and isinstance(d_ev, dict):
                            hb_interval = max(15.0, (float(d_ev.get("heartbeat_interval", 41250)) / 1000.0) * random.uniform(0.86, 0.94))
                            if client.is_bot:
                                ident_payload = {
                                    "op": 2,
                                    "d": {
                                        "token": client.token,
                                        "intents": 37377,
                                        "properties": {"os": "linux", "browser": "discord_client", "device": "discord_client"}
                                    }
                                }
                            else:
                                ident_payload = {
                                    "op": 2,
                                    "d": {
                                        "token": client.token,
                                        "capabilities": 16381,
                                        "properties": {
                                            "os": prof["os"],
                                            "browser": prof["browser"],
                                            "device": "",
                                            "system_locale": "vi-VN",
                                            "browser_user_agent": prof["ua"],
                                            "browser_version": prof["browser_version"],
                                            "os_version": prof["os_version"],
                                            "referrer": "",
                                            "referring_domain": "",
                                            "referrer_current": "",
                                            "referring_domain_current": "",
                                            "release_channel": "stable",
                                            "client_build_number": prof["build_number"],
                                            "client_event_source": None,
                                            "has_client_mods": False,
                                            "launch_signature": launch_sig,
                                            "client_heartbeat_session_id": hb_sess,
                                        },
                                        "presence": {"status": "online", "since": 0, "activities": [], "afk": False},
                                        "compress": False,
                                        "client_state": {
                                            "guild_versions": {},
                                            "highest_last_message_id": "0",
                                            "read_state_version": 0,
                                            "user_guild_settings_version": -1,
                                            "user_settings_version": -1,
                                            "private_channels_version": "0",
                                            "api_code_version": 0
                                        }
                                    }
                                }
                            ZaloSelfBotListener._send_ws_frame(sock, json.dumps(ident_payload).encode("utf-8"), opcode=0x1)
                            identified = True
                            last_hb = time.time()
                            self.ws_status = "Discord Anti-Die-All Shield"

                        elif op == 0 and t_ev == "READY" and isinstance(d_ev, dict):
                            self.ws_status = "Discord Anti-Die-All Shield"

                        elif op == 0 and t_ev == "MESSAGE_CREATE" and isinstance(d_ev, dict):
                            self.last_event_ts = time.time()
                            self._handle_discord_message_event(client, acc_now, d_ev)

                        elif op in (7, 9):
                            break
                except socket.timeout:
                    continue
                except Exception:
                    break
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _run_loop(self):
        while not self.stop_ev.is_set():
            acc_row = self._get_acc_row()
            if not acc_row or acc_row.get("platform") != "discord":
                break
            if not acc_row.get("chat_cmd_enabled", 1):
                self.ws_status = "Đã tắt nhận lệnh"
                self.stop_ev.wait(4.0)
                continue

            try:
                client = DiscordBot(acc_row["token"], is_bot=bool(acc_row.get("is_bot", 0)))
                if not client.check():
                    self.ws_status = "Token cần kiểm tra lại"
                    self.stop_ev.wait(10.0)
                    continue

                self._run_gateway_session(client, acc_row)
                self.stop_ev.wait(3.0)
            except Exception:
                self.ws_status = "Đang kết nối lại..."
                self.stop_ev.wait(5.0)


def sync_all_zalo_listeners():
    refresh_owner_uids()
    try:
        conn = db()
        rows = conn.execute("SELECT id, platform, chat_cmd_enabled FROM accounts").fetchall()
        conn.close()
        active_ids = set()
        for r in rows:
            aid = r["id"]
            plat = (r["platform"] or "zalo").lower()
            if r["chat_cmd_enabled"]:
                active_ids.add(aid)
                if aid not in ACTIVE_LISTENERS or not ACTIVE_LISTENERS[aid].thread.is_alive():
                    if plat == "discord":
                        listener = DiscordSelfBotListener(aid)
                    else:
                        listener = ZaloSelfBotListener(aid)
                    ACTIVE_LISTENERS[aid] = listener
                    listener.start()
        for aid in list(ACTIVE_LISTENERS.keys()):
            if aid not in active_ids:
                ACTIVE_LISTENERS[aid].stop()
                ACTIVE_LISTENERS.pop(aid, None)
    except Exception:
        pass


threading.Timer(1.2, sync_all_zalo_listeners).start()
# ============================================================
# GIAO DIỆN WEB CHÍNH: NOEL (100% VECTOR SVG HIỆN ĐẠI, CHỐNG TRÀN VIỀN TUYỆT ĐỐI,
# THANH TAB NGANG DƯỚI NHỎ GỌN HIỆN ĐẠI, NÚT BẤM CÓ HÌNH ẢNH DESIGN NOEL)
# ============================================================
LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>NOEL</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0;min-width:0;-webkit-tap-highlight-color:transparent}
html,body{
  width:100%;max-width:100%;overflow-x:hidden;
  touch-action:manipulation;-webkit-text-size-adjust:100%;
  font-family:'Plus Jakarta Sans',sans-serif;
  background:#f4f7f9;
  background-image:
    radial-gradient(at 10% 10%, rgba(201,42,42,0.09) 0px, transparent 48%),
    radial-gradient(at 90% 15%, rgba(13,104,71,0.10) 0px, transparent 48%),
    radial-gradient(at 50% 90%, rgba(217,119,6,0.08) 0px, transparent 50%);
  color:#0f172a;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px;
}
.login-card{
  width:100%;max-width:410px;background:#ffffff;
  border:1px solid #e2e8f0;border-radius:26px;overflow:hidden;
  box-shadow:0 20px 45px -12px rgba(15,23,42,0.10);position:relative;
}
.noel-art-banner{
  position:relative;height:148px;overflow:hidden;
  background:linear-gradient(135deg,#881337 0%,#be123c 45%,#065f46 100%);
  display:flex;flex-direction:column;align-items:center;justify-content:center;padding:18px;
}
.noel-art-svg{
  position:absolute;inset:0;width:100%;height:100%;object-fit:cover;pointer-events:none;opacity:0.92;
}
.brand-mark{
  position:relative;z-index:2;width:58px;height:58px;border-radius:18px;
  background:rgba(255,255,255,0.16);backdrop-filter:blur(10px);
  border:1.5px solid rgba(255,255,255,0.45);
  display:flex;align-items:center;justify-content:center;
  box-shadow:0 10px 24px rgba(0,0,0,0.22);margin-bottom:8px;overflow:hidden;
}
.brand-mark img{width:100%;height:100%;object-fit:cover}
.brand-title{
  position:relative;z-index:2;font-size:23px;font-weight:800;color:#ffffff;
  letter-spacing:2.5px;text-shadow:0 2px 10px rgba(0,0,0,0.25);
}
.login-body{padding:24px 20px 26px}
.field-label{
  display:flex;align-items:center;gap:6px;font-size:12px;font-weight:700;color:#334155;margin-bottom:8px;
}
.field-input{
  width:100%;padding:13px 14px;background:#f8fafc;border:1.5px solid #cbd5e1;
  border-radius:14px;color:#0f172a;font-size:16px;outline:none;transition:all .2s;margin-bottom:16px;
}
.field-input:focus{border-color:#be123c;background:#fff;box-shadow:0 0 0 3px rgba(190,18,60,0.12)}
.btn-noel-login{
  position:relative;overflow:hidden;width:100%;padding:13px 16px;
  background:linear-gradient(135deg,#be123c 0%,#9f1239 50%,#065f46 100%);
  color:#fff;font-weight:800;border:none;border-radius:14px;cursor:pointer;font-size:14px;
  display:flex;align-items:center;justify-content:center;gap:8px;
  box-shadow:0 10px 22px -6px rgba(190,18,60,0.45);transition:transform .18s;
}
.btn-noel-login:active{transform:scale(0.98)}
.btn-art-bg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;opacity:0.28}
.err-box{
  background:#fef2f2;border:1px solid #fecaca;color:#b91c1c;
  padding:11px 12px;border-radius:12px;font-size:12.5px;margin-bottom:14px;text-align:center;font-weight:600;
  overflow-wrap:break-word;word-break:break-word;
}
</style>
</head>
<body>
  <div class="login-card">
    <div class="noel-art-banner">
      <svg class="noel-art-svg" viewBox="0 0 420 160" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="lgGlow" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#fde68a" stop-opacity="0.35"/>
            <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
          </linearGradient>
        </defs>
        <circle cx="48" cy="34" r="32" fill="url(#lgGlow)"/>
        <circle cx="370" cy="28" r="3.5" fill="#fff" opacity="0.7"/>
        <circle cx="110" cy="22" r="2.2" fill="#fde68a" opacity="0.85"/>
        <circle cx="290" cy="40" r="2.5" fill="#fff" opacity="0.65"/>
        <circle cx="195" cy="18" r="3" fill="#fff" opacity="0.5"/>
        <path d="M0 132 Q95 108 210 128 T420 120 L420 160 L0 160 Z" fill="rgba(255,255,255,0.14)"/>
        <polygon points="34,135 54,82 74,135" fill="rgba(6,95,70,0.55)"/>
        <polygon points="40,105 54,68 68,105" fill="rgba(16,185,129,0.45)"/>
        <polygon points="348,136 372,74 396,136" fill="rgba(6,95,70,0.6)"/>
        <polygon points="354,104 372,58 390,104" fill="rgba(16,185,129,0.5)"/>
      </svg>
      <div class="brand-mark">
        {% if has_logo %}
          <img src="/api/logo?v={{ logo_ts }}" alt="NOEL">
        {% else %}
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L14.8 8.5L21 9.3L16.2 14L17.5 20.5L12 17.2L6.5 20.5L7.8 14L3 9.3L9.2 8.5L12 2Z" fill="#FDE68A" stroke="#FFF" stroke-width="1.5"/>
          </svg>
        {% endif %}
      </div>
      <div class="brand-title">NOEL</div>
    </div>
    <div class="login-body">
      {% if error %}<div class="err-box">{{ error }}</div>{% endif %}
      <form method="POST" action="/login">
        <label class="field-label">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#be123c" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
          <span>Mật khẩu truy cập</span>
        </label>
        <input class="field-input" type="password" name="password" placeholder="Nhập mật khẩu..." required autofocus>
        <button class="btn-noel-login" type="submit">
          <svg class="btn-art-bg" viewBox="0 0 300 50" preserveAspectRatio="none">
            <circle cx="25" cy="12" r="2" fill="#fff"/><circle cx="140" cy="38" r="1.8" fill="#fde68a"/><circle cx="265" cy="16" r="2.5" fill="#fff"/>
            <path d="M0 40 Q80 20 180 38 T300 28 L300 50 L0 50 Z" fill="rgba(255,255,255,0.18)"/>
          </svg>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>
          <span>ĐĂNG NHẬP NOEL</span>
        </button>
      </form>
    </div>
  </div>
</body>
</html>"""


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>NOEL</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg-main:#f3f6fa;
  --bg-card:#ffffff;
  --bg-soft:#f8fafc;
  --text-primary:#0f172a;
  --text-secondary:#334155;
  --text-muted:#64748b;
  --border-light:#e2e8f0;
  --noel-red:#be123c;
  --noel-red-soft:#ffe4e6;
  --noel-pine:#047857;
  --noel-pine-soft:#d1fae5;
  --noel-gold:#d97706;
  --noel-blue:#1d4ed8;
  --noel-indigo:#4f46e5;
  --shadow-card:0 8px 24px -6px rgba(15,23,42,0.06),0 2px 6px -1px rgba(15,23,42,0.03);
}
*{
  box-sizing:border-box;margin:0;padding:0;min-width:0;
  -webkit-tap-highlight-color:transparent;
}
html,body{
  width:100%;max-width:100vw;overflow-x:hidden;
  touch-action:manipulation;-webkit-text-size-adjust:100%;
  font-family:'Plus Jakarta Sans',sans-serif;
  background-color:var(--bg-main);
  background-image:
    radial-gradient(at 0% 0%, rgba(190,18,60,0.07) 0px, transparent 42%),
    radial-gradient(at 100% 0%, rgba(4,120,87,0.08) 0px, transparent 42%),
    radial-gradient(at 50% 100%, rgba(217,119,6,0.06) 0px, transparent 48%);
  color:var(--text-primary);
  min-height:100vh;
  padding-bottom:92px;
}
input,select,textarea{font-size:16px !important;font-family:inherit;max-width:100%}

.app-container{
  width:100%;max-width:1180px;margin:0 auto;padding:10px 10px 24px;
  overflow-x:hidden;
}

.noel-hero{
  position:relative;overflow:hidden;
  border-radius:22px;margin-bottom:12px;
  background:linear-gradient(125deg,#881337 0%,#be123c 46%,#065f46 100%);
  box-shadow:0 12px 28px -8px rgba(136,19,55,0.32);
  color:#ffffff;padding:14px 14px;
}
.noel-hero-art{
  position:absolute;inset:0;width:100%;height:100%;pointer-events:none;opacity:0.9;
}
.hero-top-row{
  position:relative;z-index:2;display:flex;align-items:center;justify-content:space-between;
  gap:8px;flex-wrap:wrap;
}
.brand-cluster{
  display:flex;align-items:center;gap:10px;min-width:0;
}
.logo-frame{
  width:42px;height:42px;border-radius:13px;
  background:rgba(255,255,255,0.18);backdrop-filter:blur(8px);
  border:1.5px solid rgba(255,255,255,0.5);
  display:flex;align-items:center;justify-content:center;
  overflow:hidden;cursor:pointer;flex-shrink:0;position:relative;
  box-shadow:0 6px 16px rgba(0,0,0,0.18);
}
.logo-frame img{width:100%;height:100%;object-fit:cover}
.brand-name{
  font-size:20px;font-weight:800;letter-spacing:2px;color:#ffffff;
  text-shadow:0 2px 8px rgba(0,0,0,0.22);line-height:1.1;
}
.hero-actions{
  display:flex;align-items:center;gap:6px;flex-wrap:wrap;
}
.hero-pill-btn{
  position:relative;overflow:hidden;
  display:inline-flex;align-items:center;gap:5px;
  padding:7px 11px;border-radius:11px;
  background:rgba(255,255,255,0.16);backdrop-filter:blur(8px);
  border:1px solid rgba(255,255,255,0.35);
  color:#ffffff;font-size:11.5px;font-weight:700;cursor:pointer;
  text-decoration:none;transition:all .18s;
}
.hero-pill-btn:hover{background:rgba(255,255,255,0.26)}
.hero-pill-btn svg{flex-shrink:0}

.kpi-strip{
  display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:12px;
}
@media(max-width:640px){
  .kpi-strip{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}
}
.kpi-card{
  position:relative;overflow:hidden;
  background:var(--bg-card);border:1px solid var(--border-light);
  border-radius:16px;padding:11px 12px;
  display:flex;align-items:center;justify-content:space-between;gap:8px;
  box-shadow:var(--shadow-card);
}
.kpi-art-bg{
  position:absolute;right:0;bottom:0;width:84px;height:56px;pointer-events:none;opacity:0.25;
}
.kpi-info{min-width:0;position:relative;z-index:1}
.kpi-label{
  font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:0.4px;
  color:var(--text-muted);margin-bottom:3px;
  overflow-wrap:break-word;word-break:break-word;
}
.kpi-val{font-size:19px;font-weight:800;font-family:'JetBrains Mono',monospace;line-height:1.1}
.kpi-icon-box{
  position:relative;z-index:1;width:36px;height:36px;border-radius:11px;
  display:flex;align-items:center;justify-content:center;flex-shrink:0;
}

.tab-section{display:none;animation:fadeSlide .2s ease}
.tab-section.active{display:block}
@keyframes fadeSlide{
  from{opacity:0;transform:translateY(5px)}
  to{opacity:1;transform:translateY(0)}
}

.panel-grid{
  display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:12px;width:100%;
}
.col-5{grid-column:span 5;min-width:0}
.col-6{grid-column:span 6;min-width:0}
.col-7{grid-column:span 7;min-width:0}
.col-12{grid-column:span 12;min-width:0}
@media(max-width:960px){
  .col-5,.col-6,.col-7{grid-column:span 12}
}

.card{
  position:relative;overflow:hidden;
  background:var(--bg-card);border:1px solid var(--border-light);
  border-radius:20px;padding:14px;box-shadow:var(--shadow-card);
  margin-bottom:12px;width:100%;max-width:100%;
}
.card-corner-art{
  position:absolute;top:0;right:0;width:110px;height:70px;pointer-events:none;opacity:0.22;
}
.card-head{
  position:relative;z-index:1;
  display:flex;align-items:center;justify-content:space-between;
  gap:8px;margin-bottom:12px;padding-bottom:10px;
  border-bottom:1px solid #f1f5f9;flex-wrap:wrap;
}
.card-title{
  font-size:14px;font-weight:800;color:var(--text-primary);
  display:flex;align-items:center;gap:8px;min-width:0;flex:1;
  overflow-wrap:break-word;word-break:break-word;line-height:1.3;
}
.card-title-icon{
  width:28px;height:28px;border-radius:9px;
  display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;
}
.badge{
  display:inline-flex;align-items:center;gap:4px;
  padding:4px 9px;border-radius:999px;font-size:10.5px;font-weight:800;
  max-width:100%;white-space:normal;text-align:center;line-height:1.2;flex-shrink:0;
}
.badge-red{background:var(--noel-red-soft);color:var(--noel-red)}
.badge-green{background:var(--noel-pine-soft);color:var(--noel-pine)}
.badge-blue{background:#dbeafe;color:#1d4ed8}
.badge-purple{background:#ede9fe;color:#6d28d9}
.badge-amber{background:#fef3c7;color:#b45309}

.form-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:9px;width:100%}
.form-row-3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:9px;width:100%}
@media(max-width:560px){
  .form-row,.form-row-3{grid-template-columns:minmax(0,1fr)}
}
.sub-label{
  display:block;font-size:11.5px;font-weight:700;color:var(--text-secondary);
  margin-bottom:4px;overflow-wrap:break-word;word-break:break-word;line-height:1.3;
}
.form-input,.form-select,.form-textarea{
  width:100%;max-width:100%;padding:9px 11px;background:var(--bg-soft);
  border:1.5px solid #cbd5e1;border-radius:12px;color:var(--text-primary);
  outline:none;transition:all .18s;
}
.form-input:focus,.form-select:focus,.form-textarea:focus{
  border-color:var(--noel-red);background:#fff;box-shadow:0 0 0 3px rgba(190,18,60,0.10);
}
.form-textarea{resize:vertical;min-height:70px;line-height:1.45}

.seg-bar{
  display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;
  background:#f1f5f9;padding:5px;border-radius:14px;margin-bottom:12px;
  border:1px solid #e2e8f0;width:100%;max-width:100%;
}
.seg-btn{
  position:relative;overflow:hidden;
  padding:8px 6px;border:none;border-radius:10px;background:transparent;
  color:var(--text-secondary);font-size:11.5px;font-weight:700;cursor:pointer;
  transition:all .18s;display:flex;align-items:center;justify-content:center;gap:6px;
  white-space:normal;text-align:center;line-height:1.25;width:100%;
}
.seg-btn svg{flex-shrink:0}
.seg-btn.active{
  background:#ffffff;color:var(--noel-red);
  box-shadow:0 3px 10px rgba(15,23,42,0.08);
  border:1px solid rgba(190,18,60,0.18);
}

.btn{
  position:relative;overflow:hidden;
  padding:10px 12px;border-radius:13px;border:none;font-weight:800;font-size:12.5px;
  cursor:pointer;transition:all .18s;
  display:inline-flex;align-items:center;justify-content:center;gap:7px;
  width:100%;max-width:100%;white-space:normal;text-align:center;line-height:1.3;
  overflow-wrap:break-word;word-break:break-word;
}
.btn svg.btn-ico{flex-shrink:0;position:relative;z-index:2}
.btn span{position:relative;z-index:2;min-width:0}
.btn::before{
  content:"";position:absolute;inset:0;pointer-events:none;opacity:0.26;
  background-image:
    radial-gradient(circle at 14% 25%, rgba(255,255,255,0.65) 0, rgba(255,255,255,0.65) 2px, transparent 2.5px),
    radial-gradient(circle at 85% 30%, rgba(253,230,138,0.75) 0, rgba(253,230,138,0.75) 2.2px, transparent 3px),
    radial-gradient(circle at 52% 78%, rgba(255,255,255,0.5) 0, rgba(255,255,255,0.5) 1.8px, transparent 2.5px),
    linear-gradient(120deg, rgba(255,255,255,0.22) 0%, transparent 45%, rgba(255,255,255,0.12) 100%);
}
.btn:active{transform:scale(0.98)}
.btn-primary{
  background:linear-gradient(135deg,#be123c 0%,#9f1239 55%,#047857 100%);
  color:#fff;box-shadow:0 8px 18px -5px rgba(190,18,60,0.38);
}
.btn-indigo{
  background:linear-gradient(135deg,#4338ca 0%,#6d28d9 60%,#be123c 100%);
  color:#fff;box-shadow:0 8px 18px -5px rgba(79,70,229,0.35);
}
.btn-emerald{
  background:linear-gradient(135deg,#047857 0%,#059669 60%,#0d9488 100%);
  color:#fff;box-shadow:0 8px 18px -5px rgba(4,120,87,0.35);
}
.btn-danger{
  background:linear-gradient(135deg,#dc2626 0%,#b91c1c 100%);
  color:#fff;box-shadow:0 6px 14px -4px rgba(220,38,38,0.32);
}
.btn-soft{
  background:#f1f5f9;color:var(--text-secondary);border:1px solid #cbd5e1;
}
.btn-soft::before{display:none}
.btn-soft:hover{background:#e2e8f0;color:var(--text-primary)}
.btn-sm{padding:6px 10px;font-size:11.5px;border-radius:10px;width:auto}

.check-pill{
  display:flex;align-items:flex-start;gap:8px;padding:9px 10px;
  background:var(--bg-soft);border:1px solid #e2e8f0;border-radius:12px;
  font-size:12px;font-weight:600;color:var(--text-secondary);cursor:pointer;
  width:100%;max-width:100%;overflow-wrap:anywhere;word-break:break-word;line-height:1.35;
}
.check-pill input{
  width:16px;height:16px;accent-color:var(--noel-red);flex-shrink:0;margin-top:1px;
}
.check-pill span{flex:1;min-width:0;overflow-wrap:anywhere;word-break:break-word}

.upload-zone{
  position:relative;border:2px dashed #fda4af;border-radius:16px;
  background:linear-gradient(180deg,#fff1f2 0%,#f8fafc 100%);
  padding:16px 12px;text-align:center;cursor:pointer;transition:all .2s;margin-bottom:10px;
  overflow:hidden;width:100%;
}
.upload-zone:hover,.upload-zone.dragover{
  border-color:var(--noel-red);background:#ffe4e6;
}
.upload-zone input[type="file"]{
  position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%;
}
.upload-icon-circle{
  width:42px;height:42px;border-radius:13px;background:#ffffff;color:var(--noel-red);
  display:inline-flex;align-items:center;justify-content:center;margin-bottom:6px;
  box-shadow:0 4px 12px rgba(190,18,60,0.12);
}
.upload-progress-wrap{
  display:none;margin-top:8px;background:#e2e8f0;border-radius:999px;height:7px;overflow:hidden;
}
.upload-progress-bar{
  height:100%;width:0%;background:linear-gradient(90deg,#be123c,#047857);transition:width .25s ease;
}

.scroll-box{
  max-height:280px;overflow-y:auto;overflow-x:hidden;padding-right:2px;width:100%;
}
.scroll-box::-webkit-scrollbar{width:4px}
.scroll-box::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:4px}

.list-item{
  display:flex;align-items:center;justify-content:space-between;gap:8px;
  padding:9px 10px;background:var(--bg-soft);border:1px solid #e2e8f0;
  border-radius:13px;margin-bottom:7px;transition:all .15s;
  width:100%;max-width:100%;flex-wrap:wrap;
}
.list-item:hover{border-color:#fda4af;background:#ffffff}
.item-title{
  font-size:12.5px;font-weight:700;color:var(--text-primary);
  overflow-wrap:anywhere;word-break:break-word;line-height:1.3;
}
.item-sub{
  font-size:11px;color:var(--text-muted);margin-top:2px;
  overflow-wrap:anywhere;word-break:break-word;line-height:1.3;
}

.info-banner{
  background:linear-gradient(135deg,#fff1f2 0%,#ecfdf5 100%);
  border:1px solid #fecdd3;border-radius:13px;padding:10px 11px;
  font-size:11.5px;color:#881337;line-height:1.45;margin-bottom:10px;
  overflow-wrap:anywhere;word-break:break-word;width:100%;
}

.bottom-dock-wrap{
  position:fixed;bottom:10px;left:50%;transform:translateX(-50%);
  z-index:999;width:calc(100vw - 16px);max-width:470px;
  background:rgba(255,255,255,0.94);backdrop-filter:blur(16px);
  border:1.5px solid #cbd5e1;border-radius:18px;padding:4px;
  box-shadow:0 14px 32px -6px rgba(15,23,42,0.18),0 4px 10px -2px rgba(190,18,60,0.10);
}
.bottom-dock{
  display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:3px;width:100%;
}
.tab-btn{
  position:relative;overflow:hidden;
  padding:5px 2px;border-radius:13px;border:none;background:transparent;
  color:var(--text-muted);font-weight:700;font-size:10.5px;cursor:pointer;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;
  transition:all .18s;line-height:1.15;text-align:center;min-width:0;
}
.tab-btn svg.tab-ico{
  width:17px;height:17px;flex-shrink:0;transition:transform .18s;
}
.tab-btn .tab-lbl{
  display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-size:10px;letter-spacing:-0.1px;
}
.tab-btn:hover{color:var(--text-primary);background:#f1f5f9}
.tab-btn.active{
  background:linear-gradient(135deg,#be123c 0%,#047857 100%);
  color:#ffffff;box-shadow:0 4px 12px -2px rgba(190,18,60,0.40);
}
.tab-btn.active svg.tab-ico{transform:translateY(-1px)}
.tab-count{
  position:absolute;top:2px;right:4px;
  padding:1px 4.5px;border-radius:999px;font-size:9px;font-weight:800;
  background:#e2e8f0;color:#334155;line-height:1.2;
}
.tab-btn.active .tab-count{
  background:#fde68a;color:#881337;
}

#toastBox{
  position:fixed;top:14px;right:14px;left:14px;z-index:9999;
  display:flex;flex-direction:column;align-items:flex-end;gap:7px;pointer-events:none;
}
.toast-msg{
  background:#0f172a;color:#fff;padding:10px 14px;border-radius:13px;
  font-size:12px;font-weight:700;box-shadow:0 10px 24px rgba(15,23,42,0.22);
  display:flex;align-items:center;gap:8px;max-width:100%;
  overflow-wrap:anywhere;word-break:break-word;
}
</style>
</head>
<body>
<div id="toastBox"></div>

<div class="app-container">
  <header class="noel-hero">
    <svg class="noel-hero-art" viewBox="0 0 900 120" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="snowHill" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="#ffffff" stop-opacity="0.18"/>
          <stop offset="50%" stop-color="#fde68a" stop-opacity="0.12"/>
          <stop offset="100%" stop-color="#ffffff" stop-opacity="0.20"/>
        </linearGradient>
      </defs>
      <circle cx="80" cy="24" r="2.5" fill="#fff" opacity="0.75"/>
      <circle cx="195" cy="18" r="1.8" fill="#fde68a" opacity="0.85"/>
      <circle cx="340" cy="30" r="2.4" fill="#fff" opacity="0.65"/>
      <circle cx="520" cy="20" r="3" fill="#fff" opacity="0.7"/>
      <circle cx="690" cy="28" r="2" fill="#fde68a" opacity="0.8"/>
      <circle cx="830" cy="18" r="2.8" fill="#fff" opacity="0.75"/>
      <polygon points="440,115 462,48 484,115" fill="rgba(6,95,70,0.45)"/>
      <polygon points="475,115 494,62 513,115" fill="rgba(16,185,129,0.35)"/>
      <polygon points="760,115 785,42 810,115" fill="rgba(6,95,70,0.5)"/>
      <path d="M0 94 Q220 68 450 92 T900 82 L900 120 L0 120 Z" fill="url(#snowHill)"/>
    </svg>

    <div class="hero-top-row">
      <div class="brand-cluster">
        <label class="logo-frame" title="Nhấn để tải Logo mới">
          <input type="file" id="logoInput" accept="image/*" style="display:none" onchange="uploadBrandLogo(this)">
          <img id="brandLogoImg" src="/api/logo?v={{ logo_ts }}" alt="NOEL" style="{% if not has_logo %}display:none{% endif %}">
          <svg id="brandLogoFallback" width="24" height="24" viewBox="0 0 24 24" fill="none" style="{% if has_logo %}display:none{% endif %}">
            <path d="M12 2L14.8 8.5L21 9.3L16.2 14L17.5 20.5L12 17.2L6.5 20.5L7.8 14L3 9.3L9.2 8.5L12 2Z" fill="#FDE68A" stroke="#FFFFFF" stroke-width="1.6"/>
          </svg>
        </label>
        <div class="brand-name">NOEL</div>
      </div>

      <div class="hero-actions">
        <button class="hero-pill-btn" type="button" onclick="document.getElementById('logoInput').click()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          <span>Đổi Logo</span>
        </button>
        <a href="/logout" class="hero-pill-btn">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
          <span>Thoát</span>
        </a>
      </div>
    </div>
  </header>

  <div class="kpi-strip">
    <div class="kpi-card">
      <svg class="kpi-art-bg" viewBox="0 0 100 60"><circle cx="80" cy="45" r="28" fill="#be123c"/><circle cx="45" cy="52" r="14" fill="#fda4af"/></svg>
      <div class="kpi-info">
        <div class="kpi-label">Tài Khoản</div>
        <div class="kpi-val" style="color:var(--noel-red)" id="kpiAccCount">{{ accounts|length }}</div>
      </div>
      <div class="kpi-icon-box" style="background:var(--noel-red-soft);color:var(--noel-red)">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
      </div>
    </div>

    <div class="kpi-card">
      <svg class="kpi-art-bg" viewBox="0 0 100 60"><polygon points="65,60 82,15 99,60" fill="#047857"/><circle cx="50" cy="48" r="15" fill="#6ee7b7"/></svg>
      <div class="kpi-info">
        <div class="kpi-label">Phòng Chọn</div>
        <div class="kpi-val" style="color:var(--noel-pine)" id="kpiTargetCount">0</div>
      </div>
      <div class="kpi-icon-box" style="background:var(--noel-pine-soft);color:var(--noel-pine)">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
      </div>
    </div>

    <div class="kpi-card">
      <svg class="kpi-art-bg" viewBox="0 0 100 60"><path d="M30 60 Q65 20 100 45 L100 60 Z" fill="#1d4ed8"/></svg>
      <div class="kpi-info">
        <div class="kpi-label">Đang Chạy</div>
        <div class="kpi-val" style="color:var(--noel-blue)" id="kpiRunningTasks">0</div>
      </div>
      <div class="kpi-icon-box" style="background:#dbeafe;color:var(--noel-blue)">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
      </div>
    </div>

    <div class="kpi-card">
      <svg class="kpi-art-bg" viewBox="0 0 100 60"><circle cx="78" cy="42" r="24" fill="#d97706"/></svg>
      <div class="kpi-info">
        <div class="kpi-label">Tin Đã Phát</div>
        <div class="kpi-val" style="color:var(--noel-gold)" id="kpiTotalSent">0</div>
      </div>
      <div class="kpi-icon-box" style="background:#fef3c7;color:var(--noel-gold)">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      </div>
    </div>
  </div>

  <!-- TAB 1: KẾT NỐI TÀI KHOẢN & REG DISCORD ANTI-SCAN -->
  <section id="tab-accounts" class="tab-section active">
    <div class="panel-grid">
      <div class="col-5">
        <div class="card">
          <svg class="card-corner-art" viewBox="0 0 120 80"><circle cx="95" cy="15" r="36" fill="#be123c"/><polygon points="60,80 80,30 100,80" fill="#047857"/></svg>
          <div class="card-head">
            <div class="card-title">
              <span class="card-title-icon" style="background:var(--noel-red-soft);color:var(--noel-red)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
              </span>
              <span>Kết Nối Tài Khoản & Reg Discord</span>
            </div>
            <span class="badge badge-green">Anti-Die-All 24/7</span>
          </div>

          <form method="POST" action="/account/add">
            <input type="hidden" name="platform" id="accPlatformInput" value="zalo">

            <div class="seg-bar">
              <button type="button" class="seg-btn active" id="segZaloBtn" onclick="switchAccForm('zalo')">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
                <span>Zalo (IMEI + Cookie)</span>
              </button>
              <button type="button" class="seg-btn" id="segDiscordBtn" onclick="switchAccForm('discord')">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="13" rx="4"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/></svg>
                <span>Discord (Stealth + Reg)</span>
              </button>
            </div>

            <div style="margin-bottom:9px">
              <label class="sub-label">Tên gợi nhớ (Tùy chọn)</label>
              <input class="form-input" name="name" placeholder="Để trống hệ thống tự lấy tên thật...">
            </div>

            <div id="zaloInputFields">
              <div style="margin-bottom:9px">
                <label class="sub-label">IMEI Zalo Web</label>
                <input class="form-input" name="imei" placeholder="Dán chuỗi IMEI Zalo...">
              </div>
              <div style="margin-bottom:9px">
                <label class="sub-label">Cookie Zalo (JSON hoặc chuỗi Cookie)</label>
                <textarea class="form-textarea" name="cookies" placeholder='{"zpw_sek":"..."} hoặc dán thẳng Cookie...'></textarea>
              </div>
            </div>

            <div id="discordInputFields" style="display:none">
              <div class="seg-bar" style="margin-bottom:9px">
                <button type="button" class="seg-btn active" id="subDisTokenBtn" onclick="switchDiscordRegTab('token')">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
                  <span>Dán Token / Chuỗi Reg</span>
                </button>
                <button type="button" class="seg-btn" id="subDisLoginBtn" onclick="switchDiscordRegTab('login')">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                  <span>Reg Phiên Bằng Email</span>
                </button>
              </div>

              <div id="discordTokenBox">
                <div class="info-banner">
                  <strong>Anti-Die-All Discord:</strong> Dán Token đơn hoặc danh sách Reg <code>email:pass:token</code> (mỗi dòng 1 nick). Tự động khóa định danh phần cứng <code>launch_signature</code> + <code>X-Context-Properties</code> chống quét.
                </div>
                <label class="sub-label">Token Discord hoặc Chuỗi Reg</label>
                <textarea class="form-textarea" name="token" id="discordTokenInput" placeholder="Dán Token hoặc email:pass:token..."></textarea>
                <label class="check-pill" style="margin-top:8px;margin-bottom:8px">
                  <input type="checkbox" name="is_bot" value="1">
                  <span>Đây là Bot Token (Chỉ bật nếu dùng Bot Developer)</span>
                </label>
              </div>

              <div id="discordLoginBox" style="display:none;margin-bottom:9px">
                <div class="info-banner">
                  Khởi tạo <code>X-Fingerprint</code> chuẩn Chrome 131 để lấy Token sạch hạn chế checkpoint:
                </div>
                <div style="margin-bottom:8px">
                  <label class="sub-label">Email hoặc SĐT Discord</label>
                  <input class="form-input" id="regDisEmail" placeholder="nhap_email@gmail.com">
                </div>
                <div class="form-row">
                  <div>
                    <label class="sub-label">Mật khẩu</label>
                    <input class="form-input" type="password" id="regDisPass" placeholder="Mật khẩu...">
                  </div>
                  <div>
                    <label class="sub-label">Mã 2FA (Nếu có)</label>
                    <input class="form-input" id="regDis2FA" placeholder="6 số 2FA...">
                  </div>
                </div>
                <button type="button" class="btn btn-indigo" onclick="extractDiscordTokenByReg()">
                  <svg class="btn-ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>
                  <span>LẤY TOKEN REG SẠCH & LƯU</span>
                </button>
              </div>
            </div>

            <div style="display:flex;flex-direction:column;gap:7px;margin-bottom:12px">
              <label class="check-pill">
                <input type="checkbox" name="chat_cmd_enabled" value="1" checked>
                <span>Bật nhận lệnh trong khung chat 24/7 ( .menu , .nhay , .ngon , .stop )</span>
              </label>
              <label class="check-pill">
                <input type="checkbox" name="allow_all_cmd" value="1">
                <span>Cho phép mọi người trong phòng dùng lệnh</span>
              </label>
            </div>

            <button class="btn btn-primary" type="submit">
              <svg class="btn-ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span>KẾT NỐI TÀI KHOẢN & BẬT ANTI-BAN</span>
            </button>
          </form>
        </div>
      </div>

      <div class="col-7">
        <div class="card">
          <svg class="card-corner-art" viewBox="0 0 120 80"><polygon points="75,80 95,22 115,80" fill="#047857"/><circle cx="55" cy="24" r="18" fill="#fde68a"/></svg>
          <div class="card-head">
            <div class="card-title">
              <span class="card-title-icon" style="background:var(--noel-pine-soft);color:var(--noel-pine)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="3"/><path d="M6 8h.01"/><path d="M10 8h8"/><path d="M6 12h.01"/><path d="M10 12h8"/></svg>
              </span>
              <span>Danh Sách Tài Khoản Đang Bảo Vệ ({{ accounts|length }})</span>
            </div>
            <button class="btn btn-soft btn-sm" type="button" onclick="loadGroupsAndRooms(false)">
              <svg class="btn-ico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
              <span>Đồng Bộ Phòng</span>
            </button>
          </div>

          <div class="scroll-box" style="max-height:460px">
            {% if not accounts %}
              <div style="text-align:center;padding:30px 14px;color:var(--text-muted);font-size:12.5px">
                Chưa có tài khoản nào. Hãy kết nối Zalo hoặc Discord ở khung bên cạnh.
              </div>
            {% endif %}
            {% for a in accounts %}
              <div class="list-item">
                <div style="min-width:0;flex:1">
                  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
                    <span class="badge {% if a.platform == 'discord' %}badge-purple{% else %}badge-blue{% endif %}">
                      {{ 'DISCORD STEALTH' if a.platform == 'discord' else 'ZALO SHIELD' }}
                    </span>
                    <span class="item-title">{{ a.masked_name }}</span>
                    <span class="badge badge-green">Anti-Die-All</span>
                  </div>
                  <div class="item-sub">
                    ID ẩn: <code>{{ a.masked_uid }}</code> • Lệnh 24/7: <strong>{{ 'BẬT' if a.chat_cmd_enabled else 'TẮT' }}</strong>
                  </div>
                </div>
                <div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap">
                  <button class="btn btn-soft btn-sm" type="button" onclick="toggleAccCmd({{ a.id }}, {{ 0 if a.chat_cmd_enabled else 1 }})">
                    <span>{{ 'Tắt Lệnh' if a.chat_cmd_enabled else 'Bật Lệnh' }}</span>
                  </button>
                  <button class="btn btn-soft btn-sm" type="button" onclick="toggleAccAllowAll({{ a.id }}, {{ 0 if a.allow_all_cmd else 1 }})">
                    <span>{{ 'Chỉ Chủ Acc' if a.allow_all_cmd else 'Mở Cho Nhóm' }}</span>
                  </button>
                  <a href="/account/delete/{{ a.id }}" class="btn btn-danger btn-sm" style="text-decoration:none">
                    <span>Xóa</span>
                  </a>
                </div>
              </div>
            {% endfor %}
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- TAB 2: PHÒNG CHAT & TAG THẬT CHUẨN KHUNG CHAT -->
  <section id="tab-targets" class="tab-section">
    <div class="panel-grid">
      <div class="col-6">
        <div class="card">
          <svg class="card-corner-art" viewBox="0 0 120 80"><circle cx="92" cy="18" r="32" fill="#047857"/></svg>
          <div class="card-head">
            <div class="card-title">
              <span class="card-title-icon" style="background:var(--noel-pine-soft);color:var(--noel-pine)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
              </span>
              <span>Danh Sách Phòng Chat (Zalo & Discord)</span>
            </div>
            <div style="display:flex;gap:5px;flex-wrap:wrap">
              <button class="btn btn-soft btn-sm" type="button" onclick="loadGroupsAndRooms(true)">Làm Mới</button>
              <button class="btn btn-soft btn-sm" type="button" onclick="selectAllTargets()">Chọn Hết</button>
              <button class="btn btn-soft btn-sm" type="button" onclick="clearAllTargets()">Bỏ Chọn</button>
            </div>
          </div>

          <div class="form-row">
            <input class="form-input" id="roomSearchInput" placeholder="Tìm tên nhóm hoặc ID..." oninput="renderTargetList()">
            <div style="display:flex;gap:6px">
              <input class="form-input" id="manualDiscordChannel" placeholder="Nhập Channel ID Discord...">
              <button class="btn btn-indigo btn-sm" type="button" onclick="addDiscordChannelManual()">+ Thêm</button>
            </div>
          </div>

          <div class="scroll-box" id="targetListContainer" style="max-height:360px">
            <div style="text-align:center;padding:24px;color:var(--text-muted);font-size:12.5px">
              Nhấn "Làm Mới" để tải danh sách nhóm Zalo & kênh Discord...
            </div>
          </div>
        </div>
      </div>

      <div class="col-6">
        <div class="card">
          <svg class="card-corner-art" viewBox="0 0 120 80"><circle cx="90" cy="18" r="30" fill="#be123c"/></svg>
          <div class="card-head">
            <div class="card-title">
              <span class="card-title-icon" style="background:var(--noel-red-soft);color:var(--noel-red)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94"/></svg>
              </span>
              <span>Tag Tên Thật Chuẩn Khung Chat (Zalo + Discord)</span>
            </div>
            <span class="badge badge-red" id="selectedTagBadge">0 người được tag</span>
          </div>

          <div class="info-banner">
            <strong>Đã nâng cấp Endpoint <code>/api/group/mention</code>:</strong> Nhấn nút <strong>"Lấy Thành Viên"</strong> bên cạnh bất kỳ nhóm Zalo hoặc kênh Discord nào để chọn người cần Tag Xanh Dương thật 100%, hoặc gõ thẳng <code>.nhay 1 @Tên</code> trong khung chat!
          </div>

          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:9px;flex-wrap:wrap">
            <label class="check-pill" style="flex:1">
              <input type="checkbox" id="chkTagAll" onchange="updateTagSummary()">
              <span>Tag @All ( Báo hiệu tất cả thành viên )</span>
            </label>
            <button class="btn btn-soft btn-sm" type="button" onclick="selectAllMembersInBox()">Tag Cả Nhóm</button>
            <button class="btn btn-soft btn-sm" type="button" onclick="clearSelectedMentions()">Xóa Tag</button>
          </div>

          <div class="form-row">
            <input class="form-input" id="memberSearchInput" placeholder="Lọc tên thành viên trong nhóm..." oninput="renderMemberList()">
            <div style="display:flex;gap:6px">
              <input class="form-input" id="manualTagUid" placeholder="UID Zalo / Discord ID...">
              <input class="form-input" id="manualTagName" placeholder="Tên hiển thị...">
              <button class="btn btn-primary btn-sm" type="button" onclick="addManualMention()">+ Tag</button>
            </div>
          </div>

          <div class="scroll-box" id="memberListContainer" style="max-height:290px">
            <div style="text-align:center;padding:24px;color:var(--text-muted);font-size:12.5px">
              Chọn nút "Lấy Thành Viên" ở 1 nhóm bên trái để hiển thị danh sách thành viên thật...
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- TAB 3: PHÁT CHIẾN DỊCH & LÁ CHẮN ANTI-DIE-ALL -->
  <section id="tab-campaign" class="tab-section">
    <div class="panel-grid">
      <div class="col-7">
        <div class="card">
          <svg class="card-corner-art" viewBox="0 0 120 80"><polygon points="65,80 90,18 115,80" fill="#be123c"/></svg>
          <div class="card-head">
            <div class="card-title">
              <span class="card-title-icon" style="background:var(--noel-red-soft);color:var(--noel-red)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
              </span>
              <span>Khởi Chạy Chiến Dịch Tự Động Đa Luồng</span>
            </div>
            <span class="badge badge-green">Zalo Native + Discord Bung Chữ</span>
          </div>

          <div class="form-row-3">
            <div>
              <label class="sub-label">Chế độ gửi</label>
              <select class="form-select" id="cfgMode">
                <option value="treo_nhay">Treo Nhây (Từng dòng sạch)</option>
                <option value="treo_ngon">Treo Ngôn (Nguyên bài)</option>
                <option value="fast">Spam Tốc Độ Cao</option>
              </select>
            </div>
            <div>
              <label class="sub-label">Chế độ màu chữ</label>
              <select class="form-select" id="cfgColorMode">
                <option value="rainbow">Cầu Vồng Từng Dòng</option>
                <option value="word_rainbow">Phối Màu Từng Từ</option>
                <option value="random">Đổi Màu Ngẫu Nhiên</option>
                <option value="fixed">Màu Cố Định</option>
                <option value="none">Chữ Mặc Định</option>
              </select>
            </div>
            <div>
              <label class="sub-label">Màu cố định</label>
              <select class="form-select" id="cfgFixedColor">
                <option value="red">Đỏ Noel</option>
                <option value="yellow">Vàng Hoàng Gia</option>
                <option value="green">Xanh Lá Thông</option>
                <option value="orange">Cam Rực Rỡ</option>
              </select>
            </div>
          </div>

          <div class="form-row-3">
            <div>
              <label class="sub-label">Delay cơ bản (Giây)</label>
              <input class="form-input" type="number" step="0.1" min="0.2" id="cfgDelay" value="1.0">
            </div>
            <div>
              <label class="sub-label">Số lượng Icon VIP (0-10)</label>
              <input class="form-input" type="number" min="0" max="10" id="cfgIconCount" value="3">
            </div>
            <div>
              <label class="sub-label">Chọn File Kịch Bản</label>
              <select class="form-select" id="cfgFileSelect">
                <option value="">-- Dùng văn bản nhập tay bên dưới --</option>
                {% for f in files %}
                  <option value="{{ f.id }}">File số {{ f.display_num }}: {{ f.filename }} ({{ f.lines_count }} dòng)</option>
                {% endfor %}
              </select>
            </div>
          </div>

          <div style="margin-bottom:9px">
            <label class="sub-label">Nội dung gửi trực tiếp (Ngăn cách câu bằng dấu ; hoặc xuống dòng)</label>
            <textarea class="form-textarea" id="cfgRawText" placeholder="Nhập nội dung hoặc chọn File kịch bản ở trên... Có thể gõ kèm @Tên ở cuối để tự động Tag!"></textarea>
          </div>

          <div class="form-row" style="margin-bottom:12px">
            <label class="check-pill">
              <input type="checkbox" id="cfgHeading" checked>
              <span>Chữ lớn In Đậm (Zalo Heading / Discord Bung Chữ)</span>
            </label>
            <label class="check-pill">
              <input type="checkbox" id="cfgUseEmoji" checked>
              <span>Đính kèm Icon VIP Zalo (Đã diệt sạch lỗi :- )</span>
            </label>
            <label class="check-pill">
              <input type="checkbox" id="cfgAntiband" checked>
              <span>Bật Anti-Ban Đa Tầng (Zalo + Discord Stealth)</span>
            </label>
            <label class="check-pill">
              <input type="checkbox" id="cfgMultiAcc" checked>
              <span>Đồng bộ tất cả tài khoản + Anti-Die-All</span>
            </label>
          </div>

          <div class="form-row">
            <button class="btn btn-primary" type="button" onclick="launchCampaignTask()">
              <svg class="btn-ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>BẮT ĐẦU PHÁT CHIẾN DỊCH</span>
            </button>
            <button class="btn btn-danger" type="button" onclick="stopAllRunningTasks()">
              <svg class="btn-ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
              <span>DỪNG TẤT CẢ TIẾN TRÌNH</span>
            </button>
          </div>
        </div>
      </div>

      <div class="col-5">
        <div class="card">
          <div class="card-head">
            <div class="card-title">
              <span class="card-title-icon" style="background:#dbeafe;color:var(--noel-blue)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
              </span>
              <span>Tiến Trình Đang Hoạt Động</span>
            </div>
            <span class="badge badge-blue">Thời Gian Thực</span>
          </div>
          <div class="scroll-box" id="activeTasksContainer" style="max-height:380px">
            <div style="text-align:center;padding:24px;color:var(--text-muted);font-size:12.5px">
              Chưa có chiến dịch nào đang chạy.
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- TAB 4: KHO FILE KỊCH BẢN & HIỆU ỨNG UPLOAD -->
  <section id="tab-files" class="tab-section">
    <div class="panel-grid">
      <div class="col-5">
        <div class="card">
          <div class="card-head">
            <div class="card-title">
              <span class="card-title-icon" style="background:var(--noel-red-soft);color:var(--noel-red)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              </span>
              <span>Tải Lên & Tạo File Kịch Bản</span>
            </div>
            <span class="badge badge-red">Tự Đánh Số File</span>
          </div>

          <div class="upload-zone" id="fileDropZone">
            <input type="file" id="txtFileInput" accept=".txt" onchange="handleTxtUpload(this)">
            <div class="upload-icon-circle">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><polyline points="9 15 12 12 15 15"/></svg>
            </div>
            <div style="font-size:13px;font-weight:800;color:var(--text-primary)">Chạm hoặc Kéo Thả File .TXT vào đây</div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:3px">Tự động lọc sạch ký tự lỗi <code>:-</code> và đánh số thứ tự</div>
            <div class="upload-progress-wrap" id="uploadProgWrap">
              <div class="upload-progress-bar" id="uploadProgBar"></div>
            </div>
          </div>

          <form method="POST" action="/file/create">
            <div style="margin-bottom:8px">
              <label class="sub-label">Tên File Mới (.txt)</label>
              <input class="form-input" name="filename" placeholder="VD: kich_ban_noel.txt" required>
            </div>
            <div style="margin-bottom:10px">
              <label class="sub-label">Nội dung (Mỗi dòng 1 câu)</label>
              <textarea class="form-textarea" name="content" placeholder="Nhập nội dung kịch bản..." required></textarea>
            </div>
            <button class="btn btn-emerald" type="submit">
              <svg class="btn-ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 13 7 21"/></svg>
              <span>LƯU FILE KỊCH BẢN MỚI</span>
            </button>
          </form>
        </div>
      </div>

      <div class="col-7">
        <div class="card">
          <div class="card-head">
            <div class="card-title">
              <span class="card-title-icon" style="background:var(--noel-pine-soft);color:var(--noel-pine)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
              </span>
              <span>Danh Sách File Kịch Bản ({{ files|length }})</span>
            </div>
            <span class="badge badge-green">Gõ .nhay &lt;số&gt; @Tên</span>
          </div>

          <div class="scroll-box" style="max-height:420px">
            {% if not files %}
              <div style="text-align:center;padding:24px;color:var(--text-muted);font-size:12.5px">
                Kho lưu trữ trống. Hãy tải file .txt hoặc tạo mới ở khung bên trái.
              </div>
            {% endif %}
            {% for f in files %}
              <div class="list-item">
                <div style="min-width:0;flex:1">
                  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
                    <span class="badge badge-red">File số {{ f.display_num }}</span>
                    <span class="item-title">{{ f.filename }}</span>
                  </div>
                  <div class="item-sub">Số câu: <strong>{{ f.lines_count }}</strong> • Gọi nhanh: <code>.nhay {{ f.display_num }} @Tên</code></div>
                </div>
                <a href="/file/delete/{{ f.id }}" class="btn btn-danger btn-sm" style="text-decoration:none">Xóa</a>
              </div>
            {% endfor %}
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- TAB 5: TRUNG TÂM GIÁM SÁT ANTI-DIE-ALL & NHẬT KÝ ĐÃ ẨN LOG ACC -->
  <section id="tab-shield" class="tab-section">
    <div class="panel-grid">
      <div class="col-6">
        <div class="card">
          <div class="card-head">
            <div class="card-title">
              <span class="card-title-icon" style="background:var(--noel-pine-soft);color:var(--noel-pine)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>
              </span>
              <span>Hạ Tầng Anti-Die-All (Zalo & Discord Stealth)</span>
            </div>
            <span class="badge badge-green">Chống Quét Kép</span>
          </div>
          <div class="info-banner">
            <strong>Cơ chế bảo vệ chủ động:</strong><br>
            • <strong>Discord Anti-Die-All:</strong> Khóa cố định <code>launch_signature</code> & <code>client_heartbeat_session_id</code>, <code>X-Context-Properties</code>, kiểm soát ngưỡng 4 tin/5 giây và tự động giãn nhịp lệch pha (Phase-Shift Stagger) toàn dàn nick khi có 1 kênh báo Slowmode/429.<br>
            • <strong>Zalo Group Mention & Anti-Ban:</strong> Gửi qua <code>/api/group/mention</code> kích hoạt Tag xanh thật 100%, kèm nhịp thở Gaussian & Zero-Shift Tail.
          </div>
          <div class="scroll-box" id="healthShieldBox" style="max-height:310px"></div>
        </div>
      </div>

      <div class="col-6">
        <div class="card">
          <div class="card-head">
            <div class="card-title">
              <span class="card-title-icon" style="background:#ede9fe;color:#6d28d9">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              </span>
              <span>Nhật Ký Lệnh (Đã Mã Hóa Ẩn Log Acc)</span>
            </div>
            <span class="badge badge-purple">Stealth Log</span>
          </div>
          <div class="scroll-box" id="cmdLogBox" style="max-height:380px"></div>
        </div>
      </div>
    </div>
  </section>
</div>

<!-- THANH TAB NGANG Ở DƯỚI NHỎ GỌN HIỆN ĐẠI (5 TAB VỪA KHÍT MỌI MÀN HÌNH) -->
<nav class="bottom-dock-wrap">
  <div class="bottom-dock">
    <button type="button" class="tab-btn active" data-tab="tab-accounts" onclick="switchMainTab('tab-accounts', this)">
      <span class="tab-count">{{ accounts|length }}</span>
      <svg class="tab-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
      <span class="tab-lbl">Tài Khoản</span>
    </button>

    <button type="button" class="tab-btn" data-tab="tab-targets" onclick="switchMainTab('tab-targets', this)">
      <span class="tab-count" id="dockTargetBadge">0</span>
      <svg class="tab-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94"/></svg>
      <span class="tab-lbl">Phòng Tag</span>
    </button>

    <button type="button" class="tab-btn" data-tab="tab-campaign" onclick="switchMainTab('tab-campaign', this)">
      <span class="tab-count" id="dockTaskBadge">0</span>
      <svg class="tab-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
      <span class="tab-lbl">Chiến Dịch</span>
    </button>

    <button type="button" class="tab-btn" data-tab="tab-files" onclick="switchMainTab('tab-files', this)">
      <span class="tab-count">{{ files|length }}</span>
      <svg class="tab-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
      <span class="tab-lbl">Kho File</span>
    </button>

    <button type="button" class="tab-btn" data-tab="tab-shield" onclick="switchMainTab('tab-shield', this)">
      <svg class="tab-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>
      <span class="tab-lbl">Giám Sát</span>
    </button>
  </div>
</nav>

<script>
let ALL_TARGETS = [];
let SELECTED_TARGETS = new Map();
let CURRENT_MEMBERS = [];
let SELECTED_MENTIONS = new Map();

function showToast(msg) {
  const box = document.getElementById('toastBox');
  const el = document.createElement('div');
  el.className = 'toast-msg';
  el.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fde68a" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg><span>${msg}</span>`;
  box.appendChild(el);
  setTimeout(() => { el.remove(); }, 3200);
}

function switchMainTab(tabId, btnEl) {
  document.querySelectorAll('.tab-section').forEach(s => s.classList.remove('active'));
  const targetSec = document.getElementById(tabId);
  if (targetSec) targetSec.classList.add('active');
  document.querySelectorAll('.bottom-dock .tab-btn').forEach(b => b.classList.remove('active'));
  if (btnEl) btnEl.classList.add('active');
  if (tabId === 'tab-targets' && ALL_TARGETS.length === 0) {
    loadGroupsAndRooms(false);
  }
}

function switchAccForm(plat) {
  document.getElementById('accPlatformInput').value = plat;
  document.getElementById('segZaloBtn').classList.toggle('active', plat === 'zalo');
  document.getElementById('segDiscordBtn').classList.toggle('active', plat === 'discord');
  document.getElementById('zaloInputFields').style.display = (plat === 'zalo') ? 'block' : 'none';
  document.getElementById('discordInputFields').style.display = (plat === 'discord') ? 'block' : 'none';
}

function switchDiscordRegTab(mode) {
  document.getElementById('subDisTokenBtn').classList.toggle('active', mode === 'token');
  document.getElementById('subDisLoginBtn').classList.toggle('active', mode === 'login');
  document.getElementById('discordTokenBox').style.display = (mode === 'token') ? 'block' : 'none';
  document.getElementById('discordLoginBox').style.display = (mode === 'login') ? 'block' : 'none';
}

async function extractDiscordTokenByReg() {
  const email = document.getElementById('regDisEmail').value.trim();
  const password = document.getElementById('regDisPass').value.trim();
  const two_fa = document.getElementById('regDis2FA').value.trim();
  if (!email || !password) {
    showToast('Vui lòng nhập đầy đủ Email và Mật khẩu Discord!');
    return;
  }
  showToast('Đang tạo phiên Reg Stealth Chrome 131...');
  try {
    const r = await fetch('/api/discord/reg_login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email, password, two_fa, auto_save: true})
    });
    const d = await r.json();
    if (d.ok) {
      document.getElementById('discordTokenInput').value = d.token || '';
      showToast(d.message || 'Đã lấy Token sạch & lưu thành công!');
      setTimeout(() => location.reload(), 900);
    } else {
      showToast(d.error || 'Không thể lấy Token');
    }
  } catch (e) {
    showToast('Lỗi kết nối máy chủ');
  }
}

async function uploadBrandLogo(inputEl) {
  if (!inputEl.files || !inputEl.files[0]) return;
  const fd = new FormData();
  fd.append('logo', inputEl.files[0]);
  showToast('Đang tải Logo lên...');
  try {
    const r = await fetch('/api/logo/upload', {method: 'POST', body: fd});
    const d = await r.json();
    if (d.ok) {
      const img = document.getElementById('brandLogoImg');
      const fb = document.getElementById('brandLogoFallback');
      img.src = '/api/logo?v=' + Date.now();
      img.style.display = 'block';
      if (fb) fb.style.display = 'none';
      showToast('Đã cập nhật Logo!');
    } else {
      showToast(d.error || 'Lỗi tải Logo');
    }
  } catch (e) {
    showToast('Lỗi tải Logo');
  }
}

async function handleTxtUpload(inputEl) {
  if (!inputEl.files || !inputEl.files[0]) return;
  const file = inputEl.files[0];
  const wrap = document.getElementById('uploadProgWrap');
  const bar = document.getElementById('uploadProgBar');
  wrap.style.display = 'block';
  bar.style.width = '38%';
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch('/file/upload', {
      method: 'POST',
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      body: fd
    });
    bar.style.width = '100%';
    const d = await r.json();
    if (d.ok) {
      showToast(`Đã tải lên ${d.filename} (${d.lines_count} dòng)!`);
      setTimeout(() => location.reload(), 650);
    } else {
      showToast(d.error || 'Lỗi tải file');
    }
  } catch (e) {
    location.reload();
  }
}

async function toggleAccCmd(accId, enabled) {
  await fetch('/api/account/chat_cmd', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({acc_id: accId, enabled})
  });
  location.reload();
}

async function toggleAccAllowAll(accId, allow_all) {
  await fetch('/api/account/allow_all_cmd', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({acc_id: accId, allow_all})
  });
  location.reload();
}

async function loadGroupsAndRooms(forceRefresh) {
  const box = document.getElementById('targetListContainer');
  box.innerHTML = '<div style="text-align:center;padding:22px;color:var(--text-muted)">Đang đồng bộ danh sách nhóm Zalo & kênh Discord...</div>';
  try {
    const [rZalo, rDis] = await Promise.all([
      fetch('/api/all_groups' + (forceRefresh ? '?refresh=1' : '')).then(r => r.json()).catch(() => ({groups:[], friends:[]})),
      fetch('/api/discord_channels').then(r => r.json()).catch(() => ({channels:[]}))
    ]);
    const list = [];
    (rZalo.groups || []).forEach(g => list.push({id: String(g.id), name: g.name, type: 'group', members: g.members || '?'}));
    (rZalo.friends || []).forEach(f => list.push({id: String(f.id), name: f.name, type: 'user', members: 1}));
    (rDis.channels || []).forEach(c => list.push({id: String(c.id), name: c.name, type: 'discord_channel', members: 'Discord'}));
    ALL_TARGETS = list;
    renderTargetList();
    showToast(`Đã tải ${ALL_TARGETS.length} phòng chat!`);
  } catch (e) {
    box.innerHTML = '<div style="text-align:center;padding:20px;color:#dc2626">Lỗi tải danh sách phòng chat</div>';
  }
}

function renderTargetList() {
  const box = document.getElementById('targetListContainer');
  const q = (document.getElementById('roomSearchInput').value || '').toLowerCase().trim();
  const filtered = ALL_TARGETS.filter(t => !q || t.name.toLowerCase().includes(q) || t.id.includes(q));
  if (!filtered.length) {
    box.innerHTML = '<div style="text-align:center;padding:22px;color:var(--text-muted)">Không tìm thấy phòng phù hợp.</div>';
    return;
  }
  box.innerHTML = filtered.map(t => {
    const checked = SELECTED_TARGETS.has(t.id) ? 'checked' : '';
    const badgeClass = t.type === 'discord_channel' ? 'badge-purple' : (t.type === 'group' ? 'badge-blue' : 'badge-green');
    const badgeTxt = t.type === 'discord_channel' ? 'DISCORD' : (t.type === 'group' ? 'NHÓM ZALO' : 'BẠN BÈ');
    const safeName = t.name.replace(/'/g, "\\'");
    return `
      <div class="list-item">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;flex:1;min-width:0">
          <input type="checkbox" ${checked} onchange="toggleTargetItem('${t.id}', '${safeName}', '${t.type}', this.checked)" style="width:16px;height:16px;accent-color:var(--noel-red);flex-shrink:0">
          <div style="min-width:0;flex:1">
            <div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap">
              <span class="badge ${badgeClass}">${badgeTxt}</span>
              <span class="item-title">${t.name}</span>
            </div>
            <div class="item-sub">ID: <code>${t.id.slice(-6)}</code> • Thành viên: ${t.members}</div>
          </div>
        </label>
        ${(t.type === 'group' || t.type === 'discord_channel') ? `<button class="btn btn-soft btn-sm" type="button" onclick="fetchRoomMembers('${t.id}', '${t.type}')">Lấy Thành Viên</button>` : ''}
      </div>
    `;
  }).join('');
}

function toggleTargetItem(id, name, type, isChecked) {
  if (isChecked) SELECTED_TARGETS.set(String(id), {id: String(id), name, type});
  else SELECTED_TARGETS.delete(String(id));
  updateTargetBadges();
}

function selectAllTargets() {
  ALL_TARGETS.forEach(t => SELECTED_TARGETS.set(String(t.id), t));
  renderTargetList();
  updateTargetBadges();
}

function clearAllTargets() {
  SELECTED_TARGETS.clear();
  renderTargetList();
  updateTargetBadges();
}

function addDiscordChannelManual() {
  const cid = document.getElementById('manualDiscordChannel').value.trim();
  if (!cid) return;
  const item = {id: cid, name: `Kênh Discord ${cid.slice(-5)}`, type: 'discord_channel', members: 'Discord'};
  ALL_TARGETS.unshift(item);
  SELECTED_TARGETS.set(cid, item);
  document.getElementById('manualDiscordChannel').value = '';
  renderTargetList();
  updateTargetBadges();
  showToast('Đã thêm kênh Discord!');
}

function updateTargetBadges() {
  const c = SELECTED_TARGETS.size;
  document.getElementById('kpiTargetCount').textContent = c;
  document.getElementById('dockTargetBadge').textContent = c;
}

async function fetchRoomMembers(roomId, roomType) {
  const box = document.getElementById('memberListContainer');
  box.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted)">Đang tải danh sách thành viên thật...</div>';
  try {
    const url = roomType === 'discord_channel'
      ? `/api/discord_channel_members?channel_id=${encodeURIComponent(roomId)}`
      : `/api/group_members?group_id=${encodeURIComponent(roomId)}&refresh=1`;
    const r = await fetch(url);
    const d = await r.json();
    CURRENT_MEMBERS = d.members || [];
    renderMemberList();
    showToast(`Đã tải ${CURRENT_MEMBERS.length} thành viên để Tag!`);
  } catch (e) {
    box.innerHTML = '<div style="text-align:center;padding:20px;color:#dc2626">Không thể tải thành viên nhóm</div>';
  }
}

function renderMemberList() {
  const box = document.getElementById('memberListContainer');
  const q = (document.getElementById('memberSearchInput').value || '').toLowerCase().trim();
  const list = CURRENT_MEMBERS.filter(m => !q || (m.name || '').toLowerCase().includes(q) || String(m.uid || m.id).includes(q));
  if (!list.length) {
    box.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted)">Không có thành viên khớp bộ lọc.</div>';
    return;
  }
  box.innerHTML = list.map(m => {
    const uid = String(m.uid || m.id);
    const checked = SELECTED_MENTIONS.has(uid) ? 'checked' : '';
    const safeName = (m.name || '').replace(/'/g, "\\'");
    return `
      <div class="list-item">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;flex:1;min-width:0">
          <input type="checkbox" ${checked} onchange="toggleMentionUser('${uid}', '${safeName}', this.checked)" style="width:16px;height:16px;accent-color:var(--noel-red);flex-shrink:0">
          <div style="min-width:0;flex:1">
            <div class="item-title">@${m.name}</div>
            <div class="item-sub">UID: <code>${uid.slice(-6)}</code></div>
          </div>
        </label>
      </div>
    `;
  }).join('');
}

function toggleMentionUser(uid, name, isChecked) {
  if (isChecked) SELECTED_MENTIONS.set(String(uid), {uid: String(uid), id: String(uid), name});
  else SELECTED_MENTIONS.delete(String(uid));
  updateTagSummary();
}

function selectAllMembersInBox() {
  CURRENT_MEMBERS.forEach(m => {
    const uid = String(m.uid || m.id);
    SELECTED_MENTIONS.set(uid, {uid, id: uid, name: m.name});
  });
  renderMemberList();
  updateTagSummary();
}

function clearSelectedMentions() {
  SELECTED_MENTIONS.clear();
  document.getElementById('chkTagAll').checked = false;
  renderMemberList();
  updateTagSummary();
}

function addManualMention() {
  const uid = document.getElementById('manualTagUid').value.trim();
  const name = document.getElementById('manualTagName').value.trim() || `User_${uid.slice(-4)}`;
  if (!uid) {
    showToast('Vui lòng nhập UID Zalo hoặc ID Discord cần tag!');
    return;
  }
  SELECTED_MENTIONS.set(uid, {uid, id: uid, name});
  CURRENT_MEMBERS.unshift({uid, id: uid, name});
  document.getElementById('manualTagUid').value = '';
  document.getElementById('manualTagName').value = '';
  renderMemberList();
  updateTagSummary();
}

function updateTagSummary() {
  const tagAll = document.getElementById('chkTagAll').checked;
  const cnt = SELECTED_MENTIONS.size;
  document.getElementById('selectedTagBadge').textContent = tagAll ? `Tag @All + ${cnt} người` : `${cnt} người được tag`;
}

async function launchCampaignTask() {
  const targets = Array.from(SELECTED_TARGETS.values());
  if (!targets.length) {
    showToast('Hãy chọn ít nhất 1 phòng chat ở tab "Phòng Tag"!');
    switchMainTab('tab-targets', document.querySelector('[data-tab="tab-targets"]'));
    return;
  }
  const payload = {
    targets,
    mode: document.getElementById('cfgMode').value,
    color_mode: document.getElementById('cfgColorMode').value,
    fixed_color: document.getElementById('cfgFixedColor').value,
    delay: parseFloat(document.getElementById('cfgDelay').value || '1.0'),
    icon_count: parseInt(document.getElementById('cfgIconCount').value || '3', 10),
    file_id: document.getElementById('cfgFileSelect').value,
    raw_text: document.getElementById('cfgRawText').value,
    is_heading: document.getElementById('cfgHeading').checked,
    use_emoji: document.getElementById('cfgUseEmoji').checked,
    antiband: document.getElementById('cfgAntiband').checked,
    multi_acc: document.getElementById('cfgMultiAcc').checked,
    tag_all: document.getElementById('chkTagAll').checked,
    tag_users: Array.from(SELECTED_MENTIONS.values())
  };
  try {
    const r = await fetch('/task/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const d = await r.json();
    if (d.ok) {
      showToast('Đã phát động chiến dịch thành công!');
      pollSystemStatus();
    } else {
      showToast(d.error || 'Không thể chạy chiến dịch');
    }
  } catch (e) {
    showToast('Lỗi kết nối máy chủ');
  }
}

async function stopAllRunningTasks() {
  await fetch('/task/stop_all', {method: 'POST'});
  showToast('Đã dừng tất cả chiến dịch!');
  pollSystemStatus();
}

async function stopSingleTask(tid) {
  await fetch('/task/stop/' + encodeURIComponent(tid), {method: 'POST'});
  pollSystemStatus();
}

async function pollSystemStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    const tasks = d.tasks || [];
    const running = tasks.filter(t => t.status && t.status.includes('Đang chạy')).length;
    let totalSent = 0;
    tasks.forEach(t => { totalSent += (t.sent || 0); });

    document.getElementById('kpiRunningTasks').textContent = running;
    document.getElementById('dockTaskBadge').textContent = running;
    document.getElementById('kpiTotalSent').textContent = totalSent;

    const tBox = document.getElementById('activeTasksContainer');
    if (!tasks.length) {
      tBox.innerHTML = '<div style="text-align:center;padding:22px;color:var(--text-muted);font-size:12.5px">Chưa có chiến dịch nào đang chạy.</div>';
    } else {
      tBox.innerHTML = tasks.map(t => `
        <div class="list-item">
          <div style="min-width:0;flex:1">
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
              <span class="badge ${t.status.includes('Đang chạy') ? 'badge-green' : 'badge-amber'}">${t.status}</span>
              <span class="item-title">${t.mode} (${t.targets_count} phòng)</span>
            </div>
            <div class="item-sub">Đã phát: <strong>${t.sent}</strong> tin • Delay: ${t.delay}s</div>
          </div>
          ${t.status.includes('Đang chạy') ? `<button class="btn btn-danger btn-sm" onclick="stopSingleTask('${t.id}')">Dừng</button>` : ''}
        </div>
      `).join('');
    }

    const hBox = document.getElementById('healthShieldBox');
    const healthList = d.accounts_health || [];
    hBox.innerHTML = healthList.map(h => `
      <div class="list-item">
        <div style="min-width:0;flex:1">
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
            <span class="badge ${h.platform === 'discord' ? 'badge-purple' : 'badge-blue'}">${h.platform.toUpperCase()}</span>
            <span class="item-title">${h.masked_name}</span>
            <span class="badge ${h.circuit === 'CLOSED' ? 'badge-green' : 'badge-amber'}">${h.circuit}</span>
          </div>
          <div class="item-sub">Tốc độ: <strong>${h.rpm} RPM</strong> • Thành công: <strong>${h.ok_total}</strong> • Rủi ro: ${h.risk_score}% • ${h.ws_status}</div>
        </div>
      </div>
    `).join('') || '<div style="text-align:center;padding:18px;color:var(--text-muted)">Chưa có tài khoản kết nối</div>';

    const cBox = document.getElementById('cmdLogBox');
    const logs = d.cmd_logs || [];
    cBox.innerHTML = logs.map(l => `
      <div class="list-item">
        <div style="min-width:0;flex:1">
          <div class="item-title"><code>${l.cmd_text}</code></div>
          <div class="item-sub">${l.action_taken} • Phòng: <code>${l.masked_thread}</code></div>
        </div>
      </div>
    `).join('') || '<div style="text-align:center;padding:18px;color:var(--text-muted)">Chưa có nhật ký lệnh</div>';
  } catch (e) {}
}

setInterval(pollSystemStatus, 2600);
pollSystemStatus();
</script>
</body>
</html>"""


# ============================================================
# CÁC ROUTE FLASK & API ĐIỀU KHIỂN TOÀN DIỆN (CHỐNG LỖI 500 TUYỆT ĐỐI)
# ============================================================
@app.errorhandler(Exception)
def handle_unexpected_error(e):
    if request.path.startswith("/api/") or request.path.startswith("/task/"):
        return jsonify({"ok": False, "error": str(e)}), 200
    try:
        has_logo = bool(get_setting("brand_logo_b64", ""))
        logo_ts = get_setting("brand_logo_ts", "1")
        return render_template_string(
            DASHBOARD_HTML,
            accounts=[],
            files=[],
            has_logo=has_logo,
            logo_ts=logo_ts,
        ), 200
    except Exception:
        return Response("NOEL System Ready", mimetype="text/plain"), 200


@app.route("/login", methods=["GET", "POST"])
def login():
    ip = get_client_ip()
    allowed, wait_s = check_ip_bruteforce(ip)
    has_logo = bool(get_setting("brand_logo_b64", ""))
    logo_ts = get_setting("brand_logo_ts", "1")
    if not allowed:
        return render_template_string(
            LOGIN_HTML,
            error=f"Tạm khóa đăng nhập do nhập sai nhiều lần. Thử lại sau {wait_s} giây.",
            has_logo=has_logo,
            logo_ts=logo_ts,
        )
    if request.method == "POST":
        pw = (request.form.get("password") or "").strip()
        is_valid = False
        if pw and (pw == ACCESS_KEY or pw == DEFAULT_ADMIN_PASS):
            is_valid = True
        else:
            try:
                conn = db()
                row = conn.execute("SELECT password FROM users WHERE username=?", (DEFAULT_ADMIN_USER,)).fetchone()
                conn.close()
                if row and verify_password_secure(row["password"], pw):
                    is_valid = True
            except Exception:
                pass

        if is_valid:
            record_login_result(ip, True)
            session.permanent = True
            session["logged_in"] = True
            return redirect("/")

        record_login_result(ip, False)
        return render_template_string(
            LOGIN_HTML,
            error="Mật khẩu truy cập không chính xác!",
            has_logo=has_logo,
            logo_ts=logo_ts,
        )
    return render_template_string(LOGIN_HTML, error=None, has_logo=has_logo, logo_ts=logo_ts)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/api/logo")
def api_get_logo():
    b64 = get_setting("brand_logo_b64", "")
    mime = get_setting("brand_logo_mime", "image/png")
    if not b64:
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24"><rect width="24" height="24" rx="6" fill="#be123c"/><path d="M12 3L14.8 8.5L21 9.3L16.2 14L17.5 20.5L12 17.2L6.5 20.5L7.8 14L3 9.3L9.2 8.5L12 3Z" fill="#fde68a"/></svg>'
        return Response(svg, mimetype="image/svg+xml")
    try:
        raw = base64.b64decode(b64)
        return Response(raw, mimetype=mime)
    except Exception:
        return Response(status=404)


@app.route("/api/logo/upload", methods=["POST"])
def api_upload_logo():
    f = request.files.get("logo")
    if not f:
        return jsonify({"ok": False, "error": "Chưa chọn ảnh"}), 400
    raw = f.read()
    if not raw or len(raw) > 6 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Ảnh không hợp lệ hoặc quá 6MB"}), 400
    mime = f.mimetype or "image/png"
    set_setting("brand_logo_b64", base64.b64encode(raw).decode("utf-8"))
    set_setting("brand_logo_mime", mime)
    set_setting("brand_logo_ts", str(int(time.time())))
    return jsonify({"ok": True})


@app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect("/login")
    acc_rows = []
    try:
        conn = db()
        acc_rows = [dict(r) for r in conn.execute("SELECT * FROM accounts ORDER BY id DESC").fetchall()]
        conn.close()
    except Exception:
        acc_rows = []
    for a in acc_rows:
        a["masked_name"] = mask_account_name(a.get("name") or "Tài khoản")
        a["masked_uid"] = mask_sensitive_id(a.get("uid") or a.get("imei") or a.get("token") or "", 3)
    try:
        files_list = get_ordered_files_with_display_num()
    except Exception:
        files_list = []
    has_logo = bool(get_setting("brand_logo_b64", ""))
    logo_ts = get_setting("brand_logo_ts", "1")
    return render_template_string(
        DASHBOARD_HTML,
        accounts=acc_rows,
        files=files_list,
        has_logo=has_logo,
        logo_ts=logo_ts,
    )


@app.route("/api/discord/reg_login", methods=["POST"])
def api_discord_reg_login():
    data = request.json or {}
    email = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()
    two_fa = (data.get("two_fa") or "").strip()
    auto_save = bool(data.get("auto_save", True))

    res = login_discord_reg_session(email, password, two_fa)
    if not res.get("ok"):
        return jsonify(res), 400

    token = res["token"]
    prof = res.get("profile") or {}
    if auto_save:
        uid = str(prof.get("id") or "")
        uname = prof.get("global_name") or prof.get("username") or f"Discord_{uid[-4:]}"
        conn = db()
        conn.execute(
            """INSERT INTO accounts (name, platform, imei, cookies, token, is_bot, uid, chat_cmd_enabled, cmd_prefix, allow_all_cmd, enabled, created_at)
               VALUES (?, 'discord', '', '{}', ?, 0, ?, 1, '.', 0, 1, ?)""",
            (uname, token, uid, time.time()),
        )
        conn.commit()
        conn.close()
        sync_all_zalo_listeners()
    return jsonify({
        "ok": True,
        "token": token,
        "message": "Đã lấy Token Discord Reg sạch & kích hoạt bảo vệ Anti-Scan!"
    })


@app.route("/account/add", methods=["POST"])
def account_add():
    platform = (request.form.get("platform") or "zalo").strip().lower()
    custom_name = (request.form.get("name") or "").strip()
    chat_cmd = 1 if request.form.get("chat_cmd_enabled") else 0
    allow_all = 1 if request.form.get("allow_all_cmd") else 0

    if platform == "discord":
        raw_token_input = (request.form.get("token") or "").strip()
        is_bot = 1 if request.form.get("is_bot") else 0
        tokens = extract_discord_tokens_from_reg_or_raw(raw_token_input)
        if not tokens:
            return redirect("/")

        conn = db()
        for idx, tk in enumerate(tokens):
            warmup_discord_stealth_token(tk)
            bot = DiscordBot(tk, is_bot=bool(is_bot))
            uid = ""
            acc_name = custom_name or f"Discord Stealth #{idx + 1}"
            if bot.check():
                uid = str(bot.user_id or "")
                if not custom_name and bot.username:
                    acc_name = bot.username
            conn.execute(
                """INSERT INTO accounts (name, platform, imei, cookies, token, is_bot, uid, chat_cmd_enabled, cmd_prefix, allow_all_cmd, enabled, created_at)
                   VALUES (?, 'discord', '', '{}', ?, ?, ?, ?, '.', ?, 1, ?)""",
                (acc_name, tk, is_bot, uid, chat_cmd, allow_all, time.time()),
            )
        conn.commit()
        conn.close()
        sync_all_zalo_listeners()
        return redirect("/")

    imei = (request.form.get("imei") or "").strip()
    raw_cookies = (request.form.get("cookies") or "").strip()
    if not imei or not raw_cookies:
        return redirect("/")

    cookies_dict = {}
    try:
        parsed = json.loads(raw_cookies)
        if isinstance(parsed, dict):
            cookies_dict = parsed
        elif isinstance(parsed, list):
            for c in parsed:
                if isinstance(c, dict) and c.get("name") and c.get("value") is not None:
                    cookies_dict[c["name"]] = str(c["value"])
    except Exception:
        for part in raw_cookies.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies_dict[k.strip()] = v.strip()

    uid = ""
    acc_name = custom_name or f"Zalo_{imei[-4:]}"
    try:
        z = Zalo(imei, cookies_dict)
        uid = z.uid or ""
        if not custom_name and z.display_name:
            acc_name = z.display_name
    except Exception:
        pass

    conn = db()
    conn.execute(
        """INSERT INTO accounts (name, platform, imei, cookies, token, is_bot, uid, chat_cmd_enabled, cmd_prefix, allow_all_cmd, enabled, created_at)
           VALUES (?, 'zalo', ?, ?, '', 0, ?, ?, '.', ?, 1, ?)""",
        (acc_name, imei, json.dumps(cookies_dict, ensure_ascii=False), uid, chat_cmd, allow_all, time.time()),
    )
    conn.commit()
    conn.close()
    sync_all_zalo_listeners()
    return redirect("/")


@app.route("/account/delete/<int:acc_id>")
def account_delete(acc_id):
    if acc_id in ACTIVE_LISTENERS:
        ACTIVE_LISTENERS[acc_id].stop()
        ACTIVE_LISTENERS.pop(acc_id, None)
    conn = db()
    conn.execute("DELETE FROM accounts WHERE id=?", (acc_id,))
    conn.commit()
    conn.close()
    refresh_owner_uids()
    return redirect("/")


@app.route("/api/account/chat_cmd", methods=["POST"])
def api_toggle_chat_cmd():
    data = request.json or {}
    acc_id = int(data.get("acc_id", 0))
    enabled = 1 if data.get("enabled") else 0
    conn = db()
    conn.execute("UPDATE accounts SET chat_cmd_enabled=? WHERE id=?", (enabled, acc_id))
    conn.commit()
    conn.close()
    sync_all_zalo_listeners()
    return jsonify({"ok": True})


@app.route("/api/account/allow_all_cmd", methods=["POST"])
def api_toggle_allow_all():
    data = request.json or {}
    acc_id = int(data.get("acc_id", 0))
    allow_all = 1 if data.get("allow_all") else 0
    conn = db()
    conn.execute("UPDATE accounts SET allow_all_cmd=? WHERE id=?", (allow_all, acc_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/all_groups")
def api_all_groups():
    conn = db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM accounts WHERE platform='zalo'").fetchall()]
    conn.close()
    groups_map = {}
    friends_map = {}
    for r in rows:
        try:
            z = Zalo(r["imei"], r["cookies"])
            for g in z.groups():
                groups_map[str(g["id"])] = g
            for f in z.friends():
                friends_map[str(f["id"])] = f
        except Exception:
            continue
    return jsonify({"groups": list(groups_map.values()), "friends": list(friends_map.values())})


@app.route("/api/group_members")
def api_group_members():
    gid = (request.args.get("group_id") or "").strip()
    force = request.args.get("refresh") == "1"
    if not gid:
        return jsonify({"members": []})
    conn = db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM accounts WHERE platform='zalo'").fetchall()]
    conn.close()
    for r in rows:
        try:
            z = Zalo(r["imei"], r["cookies"])
            mems = z.get_members_full(gid, use_cache=not force)
            if mems:
                return jsonify({"members": mems})
        except Exception:
            continue
    return jsonify({"members": []})


@app.route("/api/discord_channels")
def api_discord_channels():
    conn = db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM accounts WHERE platform='discord'").fetchall()]
    conn.close()
    channels_map = {}
    for r in rows:
        try:
            bot = DiscordBot(r["token"], is_bot=bool(r.get("is_bot", 0)))
            for g in bot.get_guilds():
                gid = g.get("id")
                gname = g.get("name") or "Server"
                for ch in bot.get_guild_channels(gid):
                    cid = str(ch["id"])
                    channels_map[cid] = {
                        "id": cid,
                        "name": f"{gname} # {ch['name']}",
                        "type": "discord_channel",
                    }
        except Exception:
            continue
    return jsonify({"channels": list(channels_map.values())})


@app.route("/api/discord_channel_members")
def api_discord_channel_members():
    cid = (request.args.get("channel_id") or "").strip()
    if not cid:
        return jsonify({"members": []})
    conn = db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM accounts WHERE platform='discord'").fetchall()]
    conn.close()
    for r in rows:
        try:
            bot = DiscordBot(r["token"], is_bot=bool(r.get("is_bot", 0)))
            mems = bot.get_channel_recent_members(cid)
            if mems:
                return jsonify({"members": mems})
        except Exception:
            continue
    return jsonify({"members": []})


@app.route("/file/upload", methods=["POST"])
def file_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "Chưa chọn file"}), 400
    fname = os.path.basename(f.filename)
    if not fname.lower().endswith(".txt"):
        fname += ".txt"
    save_path = os.path.join(UPLOAD_DIR, f"{int(time.time())}_{fname}")
    raw_bytes = f.read()
    text_content = raw_bytes.decode("utf-8", errors="ignore")
    cleaned = clean_corrupted_shortcuts(text_content)
    with open(save_path, "w", encoding="utf-8") as wf:
        wf.write(cleaned)
    parsed = parse_file_stream_fast(save_path, strip_numbers=True)
    lines_cnt = parsed.get("line_count", len(parsed.get("lines", []))) if isinstance(parsed, dict) else len(parsed)
    conn = db()
    conn.execute(
        "INSERT INTO files (filename, filepath, lines_count, created_at) VALUES (?, ?, ?, ?)",
        (fname, save_path, lines_cnt, time.time()),
    )
    conn.commit()
    conn.close()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "filename": fname, "lines_count": lines_cnt})
    return redirect("/")


@app.route("/file/create", methods=["POST"])
def file_create():
    fname = (request.form.get("filename") or "kich_ban.txt").strip()
    if not fname.lower().endswith(".txt"):
        fname += ".txt"
    content = clean_corrupted_shortcuts(request.form.get("content") or "")
    save_path = os.path.join(UPLOAD_DIR, f"{int(time.time())}_{os.path.basename(fname)}")
    with open(save_path, "w", encoding="utf-8") as wf:
        wf.write(content)
    parsed = parse_file_stream_fast(save_path, strip_numbers=True)
    lines_cnt = parsed.get("line_count", len(parsed.get("lines", []))) if isinstance(parsed, dict) else len(parsed)
    conn = db()
    conn.execute(
        "INSERT INTO files (filename, filepath, lines_count, created_at) VALUES (?, ?, ?, ?)",
        (fname, save_path, lines_cnt, time.time()),
    )
    conn.commit()
    conn.close()
    return redirect("/")


@app.route("/file/delete/<int:fid>")
def file_delete(fid):
    conn = db()
    row = conn.execute("SELECT filepath FROM files WHERE id=?", (fid,)).fetchone()
    if row and row["filepath"] and os.path.exists(row["filepath"]):
        try:
            os.remove(row["filepath"])
        except Exception:
            pass
    conn.execute("DELETE FROM files WHERE id=?", (fid,))
    conn.commit()
    conn.close()
    return redirect("/")


@app.route("/task/start", methods=["POST"])
def route_task_start():
    data = request.json or {}
    targets = data.get("targets") or []
    if not targets:
        return jsonify({"ok": False, "error": "Chưa chọn phòng chat mục tiêu!"}), 400

    mode = data.get("mode", "treo_nhay")
    file_id = str(data.get("file_id") or "").strip()
    raw_text = clean_corrupted_shortcuts(data.get("raw_text") or "").strip()
    tag_users = list(data.get("tag_users") or [])
    tag_all = bool(data.get("tag_all", False))

    if raw_text and "@" in raw_text:
        conn = db()
        z_row = conn.execute("SELECT * FROM accounts WHERE platform='zalo' LIMIT 1").fetchone()
        conn.close()
        z_client = None
        if z_row:
            try:
                z_client = Zalo(z_row["imei"], z_row["cookies"])
            except Exception:
                pass
        first_gid = next((t["id"] for t in targets if t.get("type") == "group"), None)
        stripped, auto_m, auto_all = extract_trailing_tags_and_resolve(
            raw_text, incoming_mentions=None, zalo_client=z_client, group_id=first_gid
        )
        if auto_m or auto_all:
            raw_text = stripped if stripped else raw_text
            if auto_all:
                tag_all = True
            for am in auto_m:
                if not any(str(x.get("uid") or x.get("id")) == str(am["uid"]) for x in tag_users):
                    tag_users.append(am)

    blocks = []
    if file_id:
        blocks = get_blocks_from_file_query(file_id, mode=mode)
    if not blocks and raw_text:
        if mode == "treo_nhay":
            if ";" in raw_text:
                blocks = [strip_leading_line_number(x.strip()) for x in raw_text.split(";") if x.strip()]
            else:
                blocks = [strip_leading_line_number(x.strip()) for x in raw_text.split("\n") if x.strip()]
        elif mode == "treo_ngon":
            blocks = [raw_text]
        else:
            blocks = [x.strip() for x in raw_text.split(";") if x.strip()] if ";" in raw_text else [raw_text]

    if not blocks:
        return jsonify({"ok": False, "error": "Vui lòng chọn File kịch bản hoặc nhập nội dung!"}), 400

    tid = start_task_programmatic(
        targets=targets,
        blocks=blocks,
        delay=float(data.get("delay", 1.0)),
        use_emoji=bool(data.get("use_emoji", True)),
        icon_count=int(data.get("icon_count", 3)),
        tag_users=tag_users,
        tag_all=tag_all,
        is_heading=bool(data.get("is_heading", True)),
        multi_acc=bool(data.get("multi_acc", True)),
        mode=mode,
        color_mode=data.get("color_mode", "rainbow"),
        fixed_color=data.get("fixed_color", "red"),
        antiband=bool(data.get("antiband", True)),
        antidieall=True,
        source_label="web",
    )
    return jsonify({"ok": True, "task_id": tid})


@app.route("/task/stop/<tid>", methods=["POST"])
def route_task_stop(tid):
    info = ACTIVE_TASKS.get(tid)
    if info and info.get("stop"):
        info["stop"].set()
    try:
        conn = db()
        conn.execute("UPDATE tasks SET status='stopped' WHERE id=?", (tid,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/task/stop_all", methods=["POST"])
def route_task_stop_all():
    cnt = stop_tasks_for_thread(None)
    try:
        conn = db()
        conn.execute("UPDATE tasks SET status='stopped' WHERE status='running'")
        conn.commit()
        conn.close()
    except Exception:
        pass
    return jsonify({"ok": True, "stopped": cnt})


@app.route("/api/status")
def api_status():
    task_list = []
    try:
        conn = db()
        t_rows = [dict(r) for r in conn.execute("SELECT * FROM tasks ORDER BY started_at DESC LIMIT 25").fetchall()]
        acc_rows = [dict(r) for r in conn.execute("SELECT id, name, platform, uid FROM accounts ORDER BY id DESC").fetchall()]
        cmd_rows = [dict(r) for r in conn.execute("SELECT * FROM bot_logs ORDER BY id DESC LIMIT 25").fetchall()]
        conn.close()
    except Exception:
        t_rows, acc_rows, cmd_rows = [], [], []

    for r in t_rows:
        tid = r.get("id", "")
        is_active = tid in ACTIVE_TASKS and not ACTIVE_TASKS[tid]["stop"].is_set()
        try:
            meta = json.loads(r.get("meta") or "{}")
        except Exception:
            meta = {}
        try:
            stats = json.loads(r.get("stats") or "{}")
        except Exception:
            stats = {}
        live_opts = (ACTIVE_TASKS.get(tid) or {}).get("opts") or {}
        task_list.append({
            "id": tid,
            "mode": r.get("type") or live_opts.get("mode") or "treo_nhay",
            "targets_count": meta.get("box_count") or len(meta.get("targets") or []),
            "sent": stats.get("sent", 0),
            "fail": stats.get("fail", 0),
            "status": "Đang chạy" if is_active else "Đã dừng",
            "delay": live_opts.get("delay", meta.get("delay", 1.0)),
        })

    health_out = []
    for a in acc_rows:
        aid = a["id"]
        snap = HEALTH_MGR.get_snapshot(aid)
        lst = ACTIVE_LISTENERS.get(aid)
        ws_st = getattr(lst, "ws_status", "Đang bảo vệ ngầm") if lst else "Tắt nhận lệnh"
        health_out.append({
            "id": aid,
            "platform": a.get("platform") or "zalo",
            "masked_name": mask_account_name(a.get("name") or "Account"),
            "circuit": snap["circuit"],
            "rpm": snap["rpm"],
            "ok_total": snap["ok_total"],
            "risk_score": snap["risk_score"],
            "ws_status": sanitize_log_text(ws_st),
        })

    masked_logs = []
    for l in cmd_rows:
        masked_logs.append({
            "cmd_text": sanitize_log_text(l.get("cmd_text") or ""),
            "action_taken": sanitize_log_text(l.get("action_taken") or ""),
            "masked_thread": mask_sensitive_id(l.get("thread_id") or "", 4),
            "created_at": l.get("created_at") or "",
        })

    return jsonify({
        "tasks": task_list,
        "accounts_health": health_out,
        "cmd_logs": masked_logs,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
