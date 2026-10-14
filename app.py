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
    Flask, request, jsonify, session, redirect, Response, send_from_directory
)
from werkzeug.utils import secure_filename

# ============================================================
# CẤU HÌNH HỆ THỐNG & BẢO MẬT WEB — NOEL WINTER STUDIO EDITION
# ============================================================
APP_TITLE = "NOEL WINTER STUDIO — ZALO & DISCORD AUTOMATION"
SECRET_KEY = os.environ.get("SECRET_KEY", "noel-winter-studio-secret-key-2026-secure")
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
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024  # Hỗ trợ tải file lớn lên tới 256MB
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
    """Che dấu ID/UID/Token nhạy cảm trong log hệ thống để bảo vệ thông tin tài khoản."""
    s = str(val or "").strip()
    if not s:
        return "***"
    if len(s) <= keep_tail + 2:
        return "***"
    return f"***{s[-keep_tail:]}"


def mask_account_name(name):
    """Làm mờ tên tài khoản khi hiển thị trong log bảo mật."""
    s = str(name or "").strip()
    if not s:
        return "Acc_***"
    if len(s) <= 3:
        return s[0] + "**"
    return f"{s[:2]}***{s[-1:]}"


def sanitize_log_text(txt):
    """Loại bỏ mọi chuỗi Token, Cookie, IMEI, hoặc đường dẫn nhạy cảm trước khi ghi log."""
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
        _ACTIVE_DB_PATH = os.path.join(tempfile.gettempdir(), "noel_studio_database.db")
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
        _ACTIVE_DB_PATH = os.path.join(tempfile.gettempdir(), "noel_studio_database.db")
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

    # Đảm bảo luôn có ít nhất 1 tài khoản quản trị mặc định (vì đã xoá chức năng tạo acc công khai)
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
    """Đánh dấu tin nhắn do Bot tự gửi đi (cả Zalo & Discord) để Listener không bao giờ tự đọc lại làm lệnh."""
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
    """Kiểm tra xem gói tin nhận về có phải là tin nhắn do chính Bot vừa phát ra hay không."""
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
            clean_ln = strip_leading_line_number(stripped) if strip_numbers else stripped
            all_lines.append(clean_ln)
            current_block.append(clean_ln if strip_numbers else ln.rstrip())
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
# HỆ THỐNG KÉP 2 ĐỘNG CƠ ANTI-BAN ĐẶC RIÊNG SIÊU THÔNG MINH & HIỆN ĐẠI:
# 1. ZaloSmartAntiBanEngine (Chuyên biệt cho Zalo WPA v645)
# 2. DiscordStealthAntiBanEngine (Chuyên biệt cho Discord - Ẩn Đường Chuyển Stealth Route)
# ============================================================
ZERO_WIDTH_ZALO_POOL = ["\u200b", "\u200c", "\u2060"]
ZERO_WIDTH_DISCORD_POOL = ["\u200b", "\u200c", "\u200d", "\u2060"]
_ANTIBAN_COUNTER = 0
_ANTIBAN_LOCK = threading.Lock()


class ZaloSmartAntiBanEngine:
    """Động cơ Anti-Ban chuyên sâu dành riêng cho Zalo:
    - Zero-Shift Polymorphic Tail Signature: Mã hóa vi chữ ký tàng hình ở cuối chuỗi sau khi đã tính xong
      toạ độ UTF-16 của Màu chữ (textProperties) và @Tag (mentionInfo) -> Không bao giờ lệch Tag hay mất màu chữ!
    - Biometric Human Cadence: Mô phỏng nhịp gõ và nhịp thở sinh học (Weibull + Gaussian jitter + Micro-break).
    - Zalo Session Shield: Bảo vệ Cookie & khóa zpw_enk trước các mã phạt -112, -114, 300, 301, 429."""

    RATELIMIT_CODES = {-2, -108, -112, -114, 112, 114, 300, 301, 302, 429, 500, 1001, 2001}
    AUTH_CODES = {-401, 401, -102, 102, -30, -13, 3003}

    BROWSER_PROFILES = [
        {
            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "sec_ch_ua": '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
            "platform": '"Windows"'
        },
        {
            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
            "sec_ch_ua": '"Chromium";v="130", "Microsoft Edge";v="130", "Not?A_Brand";v="99"',
            "platform": '"Windows"'
        },
        {
            "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "sec_ch_ua": '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
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
        if burst_cnt > 0 and burst_cnt % 16 == 0:
            micro_break = random.uniform(0.45, 1.15)
        elif burst_cnt > 0 and burst_cnt % 45 == 0:
            micro_break = random.uniform(1.2, 2.2)
        return max(0.24, d + typing_factor + gaussian_jitter + micro_break)


class DiscordStealthAntiBanEngine:
    """Động cơ Anti-Ban & Ẩn Đường Chuyển (Stealth Route) chuyên biệt cho Discord:
    - Ẩn đường chuyển (Stealth Route Rotation & Referer Spoofing): Tự động định tuyến qua các cổng
      chính thức của Discord (discord.com/api/v9, v10, canary, ptb) với Referer khớp đúng kênh chat.
    - X-Super-Properties Telemetry Binding: Tạo hồ sơ thiết bị cố định theo từng Token để Discord nhận diện
      100% là thao tác từ ứng dụng Discord Web/Desktop chính chủ, chống khóa Token (Anti-Die Token).
    - Snowflake 64-bit Nonce & Smart Typing Cadence: Mọi tin nhắn đều đính kèm `nonce` chuẩn thời gian thực
      Discord Epoch và nhịp gõ phím tự nhiên.
    - Per-Channel RateLimit Bucket Tracking: Đọc trực tiếp X-RateLimit-Remaining từ header trả về của Discord."""

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
            "browser_version": "129.0.0.0",
            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "sec_ch_ua": '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
            "build_number": 346892,
        },
        {
            "os": "Windows",
            "browser": "Chrome",
            "os_version": "11",
            "browser_version": "130.0.0.0",
            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "sec_ch_ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
            "build_number": 348105,
        },
        {
            "os": "Mac OS X",
            "browser": "Chrome",
            "os_version": "10.15.7",
            "browser_version": "129.0.0.0",
            "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "sec_ch_ua": '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
            "build_number": 346892,
        },
    ]

    _CHANNEL_BUCKETS = {}
    _LAST_TYPING_TS = defaultdict(float)
    _LOCK = threading.Lock()

    @classmethod
    def get_deterministic_profile(cls, token):
        h = zlib.crc32(str(token or "discord").encode("utf-8"))
        return cls.CLIENT_PROFILES[h % len(cls.CLIENT_PROFILES)]

    @classmethod
    def build_super_properties_b64(cls, token):
        prof = cls.get_deterministic_profile(token)
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
        }
        raw_json = json.dumps(props, separators=(",", ":"))
        return base64.b64encode(raw_json.encode("utf-8")).decode("utf-8")

    @classmethod
    def build_stealth_headers(cls, token, is_bot=False, channel_id=None):
        auth_val = f"Bot {token}" if is_bot else token
        if is_bot:
            return {
                "Authorization": auth_val,
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://discord.com, 10.0)",
            }
        prof = cls.get_deterministic_profile(token)
        ref = f"https://discord.com/channels/@me/{channel_id}" if channel_id else "https://discord.com/channels/@me"
        return {
            "Authorization": auth_val,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "User-Agent": prof["ua"],
            "X-Super-Properties": cls.build_super_properties_b64(token),
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

    @classmethod
    def pick_stealth_endpoint(cls, token, path_suffix, rotate_step=0):
        """Ẩn đường chuyển Discord bằng cách phân tán hợp lệ qua các cổng API v9/v10 chính thức."""
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
    def get_channel_bucket_wait(cls, channel_id):
        with cls._LOCK:
            b = cls._CHANNEL_BUCKETS.get(str(channel_id))
            if not b:
                return 0.0
            now = time.time()
            if b["remaining"] <= 1 and now < b["reset_at"]:
                return max(0.15, (b["reset_at"] - now) + random.uniform(0.08, 0.25))
            return 0.0

    @classmethod
    def should_trigger_typing(cls, channel_id):
        now = time.time()
        with cls._LOCK:
            last_t = cls._LAST_TYPING_TS[str(channel_id)]
            if now - last_t >= random.uniform(18.0, 32.0):
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

    def can_send(self, acc_id, max_rpm=46, channel_id=None, platform="zalo"):
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
                    st["adaptive_delay_bonus"] = max(0.55, st["adaptive_delay_bonus"])

            while st["timestamps"] and now - st["timestamps"][0] > 60.0:
                st["timestamps"].popleft()

            rpm = len(st["timestamps"])
            effective_limit = max_rpm if st["circuit"] == "CLOSED" else max(16, max_rpm // 2)
            if rpm >= effective_limit:
                wait_s = max(0.7, 60.0 - (now - st["timestamps"][0]) + random.uniform(0.2, 0.7))
                return False, round(wait_s, 2)

            recent_burst = sum(1 for t in st["timestamps"] if now - t <= 1.2)
            if recent_burst >= 5:
                return False, round(random.uniform(0.32, 0.72), 2)

            if st["timestamps"] and (now - st["timestamps"][-1]) < 0.20:
                return False, round(0.22 - (now - st["timestamps"][-1]), 2)

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
            d = float(base_delay) + bonus + (risk * 0.014)
            jitter = abs(random.gauss(0.10, 0.06))
            if b_cnt % 15 == 0:
                jitter += random.uniform(0.35, 0.95)
            return max(0.24, d + jitter)

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

    def report_rate_limit(self, acc_id, retry_after=None, reason="Rate Limit 429"):
        now = time.time()
        with self.lock:
            st = self.state[acc_id]
            st["ratelimit_streak"] += 1
            st["fail_total"] += 1
            st["last_error"] = sanitize_log_text(reason)
            streak = min(st["ratelimit_streak"], 6)
            base_cd = float(retry_after) if retry_after else (10.0 * (1.65 ** (streak - 1)))
            cooldown = min(210.0, max(6.0, base_cd + random.uniform(1.2, 4.0)))
            st["circuit"] = "OPEN"
            st["cooldown_until"] = now + cooldown
            st["adaptive_delay_bonus"] = min(4.0, st["adaptive_delay_bonus"] + 0.55)
            st["risk_score"] = min(100.0, st["risk_score"] + 20.0)

            open_count = sum(1 for v in self.state.values() if v["circuit"] == "OPEN" and v["cooldown_until"] > now)
            if open_count >= 1 and len(self.state) >= 2 and open_count >= len(self.state) * 0.5:
                self.global_cooldown_until = max(self.global_cooldown_until, now + random.uniform(2.5, 5.0))

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


# ============================================================
# BẢNG MÀU CHUẨN ZALO RICH-TEXT & BỘ ICON CHUẨN ZALO CÓ HIỆU ỨNG VIP
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
    ";-A", "=))", "b-)", "/-strong", "/-weak",
    "/-punch", "/-shit", "/-bome", "/-rose", "/-heart",
    "/-ok", "/-li", "/-fade", "/-bd", "/-break",
    ":d", ":p", ":v", ":3", ":>",
    ":$", ":x", ":o", ":-R", ":-L",
    ":-F", ":-h", ":-*", ":-?", ":-s",
    "x-)", "8-)", ":-t", "=d>", ";-!"
]


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
    text = re.sub(r"(?<!\S);f(?!\S)", ";-A", text)
    text = re.sub(r"(?<!\S);;?\)(?!\S)", "b-)", text)
    text = re.sub(r"(?<!\S):-bd(?!\S)", "/-bd", text)
    return text


def _is_emoji_or_zalo_shortcut_token(tk):
    if not tk:
        return False
    if tk in ZALO_ICON_VIP or tk in ("/-no", ":-d", ";f", ":-bd", ";;)", ";)"):
        return True
    if all((ord(ch) > 0x2000 or ch in ("\ufe0f", "\u200d")) for ch in tk):
        return True
    return False


GROUP_MEMBERS_CACHE = {}
GROUP_CACHE_LOCK = threading.Lock()
KNOWN_GROUPS_BY_ACC = defaultdict(set)


# ============================================================
# CLIENT GIAO THỨC ZALO (TỰ ĐỘNG TAG CHUẨN THEO KHUNG CHAT ZALO 100% + ANTI-BAN RIÊNG)
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
        """Lấy 100% Tên Hiển Thị Thực Tế Trong Khung Chat Nhóm Zalo & UID của toàn bộ thành viên:
        Kết hợp 5 nguồn:
        1. Quét nhanh lịch sử tin nhắn nhóm gần nhất (`get_recent_group_messages`) để bắt ngay `dName` vừa chat
        2. `getmg-v2` (`currentMems`, `memInfoList`, `members`, `adminIds`, `creatorId`)
        3. `GLOBAL_USER_NAME_CACHE`
        4. `getprofiles/v2` (profile-wpa.chat.zalo.me)
        5. `getuserinfo` (tt-group-wpa.chat.zalo.me)"""
        gid_str = str(gid)
        if use_cache:
            with GROUP_CACHE_LOCK:
                c = GROUP_MEMBERS_CACHE.get(gid_str)
                if c and time.time() - c["ts"] < 180:
                    return c["members"]

        # Bước 0: Quét lịch sử chat gần nhất của nhóm để thu thập dName thực tế trên khung chat
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
                elif tk == ";f":
                    line_tail_icons.insert(0, ";-A")
                elif tk in (":-bd",):
                    line_tail_icons.insert(0, "/-bd")
                elif tk in (";;)", ";)"):
                    line_tail_icons.insert(0, "b-)")
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
        """Gắn Tag Thật chuẩn 100% khung chat Zalo (mentionInfo):
        - Tự động làm sạch tên hiển thị từ GLOBAL_USER_NAME_CACHE hoặc danh sách thành viên nhóm nếu tên đang bị khuyết.
        - Nếu trong `core_msg` đã có sẵn `@Tên` của người đó thì đặt tọa độ `pos` và `len` ngay tại vị trí `@Tên` trong câu;
          nếu chưa có thì nối ` @Tên` vào ngay sau `core_msg` và tính chính xác tuyệt đối `pos`, `len` theo UTF-16LE."""
        final = core_msg.rstrip() if core_msg else ""
        m_arr = []

        if tag_all:
            tag_token = "@All"
            idx_existing = final.find("@All")
            if idx_existing != -1:
                pos = utf16_len(final[:idx_existing])
                t_len = utf16_len(tag_token)
            else:
                pos = utf16_len(final) + (1 if final else 0)
                final = (final + " " + tag_token) if final else tag_token
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
                uid = str(m.get("uid") or m.get("id") or "").strip()
                if not uid or uid in ("-1", "0") or uid in seen_uids:
                    continue
                seen_uids.add(uid)

                raw_name = str(m.get("name") or m.get("dName") or "").strip().lstrip("@")
                if not raw_name or raw_name.startswith("Thành viên ") or raw_name.startswith("Người dùng ") or raw_name.startswith("User_"):
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
                # Kiểm tra xem `@name` đã xuất hiện sẵn trong `final` hay chưa
                existing_idx = final.find(tag_token)
                if existing_idx != -1:
                    pos = utf16_len(final[:existing_idx])
                    t_len = utf16_len(tag_token)
                else:
                    pos = utf16_len(final) + (1 if final else 0)
                    final = (final + " " + tag_token) if final else tag_token
                    t_len = utf16_len(tag_token)

                m_arr.append({
                    "pos": int(pos),
                    "len": int(t_len),
                    "uid": str(uid),
                    "type": 0
                })

        return final, m_arr

    def _send_raw_payload(self, final_msg, thread_id, is_group, m_arr, styles, first_color="db342e"):
        url = ("https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
               if is_group
               else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms")

        client_id = str(int(time.time() * 1000)) + str(random.randint(100, 999))
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

        if styles:
            params_obj = {"styles": styles, "ver": 0}
            params_json = json.dumps(params_obj, separators=(",", ":"), ensure_ascii=False)
            pl["textProperties"] = params_json
            if not (is_group and m_arr):
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
        # Tự động bóc tách @Tên hoặc @All nếu người dùng viết trực tiếp trong raw_text mà chưa truyền mentions
        eff_mentions = list(mentions) if mentions else []
        eff_tag_all = bool(tag_all)
        working_text = raw_text

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
            final_msg = f"{msg_with_tags} {tail_icon_str}".strip()
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
def _smart_match_member_by_query(query_str, members, zalo_client=None, group_id=None):
    """Tìm thành viên trong nhóm Zalo/Discord khớp chuẩn nhất với chuỗi người dùng gõ sau dấu @:
    - Ưu tiên 1: Khớp chính xác 100% tên hiển thị (không phân biệt hoa/thường).
    - Ưu tiên 2: Khớp chính xác không dấu tiếng Việt (`remove_vn_accents`).
    - Ưu tiên 3: Khớp tiền tố hoặc hậu tố tên (ví dụ gõ `@Kien` khớp `Nguyen Trung Kien メ`).
    - Ưu tiên 4: Khớp tập từ khóa con (token overlap) hoặc chuỗi con (substring).
    - Nếu bộ nhớ cache chưa có thành viên đó, tự động gọi làm mới `get_members_full(group_id, use_cache=False)`."""
    q_raw = (query_str or "").strip().lstrip("@").strip()
    if not q_raw:
        return None

    def _search_in_list(mem_list):
        if not mem_list:
            return None
        valid_mems = [
            m for m in mem_list
            if m.get("name") and not str(m["name"]).startswith("Thành viên ") and not str(m["name"]).startswith("Người dùng ")
        ]
        q_low = q_raw.lower()
        q_no_acc = remove_vn_accents(q_raw)

        # 1. Khớp chính xác hoặc hậu tố ở cuối câu
        for m in valid_mems:
            n_low = m["name"].strip().lower()
            n_no_acc = remove_vn_accents(m["name"])
            if q_low == n_low or (q_no_acc and q_no_acc == n_no_acc):
                return m

        # 2. Khớp chuỗi bắt đầu hoặc kết thúc bằng từ khóa
        sorted_mems = sorted(valid_mems, key=lambda x: len(x.get("name", "")), reverse=True)
        for m in sorted_mems:
            n_low = m["name"].strip().lower()
            n_no_acc = remove_vn_accents(m["name"])
            if n_low.startswith(q_low) or n_low.endswith(q_low):
                return m
            if len(q_no_acc) >= 2 and (n_no_acc.startswith(q_no_acc) or n_no_acc.endswith(q_no_acc)):
                return m

        # 3. Khớp chứa toàn bộ các từ khóa (tokens) hoặc chuỗi con
        q_tokens = [t for t in q_no_acc.split() if t]
        for m in sorted_mems:
            n_low = m["name"].strip().lower()
            n_no_acc = remove_vn_accents(m["name"])
            if q_low in n_low or (len(q_no_acc) >= 2 and q_no_acc in n_no_acc):
                return m
            if q_tokens and all(tk in n_no_acc for tk in q_tokens):
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
            # Trường hợp nhóm chỉ có 2 thành viên (mình và đối phương), thành viên còn lại chắc chắn là người được Tag
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
    """Nhận diện và phân giải Tag Thật 100% (@Tên hoặc @All) cho cả Zalo và Discord:
    - Cắt chính xác từ `full_original_msg` (nếu có) hoặc `raw_text` dựa trên `pos` và `len` UTF-16 của Zalo.
    - Nếu người dùng gõ tay `@Tên` trên khung chat Zalo hoặc trong văn bản mà không chọn popup,
      tự động đối chiếu thông minh với danh sách thành viên nhóm + lịch sử chat để biến thành Tag Xanh Dương Thật 100%."""
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

    # 1. Bóc tách từ metadata mentions của sự kiện tin nhắn Zalo hoặc Discord
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

                # Ưu tiên cắt trực tiếp từ full_original_msg theo raw_pos của Zalo để không bao giờ bị lệch offset
                if full_original_msg and raw_pos >= 0 and mlen > 0:
                    try:
                        orig_u16 = full_original_msg.encode("utf-16-le")
                        if (raw_pos + mlen) * 2 <= len(orig_u16):
                            sub_orig = orig_u16[raw_pos * 2:(raw_pos + mlen) * 2].decode("utf-16-le", errors="ignore").strip()
                            if sub_orig.startswith("@"):
                                extracted_orig = sub_orig.lstrip("@").strip()
                                if extracted_orig:
                                    m_name = extracted_orig
                                # Xoá sub_orig khỏi text hiện tại
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

    # 2. Kiểm tra thẻ mention Discord dạng <@123456789> hoặc <@!123456789>
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

    # 3. Kiểm tra chuỗi @All / @all / @tất cả / @everyone / @here ở cuối văn bản
    all_pattern = re.compile(r"(?:\s+|^)(?:@all|@tất\s*cả|@tat\s*ca|@mọi\s*người|@everyone|@here)\s*$", re.IGNORECASE)
    while True:
        m_all = all_pattern.search(text)
        if not m_all:
            break
        tag_all = True
        text = text[:m_all.start()].rstrip()

    # 4. Đối chiếu @Tên ở cuối văn bản với danh sách thành viên thật của nhóm Zalo / Discord
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
                    real_label = matched_mem["name"] if not matched_mem["name"].startswith(("Người dùng ", "Thành viên ")) else partial_raw
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
# CÔNG CỤ LẤY & CHUẨN HOÁ TOKEN DISCORD BẰNG REG / MULTI-FORMAT CHỐNG DIE
# ============================================================
DISCORD_TOKEN_REGEX = re.compile(r"([A-Za-z0-9_\-]{23,28}\.[A-Za-z0-9_\-]{6,7}\.[A-Za-z0-9_\-]{27,45}|mfa\.[A-Za-z0-9_\-]{80,})")


def extract_discord_tokens_from_reg_or_raw(raw_input):
    """Bóc tách thông minh Token Discord từ mọi định dạng:
    - File/chuỗi Regedit, LevelDB (.ldb / .log), LocalStorage dump
    - Chuỗi cURL / Fetch / Network Headers (F12)
    - Định dạng mua/reg acc: email:pass:token hoặc email|pass|token
    - Token trực tiếp"""
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


def login_discord_reg_session(login_email, password, two_fa_code=""):
    """Đăng nhập lấy Token Discord thông qua Stealth Fingerprint cố định để hạn chế tối đa bị die token."""
    seed_key = f"{login_email}:{password[:4]}"
    s = requests.Session()
    headers = DiscordStealthAntiBanEngine.build_stealth_headers(seed_key, is_bot=False)
    s.headers.update(headers)

    # Bước 1: Khởi tạo X-Fingerprint hợp lệ từ Discord Experiments API
    try:
        r_fp = s.get("https://discord.com/api/v10/experiments", timeout=10)
        if r_fp.status_code == 200:
            fp = r_fp.json().get("fingerprint")
            if fp:
                s.headers["X-Fingerprint"] = fp
    except Exception:
        pass

    # Bước 2: Gửi yêu cầu đăng nhập chuẩn
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
        return {"ok": True, "token": d["token"]}

    if d.get("mfa") and d.get("ticket"):
        if not two_fa_code:
            return {"ok": False, "need_2fa": True, "error": "Tài khoản bật 2FA, hãy nhập mã 6 số 2FA vào ô Mã 2FA"}
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
            return {"ok": True, "token": d_mfa["token"]}
        return {"ok": False, "error": f"Mã 2FA không đúng hoặc hết hạn: {d_mfa.get('message', '')}"}

    if d.get("captcha_key"):
        return {
            "ok": False,
            "error": "Discord yêu cầu Captcha khi đăng nhập bằng mật khẩu từ IP này. Hãy dùng tab 'Dán Chuỗi Reg / F12 / mail:pass:token' để tách Token trực tiếp không dính Captcha!"
        }

    return {"ok": False, "error": d.get("message") or f"Không thể đăng nhập (HTTP {r.status_code})"}


# ============================================================
# CLIENT GIAO THỨC DISCORD STEALTH EDITION
# (BUNG CHỮ TỰ NHIÊN 100% KHÔNG ĐÓNG KHUNG + ẨN ĐƯỜNG CHUYỂN + TAG THẬT)
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
        """Tự động nhận diện Acc Chính Chủ (User Token) hoặc Bot Token thông minh qua đường truyền Stealth."""
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
                                "name": f"👥 [Box Nhóm] {g_name}",
                                "type": "discord_channel",
                                "sub_type": "group_dm",
                                "members": len(recipients) + 1
                            })
                        elif ctype == 1:
                            rec = recipients[0] if recipients else {}
                            dm_name = rec.get("global_name") or rec.get("username") or f"User {cid[-5:]}"
                            out.append({
                                "id": cid,
                                "name": f"💬 [Chat Riêng] {dm_name}",
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
                    "name": f"🌐 {prefix}# {c.get('name', 'channel')}",
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
        """BUNG HẾT CHỮ RA NGOÀI TỰ NHIÊN TRÊN DISCORD (TUYỆT ĐỐI KHÔNG ĐÓNG KHUNG code block):
        - Chữ hiện to, rõ, sắc nét ngay trên nền chat của Discord mà không bị nhốt trong hộp code block đen.
        - Nếu bật `is_heading` (Chữ To In Đậm): dùng cú pháp `# **...**` chuẩn Markdown Discord để bung chữ cỡ lớn."""
        lines = [ln.strip() for ln in str(raw_text or "").split("\n")]
        out_lines = []
        for idx, ln in enumerate(lines):
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

        # Tự động kích hoạt nhịp /typing ngầm theo chu kỳ tự nhiên khi bật antiband
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

        # Chuẩn bị chuỗi Tag Thật Discord (<@uid> và @everyone)
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

        # BUNG TOÀN BỘ CHỮ RA NGOÀI (Không đóng khung code block)
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
                retry_after = r.json().get("retry_after", 8)
            except Exception:
                retry_after = 8
            raise Exception(f"429:RateLimit:{retry_after}")
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

    is_group = (target_type == "group")
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
                if plat == "zalo" and is_group:
                    stripped_txt, auto_m, auto_all = extract_trailing_tags_and_resolve(
                        raw, incoming_mentions=None, zalo_client=client, group_id=target_id
                    )
                elif plat == "discord":
                    stripped_txt, auto_m, auto_all = extract_trailing_tags_and_resolve(
                        raw, incoming_mentions=None, discord_client=client, discord_channel_id=target_id
                    )
                else:
                    stripped_txt, auto_m, auto_all = raw, [], False
                target_parsed_cache[cache_key] = (stripped_txt or raw, auto_m, auto_all)
            c_txt, auto_m, auto_all = target_parsed_cache[cache_key]
            clean_raw = c_txt
            if auto_all:
                eff_tag_all = True
            for am in auto_m:
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
                        strip_line_num=False
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
                            strip_line_num=True
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
                        strip_line_num=strip_line_num
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
                HEALTH_MGR.report_rate_limit(acc_id, retry_after, reason=err_str)
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
            clean_blocks.append(str(b))
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
# (ĐÃ NÂNG CẤP TỰ ĐỘNG TAG CHUẨN THEO KHUNG CHAT ZALO + ẨN LOG ACC NHẠY CẢM)
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
            zalo_client=zalo_client if (platform == "zalo" and is_group) else None,
            group_id=thread_id if (platform == "zalo" and is_group) else None,
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
                zalo_client=zalo_client if (platform == "zalo" and is_group) else None,
                group_id=thread_id if (platform == "zalo" and is_group) else None,
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
        zalo_client=zalo_client if (platform == "zalo" and is_group) else None,
        group_id=thread_id if (platform == "zalo" and is_group) else None,
        prefix_u16_offset=prefix_u16_offset,
        discord_client=discord_client if platform == "discord" else None,
        discord_channel_id=thread_id if platform == "discord" else None,
        full_original_msg=text
    )

    if cmd_token == "all":
        extracted_tag_all = True

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
        self.ws_status = "Đang khởi tạo Zalo WS..."
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
        """Bóc tách toàn diện mảng mentions từ mọi định dạng gói tin Zalo (mentions, mentionInfo, propertyExt, params)."""
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

        known_gids = KNOWN_GROUPS_BY_ACC.get(client.uid, set())
        is_group = bool(
            default_is_group
            or msg_obj.get("_is_group_hint")
            or msg_obj.get("isGroup")
            or (cmd_num == 521)
            or (id_to in known_gids)
            or (uid_from in known_gids)
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

        raw_mentions = self._extract_raw_mentions_from_msg_obj(msg_obj)

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

        self.ws_status = "🟢 Zalo 24/7 Đang Bảo Vệ"
        sock.settimeout(2.5)
        last_ping = time.time()

        try:
            while not self.stop_ev.is_set():
                acc_now = self._get_acc_row()
                if not acc_now or not acc_now.get("chat_cmd_enabled", 1):
                    self.ws_status = "⚪ Đã tắt nhận lệnh"
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
                            self.ws_status = "🟢 Zalo Anti-Ban Active"
                        elif isinstance(outer.get("data"), dict) and outer["data"].get("key"):
                            self.ws_cipher_key = outer["data"]["key"]
                            self.ws_status = "🟢 Zalo Anti-Ban Active"

                        if cmd_id == 3000:
                            self.ws_status = "🟡 Đang đồng bộ lại phiên..."
                            break

                        enc_type = int(outer.get("encrypt", 0))
                        raw_d = outer.get("data")
                        if not raw_d or (cmd_id in (1, 2) and not isinstance(raw_d, str)):
                            continue

                        inner = self._decode_ws_payload(client, raw_d, enc_type)
                        if inner is not None:
                            self.last_event_ts = time.time()
                            is_grp_cmd = (cmd_id == 521)
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
                self.ws_status = "⚪ Đã tắt nhận lệnh"
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
                self.ws_status = "🔴 Đang kết nối lại..."
                self.stop_ev.wait(5.0)


# ============================================================
# LISTENER 24/7 TRÊN DISCORD ACC CHÍNH CHỦ & BOT (STEALTH GATEWAY v10)
# ============================================================
class DiscordSelfBotListener:
    def __init__(self, acc_id):
        self.acc_id = acc_id
        self.platform = "discord"
        self.stop_ev = threading.Event()
        self.seen_msg_ids = deque(maxlen=1000)
        self.ws_status = "Đang kết nối Discord Stealth..."
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
        path = "/?v=10&encoding=json"

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

        sock.settimeout(2.5)
        hb_interval = 38.0
        last_hb = time.time()
        identified = False
        prof = DiscordStealthAntiBanEngine.get_deterministic_profile(client.token)

        try:
            while not self.stop_ev.is_set():
                acc_now = self._get_acc_row()
                if not acc_now or not acc_now.get("chat_cmd_enabled", 1):
                    self.ws_status = "⚪ Đã tắt nhận lệnh"
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
                            hb_interval = max(15.0, (float(d_ev.get("heartbeat_interval", 41250)) / 1000.0) * 0.85)
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
                                            "release_channel": "stable",
                                            "client_build_number": prof["build_number"]
                                        },
                                        "presence": {"status": "online", "since": 0, "activities": [], "afk": False},
                                        "compress": False
                                    }
                                }
                            ZaloSelfBotListener._send_ws_frame(sock, json.dumps(ident_payload).encode("utf-8"), opcode=0x1)
                            identified = True
                            last_hb = time.time()
                            self.ws_status = "🟢 Discord Stealth Route Active"

                        elif op == 0 and t_ev == "READY" and isinstance(d_ev, dict):
                            self.ws_status = "🟢 Discord Stealth Route Active"

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
                self.ws_status = "⚪ Đã tắt nhận lệnh"
                self.stop_ev.wait(4.0)
                continue

            try:
                client = DiscordBot(acc_row["token"], is_bot=bool(acc_row.get("is_bot", 0)))
                if not client.check():
                    self.ws_status = "🔴 Token cần kiểm tra lại"
                    self.stop_ev.wait(10.0)
                    continue

                self._run_gateway_session(client, acc_row)
                self.stop_ev.wait(3.0)
            except Exception:
                self.ws_status = "🔴 Đang kết nối lại..."
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
# GIAO DIỆN NOEL WINTER STUDIO (GIÁNG SINH HOÀNG GIA - GỌN SẠCH - CHỐNG AUTO-ZOOM 100%)
# ============================================================
CSS_NOEL_STUDIO = """
:root {
  --bg-deep: #061017;
  --bg-pine: #0b1c26;
  --bg-card: rgba(12, 28, 38, 0.92);
  --bg-card-inner: #08151d;
  --bg-input: #061118;
  --border-frost: rgba(226, 241, 255, 0.15);
  --border-gold: rgba(251, 191, 36, 0.32);
  --noel-red: #e11d48;
  --noel-red-dark: #be123c;
  --noel-green: #10b981;
  --noel-green-dark: #059669;
  --noel-gold: #fbbf24;
  --noel-ice: #38bdf8;
  --text-main: #f8fafc;
  --text-muted: #94a3b8;
  --radius-xl: 18px;
  --radius-lg: 14px;
  --radius-md: 10px;
  --shadow-card: 0 14px 34px -6px rgba(0, 0, 0, 0.65);
}

html, body {
  margin: 0;
  padding: 0;
  width: 100%;
  min-height: 100vh;
  background-color: var(--bg-deep);
  background-image:
    radial-gradient(circle at 12% 8%, rgba(225, 29, 72, 0.14) 0%, transparent 38%),
    radial-gradient(circle at 88% 10%, rgba(16, 185, 129, 0.14) 0%, transparent 40%),
    radial-gradient(circle at 50% 95%, rgba(251, 191, 36, 0.08) 0%, transparent 45%),
    linear-gradient(180deg, #061017 0%, #0a1922 100%);
  color: var(--text-main);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.5;
  overflow-x: hidden;
  /* CHỐNG TỰ ĐỘNG ZOOM MÀN HÌNH 100% TRÊN ĐIỆN THOẠI & TABLET */
  touch-action: manipulation;
  -webkit-text-size-adjust: 100%;
  -moz-text-size-adjust: 100%;
  text-size-adjust: 100%;
  overscroll-behavior-x: none;
}

*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
  -webkit-tap-highlight-color: transparent;
  touch-action: manipulation;
}

/* CANVAS TUYẾT RƠI NỀN (KHÔNG CHẶN CLICK) */
#snowCanvas {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  pointer-events: none;
  z-index: 1;
}

/* DẢI ĐÈN LED GIÁNG SINH TRÊN ĐỈNH TRANG */
.noel-garland {
  position: sticky;
  top: 0;
  z-index: 50;
  height: 6px;
  width: 100%;
  background: repeating-linear-gradient(
    90deg,
    #e11d48 0px, #e11d48 24px,
    #fbbf24 24px, #fbbf24 48px,
    #10b981 48px, #10b981 72px,
    #38bdf8 72px, #38bdf8 96px
  );
  box-shadow: 0 2px 14px rgba(251, 191, 36, 0.45);
}

.app-container {
  position: relative;
  z-index: 2;
  max-width: 1400px;
  margin: 0 auto;
  padding: 18px 16px 56px;
}

/* HEADER GIÁNG SINH HOÀNG GIA + UPLOAD LOGO */
.noel-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  background: linear-gradient(135deg, rgba(14, 34, 46, 0.96) 0%, rgba(19, 24, 38, 0.96) 100%);
  border: 1px solid var(--border-gold);
  border-radius: var(--radius-xl);
  padding: 16px 20px;
  margin-bottom: 18px;
  box-shadow: var(--shadow-card), inset 0 1px 0 rgba(255, 255, 255, 0.08);
  position: relative;
  overflow: hidden;
}

.brand-area {
  display: flex;
  align-items: center;
  gap: 15px;
  min-width: 0;
}

.logo-frame {
  position: relative;
  width: 62px;
  height: 62px;
  border-radius: 16px;
  background: radial-gradient(circle at 30% 30%, #1e3a2f, #091914);
  border: 2px solid var(--noel-gold);
  box-shadow: 0 0 18px rgba(251, 191, 36, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  cursor: pointer;
  flex-shrink: 0;
}

.logo-frame img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.logo-upload-badge {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  background: rgba(225, 29, 72, 0.88);
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  text-align: center;
  padding: 2px 0;
  letter-spacing: 0.02em;
}

.brand-info {
  min-width: 0;
}

.brand-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.brand-title {
  font-size: 1.25rem;
  font-weight: 900;
  letter-spacing: -0.01em;
  background: linear-gradient(90deg, #ffffff 0%, #fde68a 50%, #6ee7b7 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.brand-subtitle {
  font-size: 0.82rem;
  color: #cbd5e1;
  margin-top: 3px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* KPI GIÁNG SINH */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}

@media (max-width: 920px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
}

.kpi-box {
  background: var(--bg-card);
  border: 1px solid var(--border-frost);
  border-top: 2px solid var(--noel-gold);
  border-radius: var(--radius-lg);
  padding: 13px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: var(--shadow-card);
}

.kpi-title {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.kpi-num {
  font-size: 1.45rem;
  font-weight: 900;
  color: #fff;
  margin-top: 2px;
}

.kpi-art {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: rgba(251, 191, 36, 0.12);
  border: 1px solid rgba(251, 191, 36, 0.28);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

/* LƯỚI BỐ CỤC 2 CỘT GỌN SẠCH */
.main-grid {
  display: grid;
  grid-template-columns: 440px 1fr;
  gap: 18px;
  align-items: start;
}

@media (max-width: 1100px) {
  .main-grid { grid-template-columns: 1fr; }
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border-frost);
  border-radius: var(--radius-xl);
  padding: 18px;
  margin-bottom: 18px;
  box-shadow: var(--shadow-card);
  position: relative;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 12px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border-frost);
}

.card-title {
  font-size: 1rem;
  font-weight: 800;
  color: #fff;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* NHÃN BADGE RÕ NÉT */
.tag-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.74rem;
  font-weight: 800;
}

.b-red    { background: rgba(225, 29, 72, 0.18); color: #fda4af; border: 1px solid rgba(225, 29, 72, 0.4); }
.b-green  { background: rgba(16, 185, 129, 0.18); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.4); }
.b-gold   { background: rgba(251, 191, 36, 0.18); color: #fde68a; border: 1px solid rgba(251, 191, 36, 0.4); }
.b-ice    { background: rgba(56, 189, 248, 0.18); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.4); }

/* FORM INPUTS — BẮT BUỘC FONT-SIZE 16PX ĐỂ KHÔNG BAO GIỜ BỊ TỰ ZOOM MÀN HÌNH */
label {
  display: block;
  font-size: 0.82rem;
  font-weight: 700;
  color: #e2e8f0;
  margin-bottom: 6px;
}

input[type="text"],
input[type="password"],
input[type="number"],
select,
textarea {
  width: 100%;
  background: var(--bg-input);
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  color: #fff;
  font-size: 16px !important; /* Chặn đứng lỗi tự động zoom màn hình trên iOS/Android */
  font-family: inherit;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

input:focus, select:focus, textarea:focus {
  outline: none;
  border-color: var(--noel-gold);
  box-shadow: 0 0 0 2px rgba(251, 191, 36, 0.18);
}

textarea {
  resize: vertical;
  min-height: 88px;
}

/* NÚT BẤM GỌN, RÕ RÀNG, KHÔNG GIẬT ZOOM */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 10px 15px;
  border-radius: var(--radius-md);
  font-weight: 800;
  font-size: 0.86rem;
  cursor: pointer;
  border: 1px solid transparent;
  color: #fff;
  user-select: none;
  text-decoration: none;
  white-space: nowrap;
  transition: filter 0.15s ease, border-color 0.15s ease;
}

.btn:hover { filter: brightness(1.08); }
.btn:active { filter: brightness(0.95); }

.btn-noel-red   { background: linear-gradient(135deg, #e11d48, #be123c); box-shadow: 0 4px 14px rgba(225, 29, 72, 0.32); }
.btn-noel-green { background: linear-gradient(135deg, #10b981, #059669); box-shadow: 0 4px 14px rgba(16, 185, 129, 0.30); }
.btn-noel-gold  { background: linear-gradient(135deg, #fbbf24, #d97706); color: #081218; font-weight: 900; }
.btn-noel-ice   { background: linear-gradient(135deg, #0ea5e9, #0284c7); }
.btn-noel-ghost { background: rgba(255, 255, 255, 0.06); border-color: rgba(226, 241, 255, 0.2); color: #f1f5f9; }
.btn-sm         { padding: 7px 11px; font-size: 0.79rem; border-radius: 8px; }
.btn-block      { width: 100%; }

/* THANH CHUYỂN NỀN TẢNG ZALO / DISCORD */
.plat-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  background: var(--bg-input);
  padding: 5px;
  border-radius: 12px;
  border: 1px solid var(--border-frost);
  margin-bottom: 12px;
}

.plat-tab-btn {
  padding: 9px 12px;
  border-radius: 9px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-weight: 800;
  font-size: 0.85rem;
  cursor: pointer;
}

.plat-tab-btn.active-zalo {
  background: linear-gradient(135deg, #0284c7, #0ea5e9);
  color: #fff;
}

.plat-tab-btn.active-discord {
  background: linear-gradient(135deg, #e11d48, #be123c);
  color: #fff;
}

/* DANH SÁCH CUỘN SẠCH GỌN */
.scroll-list {
  max-height: 250px;
  overflow-y: auto;
  background: var(--bg-card-inner);
  border: 1px solid var(--border-frost);
  border-radius: var(--radius-md);
  padding: 8px;
}

.scroll-list::-webkit-scrollbar { width: 6px; }
.scroll-list::-webkit-scrollbar-thumb { background: rgba(251, 191, 36, 0.32); border-radius: 99px; }

.row-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(17, 38, 51, 0.85);
  border: 1px solid rgba(226, 241, 255, 0.10);
  margin-bottom: 7px;
}

.row-item:last-child { margin-bottom: 0; }
.row-item:hover { border-color: rgba(251, 191, 36, 0.4); }

/* HỘP UPLOAD FILE .TXT CÓ HIỆU ỨNG TIẾN TRÌNH ĐẦY ĐỦ */
.noel-dropzone {
  border: 2px dashed rgba(251, 191, 36, 0.48);
  background: radial-gradient(circle at 50% 0%, rgba(225, 29, 72, 0.10), rgba(16, 185, 129, 0.06));
  border-radius: 14px;
  padding: 18px 14px;
  text-align: center;
  cursor: pointer;
  margin-bottom: 12px;
  transition: border-color 0.2s ease, background-color 0.2s ease;
}

.noel-dropzone.drag-active,
.noel-dropzone:hover {
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.12);
}

.upload-progress-wrap {
  display: none;
  background: var(--bg-input);
  border: 1px solid var(--border-gold);
  border-radius: 11px;
  padding: 10px 12px;
  margin-bottom: 12px;
}

.progress-track {
  width: 100%;
  height: 12px;
  background: #040b10;
  border-radius: 999px;
  overflow: hidden;
  margin-top: 6px;
  border: 1px solid rgba(255,255,255,0.12);
}

@keyframes candyStripe {
  0% { background-position: 0 0; }
  100% { background-position: 40px 0; }
}

.progress-fill {
  height: 100%;
  width: 0%;
  border-radius: 999px;
  background: repeating-linear-gradient(
    45deg,
    #e11d48,
    #e11d48 10px,
    #10b981 10px,
    #10b981 20px
  );
  background-size: 40px 40px;
  animation: candyStripe 1s linear infinite;
  transition: width 0.2s ease;
}

/* SWATCH CHỌN MÀU ZALO */
.swatch-group {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 6px;
}

.swatch-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 800;
  cursor: pointer;
  border: 2px solid transparent;
  background: var(--bg-input);
  color: #fff;
}

.swatch-chip.active {
  border-color: var(--noel-gold);
  box-shadow: 0 0 12px rgba(251, 191, 36, 0.35);
}

.color-dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }

/* TOAST THÔNG BÁO */
#toastBox {
  position: fixed;
  bottom: 18px;
  right: 18px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 360px;
}

.toast-msg {
  background: #0b1c26;
  border-left: 4px solid var(--noel-gold);
  border-top: 1px solid var(--border-frost);
  border-right: 1px solid var(--border-frost);
  border-bottom: 1px solid var(--border-frost);
  color: #fff;
  padding: 12px 15px;
  border-radius: 11px;
  font-size: 0.85rem;
  font-weight: 700;
  box-shadow: 0 12px 28px rgba(0,0,0,0.7);
}

/* KHUNG ĐĂNG NHẬP GỌN SẠCH (ĐÃ XOÁ PHẦN TẠO ACC) */
.auth-screen {
  position: relative;
  z-index: 2;
  min-height: 96vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.auth-box {
  width: 100%;
  max-width: 420px;
  background: var(--bg-card);
  border: 1px solid var(--border-gold);
  border-radius: 22px;
  padding: 28px 24px;
  box-shadow: var(--shadow-card);
}
"""

SVG_NOEL_TREE = """<svg width="36" height="36" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polygon points="32,4 35,11 43,11 37,16 39,23 32,19 25,23 27,16 21,11 29,11" fill="#fbbf24"/>
  <polygon points="32,14 14,34 23,34 11,48 22,48 16,56 48,56 42,48 53,48 41,34 50,34" fill="#10b981" stroke="#6ee7b7" stroke-width="1.5"/>
  <rect x="28" y="56" width="8" height="6" rx="1.5" fill="#b45309"/>
  <circle cx="27" cy="31" r="2.6" fill="#e11d48"/>
  <circle cx="37" cy="39" r="2.6" fill="#fbbf24"/>
  <circle cx="24" cy="45" r="2.6" fill="#38bdf8"/>
  <circle cx="38" cy="50" r="2.6" fill="#e11d48"/>
</svg>"""

HTML_GATE = """<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, minimum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <title>Cổng Bảo Mật — Noel Winter Studio</title>
  <style>""" + CSS_NOEL_STUDIO + """</style>
</head>
<body>
  <div class="noel-garland"></div>
  <div class="auth-screen">
    <div class="auth-box">
      <div style="display:flex;align-items:center;gap:14px;margin-bottom:18px">
        <div class="logo-frame">__BRAND_LOGO_HTML__</div>
        <div>
          <div class="brand-title">NOEL WINTER STUDIO</div>
          <div class="brand-subtitle">Hệ Thống Điều Khiển Zalo & Discord Stealth</div>
        </div>
      </div>
      <p style="font-size:0.85rem;color:var(--text-muted);margin-bottom:14px">
        Nhập khóa bảo mật hệ thống để mở bảng điều khiển Giáng Sinh.
      </p>
      __ERR_BLOCK__
      <form method="post" action="/gate">
        <label>Mã Khóa Truy Cập (Access Key)</label>
        <input type="password" name="key" placeholder="Nhập khóa bảo mật..." required autofocus style="margin-bottom:14px">
        <button type="submit" class="btn btn-noel-red btn-block">🎄 MỞ CỔNG ĐIỀU KHIỂN</button>
      </form>
    </div>
  </div>
</body>
</html>
"""

HTML_LOGIN = """<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, minimum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <title>Đăng Nhập Quản Trị — Noel Winter Studio</title>
  <style>""" + CSS_NOEL_STUDIO + """</style>
</head>
<body>
  <div class="noel-garland"></div>
  <div class="auth-screen">
    <div class="auth-box">
      <div style="display:flex;align-items:center;gap:14px;margin-bottom:18px">
        <div class="logo-frame">__BRAND_LOGO_HTML__</div>
        <div>
          <div class="brand-title">NOEL WINTER STUDIO</div>
          <div class="brand-subtitle">Đăng Nhập Bảng Điều Khiển Quản Trị</div>
        </div>
      </div>
      __MSG_BLOCK__
      <form method="post" action="/login">
        <label>Tài khoản quản trị</label>
        <input type="text" name="username" value="admin" placeholder="Nhập tài khoản..." required style="margin-bottom:12px">
        <label>Mật khẩu</label>
        <input type="password" name="password" placeholder="Nhập mật khẩu quản trị..." required autofocus style="margin-bottom:16px">
        <button type="submit" class="btn btn-noel-green btn-block">❄️ ĐĂNG NHẬP HỆ THỐNG</button>
      </form>
    </div>
  </div>
</body>
</html>
"""

HTML_INDEX_PART1 = """<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, minimum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <title>Noel Winter Studio — Zalo & Discord Stealth Automation</title>
  <style>""" + CSS_NOEL_STUDIO + """</style>
</head>
<body>
  <div class="noel-garland"></div>
  <canvas id="snowCanvas"></canvas>
  <div id="toastBox"></div>

  <!-- INPUT ẨN ĐỂ UPLOAD LOGO THƯƠNG HIỆU -->
  <input type="file" id="logoUploadInput" accept=".png,.jpg,.jpeg,.webp,.gif,.svg" style="display:none" onchange="uploadBrandLogo(this.files)">

  <div class="app-container">
    <!-- HEADER NOEL VỚI CHỖ UPLOAD LOGO RIÊNG & NÚT ĐIỀU KHIỂN GỌN RÕ -->
    <header class="noel-header">
      <div class="brand-area">
        <div class="logo-frame" onclick="document.getElementById('logoUploadInput').click()" title="Bấm để tải Logo của bạn lên">
          <div id="brandLogoContainer">__BRAND_LOGO_HTML__</div>
          <div class="logo-upload-badge">ĐỔI LOGO</div>
        </div>
        <div class="brand-info">
          <div class="brand-heading">
            <span class="brand-title">🎄 NOEL WINTER STUDIO</span>
            <span class="tag-badge b-gold">✨ Dual Anti-Ban Pro</span>
            <span class="tag-badge b-green">🛡️ Stealth Route Discord</span>
          </div>
          <div class="brand-subtitle">
            Zalo Tự Động Tag Chuẩn Khung Chat • Discord Bung Chữ Không Đóng Khung • Reg Token Chống Die • Ẩn Log Acc Bảo Mật
          </div>
        </div>
      </div>

      <div class="header-actions">
        <button type="button" class="btn btn-noel-gold btn-sm" onclick="document.getElementById('logoUploadInput').click()">
          🖼️ Tải Logo Lên
        </button>
        <button type="button" class="btn btn-noel-ghost btn-sm" id="btnSnowToggle" onclick="toggleSnowEffect()">
          ❄️ Tuyết: BẬT
        </button>
        <button type="button" class="btn btn-noel-red btn-sm" onclick="stopAllTasks()">
          ⏹ Dừng Tất Cả
        </button>
        <a href="/logout" class="btn btn-noel-ghost btn-sm">Đăng xuất (__USER__)</a>
      </div>
    </header>

    
    <!-- BANNER ĐỒ HỌA NGHỆ THUẬT GIÁNG SINH ĐÊM ĐÔNG (SVG VECTOR SẮC NÉT) -->
    <div style="position:relative;border-radius:18px;overflow:hidden;border:1px solid rgba(251,191,36,0.35);margin-bottom:18px;background:linear-gradient(135deg,#071622 0%,#122b38 50%,#1d1836 100%);box-shadow:0 14px 34px -6px rgba(0,0,0,0.65)">
      <svg viewBox="0 0 1200 135" width="100%" height="115" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" style="display:block">
        <defs>
          <linearGradient id="skyGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#06131d"/>
            <stop offset="50%" stop-color="#0d2636"/>
            <stop offset="100%" stop-color="#1e1633"/>
          </linearGradient>
          <radialGradient id="moonGlow" cx="0.85" cy="0.28" r="0.18">
            <stop offset="0%" stop-color="#fef08a" stop-opacity="0.95"/>
            <stop offset="40%" stop-color="#fbbf24" stop-opacity="0.35"/>
            <stop offset="100%" stop-color="#fbbf24" stop-opacity="0"/>
          </radialGradient>
        </defs>
        <rect width="1200" height="135" fill="url(#skyGrad)"/>
        <circle cx="1020" cy="38" r="75" fill="url(#moonGlow)"/>
        <circle cx="1020" cy="38" r="22" fill="#fef9c3"/>
        <!-- Các ngôi sao lấp lánh -->
        <circle cx="120" cy="24" r="1.8" fill="#fde68a"/>
        <circle cx="280" cy="18" r="2.2" fill="#fff"/>
        <circle cx="460" cy="30" r="1.5" fill="#fde68a"/>
        <circle cx="640" cy="16" r="2.0" fill="#7dd3fc"/>
        <circle cx="820" cy="28" r="1.8" fill="#fde68a"/>
        <!-- Đồi tuyết xa và gần -->
        <path d="M0,105 Q220,72 480,102 T960,95 T1200,105 L1200,135 L0,135 Z" fill="#0d2838" opacity="0.85"/>
        <path d="M0,115 Q320,88 680,114 T1200,108 L1200,135 L0,135 Z" fill="#133647"/>
        <!-- Rừng thông Noel phủ tuyết và ánh đèn vàng -->
        <g transform="translate(45,42)">
          <polygon points="28,0 6,36 18,36 2,62 16,62 8,82 48,82 40,62 54,62 38,36 50,36" fill="#059669" stroke="#6ee7b7" stroke-width="1.2"/>
          <circle cx="28" cy="0" r="4" fill="#fbbf24"/>
          <circle cx="22" cy="32" r="2.5" fill="#e11d48"/>
          <circle cx="34" cy="48" r="2.5" fill="#fbbf24"/>
          <circle cx="20" cy="64" r="2.5" fill="#38bdf8"/>
        </g>
        <g transform="translate(115,58) scale(0.78)">
          <polygon points="28,0 6,36 18,36 2,62 16,62 8,82 48,82 40,62 54,62 38,36 50,36" fill="#10b981"/>
          <circle cx="28" cy="0" r="3.5" fill="#fde68a"/>
        </g>
        <g transform="translate(1090,46) scale(0.9)">
          <polygon points="28,0 6,36 18,36 2,62 16,62 8,82 48,82 40,62 54,62 38,36 50,36" fill="#059669" stroke="#6ee7b7" stroke-width="1"/>
          <circle cx="28" cy="0" r="4" fill="#fbbf24"/>
          <circle cx="25" cy="40" r="2.5" fill="#e11d48"/>
          <circle cx="33" cy="58" r="2.5" fill="#fbbf24"/>
        </g>
        <!-- Ngôi nhà gỗ Giáng Sinh ấm áp -->
        <g transform="translate(910,66)">
          <rect x="8" y="22" width="46" height="32" rx="3" fill="#7c2d12" stroke="#f59e0b" stroke-width="1"/>
          <polygon points="2,24 31,2 60,24" fill="#e11d48" stroke="#fecdd3" stroke-width="1.5"/>
          <rect x="16" y="30" width="11" height="11" rx="1.5" fill="#fef08a"/>
          <rect x="35" y="30" width="11" height="11" rx="1.5" fill="#fef08a"/>
        </g>
      </svg>
      <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:space-between;padding:14px 28px;flex-wrap:wrap;gap:12px;background:linear-gradient(90deg,rgba(6,16,23,0.45) 0%,rgba(6,16,23,0.75) 50%,rgba(6,16,23,0.35) 100%)">
        <div style="margin-left:110px">
          <div style="font-size:1.05rem;font-weight:900;color:#fef08a;letter-spacing:0.01em">
            🎄 MERRY CHRISTMAS & HAPPY NEW YEAR — HỆ THỐNG TỰ ĐỘNG HÓA ZALO & DISCORD
          </div>
          <div style="font-size:0.8rem;color:#e2e8f0;margin-top:3px">
            2 Động Cơ Anti-Ban Độc Lập • Ẩn Đường Chuyển Discord • Tự Động Tag Chuẩn Khung Chat Zalo • Không Đóng Khung Chữ Discord
          </div>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <span class="tag-badge b-red">🎅 Noel Edition</span>
          <span class="tag-badge b-gold">⚡ 60FPS Smooth</span>
        </div>
      </div>
    </div>

    <!-- 4 THẺ KPI GIÁNG SINH -->
    <section class="kpi-grid">
      <div class="kpi-box">
        <div>
          <div class="kpi-title">Tài Khoản Đang Bảo Vệ</div>
          <div class="kpi-num" id="kpiAccounts">0</div>
        </div>
        <div class="kpi-art">🎅</div>
      </div>
      <div class="kpi-box">
        <div>
          <div class="kpi-title">Chiến Dịch Đang Chạy</div>
          <div class="kpi-num" id="kpiTasks" style="color:#6ee7b7">0</div>
        </div>
        <div class="kpi-art">🦌</div>
      </div>
      <div class="kpi-box">
        <div>
          <div class="kpi-title">Tin Nhắn Đã Phát</div>
          <div class="kpi-num" id="kpiSent" style="color:#fde68a">0</div>
        </div>
        <div class="kpi-art">🔔</div>
      </div>
      <div class="kpi-box">
        <div>
          <div class="kpi-title">Kho File .TXT Sạch</div>
          <div class="kpi-num" id="kpiFiles" style="color:#7dd3fc">0</div>
        </div>
        <div class="kpi-art">🎁</div>
      </div>
    </section>

    <div class="main-grid">
      <!-- CỘT TRÁI: KẾT NỐI TÀI KHOẢN (CÓ LẤY TOKEN DISCORD BẰNG REG), KHO FILE HIỆU ỨNG ĐẦY ĐỦ & PHÂN QUYỀN -->
      <div>
        <!-- MỤC 1: KẾT NỐI TÀI KHOẢN & ANTI-BAN RIÊNG TỪNG APP -->
        <div class="card">
          <div class="card-head">
            <div class="card-title">🎄 1. Kết Nối Tài Khoản (Zalo & Discord Stealth)</div>
            <span class="tag-badge b-green">Ẩn Log Acc</span>
          </div>

          <div class="plat-tabs">
            <button type="button" id="tabZalo" class="plat-tab-btn active-zalo" onclick="switchPlatform('zalo')">
              🔵 Zalo (Anti-Ban Zero-Shift)
            </button>
            <button type="button" id="tabDiscord" class="plat-tab-btn" onclick="switchPlatform('discord')">
              🔴 Discord (Stealth + Reg Token)
            </button>
          </div>

          <input type="hidden" id="accPlatform" value="zalo">

          <div style="margin-bottom:10px">
            <label>Tên gợi nhớ (Tùy chọn)</label>
            <input type="text" id="accName" placeholder="Để trống hệ thống tự lấy tên tài khoản...">
          </div>

          <!-- FORM ZALO -->
          <div id="zaloFields">
            <div style="margin-bottom:10px">
              <label>IMEI Zalo Web</label>
              <input type="text" id="accImei" placeholder="Dán chuỗi IMEI Zalo...">
            </div>
            <div style="margin-bottom:10px">
              <label>Cookie Zalo (JSON hoặc chuỗi Cookie)</label>
              <textarea id="accCookies" rows="3" placeholder='{"zpw_sek":"..."} hoặc dán thẳng Cookie...'></textarea>
            </div>
          </div>

          <!-- FORM DISCORD + TRÌNH LẤY TOKEN BẰNG REG CHỐNG DIE -->
          <div id="discordFields" style="display:none">
            <div style="margin-bottom:10px">
              <label>Token Discord (Dán trực tiếp hoặc dùng công cụ Reg bên dưới)</label>
              <input type="password" id="accToken" placeholder="Dán Token Discord hoặc chuỗi mail:pass:token...">
            </div>

            <!-- HỘP CÔNG CỤ LẤY TOKEN DISCORD BẰNG REG CHỐNG DIE -->
            <div style="background:var(--bg-card-inner);border:1px solid var(--border-gold);border-radius:12px;padding:11px;margin-bottom:10px">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:6px;margin-bottom:8px;flex-wrap:wrap">
                <span style="font-size:0.8rem;font-weight:800;color:#fde68a">
                  🛡️ Lấy & Nuôi Token Discord Bằng Reg (Chống Die Token)
                </span>
                <button type="button" class="btn btn-noel-ghost btn-sm" onclick="copyDiscordRegScript()">
                  📋 Copy Code Lấy Token
                </button>
              </div>

              <div style="margin-bottom:8px">
                <input type="text" id="regRawDump" placeholder="Dán dòng Reg / mail:pass:token / cURL / Header F12 vào đây..." style="margin-bottom:6px">
                <button type="button" class="btn btn-noel-gold btn-sm btn-block" onclick="extractTokenFromReg()">
                  ⚡ Tách Token Từ Reg & Khởi Tạo Fingerprint Chống Die
                </button>
              </div>

              <details style="margin-top:6px">
                <summary style="cursor:pointer;font-size:0.78rem;color:#7dd3fc;font-weight:700">
                  🔑 Hoặc Đăng Nhập Lấy Token Bằng Email / Mật Khẩu (Reg Session)
                </summary>
                <div style="margin-top:8px;display:grid;gap:6px">
                  <input type="text" id="regEmail" placeholder="Email hoặc SĐT Discord...">
                  <input type="password" id="regPass" placeholder="Mật khẩu Discord...">
                  <input type="text" id="reg2fa" placeholder="Mã 2FA 6 số (Nếu tài khoản có bật 2FA)...">
                  <button type="button" class="btn btn-noel-ice btn-sm btn-block" onclick="loginDiscordRegSession()">
                    🚀 Lấy Token Qua Phiên Reg Stealth
                  </button>
                </div>
              </details>
            </div>

            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 11px;background:var(--bg-input);border-radius:10px;border:1px solid var(--border-frost);margin-bottom:10px">
              <span style="font-size:0.8rem;color:#cbd5e1;font-weight:700">Loại Token:</span>
              <select id="accIsBot" style="width:auto;padding:6px 10px">
                <option value="0" selected>👑 Acc Chính Chủ (Stealth User)</option>
                <option value="1">🤖 Discord Bot Token</option>
              </select>
            </div>
          </div>

          <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px;padding:9px 11px;background:var(--bg-input);border-radius:10px;border:1px solid var(--border-frost)">
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.81rem">
              <input type="checkbox" id="accChatCmd" checked> Bật lệnh chat 24/7 (<code>.menu</code>, <code>.nhay</code>)
            </label>
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.81rem;color:#fde68a">
              <input type="checkbox" id="accAllowAll"> Cho mọi người dùng lệnh
            </label>
          </div>

          <button type="button" class="btn btn-noel-green btn-block" onclick="addAccount()">
            ➕ LƯU TÀI KHOẢN & BẬT LÁ CHẮN ANTI-BAN
          </button>

          <div style="margin-top:14px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px;flex-wrap:wrap;gap:6px">
              <span style="font-size:0.78rem;color:var(--text-muted);font-weight:800">DANH SÁCH ACC (ĐÃ ẨN THÔNG TIN NHẠY CẢM)</span>
              <div style="display:flex;gap:5px">
                <button type="button" class="btn btn-noel-ghost btn-sm" id="btnMaskAcc" onclick="toggleMaskAccounts()">🔒 Ẩn Tên: BẬT</button>
                <button type="button" class="btn btn-noel-ghost btn-sm" onclick="loadAccounts(true)">🔄 Làm mới</button>
              </div>
            </div>
            <div id="accListBox" class="scroll-list" style="max-height:230px"></div>
          </div>
        </div>

        <!-- MỤC 2: KHO FILE .TXT VỚI HIỆU ỨNG UPLOAD PROGRESS BAR ĐẦY ĐỦ -->
        <div class="card">
          <div class="card-head">
            <div class="card-title">🎁 2. Kho File .TXT (Có Hiệu Ứng Tải Lên & Lọc Số Đầu Dòng)</div>
            <span class="tag-badge b-gold">Auto Clean</span>
          </div>

          <div class="noel-dropzone" id="fileDropzone"
               onclick="document.getElementById('fileInput').click()"
               ondragenter="onDragZone(event, true)"
               ondragover="onDragZone(event, true)"
               ondragleave="onDragZone(event, false)"
               ondrop="handleDropFile(event)">
            <div style="font-size:1.75rem;margin-bottom:4px">🎄📤</div>
            <div style="font-weight:800;font-size:0.88rem;color:#fff">Bấm chọn hoặc kéo thả file .txt vào Hộp Quà Noel</div>
            <div style="font-size:0.76rem;color:var(--text-muted);margin-top:3px">
              Tự động xoá số <code>1.</code>, <code>2.</code> đầu dòng • Gõ <code>.nhay 1</code> hoặc <code>.file 1 @Tên</code> trong chat là chạy ngay
            </div>
            <input type="file" id="fileInput" multiple accept=".txt" style="display:none" onchange="uploadFilesWithProgress(this.files)">
          </div>

          <!-- THANH HIỆU ỨNG TIẾN TRÌNH UPLOAD FILE -->
          <div id="uploadProgressWrap" class="upload-progress-wrap">
            <div style="display:flex;justify-content:space-between;align-items:center;font-size:0.8rem;font-weight:800">
              <span id="uploadProgressLabel" style="color:#fde68a">❄️ Đang tải file lên...</span>
              <span id="uploadProgressPct" style="color:#6ee7b7">0%</span>
            </div>
            <div class="progress-track">
              <div id="uploadProgressBar" class="progress-fill"></div>
            </div>
          </div>

          <div id="fileListBox" class="scroll-list" style="max-height:220px"></div>
        </div>

        <!-- MỤC 3: PHÂN QUYỀN DÙNG LỆNH CHAT -->
        <div class="card">
          <div class="card-head">
            <div class="card-title">🔑 3. Cấp Quyền Dùng Lệnh Trong Khung Chat</div>
            <span class="tag-badge b-ice">.chophep @Tên</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr auto;gap:6px;margin-bottom:10px">
            <input type="text" id="authUidInput" placeholder="UID Zalo/Discord...">
            <input type="text" id="authNameInput" placeholder="Tên hiển thị...">
            <button type="button" class="btn btn-noel-ice btn-sm" onclick="addAuthUserWeb()">+ Thêm</button>
          </div>
          <div id="authUserBox" class="scroll-list" style="max-height:135px"></div>
        </div>
      </div>

      <!-- CỘT PHẢI: CHỌN BOX & TỰ ĐỘNG TAG CHUẨN ZALO/DISCORD + BẢNG ĐIỀU KHIỂN CHIẾN DỊCH -->
      <div>
        <!-- MỤC 4: CHỌN BOX & TỰ ĐỘNG TAG CHUẨN KHUNG CHAT -->
        <div class="card">
          <div class="card-head">
            <div class="card-title">🦌 4. Chọn Box Chat & Tự Động Tag Chuẩn Khung Chat (Zalo + Discord)</div>
            <span class="tag-badge b-green" id="selectedBoxBadge">Đã chọn: 0 box</span>
          </div>

          <div style="display:grid;grid-template-columns:1fr auto;gap:8px;margin-bottom:10px">
            <div>
              <label>Chọn tài khoản để lấy danh sách Nhóm Zalo / Box Discord</label>
              <select id="groupAccSelect" onchange="onAccountSelectChange()"></select>
            </div>
            <div style="display:flex;align-items:flex-end;gap:6px;flex-wrap:wrap">
              <button type="button" class="btn btn-noel-ice btn-sm" onclick="fetchZaloGroups()">📂 Nhóm Zalo</button>
              <button type="button" class="btn btn-noel-ghost btn-sm" onclick="fetchZaloFriends()">👥 Bạn Bè</button>
              <button type="button" class="btn btn-noel-red btn-sm" onclick="fetchDiscordAllBoxes()">🔴 All Box Discord</button>
            </div>
          </div>

          <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:9px">
            <input type="text" id="boxSearchInput" placeholder="🔍 Tìm nhanh tên nhóm, bạn bè hoặc kênh Discord..."
                   oninput="renderTargetBoxes()" style="flex:1;min-width:180px">
            <button type="button" class="btn btn-noel-gold btn-sm" onclick="selectTopBoxes(3)">⚡ Chọn 3 Box</button>
            <button type="button" class="btn btn-noel-gold btn-sm" onclick="selectTopBoxes(5)">⚡ Chọn 5 Box</button>
            <button type="button" class="btn btn-noel-ghost btn-sm" onclick="toggleAllBoxes(true)">Chọn hết</button>
            <button type="button" class="btn btn-noel-ghost btn-sm" onclick="toggleAllBoxes(false)">Bỏ chọn</button>
          </div>

          <div style="display:flex;gap:6px;margin-bottom:10px">
            <input type="text" id="manualBoxId" placeholder="Nhập thêm ID Nhóm Zalo hoặc Channel ID Discord..." style="flex:1">
            <select id="manualBoxType" style="width:165px">
              <option value="group">Nhóm Zalo</option>
              <option value="user">Bạn bè Zalo</option>
              <option value="discord_channel">Kênh Discord</option>
            </select>
            <button type="button" class="btn btn-noel-ghost btn-sm" onclick="addManualBox()">+ Thêm</button>
          </div>

          <div id="targetBoxContainer" class="scroll-list" style="max-height:215px;margin-bottom:12px">
            <div style="text-align:center;color:var(--text-muted);padding:16px;font-size:0.84rem">
              Chọn tài khoản rồi bấm <b>Nhóm Zalo</b> hoặc <b>All Box Discord</b>. Khi tích chọn nhóm Zalo, danh sách thành viên để Tag sẽ tự động nạp ngay bên dưới!
            </div>
          </div>

          <!-- BẢNG TAG THẬT TỰ ĐỘNG CHUẨN KHUNG CHAT ZALO & DISCORD -->
          <div style="background:var(--bg-card-inner);border:1px solid var(--border-gold);border-radius:12px;padding:12px">
            <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:8px">
              <div style="font-size:0.85rem;font-weight:800;color:#fde68a">
                🏷️ Tự Động Tag Tên Chuẩn Khung Chat (Zalo Mention Xanh Dương & Discord Mention)
              </div>
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                <label style="display:flex;align-items:center;gap:5px;margin:0;cursor:pointer;font-size:0.81rem;color:#6ee7b7">
                  <input type="checkbox" id="tagAllCheck"> Tag @All / @everyone
                </label>
                <button type="button" class="btn btn-noel-ice btn-sm" onclick="loadMembersOfSelectedBox()">
                  🔄 Tải Lại Thành Viên Nhóm
                </button>
              </div>
            </div>

            <div style="display:flex;gap:6px;margin-bottom:7px">
              <input type="text" id="memberSearchInput" placeholder="🔍 Tìm tên thành viên trong khung chat để Tag..."
                     oninput="renderMemberTags()" style="flex:1">
              <button type="button" class="btn btn-noel-ghost btn-sm" onclick="toggleAllMembers(true)">Tag Hết</button>
              <button type="button" class="btn btn-noel-ghost btn-sm" onclick="toggleAllMembers(false)">Bỏ Tag</button>
            </div>

            <div id="memberTagContainer" class="scroll-list" style="max-height:145px">
              <div style="text-align:center;color:var(--text-muted);padding:10px;font-size:0.8rem">
                Tích chọn 1 nhóm Zalo hoặc kênh Discord ở trên để hệ thống tự động lấy toàn bộ thành viên trong khung chat (hoặc gõ thẳng <code>@Tên</code> ở cuối câu).
              </div>
            </div>
          </div>
        </div>
"""

HTML_INDEX_PART2 = """
        <!-- MỤC 5: KHỞI CHẠY CHIẾN DỊCH (DISCORD BUNG CHỮ KHÔNG ĐÓNG KHUNG + ZALO RICH-TEXT) -->
        <div class="card">
          <div class="card-head">
            <div class="card-title">🚀 5. Khởi Chạy Chiến Dịch (Discord Bung Chữ Tự Nhiên • Zalo Đổi Màu Chữ To)</div>
            <span class="tag-badge b-red">No-Frame Discord</span>
          </div>

          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin-bottom:12px">
            <div>
              <label>Chế độ gửi</label>
              <select id="taskMode">
                <option value="treo_nhay" selected>🔥 Treo Nhây (Từng dòng - Tự xoá số 1., 2.)</option>
                <option value="treo_ngon">📜 Treo Ngôn (Gửi nguyên khối văn bản)</option>
                <option value="fast">⚡ Spam Tốc Độ Cao</option>
              </select>
            </div>
            <div>
              <label>Chọn nhanh File .TXT theo Số Thứ Tự</label>
              <select id="taskFileSelect" onchange="onFileSelectChange()">
                <option value="">-- Hoặc nhập nội dung trực tiếp bên dưới --</option>
              </select>
            </div>
          </div>

          <div style="margin-bottom:12px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;flex-wrap:wrap;gap:4px">
              <label style="margin:0">Nội dung gửi (Gõ <code>@Tên</code> ở cuối câu hoặc tích chọn ở Mục 4 để tự động Tag chuẩn)</label>
              <span style="font-size:0.75rem;color:#6ee7b7;font-weight:800">
                ✨ Bên Discord chữ tự bung to rõ, không bao giờ đóng khung đen!
              </span>
            </div>
            <textarea id="taskRawText" rows="4" placeholder="Nhập nội dung tin nhắn... (Có thể gõ @Tên thành viên ở cuối câu để hệ thống tự động nhận diện Tag chuẩn theo khung chat Zalo & Discord)"></textarea>
          </div>

          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:10px;margin-bottom:12px">
            <div>
              <label>Chế độ Màu Chữ Zalo / Kiểu Chữ</label>
              <select id="colorMode" onchange="toggleFixedColorSwatches()">
                <option value="rainbow" selected>🌈 Phối Màu Từng Dòng</option>
                <option value="word_rainbow">✨ Phối Màu Từng Từ</option>
                <option value="random">🎲 Ngẫu Nhiên</option>
                <option value="fixed">🎨 Khóa Cố Định 1 Màu</option>
                <option value="none">⚪ Chữ Thường</option>
              </select>
            </div>
            <div>
              <label>Độ Trễ Delay (Giây)</label>
              <input type="number" id="taskDelay" value="1.0" min="0.2" max="120" step="0.1">
            </div>
            <div>
              <label>Số Lượng Icon VIP</label>
              <input type="number" id="iconCount" value="3" min="0" max="10" step="1">
            </div>
          </div>

          <div id="fixedColorBox" style="display:none;margin-bottom:12px;padding:10px 12px;background:var(--bg-input);border-radius:10px;border:1px solid var(--border-frost)">
            <label style="margin-bottom:4px">Chọn Màu Cố Định Zalo Rich-Text:</label>
            <input type="hidden" id="fixedColorVal" value="red">
            <div class="swatch-group">
              <div class="swatch-chip active" onclick="pickSwatch('red',this)">
                <span class="color-dot" style="background:#db342e"></span> Đỏ Rực
              </div>
              <div class="swatch-chip" onclick="pickSwatch('yellow',this)">
                <span class="color-dot" style="background:#f7b503"></span> Vàng Kim
              </div>
              <div class="swatch-chip" onclick="pickSwatch('green',this)">
                <span class="color-dot" style="background:#15a85f"></span> Xanh Ngọc
              </div>
              <div class="swatch-chip" onclick="pickSwatch('orange',this)">
                <span class="color-dot" style="background:#f27806"></span> Cam Lửa
              </div>
            </div>
          </div>

          <div style="display:flex;gap:14px;flex-wrap:wrap;padding:10px 12px;background:var(--bg-input);border:1px solid var(--border-frost);border-radius:11px;margin-bottom:12px">
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.82rem;color:#6ee7b7">
              <input type="checkbox" id="chkStripNum" checked> ✂️ Tự xoá số <code>1.</code>, <code>2.</code> đầu dòng
            </label>
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.82rem;color:#fde68a">
              <input type="checkbox" id="chkBigText" checked> 🔠 Bung Chữ To In Đậm (Zalo & Discord)
            </label>
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.82rem">
              <input type="checkbox" id="chkUseEmoji" checked> 😎 Gắn Icon VIP
            </label>
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.82rem;color:#7dd3fc">
              <input type="checkbox" id="chkAntiband" checked> 🛡️ Bật Anti-Ban Chuyên Sâu (Zalo + Discord Stealth)
            </label>
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.82rem">
              <input type="checkbox" id="chkMultiAcc" checked> 👥 Chạy Đa Acc
            </label>
          </div>

          <div style="display:grid;grid-template-columns:2fr 1fr;gap:10px">
            <button type="button" class="btn btn-noel-red" style="font-size:0.94rem;padding:12px" onclick="startCampaign()">
              🎄 KHỞI CHẠY CHIẾN DỊCH NGAY
            </button>
            <button type="button" class="btn btn-noel-green" onclick="applyLiveConfig()">
              ⚡ CẬP NHẬT NÓNG DELAY/MÀU
            </button>
          </div>
        </div>

        <!-- MỤC 6: GIÁM SÁT TIẾN TRÌNH & LOG ĐÃ ẨN THÔNG TIN ACC NHẠY CẢM -->
        <div class="card">
          <div class="card-head">
            <div class="card-title">📡 6. Giám Sát Tiến Trình & Nhật Ký Bảo Mật (Đã Ẩn Log Acc)</div>
            <div style="display:flex;gap:6px;flex-wrap:wrap">
              <button type="button" class="btn btn-noel-ghost btn-sm" id="btnToggleLogPanel" onclick="toggleBotLogVisibility()">
                👁️ Hiện Nhật Ký Lệnh
              </button>
              <button type="button" class="btn btn-noel-ghost btn-sm" onclick="clearStoppedTasks()">🧹 Dọn Task Dừng</button>
              <button type="button" class="btn btn-noel-red btn-sm" onclick="stopAllTasks()">⏹ Dừng Hết</button>
            </div>
          </div>

          <div id="activeTasksBox" class="scroll-list" style="max-height:210px"></div>

          <!-- PHẦN LOG LỆNH KHUNG CHAT MẶC ĐỊNH ĐƯỢC ẨN GỌN ĐỂ BẢO MẬT ACC -->
          <div id="stealthLogSection" style="display:none;margin-top:12px;border-top:1px solid var(--border-frost);padding-top:12px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px">
              <span style="font-size:0.78rem;font-weight:800;color:#fde68a">
                🔒 NHẬT KÝ LỆNH KHUNG CHAT (ĐÃ MÃ HÓA ẨN UID/TOKEN)
              </span>
              <button type="button" class="btn btn-noel-ghost btn-sm" onclick="clearBotLogs()">Xóa log</button>
            </div>
            <div id="botLogsBox" class="scroll-list" style="max-height:150px"></div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
    // ============================================================
    // CHẶN TUYỆT ĐỐI LỖI ẤN VÀO MÀN HÌNH BỊ TỰ ĐỘNG ZOOM TO
    // ============================================================
    document.addEventListener("gesturestart", function(e) { e.preventDefault(); }, {passive: false});
    document.addEventListener("gesturechange", function(e) { e.preventDefault(); }, {passive: false});
    document.addEventListener("gestureend", function(e) { e.preventDefault(); }, {passive: false});
    let lastTouchEnd = 0;
    document.addEventListener("touchend", function(e) {
      const now = Date.now();
      if (now - lastTouchEnd <= 280) {
        e.preventDefault();
      }
      lastTouchEnd = now;
    }, {passive: false});

    // ============================================================
    // HIỆU ỨNG TUYẾT RƠI GIÁNG SINH 60FPS SIÊU MƯỢT
    // ============================================================
    let SNOW_ENABLED = true;
    (function initSnow() {
      const canvas = document.getElementById("snowCanvas");
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      let w = canvas.width = window.innerWidth;
      let h = canvas.height = window.innerHeight;
      window.addEventListener("resize", () => {
        w = canvas.width = window.innerWidth;
        h = canvas.height = window.innerHeight;
      });
      const flakes = Array.from({length: 55}, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        r: Math.random() * 2.6 + 1.0,
        vy: Math.random() * 0.85 + 0.35,
        vx: (Math.random() - 0.5) * 0.45,
        alpha: Math.random() * 0.55 + 0.25
      }));
      function drawSnow() {
        ctx.clearRect(0, 0, w, h);
        if (SNOW_ENABLED) {
          for (const f of flakes) {
            ctx.beginPath();
            ctx.arc(f.x, f.y, f.r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(240, 249, 255, ${f.alpha})`;
            ctx.fill();
            f.y += f.vy;
            f.x += f.vx;
            if (f.y > h + 6) { f.y = -6; f.x = Math.random() * w; }
            if (f.x > w + 6) f.x = -6;
            if (f.x < -6) f.x = w + 6;
          }
        }
        requestAnimationFrame(drawSnow);
      }
      requestAnimationFrame(drawSnow);
    })();

    function toggleSnowEffect() {
      SNOW_ENABLED = !SNOW_ENABLED;
      const btn = document.getElementById("btnSnowToggle");
      btn.textContent = SNOW_ENABLED ? "❄️ Tuyết: BẬT" : "❄️ Tuyết: TẮT";
    }

    // ============================================================
    // QUẢN LÝ TRẠNG THÁI GIAO DIỆN & SMART DOM DIFFING
    // ============================================================
    let ALL_ACCOUNTS = [];
    let ALL_FILES = [];
    let LOADED_BOXES = [];
    let SELECTED_BOX_MAP = {};
    let LOADED_MEMBERS = [];
    let SELECTED_MEMBER_MAP = {};
    let LAST_ACC_SELECT_SIG = "";
    let LAST_FILE_SELECT_SIG = "";
    let MASK_ACC_MODE = true;
    let SHOW_BOT_LOG_PANEL = false;

    function setHtmlIfChanged(el, htmlStr) {
      if (!el) return;
      if (el._lastHtml === htmlStr) return;
      el._lastHtml = htmlStr;
      el.innerHTML = htmlStr;
    }

    function esc(s) {
      return String(s == null ? "" : s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function maskStr(str) {
      const s = String(str || "");
      if (!MASK_ACC_MODE) return s;
      if (s.length <= 4) return s.slice(0, 1) + "***";
      return s.slice(0, 3) + "***" + s.slice(-2);
    }

    function toast(msg, isErr = false) {
      const box = document.getElementById("toastBox");
      const d = document.createElement("div");
      d.className = "toast-msg";
      if (isErr) d.style.borderLeftColor = "#e11d48";
      d.textContent = msg;
      box.appendChild(d);
      setTimeout(() => { d.remove(); }, 3200);
    }

    // UPLOAD LOGO THƯƠNG HIỆU LÊN SERVER
    async function uploadBrandLogo(fileList) {
      if (!fileList || !fileList.length) return;
      const fd = new FormData();
      fd.append("logo", fileList[0]);
      toast("🎄 Đang tải Logo thương hiệu lên...");
      try {
        const r = await fetch("/api/upload_logo", {method: "POST", body: fd});
        const d = await r.json();
        if (!d.ok) return toast(d.error || "Lỗi tải Logo", true);
        const container = document.getElementById("brandLogoContainer");
        container.innerHTML = `<img src="${d.logo_url}?t=${Date.now()}" alt="Brand Logo">`;
        toast("✅ Đã cập nhật Logo thương hiệu thành công!");
      } catch (e) {
        toast("Lỗi kết nối khi tải Logo", true);
      }
    }

    function toggleMaskAccounts() {
      MASK_ACC_MODE = !MASK_ACC_MODE;
      document.getElementById("btnMaskAcc").textContent = MASK_ACC_MODE ? "🔒 Ẩn Tên: BẬT" : "🔓 Ẩn Tên: TẮT";
      loadAccounts(true);
    }

    function toggleBotLogVisibility() {
      SHOW_BOT_LOG_PANEL = !SHOW_BOT_LOG_PANEL;
      document.getElementById("stealthLogSection").style.display = SHOW_BOT_LOG_PANEL ? "block" : "none";
      document.getElementById("btnToggleLogPanel").textContent = SHOW_BOT_LOG_PANEL ? "🙈 Ẩn Nhật Ký Lệnh" : "👁️ Hiện Nhật Ký Lệnh";
    }

    function switchPlatform(plat) {
      document.getElementById("accPlatform").value = plat;
      const zBtn = document.getElementById("tabZalo");
      const dBtn = document.getElementById("tabDiscord");
      const zFields = document.getElementById("zaloFields");
      const dFields = document.getElementById("discordFields");
      if (plat === "zalo") {
        zBtn.className = "plat-tab-btn active-zalo";
        dBtn.className = "plat-tab-btn";
        zFields.style.display = "block";
        dFields.style.display = "none";
      } else {
        zBtn.className = "plat-tab-btn";
        dBtn.className = "plat-tab-btn active-discord";
        zFields.style.display = "none";
        dFields.style.display = "block";
      }
    }

    function toggleFixedColorSwatches() {
      const cm = document.getElementById("colorMode").value;
      document.getElementById("fixedColorBox").style.display = (cm === "fixed") ? "block" : "none";
    }

    function pickSwatch(cId, el) {
      document.getElementById("fixedColorVal").value = cId;
      document.querySelectorAll(".swatch-chip").forEach(p => p.classList.remove("active"));
      el.classList.add("active");
    }

    // CÔNG CỤ LẤY TOKEN DISCORD BẰNG REG CHỐNG DIE
    function copyDiscordRegScript() {
      const scriptCode = `window.webpackChunkdiscord_app.push([[Math.random()],{},req=>{for(const m of Object.keys(req.c).map(x=>req.c[x].exports).filter(x=>x)){if(m.default&&m.default.getToken!==undefined)return copy(m.default.getToken());if(m.getToken!==undefined)return copy(m.getToken())}}]);console.log("Đã copy Token Discord vào Clipboard!");`;
      navigator.clipboard.writeText(scriptCode).then(() => {
        toast("✅ Đã copy đoạn mã Reg lấy Token Discord an toàn (Dán vào Console F12 là tự copy Token)!");
      }).catch(() => {
        prompt("Copy đoạn mã lấy Token an toàn này dán vào F12 Console Discord:", scriptCode);
      });
    }

    async function extractTokenFromReg() {
      const raw_dump = document.getElementById("regRawDump").value.trim();
      if (!raw_dump) return toast("Hãy dán chuỗi Reg / mail:pass:token / Header F12 vào ô!", true);
      toast("⏳ Đang tách Token & khởi tạo hồ sơ Stealth Fingerprint chống die...");
      try {
        const r = await fetch("/api/discord_reg_token", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({mode: "extract", raw_dump})
        });
        const d = await r.json();
        if (!d.ok) return toast(d.error || "Không tìm thấy Token hợp lệ", true);
        document.getElementById("accToken").value = d.token;
        if (d.username && !document.getElementById("accName").value) {
          document.getElementById("accName").value = d.username;
        }
        toast(`✅ Token Live (${d.username || "OK"})! Bấm 'Lưu Tài Khoản' để kết nối.`);
      } catch (e) {
        toast("Lỗi kiểm tra Token", true);
      }
    }

    async function loginDiscordRegSession() {
      const email = document.getElementById("regEmail").value.trim();
      const password = document.getElementById("regPass").value;
      const two_fa = document.getElementById("reg2fa").value.trim();
      if (!email || !password) return toast("Hãy nhập Email và Mật khẩu Discord!", true);
      toast("⏳ Đang đăng nhập qua phiên Reg Stealth...");
      try {
        const r = await fetch("/api/discord_reg_token", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({mode: "login", email, password, two_fa})
        });
        const d = await r.json();
        if (!d.ok) return toast(d.error || "Không lấy được Token", true);
        document.getElementById("accToken").value = d.token;
        toast("✅ Đã lấy Token qua phiên Reg thành công! Bấm 'Lưu Tài Khoản' ngay.");
      } catch (e) {
        toast("Lỗi kết nối máy chủ", true);
      }
    }

    // 1. QUẢN LÝ TÀI KHOẢN (ẨN LOG ACC BẢO MẬT)
    async function loadAccounts(force = false) {
      try {
        const r = await fetch("/api/accounts");
        const d = await r.json();
        ALL_ACCOUNTS = d.accounts || [];
        document.getElementById("kpiAccounts").textContent = ALL_ACCOUNTS.length;

        const box = document.getElementById("accListBox");
        if (!ALL_ACCOUNTS.length) {
          setHtmlIfChanged(box, `<div style="text-align:center;color:var(--text-muted);padding:14px;font-size:0.82rem">Chưa có tài khoản nào. Hãy thêm Zalo hoặc Discord ở trên.</div>`);
        } else {
          const html = ALL_ACCOUNTS.map(a => {
            const isZalo = (a.platform || "zalo") === "zalo";
            const platBadge = isZalo
              ? `<span class="tag-badge b-ice">ZALO ANTI-BAN</span>`
              : `<span class="tag-badge b-red">DISCORD STEALTH</span>`;
            const cmdOn = a.chat_cmd_enabled ? "🟢 24/7" : "⚪ Tắt";
            const dispName = MASK_ACC_MODE ? maskStr(a.name) : a.name;
            return `
              <div class="row-item">
                <div style="min-width:0;flex:1">
                  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
                    ${platBadge}
                    <b style="font-size:0.86rem;color:#fff">${esc(dispName)}</b>
                  </div>
                  <div style="font-size:0.74rem;color:var(--text-muted);margin-top:2px">
                    ${esc(a.ws_status || "Đang bảo vệ")} • Chế độ: <b>${a.allow_all_cmd ? "Mọi người" : "Chỉ Chủ Acc"}</b>
                  </div>
                </div>
                <div style="display:flex;gap:5px;flex-wrap:wrap">
                  <button type="button" class="btn btn-noel-ghost btn-sm" onclick="toggleAccCmd(${a.id})">${cmdOn}</button>
                  <button type="button" class="btn btn-noel-ghost btn-sm" onclick="toggleAllowAll(${a.id})">🔒</button>
                  <button type="button" class="btn btn-noel-red btn-sm" onclick="deleteAccount(${a.id})">✕</button>
                </div>
              </div>
            `;
          }).join("");
          setHtmlIfChanged(box, html);
        }

        const sig = ALL_ACCOUNTS.map(a => `${a.id}:${a.platform}:${a.name}:${MASK_ACC_MODE}`).join("|");
        if (force || sig !== LAST_ACC_SELECT_SIG) {
          LAST_ACC_SELECT_SIG = sig;
          const sel = document.getElementById("groupAccSelect");
          const prevVal = sel.value;
          sel.innerHTML = ALL_ACCOUNTS.length
            ? ALL_ACCOUNTS.map(a => `<option value="${a.id}">[${(a.platform || "zalo").toUpperCase()}] ${esc(MASK_ACC_MODE ? maskStr(a.name) : a.name)}</option>`).join("")
            : `<option value="">-- Chưa có tài khoản --</option>`;
          if (prevVal && ALL_ACCOUNTS.some(a => String(a.id) === String(prevVal))) {
            sel.value = prevVal;
          }
        }
      } catch (e) {}
    }

    async function addAccount() {
      const platform = document.getElementById("accPlatform").value;
      const name = document.getElementById("accName").value.trim();
      const imei = document.getElementById("accImei").value.trim();
      const cookies = document.getElementById("accCookies").value.trim();
      const token = document.getElementById("accToken").value.trim();
      const is_bot = parseInt(document.getElementById("accIsBot").value || "0", 10);
      const chat_cmd_enabled = document.getElementById("accChatCmd").checked ? 1 : 0;
      const allow_all_cmd = document.getElementById("accAllowAll").checked ? 1 : 0;

      toast("⏳ Đang xác thực và kích hoạt lá chắn Anti-Ban riêng...");
      try {
        const r = await fetch("/api/accounts", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({platform, name, imei, cookies, token, is_bot, chat_cmd_enabled, allow_all_cmd})
        });
        const d = await r.json();
        if (!d.ok) return toast(d.error || "Lỗi thêm tài khoản", true);
        toast(`✅ Đã kết nối & bật Anti-Ban: ${d.name}`);
        document.getElementById("accName").value = "";
        document.getElementById("accImei").value = "";
        document.getElementById("accCookies").value = "";
        document.getElementById("accToken").value = "";
        await loadAccounts(true);
      } catch (e) {
        toast("Lỗi kết nối máy chủ", true);
      }
    }

    async function deleteAccount(aid) {
      await fetch(`/api/delete_account/${aid}`, {method: "POST"});
      toast("Đã xóa tài khoản");
      loadAccounts(true);
    }

    async function toggleAccCmd(aid) {
      await fetch(`/api/toggle_account_cmd/${aid}`, {method: "POST"});
      loadAccounts();
    }

    async function toggleAllowAll(aid) {
      const r = await fetch(`/api/toggle_allow_all/${aid}`, {method: "POST"});
      const d = await r.json();
      if (d.ok) toast(d.allow_all ? "Đã mở cho mọi người dùng lệnh" : "Đã khóa: Chỉ chủ Acc & người được cấp quyền");
      loadAccounts();
    }

    // 2. UPLOAD FILE .TXT VỚI HIỆU ỨNG THANH TIẾN TRÌNH ĐẦY ĐỦ
    function onDragZone(ev, active) {
      ev.preventDefault();
      const dz = document.getElementById("fileDropzone");
      if (active) dz.classList.add("drag-active");
      else dz.classList.remove("drag-active");
    }

    function handleDropFile(ev) {
      ev.preventDefault();
      onDragZone(ev, false);
      if (ev.dataTransfer && ev.dataTransfer.files.length) {
        uploadFilesWithProgress(ev.dataTransfer.files);
      }
    }

    function uploadFilesWithProgress(fileList) {
      if (!fileList || !fileList.length) return;
      const wrap = document.getElementById("uploadProgressWrap");
      const bar = document.getElementById("uploadProgressBar");
      const pctEl = document.getElementById("uploadProgressPct");
      const lblEl = document.getElementById("uploadProgressLabel");

      wrap.style.display = "block";
      bar.style.width = "0%";
      pctEl.textContent = "0%";
      lblEl.textContent = `🎄 Đang tải lên ${fileList.length} file & lọc số đầu dòng...`;

      const fd = new FormData();
      for (let i = 0; i < fileList.length; i++) {
        fd.append("file", fileList[i]);
      }

      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload_file", true);

      xhr.upload.onprogress = function(e) {
        if (e.lengthComputable) {
          const pct = Math.min(100, Math.round((e.loaded / e.total) * 100));
          bar.style.width = pct + "%";
          pctEl.textContent = pct + "%";
        }
      };

      xhr.onload = async function() {
        try {
          const d = JSON.parse(xhr.responseText || "{}");
          if (!d.ok) {
            lblEl.textContent = "❌ " + (d.error || "Lỗi tải file");
            return;
          }
          bar.style.width = "100%";
          pctEl.textContent = "100%";
          lblEl.textContent = `✅ Hoàn tất! Đã lưu ${d.uploaded.length} file sạch vào kho.`;
          toast(`🎁 Đã tải lên thành công ${d.uploaded.length} file .txt!`);
          await loadFiles(true);
          if (d.uploaded.length === 1) {
            useFileNow(d.uploaded[0].id);
          }
          setTimeout(() => { wrap.style.display = "none"; }, 2600);
        } catch (err) {
          lblEl.textContent = "❌ Phản hồi máy chủ không hợp lệ";
        }
      };

      xhr.onerror = function() {
        lblEl.textContent = "❌ Lỗi mạng khi tải file lên";
      };

      xhr.send(fd);
    }

    async function loadFiles(force = false) {
      try {
        const r = await fetch("/api/files");
        const d = await r.json();
        ALL_FILES = d.files || [];
        document.getElementById("kpiFiles").textContent = ALL_FILES.length;

        const box = document.getElementById("fileListBox");
        if (!ALL_FILES.length) {
          setHtmlIfChanged(box, `<div style="text-align:center;color:var(--text-muted);padding:14px;font-size:0.81rem">Kho file đang trống. Hãy tải file .txt lên ở trên.</div>`);
        } else {
          const html = ALL_FILES.map(f => `
            <div class="row-item">
              <div style="min-width:0;flex:1">
                <div style="display:flex;align-items:center;gap:6px">
                  <span class="tag-badge b-gold">Số ${f.display_num}</span>
                  <b style="font-size:0.85rem;color:#fff;word-break:break-all">${esc(f.filename)}</b>
                </div>
                <div style="font-size:0.73rem;color:var(--text-muted);margin-top:2px">
                  ${f.lines_count} dòng sạch • Gõ <code>.nhay ${f.display_num} @Tên</code> trên chat
                </div>
              </div>
              <div style="display:flex;gap:5px">
                <button type="button" class="btn btn-noel-ice btn-sm" onclick="useFileNow(${f.id})">Nạp</button>
                <button type="button" class="btn btn-noel-red btn-sm" onclick="deleteFile(${f.id})">✕</button>
              </div>
            </div>
          `).join("");
          setHtmlIfChanged(box, html);
        }

        const fSig = ALL_FILES.map(f => `${f.id}:${f.display_num}:${f.filename}`).join("|");
        if (force || fSig !== LAST_FILE_SELECT_SIG) {
          LAST_FILE_SELECT_SIG = fSig;
          const sel = document.getElementById("taskFileSelect");
          const prev = sel.value;
          sel.innerHTML = `<option value="">-- Hoặc nhập nội dung trực tiếp bên dưới --</option>` +
            ALL_FILES.map(f => `<option value="${f.display_num}">File số ${f.display_num}: ${esc(f.filename)} (${f.lines_count} dòng)</option>`).join("");
          if (prev) sel.value = prev;
        }
      } catch (e) {}
    }

    async function useFileNow(fid) {
      try {
        const r = await fetch(`/api/file_preview/${fid}`);
        const d = await r.json();
        if (d.ok) {
          document.getElementById("taskFileSelect").value = String(d.display_num);
          document.getElementById("taskRawText").value = d.preview_text || "";
          toast(`Đã nạp File số ${d.display_num}: ${d.filename}`);
        }
      } catch (e) {}
    }

    async function onFileSelectChange() {
      const dispNum = document.getElementById("taskFileSelect").value;
      if (!dispNum) return;
      const found = ALL_FILES.find(f => String(f.display_num) === String(dispNum));
      if (found) useFileNow(found.id);
    }

    async function deleteFile(fid) {
      await fetch(`/api/delete_file/${fid}`, {method: "POST"});
      toast("Đã xóa file");
      loadFiles(true);
    }

    // 3. QUẢN LÝ PHÂN QUYỀN
    async function loadAuthUsers() {
      try {
        const r = await fetch("/api/authorized_users");
        const d = await r.json();
        const users = d.users || [];
        const box = document.getElementById("authUserBox");
        if (!users.length) {
          setHtmlIfChanged(box, `<div style="text-align:center;color:var(--text-muted);padding:10px;font-size:0.79rem">Hiện chỉ mình chủ Acc dùng được lệnh.</div>`);
        } else {
          const html = users.map(u => `
            <div class="row-item" style="padding:7px 10px">
              <div style="font-size:0.81rem"><b>${esc(u.name)}</b> <span style="color:var(--text-muted)">(${esc(maskStr(u.uid))})</span></div>
              <button type="button" class="btn btn-noel-red btn-sm" onclick="delAuthUserWeb('${esc(u.uid)}')">Xóa</button>
            </div>
          `).join("");
          setHtmlIfChanged(box, html);
        }
      } catch (e) {}
    }

    async function addAuthUserWeb() {
      const uid = document.getElementById("authUidInput").value.trim();
      const name = document.getElementById("authNameInput").value.trim();
      if (!uid) return toast("Hãy nhập UID cần cấp quyền", true);
      await fetch("/api/authorized_users", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({uid, name})
      });
      document.getElementById("authUidInput").value = "";
      document.getElementById("authNameInput").value = "";
      toast("Đã cấp quyền sử dụng lệnh");
      loadAuthUsers();
    }

    async function delAuthUserWeb(uid) {
      await fetch("/api/authorized_users", {
        method: "DELETE",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({uid})
      });
      loadAuthUsers();
    }

    // 4. LẤY BOX ZALO / DISCORD & TỰ ĐỘNG NẠP THÀNH VIÊN ĐỂ TAG CHUẨN KHUNG CHAT
    function onAccountSelectChange() {
      const aid = document.getElementById("groupAccSelect").value;
      const acc = ALL_ACCOUNTS.find(a => String(a.id) === String(aid));
      if (!acc) return;
      if (acc.platform === "discord") {
        fetchDiscordAllBoxes();
      } else {
        fetchZaloGroups();
      }
    }

    async function fetchZaloGroups() {
      const aid = document.getElementById("groupAccSelect").value;
      if (!aid) return toast("Hãy chọn tài khoản trước", true);
      toast("⏳ Đang tải danh sách Nhóm Zalo...");
      try {
        const r = await fetch(`/api/account_groups/${aid}?type=group`);
        const d = await r.json();
        if (!d.ok) return toast(d.error || "Lỗi tải nhóm Zalo", true);
        LOADED_BOXES = d.groups || [];
        renderTargetBoxes();
        toast(`✅ Đã tải ${LOADED_BOXES.length} nhóm Zalo!`);
      } catch (e) {
        toast("Lỗi tải nhóm Zalo", true);
      }
    }

    async function fetchZaloFriends() {
      const aid = document.getElementById("groupAccSelect").value;
      if (!aid) return toast("Hãy chọn tài khoản trước", true);
      toast("⏳ Đang tải danh sách Bạn Bè Zalo...");
      try {
        const r = await fetch(`/api/account_groups/${aid}?type=friends`);
        const d = await r.json();
        if (!d.ok) return toast(d.error || "Lỗi tải bạn bè", true);
        LOADED_BOXES = d.groups || [];
        renderTargetBoxes();
        toast(`✅ Đã tải ${LOADED_BOXES.length} bạn bè Zalo!`);
      } catch (e) {
        toast("Lỗi tải bạn bè", true);
      }
    }

    async function fetchDiscordAllBoxes() {
      const aid = document.getElementById("groupAccSelect").value;
      if (!aid) return toast("Hãy chọn tài khoản Discord trước", true);
      toast("⏳ Đang quét toàn bộ Box Discord (DM + Box Nhóm + Server)...");
      try {
        const r = await fetch(`/api/account_groups/${aid}?type=discord_all`);
        const d = await r.json();
        if (!d.ok) return toast(d.error || "Lỗi tải Box Discord", true);
        LOADED_BOXES = d.groups || [];
        renderTargetBoxes();
        toast(`✅ Đã tải ${LOADED_BOXES.length} Box & Kênh Discord!`);
      } catch (e) {
        toast("Lỗi tải Box Discord", true);
      }
    }

    function updateSelectedBoxBadge() {
      const cnt = Object.keys(SELECTED_BOX_MAP).length;
      document.getElementById("selectedBoxBadge").textContent = `Đã chọn: ${cnt} box`;
    }

    function toggleBoxSelection(id, name, type, checked) {
      if (checked) {
        SELECTED_BOX_MAP[id] = {id: String(id), name: name, type: type};
        // Tự động tải luôn danh sách thành viên của nhóm Zalo / Box Discord vừa tích chọn để Tag chuẩn ngay!
        if (type === "group" || type === "discord_channel") {
          loadMembersForBoxId(String(id), name, true);
        }
      } else {
        delete SELECTED_BOX_MAP[id];
      }
      updateSelectedBoxBadge();
    }

    function renderTargetBoxes() {
      const q = (document.getElementById("boxSearchInput").value || "").toLowerCase().trim();
      const box = document.getElementById("targetBoxContainer");
      const filtered = LOADED_BOXES.filter(g => !q || g.name.toLowerCase().includes(q) || String(g.id).includes(q));

      if (!filtered.length) {
        box.innerHTML = `<div style="text-align:center;color:var(--text-muted);padding:14px;font-size:0.82rem">Không tìm thấy Box phù hợp.</div>`;
        return;
      }

      box.innerHTML = filtered.map(g => {
        const isChecked = !!SELECTED_BOX_MAP[g.id];
        const tBadge = g.type === "discord_channel"
          ? `<span class="tag-badge b-red">DISCORD</span>`
          : (g.type === "group" ? `<span class="tag-badge b-ice">NHÓM ZALO</span>` : `<span class="tag-badge b-green">BẠN BÈ</span>`);
        const memInfo = g.members ? ` • ${g.members} TV` : "";
        return `
          <label class="row-item" style="cursor:pointer;margin-bottom:6px">
            <div style="display:flex;align-items:center;gap:8px;min-width:0;flex:1">
              <input type="checkbox" ${isChecked ? "checked" : ""}
                     onchange='toggleBoxSelection(${JSON.stringify(String(g.id))}, ${JSON.stringify(g.name)}, ${JSON.stringify(g.type)}, this.checked)'>
              ${tBadge}
              <span style="font-weight:800;font-size:0.85rem;color:#fff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(g.name)}</span>
            </div>
            <span style="font-size:0.72rem;color:var(--text-muted)">ID: ***${esc(String(g.id).slice(-4))}${memInfo}</span>
          </label>
        `;
      }).join("");
      updateSelectedBoxBadge();
    }

    function selectTopBoxes(n) {
      SELECTED_BOX_MAP = {};
      LOADED_BOXES.slice(0, n).forEach(g => {
        SELECTED_BOX_MAP[g.id] = {id: String(g.id), name: g.name, type: g.type};
      });
      renderTargetBoxes();
      const firstBox = LOADED_BOXES[0];
      if (firstBox) loadMembersForBoxId(String(firstBox.id), firstBox.name, true);
      toast(`⚡ Đã chọn nhanh ${Object.keys(SELECTED_BOX_MAP).length} Box!`);
    }

    function toggleAllBoxes(selectAll) {
      if (!selectAll) {
        SELECTED_BOX_MAP = {};
      } else {
        LOADED_BOXES.forEach(g => {
          SELECTED_BOX_MAP[g.id] = {id: String(g.id), name: g.name, type: g.type};
        });
      }
      renderTargetBoxes();
    }

    function addManualBox() {
      const id = document.getElementById("manualBoxId").value.trim();
      const type = document.getElementById("manualBoxType").value;
      if (!id) return toast("Hãy nhập ID Box / Channel", true);
      const item = {id, name: `Box_${id.slice(-5)}`, type};
      LOADED_BOXES.unshift(item);
      SELECTED_BOX_MAP[id] = item;
      document.getElementById("manualBoxId").value = "";
      renderTargetBoxes();
      loadMembersForBoxId(id, item.name, true);
      toast(`Đã thêm & chọn Box ID: ***${id.slice(-4)}`);
    }

    async function loadMembersForBoxId(boxId, boxName, silent = false) {
      const aid = document.getElementById("groupAccSelect").value;
      if (!aid || !boxId) return;
      if (!silent) toast(`⏳ Đang quét thành viên trong khung chat ${boxName}...`);
      try {
        const r = await fetch(`/api/group_members/${aid}/${boxId}`);
        const d = await r.json();
        if (!d.ok) {
          if (!silent) toast(d.error || "Không lấy được thành viên", true);
          return;
        }
        LOADED_MEMBERS = d.members || [];
        renderMemberTags();
        if (!silent) toast(`✅ Đã nạp ${LOADED_MEMBERS.length} thành viên để Tag chuẩn khung chat!`);
      } catch (e) {
        if (!silent) toast("Lỗi tải thành viên", true);
      }
    }

    async function loadMembersOfSelectedBox() {
      const selectedList = Object.values(SELECTED_BOX_MAP);
      if (!selectedList.length) {
        return toast("Hãy tích chọn ít nhất 1 Nhóm Zalo hoặc Box Discord trước!", true);
      }
      const targetBox = selectedList[0];
      await loadMembersForBoxId(targetBox.id, targetBox.name, false);
    }

    function toggleMemberTag(uid, name, checked) {
      if (checked) {
        SELECTED_MEMBER_MAP[uid] = {uid: String(uid), id: String(uid), name: name};
      } else {
        delete SELECTED_MEMBER_MAP[uid];
      }
    }

    function renderMemberTags() {
      const q = (document.getElementById("memberSearchInput").value || "").toLowerCase().trim();
      const box = document.getElementById("memberTagContainer");
      const filtered = LOADED_MEMBERS.filter(m => !q || m.name.toLowerCase().includes(q) || String(m.id).includes(q));

      if (!filtered.length) {
        box.innerHTML = `<div style="text-align:center;color:var(--text-muted);padding:10px;font-size:0.79rem">Không tìm thấy thành viên.</div>`;
        return;
      }

      box.innerHTML = filtered.map(m => {
        const isChecked = !!SELECTED_MEMBER_MAP[m.id];
        return `
          <label class="row-item" style="cursor:pointer;padding:7px 10px;margin-bottom:5px">
            <div style="display:flex;align-items:center;gap:8px">
              <input type="checkbox" ${isChecked ? "checked" : ""}
                     onchange='toggleMemberTag(${JSON.stringify(String(m.id))}, ${JSON.stringify(m.name)}, this.checked)'>
              <span style="font-size:0.84rem;font-weight:800;color:#7dd3fc">@${esc(m.name)}</span>
            </div>
            <span style="font-size:0.72rem;color:var(--text-muted)">UID: ***${esc(String(m.id).slice(-4))}</span>
          </label>
        `;
      }).join("");
    }

    function toggleAllMembers(selectAll) {
      if (!selectAll) {
        SELECTED_MEMBER_MAP = {};
      } else {
        LOADED_MEMBERS.forEach(m => {
          SELECTED_MEMBER_MAP[m.id] = {uid: String(m.id), id: String(m.id), name: m.name};
        });
      }
      renderMemberTags();
    }

    // 5. KHỞI CHẠY CHIẾN DỊCH & CẬP NHẬT NÓNG
    async function startCampaign() {
      const targets = Object.values(SELECTED_BOX_MAP);
      if (!targets.length) return toast("Hãy tích chọn ít nhất 1 Box Chat ở Mục 4!", true);

      const mode = document.getElementById("taskMode").value;
      const file_query = document.getElementById("taskFileSelect").value;
      const raw_text = document.getElementById("taskRawText").value;
      const color_mode = document.getElementById("colorMode").value;
      const fixed_color = document.getElementById("fixedColorVal").value;
      const delay = parseFloat(document.getElementById("taskDelay").value || "1.0");
      const icon_count = parseInt(document.getElementById("iconCount").value || "3", 10);
      const strip_line_num = document.getElementById("chkStripNum").checked;
      const is_heading = document.getElementById("chkBigText").checked;
      const use_emoji = document.getElementById("chkUseEmoji").checked && (icon_count > 0);
      const antiband = document.getElementById("chkAntiband").checked;
      const multi_acc = document.getElementById("chkMultiAcc").checked;
      const tag_all = document.getElementById("tagAllCheck").checked;
      const tag_users = Object.values(SELECTED_MEMBER_MAP);
      const specific_acc_id = multi_acc ? null : parseInt(document.getElementById("groupAccSelect").value || "0", 10);

      try {
        const r = await fetch("/api/start_task", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            targets, mode, file_query, raw_text, color_mode, fixed_color,
            delay, icon_count, strip_line_num, is_heading, use_emoji,
            antiband, multi_acc, tag_all, tag_users, specific_acc_id
          })
        });
        const d = await r.json();
        if (!d.ok) return toast(d.error || "Không thể khởi chạy", true);
        toast(`🎄 Đã khởi chạy chiến dịch trên ${targets.length} Box!`);
        loadTasks();
      } catch (e) {
        toast("Lỗi khởi chạy tiến trình", true);
      }
    }

    async function applyLiveConfig() {
      const delay = parseFloat(document.getElementById("taskDelay").value || "1.0");
      const color_mode = document.getElementById("colorMode").value;
      const fixed_color = document.getElementById("fixedColorVal").value;
      const icon_count = parseInt(document.getElementById("iconCount").value || "3", 10);
      const use_emoji = document.getElementById("chkUseEmoji").checked && (icon_count > 0);
      const is_heading = document.getElementById("chkBigText").checked;
      const antiband = document.getElementById("chkAntiband").checked;

      const r = await fetch("/api/update_live_config", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({delay, color_mode, fixed_color, icon_count, use_emoji, is_heading, antiband})
      });
      const d = await r.json();
      if (d.ok) toast(`⚡ Đã cập nhật nóng cho ${d.updated} chiến dịch đang chạy!`);
    }

    // 6. GIÁM SÁT TIẾN TRÌNH & LOG ĐÃ MÃ HÓA ẨN ACC
    async function loadTasks() {
      try {
        const r = await fetch("/api/tasks");
        const d = await r.json();
        const tasks = d.tasks || [];
        const runningCnt = tasks.filter(t => t.status === "running").length;
        let totalSent = 0;
        tasks.forEach(t => { totalSent += (t.stats && t.stats.sent) ? t.stats.sent : 0; });

        document.getElementById("kpiTasks").textContent = runningCnt;
        document.getElementById("kpiSent").textContent = totalSent;

        const box = document.getElementById("activeTasksBox");
        if (!tasks.length) {
          setHtmlIfChanged(box, `<div style="text-align:center;color:var(--text-muted);padding:14px;font-size:0.81rem">Chưa có chiến dịch nào.</div>`);
          return;
        }

        const html = tasks.map(t => {
          const isRun = t.status === "running";
          const stBadge = isRun
            ? `<span class="tag-badge b-green">🟢 ĐANG CHẠY</span>`
            : `<span class="tag-badge b-red">⏹ ĐÃ DỪNG</span>`;
          const meta = t.meta || {};
          const sent = (t.stats && t.stats.sent) ? t.stats.sent : 0;
          const names = (meta.target_names || []).join(", ") || "Box Chat";
          return `
            <div class="row-item">
              <div style="min-width:0;flex:1">
                <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
                  ${stBadge}
                  <b style="font-size:0.85rem;color:#fff">[${esc(t.type)}] ${esc(names)}</b>
                  <span class="tag-badge b-gold">Đã gửi: ${sent} tin</span>
                </div>
                <div style="font-size:0.73rem;color:var(--text-muted);margin-top:2px">
                  Nguồn: <b>${meta.source === "chat" ? "Lệnh Chat" : "Web UI"}</b> • Delay: ${meta.delay || 1}s • Anti-Ban: <b>Active</b>
                </div>
              </div>
              ${isRun ? `<button type="button" class="btn btn-noel-red btn-sm" onclick="stopTask('${esc(t.id)}')">Dừng</button>` : ""}
            </div>
          `;
        }).join("");
        setHtmlIfChanged(box, html);
      } catch (e) {}
    }

    async function stopTask(tid) {
      await fetch(`/api/stop_task/${tid}`, {method: "POST"});
      toast("Đã dừng tiến trình");
      loadTasks();
    }

    async function stopAllTasks() {
      await fetch("/api/stop_all", {method: "POST"});
      toast("⏹ Đã dừng tất cả chiến dịch!");
      loadTasks();
    }

    async function clearStoppedTasks() {
      await fetch("/api/clear_tasks", {method: "POST"});
      loadTasks();
    }

    async function loadBotLogs() {
      if (!SHOW_BOT_LOG_PANEL) return;
      try {
        const r = await fetch("/api/bot_logs");
        const d = await r.json();
        const logs = d.logs || [];
        const box = document.getElementById("botLogsBox");
        if (!logs.length) {
          setHtmlIfChanged(box, `<div style="text-align:center;color:var(--text-muted);padding:10px;font-size:0.78rem">Chưa có lịch sử lệnh.</div>`);
          return;
        }
        const html = logs.map(l => `
          <div class="row-item" style="padding:7px 10px;margin-bottom:5px">
            <div style="min-width:0;flex:1">
              <div style="font-size:0.8rem;color:#fde68a;font-weight:800">${esc(l.cmd_text)}</div>
              <div style="font-size:0.73rem;color:#cbd5e1">${esc(l.action_taken)} • Box: ${esc(l.thread_id)}</div>
            </div>
            <span style="font-size:0.7rem;color:var(--text-muted)">${esc(l.time_str)}</span>
          </div>
        `).join("");
        setHtmlIfChanged(box, html);
      } catch (e) {}
    }

    async function clearBotLogs() {
      await fetch("/api/clear_bot_logs", {method: "POST"});
      loadBotLogs();
    }

    window.addEventListener("DOMContentLoaded", () => {
      loadAccounts(true);
      loadFiles(true);
      loadAuthUsers();
      loadTasks();

      setInterval(() => {
        loadTasks();
        loadBotLogs();
      }, 2500);

      setInterval(() => {
        loadAccounts(false);
      }, 6000);
    });
  </script>
</body>
</html>
"""

HTML_INDEX = HTML_INDEX_PART1 + HTML_INDEX_PART2


# ============================================================
# ROUTES XÁC THỰC, LOGO UPLOAD, DISCORD REG TOKEN & API ĐIỀU KHIỂN
# ============================================================
def get_brand_logo_html():
    custom_logo = get_setting("brand_logo", "")
    if custom_logo and os.path.exists(os.path.join(LOGO_DIR, custom_logo)):
        return f'<img src="/api/brand_logo/{custom_logo}" alt="Logo">'
    return SVG_NOEL_TREE


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("gate_passed"):
            return redirect("/gate")
        if not session.get("user"):
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


def parse_cookie_input_flexible(raw_cookie_str):
    raw = (raw_cookie_str or "").strip()
    if not raw:
        raise Exception("Cookie không được để trống")
    if raw.startswith("{") and raw.endswith("}"):
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            if "cookies" in parsed and isinstance(parsed["cookies"], list):
                return {c["name"]: c["value"] for c in parsed["cookies"] if "name" in c and "value" in c}
            return {str(k): str(v) for k, v in parsed.items()}
    if raw.startswith("[") and raw.endswith("]"):
        arr = json.loads(raw)
        return {c["name"]: c["value"] for c in arr if isinstance(c, dict) and "name" in c and "value" in c}
    out = {}
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    if not out:
        raise Exception("Định dạng Cookie không hợp lệ")
    return out


@app.route("/gate", methods=["GET", "POST"])
def route_gate():
    ip = get_client_ip()
    ok_ip, wait_s = check_ip_bruteforce(ip)
    logo_html = get_brand_logo_html()
    if not ok_ip:
        err_html = f'<div style="color:#fda4af;margin-bottom:10px;font-size:0.83rem;font-weight:700">Tạm khóa {wait_s}s do nhập sai nhiều lần.</div>'
        return HTML_GATE.replace("__ERR_BLOCK__", err_html).replace("__BRAND_LOGO_HTML__", logo_html)

    if request.method == "POST":
        k = (request.form.get("key") or "").strip()
        if hmac.compare_digest(k, ACCESS_KEY):
            record_login_result(ip, True)
            session["gate_passed"] = True
            return redirect("/login")
        record_login_result(ip, False)
        err_html = '<div style="color:#fda4af;margin-bottom:10px;font-size:0.83rem;font-weight:700">Mã khóa truy cập không chính xác!</div>'
        return HTML_GATE.replace("__ERR_BLOCK__", err_html).replace("__BRAND_LOGO_HTML__", logo_html)

    return HTML_GATE.replace("__ERR_BLOCK__", "").replace("__BRAND_LOGO_HTML__", logo_html)


@app.route("/login", methods=["GET", "POST"])
def route_login():
    if not session.get("gate_passed"):
        return redirect("/gate")

    logo_html = get_brand_logo_html()
    if request.method == "POST":
        u = (request.form.get("username") or "admin").strip()
        p = (request.form.get("password") or "").strip()
        # Cho phép đăng nhập bằng tài khoản quản trị trong DB hoặc mật khẩu hệ thống
        conn = db()
        row = conn.execute("SELECT * FROM users WHERE username = ?", (u,)).fetchone()
        conn.close()
        if (row and verify_password_secure(row["password"], p)) or hmac.compare_digest(p, ACCESS_KEY):
            session["user"] = u or "admin"
            return redirect("/")
        msg = '<div style="color:#fda4af;margin-bottom:10px;font-size:0.83rem;font-weight:700">Mật khẩu quản trị không chính xác!</div>'
        return HTML_LOGIN.replace("__MSG_BLOCK__", msg).replace("__BRAND_LOGO_HTML__", logo_html)

    return HTML_LOGIN.replace("__MSG_BLOCK__", "").replace("__BRAND_LOGO_HTML__", logo_html)


@app.route("/logout")
def route_logout():
    session.clear()
    return redirect("/gate")


@app.route("/")
@login_required
def route_index():
    logo_html = get_brand_logo_html()
    return HTML_INDEX.replace("__USER__", session.get("user", "Admin")).replace("__BRAND_LOGO_HTML__", logo_html)


@app.route("/api/upload_logo", methods=["POST"])
@login_required
def api_upload_logo():
    f = request.files.get("logo")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "Chưa chọn ảnh Logo"})
    ext = os.path.splitext(secure_filename(f.filename))[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
        return jsonify({"ok": False, "error": "Chỉ hỗ trợ ảnh .png, .jpg, .webp, .gif, .svg"})

    fname = f"noel_logo_{int(time.time())}{ext}"
    save_path = os.path.join(LOGO_DIR, fname)
    f.save(save_path)
    set_setting("brand_logo", fname)
    return jsonify({"ok": True, "logo_url": f"/api/brand_logo/{fname}"})


@app.route("/api/brand_logo/<path:filename>")
def api_get_brand_logo(filename):
    return send_from_directory(LOGO_DIR, filename)


@app.route("/api/discord_reg_token", methods=["POST"])
@login_required
def api_discord_reg_token():
    data = request.get_json(force=True) or {}
    mode = data.get("mode", "extract")
    if mode == "extract":
        raw_dump = data.get("raw_dump") or ""
        tokens = extract_discord_tokens_from_reg_or_raw(raw_dump)
        if not tokens:
            return jsonify({"ok": False, "error": "Không tìm thấy chuỗi Token Discord hợp lệ trong văn bản đã dán"})
        for tk in tokens:
            dc = DiscordBot(tk, is_bot=False)
            if dc.check():
                return jsonify({
                    "ok": True,
                    "token": dc.token,
                    "username": dc.display_name or dc.username,
                    "uid": dc.user_id,
                    "is_bot": dc.is_bot
                })
        # Trả về token đầu tiên nếu offline check chưa qua
        return jsonify({"ok": True, "token": tokens[0], "username": ""})
    else:
        email = (data.get("email") or "").strip()
        password = data.get("password") or ""
        two_fa = (data.get("two_fa") or "").strip()
        if not email or not password:
            return jsonify({"ok": False, "error": "Vui lòng nhập đầy đủ Email và Mật khẩu"})
        res = login_discord_reg_session(email, password, two_fa)
        return jsonify(res)


@app.route("/api/accounts", methods=["GET", "POST"])
@login_required
def api_accounts():
    if request.method == "GET":
        conn = db()
        rows = conn.execute("SELECT * FROM accounts ORDER BY id DESC").fetchall()
        conn.close()
        out = []
        for r in rows:
            d = dict(r)
            # Ẩn tuyệt đối toàn bộ thông tin nhạy cảm (Cookie, Token, IMEI, UID đầy đủ) khỏi API trả về
            d.pop("cookies", None)
            d.pop("token", None)
            d.pop("imei", None)
            d["uid"] = mask_sensitive_id(d.get("uid", ""), 3)
            listener = ACTIVE_LISTENERS.get(d["id"])
            d["ws_status"] = listener.ws_status if listener else ("🟢 Đang bảo vệ" if d.get("chat_cmd_enabled") else "⚪ Tắt")
            d["health"] = HEALTH_MGR.get_snapshot(d["id"])
            out.append(d)
        return jsonify({"ok": True, "accounts": out})

    data = request.get_json(force=True) or {}
    platform = (data.get("platform") or "zalo").strip().lower()
    name = (data.get("name") or "").strip()
    chat_cmd_enabled = 1 if data.get("chat_cmd_enabled", 1) else 0
    allow_all_cmd = 1 if data.get("allow_all_cmd", 0) else 0

    if platform == "zalo":
        imei = (data.get("imei") or "").strip()
        raw_cookies = data.get("cookies") or ""
        if not imei or not raw_cookies:
            return jsonify({"ok": False, "error": "Vui lòng nhập đầy đủ IMEI và Cookie Zalo"})
        try:
            c_dict = parse_cookie_input_flexible(raw_cookies)
            z = Zalo(imei, c_dict)
            real_name = name or z.display_name or z.zalo_name or f"Zalo_{z.uid[-4:]}"
            uid_combined = ",".join(filter(None, {str(z.uid or ""), str(z.send2me_id or "")}))
            conn = db()
            conn.execute(
                """INSERT INTO accounts (name, imei, cookies, platform, uid, chat_cmd_enabled, allow_all_cmd, enabled, created_at)
                   VALUES (?, ?, ?, 'zalo', ?, ?, ?, 1, ?)""",
                (real_name, imei, json.dumps(c_dict, ensure_ascii=False), uid_combined, chat_cmd_enabled, allow_all_cmd, time.time())
            )
            conn.commit()
            conn.close()
            sync_all_zalo_listeners()
            return jsonify({"ok": True, "name": real_name})
        except Exception as e:
            return jsonify({"ok": False, "error": f"Lỗi xác thực Zalo: {e}"})
    else:
        raw_token_input = (data.get("token") or "").strip()
        is_bot = int(data.get("is_bot", 0))
        if not raw_token_input:
            return jsonify({"ok": False, "error": "Vui lòng nhập Token Discord hoặc dùng công cụ Reg Token"})
        try:
            dc = DiscordBot(raw_token_input, is_bot=bool(is_bot))
            if not dc.check():
                return jsonify({"ok": False, "error": "Token Discord không hợp lệ hoặc đã hết hạn"})
            actual_is_bot = 1 if dc.is_bot else 0
            real_name = name or dc.display_name or dc.username or f"Discord_{dc.user_id[-4:]}"
            conn = db()
            conn.execute(
                """INSERT INTO accounts (name, platform, token, is_bot, uid, chat_cmd_enabled, allow_all_cmd, enabled, created_at)
                   VALUES (?, 'discord', ?, ?, ?, ?, ?, 1, ?)""",
                (real_name, dc.token, actual_is_bot, str(dc.user_id or ""), chat_cmd_enabled, allow_all_cmd, time.time())
            )
            conn.commit()
            conn.close()
            sync_all_zalo_listeners()
            return jsonify({"ok": True, "name": real_name, "is_bot": actual_is_bot})
        except Exception as e:
            return jsonify({"ok": False, "error": f"Lỗi kết nối Discord: {e}"})


@app.route("/api/delete_account/<int:aid>", methods=["POST"])
@login_required
def api_delete_account(aid):
    conn = db()
    conn.execute("DELETE FROM accounts WHERE id = ?", (aid,))
    conn.commit()
    conn.close()
    sync_all_zalo_listeners()
    return jsonify({"ok": True})


@app.route("/api/toggle_account_cmd/<int:aid>", methods=["POST"])
@login_required
def api_toggle_account_cmd(aid):
    conn = db()
    row = conn.execute("SELECT chat_cmd_enabled FROM accounts WHERE id = ?", (aid,)).fetchone()
    if row:
        new_v = 0 if row["chat_cmd_enabled"] else 1
        conn.execute("UPDATE accounts SET chat_cmd_enabled = ? WHERE id = ?", (new_v, aid))
        conn.commit()
    conn.close()
    sync_all_zalo_listeners()
    return jsonify({"ok": True})


@app.route("/api/toggle_allow_all/<int:aid>", methods=["POST"])
@login_required
def api_toggle_allow_all(aid):
    conn = db()
    row = conn.execute("SELECT allow_all_cmd FROM accounts WHERE id = ?", (aid,)).fetchone()
    new_v = 0
    if row:
        new_v = 0 if row["allow_all_cmd"] else 1
        conn.execute("UPDATE accounts SET allow_all_cmd = ? WHERE id = ?", (new_v, aid))
        conn.commit()
    conn.close()
    return jsonify({"ok": True, "allow_all": bool(new_v)})


@app.route("/api/authorized_users", methods=["GET", "POST", "DELETE"])
@login_required
def api_authorized_users():
    if request.method == "GET":
        return jsonify({"ok": True, "users": list_authorized_users()})
    data = request.get_json(force=True) or {}
    uid = (data.get("uid") or "").strip()
    if request.method == "POST":
        name = (data.get("name") or "").strip()
        add_authorized_user(uid, name)
        return jsonify({"ok": True})
    if request.method == "DELETE":
        remove_authorized_user(uid)
        return jsonify({"ok": True})


@app.route("/api/account_groups/<int:aid>")
@login_required
def api_account_groups(aid):
    qtype = request.args.get("type", "group")
    guild_id = request.args.get("guild_id", "")
    conn = db()
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    conn.close()
    if not acc:
        return jsonify({"ok": False, "error": "Không tìm thấy tài khoản"})

    plat = (acc["platform"] or "zalo").lower()
    try:
        if plat == "zalo":
            z = Zalo(acc["imei"], json.loads(acc["cookies"]))
            if qtype == "friends":
                return jsonify({"ok": True, "groups": z.friends()})
            return jsonify({"ok": True, "groups": z.groups()})
        else:
            dc = DiscordBot(acc["token"], is_bot=bool(acc["is_bot"]))
            if not dc.check():
                return jsonify({"ok": False, "error": "Token Discord hết hạn hoặc không hợp lệ"})
            if guild_id:
                return jsonify({"ok": True, "groups": dc.get_channels(guild_id)})
            if qtype == "discord_dm":
                return jsonify({"ok": True, "groups": dc.get_dm_and_group_boxes()})
            if qtype == "discord_guilds":
                return jsonify({"ok": True, "groups": dc.get_guilds()})
            return jsonify({"ok": True, "groups": dc.get_all_boxes()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/group_members/<int:aid>/<gid>")
@login_required
def api_group_members(aid, gid):
    conn = db()
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    conn.close()
    if not acc:
        return jsonify({"ok": False, "error": "Không tìm thấy tài khoản"})

    plat = (acc["platform"] or "zalo").lower()
    try:
        if plat == "zalo":
            z = Zalo(acc["imei"], json.loads(acc["cookies"]))
            mems = z.get_members_full(gid, use_cache=False)
            return jsonify({"ok": True, "members": mems})
        else:
            dc = DiscordBot(acc["token"], is_bot=bool(acc["is_bot"]))
            dc.check()
            mems = dc.get_box_members(gid)
            return jsonify({"ok": True, "members": mems})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/files")
@login_required
def api_files():
    return jsonify({"ok": True, "files": get_ordered_files_with_display_num()})


@app.route("/api/upload_file", methods=["POST"])
@login_required
def api_upload_file():
    files = request.files.getlist("file")
    if not files:
        return jsonify({"ok": False, "error": "Chưa chọn file tải lên"})

    uploaded = []
    conn = db()
    for f in files:
        if not f or not f.filename:
            continue
        orig_name = secure_filename(f.filename) or f"file_{int(time.time())}.txt"
        save_name = f"{int(time.time() * 1000)}_{orig_name}"
        fpath = os.path.join(UPLOAD_DIR, save_name)

        raw_bytes = f.read()
        raw_text = raw_bytes.decode("utf-8", errors="ignore").replace("\r\n", "\n").replace("\r", "\n")
        cleaned_lines = []
        for ln in raw_text.split("\n"):
            if ln.strip():
                cleaned_lines.append(strip_leading_line_number(ln.strip()))
            else:
                cleaned_lines.append("")
        clean_content = "\n".join(cleaned_lines)

        with open(fpath, "wb") as out_f:
            out_f.write(clean_content.encode("utf-8"))

        parsed = parse_file_stream_fast(fpath, strip_numbers=True)
        cur = conn.execute(
            "INSERT INTO files (filename, filepath, lines_count, created_at) VALUES (?, ?, ?, ?)",
            (orig_name, fpath, parsed["line_count"], time.time())
        )
        uploaded.append({"id": cur.lastrowid, "filename": orig_name, "lines_count": parsed["line_count"]})

    conn.commit()
    conn.close()
    return jsonify({"ok": True, "uploaded": uploaded})


@app.route("/api/file_preview/<int:fid>")
@login_required
def api_file_preview(fid):
    files = get_ordered_files_with_display_num()
    rec = next((f for f in files if f["id"] == fid), None)
    if not rec:
        return jsonify({"ok": False, "error": "Không tìm thấy file"})
    parsed = parse_file_stream_fast(rec["filepath"], strip_numbers=True)
    preview_lines = parsed["lines"][:150]
    return jsonify({
        "ok": True,
        "id": rec["id"],
        "display_num": rec["display_num"],
        "filename": rec["filename"],
        "line_count": parsed["line_count"],
        "preview_text": "\n".join(preview_lines)
    })


@app.route("/api/delete_file/<int:fid>", methods=["POST"])
@login_required
def api_delete_file(fid):
    conn = db()
    row = conn.execute("SELECT filepath FROM files WHERE id = ?", (fid,)).fetchone()
    if row and row["filepath"] and os.path.exists(row["filepath"]):
        try:
            os.remove(row["filepath"])
        except Exception:
            pass
    conn.execute("DELETE FROM files WHERE id = ?", (fid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/start_task", methods=["POST"])
@login_required
def api_start_task():
    data = request.get_json(force=True) or {}
    targets = data.get("targets") or []
    if not targets:
        return jsonify({"ok": False, "error": "Vui lòng chọn ít nhất 1 Box Chat"})

    mode = data.get("mode", "treo_nhay")
    file_query = (data.get("file_query") or "").strip()
    raw_text = (data.get("raw_text") or "").strip()
    strip_num = bool(data.get("strip_line_num", True)) or (mode == "treo_nhay")

    blocks = []
    if file_query:
        blocks = get_blocks_from_file_query(file_query, mode=mode)

    if not blocks and raw_text:
        if mode == "treo_nhay":
            blocks = [strip_leading_line_number(ln) for ln in raw_text.split("\n") if ln.strip()]
        elif mode == "treo_ngon":
            blocks = [raw_text]
        else:
            lines_f = [strip_leading_line_number(ln) if strip_num else ln.strip() for ln in raw_text.split("\n") if ln.strip()]
            blocks = lines_f if lines_f else [raw_text]

    if not blocks:
        blocks = get_blocks_from_file_query("latest", mode=mode)

    if not blocks:
        return jsonify({"ok": False, "error": "Vui lòng chọn File hoặc nhập nội dung tin nhắn"})

    delay = max(0.2, float(data.get("delay", 1.0)))
    icon_count = max(0, int(data.get("icon_count", 3)))
    use_emoji = bool(data.get("use_emoji", True)) and (icon_count > 0)
    is_heading = bool(data.get("is_heading", True))
    color_mode = data.get("color_mode", "rainbow")
    fixed_color = data.get("fixed_color", "red")
    antiband = bool(data.get("antiband", True))
    multi_acc = bool(data.get("multi_acc", True))
    tag_all = bool(data.get("tag_all", False))
    tag_users = data.get("tag_users") or []
    specific_acc_id = data.get("specific_acc_id")

    tid = start_task_programmatic(
        targets=targets,
        blocks=blocks,
        delay=delay,
        use_emoji=use_emoji,
        icon_count=icon_count,
        tag_users=tag_users,
        tag_all=tag_all,
        is_heading=is_heading,
        multi_acc=multi_acc,
        mode=mode,
        color_mode=color_mode,
        fixed_color=fixed_color,
        antiband=antiband,
        antidieall=True,
        specific_acc_id=specific_acc_id,
        source_label="web"
    )
    return jsonify({"ok": True, "task_id": tid})


@app.route("/api/update_live_config", methods=["POST"])
@login_required
def api_update_live_config():
    data = request.get_json(force=True) or {}
    kwargs = {}
    if "delay" in data:
        kwargs["delay"] = max(0.2, float(data["delay"]))
    if "color_mode" in data:
        kwargs["color_mode"] = data["color_mode"]
    if "fixed_color" in data:
        kwargs["fixed_color"] = data["fixed_color"]
    if "icon_count" in data:
        kwargs["icon_count"] = max(0, int(data["icon_count"]))
    if "use_emoji" in data:
        kwargs["use_emoji"] = bool(data["use_emoji"])
    if "is_heading" in data:
        kwargs["is_heading"] = bool(data["is_heading"])
    if "antiband" in data:
        kwargs["antiband"] = bool(data["antiband"])

    cnt = update_running_tasks_config(thread_id=None, **kwargs)
    return jsonify({"ok": True, "updated": cnt})


@app.route("/api/tasks")
@login_required
def api_tasks():
    conn = db()
    rows = conn.execute("SELECT * FROM tasks ORDER BY started_at DESC LIMIT 35").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["meta"] = json.loads(d["meta"] or "{}")
        except Exception:
            d["meta"] = {}
        try:
            d["stats"] = json.loads(d["stats"] or "{}")
        except Exception:
            d["stats"] = {}
        if d["status"] == "running" and d["id"] not in ACTIVE_TASKS:
            d["status"] = "stopped"
        out.append(d)
    return jsonify({"ok": True, "tasks": out})


@app.route("/api/stop_task/<tid>", methods=["POST"])
@login_required
def api_stop_task(tid):
    info = ACTIVE_TASKS.get(tid)
    if info:
        info["stop"].set()
    conn = db()
    conn.execute("UPDATE tasks SET status = 'stopped' WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/stop_all", methods=["POST"])
@login_required
def api_stop_all():
    stop_tasks_for_thread(None)
    conn = db()
    conn.execute("UPDATE tasks SET status = 'stopped' WHERE status = 'running'")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/clear_tasks", methods=["POST"])
@login_required
def api_clear_tasks():
    conn = db()
    conn.execute("DELETE FROM tasks WHERE status != 'running'")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/bot_logs")
@login_required
def api_bot_logs():
    conn = db()
    rows = conn.execute("SELECT * FROM bot_logs ORDER BY id DESC LIMIT 40").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["time_str"] = time.strftime("%H:%M:%S", time.localtime(d.get("created_at") or time.time()))
        out.append(d)
    return jsonify({"ok": True, "logs": out})


@app.route("/api/clear_bot_logs", methods=["POST"])
@login_required
def api_clear_bot_logs():
    conn = db()
    conn.execute("DELETE FROM bot_logs")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
