import os
import re
import ssl
import zlib
import json
import time
import uuid
import hmac
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
# CẤU HÌNH HỆ THỐNG & BẢO MẬT WEB — ALB FORGE v7.0 ULTRA
# Tác giả: Phạm Anh Khôi (Anhba)
# ============================================================
APP_TITLE = "ALB FORGE v7.0 ULTRA — ZALO & DISCORD AUTOMATION"
SECRET_KEY = os.environ.get("SECRET_KEY", "alb-forge-v7-ultra-secret-key-2026-secure")
ACCESS_KEY = os.environ.get("WEB_KEY", "anhba")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

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
API_RATE_BUCKETS = defaultdict(lambda: deque(maxlen=240))
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


def record_login_Result(ip, success):
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
            if len(dq) >= 220:
                return jsonify({"ok": False, "error": "Thao tác quá nhanh, vui lòng thử lại sau vài giây"}), 429
            dq.append(now)


@app.after_request
def add_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp


def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(24)
    return session["csrf_token"]


# ============================================================
# KHỞI TẠO & ĐỒNG BỘ CƠ SỞ DỮ LIỆU SQLITE WAL TỐC ĐỘ CAO
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
        _ACTIVE_DB_PATH = os.path.join(tempfile.gettempdir(), "alb_forge_v7_database.db")
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
        _ACTIVE_DB_PATH = os.path.join(tempfile.gettempdir(), "alb_forge_v7_database.db")
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

    conn.commit()
    conn.close()


init_db()

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
}
BOT_CFG_LOCK = threading.Lock()

# Bộ nhớ đệm ghi nhận mọi tin nhắn do chính Bot vừa gửi ra (tránh tuyệt đối lỗi gõ .menu bị Bot đọc lại rồi tự chạy .spam)
BOT_SENT_IDS = deque(maxlen=1200)
BOT_SENT_TEXT_HASHES = deque(maxlen=1200)
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
    """Kiểm tra xem gói tin WebSocket/Polling nhận về có phải là tin nhắn do chính Bot vừa phát ra hay không."""
    now = time.time()
    with BOT_SENT_LOCK:
        for mid, ts in list(BOT_SENT_IDS):
            if now - ts <= 90.0:
                if (msg_id and str(msg_id) == mid) or (client_id and str(client_id) == mid):
                    return True
        if text:
            nh = _normalize_for_echo_hash(text)
            first_line = _normalize_for_echo_hash(text.split("\n")[0])
            for h_saved, ts in list(BOT_SENT_TEXT_HASHES):
                if now - ts <= 60.0 and h_saved and (nh == h_saved or first_line == h_saved):
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

# Regex nhận diện chính xác số thứ tự ở đầu dòng: "1. ", "2. ", "10) ", "1: ", "1 - ", "(1) ", "Câu 1:"
LEADING_NUMBER_RE = re.compile(
    r"^\s*(?:câu\s*\d+[\.\:\)\-]+|\(\d+\)|#?\d+[\.\)\:\-]+)\s*",
    re.IGNORECASE
)


def strip_leading_line_number(line):
    """Tự động xoá số thứ tự ở đầu dòng (ví dụ: '1. Dit me may...' -> 'Dit me may...',
    '2. Cai mat may...' -> 'Cai mat may...') để khi chạy chế độ Nhây chỉ lấy đúng phần nội dung."""
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
    # Luôn tự động xoá số thứ tự đầu dòng (1., 2., 3.) khi chạy chế độ nhây hoặc đọc dòng từ file
    parsed = parse_file_stream_fast(rec["filepath"], strip_numbers=True)
    if mode == "treo_nhay":
        return parsed["lines"] if parsed["lines"] else parsed["blocks"]
    return parsed["blocks"]


# ============================================================
# HỆ THỐNG ANTI-BAN ZERO-SHIFT v7.0 & ANTI-DIE-ALL CIRCUIT BREAKER
# ============================================================
ZERO_WIDTH_SAFE = ["\u200b", "\u200c"]
_ANTIBAN_COUNTER = 0
_ANTIBAN_LOCK = threading.Lock()


def _next_invisible_signature():
    """Tạo chuỗi vi chữ ký tàng hình ở CUỐI CÙNG của tin nhắn (sau khi đã tính xong toạ độ Màu Chữ & @Tag).
    Nhờ đặt ở cuối cùng, mã băm (hash) của mỗi tin nhắn luôn khác nhau 100% để chống Anti-Spam,
    mà KHÔNG BAO GIỜ làm lệch vị trí UTF-16 của RichText Styles hay @Tag thật!"""
    global _ANTIBAN_COUNTER
    with _ANTIBAN_LOCK:
        _ANTIBAN_COUNTER = (_ANTIBAN_COUNTER + 1) & 0xFFFFF
        seq = _ANTIBAN_COUNTER
    salt = ((int(time.time() * 1000) & 0xFFF) ^ (seq << 3) ^ random.randint(1, 0xFFFF)) & 0xFFFF
    bits = bin(salt)[2:].zfill(16)
    return "".join(ZERO_WIDTH_SAFE[int(b)] for b in bits[:8])


def apply_antiband_on_clean_text(text, level=3):
    """Giữ nguyên 100% độ dài UTF-16 của phần chữ chính để toạ độ Màu Chữ (textProperties)
    và toạ độ @Tag Thật (mentionInfo) khớp chính xác tuyệt đối trên Zalo iOS/Android/Web."""
    if not text:
        return ""
    return text


def append_antiband_tail(final_msg):
    """Gắn chữ ký tàng hình Anti-Ban vào vị trí cuối cùng của tin nhắn (cách 1 khoảng trắng sau Icon/Tag)."""
    if not final_msg:
        return final_msg
    return final_msg + " " + _next_invisible_signature()


class AntiDieAllEngine:
    ZALO_RATELIMIT_CODES = {-2, -108, -112, -114, 112, 114, 300, 301, 302, 429, 500, 1001, 2001}
    ZALO_AUTH_CODES = {-401, 401, -102, 102, -30, -13, 3003}

    def __init__(self):
        self.lock = threading.Lock()
        self.state = defaultdict(lambda: {
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

    def can_send(self, acc_id, max_rpm=45):
        now = time.time()
        with self.lock:
            if now < self.global_cooldown_until:
                return False, round(self.global_cooldown_until - now, 2)

            st = self.state[acc_id]
            if st["circuit"] == "OPEN":
                if now < st["cooldown_until"]:
                    return False, round(st["cooldown_until"] - now, 2)
                else:
                    st["circuit"] = "HALF_OPEN"
                    st["adaptive_delay_bonus"] = max(0.6, st["adaptive_delay_bonus"])

            while st["timestamps"] and now - st["timestamps"][0] > 60.0:
                st["timestamps"].popleft()

            rpm = len(st["timestamps"])
            effective_limit = max_rpm if st["circuit"] == "CLOSED" else max(15, max_rpm // 2)
            if rpm >= effective_limit:
                wait_s = max(0.8, 60.0 - (now - st["timestamps"][0]) + random.uniform(0.2, 0.8))
                return False, round(wait_s, 2)

            recent_burst = sum(1 for t in st["timestamps"] if now - t <= 1.2)
            if recent_burst >= 5:
                return False, round(random.uniform(0.35, 0.75), 2)

            if st["timestamps"] and (now - st["timestamps"][-1]) < 0.20:
                return False, round(0.22 - (now - st["timestamps"][-1]), 2)

            return True, 0.0

    def get_adaptive_delay(self, acc_id, base_delay, antiband=True):
        with self.lock:
            st = self.state[acc_id]
            bonus = st["adaptive_delay_bonus"]
            risk = st["risk_score"]
            st["burst_counter"] += 1
            b_cnt = st["burst_counter"]

        d = float(base_delay) + bonus + (risk * 0.015)
        if antiband:
            jitter = abs(random.gauss(0.12, 0.08))
            if b_cnt % 18 == 0:
                jitter += random.uniform(0.45, 1.15)
            d += jitter
        return max(0.25, d)

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
            st["last_error"] = reason
            streak = min(st["ratelimit_streak"], 6)
            base_cd = float(retry_after) if retry_after else (12.0 * (1.7 ** (streak - 1)))
            cooldown = min(240.0, max(8.0, base_cd + random.uniform(1.5, 5.0)))
            st["circuit"] = "OPEN"
            st["cooldown_until"] = now + cooldown
            st["adaptive_delay_bonus"] = min(4.0, st["adaptive_delay_bonus"] + 0.65)
            st["risk_score"] = min(100.0, st["risk_score"] + 22.0)

            open_count = sum(1 for v in self.state.values() if v["circuit"] == "OPEN" and v["cooldown_until"] > now)
            if open_count >= 1 and len(self.state) >= 2 and open_count >= len(self.state) * 0.5:
                self.global_cooldown_until = max(self.global_cooldown_until, now + random.uniform(3.0, 6.0))

    def report_error(self, acc_id, err_msg="", is_auth_error=False):
        now = time.time()
        with self.lock:
            st = self.state[acc_id]
            st["fail_streak"] += 1
            st["fail_total"] += 1
            st["last_error"] = str(err_msg)[:120]
            if is_auth_error:
                st["circuit"] = "OPEN"
                st["cooldown_until"] = now + 180.0
                st["risk_score"] = min(100.0, st["risk_score"] + 40.0)
            elif st["fail_streak"] >= 3:
                backoff = min(150.0, 12.0 * (2 ** min(st["fail_streak"] - 3, 4)) + random.uniform(1.5, 4.0))
                st["circuit"] = "OPEN"
                st["cooldown_until"] = now + backoff
                st["adaptive_delay_bonus"] = min(3.5, st["adaptive_delay_bonus"] + 0.45)
                st["risk_score"] = min(100.0, st["risk_score"] + 15.0)
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
    {"id": "red",    "name": "Đỏ Rực",        "hex": "#db342e", "zcode": "db342e", "ansi": "31"},
    {"id": "yellow", "name": "Vàng Hoàng Kim", "hex": "#f7b503", "zcode": "f7b503", "ansi": "33"},
    {"id": "green",  "name": "Xanh Ngọc Lục",  "hex": "#15a85f", "zcode": "15a85f", "ansi": "32"},
    {"id": "orange", "name": "Cam Rực Lửa",    "hex": "#f27806", "zcode": "f27806", "ansi": "33"},
]

ZALO_NATIVE_ZCODES = ["db342e", "f7b503", "15a85f", "f27806"]
ZALO_COLOR_MAP = {
    "red": "db342e", "do": "db342e", "đỏ": "db342e",
    "yellow": "f7b503", "vang": "f7b503", "vàng": "f7b503",
    "green": "15a85f", "xanh": "15a85f", "xanhla": "15a85f",
    "orange": "f27806", "cam": "f27806",
    "ocean": "15a85f", "blue": "f7b503", "purple": "db342e", "pink": "f27806",
}

# 100% Bộ Icon Chuẩn Zalo Có Hiệu Ứng Động VIP (Đã loại bỏ ;;) và :-bd bị lỗi chữ thô trên iOS)
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
    """Làm sạch các ký tự tàng hình dính vào mã icon và chuyển đổi các mã Yahoo cũ (;;), :-bd, ;f)
    sang mã Icon Chuẩn Zalo Có Hiệu Ứng thật 100% trên Zalo iOS/Android."""
    if not text:
        return ""
    for zw in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"):
        text = text.replace(zw, "")
    text = re.sub(r"(?<!\S);f(?!\S)", ";-A", text)
    text = re.sub(r"(?<!\S);;?\)(?!\S)", "b-)", text)
    text = re.sub(r"(?<!\S):-bd(?!\S)", "/-bd", text)
    return text


def _is_emoji_or_zalo_shortcut_token(tk):
    """Kiểm tra xem token ở cuối dòng có phải là mã icon Zalo hoặc emoji có sẵn trong file .txt hay không."""
    if not tk:
        return False
    if tk in ZALO_ICON_VIP or tk in ("/-no", ":-d", ";f", ":-bd", ";;)", ";)"):
        return True
    # Nhận diện các emoji Unicode (như 😜, 😤, 🤣, 😡, 🫣, 😎, 💣, 👊, 👌) ở cuối dòng trong file .txt
    if all((ord(ch) > 0x2000 or ch in ("\ufe0f", "\u200d")) for ch in tk):
        return True
    return False


GROUP_MEMBERS_CACHE = {}
GROUP_CACHE_LOCK = threading.Lock()
KNOWN_GROUPS_BY_ACC = defaultdict(set)


# ============================================================
# CLIENT GIAO THỨC ZALO v7.0 ULTRA
# (CHỮ TO + ĐỔI MÀU TỪNG DÒNG 100% + TAG THẬT XANH DƯƠNG 100% + TẢI NHÓM BATCH SIÊU TỐC)
# ============================================================
class Zalo:
    def __init__(self, imei, cookies):
        self.imei = str(imei).strip()
        self.cookies_dict = cookies if isinstance(cookies, dict) else json.loads(cookies)
        self.s = requests.Session()
        adapter = HTTPAdapter(pool_connections=40, pool_maxsize=80, max_retries=2)
        self.s.mount("https://", adapter)
        self.s.mount("http://", adapter)
        self.s.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0.0.0 Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": "https://chat.zalo.me",
            "Referer": "https://chat.zalo.me/",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        })
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
        """Tải toàn bộ danh sách nhóm Zalo theo lô (Batch 50 nhóm/lần) giúp giao diện mượt tức thì, không bao giờ bị đơ."""
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
        # Gộp 50 nhóm mỗi request vào getmg-v2 thay vì gọi lẻ từng nhóm gây đơ web
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

    def group_info(self, gid):
        enc = self._enc({"gridVerMap": json.dumps({str(gid): 0})})
        r = self.s.post(
            "https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2",
            params={"zpw_ver": 645, "zpw_type": 30},
            data={"params": enc}, timeout=15,
        )
        dec = self._dec(r.json()["data"])
        info = json.loads(dec).get("data", {}).get("gridInfoMap", {}).get(str(gid), {})
        return {
            "name": info.get("name", "Nhóm Zalo"),
            "totalMember": info.get("totalMember", "?"),
            "raw": info
        }

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
        """Lấy 100% Tên Thật và UID của toàn bộ thành viên trong nhóm Zalo
        kết hợp 4 nguồn: getmg-v2 + GLOBAL_USER_NAME_CACHE + getprofiles/v2 + getuserinfo."""
        gid_str = str(gid)
        if use_cache:
            with GROUP_CACHE_LOCK:
                c = GROUP_MEMBERS_CACHE.get(gid_str)
                if c and time.time() - c["ts"] < 240:
                    return c["members"]

        enc = self._enc({"gridVerMap": json.dumps({gid_str: 0})})
        r = self.s.post(
            "https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2",
            params={"zpw_ver": 645, "zpw_type": 30},
            data={"params": enc}, timeout=20,
        )
        dec = self._dec(r.json().get("data", ""))
        info = json.loads(dec).get("data", {}).get("gridInfoMap", {}).get(gid_str, {})

        members_dict = {}
        for list_key in ("currentMems", "memInfoList", "members"):
            mem_list = info.get(list_key, [])
            if isinstance(mem_list, list):
                for m in mem_list:
                    if isinstance(m, dict):
                        uid = str(m.get("userId") or m.get("id") or "").strip()
                        name = (m.get("dName") or m.get("displayName") or m.get("zaloName") or m.get("name") or "").strip()
                        if uid and name:
                            members_dict[uid] = name
                            GLOBAL_USER_NAME_CACHE[uid] = name

        mem_ver_list = info.get("memVerList", [])
        uids = [str(m).split("_")[0] for m in mem_ver_list if m]
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
                    for uid in chunk:
                        p = profiles.get(uid, {})
                        pname = (p.get("displayName") or p.get("zaloName") or p.get("username") or "").strip()
                        if pname:
                            members_dict[uid] = pname
                            GLOBAL_USER_NAME_CACHE[uid] = pname
                except Exception:
                    pass

        out = []
        for uid in uids:
            real_name = members_dict.get(uid) or GLOBAL_USER_NAME_CACHE.get(uid) or f"Người dùng {uid[-6:]}"
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
                enc = self._enc({"grid": str(gid), "groupId": str(gid), "imed": 0, "count": 10})
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
        """Kiến trúc Rich-Text & Icon Chuẩn Zalo v7.0:
        1. Xoá số thứ tự đầu dòng ('1. ', '2. ') nếu ở chế độ nhây hoặc strip_line_num=True.
        2. Tách riêng các icon/emoji ở cuối dòng ra khỏi phần chữ chính `core_text`.
        3. Tạo mảng `styles` (b,f_18,c_<hex>) CHỈ trên phần chữ chính `core_text` (không chứa ký tự tàng hình,
           không chứa mã icon) để Zalo iOS/Android/Web hiển thị CHỮ TO IN ĐẬM + ĐỔI MÀU TỪNG DÒNG 100%!
        4. Trả về `(core_msg, styles, first_color, tail_icons_str)` để `send_adv` gắn `@Tag Thật 100%`
           ngay sau `core_msg` (trước `tail_icons_str`), giúp toạ độ `pos` của `@Tag` chính xác tuyệt đối 100%!"""
        raw_clean = clean_corrupted_shortcuts(raw_text)
        lines = raw_clean.split("\n")

        core_lines = []
        collected_tail_icons = []
        styles = []
        current_u16_pos = 0
        active_line_idx = color_offset
        prev_line_zcode = None
        first_color = "db342e"

        for i, ln in enumerate(lines):
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

            # Tách các mã Icon Zalo hoặc Emoji có sẵn ở cuối dòng ra khỏi phần chữ chính
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
                # Nếu là emoji Unicode thường (như 😜, 😤) thì tự động đổi sang Icon Chuẩn Zalo VIP có hiệu ứng
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

    def attach_mentions_real_zalo(self, core_msg, mentions=None, tag_all=False):
        """Gắn Tag Thật 100% chuẩn giao thức Chat Zalo (mentionInfo):
        - Đặt ngay sau `core_msg` (TRƯỚC khi gắn mã Icon Zalo VIP và TRƯỚC chữ ký Anti-Ban).
        - Nhờ `core_msg` hoàn toàn sạch (không có mã icon co giãn độ dài và không có ký tự tàng hình),
          toạ độ UTF-16 `(pos, len)` khớp 100% với tên thành viên trên Zalo iOS/Android/PC -> Bung thẻ Tag Xanh Dương Thật 100%!"""
        final = core_msg.rstrip() if core_msg else ""
        m_arr = []

        if tag_all:
            tag_token = "@All"
            pos = utf16_len(final) + (1 if final else 0)
            final = (final + " " + tag_token) if final else tag_token
            t_len = utf16_len(tag_token)
            m_arr.append({
                "pos": pos,
                "len": t_len,
                "uid": "-1",
                "type": 1
            })

        if mentions:
            seen_uids = set()
            for m in mentions:
                raw_name = str(m.get("name", "")).strip().lstrip("@")
                name = raw_name.split(" (")[0] if " (" in raw_name else raw_name
                uid = str(m.get("uid") or m.get("id") or "").strip()
                if not name or not uid or uid in ("-1", "0") or uid in seen_uids:
                    continue
                seen_uids.add(uid)

                tag_token = f"@{name}"
                pos = utf16_len(final) + (1 if final else 0)
                final = (final + " " + tag_token) if final else tag_token
                t_len = utf16_len(tag_token)
                m_arr.append({
                    "pos": pos,
                    "len": t_len,
                    "uid": str(uid),
                    "type": 0
                })

        return final, m_arr

    def _send_raw_payload(self, final_msg, thread_id, is_group, m_arr, styles, first_color="db342e"):
        url = ("https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
               if is_group
               else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms")

        client_id = str(int(time.time() * 1000)) + str(random.randint(100, 999))
        # Đăng ký ngay tin nhắn của Bot vào bộ nhớ chống lặp để Listener không bao giờ tự đọc lại .menu thành .spam!
        register_bot_sent_message(client_id=client_id, text=final_msg)

        pl = {
            "message": final_msg,
            "clientId": client_id,
            "imei": self.imei,
            "ttl": 0,
        }

        if is_group and m_arr:
            mention_json = json.dumps(m_arr, separators=(",", ":"), ensure_ascii=False)
            pl["mentionInfo"] = mention_json
            pl["mentions"] = mention_json

        if styles:
            params_obj = {"styles": styles, "ver": 0}
            params_json = json.dumps(params_obj, separators=(",", ":"), ensure_ascii=False)
            # Gửi đầy đủ cả textProperties và params để tương thích 100% trên Zalo iOS, Android và Zalo Web/PC
            pl["textProperties"] = params_json
            pl["params"] = params_json
            pl["styles"] = json.dumps(styles, separators=(",", ":"), ensure_ascii=False)
            if first_color:
                pl["msgColor"] = first_color

        if is_group:
            pl["visibility"] = 0
            pl["grid"] = str(thread_id)
        else:
            pl["toid"] = str(thread_id)

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
        core_msg, styles, first_color, tail_icon_str = self.build_colored_message_with_vip_icons(
            raw_text,
            color_mode=color_mode,
            fixed_color=fixed_color,
            is_heading=is_heading,
            color_offset=color_offset,
            antiband=antiband,
            use_emoji=use_emoji,
            icon_count=icon_count,
            strip_line_num=strip_line_num
        )

        # Bước 2: Gắn @Tag Thật 100% ngay sau core_msg (trước khi gắn Icon Zalo VIP để không bao giờ lệch pos!)
        msg_with_tags, m_arr = self.attach_mentions_real_zalo(
            core_msg,
            mentions=(mentions if is_group else None),
            tag_all=(tag_all if is_group else False)
        )

        # Bước 3: Gắn Icon Chuẩn Zalo Có Hiệu Ứng VIP vào sau phần @Tag
        if tail_icon_str:
            final_msg = f"{msg_with_tags} {tail_icon_str}".strip()
        else:
            final_msg = msg_with_tags

        # Bước 4: Gắn chữ ký tàng hình Anti-Ban ở cuối cùng của chuỗi (không làm xê dịch bất kỳ toạ độ nào phía trước)
        if antiband:
            final_msg = append_antiband_tail(final_msg)

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
# BỘ PHÂN TÍCH TAG THẬT 100% Ở CUỐI CÂU LỆNH (@TÊN & @ALL) CHO CẢ ZALO & DISCORD
# (ĐÃ FIX TRIỆT ĐỂ LỖI CẮT ĐẦU TÊN @Nguyen Trung Kien メ -> @n Trung Kien メ)
# ============================================================
def extract_trailing_tags_and_resolve(
    raw_text, incoming_mentions=None, zalo_client=None, group_id=None,
    prefix_u16_offset=0, discord_client=None, discord_channel_id=None
):
    """Nhận diện và phân giải Tag Thật 100% (@Tên hoặc @All) ở cuối câu lệnh:
    - Tự động trừ `prefix_u16_offset` (ví dụ độ dài '.nhay ' = 6) khi cắt tên từ `incoming_mentions` của Zalo,
      giúp lấy trọn vẹn 100% tên gốc '@Nguyen Trung Kien メ' thay vì bị cắt mất 6 ký tự đầu thành '@n Trung Kien メ'!
    - Tra cứu danh sách thành viên nhóm Zalo / Discord để lấy đúng UID và Tên hiển thị chuẩn."""
    if not raw_text and not incoming_mentions:
        return "", [], False

    text = (raw_text or "").strip()
    resolved_mentions = []
    tag_all = False

    members = []
    if zalo_client and group_id:
        try:
            members = zalo_client.get_members_full(group_id)
        except Exception:
            members = []
    elif discord_client and discord_channel_id:
        try:
            members = discord_client.get_box_members(discord_channel_id)
        except Exception:
            members = []

    # 1. Bóc tách từ metadata mentions của sự kiện tin nhắn Zalo hoặc Discord
    if incoming_mentions and isinstance(incoming_mentions, list):
        sorted_m = sorted(incoming_mentions, key=lambda x: int(x.get("pos", 0)), reverse=True)
        for m in sorted_m:
            uid = str(m.get("uid") or m.get("id") or "").strip()
            mtype = int(m.get("type", 0))
            raw_pos = int(m.get("pos", -1))
            mlen = int(m.get("len", 0))

            # Hiệu chỉnh vị trí UTF-16 sau khi đã cắt bỏ tiền tố lệnh (ví dụ '.nhay ')
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
                if adj_pos >= 0 and mlen > 0:
                    try:
                        u16_bytes = text.encode("utf-16-le")
                        # Nếu adj_pos trỏ đúng vào dấu '@' trên arg_body -> Cắt chính xác từ adj_pos đến adj_pos + mlen
                        if (adj_pos + mlen) * 2 <= len(u16_bytes):
                            sub = u16_bytes[adj_pos * 2:(adj_pos + mlen) * 2].decode("utf-16-le", errors="ignore").strip()
                            if sub.startswith("@"):
                                extracted_label = sub.lstrip("@").strip()
                                if extracted_label:
                                    m_name = extracted_label
                                text = (u16_bytes[:adj_pos * 2] + u16_bytes[(adj_pos + mlen) * 2:]).decode("utf-16-le", errors="ignore").strip()
                            else:
                                # Dự phòng nếu pos có sai số 1-2 ký tự khoảng trắng: Tìm vị trí '@' gần adj_pos nhất
                                at_idx = text.rfind("@")
                                if at_idx != -1:
                                    at_u16 = utf16_len(text[:at_idx])
                                    sub2 = u16_bytes[at_u16 * 2:(at_u16 + mlen) * 2].decode("utf-16-le", errors="ignore").strip()
                                    if sub2.startswith("@"):
                                        m_name = sub2.lstrip("@").strip() or m_name
                                        text = (u16_bytes[:at_u16 * 2] + u16_bytes[(at_u16 + mlen) * 2:]).decode("utf-16-le", errors="ignore").strip()
                    except Exception:
                        pass

                # Luôn ưu tiên đối chiếu với danh sách thành viên nhóm hoặc bộ nhớ tên thật để đảm bảo tên hiển thị chuẩn 100%
                if members:
                    found_mem = next((x for x in members if str(x.get("id") or x.get("uid")) == uid), None)
                    if found_mem and found_mem.get("name") and not str(found_mem["name"]).startswith("Người dùng "):
                        if not m_name or len(found_mem["name"]) >= len(m_name):
                            m_name = found_mem["name"]

                if m_name and not m_name.startswith("Người dùng "):
                    GLOBAL_USER_NAME_CACHE[uid] = m_name
                elif uid in GLOBAL_USER_NAME_CACHE:
                    m_name = GLOBAL_USER_NAME_CACHE[uid]

                if not any(x["uid"] == uid for x in resolved_mentions):
                    resolved_mentions.append({
                        "uid": uid,
                        "id": uid,
                        "name": m_name or f"Thành viên {uid[-4:]}"
                    })

    # 2. Kiểm tra thẻ mention Discord dạng <@123456789> hoặc <@!123456789> trong văn bản
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

    # 4. Đối chiếu @Tên ở cuối văn bản với danh sách thành viên thật của nhóm (hỗ trợ cả có dấu & không dấu)
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
                    if not mname or mname.startswith("Người dùng "):
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

        # Khớp tên hoặc phần đuôi @Tên ở cuối câu (ví dụ .nhay @Nguyen Trung Kien メ)
        tail_at_match = re.search(r"(?:\s+|^)@([^\s@][^@]{0,40})$", text)
        if tail_at_match:
            partial_raw = tail_at_match.group(1).strip()
            partial_low = partial_raw.lower()
            partial_no_acc = remove_vn_accents(partial_raw)
            if partial_low in ("all", "tất cả", "tat ca", "everyone", "here"):
                tag_all = True
                text = text[:tail_at_match.start()].rstrip()
            elif members:
                sorted_members = sorted(members, key=lambda x: len(x.get("name", "")), reverse=True)
                matched_mem = next(
                    (
                        m for m in sorted_members
                        if not m.get("name", "").startswith("Người dùng ") and (
                            partial_low in m.get("name", "").lower()
                            or (len(partial_no_acc) >= 2 and partial_no_acc in remove_vn_accents(m.get("name", "")))
                        )
                    ),
                    None
                )
                # Trường hợp đặc biệt: Nhóm 2 thành viên (như nhóm 'test treo - 2 thành viên'), nếu Zalo ẩn tên người lạ
                # thành 'Người dùng ...' thì thành viên duy nhất còn lại trong nhóm chắc chắn 100% là người được Tag!
                if not matched_mem and zalo_client:
                    other_mems = [m for m in members if str(m.get("id")) != str(zalo_client.uid)]
                    if len(other_mems) == 1:
                        matched_mem = {
                            "id": str(other_mems[0]["id"]),
                            "uid": str(other_mems[0]["id"]),
                            "name": partial_raw
                        }
                        GLOBAL_USER_NAME_CACHE[str(other_mems[0]["id"])] = partial_raw

                if matched_mem:
                    m_uid = str(matched_mem.get("id") or matched_mem.get("uid"))
                    real_label = matched_mem["name"] if not matched_mem["name"].startswith("Người dùng ") else partial_raw
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
                    # Nếu UID đã được lấy từ incoming_mentions nhưng phần chữ @... vẫn còn sót ở cuối câu
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
# CLIENT GIAO THỨC DISCORD v7.0 ULTRA
# (HỖ TRỢ THẲNG ACC CHÍNH CHỦ USER TOKEN + LẤY ALL BOX DM/NHÓM/SERVER + TAG THẬT)
# ============================================================
class DiscordBot:
    def __init__(self, token, is_bot=False):
        raw_tok = str(token or "").strip()
        if raw_tok.lower().startswith("bot "):
            raw_tok = raw_tok[4:].strip()
            is_bot = True
        self.token = raw_tok
        self.is_bot = bool(is_bot)
        self.s = requests.Session()
        adapter = HTTPAdapter(pool_connections=30, pool_maxsize=60, max_retries=2)
        self.s.mount("https://", adapter)
        self.s.mount("http://", adapter)
        self._apply_headers()
        self.user_id = None
        self.username = None
        self.display_name = None

    def _apply_headers(self):
        auth_header = f"Bot {self.token}" if self.is_bot else self.token
        self.s.headers.update({
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0.0.0 Safari/537.36" if not self.is_bot
                           else "DiscordBot (ALBForgeUltra, 7.0.0)")
        })

    def check(self):
        """Tự động nhận diện Acc Chính Chủ (User Token) hoặc Bot Token thông minh."""
        r = self.s.get("https://discord.com/api/v10/users/@me", timeout=12)
        if r.status_code == 401:
            # Tự động thử đảo chế độ User Token <-> Bot Token nếu người dùng chọn nhầm
            self.is_bot = not self.is_bot
            self._apply_headers()
            r = self.s.get("https://discord.com/api/v10/users/@me", timeout=12)

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
        """Lấy toàn bộ Box Chat Nhóm (Group DM) và Chat Riêng (Direct Message) trên Acc Chính Chủ Discord."""
        out = []
        try:
            r = self.s.get("https://discord.com/api/v10/users/@me/channels", timeout=15)
            if r.status_code == 200:
                channels = r.json()
                if isinstance(channels, list):
                    # Sắp xếp theo tin nhắn gần nhất (last_message_id)
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
                            # Group DM (Box Chat Nhóm trên Discord)
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
                            # Direct Message (Chat Riêng 1-1 trên Discord)
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
            r = self.s.get("https://discord.com/api/v10/users/@me/guilds", timeout=15)
            if r.status_code == 200:
                return [{"id": str(g["id"]), "name": g.get("name", "Server"), "type": "discord_guild"} for g in r.json()]
        except Exception:
            pass
        return []

    def get_channels(self, guild_id, guild_name=""):
        try:
            r = self.s.get(f"https://discord.com/api/v10/guilds/{guild_id}/channels", timeout=12)
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
        """Lấy TẤT CẢ Box Chat ở Discord cùng lúc cho Acc Chính Chủ:
        Bao gồm toàn bộ Box Nhóm (Group DM) + Chat Riêng (DM) + Toàn bộ Kênh Chat trong các Server!"""
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
        """Lấy danh sách thành viên trong Box Discord (Group DM, DM, hoặc Kênh Server) để chọn Tag Thật <@id>."""
        members = []
        seen = set()
        try:
            r = self.s.get(f"https://discord.com/api/v10/channels/{channel_id}", timeout=10)
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

        # Quét thêm người vừa nhắn tin gần đây trong kênh Discord đó để lấy đầy đủ người trong kênh Server
        try:
            r_msgs = self.s.get(f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=35", timeout=10)
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

    def get_recent_messages(self, channel_id, limit=6):
        try:
            r = self.s.get(f"https://discord.com/api/v10/channels/{channel_id}/messages?limit={limit}", timeout=8)
            if r.status_code == 200 and isinstance(r.json(), list):
                return r.json()
        except Exception:
            pass
        return []

    def send_message(self, channel_id, content, color_mode="none", fixed_color=None,
                     antiband=True, mentions=None, tag_all=False, strip_line_num=False):
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        raw = clean_corrupted_shortcuts(content)
        if strip_line_num:
            raw = "\n".join(strip_leading_line_number(ln) for ln in raw.split("\n"))

        DISCORD_ANSI_CODES = {
            "red": "31", "green": "32", "yellow": "33", "orange": "33",
            "blue": "34", "purple": "35", "ocean": "36", "pink": "35"
        }

        # Chuẩn bị chuỗi Tag Thật Discord (<@uid> và @everyone) nằm NGOÀI khối ```ansi để Discord thông báo & hiện màu xanh thật 100%
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

        if color_mode != "none":
            if color_mode in ("rainbow", "word_rainbow", "random"):
                ansi_pool = ["31", "32", "33", "34", "35", "36"]
                lines = raw.split("\n")
                colored_lines = []
                for idx, ln in enumerate(lines):
                    c_code = ansi_pool[idx % len(ansi_pool)]
                    colored_lines.append(f"\u001b[1;{c_code}m{ln}\u001b[0m")
                ansi_body = "\n".join(colored_lines)
                formatted_content = f"```ansi\n{ansi_body}\n```{tag_suffix}"
            else:
                code = DISCORD_ANSI_CODES.get(fixed_color, "31")
                formatted_content = f"```ansi\n\u001b[1;{code}m{raw}\u001b[0m\n```{tag_suffix}"
        else:
            formatted_content = f"{raw}{tag_suffix}"

        if antiband:
            formatted_content = append_antiband_tail(formatted_content)

        # Đăng ký trước vào bộ nhớ chống lặp để DiscordSelfBotListener không bao giờ tự chạy lệnh từ tin nhắn của Bot
        register_bot_sent_message(text=formatted_content)
        register_bot_sent_message(text=raw)

        pl = {"content": formatted_content}
        r = self.s.post(url, json=pl, timeout=15)
        if r.status_code == 429:
            try:
                retry_after = r.json().get("retry_after", 10)
            except Exception:
                retry_after = 10
            raise Exception(f"429:RateLimit:{retry_after}")
        if r.status_code not in (200, 201):
            raise Exception(f"HTTP {r.status_code}: {r.text[:100]}")

        resp_data = r.json()
        if isinstance(resp_data, dict) and resp_data.get("id"):
            register_bot_sent_message(msg_id=resp_data["id"], text=formatted_content)
        return resp_data


# ============================================================
# ĐỘNG CƠ ĐA LUỒNG CHẠY 2-5 ĐOẠN CHAT SONG SONG ỔN ĐỊNH KHÔNG LAG (ZALO & DISCORD)
# ============================================================
def box_target_worker(client, acc_id, plat, target, blocks, runtime_opts,
                      stop_ev, counter, lock, stagger_sec=0.0):
    """Luồng độc lập cho từng đoạn chat (hỗ trợ chạy song song 2-5+ đoạn chat mượt mà trên cả Zalo và Discord,
    tự động xoá số thứ tự đầu dòng '1. ', '2. ' ở chế độ Treo Nhây)."""
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
            ok_send, wait_sec = HEALTH_MGR.can_send(acc_id)
            if not ok_send:
                stop_ev.wait(min(2.0, max(0.3, wait_sec)))
                continue

        raw = blocks[b_idx % len(blocks)]
        b_idx += 1

        eff_mentions = list(tag_users)
        eff_tag_all = tag_all
        clean_raw = raw

        # Nếu trong nội dung có @Tên hoặc @All ở cuối -> Phân giải ra UID Tag Thật 100%
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
                        strip_line_num=False
                    )

                color_counter += 1
                with lock:
                    counter["sent"] += 1
                HEALTH_MGR.report_success(acc_id)

            elif mode == "treo_nhay":
                # Tự động xoá số thứ tự đầu dòng ('1. ', '2. ', '3. ') khi chạy chế độ Nhây
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
                        ok_s, w_s = HEALTH_MGR.can_send(acc_id)
                        if not ok_s:
                            stop_ev.wait(min(1.8, max(0.3, w_s)))
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
                            strip_line_num=True
                        )

                    color_counter += 1
                    with lock:
                        counter["sent"] += 1
                    HEALTH_MGR.report_success(acc_id)
                    step_d = HEALTH_MGR.get_adaptive_delay(acc_id, delay, antiband=antiband)
                    stop_ev.wait(max(0.25, step_d))
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
                        strip_line_num=strip_line_num
                    )

                color_counter += 1
                with lock:
                    counter["sent"] += 1
                HEALTH_MGR.report_success(acc_id)

        except Exception as e:
            err_str = str(e)
            print(f"[Worker #{acc_id} -> Box {target_id}] Cảnh báo gửi: {err_str}")
            if "429:RateLimit:" in err_str:
                parts = err_str.split(":")
                try:
                    retry_after = float(parts[2])
                except Exception:
                    retry_after = 20.0
                HEALTH_MGR.report_rate_limit(acc_id, retry_after, reason=err_str)
            elif "AuthError" in err_str:
                HEALTH_MGR.report_error(acc_id, err_str, is_auth_error=True)
            else:
                HEALTH_MGR.report_error(acc_id, err_str, is_auth_error=False)

        actual_delay = HEALTH_MGR.get_adaptive_delay(acc_id, delay, antiband=antiband)
        stop_ev.wait(max(0.25, actual_delay))


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

    # Nếu chế độ là treo_nhay, tự động xoá số thứ tự 1., 2., 3. ở đầu từng dòng ngay từ đầu
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
# HỆ THỐNG SELF-BOT LỆNH KHUNG CHAT ZALO & DISCORD v7.0 ULTRA
# (ĐÃ FIX TRIỆT ĐỂ LỖI .MENU TỰ CHẠY SPAM + HỖ TRỢ CẢ 2 APP ZALO & DISCORD)
# ============================================================
def log_bot_command(acc_id, thread_id, sender_id, cmd_text, action_taken):
    try:
        conn = db()
        conn.execute(
            "INSERT INTO bot_logs (acc_id, thread_id, sender_id, cmd_text, action_taken, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (acc_id, str(thread_id), str(sender_id), cmd_text[:300], action_taken[:300], time.time())
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
    """Thực thi lệnh trực tiếp trên khung chat cho CẢ 2 APP (Zalo & Discord Chính Chủ):
    - Lớp bảo vệ 1: Chặn tuyệt đối mọi tin nhắn do chính Bot vừa phát ra (`is_bot_echo_message`) để gõ `.menu` không bao giờ tự chạy `.spam`.
    - Lớp bảo vệ 2: Mỗi dòng trong `.menu` đều bắt đầu bằng dấu `• ` nên bản thân nội dung `.menu` không bao giờ bắt đầu bằng dấu `.`.
    - Lớp bảo vệ 3: Chặn mọi chuỗi chứa cú pháp hướng dẫn `<nội dung>`, `<số file>`, `[@Tên / @All]`.
    - Tính chính xác `prefix_u16_offset` để khi gõ `.nhay @Nguyen Trung Kien メ` lấy đúng 100% tên `@Nguyen Trung Kien メ`."""
    if not raw_msg:
        return False

    # Lớp bảo vệ 1: Nếu tin nhắn này nằm trong bộ nhớ đệm tin nhắn do Bot tự gửi -> Bỏ qua ngay lập tức!
    if is_bot_echo_message(text=raw_msg):
        return False

    text = strip_invisible_chars(str(raw_msg))
    if not text:
        return False

    # Lớp bảo vệ 3: Nếu tin nhắn có nhiều dòng chứa bảng hướng dẫn hoặc chứa thẻ mẫu '<nội dung>' -> Tuyệt đối không thực thi!
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
                    thread_id, msg_txt, color_mode="rainbow", antiband=True
                )
        except Exception as e:
            print(f"[SelfBot #{acc_id} ({platform})] Lỗi gửi phản hồi: {e}")

    # 1. LỆNH .MENU / .HELP (SẠCH SẼ - MỖI DÒNG BẮT ĐẦU BẰNG '• ' ĐỂ KHÔNG BAO GIỜ TỰ KÍCH HOẠT .SPAM)
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

    # 2. LỆNH PHÂN QUYỀN CHO NGƯỜI KHÁC DÙNG LỆNH (.chophep / .xoaquyen / .dsquyen)
    if cmd_token in ("chophep", "capquyen", "adduser", "add", "admin"):
        if not is_owner:
            return False
        _, target_mentions, _ = extract_trailing_tags_and_resolve(
            arg_body, incoming_mentions=raw_mentions,
            zalo_client=zalo_client if (platform == "zalo" and is_group) else None,
            group_id=thread_id if (platform == "zalo" and is_group) else None,
            prefix_u16_offset=prefix_u16_offset,
            discord_client=discord_client if platform == "discord" else None,
            discord_channel_id=thread_id if platform == "discord" else None
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
                discord_channel_id=thread_id if platform == "discord" else None
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
            reply_txt = "\n".join(f"• {u['name']} ({u['uid']})" for u in users)
        _send_reply(reply_txt)
        return True

    # 3. CÁC LỆNH CHỈNH DELAY & CHỨC NĂNG TRỰC TIẾP (.delay, .mau, .icon, .chuto, .antiband)
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
            reply_txt = "Đã bật tự động phối màu từng dòng (Không trùng màu)"
        elif arg_c in ("word", "word_rainbow", "tu", "tungtu"):
            update_running_tasks_config(color_mode="word_rainbow")
            reply_txt = "Đã bật phối màu từng từ"
        elif arg_c in ("random", "ngaunhien"):
            update_running_tasks_config(color_mode="random")
            reply_txt = "Đã bật phối màu ngẫu nhiên không trùng"
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
            reply_txt = f"Đã chỉnh số lượng Icon Chuẩn Zalo VIP: {ic_n}"
        except Exception:
            reply_txt = "Cú pháp: .icon <số lượng từ 0 đến 10>"
        _send_reply(reply_txt)
        return True

    if cmd_token in ("chuto", "heading"):
        on_val = arg_body.strip().lower() not in ("off", "tat", "0")
        update_running_tasks_config(is_heading=on_val)
        reply_txt = "Đã BẬT chữ lớn in đậm Zalo" if on_val else "Đã TẮT chữ lớn in đậm Zalo"
        _send_reply(reply_txt)
        return True

    if cmd_token in ("antiband", "antiban"):
        on_val = arg_body.strip().lower() not in ("off", "tat", "0")
        update_running_tasks_config(antiband=on_val)
        reply_txt = "Đã BẬT Anti-Ban bảo vệ tài khoản" if on_val else "Đã TẮT Anti-Ban"
        _send_reply(reply_txt)
        return True

    # 4. LỆNH DỪNG (.stop / .dung / .tat / .stopall)
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

    # 5. LỆNH XEM DANH SÁCH FILE (.files / .dsfile)
    if cmd_token in ("files", "dsfile", "listfile"):
        f_list = get_ordered_files_with_display_num()
        if not f_list:
            msg_out = "Chưa có file nào trên hệ thống"
        else:
            msg_out = "\n".join(f"File số {f['display_num']}: {f['filename']} ({f['lines_count']} dòng)" for f in f_list)
        _send_reply(msg_out)
        log_bot_command(acc_id, thread_id, sender_id, text, "Hiển thị danh sách số thứ tự file")
        return True

    # 6. CÁC LỆNH KHỞI CHẠY (.spam, .nhay, .ngon, .file, HOẶC GÕ TRỰC TIẾP SỐ FILE NHƯ .1, .2)
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

    # Bóc tách @Tên hoặc @All ở cuối câu lệnh với `prefix_u16_offset` chuẩn xác 100%
    cleaned_body, extracted_mentions, extracted_tag_all = extract_trailing_tags_and_resolve(
        arg_body,
        incoming_mentions=raw_mentions,
        zalo_client=zalo_client if (platform == "zalo" and is_group) else None,
        group_id=thread_id if (platform == "zalo" and is_group) else None,
        prefix_u16_offset=prefix_u16_offset,
        discord_client=discord_client if platform == "discord" else None,
        discord_channel_id=thread_id if platform == "discord" else None
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
        for key in ("mentions", "mentionInfo"):
            val = msg_obj.get(key)
            if isinstance(val, list) and val:
                return val
            if isinstance(val, str) and val.strip().startswith("["):
                try:
                    return json.loads(val)
                except Exception:
                    pass
        for nested_key in ("propertyExt", "params"):
            sub = msg_obj.get(nested_key)
            if isinstance(sub, str) and sub.strip().startswith("{"):
                try:
                    sub = json.loads(sub)
                except Exception:
                    sub = None
            if isinstance(sub, dict):
                for mkey in ("mentions", "mentionInfo"):
                    mval = sub.get(mkey)
                    if isinstance(mval, list) and mval:
                        return mval
                    if isinstance(mval, str) and mval.strip().startswith("["):
                        try:
                            return json.loads(mval)
                        except Exception:
                            pass
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

        # Chặn ngay từ vòng gửi xe nếu là tin nhắn do chính Bot vừa gửi (Fix triệt để lỗi .menu tự chạy .spam)
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

        self.ws_status = "🟢 Zalo 24/7 Đang Lắng Nghe"
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
                            self.ws_status = "🟢 Zalo 24/7 (WS Key Synced)"
                        elif isinstance(outer.get("data"), dict) and outer["data"].get("key"):
                            self.ws_cipher_key = outer["data"]["key"]
                            self.ws_status = "🟢 Zalo 24/7 (WS Key Synced)"

                        if cmd_id == 3000:
                            self.ws_status = "🟡 Đang đồng bộ lại phiên WS..."
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
            except Exception as e:
                self.ws_status = f"🔴 Lỗi kết nối: {str(e)[:35]}"
                self.stop_ev.wait(5.0)


# ============================================================
# LISTENER 24/7 TRÊN DISCORD ACC CHÍNH CHỦ & BOT (GATEWAY v10 WEBSOCKET)
# ============================================================
class DiscordSelfBotListener:
    """Lắng nghe lệnh trực tiếp trên mọi Box Chat Discord (DM, Group DM, Server Channels)
    cho cả Acc Chính Chủ (User Token) và Bot Token thông qua Discord Gateway v10."""
    def __init__(self, acc_id):
        self.acc_id = acc_id
        self.platform = "discord"
        self.stop_ev = threading.Event()
        self.seen_msg_ids = deque(maxlen=1000)
        self.ws_status = "Đang kết nối Discord Gateway..."
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
                                        "properties": {"os": "linux", "browser": "alb_forge", "device": "alb_forge"}
                                    }
                                }
                            else:
                                # Identify chuẩn Acc Chính Chủ Discord (User Token)
                                ident_payload = {
                                    "op": 2,
                                    "d": {
                                        "token": client.token,
                                        "capabilities": 16381,
                                        "properties": {
                                            "os": "Windows",
                                            "browser": "Chrome",
                                            "device": "",
                                            "system_locale": "vi-VN",
                                            "browser_user_agent": client.s.headers.get("User-Agent"),
                                            "browser_version": "126.0.0.0",
                                            "os_version": "10",
                                            "release_channel": "stable",
                                            "client_build_number": 305000
                                        },
                                        "presence": {"status": "online", "since": 0, "activities": [], "afk": False},
                                        "compress": False
                                    }
                                }
                            ZaloSelfBotListener._send_ws_frame(sock, json.dumps(ident_payload).encode("utf-8"), opcode=0x1)
                            identified = True
                            last_hb = time.time()
                            self.ws_status = "🟢 Discord 24/7 Đang Lắng Nghe (All Box)"

                        elif op == 0 and t_ev == " READY" and isinstance(d_ev, dict):
                            self.ws_status = "🟢 Discord 24/7 Đang Lắng Nghe (All Box)"

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
                    self.ws_status = "🔴 Token Discord hết hạn"
                    self.stop_ev.wait(10.0)
                    continue

                self._run_gateway_session(client, acc_row)
                self.stop_ev.wait(3.0)
            except Exception as e:
                self.ws_status = f"🔴 Lỗi Discord WS: {str(e)[:30]}"
                self.stop_ev.wait(5.0)


def sync_all_zalo_listeners():
    """Đồng bộ toàn bộ Listener 24/7 cho cả 2 nền tảng Zalo & Discord."""
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
    except Exception as e:
        print(f"[ListenerSync] Cảnh báo: {e}")


threading.Timer(1.2, sync_all_zalo_listeners).start()


# ============================================================
# GIAO DIỆN CYBER-OBSIDIAN v7.0 ULTRA (SIÊU MƯỢT 60FPS - KHÔNG ĐƠ LAG)
# ============================================================
CSS_NOEL_PRO = """
:root {
  --bg-main: #070b14;
  --bg-card: #0f172a;
  --bg-card-alt: #131d35;
  --bg-input: #090e1a;
  --border: rgba(148, 163, 184, 0.16);
  --border-focus: #06b6d4;
  --primary: #10b981;
  --primary-hover: #059669;
  --accent: #06b6d4;
  --indigo: #6366f1;
  --gold: #f59e0b;
  --danger: #ef4444;
  --text-main: #f8fafc;
  --text-sub: #94a3b8;
  --radius-lg: 16px;
  --radius-md: 11px;
  --shadow: 0 10px 30px -5px rgba(0, 0, 0, 0.55);
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
  -webkit-tap-highlight-color: transparent;
}

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background-color: var(--bg-main);
  background-image:
    radial-gradient(circle at 10% 0%, rgba(16, 185, 129, 0.10) 0%, transparent 40%),
    radial-gradient(circle at 90% 0%, rgba(99, 102, 241, 0.10) 0%, transparent 40%);
  color: var(--text-main);
  min-height: 100vh;
  line-height: 1.5;
  overflow-x: hidden;
}

.app-shell {
  max-width: 1440px;
  margin: 0 auto;
  padding: 18px 16px 48px;
}

/* TOP NAVBAR */
.topbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 14px 20px;
  margin-bottom: 18px;
  box-shadow: var(--shadow);
}

.brand-box {
  display: flex;
  align-items: center;
  gap: 13px;
}

.brand-logo {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #10b981, #06b6d4);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 900;
  font-size: 1.25rem;
  color: #04131a;
  box-shadow: 0 4px 15px rgba(16, 185, 129, 0.35);
}

.brand-title {
  font-size: 1.18rem;
  font-weight: 800;
  letter-spacing: -0.01em;
  background: linear-gradient(90deg, #ffffff, #67e8f9, #34d399);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.brand-sub {
  font-size: 0.78rem;
  color: var(--text-sub);
}

/* KPI STATS BAR */
.kpi-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}

@media (max-width: 900px) {
  .kpi-strip { grid-template-columns: repeat(2, 1fr); }
}

.kpi-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 13px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.kpi-label {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-sub);
  font-weight: 700;
}

.kpi-val {
  font-size: 1.38rem;
  font-weight: 800;
  color: #fff;
  margin-top: 2px;
}

.kpi-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.15rem;
  background: rgba(6, 182, 212, 0.12);
  color: #22d3ee;
}

/* MAIN 2-COLUMN GRID */
.workspace-grid {
  display: grid;
  grid-template-columns: 430px 1fr;
  gap: 18px;
  align-items: start;
}

@media (max-width: 1080px) {
  .workspace-grid { grid-template-columns: 1fr; }
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 18px;
  margin-bottom: 18px;
  box-shadow: var(--shadow);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 12px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border);
}

.card-title {
  font-size: 0.98rem;
  font-weight: 800;
  color: #f8fafc;
  display: flex;
  align-items: center;
  gap: 8px;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
}

.badge-green { background: rgba(16, 185, 129, 0.16); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.32); }
.badge-cyan  { background: rgba(6, 182, 212, 0.16); color: #22d3ee; border: 1px solid rgba(6, 182, 212, 0.32); }
.badge-indigo{ background: rgba(99, 102, 241, 0.18); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.35); }
.badge-gold  { background: rgba(245, 158, 11, 0.16); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.35); }
.badge-red   { background: rgba(239, 68, 68, 0.16); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.35); }

/* FORMS & INPUTS */
label {
  display: block;
  font-size: 0.79rem;
  font-weight: 600;
  color: #cbd5e1;
  margin-bottom: 5px;
}

input[type="text"],
input[type="password"],
input[type="number"],
select,
textarea {
  width: 100%;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 9px 12px;
  color: var(--text-main);
  font-size: 0.88rem;
  font-family: inherit;
  transition: border-color 0.15s ease;
}

input:focus, select:focus, textarea:focus {
  outline: none;
  border-color: var(--border-focus);
}

textarea {
  resize: vertical;
  min-height: 90px;
}

/* BUTTONS */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px 14px;
  border-radius: var(--radius-md);
  font-weight: 700;
  font-size: 0.84rem;
  cursor: pointer;
  border: 1px solid transparent;
  transition: transform 0.1s ease, opacity 0.15s ease, background-color 0.15s ease;
  color: #fff;
  user-select: none;
}

.btn:active { transform: scale(0.98); }
.btn-primary { background: linear-gradient(135deg, #10b981, #059669); }
.btn-cyan    { background: linear-gradient(135deg, #06b6d4, #0284c7); }
.btn-indigo  { background: linear-gradient(135deg, #6366f1, #4f46e5); }
.btn-gold    { background: linear-gradient(135deg, #f59e0b, #d97706); color: #090d16; }
.btn-danger  { background: linear-gradient(135deg, #ef4444, #dc2626); }
.btn-ghost   { background: rgba(255, 255, 255, 0.05); border-color: var(--border); color: #e2e8f0; }
.btn-ghost:hover { background: rgba(255, 255, 255, 0.10); }
.btn-sm      { padding: 5px 10px; font-size: 0.76rem; border-radius: 8px; }
.btn-block   { width: 100%; }

/* PLATFORM TABS */
.plat-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  background: var(--bg-input);
  padding: 5px;
  border-radius: 12px;
  border: 1px solid var(--border);
  margin-bottom: 12px;
}

.plat-btn {
  padding: 8px 10px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--text-sub);
  font-weight: 700;
  font-size: 0.83rem;
  cursor: pointer;
}

.plat-btn.active-zalo {
  background: linear-gradient(135deg, #0284c7, #06b6d4);
  color: #fff;
}

.plat-btn.active-discord {
  background: linear-gradient(135deg, #6366f1, #4f46e5);
  color: #fff;
}

/* SCROLLABLE LIST CONTAINERS (GPU OPTIMIZED - NO LAG) */
.scroll-box {
  max-height: 270px;
  overflow-y: auto;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 8px;
}

.scroll-box::-webkit-scrollbar { width: 6px; }
.scroll-box::-webkit-scrollbar-thumb { background: rgba(148, 163, 184, 0.28); border-radius: 99px; }

.list-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 11px;
  border-radius: 10px;
  background: var(--bg-card-alt);
  border: 1px solid rgba(148, 163, 184, 0.10);
  margin-bottom: 7px;
}

.list-item:last-child { margin-bottom: 0; }
.list-item:hover { border-color: rgba(6, 182, 212, 0.35); }

/* DROPZONE */
.dropzone {
  border: 1.5px dashed rgba(6, 182, 212, 0.45);
  background: rgba(6, 182, 212, 0.04);
  border-radius: 13px;
  padding: 16px;
  text-align: center;
  cursor: pointer;
  margin-bottom: 12px;
}

.dropzone:hover {
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.06);
}

/* COLOR SWATCHES */
.swatch-bar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 6px;
}

.swatch-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border-radius: 999px;
  font-size: 0.76rem;
  font-weight: 700;
  cursor: pointer;
  border: 2px solid transparent;
  background: var(--bg-input);
  color: #f8fafc;
}

.swatch-pill.active {
  border-color: #fff;
  box-shadow: 0 0 10px rgba(255, 255, 255, 0.25);
}

.dot { width: 11px; height: 11px; border-radius: 50%; display: inline-block; }

/* TOAST */
#toastBox {
  position: fixed;
  bottom: 18px;
  right: 18px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 350px;
}

.toast-item {
  background: #0f172a;
  border-left: 4px solid #10b981;
  border-top: 1px solid var(--border);
  border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  color: #f8fafc;
  padding: 11px 14px;
  border-radius: 10px;
  font-size: 0.84rem;
  font-weight: 600;
  box-shadow: 0 10px 25px rgba(0,0,0,0.6);
}

/* AUTH CARD */
.auth-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.auth-card {
  width: 100%;
  max-width: 420px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 28px 24px;
  box-shadow: var(--shadow);
}
"""

HTML_GATE = """<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Bảo Mật Hệ Thống — ALB FORGE v7.0 ULTRA</title>
  <style>""" + CSS_NOEL_PRO + """</style>
</head>
<body>
  <div class="auth-wrap">
    <div class="auth-card">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
        <div class="brand-logo">⚡</div>
        <div>
          <div class="brand-title">ALB FORGE v7.0 ULTRA</div>
          <div class="brand-sub">Zalo & Discord Chính Chủ Automation</div>
        </div>
      </div>
      <p style="font-size:0.84rem;color:var(--text-sub);margin-bottom:14px">
        Nhập mã khóa bảo mật hệ thống để mở cổng điều khiển.
      </p>
      __ERR_BLOCK__
      <form method="post" action="/gate">
        <label>Mã Khóa Truy Cập (Access Key)</label>
        <input type="password" name="key" placeholder="Nhập khóa bảo mật..." required autofocus style="margin-bottom:14px">
        <button type="submit" class="btn btn-primary btn-block">MỞ KHÓA HỆ THỐNG</button>
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
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Đăng Nhập Quản Trị — ALB FORGE v7.0 ULTRA</title>
  <style>""" + CSS_NOEL_PRO + """</style>
</head>
<body>
  <div class="auth-wrap">
    <div class="auth-card">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
        <div class="brand-logo">⚡</div>
        <div>
          <div class="brand-title">ALB FORGE v7.0 ULTRA</div>
          <div class="brand-sub">Đăng Nhập Hoặc Tạo Tài Khoản Quản Trị</div>
        </div>
      </div>
      __MSG_BLOCK__
      <form method="post" action="/login" style="margin-bottom:16px">
        <label>Tên tài khoản</label>
        <input type="text" name="username" placeholder="Nhập username..." required style="margin-bottom:10px">
        <label>Mật khẩu</label>
        <input type="password" name="password" placeholder="Nhập mật khẩu..." required style="margin-bottom:12px">
        <button type="submit" class="btn btn-primary btn-block">ĐĂNG NHẬP NGAY</button>
      </form>
      <details style="border-top:1px solid var(--border);padding-top:12px">
        <summary style="cursor:pointer;font-size:0.82rem;color:#22d3ee;font-weight:700">Chưa có tài khoản? Đăng ký nhanh tại đây</summary>
        <form method="post" action="/register" style="margin-top:10px">
          <label>Tài khoản mới</label>
          <input type="text" name="username" required style="margin-bottom:8px">
          <label>Mật khẩu mới</label>
          <input type="password" name="password" required style="margin-bottom:10px">
          <button type="submit" class="btn btn-indigo btn-block">TẠO TÀI KHOẢN MỚI</button>
        </form>
      </details>
    </div>
  </div>
</body>
</html>
"""

HTML_INDEX_PART1 = """<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ALB FORGE v7.0 ULTRA — Zalo & Discord Chính Chủ</title>
  <style>""" + CSS_NOEL_PRO + """</style>
</head>
<body>
  <div id="toastBox"></div>

  <div class="app-shell">
    <!-- TOP HEADER -->
    <header class="topbar">
      <div class="brand-box">
        <div class="brand-logo">⚡</div>
        <div>
          <div class="brand-title">ALB FORGE v7.0 ULTRA — ZALO & DISCORD PRO</div>
          <div class="brand-sub">
            Chữ To Đổi Màu 100% • Tag Thật Xanh Dương 100% • Tự Xoá Số Thứ Tự Đầu Dòng (1., 2.) • Discord Chính Chủ All Box 24/7
          </div>
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <span class="badge badge-green">🛡️ Anti-Ban Zero-Shift v7</span>
        <span class="badge badge-cyan">🤖 Self-Bot 24/7 Zalo + Discord</span>
        <button class="btn btn-danger btn-sm" onclick="stopAllTasks()">⏹ DỪNG TẤT CẢ</button>
        <a href="/logout" class="btn btn-ghost btn-sm" style="text-decoration:none">Đăng xuất (__USER__)</a>
      </div>
    </header>

    <!-- KPI BAR -->
    <section class="kpi-strip">
      <div class="kpi-card">
        <div>
          <div class="kpi-label">Tài Khoản Kết Nối</div>
          <div class="kpi-val" id="kpiAccounts">0</div>
        </div>
        <div class="kpi-icon">👤</div>
      </div>
      <div class="kpi-card">
        <div>
          <div class="kpi-label">Tiến Trình Đang Chạy</div>
          <div class="kpi-val" id="kpiTasks" style="color:#34d399">0</div>
        </div>
        <div class="kpi-icon">🚀</div>
      </div>
      <div class="kpi-card">
        <div>
          <div class="kpi-label">Tổng Tin Nhắn Đã Gửi</div>
          <div class="kpi-val" id="kpiSent" style="color:#22d3ee">0</div>
        </div>
        <div class="kpi-icon">⚡</div>
      </div>
      <div class="kpi-card">
        <div>
          <div class="kpi-label"> Kho File Đã Lưu</div>
          <div class="kpi-val" id="kpiFiles" style="color:#fbbf24">0</div>
        </div>
        <div class="kpi-icon">📁</div>
      </div>
    </section>

    <div class="workspace-grid">
      <!-- LEFT COLUMN: ACCOUNTS & FILES & PERMISSIONS -->
      <div>
        <!-- CARD 1: ADD & MANAGE ACCOUNTS (ZALO + DISCORD ACC CHÍNH CHỦ) -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">👤 1. Quản Lý Tài Khoản (Zalo & Discord Chính Chủ)</div>
            <span class="badge badge-cyan">24/7 Listener</span>
          </div>

          <div class="plat-switch">
            <button type="button" id="tabZalo" class="plat-btn active-zalo" onclick="switchPlatform('zalo')">
              🔵 Zalo (IMEI + Cookie)
            </button>
            <button type="button" id="tabDiscord" class="plat-btn" onclick="switchPlatform('discord')">
              🟣 Discord (Acc Chính Chủ / Bot)
            </button>
          </div>

          <input type="hidden" id="accPlatform" value="zalo">

          <div style="margin-bottom:9px">
            <label>Tên gợi nhớ (Tùy chọn)</label>
            <input type="text" id="accName" placeholder="Để trống hệ thống tự lấy tên thật của tài khoản...">
          </div>

          <!-- ZALO INPUTS -->
          <div id="zaloFields">
            <div style="margin-bottom:9px">
              <label>IMEI Zalo Web</label>
              <input type="text" id="accImei" placeholder="Dán chuỗi IMEI Zalo...">
            </div>
            <div style="margin-bottom:9px">
              <label>Cookies Zalo (JSON Object hoặc chuỗi Cookie)</label>
              <textarea id="accCookies" rows="3" placeholder='{"zpw_sek":"..."} hoặc dán thẳng Cookie...'></textarea>
            </div>
          </div>

          <!-- DISCORD INPUTS (DEFAULT TO ACC CHÍNH CHỦ USER TOKEN) -->
          <div id="discordFields" style="display:none">
            <div style="margin-bottom:9px">
              <label>Token Discord (Hỗ trợ thẳng Token Acc Chính Chủ hoặc Bot)</label>
              <input type="password" id="accToken" placeholder="Dán trực tiếp Token Acc Chính Chủ Discord vào đây...">
            </div>
            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 11px;background:var(--bg-input);border-radius:10px;border:1px solid var(--border);margin-bottom:9px">
              <span style="font-size:0.8rem;color:#cbd5e1;font-weight:600">Chế độ tài khoản Discord:</span>
              <select id="accIsBot" style="width:auto;padding:5px 10px;font-size:0.8rem">
                <option value="0" selected>👑 Acc Chính Chủ (User Token - Khuyên dùng)</option>
                <option value="1">🤖 Discord Bot Token</option>
              </select>
            </div>
          </div>

          <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:11px;padding:8px 11px;background:var(--bg-input);border-radius:10px;border:1px solid var(--border)">
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.8rem">
              <input type="checkbox" id="accChatCmd" checked> Bật gõ lệnh 24/7 trên chat (.menu, .nhay...)
            </label>
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.8rem;color:#fbbf24">
              <input type="checkbox" id="accAllowAll"> Cho mọi người cùng dùng lệnh
            </label>
          </div>

          <button type="button" class="btn btn-primary btn-block" onclick="addAccount()">
            ➕ LƯU TÀI KHOẢN & KÍCH HOẠT 24/7
          </button>

          <div style="margin-top:14px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px">
              <span style="font-size:0.78rem;color:var(--text-sub);font-weight:700">DANH SÁCH TÀI KHOẢN ĐÃ LƯU</span>
              <button class="btn btn-ghost btn-sm" onclick="loadAccounts(true)">🔄 Làm mới</button>
            </div>
            <div id="accListBox" class="scroll-box" style="max-height:245px"></div>
          </div>
        </div>

        <!-- CARD 2: MULTI-MB FILE STORAGE (AUTO STRIP 1., 2. NUMBERS) -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">📁 2. Kho File .TXT (Tự Xoá Số Thứ Tự 1. 2. Đầu Dòng)</div>
            <span class="badge badge-gold">Tải Siêu Tốc</span>
          </div>

          <div class="dropzone" onclick="document.getElementById('fileInput').click()"
               ondragover="event.preventDefault()" ondrop="handleDropFile(event)">
            <div style="font-size:1.4rem;margin-bottom:4px">📤</div>
            <div style="font-weight:700;font-size:0.86rem;color:#e2e8f0">Nhấn để chọn hoặc kéo thả nhiều file .txt vào đây</div>
            <div style="font-size:0.75rem;color:var(--text-sub);margin-top:2px">
              Tự động lọc bỏ số thứ tự đầu dòng (1., 2., 3.) khi chạy Nhây • Gõ .file 1 hoặc .nhay 1 trên chat là chạy ngay
            </div>
            <input type="file" id="fileInput" multiple accept=".txt" style="display:none" onchange="uploadFiles(this.files)">
          </div>

          <div id="uploadStatus" style="font-size:0.78rem;color:#34d399;margin-bottom:8px;display:none"></div>
          <div id="fileListBox" class="scroll-box" style="max-height:230px"></div>
        </div>

        <!-- CARD 3: AUTHORIZED USERS (.chophep @Tên) -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">🔑 3. Phân Quyền Người Được Phép Dùng Lệnh Chat</div>
            <span class="badge badge-indigo">Chống Loạn Box</span>
          </div>
          <div style="font-size:0.77rem;color:var(--text-sub);margin-bottom:10px">
            Mặc định <b>chỉ mình chủ Acc</b> mới dùng được lệnh (<code>.menu</code>, <code>.nhay</code>, <code>.spam</code>). Muốn cấp quyền cho người khác, gõ <code>.chophep @Tên</code> trong chat hoặc thêm UID bên dưới:
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr auto;gap:6px;margin-bottom:10px">
            <input type="text" id="authUidInput" placeholder="UID Zalo/Discord...">
            <input type="text" id="authNameInput" placeholder="Tên người dùng...">
            <button class="btn btn-indigo btn-sm" onclick="addAuthUserWeb()">+ Cấp quyền</button>
          </div>
          <div id="authUserBox" class="scroll-box" style="max-height:150px"></div>
        </div>
      </div>

      <!-- RIGHT COLUMN: TARGET BOXES, REAL TAGS, CAMPAIGN LAUNCHER & LIVE MONITOR -->
      <div>
        <!-- CARD 4: SELECT BOXES & REAL @TAG (ZALO + DISCORD ALL BOX) -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">🎯 4. Chọn Box Chat (Zalo & All Box Discord) + Tag Thật 100%</div>
            <span class="badge badge-green" id="selectedBoxBadge">Đã chọn: 0 box</span>
          </div>

          <div style="display:grid;grid-template-columns:1fr auto;gap:8px;margin-bottom:10px">
            <div>
              <label>Chọn tài khoản để lấy danh sách Box / Nhóm / Bạn bè</label>
              <select id="groupAccSelect" onchange="onAccountSelectChange()"></select>
            </div>
            <div style="display:flex;align-items:flex-end;gap:6px;flex-wrap:wrap">
              <button class="btn btn-cyan btn-sm" onclick="fetchZaloGroups()">📂 Lấy Nhóm Zalo</button>
              <button class="btn btn-ghost btn-sm" onclick="fetchZaloFriends()">👥 Bạn Bè Zalo</button>
              <button class="btn btn-indigo btn-sm" onclick="fetchDiscordAllBoxes()">🟣 Lấy All Box Discord (DM + Nhóm + Server)</button>
            </div>
          </div>

          <!-- Thanh công cụ chọn nhanh 2-5 box -->
          <div style="display:flex;gap:7px;flex-wrap:wrap;align-items:center;margin-bottom:9px">
            <input type="text" id="boxSearchInput" placeholder="🔍 Tìm tên nhóm, bạn bè, kênh Discord hoặc nhập ID..."
                   oninput="renderTargetBoxes()" style="flex:1;min-width:190px;padding:7px 11px;font-size:0.82rem">
            <button class="btn btn-gold btn-sm" onclick="selectTopBoxes(3)">⚡ Chọn 3 Box</button>
            <button class="btn btn-gold btn-sm" onclick="selectTopBoxes(5)">⚡ Chọn 5 Box</button>
            <button class="btn btn-ghost btn-sm" onclick="toggleAllBoxes(true)">Chọn hết</button>
            <button class="btn btn-ghost btn-sm" onclick="toggleAllBoxes(false)">Bỏ chọn</button>
          </div>

          <!-- Nhập ID thủ công nếu muốn -->
          <div style="display:flex;gap:6px;margin-bottom:10px">
            <input type="text" id="manualBoxId" placeholder="Nhập thêm ID Box Zalo hoặc Channel ID Discord thủ công..." style="padding:7px 11px;font-size:0.81rem">
            <select id="manualBoxType" style="width:165px;padding:7px;font-size:0.8rem">
              <option value="group">Nhóm Zalo</option>
              <option value="user">Bạn bè Zalo</option>
              <option value="discord_channel">Box / Kênh Discord</option>
            </select>
            <button class="btn btn-ghost btn-sm" onclick="addManualBox()">+ Thêm Box</button>
          </div>

          <div id="targetBoxContainer" class="scroll-box" style="max-height:220px;margin-bottom:12px">
            <div style="text-align:center;color:var(--text-sub);padding:18px;font-size:0.83rem">
              Hãy chọn tài khoản rồi bấm <b>Lấy Nhóm Zalo</b> hoặc <b>Lấy All Box Discord</b>.
            </div>
          </div>

          <!-- KHU VỰC TAG THẬT 100% (@TÊN & @ALL CHO ZALO VÀ DISCORD) -->
          <div style="background:var(--bg-input);border:1px solid var(--border);border-radius:12px;padding:12px">
            <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:8px">
              <div style="font-size:0.84rem;font-weight:800;color:#67e8f9">
                🏷️ Tag Tên Thật 100% (Hiện Thẻ Xanh Dương Chuẩn Chat Zalo & Mention Discord)
              </div>
              <div style="display:flex;gap:8px;align-items:center">
                <label style="display:flex;align-items:center;gap:5px;margin:0;cursor:pointer;font-size:0.8rem;color:#fbbf24">
                  <input type="checkbox" id="tagAllCheck"> Tag @All / @everyone
                </label>
                <button class="btn btn-cyan btn-sm" onclick="loadMembersOfSelectedBox()">🔄 Tải Thành Viên Để Tag</button>
              </div>
            </div>

            <div style="display:flex;gap:6px;margin-bottom:7px">
              <input type="text" id="memberSearchInput" placeholder="🔍 Lọc nhanh tên thành viên cần Tag..."
                     oninput="renderMemberTags()" style="padding:6px 10px;font-size:0.8rem">
              <button class="btn btn-ghost btn-sm" onclick="toggleAllMembers(true)">Tag Hết</button>
              <button class="btn btn-ghost btn-sm" onclick="toggleAllMembers(false)">Bỏ Tag</button>
            </div>

            <div id="memberTagContainer" class="scroll-box" style="max-height:145px">
              <div style="text-align:center;color:var(--text-sub);padding:10px;font-size:0.79rem">
                Chọn 1 nhóm Zalo hoặc Box Discord ở trên rồi bấm <b>"Tải Thành Viên Để Tag"</b> (Hoặc gõ thẳng <code>@Tên</code> ở cuối câu lệnh).
              </div>
            </div>
          </div>
        </div>
"""


HTML_INDEX_PART2 = """
        <!-- CARD 5: CAMPAIGN CONFIG & LIVE COLOR / CHỮ TO / DELAY TUNER -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">🚀 5. Khởi Chạy Chiến Dịch & Chỉnh Màu Chữ / Chữ To / Delay</div>
            <span class="badge badge-gold">Hỗ Trợ 2-5+ Box Cùng Lúc</span>
          </div>

          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-bottom:12px">
            <div>
              <label>Chế độ chạy</label>
              <select id="taskMode">
                <option value="treo_nhay" selected>🔥 Treo Nhây (Gửi từng dòng - Tự xoá số 1., 2. đầu dòng)</option>
                <option value="treo_ngon">📜 Treo Ngôn (Gửi nguyên khối văn bản nhiều dòng)</option>
                <option value="fast">⚡ Spam Tốc Độ Cao (Lặp nhanh liên tục)</option>
              </select>
            </div>
            <div>
              <label>Chọn File .TXT theo Số Thứ Tự (1, 2, 3...)</label>
              <select id="taskFileSelect" onchange="onFileSelectChange()">
                <option value="">-- Hoặc tự nhập nội dung bên dưới --</option>
              </select>
            </div>
          </div>

          <div style="margin-bottom:11px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
              <label style="margin:0">Nội dung tin nhắn (Hoặc tự động nạp từ File số 1, 2, 3...)</label>
              <span style="font-size:0.74rem;color:#34d399;font-weight:700">
                Gõ @Tên hoặc @All ở cuối nội dung để Tag Thật 100% liên tục!
              </span>
            </div>
            <textarea id="taskRawText" rows="4" placeholder="Nhập nội dung... (Nếu có dòng '1. Nội dung', '2. Nội dung' hệ thống sẽ tự động xoá '1.', '2.' và chỉ gửi phần chữ phía sau)"></textarea>
          </div>

          <!-- CẤU HÌNH ĐỔI MÀU CHỮ & CHỮ TO & DELAY & ICON VIP -->
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:11px">
            <div>
              <label>Chế Độ Đổi Màu Chữ</label>
              <select id="colorMode" onchange="toggleFixedColorSwatches()">
                <option value="rainbow" selected>🌈 Phối Màu Từng Dòng (Không trùng)</option>
                <option value="word_rainbow">✨ Phối Màu Từng Từ</option>
                <option value="random">🎲 Ngẫu Nhiên (Không trùng)</option>
                <option value="fixed">🎨 Khóa Cố Định 1 Màu</option>
                <option value="none">⚪ Tắt Đổi Màu</option>
              </select>
            </div>
            <div>
              <label>Độ Trễ Delay (Giây)</label>
              <input type="number" id="taskDelay" value="1.0" min="0.2" max="120" step="0.1">
            </div>
            <div>
              <label>Số Icon Chuẩn Zalo VIP</label>
              <input type="number" id="iconCount" value="3" min="0" max="10" step="1">
            </div>
          </div>

          <!-- BẢNG CHỌN MÀU CỐ ĐỊNH -->
          <div id="fixedColorBox" style="display:none;margin-bottom:11px;padding:9px 12px;background:var(--bg-input);border-radius:10px;border:1px solid var(--border)">
            <label style="margin-bottom:4px">Chọn Màu Cố Định Chuẩn Rich-Text Zalo & ANSI Discord:</label>
            <input type="hidden" id="fixedColorVal" value="red">
            <div class="swatch-bar">
              <div class="swatch-pill active" data-c="red" onclick="pickSwatch('red',this)">
                <span class="dot" style="background:#db342e"></span> Đỏ Rực (#db342e)
              </div>
              <div class="swatch-pill" data-c="yellow" onclick="pickSwatch('yellow',this)">
                <span class="dot" style="background:#f7b503"></span> Vàng Hoàng Kim (#f7b503)
              </div>
              <div class="swatch-pill" data-c="green" onclick="pickSwatch('green',this)">
                <span class="dot" style="background:#15a85f"></span> Xanh Ngọc Lục (#15a85f)
              </div>
              <div class="swatch-pill" data-c="orange" onclick="pickSwatch('orange',this)">
                <span class="dot" style="background:#f27806"></span> Cam Rực Lửa (#f27806)
              </div>
            </div>
          </div>

          <!-- CÁC CHECKBOX TÍNH NĂNG CAO CẤP -->
          <div style="display:flex;gap:14px;flex-wrap:wrap;padding:10px 12px;background:var(--bg-input);border:1px solid var(--border);border-radius:11px;margin-bottom:12px">
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.81rem;color:#34d399">
              <input type="checkbox" id="chkStripNum" checked> ✂️ Tự xoá số thứ tự đầu dòng (<code>1.</code>, <code>2.</code>)
            </label>
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.81rem;color:#67e8f9">
              <input type="checkbox" id="chkBigText" checked> 🔠 Chữ To In Đậm Zalo (<code>f_18</code>)
            </label>
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.81rem">
              <input type="checkbox" id="chkUseEmoji" checked> 😎 Gắn Icon Chuẩn Zalo Có Hiệu Ứng VIP
            </label>
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.81rem">
              <input type="checkbox" id="chkAntiband" checked> 🛡️ Anti-Ban Zero-Shift
            </label>
            <label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;font-size:0.81rem">
              <input type="checkbox" id="chkMultiAcc" checked> 👥 Đa Tài Khoản Song Song
            </label>
          </div>

          <div style="display:grid;grid-template-columns:2fr 1fr;gap:10px">
            <button type="button" class="btn btn-primary" style="font-size:0.93rem;padding:12px" onclick="startCampaign()">
              🚀 KHỞI CHẠY NGAY (CHẠY MƯỢT 2-5+ BOX)
            </button>
            <button type="button" class="btn btn-cyan" onclick="applyLiveConfig()">
              ⚡ CẬP NHẬT NÓNG DELAY/MÀU
            </button>
          </div>
        </div>

        <!-- CARD 6: ACTIVE TASKS & 24/7 IN-CHAT COMMAND LOGS -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">📡 6. Giám Sát Tiến Trình & Nhật Ký Lệnh Khung Chat 24/7</div>
            <div style="display:flex;gap:6px">
              <button class="btn btn-ghost btn-sm" onclick="clearStoppedTasks()">🧹 Dọn Task Dừng</button>
              <button class="btn btn-danger btn-sm" onclick="stopAllTasks()">⏹ Dừng Tất Cả</button>
            </div>
          </div>

          <div id="activeTasksBox" class="scroll-box" style="max-height:220px;margin-bottom:14px"></div>

          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px">
            <span style="font-size:0.79rem;font-weight:800;color:#67e8f9">
              💬 NHẬT KÝ LỆNH GÕ TRÊN KHUNG CHAT ZALO & DISCORD (.menu, .nhay, .spam, .file...)
            </span>
            <button class="btn btn-ghost btn-sm" onclick="clearBotLogs()">Xóa log</button>
          </div>
          <div id="botLogsBox" class="scroll-box" style="max-height:175px"></div>
        </div>
      </div>
    </div>
  </div>

  <script>
    // ============================================================
    // SMART DOM DIFFING (CHỐNG ĐƠ GIAO DIỆN & KHÔNG BAO GIỜ RESET DROPDOWN)
    // ============================================================
    let ALL_ACCOUNTS = [];
    let ALL_FILES = [];
    let LOADED_BOXES = [];
    let SELECTED_BOX_MAP = {};
    let LOADED_MEMBERS = [];
    let SELECTED_MEMBER_MAP = {};
    let LAST_ACC_SELECT_SIG = "";
    let LAST_FILE_SELECT_SIG = "";

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

    function toast(msg, isErr = false) {
      const box = document.getElementById("toastBox");
      const d = document.createElement("div");
      d.className = "toast-item";
      if (isErr) d.style.borderLeftColor = "#ef4444";
      d.textContent = msg;
      box.appendChild(d);
      setTimeout(() => { d.remove(); }, 3200);
    }

    function switchPlatform(plat) {
      document.getElementById("accPlatform").value = plat;
      const zBtn = document.getElementById("tabZalo");
      const dBtn = document.getElementById("tabDiscord");
      const zFields = document.getElementById("zaloFields");
      const dFields = document.getElementById("discordFields");
      if (plat === "zalo") {
        zBtn.className = "plat-btn active-zalo";
        dBtn.className = "plat-btn";
        zFields.style.display = "block";
        dFields.style.display = "none";
      } else {
        zBtn.className = "plat-btn";
        dBtn.className = "plat-btn active-discord";
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
      document.querySelectorAll(".swatch-pill").forEach(p => p.classList.remove("active"));
      el.classList.add("active");
    }

    // 1. QUẢN LÝ TÀI KHOẢN (ZALO & DISCORD CHÍNH CHỦ)
    async function loadAccounts(force = false) {
      try {
        const r = await fetch("/api/accounts");
        const d = await r.json();
        ALL_ACCOUNTS = d.accounts || [];
        document.getElementById("kpiAccounts").textContent = ALL_ACCOUNTS.length;

        const box = document.getElementById("accListBox");
        if (!ALL_ACCOUNTS.length) {
          setHtmlIfChanged(box, `<div style="text-align:center;color:var(--text-sub);padding:14px;font-size:0.81rem">Chưa có tài khoản nào. Hãy thêm Zalo hoặc Discord Chính Chủ ở trên.</div>`);
        } else {
          const html = ALL_ACCOUNTS.map(a => {
            const isZalo = (a.platform || "zalo") === "zalo";
            const platBadge = isZalo
              ? `<span class="badge badge-cyan">ZALO</span>`
              : `<span class="badge badge-indigo">${a.is_bot ? "DISCORD BOT" : "DISCORD CHÍNH CHỦ"}</span>`;
            const cmdOn = a.chat_cmd_enabled ? "🟢 24/7 Bật" : "⚪ Tắt";
            const modePerm = a.allow_all_cmd ? "Mọi người" : "Chỉ Chủ Acc";
            return `
              <div class="list-item">
                <div style="min-width:0;flex:1">
                  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
                    ${platBadge}
                    <b style="font-size:0.85rem;color:#fff">${esc(a.name)}</b>
                  </div>
                  <div style="font-size:0.73rem;color:var(--text-sub);margin-top:3px">
                    ${esc(a.ws_status || "Sẵn sàng")} • Quyền lệnh: <b>${modePerm}</b>
                  </div>
                </div>
                <div style="display:flex;gap:5px;flex-wrap:wrap">
                  <button class="btn btn-ghost btn-sm" onclick="toggleAccCmd(${a.id})" title="Bật/Tắt nhận lệnh chat 24/7">${cmdOn}</button>
                  <button class="btn btn-ghost btn-sm" onclick="toggleAllowAll(${a.id})" title="Đổi chế độ Chỉ Chủ Acc / Mọi Người">🔒</button>
                  <button class="btn btn-danger btn-sm" onclick="deleteAccount(${a.id})">✕</button>
                </div>
              </div>
            `;
          }).join("");
          setHtmlIfChanged(box, html);
        }

        // Chỉ cập nhật dropdown tài khoản khi danh sách ID thực sự thay đổi để không bao giờ làm đơ dropdown đang mở!
        const sig = ALL_ACCOUNTS.map(a => `${a.id}:${a.platform}:${a.name}`).join("|");
        if (force || sig !== LAST_ACC_SELECT_SIG) {
          LAST_ACC_SELECT_SIG = sig;
          const sel = document.getElementById("groupAccSelect");
          const prevVal = sel.value;
          sel.innerHTML = ALL_ACCOUNTS.length
            ? ALL_ACCOUNTS.map(a => `<option value="${a.id}">[${(a.platform || "zalo").toUpperCase()}] ${esc(a.name)}</option>`).join("")
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

      toast("⏳ Đang xác thực và kết nối tài khoản...");
      try {
        const r = await fetch("/api/accounts", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({platform, name, imei, cookies, token, is_bot, chat_cmd_enabled, allow_all_cmd})
        });
        const d = await r.json();
        if (!d.ok) return toast(d.error || "Lỗi thêm tài khoản", true);
        toast(`✅ Đã kết nối: ${d.name}`);
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

    // 2. QUẢN LÝ FILE .TXT (TỰ XOÁ SỐ 1., 2. ĐẦU DÒNG)
    async function loadFiles(force = false) {
      try {
        const r = await fetch("/api/files");
        const d = await r.json();
        ALL_FILES = d.files || [];
        document.getElementById("kpiFiles").textContent = ALL_FILES.length;

        const box = document.getElementById("fileListBox");
        if (!ALL_FILES.length) {
          setHtmlIfChanged(box, `<div style="text-align:center;color:var(--text-sub);padding:14px;font-size:0.8rem">Chưa có file nào. Hãy tải file .txt lên ở trên.</div>`);
        } else {
          const html = ALL_FILES.map(f => `
            <div class="list-item">
              <div style="min-width:0;flex:1">
                <div style="display:flex;align-items:center;gap:6px">
                  <span class="badge badge-gold">Số ${f.display_num}</span>
                  <b style="font-size:0.84rem;color:#f8fafc;word-break:break-all">${esc(f.filename)}</b>
                </div>
                <div style="font-size:0.73rem;color:var(--text-sub);margin-top:2px">
                  ${f.lines_count} dòng sạch (Đã tự lọc số thứ tự đầu dòng) • Gõ <code>.nhay ${f.display_num}</code> trên chat
                </div>
              </div>
              <div style="display:flex;gap:5px">
                <button class="btn btn-cyan btn-sm" onclick="useFileNow(${f.id})">Nạp</button>
                <button class="btn btn-danger btn-sm" onclick="deleteFile(${f.id})">✕</button>
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
          sel.innerHTML = `<option value="">-- Tự nhập nội dung bên dưới --</option>` +
            ALL_FILES.map(f => `<option value="${f.display_num}">File số ${f.display_num}: ${esc(f.filename)} (${f.lines_count} dòng)</option>`).join("");
          if (prev) sel.value = prev;
        }
      } catch (e) {}
    }

    function handleDropFile(ev) {
      ev.preventDefault();
      if (ev.dataTransfer && ev.dataTransfer.files.length) {
        uploadFiles(ev.dataTransfer.files);
      }
    }

    async function uploadFiles(fileList) {
      if (!fileList || !fileList.length) return;
      const st = document.getElementById("uploadStatus");
      st.style.display = "block";
      st.textContent = `⏳ Đang tải lên ${fileList.length} file & tự lọc bỏ số thứ tự đầu dòng (1., 2.)...`;

      const fd = new FormData();
      for (let i = 0; i < fileList.length; i++) {
        fd.append("file", fileList[i]);
      }

      try {
        const r = await fetch("/api/upload_file", {method: "POST", body: fd});
        const d = await r.json();
        if (!d.ok) {
          st.textContent = "❌ " + (d.error || "Lỗi tải file");
          return;
        }
        st.textContent = `✅ Đã lưu ${d.uploaded.length} file thành công!`;
        toast(`Đã tải lên ${d.uploaded.length} file (Đã tự xoá số 1., 2. đầu dòng)`);
        await loadFiles(true);
        if (d.uploaded.length === 1) {
          useFileNow(d.uploaded[0].id);
        }
      } catch (e) {
        st.textContent = "❌ Lỗi kết nối khi tải file";
      }
    }

    async function useFileNow(fid) {
      try {
        const r = await fetch(`/api/file_preview/${fid}`);
        const d = await r.json();
        if (d.ok) {
          document.getElementById("taskFileSelect").value = String(d.display_num);
          document.getElementById("taskRawText").value = d.preview_text || "";
          toast(`Đã nạp File số ${d.display_num}: ${d.filename} (Đã lọc sạch số đầu dòng)`);
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

    // 3. QUẢN LÝ PHÂN QUYỀN (.chophep)
    async function loadAuthUsers() {
      try {
        const r = await fetch("/api/authorized_users");
        const d = await r.json();
        const users = d.users || [];
        const box = document.getElementById("authUserBox");
        if (!users.length) {
          setHtmlIfChanged(box, `<div style="text-align:center;color:var(--text-sub);padding:10px;font-size:0.78rem">Hiện chỉ mình chủ Acc dùng được lệnh.</div>`);
        } else {
          const html = users.map(u => `
            <div class="list-item" style="padding:6px 10px">
              <div style="font-size:0.8rem"><b>${esc(u.name)}</b> <span style="color:var(--text-sub)">(${esc(u.uid)})</span></div>
              <button class="btn btn-danger btn-sm" onclick="delAuthUserWeb('${esc(u.uid)}')">Xóa</button>
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

    // 4. LẤY BOX ZALO & ALL BOX DISCORD (DM + NHÓM + SERVER) + TAG THẬT 100%
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
      toast("⏳ Đang tải toàn bộ Nhóm Zalo siêu tốc...");
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
      toast("⏳ Đang quét TẤT CẢ Box Discord (Chat Riêng DM + Box Nhóm + Kênh Server)...");
      try {
        const r = await fetch(`/api/account_groups/${aid}?type=discord_all`);
        const d = await r.json();
        if (!d.ok) return toast(d.error || "Lỗi tải All Box Discord", true);
        LOADED_BOXES = d.groups || [];
        renderTargetBoxes();
        toast(`✅ Đã tải ${LOADED_BOXES.length} Box & Kênh Chat Discord!`);
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
        box.innerHTML = `<div style="text-align:center;color:var(--text-sub);padding:14px;font-size:0.82rem">Không tìm thấy Box phù hợp.</div>`;
        return;
      }

      box.innerHTML = filtered.map(g => {
        const isChecked = !!SELECTED_BOX_MAP[g.id];
        const tBadge = g.type === "discord_channel"
          ? `<span class="badge badge-indigo">DISCORD</span>`
          : (g.type === "group" ? `<span class="badge badge-cyan">NHÓM ZALO</span>` : `<span class="badge badge-green">BẠN BÈ</span>`);
        const memInfo = g.members ? ` • ${g.members} TV` : "";
        return `
          <label class="list-item" style="cursor:pointer;margin-bottom:6px">
            <div style="display:flex;align-items:center;gap:8px;min-width:0;flex:1">
              <input type="checkbox" ${isChecked ? "checked" : ""}
                     onchange='toggleBoxSelection(${JSON.stringify(String(g.id))}, ${JSON.stringify(g.name)}, ${JSON.stringify(g.type)}, this.checked)'>
              ${tBadge}
              <span style="font-weight:700;font-size:0.84rem;color:#fff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(g.name)}</span>
            </div>
            <span style="font-size:0.72rem;color:var(--text-sub)">ID: ${esc(String(g.id).slice(-6))}${memInfo}</span>
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
      toast(`⚡ Đã chọn nhanh ${Object.keys(SELECTED_BOX_MAP).length} Box để chạy song song!`);
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
      const item = {id, name: `Box_${id.slice(-6)}`, type};
      LOADED_BOXES.unshift(item);
      SELECTED_BOX_MAP[id] = item;
      document.getElementById("manualBoxId").value = "";
      renderTargetBoxes();
      toast(`Đã thêm & chọn Box ID: ${id}`);
    }

    async function loadMembersOfSelectedBox() {
      const aid = document.getElementById("groupAccSelect").value;
      const selectedList = Object.values(SELECTED_BOX_MAP);
      if (!aid || !selectedList.length) {
        return toast("Hãy tích chọn ít nhất 1 Nhóm Zalo hoặc Box Discord trước!", true);
      }
      const targetBox = selectedList[0];
      toast(`⏳ Đang tải danh sách thành viên của ${targetBox.name}...`);
      try {
        const r = await fetch(`/api/group_members/${aid}/${targetBox.id}`);
        const d = await r.json();
        if (!d.ok) return toast(d.error || "Không lấy được thành viên", true);
        LOADED_MEMBERS = d.members || [];
        renderMemberTags();
        toast(`✅ Đã tải ${LOADED_MEMBERS.length} thành viên để Tag Thật 100%!`);
      } catch (e) {
        toast("Lỗi tải thành viên", true);
      }
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
        box.innerHTML = `<div style="text-align:center;color:var(--text-sub);padding:10px;font-size:0.78rem">Không tìm thấy thành viên.</div>`;
        return;
      }

      box.innerHTML = filtered.map(m => {
        const isChecked = !!SELECTED_MEMBER_MAP[m.id];
        return `
          <label class="list-item" style="cursor:pointer;padding:6px 10px;margin-bottom:5px">
            <div style="display:flex;align-items:center;gap:8px">
              <input type="checkbox" ${isChecked ? "checked" : ""}
                     onchange='toggleMemberTag(${JSON.stringify(String(m.id))}, ${JSON.stringify(m.name)}, this.checked)'>
              <span style="font-size:0.82rem;font-weight:700;color:#67e8f9">@${esc(m.name)}</span>
            </div>
            <span style="font-size:0.72rem;color:var(--text-sub)">UID: ${esc(String(m.id).slice(-6))}</span>
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
      if (!targets.length) return toast("Hãy tích chọn ít nhất 1 Box Chat ở mục 4!", true);

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
        toast(`🚀 Đã khởi chạy trên ${targets.length} Box song song!`);
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
      if (d.ok) toast(`⚡ Đã cập nhật nóng cho ${d.updated} tiến trình đang chạy!`);
    }

    // 6. GIÁM SÁT TIẾN TRÌNH & LOG LỆNH 24/7
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
          setHtmlIfChanged(box, `<div style="text-align:center;color:var(--text-sub);padding:14px;font-size:0.8rem">Chưa có tiến trình nào.</div>`);
          return;
        }

        const html = tasks.map(t => {
          const isRun = t.status === "running";
          const stBadge = isRun
            ? `<span class="badge badge-green">🟢 ĐANG CHẠY</span>`
            : `<span class="badge badge-red">⏹ ĐÃ DỪNG</span>`;
          const meta = t.meta || {};
          const sent = (t.stats && t.stats.sent) ? t.stats.sent : 0;
          const names = (meta.target_names || []).join(", ") || "Box Chat";
          return `
            <div class="list-item">
              <div style="min-width:0;flex:1">
                <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
                  ${stBadge}
                  <b style="font-size:0.84rem;color:#fff">[${esc(t.type)}] ${esc(names)}</b>
                  <span class="badge badge-cyan">Đã gửi: ${sent} tin</span>
                </div>
                <div style="font-size:0.73rem;color:var(--text-sub);margin-top:2px">
                  Nguồn: <b>${meta.source === "chat" ? "Gõ lệnh trong Chat" : "Web UI"}</b> • Delay: ${meta.delay || 1}s • Màu: ${esc(meta.color_mode || "rainbow")}
                </div>
              </div>
              ${isRun ? `<button class="btn btn-danger btn-sm" onclick="stopTask('${esc(t.id)}')">Dừng</button>` : ""}
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
      toast("⏹ Đã dừng tất cả tiến trình!");
      loadTasks();
    }

    async function clearStoppedTasks() {
      await fetch("/api/clear_tasks", {method: "POST"});
      loadTasks();
    }

    async function loadBotLogs() {
      try {
        const r = await fetch("/api/bot_logs");
        const d = await r.json();
        const logs = d.logs || [];
        const box = document.getElementById("botLogsBox");
        if (!logs.length) {
          setHtmlIfChanged(box, `<div style="text-align:center;color:var(--text-sub);padding:10px;font-size:0.78rem">Gõ .menu hoặc .nhay @Tên trong khung chat Zalo / Discord để xem lịch sử phản hồi tại đây.</div>`);
          return;
        }
        const html = logs.map(l => `
          <div class="list-item" style="padding:7px 10px;margin-bottom:5px">
            <div style="min-width:0;flex:1">
              <div style="font-size:0.8rem;color:#67e8f9;font-weight:700">${esc(l.cmd_text)}</div>
              <div style="font-size:0.73rem;color:#cbd5e1">${esc(l.action_taken)} • Box: ${esc(String(l.thread_id).slice(-6))}</div>
            </div>
            <span style="font-size:0.7rem;color:var(--text-sub)">${esc(l.time_str)}</span>
          </div>
        `).join("");
        setHtmlIfChanged(box, html);
      } catch (e) {}
    }

    async function clearBotLogs() {
      await fetch("/api/clear_bot_logs", {method: "POST"});
      loadBotLogs();
    }

    // KHỞI ĐỘNG HỆ THỐNG MƯỢT MÀ
    window.addEventListener("DOMContentLoaded", () => {
      loadAccounts(true);
      loadFiles(true);
      loadAuthUsers();
      loadTasks();
      loadBotLogs();

      // Chu kỳ cập nhật nhẹ nhàng với Smart DOM Diffing (không bao giờ gây giật/đơ)
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
# ROUTES XÁC THỰC & API ĐIỀU KHIỂN — FLASK BACKEND v7.0 ULTRA
# ============================================================
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
    if not ok_ip:
        err_html = f'<div style="color:#f87171;margin-bottom:10px;font-size:0.82rem">Tạm khóa {wait_s}s do nhập sai nhiều lần.</div>'
        return HTML_GATE.replace("__ERR_BLOCK__", err_html)

    if request.method == "POST":
        k = (request.form.get("key") or "").strip()
        if hmac.compare_digest(k, ACCESS_KEY):
            record_login_Result(ip, True)
            session["gate_passed"] = True
            return redirect("/login")
        record_login_Result(ip, False)
        err_html = '<div style="color:#f87171;margin-bottom:10px;font-size:0.82rem">Mã khóa truy cập không chính xác!</div>'
        return HTML_GATE.replace("__ERR_BLOCK__", err_html)

    return HTML_GATE.replace("__ERR_BLOCK__", "")


@app.route("/login", methods=["GET", "POST"])
def route_login():
    if not session.get("gate_passed"):
        return redirect("/gate")

    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = (request.form.get("password") or "").strip()
        conn = db()
        row = conn.execute("SELECT * FROM users WHERE username = ?", (u,)).fetchone()
        conn.close()
        if row and verify_password_secure(row["password"], p):
            session["user"] = u
            return redirect("/")
        msg = '<div style="color:#f87171;margin-bottom:10px;font-size:0.82rem">Sai tài khoản hoặc mật khẩu!</div>'
        return HTML_LOGIN.replace("__MSG_BLOCK__", msg)

    return HTML_LOGIN.replace("__MSG_BLOCK__", "")


@app.route("/register", methods=["POST"])
def route_register():
    if not session.get("gate_passed"):
        return redirect("/gate")
    u = (request.form.get("username") or "").strip()
    p = (request.form.get("password") or "").strip()
    if not u or not p:
        return redirect("/login")
    conn = db()
    try:
        conn.execute(
            "INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
            (u, hash_password_secure(p), time.time())
        )
        conn.commit()
        session["user"] = u
        conn.close()
        return redirect("/")
    except Exception:
        conn.close()
        msg = '<div style="color:#fbbf24;margin-bottom:10px;font-size:0.82rem">Tên tài khoản đã tồn tại!</div>'
        return HTML_LOGIN.replace("__MSG_BLOCK__", msg)


@app.route("/logout")
def route_logout():
    session.clear()
    return redirect("/gate")


@app.route("/")
@login_required
def route_index():
    return HTML_INDEX.replace("__USER__", session.get("user", "Admin"))


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
            d.pop("cookies", None)
            d.pop("token", None)
            listener = ACTIVE_LISTENERS.get(d["id"])
            d["ws_status"] = listener.ws_status if listener else ("🟢 Sẵn sàng" if d.get("chat_cmd_enabled") else "⚪ Tắt")
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
            return jsonify({"ok": True, "name": real_name, "uid": z.uid})
        except Exception as e:
            return jsonify({"ok": False, "error": f"Lỗi xác thực Zalo: {e}"})
    else:
        token = (data.get("token") or "").strip()
        # Mặc định is_bot = 0 (Acc Chính Chủ Discord)
        is_bot = int(data.get("is_bot", 0))
        if not token:
            return jsonify({"ok": False, "error": "Vui lòng nhập Token Discord (Acc Chính Chủ hoặc Bot)"})
        try:
            dc = DiscordBot(token, is_bot=bool(is_bot))
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
            return jsonify({"ok": True, "name": real_name, "uid": dc.user_id, "is_bot": actual_is_bot})
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
            # Mặc định lấy TẤT CẢ Box Discord (Chat Riêng DM + Box Nhóm Group DM + Kênh Server)
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
        # Tự động làm sạch số thứ tự đầu dòng (1., 2., 3.) ngay khi lưu file để chế độ Nhây chỉ lấy nội dung
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
