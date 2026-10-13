# ============================================================
# Bản quyền thuộc về Phạm Anh Khôi
# Hệ thống điều hành: ALB Forge — Phiên Bản Giáng Sinh (Noel Edition Pro v4.0)
# Hỗ trợ Đa Nền Tảng: Zalo & Discord | Tích hợp Anti-Ban Đa Tầng & Anti-Die-All
# Tích hợp Self-Bot Lắng Nghe Lệnh Trực Tiếp Trên Khung Chat Zalo 24/7
# Tối ưu Tải File Multi-MB Streaming Siêu Tốc & Đổi Màu Chữ Chuẩn Zalo RichText
# ============================================================
import os
import re
import ssl
import zlib
import json
import time
import math
import struct
import socket
import shutil
import hashlib
import sqlite3
import threading
import random
import base64
from urllib.parse import urlparse, unquote
from functools import wraps
from collections import defaultdict, deque

from flask import (
    Flask, render_template_string, request, jsonify,
    session, redirect, url_for, send_from_directory
)
try:
    from Crypto.Cipher import AES
except ImportError:
    from Cryptodome.Cipher import AES
import requests
from requests.adapters import HTTPAdapter

APP_PASSWORD = os.environ.get("APP_PASSWORD", "anhkhoidz")
DATA_DIR = os.environ.get("DATA_DIR", "/tmp/alb_web")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "alb.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "phamanhkhoi-noel-2026-pro")
# Nâng giới hạn upload lên 500MB, xử lý luồng (stream chunking) siêu tốc
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

# ============================================================
# BỘ LỌC BẢO MẬT & CHỐNG TẤN CÔNG DDOS
# ============================================================
DDOS_LIMIT_PER_MINUTE = 240
DDOS_BURST_PER_SEC = 45
LOGIN_MAX_FAILS = 5
LOGIN_LOCKOUT_TIME = 900

ip_request_history = defaultdict(list)
ip_blocked_until = {}
login_fail_tracker = defaultdict(lambda: {"count": 0, "locked_until": 0})
security_lock = threading.Lock()


def get_client_ip():
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


@app.before_request
def security_shield_middleware():
    if request.path.startswith("/static") or request.endpoint == "static_files":
        return

    ip = get_client_ip()
    now = time.time()

    with security_lock:
        if ip in ip_blocked_until:
            if now < ip_blocked_until[ip]:
                return jsonify({
                    "error": "IP đang bị tạm khóa kết nối để bảo vệ an toàn hệ thống.",
                    "retry_after": int(ip_blocked_until[ip] - now)
                }), 429
            else:
                del ip_blocked_until[ip]

        history = [t for t in ip_request_history[ip] if now - t < 60]
        ip_request_history[ip] = history

        burst = sum(1 for t in history if now - t <= 1.0)
        if burst > DDOS_BURST_PER_SEC or len(history) > DDOS_LIMIT_PER_MINUTE:
            ip_blocked_until[ip] = now + 180
            return jsonify({"error": "Phát hiện lưu lượng bất thường. Đã tạm khóa kết nối 3 phút."}), 429

        ip_request_history[ip].append(now)

    if not session.get("human_verified") and request.endpoint not in ("verify_gate", "api_verify_human"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Chưa hoàn tất kiểm tra an toàn danh tính"}), 403
        return redirect(url_for("verify_gate"))


# ============================================================
# CƠ SỞ DỮ LIỆU SQLITE (TỐI ƯU WAL MODE CHỐNG NGHẼN)
# ============================================================
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA cache_size=-32000;")
    except Exception:
        pass
    return conn


def init_db():
    conn = db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT DEFAULT 'zalo',
            label TEXT,
            imei TEXT,
            cookies TEXT,
            token TEXT DEFAULT '',
            is_bot INTEGER DEFAULT 1,
            ok_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            risk REAL DEFAULT 0.0,
            enabled INTEGER DEFAULT 1,
            chat_cmd_enabled INTEGER DEFAULT 1,
            allow_all_cmd INTEGER DEFAULT 0,
            cmd_prefix TEXT DEFAULT '.',
            added_at REAL,
            last_used REAL DEFAULT 0,
            total_sent INTEGER DEFAULT 0,
            uid TEXT,
            display_name TEXT,
            zalo_name TEXT,
            username TEXT,
            status TEXT DEFAULT 'unknown'
        )
    """)
    for col_sql in [
        "ALTER TABLE accounts ADD COLUMN platform TEXT DEFAULT 'zalo'",
        "ALTER TABLE accounts ADD COLUMN token TEXT DEFAULT ''",
        "ALTER TABLE accounts ADD COLUMN is_bot INTEGER DEFAULT 1",
        "ALTER TABLE accounts ADD COLUMN chat_cmd_enabled INTEGER DEFAULT 1",
        "ALTER TABLE accounts ADD COLUMN allow_all_cmd INTEGER DEFAULT 0",
        "ALTER TABLE accounts ADD COLUMN cmd_prefix TEXT DEFAULT '.'",
    ]:
        try:
            c.execute(col_sql)
        except Exception:
            pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            type TEXT,
            meta TEXT,
            status TEXT,
            started_at REAL,
            stats TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            filepath TEXT,
            lines INTEGER DEFAULT 0,
            total_lines INTEGER DEFAULT 0,
            size INTEGER DEFAULT 0,
            uploaded_at REAL
        )
    """)
    try:
        c.execute("ALTER TABLE files ADD COLUMN total_lines INTEGER DEFAULT 0")
    except Exception:
        pass

    c.execute("""
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

ACTIVE_TASKS = {}
ACTIVE_LISTENERS = {}


def new_tid(p):
    return f"{p}_{int(time.time() * 1000)}_{random.randint(100, 999)}"


def utf16_len(s):
    if not s:
        return 0
    return len(s.encode("utf-16-le")) // 2


# ============================================================
# BỘ ĐỆM TẢI FILE DUNG LƯỢNG LỚN (MULTI-MB STREAMING ENGINE)
# ============================================================
FILE_MEMORY_CACHE = {}
FILE_CACHE_LOCK = threading.Lock()


def parse_file_stream_fast(filepath):
    """Đọc tệp văn bản dung lượng lớn (nhiều MB) theo luồng bộ đệm 1MB,
    tách cả khối ngôn (blocks) và từng dòng đơn (lines) mà không giới hạn 5.000 dòng,
    tốc độ xử lý hàng trăm nghìn dòng dưới 0.1 giây."""
    if not os.path.exists(filepath):
        return {"blocks": [], "lines": [], "size": 0}

    st = os.stat(filepath)
    mtime = st.st_mtime
    fsize = st.st_size

    with FILE_CACHE_LOCK:
        cached = FILE_MEMORY_CACHE.get(filepath)
        if cached and cached["mtime"] == mtime and cached["size"] == fsize:
            return cached

    blocks = []
    all_lines = []
    current_block = []

    with open(filepath, "rb") as f:
        raw_bytes = f.read()

    text = raw_bytes.decode("utf-8", errors="ignore").replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = text.split("\n")

    for ln in raw_lines:
        stripped = ln.strip()
        if stripped:
            all_lines.append(stripped)
            current_block.append(ln.rstrip())
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
        "block_count": len(blocks),
        "line_count": len(all_lines),
    }

    with FILE_CACHE_LOCK:
        if len(FILE_MEMORY_CACHE) > 25:
            oldest_key = next(iter(FILE_MEMORY_CACHE))
            FILE_MEMORY_CACHE.pop(oldest_key, None)
        FILE_MEMORY_CACHE[filepath] = result

    return result


def get_blocks_from_file_id(fid, mode="fast"):
    conn = db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    conn.close()
    if not row:
        return []
    parsed = parse_file_stream_fast(row["filepath"])
    if mode == "treo_nhay":
        return parsed["lines"] if parsed["lines"] else parsed["blocks"]
    return parsed["blocks"]


def find_file_by_query(query_str):
    """Tìm file theo ID hoặc tên gần đúng (dùng cho lệnh trực tiếp trên khung chat Zalo)."""
    q = str(query_str or "").strip()
    if not q:
        return None
    conn = db()
    if q.isdigit():
        row = conn.execute("SELECT * FROM files WHERE id = ?", (int(q),)).fetchone()
        if row:
            conn.close()
            return dict(row)
    rows = conn.execute("SELECT * FROM files ORDER BY id DESC").fetchall()
    conn.close()
    q_low = q.lower()
    for r in rows:
        if r["filename"].lower() == q_low or q_low in r["filename"].lower():
            return dict(r)
    return dict(rows[0]) if rows and q_low in ("auto", "default", "moinhat", "latest") else None


# ============================================================
# HỆ THỐNG ANTI-BAN ĐA TẦNG & ANTI-DIE-ALL CHẤT LƯỢNG CAO
# ============================================================
ZERO_WIDTH_POOL = ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"]
INVISIBLE_SPACE_VARIANTS = [" ", " \u200b", "\u200b ", " \u200c"]


def _encode_invisible_salt(seed_int):
    """Mã hóa số nguyên thành chuỗi nhị phân ký tự tàng hình Zero-Width độc nhất."""
    bits = bin(seed_int & 0xFFFF)[2:].zfill(16)
    return "".join("\u200b" if b == "0" else "\u200c" for b in bits)


def apply_antiband(text, level=2):
    """Hệ thống Anti-Ban Zalo & Discord Đa Tầng (Polymorphic Hash Obfuscator):
    - Tầng 1: Biến thiên khoảng trắng và chèn Zero-Width ngẫu nhiên vào giữa các từ,
      phá vỡ hoàn toàn bộ lọc Regex/Substring và kiểm tra trùng lặp nội dung (Duplicate Filter).
    - Tầng 2: Gắn chữ ký vi phân tàng hình (Invisible Micro-Salt) dựa trên xung nhịp thời gian thực
      ở cuối câu giúp mỗi tin nhắn gửi đi có mã băm SHA-256/MD5 khác biệt 100%.
    - Tầng 3: Bảo toàn nguyên vẹn cấu trúc hiển thị chữ và vị trí UTF-16 cho @Mention & Màu sắc."""
    if not text:
        return text

    out_lines = []
    for line in text.split("\n"):
        if not line.strip():
            out_lines.append(line)
            continue
        words = line.split(" ")
        mutated_words = []
        for idx, w in enumerate(words):
            # Không chèn ký tự lạ vào token @mention hoặc mã lệnh
            if w.startswith("@") or w.startswith("#") or len(w) <= 2:
                mutated_words.append(w)
                continue
            if random.random() < (0.48 if level >= 2 else 0.30):
                cut = random.randint(1, len(w) - 1)
                zw = random.choice(ZERO_WIDTH_POOL)
                w = w[:cut] + zw + w[cut:]
            if len(w) > 5 and level >= 2 and random.random() < 0.25:
                cut2 = random.randint(2, len(w) - 1)
                w = w[:cut2] + random.choice(ZERO_WIDTH_POOL) + w[cut2:]
            mutated_words.append(w)

        joined = ""
        for idx, mw in enumerate(mutated_words):
            if idx == 0:
                joined = mw
            else:
                sep = random.choice(INVISIBLE_SPACE_VARIANTS) if random.random() < 0.35 else " "
                joined += sep + mw
        out_lines.append(joined)

    salt_seed = (int(time.time() * 1000) ^ random.randint(1, 65535)) & 0xFFFF
    invisible_tail = _encode_invisible_salt(salt_seed)
    return "\n".join(out_lines) + invisible_tail


class AntiDieAllEngine:
    """Hệ thống Anti-Die-All Thế Hệ Mới (Circuit Breaker + Sliding Window Token Bucket + Auto-Recovery):
    - Giám sát sức khỏe từng tài khoản theo 3 trạng thái:
      1. CLOSED (Bình thường - Xanh): Cho phép gửi với tốc độ tối ưu.
      2. HALF_OPEN (Thăm dò - Vàng): Vừa hết thời gian cách ly, giảm nhịp độ gửi để kiểm tra an toàn.
      3. OPEN (Cách ly bảo vệ - Đỏ): Phát hiện Rate Limit (429 / mã lỗi Zalo spam) hoặc lỗi liên tiếp,
         lập tức ngắt tải tài khoản đó theo thuật toán Exponential Backoff + Jitter.
    - Tự động điều tiết nhịp độ toàn cục (Global Fleet Shield) khi phát hiện máy chủ Zalo/Discord siết băng thông."""

    ZALO_RATELIMIT_CODES = {-2, -108, -112, 112, 114, 300, 301, 429, 500, 1001}
    ZALO_AUTH_CODES = {-401, 401, -102, 102, -30, -13}

    def __init__(self):
        self.lock = threading.Lock()
        self.state = defaultdict(lambda: {
            "circuit": "CLOSED",          # CLOSED | HALF_OPEN | OPEN
            "cooldown_until": 0.0,
            "fail_streak": 0,
            "ratelimit_streak": 0,
            "ok_total": 0,
            "fail_total": 0,
            "risk_score": 0.0,            # 0.0 -> 100.0
            "last_error": "",
            "last_active": 0.0,
            "timestamps": deque(maxlen=120),  # Sliding window 60s
            "adaptive_delay_bonus": 0.0,
        })
        self.global_cooldown_until = 0.0

    def can_send(self, acc_id, max_rpm=52):
        now = time.time()
        with self.lock:
            if now < self.global_cooldown_until:
                return False, round(self.global_cooldown_until - now, 1)

            st = self.state[acc_id]
            if st["circuit"] == "OPEN":
                if now < st["cooldown_until"]:
                    return False, round(st["cooldown_until"] - now, 1)
                else:
                    # Chuyển sang trạng thái thăm dò nhẹ nhàng
                    st["circuit"] = "HALF_OPEN"
                    st["adaptive_delay_bonus"] = max(0.8, st["adaptive_delay_bonus"])

            # Làm sạch cửa sổ trượt 60 giây
            while st["timestamps"] and now - st["timestamps"][0] > 60.0:
                st["timestamps"].popleft()

            # Giới hạn RPM thông minh để tránh bị Zalo khóa mõm (chặn gửi tin)
            rpm = len(st["timestamps"])
            effective_limit = max_rpm if st["circuit"] == "CLOSED" else max(12, max_rpm // 2)
            if rpm >= effective_limit:
                wait_s = max(1.0, 60.0 - (now - st["timestamps"][0]) + random.uniform(0.3, 1.2))
                return False, round(wait_s, 1)

            # Kiểm tra xung đột burst 2 giây gần nhất (không quá 5 tin/2s trên 1 tài khoản)
            recent_2s = sum(1 for t in st["timestamps"] if now - t <= 2.0)
            if recent_2s >= 5:
                return False, round(random.uniform(0.6, 1.4), 1)

            return True, 0.0

    def get_adaptive_delay(self, acc_id, base_delay, antiband=True):
        with self.lock:
            st = self.state[acc_id]
            bonus = st["adaptive_delay_bonus"]
            risk = st["risk_score"]

        d = float(base_delay) + bonus + (risk * 0.015)
        if antiband:
            # Phân phối nhiễu nhân sinh học (Human Cadence Jitter)
            jitter = abs(random.gauss(0.18, 0.12))
            if random.random() < 0.08:
                # 8% cơ hội nghỉ nhịp ngắn giống người thật đang gõ phím
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
            st["adaptive_delay_bonus"] = max(0.0, st["adaptive_delay_bonus"] * 0.85 - 0.05)
            st["risk_score"] = max(0.0, st["risk_score"] - 1.5)

    def report_rate_limit(self, acc_id, retry_after=None, reason="Rate Limit 429"):
        now = time.time()
        with self.lock:
            st = self.state[acc_id]
            st["ratelimit_streak"] += 1
            st["fail_total"] += 1
            st["last_error"] = reason
            streak = min(st["ratelimit_streak"], 6)
            base_cd = float(retry_after) if retry_after else (12.0 * (1.8 ** (streak - 1)))
            cooldown = min(300.0, max(10.0, base_cd + random.uniform(2.0, 7.5)))
            st["circuit"] = "OPEN"
            st["cooldown_until"] = now + cooldown
            st["adaptive_delay_bonus"] = min(4.0, st["adaptive_delay_bonus"] + 0.65)
            st["risk_score"] = min(100.0, st["risk_score"] + 22.0)

            # Kiểm tra nếu nhiều tài khoản cùng bị Rate Limit -> Kích hoạt lá chắn toàn cục
            open_count = sum(1 for v in self.state.values() if v["circuit"] == "OPEN" and v["cooldown_until"] > now)
            if open_count >= 2 and len(self.state) >= 2 and open_count >= len(self.state) * 0.6:
                self.global_cooldown_until = max(self.global_cooldown_until, now + random.uniform(4.0, 8.0))

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
                st["risk_score"] = min(100.0, st["risk_score"] + 45.0)
            elif st["fail_streak"] >= 3:
                backoff = min(180.0, 15.0 * (2 ** min(st["fail_streak"] - 3, 4)) + random.uniform(1.0, 5.0))
                st["circuit"] = "OPEN"
                st["cooldown_until"] = now + backoff
                st["adaptive_delay_bonus"] = min(3.5, st["adaptive_delay_bonus"] + 0.4)
                st["risk_score"] = min(100.0, st["risk_score"] + 15.0)
            else:
                st["risk_score"] = min(100.0, st["risk_score"] + 5.0)

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
            out = {}
            for k in list(self.state.keys()):
                st = self.state[k]
                while st["timestamps"] and now - st["timestamps"][0] > 60.0:
                    st["timestamps"].popleft()
                rem = max(0, int(st["cooldown_until"] - now)) if st["circuit"] == "OPEN" else 0
                out[k] = {
                    "circuit": st["circuit"] if rem > 0 or st["circuit"] != "OPEN" else "HALF_OPEN",
                    "cooldown_remaining": rem,
                    "ok_total": st["ok_total"],
                    "fail_total": st["fail_total"],
                    "rpm": len(st["timestamps"]),
                    "risk_score": round(st["risk_score"], 1),
                    "last_error": st["last_error"]
                }
            return out


HEALTH_MGR = AntiDieAllEngine()


# ============================================================
# BẢNG MÀU CHUẨN ZALO RICH-TEXT (VER: 0) & DISCORD ANSI
# ============================================================
ZALO_PALETTE = [
    {"id": "red",    "name": "Đỏ Noel",        "hex": "#db342e", "zcode": "db342e", "ansi": "31"},
    {"id": "yellow", "name": "Vàng Kim Tuyến", "hex": "#f7b503", "zcode": "f7b503", "ansi": "33"},
    {"id": "green",  "name": "Xanh Thông",     "hex": "#15a85f", "zcode": "15a85f", "ansi": "32"},
    {"id": "orange", "name": "Cam Lửa",        "hex": "#f27806", "zcode": "f27806", "ansi": "33"},
    {"id": "ocean",  "name": "Xanh Tuyết",     "hex": "#0091ff", "zcode": "0091ff", "ansi": "36"},
    {"id": "blue",   "name": "Xanh Đêm",       "hex": "#0068ff", "zcode": "0068ff", "ansi": "34"},
    {"id": "purple", "name": "Tím Pha Lê",     "hex": "#6f38c5", "zcode": "6f38c5", "ansi": "35"},
    {"id": "pink",   "name": "Hồng Đào",       "hex": "#e03e96", "zcode": "e03e96", "ansi": "35"},
]

RAINBOW_ZCODES = [c["zcode"] for c in ZALO_PALETTE]
ZALO_COLOR_MAP = {c["id"]: c["zcode"] for c in ZALO_PALETTE}

ZALO_ICON_HARD = [
    ";-A", ":-bd", "/-punch", "/-shit", "/-weak",
    ":-DIG", "8-|", ";-!", ":-t", "=d>", ":q",
    ";f", ":d", "=))", "b-)", ":-R", ":-L", ":-F",
    "x-)", ":v", ":3", ":>", ":$", ";)p", ";;)",
    ":p", ":-p", ":-d", "8-)", ":-*", ":-h", ":-?",
    ":-s", ":-x", ":x", ":-o", ":o", ":-|", ":|",
    "/-no", "/-bad", "/-li", "/-strong", "/-fade",
    "/-bome", "/-bd", "/-break", ">-)", "p-(", ":--|"
]

ZALO_ICON_UNICODE = [
    "😏", "🤡", "💩", "🖕", "👊", "💀", "🤣", "🤪",
    "🤦", "💢", "☠️", "🗿", "😆", "🙄", "😒", "😑",
    "😹", "😈", "🔥", "😤", "🤮", "🤢", "🐒", "✌️", "☝️", "😁"
]


def get_icon_hard():
    if random.random() < 0.65:
        return random.choice(ZALO_ICON_HARD)
    return random.choice(ZALO_ICON_UNICODE)


# Bộ nhớ đệm thành viên nhóm để phân giải @Tên nhanh chóng
GROUP_MEMBERS_CACHE = {}
GROUP_CACHE_LOCK = threading.Lock()


# ============================================================
# CLIENT GIAO THỨC ZALO (CHUẨN HÓA ĐỔI MÀU CHỮ & LẮNG NGHE LỆNH)
# ============================================================
class Zalo:
    def __init__(self, imei, cookies):
        self.imei = str(imei).strip()
        self.cookies_dict = cookies if isinstance(cookies, dict) else json.loads(cookies)
        self.s = requests.Session()
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=40, max_retries=2)
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
            raise Exception("Phiên đăng nhập hết hạn hoặc Cookie không hợp lệ")
        self.uid = str(ud.get("send2me_id") or ud.get("uid") or "")
        self.secret_key = ud.get("zpw_enk")
        self.display_name = ud.get("displayName") or ud.get("zaloName")
        self.zalo_name = ud.get("zaloName")
        self.username = ud.get("username")
        ws_raw = ud.get("zpw_ws") or []
        if isinstance(ws_raw, list):
            self.ws_urls = ws_raw
        elif isinstance(ws_raw, str):
            self.ws_urls = [ws_raw]
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
        dec = self._dec(r.json()["data"])
        grid = json.loads(dec).get("data", {}).get("gridVerMap", {})
        out = []
        for gid in grid:
            try:
                info = self.group_info(gid)
                out.append({
                    "id": str(gid),
                    "name": info["name"],
                    "type": "group",
                    "members": info["totalMember"]
                })
            except Exception:
                continue
        return out

    def get_grid_ver_map(self):
        """Lấy bản đồ phiên bản nhóm nhanh để phát hiện tin nhắn mới."""
        r = self.s.get(
            "https://tt-group-wpa.chat.zalo.me/api/group/getlg/v4",
            params={"zpw_ver": 645, "zpw_type": 30}, timeout=12,
        )
        dec = self._dec(r.json().get("data", ""))
        return json.loads(dec).get("data", {}).get("gridVerMap", {})

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
            return [{
                "id": str(u.get("userId")),
                "name": u.get("displayName") or u.get("zaloName") or f"Bạn_{str(u.get('userId'))[-6:]}",
                "type": "user"
            } for u in users if u.get("userId")]
        except Exception:
            return []

    def get_members_full(self, gid, use_cache=True):
        gid_str = str(gid)
        if use_cache:
            with GROUP_CACHE_LOCK:
                c = GROUP_MEMBERS_CACHE.get(gid_str)
                if c and time.time() - c["ts"] < 300:
                    return c["members"]

        enc = self._enc({"gridVerMap": json.dumps({gid_str: 0})})
        r = self.s.post(
            "https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2",
            params={"zpw_ver": 645, "zpw_type": 30},
            data={"params": enc}, timeout=20,
        )
        dec = self._dec(r.json()["data"])
        info = json.loads(dec).get("data", {}).get("gridInfoMap", {}).get(gid_str, {})

        members_dict = {}
        mem_info_list = info.get("memInfoList", [])
        if isinstance(mem_info_list, list):
            for m in mem_info_list:
                if isinstance(m, dict):
                    uid = str(m.get("userId") or m.get("id") or "")
                    name = (m.get("dName") or m.get("displayName") or m.get("name") or m.get("zaloName") or "").strip()
                    if uid and name:
                        members_dict[uid] = name

        mem_ver_list = info.get("memVerList", [])
        uids = [m.split("_")[0] for m in mem_ver_list if m]
        missing_uids = [u for u in uids if u not in members_dict]

        if missing_uids:
            for chunk in [missing_uids[i:i + 50] for i in range(0, len(missing_uids), 50)]:
                try:
                    enc2 = self._enc({"grid": gid_str, "userIds": chunk, "friendId": chunk})
                    r2 = self.s.post(
                        "https://tt-group-wpa.chat.zalo.me/api/group/getuserinfo",
                        params={"zpw_ver": 645, "zpw_type": 30},
                        data={"params": enc2}, timeout=18,
                    )
                    dec2 = self._dec(r2.json()["data"])
                    profiles_data = json.loads(dec2).get("data", {})
                    profiles = profiles_data.get("profiles", {}) if isinstance(profiles_data, dict) else {}
                    for uid in chunk:
                        p = profiles.get(uid, {})
                        pname = (p.get("displayName") or p.get("zaloName") or p.get("username") or "").strip()
                        if pname:
                            members_dict[uid] = pname
                except Exception:
                    pass

        out = []
        for uid in uids:
            real_name = members_dict.get(uid) or f"Người dùng {uid[-6:]}"
            out.append({"id": str(uid), "uid": str(uid), "name": real_name})

        with GROUP_CACHE_LOCK:
            GROUP_MEMBERS_CACHE[gid_str] = {"ts": time.time(), "members": out}
        return out

    def get_recent_group_messages(self, gid):
        """Lấy danh sách tin nhắn gần nhất trong nhóm Zalo phục vụ cơ chế lắng nghe lệnh HTTP."""
        for ep in (
            "https://tt-group-wpa.chat.zalo.me/api/group/getrecentv2",
            "https://tt-group-wpa.chat.zalo.me/api/group/getrecent",
        ):
            try:
                enc = self._enc({"grid": str(gid), "groupId": str(gid), "imed": 0, "count": 15})
                r = self.s.post(
                    ep,
                    params={"zpw_ver": 645, "zpw_type": 30},
                    data={"params": enc},
                    timeout=10,
                )
                rj = r.json()
                if rj.get("data"):
                    dec = self._dec(rj["data"])
                    parsed = json.loads(dec)
                    data_obj = parsed.get("data") if isinstance(parsed, dict) else {}
                    if isinstance(data_obj, dict):
                        msgs = data_obj.get("groupMsgs") or data_obj.get("msgs") or []
                        if msgs:
                            return msgs
            except Exception:
                continue
        return []

    def _pick_zcode(self, color_mode, fixed_color, index_num):
        if color_mode == "none":
            return None
        if color_mode == "random":
            return random.choice(RAINBOW_ZCODES)
        if color_mode == "fixed" and fixed_color:
            return ZALO_COLOR_MAP.get(fixed_color, "db342e")
        return RAINBOW_ZCODES[index_num % len(RAINBOW_ZCODES)]

    def build_colored_message(self, raw_text, color_mode="rainbow", fixed_color="red",
                              is_heading=True, color_offset=0):
        """Chuẩn hóa cơ chế Đổi Màu Chữ Zalo Rich-Text (params -> styles, ver: 0):
        - Sử dụng định dạng chuẩn Zalo RichText: {"start": pos, "len": len, "st": "b,f_18,c_<hex6>"}
        - Không dùng dấu '#' thô làm xấu nội dung, thay bằng mã font chữ lớn chuẩn Zalo (f_18) + in đậm (b).
        - Hỗ trợ:
          + rainbow: Đổi màu cầu vồng theo từng dòng / đoạn
          + word_rainbow: Đổi màu cầu vồng từng từ một trong câu
          + random: Đổi màu ngẫu nhiên
          + fixed: Giữ cố định 1 màu đã chọn"""
        lines = raw_text.split("\n")
        cleaned_lines = []
        styles = []
        current_u16_pos = 0

        has_blocks = any(ln.strip() == "" for ln in lines)
        block_idx = color_offset

        for i, ln in enumerate(lines):
            stripped = ln.strip()
            if not stripped:
                cleaned_lines.append("")
                current_u16_pos += 1
                if has_blocks:
                    block_idx += 1
                continue

            # Nếu người dùng gõ '# Tiêu đề' ở đầu dòng, bỏ dấu '#' thô và chuyển sang cờ chữ lớn
            force_line_heading = False
            if stripped.startswith("#"):
                stripped = re.sub(r"^#+\s*", "", stripped).strip() or stripped
                force_line_heading = True

            line_text = stripped
            cleaned_lines.append(line_text)
            l_len = utf16_len(line_text)

            use_big_font = is_heading or force_line_heading

            if color_mode == "word_rainbow":
                # Tô màu cầu vồng trên từng từ trong dòng
                words = line_text.split(" ")
                w_offset = current_u16_pos
                w_color_idx = color_offset + i
                for w in words:
                    w_len = utf16_len(w)
                    if w_len > 0:
                        zcode = self._pick_zcode("rainbow", fixed_color, w_color_idx)
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
                        w_color_idx += 1
                    w_offset += w_len + 1
            else:
                color_num = block_idx if has_blocks else (color_offset + i)
                zcode = self._pick_zcode(color_mode, fixed_color, color_num)
                st_parts = []
                if use_big_font:
                    st_parts.extend(["b", "f_18"])
                elif color_mode != "none":
                    st_parts.append("b")
                if zcode:
                    st_parts.append(f"c_{zcode}")

                if st_parts and l_len > 0:
                    styles.append({
                        "start": current_u16_pos,
                        "len": l_len,
                        "st": ",".join(st_parts)
                    })

            current_u16_pos += l_len + 1

        final_msg = "\n".join(cleaned_lines)
        return final_msg, styles

    def attach_mentions(self, msg, mentions=None, tag_all=False, styles=None,
                        color_mode="rainbow", fixed_color="red", is_heading=True, color_offset=0):
        """Gắn @All và @Tên vào cuối nội dung tin nhắn, tính toán chính xác tọa độ UTF-16
        và áp dụng luôn hiệu ứng đổi màu cho cả phần @Mention ở cuối."""
        final = msg.rstrip() if msg else ""
        m_arr = []
        if styles is None:
            styles = []

        if tag_all:
            tag_token = "@All"
            pos = utf16_len(final) + (1 if final else 0)
            final = (final + " " + tag_token) if final else tag_token
            t_len = utf16_len(tag_token)
            m_arr.append({
                "uid": "-1",
                "pos": pos,
                "len": t_len,
                "type": 1
            })
            zcode = self._pick_zcode(color_mode, fixed_color, color_offset + 7)
            if zcode or is_heading:
                st_tags = ["b"]
                if is_heading:
                    st_tags.append("f_18")
                if zcode:
                    st_tags.append(f"c_{zcode}")
                styles.append({"start": pos, "len": t_len, "st": ",".join(st_tags)})

        if mentions:
            seen_uids = set()
            for idx, m in enumerate(mentions):
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
                    "uid": uid,
                    "pos": pos,
                    "len": t_len,
                    "type": 0
                })
                zcode = self._pick_zcode(color_mode, fixed_color, color_offset + idx + 3)
                if zcode or is_heading:
                    st_tags = ["b"]
                    if is_heading:
                        st_tags.append("f_18")
                    if zcode:
                        st_tags.append(f"c_{zcode}")
                    styles.append({"start": pos, "len": t_len, "st": ",".join(st_tags)})

        return final, m_arr, styles

    def send_adv(self, raw_text, thread_id, color_mode="rainbow", fixed_color="red",
                 is_group=True, mentions=None, tag_all=False, is_heading=True,
                 color_offset=0, antiband=True):
        url = ("https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
               if is_group
               else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms")

        processed_text = apply_antiband(raw_text) if antiband else raw_text

        final_msg, styles = self.build_colored_message(
            processed_text,
            color_mode=color_mode,
            fixed_color=fixed_color,
            is_heading=is_heading,
            color_offset=color_offset
        )

        final_msg, m_arr, styles = self.attach_mentions(
            final_msg,
            mentions=(mentions if is_group else None),
            tag_all=(tag_all if is_group else False),
            styles=styles,
            color_mode=color_mode,
            fixed_color=fixed_color,
            is_heading=is_heading,
            color_offset=color_offset
        )

        pl = {
            "message": final_msg,
            "clientId": str(int(time.time() * 1000)) + str(random.randint(100, 999)),
            "imei": self.imei,
            "ttl": 0,
        }

        if is_group and m_arr:
            mention_json = json.dumps(m_arr, separators=(",", ":"), ensure_ascii=False)
            pl["mentionInfo"] = mention_json
            pl["mentions"] = mention_json

        # QUAN TRỌNG: Zalo Web/PC/Mobile đọc màu chữ & kiểu chữ từ pl["params"] = '{"styles":[...],"ver":0}'
        if styles:
            params_json = json.dumps({"styles": styles, "ver": 0}, separators=(",", ":"), ensure_ascii=False)
            pl["params"] = params_json
            pl["textProperties"] = params_json

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

        # Kiểm tra phản hồi thực tế của Zalo để kích hoạt Anti-Die-All chính xác
        if r.status_code == 429:
            raise Exception("429:RateLimit:30")
        try:
            resp_json = r.json()
            err_code = resp_json.get("error_code", 0)
            if err_code in AntiDieAllEngine.ZALO_RATELIMIT_CODES:
                raise Exception(f"429:RateLimit:25:ZaloCode_{err_code}")
            if err_code in AntiDieAllEngine.ZALO_AUTH_CODES:
                # Thử tự động làm mới khóa giải mã 1 lần
                self._login()
                raise Exception(f"AuthError:ZaloCode_{err_code}")
            if resp_json.get("data"):
                dec_resp = json.loads(self._dec(resp_json["data"]))
                inner_err = dec_resp.get("error_code", 0)
                if inner_err in AntiDieAllEngine.ZALO_RATELIMIT_CODES:
                    raise Exception(f"429:RateLimit:25:ZaloInner_{inner_err}")
        except Exception as check_ex:
            if "429:RateLimit" in str(check_ex) or "AuthError" in str(check_ex):
                raise check_ex

        return r


# ============================================================
# BỘ PHÂN TÍCH TAG CUỐI CÂU LỆNH (@TÊN & @ALL) TỰ ĐỘNG
# ============================================================
def extract_trailing_tags_and_resolve(raw_text, incoming_mentions=None, zalo_client=None, group_id=None):
    """Bóc tách thông minh @All hoặc @Tên ở cuối nội dung / câu lệnh:
    - Nếu tin nhắn có sẵn metadata mentions từ Zalo (khi người dùng gõ @ và chọn tên trong khung chat),
      hệ thống lấy chính xác UID và tên của những người được tag ở cuối câu.
    - Nếu người dùng gõ chữ '@All' hoặc '@TênNgườiĐó' ở cuối nội dung (trên cả Web hoặc trong khung chat),
      hệ thống tự động dò danh sách thành viên nhóm để khớp UID thật và cắt phần @Tên thừa khỏi gốc câu,
      để tự động lặp lại việc tag người đó / @All liên tục cho đến khi bấm dừng."""
    if not raw_text:
        return "", [], False

    text = raw_text.strip()
    resolved_mentions = []
    tag_all = False

    # 1. Kiểm tra metadata mentions từ sự kiện tin nhắn Zalo
    if incoming_mentions and isinstance(incoming_mentions, list):
        sorted_m = sorted(incoming_mentions, key=lambda x: int(x.get("pos", 0)), reverse=True)
        for m in sorted_m:
            uid = str(m.get("uid") or m.get("id") or "")
            mtype = int(m.get("type", 0))
            pos = int(m.get("pos", -1))
            mlen = int(m.get("len", 0))
            if uid == "-1" or mtype == 1:
                tag_all = True
                continue
            if uid and uid != "0":
                m_name = str(m.get("name") or "").strip().lstrip("@")
                if not m_name and pos >= 0 and mlen > 0:
                    try:
                        u16_bytes = text.encode("utf-16-le")
                        sub = u16_bytes[pos * 2:(pos + mlen) * 2].decode("utf-16-le", errors="ignore")
                        m_name = sub.strip().lstrip("@")
                    except Exception:
                        pass
                if not m_name and zalo_client and group_id:
                    try:
                        mems = zalo_client.get_members_full(group_id)
                        found = next((x for x in mems if str(x["id"]) == uid), None)
                        if found:
                            m_name = found["name"]
                    except Exception:
                        pass
                resolved_mentions.append({"uid": uid, "id": uid, "name": m_name or f"User_{uid[-4:]}"})

    # 2. Kiểm tra chuỗi @All / @all / @tất cả ở cuối văn bản
    all_pattern = re.compile(r"(?:\s+|^)(?:@all|@tất\s*cả|@tat\s*ca|@mọi\s*người|@everyone)\s*$", re.IGNORECASE)
    while True:
        m_all = all_pattern.search(text)
        if not m_all:
            break
        tag_all = True
        text = text[:m_all.start()].rstrip()

    # 3. Kiểm tra cú pháp @Tên ở cuối văn bản (hỗ trợ cả tên có khoảng trắng hoặc nhiều @Tên ở cuối)
    if zalo_client and group_id and "@" in text:
        try:
            members = zalo_client.get_members_full(group_id)
        except Exception:
            members = []

        if members:
            # Sắp xếp tên thành viên từ dài xuống ngắn để khớp chính xác tên đầy đủ ở cuối câu
            sorted_members = sorted(members, key=lambda x: len(x.get("name", "")), reverse=True)
            changed = True
            while changed:
                changed = False
                text_low = text.lower().rstrip()
                for mem in sorted_members:
                    mname = (mem.get("name") or "").strip()
                    if not mname:
                        continue
                    token_low = "@" + mname.lower()
                    if text_low.endswith(token_low):
                        cut_pos = len(text_low) - len(token_low)
                        if cut_pos == 0 or text_low[cut_pos - 1].isspace():
                            if not any(x["uid"] == str(mem["id"]) for x in resolved_mentions):
                                resolved_mentions.append({
                                    "uid": str(mem["id"]),
                                    "id": str(mem["id"]),
                                    "name": mname
                                })
                            text = text[:cut_pos].rstrip()
                            changed = True
                            break

            # Nếu vẫn còn @TênNgắn ở cuối (người dùng gõ tên rút gọn, ví dụ @Khôi thay vì @Phạm Anh Khôi)
            tail_at_match = re.search(r"(?:\s+|^)@([^\s@][^@]{0,35})$", text)
            if tail_at_match:
                partial_name = tail_at_match.group(1).strip().lower()
                if partial_name in ("all", "tất cả", "tat ca", "everyone"):
                    tag_all = True
                    text = text[:tail_at_match.start()].rstrip()
                else:
                    matched_mem = next(
                        (m for m in sorted_members if partial_name in m.get("name", "").lower()),
                        None
                    )
                    if matched_mem:
                        if not any(x["uid"] == str(matched_mem["id"]) for x in resolved_mentions):
                            resolved_mentions.append({
                                "uid": str(matched_mem["id"]),
                                "id": str(matched_mem["id"]),
                                "name": matched_mem["name"]
                            })
                        text = text[:tail_at_match.start()].rstrip()

    # Nếu đã lấy được mention từ metadata Zalo và cuối câu vẫn còn dính @Tên của người đó thì cắt gọn
    for rm in resolved_mentions:
        rname = rm.get("name", "").strip()
        if rname and text.lower().endswith("@" + rname.lower()):
            text = text[:-(len(rname) + 1)].rstrip()

    resolved_mentions.reverse()
    return text.strip(), resolved_mentions, tag_all


# ============================================================
# CLIENT GIAO THỨC DISCORD (BOT & USER TOKEN)
# ============================================================
class DiscordBot:
    def __init__(self, token, is_bot=True):
        self.token = str(token).strip()
        self.is_bot = is_bot
        self.s = requests.Session()
        auth_header = f"Bot {self.token}" if self.is_bot else self.token
        self.s.headers.update({
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0.0.0 Safari/537.36" if not self.is_bot
                           else "DiscordBot (ALBForgeNoel, 4.0.0)")
        })
        self.user_id = None
        self.username = None
        self.display_name = None

    def check(self):
        r = self.s.get("https://discord.com/api/v10/users/@me", timeout=12)
        if r.status_code == 200:
            d = r.json()
            self.user_id = d.get("id")
            self.username = d.get("username")
            self.display_name = d.get("global_name") or d.get("username")
            return True
        return False

    def get_guilds(self):
        try:
            r = self.s.get("https://discord.com/api/v10/users/@me/guilds", timeout=15)
            if r.status_code == 200:
                return [{"id": str(g["id"]), "name": g.get("name", "Server"), "type": "discord_guild"} for g in r.json()]
        except Exception:
            pass
        return []

    def get_channels(self, guild_id):
        try:
            r = self.s.get(f"https://discord.com/api/v10/guilds/{guild_id}/channels", timeout=15)
            if r.status_code == 200:
                channels = r.json()
                return [{"id": str(c["id"]), "name": "# " + c.get("name", "channel"), "type": "discord_channel"}
                        for c in channels if c.get("type") in (0, 5)]
        except Exception:
            pass
        return []

    def send_message(self, channel_id, content, color_mode="none", fixed_color=None, antiband=True):
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        msg_text = apply_antiband(content) if antiband else content

        DISCORD_ANSI_CODES = {
            "red": "31", "green": "32", "yellow": "33", "orange": "33",
            "blue": "34", "purple": "35", "ocean": "36", "pink": "35"
        }

        if color_mode != "none":
            if color_mode in ("rainbow", "word_rainbow", "random"):
                code = random.choice(["31", "32", "33", "34", "35", "36"])
            else:
                code = DISCORD_ANSI_CODES.get(fixed_color, "31")
            formatted_content = f"```ansi\n\u001b[1;{code}m{msg_text}\u001b[0m\n```"
            pl = {"content": formatted_content}
        else:
            pl = {"content": msg_text}

        r = self.s.post(url, json=pl, timeout=15)
        if r.status_code == 429:
            retry_after = r.json().get("retry_after", 10)
            raise Exception(f"429:RateLimit:{retry_after}")
        if r.status_code not in (200, 201):
            raise Exception(f"HTTP {r.status_code}: {r.text[:100]}")
        return r.json()


# ============================================================
# WORKER ĐA NỀN TẢNG & XỬ LÝ TAG CUỐI CÂU LỆNH LIÊN TỤC
# ============================================================
def single_acc_worker(acc_dict, targets, blocks, delay, use_emoji, icon_count,
                      tag_users, tag_all, is_heading, mode, color_mode, fixed_color,
                      stop_ev, counter, lock, antiband=True, antidieall=True):
    acc_id = acc_dict["id"]
    plat = acc_dict.get("platform") or "zalo"

    client = None
    if plat == "zalo":
        imei = acc_dict["imei"]
        try:
            cookies = json.loads(acc_dict["cookies"])
            client = Zalo(imei, cookies)
            HEALTH_MGR.report_success(acc_id)
        except Exception as e:
            print(f"[Worker] Lỗi đăng nhập Zalo #{acc_id}: {e}")
            HEALTH_MGR.report_error(acc_id, str(e), is_auth_error=True)
            return
    else:
        token = acc_dict["token"]
        try:
            client = DiscordBot(token, is_bot=bool(acc_dict.get("is_bot", 1)))
            if not client.check():
                raise Exception("Token Discord không hợp lệ")
            HEALTH_MGR.report_success(acc_id)
        except Exception as e:
            print(f"[Worker] Lỗi đăng nhập Discord #{acc_id}: {e}")
            HEALTH_MGR.report_error(acc_id, str(e), is_auth_error=True)
            return

    b_idx, t_idx = 0, 0
    color_counter = 0

    # Bộ nhớ đệm bóc tách @Tên / @All ở cuối nội dung cho từng nhóm đích
    target_Parsed_Cache = {}

    while not stop_ev.is_set():
        if not targets or not blocks:
            break

        if antidieall:
            ok_send, wait_sec = HEALTH_MGR.can_send(acc_id)
            if not ok_send:
                stop_ev.wait(min(2.5, max(0.5, wait_sec)))
                continue

        target = targets[t_idx % len(targets)]
        t_idx += 1
        target_type = target.get("type", "group")
        target_id = str(target.get("id"))

        is_discord_target = (target_type == "discord_channel")
        if (plat == "zalo" and is_discord_target) or (plat == "discord" and not is_discord_target):
            if all((plat == "zalo") == (t.get("type") == "discord_channel") for t in targets):
                break
            continue

        is_group = (target_type == "group")
        raw = blocks[b_idx % len(blocks)]
        b_idx += 1

        # Nếu người dùng gõ @Tên hoặc @All ở cuối nội dung trên Web hoặc Lệnh Chat,
        # tự động bóc tách và duy trì tag liên tục người đó / @All đến khi tắt!
        eff_mentions = list(tag_users) if tag_users else []
        eff_tag_all = bool(tag_all)
        clean_raw = raw

        if plat == "zalo" and is_group and ("@" in raw):
            cache_key = (target_id, raw[:120], raw[-80:])
            if cache_key not in target_Parsed_Cache:
                stripped_txt, auto_m, auto_all = extract_trailing_tags_and_resolve(
                    raw, incoming_mentions=None, zalo_client=client, group_id=target_id
                )
                target_Parsed_Cache[cache_key] = (stripped_txt or raw, auto_m, auto_all)
            c_txt, auto_m, auto_all = target_Parsed_Cache[cache_key]
            clean_raw = c_txt
            if auto_all:
                eff_tag_all = True
            for am in auto_m:
                if not any(str(x.get("uid") or x.get("id")) == str(am["uid"]) for x in eff_mentions):
                    eff_mentions.append(am)

        try:
            if mode == "treo_ngon":
                text = clean_raw.replace("\r\n", "\n").replace("\r", "\n")
                if use_emoji and icon_count > 0:
                    text = text + " " + " ".join([get_icon_hard() for _ in range(icon_count)])

                if plat == "zalo":
                    client.send_adv(
                        text, target_id, color_mode=color_mode, fixed_color=fixed_color,
                        is_group=is_group, mentions=(eff_mentions if is_group else None),
                        tag_all=(eff_tag_all if is_group else False), is_heading=is_heading,
                        color_offset=color_counter, antiband=antiband
                    )
                else:
                    client.send_message(
                        target_id, text, color_mode=color_mode,
                        fixed_color=fixed_color, antiband=antiband
                    )

                color_counter += 1
                with lock:
                    counter["sent"] += 1
                HEALTH_MGR.report_success(acc_id)

            elif mode == "treo_nhay":
                lines = [ln.strip() for ln in clean_raw.split("\n") if ln.strip()]
                for ln in lines:
                    if stop_ev.is_set():
                        break
                    if antidieall:
                        ok_s, w_s = HEALTH_MGR.can_send(acc_id)
                        if not ok_s:
                            stop_ev.wait(min(2.0, max(0.4, w_s)))
                            continue

                    msg_line = ln
                    if use_emoji and icon_count > 0:
                        msg_line += " " + " ".join([get_icon_hard() for _ in range(icon_count)])

                    if plat == "zalo":
                        client.send_adv(
                            msg_line, target_id, color_mode=color_mode, fixed_color=fixed_color,
                            is_group=is_group, mentions=(eff_mentions if is_group else None),
                            tag_all=(eff_tag_all if is_group else False), is_heading=is_heading,
                            color_offset=color_counter, antiband=antiband
                        )
                    else:
                        client.send_message(
                            target_id, msg_line, color_mode=color_mode,
                            fixed_color=fixed_color, antiband=antiband
                        )

                    color_counter += 1
                    with lock:
                        counter["sent"] += 1
                    HEALTH_MGR.report_success(acc_id)
                    step_d = HEALTH_MGR.get_adaptive_delay(acc_id, delay, antiband=antiband)
                    stop_ev.wait(max(0.28, step_d))
                continue

            else:
                text = clean_raw
                if use_emoji and icon_count > 0:
                    text = text + " " + " ".join([get_icon_hard() for _ in range(icon_count)])

                if plat == "zalo":
                    client.send_adv(
                        text, target_id, color_mode=color_mode, fixed_color=fixed_color,
                        is_group=is_group, mentions=(eff_mentions if is_group else None),
                        tag_all=(eff_tag_all if is_group else False), is_heading=is_heading,
                        color_offset=color_counter, antiband=antiband
                    )
                else:
                    client.send_message(
                        target_id, text, color_mode=color_mode,
                        fixed_color=fixed_color, antiband=antiband
                    )

                color_counter += 1
                with lock:
                    counter["sent"] += 1
                HEALTH_MGR.report_success(acc_id)

        except Exception as e:
            err_str = str(e)
            print(f"[Worker #{acc_id}] Cảnh báo gửi tin: {err_str}")
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


def task_supervisor(tid, targets, blocks, delay, use_emoji, icon_count,
                    tag_users, tag_all, is_heading, multi_acc, mode, color_mode, fixed_color,
                    stop_ev, antiband=True, antidieall=True, specific_acc_id=None):
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
            target=single_acc_worker,
            args=(
                dict(a), targets, blocks, delay, use_emoji, icon_count,
                tag_users, tag_all, is_heading, mode, color_mode, fixed_color,
                stop_ev, counter, lock, antiband, antidieall
            ),
            daemon=True
        )
        threads.append(t)
        t.start()

    last_db_sync = time.time()
    while not stop_ev.is_set():
        alive = [t for t in threads if t.is_alive()]
        if not alive:
            break
        if time.time() - last_db_sync >= 3.0:
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
        time.sleep(0.8)

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
    """Khởi chạy tiến trình từ cả Giao diện Web hoặc từ Lệnh trực tiếp trong khung chat Zalo."""
    tid = new_tid("cmd" if source_label == "chat" else "task")
    stop_ev = threading.Event()
    tag_users = tag_users or []

    th = threading.Thread(
        target=task_supervisor,
        args=(
            tid, targets, blocks, delay, use_emoji, icon_count,
            tag_users, tag_all, is_heading, multi_acc, mode, color_mode, fixed_color,
            stop_ev, antiband, antidieall, specific_acc_id
        ),
        daemon=True
    )

    meta_info = {
        "source": source_label,
        "multi_acc": multi_acc,
        "color_mode": color_mode,
        "targets": [t.get("id") for t in targets],
        "target_names": [t.get("name", t.get("id")) for t in targets],
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
        "acc_id": specific_acc_id,
        "source": source_label
    }
    th.start()
    return tid


def stop_tasks_for_thread(thread_id=None):
    """Dừng các tiến trình đang chạy trong khung chat cụ thể hoặc toàn bộ."""
    stopped = 0
    for tid, info in list(ACTIVE_TASKS.items()):
        if thread_id is None or str(thread_id) in info.get("targets", []):
            info["stop"].set()
            stopped += 1
    return stopped


# ============================================================
# HỆ THỐNG SELF-BOT LẮNG NGHE LỆNH TRỰC TIẾP TRÊN KHUNG CHAT ZALO 24/7
# (KHÔNG CẦN BẬT WEB - HỖ TRỢ WEBSOCKET + HTTP POLLING ĐA KÊNH)
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


def parse_and_execute_inchat_command(zalo_client, acc_row, thread_id, is_group, sender_id, raw_msg, raw_mentions=None):
    """Trình biên dịch & thực thi lệnh trực tiếp trên bất kỳ khung chat Zalo nào:
    Hỗ trợ tiền tố '.', '/', '!' (hoặc tiền tố tùy chỉnh của tài khoản):
      1. .spam <nội dung> [@Tên1 @Tên2 / @All]
      2. .nhay <nội dung hoặc tên_file.txt> [@Tên / @All]
      3. .ngon <nội dung hoặc tên_file.txt> [@Tên / @All]
      4. .file <ID_hoặc_tên_file> [nhay|ngon|fast] [delay=1] [color=rainbow] [@Tên / @All]
      5. .stop / .dung / .tat (Dừng spam tại khung chat hiện tại)
      6. .stopall (Dừng toàn bộ tiến trình trên mọi khung chat)
      7. .dsfile / .files (Xem danh sách file đã tải lên hệ thống)
      8. .help / .menu (Xem hướng dẫn cú pháp lệnh ngay trong khung chat)"""
    if not raw_msg or not isinstance(raw_msg, str):
        return False

    text = raw_msg.strip()
    if not text:
        return False

    custom_prefix = (acc_row.get("cmd_prefix") or ".").strip()
    valid_prefixes = tuple(set([custom_prefix, ".", "/", "!"]))
    if not text.startswith(valid_prefixes):
        return False

    # Kiểm tra quyền điều khiển: Chủ tài khoản (uidFrom == '0' hoặc trùng uid) hoặc khi bật allow_all_cmd
    my_uid = str(zalo_client.uid or acc_row.get("uid") or "")
    is_self = (str(sender_id) in ("0", my_uid, ""))
    if not is_self and not bool(acc_row.get("allow_all_cmd", 0)):
        return False

    # Tách lệnh đầu tiên
    first_space = text.find(" ")
    if first_space == -1:
        cmd_token = text[1:].lower().strip()
        arg_body = ""
    else:
        cmd_token = text[1:first_space].lower().strip()
        arg_body = text[first_space + 1:].strip()

    acc_id = acc_row["id"]
    target_obj = [{"id": str(thread_id), "name": f"Chat_{str(thread_id)[-6:]}", "type": "group" if is_group else "user"}]

    # 1. LỆNH DỪNG (.stop / .dung / .tat)
    if cmd_token in ("stop", "dung", "dừng", "tat", "tắt", "off"):
        cnt = stop_tasks_for_thread(thread_id)
        if cnt == 0:
            cnt = stop_tasks_for_thread(None)
        log_bot_command(acc_id, thread_id, sender_id, text, f"Đã dừng {cnt} tiến trình")
        try:
            zalo_client.send_adv(
                f"🛑 Đã dừng {cnt} tiến trình tự động tại khung chat này!",
                thread_id, color_mode="fixed", fixed_color="red",
                is_group=is_group, is_heading=True, antiband=True
            )
        except Exception:
            pass
        return True

    if cmd_token in ("stopall", "dunghet", "tathet"):
        cnt = stop_tasks_for_thread(None)
        log_bot_command(acc_id, thread_id, sender_id, text, f"Dừng toàn bộ ({cnt} tiến trình)")
        try:
            zalo_client.send_adv(
                f"🛑 Đã dừng toàn bộ {cnt} tiến trình trên hệ thống!",
                thread_id, color_mode="fixed", fixed_color="red",
                is_group=is_group, is_heading=True, antiband=True
            )
        except Exception:
            pass
        return True

    # 2. LỆNH XEM DANH SÁCH FILE (.files / .dsfile)
    if cmd_token in ("files", "dsfile", "listfile"):
        conn = db()
        f_rows = conn.execute("SELECT id, filename, lines, total_lines, size FROM files ORDER BY id DESC LIMIT 15").fetchall()
        conn.close()
        if not f_rows:
            msg_out = "📂 Hệ thống hiện chưa có tệp .txt nào. Hãy tải tệp lên Web trước!"
        else:
            lines_info = ["📂 DANH SÁCH FILE TRÊN HỆ THỐNG:"]
            for fr in f_rows:
                kb = round((fr["size"] or 0) / 1024, 1)
                lines_info.append(f"• ID {fr['id']}: {fr['filename']} ({fr['lines']} khối | {kb} KB)")
            lines_info.append("👉 Gõ: .file <ID> @Tên để chạy ngay!")
            msg_out = "\n".join(lines_info)
        try:
            zalo_client.send_adv(msg_out, thread_id, color_mode="rainbow", is_group=is_group, is_heading=False)
        except Exception:
            pass
        log_bot_command(acc_id, thread_id, sender_id, text, "Xem danh sách file")
        return True

    # 3. LỆNH MENU HƯỚNG DẪN (.help / .menu)
    if cmd_token in ("help", "menu", "lenh", "bot"):
        help_txt = (
            "🎄 BẢNG LỆNH SELF-BOT TRỰC TIẾP TRÊN ZALO:\n"
            "1. .spam <nội dung> [@Tên hoặc @All]\n"
            "2. .nhay <nội dung / tên_file> [@Tên hoặc @All]\n"
            "3. .ngon <nội dung / tên_file> [@Tên hoặc @All]\n"
            "4. .file <ID_file> [nhay/ngon] [delay=1] [@Tên / @All]\n"
            "5. .files (Xem danh sách file đã lưu)\n"
            "6. .stop hoặc .dung (Dừng gửi ngay lập tức)"
        )
        try:
            zalo_client.send_adv(help_txt, thread_id, color_mode="rainbow", is_group=is_group, is_heading=False)
        except Exception:
            pass
        log_bot_command(acc_id, thread_id, sender_id, text, "Hiển thị menu trợ giúp")
        return True

    # 4. CÁC LỆNH KHỞI CHẠY (.spam, .nhay, .treonhay, .ngon, .treongon, .file, .tag, .all)
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
        "tag": "fast",
        "all": "fast",
    }
    if cmd_token not in mode_map:
        return False

    chosen_mode = mode_map[cmd_token]
    delay_val = 1.0
    color_mode = "rainbow"
    fixed_color = "red"
    use_emoji = True
    icon_count = 3
    multi_acc = True

    # Bóc tách người được tag (@Tên) hoặc @All ở cuối câu lệnh
    cleaned_body, extracted_mentions, extracted_tag_all = extract_trailing_tags_and_resolve(
        arg_body,
        incoming_mentions=raw_mentions,
        zalo_client=zalo_client if is_group else None,
        group_id=thread_id if is_group else None
    )

    if cmd_token == "all":
        extracted_tag_all = True

    # Bóc tách các tham số tùy chọn ở đầu câu lệnh như delay=0.5 color=red mode=nhay icon=0
    tokens = cleaned_body.split()
    consumed = 0
    file_query = None

    if chosen_mode == "file_cmd":
        chosen_mode = "treo_nhay"
        if tokens:
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
    # Nếu lệnh chỉ định file hoặc nội dung trùng tên file đã lưu
    if file_query or (remaining_content and (remaining_content.endswith(".txt") or remaining_content.isdigit())):
        fq = file_query or remaining_content
        f_info = find_file_by_query(fq)
        if f_info:
            blocks = get_blocks_from_file_id(f_info["id"], mode=chosen_mode)

    if not blocks and remaining_content:
        if chosen_mode == "treo_nhay":
            if ";" in remaining_content:
                blocks = [x.strip() for x in remaining_content.split(";") if x.strip()]
            elif "\n" in remaining_content:
                blocks = [x.strip() for x in remaining_content.split("\n") if x.strip()]
            else:
                blocks = [remaining_content]
        elif chosen_mode == "treo_ngon":
            blocks = [remaining_content.replace(";", "\n")]
        else:
            blocks = [x.strip() for x in remaining_content.split(";") if x.strip()] if ";" in remaining_content else [remaining_content]

    # Nếu chỉ gõ lệnh + @Tên mà không gõ chữ -> lấy file mới nhất trong hệ thống
    if not blocks:
        latest_f = find_file_by_query("latest")
        if latest_f:
            blocks = get_blocks_from_file_id(latest_f["id"], mode=chosen_mode)

    if not blocks:
        return False

    # Dừng tiến trình cũ trong cùng khung chat trước khi chạy lệnh mới
    stop_tasks_for_thread(thread_id)

    tid = start_task_programmatic(
        targets=target_obj,
        blocks=blocks,
        delay=delay_val,
        use_emoji=use_emoji,
        icon_count=icon_count,
        tag_users=extracted_mentions,
        tag_all=extracted_tag_all,
        is_heading=True,
        multi_acc=multi_acc,
        mode=chosen_mode,
        color_mode=color_mode,
        fixed_color=fixed_color,
        antiband=True,
        antidieall=True,
        specific_acc_id=None,
        source_label="chat"
    )

    tag_desc = "@All" if extracted_tag_all else (", ".join("@" + m["name"] for m in extracted_mentions) if extracted_mentions else "Không tag")
    log_bot_command(acc_id, thread_id, sender_id, text, f"Chạy {chosen_mode} (Task {tid[-6:]}) | Tag: {tag_desc}")
    return True


class ZaloSelfBotListener:
    """Bộ lắng nghe lệnh ngầm 24/7 trên tài khoản Zalo (kết hợp WebSocket RFC-6455 & HTTP Group Poller).
    Hoạt động hoàn toàn độc lập trên máy chủ ngay cả khi người dùng đã tắt trình duyệt Web."""
    def __init__(self, acc_id):
        self.acc_id = acc_id
        self.stop_ev = threading.Event()
        self.seen_msg_ids = deque(maxlen=600)
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

    def _decode_ws_payload(self, client, raw_data_str, encrypt_type):
        try:
            if encrypt_type == 0:
                return json.loads(raw_data_str) if isinstance(raw_data_str, str) else raw_data_str
            b_data = base64.b64decode(unquote(raw_data_str) if "%" in raw_data_str else raw_data_str)
            if encrypt_type == 1:
                dec_txt = client._dec(raw_data_str)
                return json.loads(dec_txt)
            if encrypt_type in (2, 3):
                # Thử giải nén trực tiếp hoặc giải mã AES rồi giải nén zlib
                for candidate in (b_data, b_data[16:], b_data[4:]):
                    for wbits in (-zlib.MAX_WBITS, zlib.MAX_WBITS, 16 + zlib.MAX_WBITS):
                        try:
                            decomp = zlib.decompress(candidate, wbits)
                            return json.loads(decomp.decode("utf-8", errors="ignore"))
                        except Exception:
                            pass
                try:
                    key = base64.b64decode(client.secret_key)
                    cipher = AES.new(key, AES.MODE_CBC, bytes(16))
                    dec_bytes = cipher.decrypt(b_data)
                    for wbits in (-zlib.MAX_WBITS, zlib.MAX_WBITS, 16 + zlib.MAX_WBITS):
                        try:
                            decomp = zlib.decompress(dec_bytes, wbits)
                            return json.loads(decomp.decode("utf-8", errors="ignore"))
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass
        return None

    def _process_msg_item(self, client, acc_row, msg_obj, default_is_group=False, fallback_thread_id=None):
        if not isinstance(msg_obj, dict):
            return
        msg_id = str(msg_obj.get("msgId") or msg_obj.get("cliMsgId") or msg_obj.get("globalMsgId") or "")
        if msg_id:
            if msg_id in self.seen_msg_ids:
                return
            self.seen_msg_ids.append(msg_id)

        content = msg_obj.get("content")
        if not isinstance(content, str):
            return

        uid_from = str(msg_obj.get("uidFrom") or msg_obj.get("fromUid") or "")
        id_to = str(msg_obj.get("idTo") or msg_obj.get("toid") or fallback_thread_id or "")
        is_group = bool(default_is_group or msg_obj.get("isGroup") or (str(msg_obj.get("cmd", "")) == "521"))

        # Xác định thread_id của hộp thoại nơi người dùng gõ lệnh
        my_uid = str(client.uid or acc_row.get("uid") or "")
        if is_group:
            thread_id = id_to if (id_to and id_to not in ("0", my_uid)) else (fallback_thread_id or uid_from)
        else:
            if uid_from in ("0", my_uid):
                thread_id = id_to if id_to not in ("0", "") else my_uid
            else:
                thread_id = uid_from

        if not thread_id:
            return

        # Bóc tách mentions đi kèm trong tin nhắn nếu có
        raw_mentions = None
        m_field = msg_obj.get("mentions") or msg_obj.get("mentionInfo")
        if isinstance(m_field, list):
            raw_mentions = m_field
        elif isinstance(m_field, str) and m_field.strip().startswith("["):
            try:
                raw_mentions = json.loads(m_field)
            except Exception:
                pass

        parse_and_execute_inchat_command(
            zalo_client=client,
            acc_row=acc_row,
            thread_id=thread_id,
            is_group=is_group,
            sender_id=uid_from,
            raw_msg=content,
            raw_mentions=raw_mentions
        )

    def _poll_http_once(self, client, acc_row, last_ver_map):
        """Cơ chế quét HTTP thông minh phát hiện tin nhắn lệnh mới trong nhóm khi WebSocket bận."""
        try:
            cur_map = client.get_grid_ver_map()
            if not cur_map:
                return last_ver_map
            if not last_ver_map:
                # Khởi tạo mốc phiên bản lần đầu
                return dict(cur_map)

            changed_gids = [gid for gid, ver in cur_map.items() if last_ver_map.get(gid) != ver]
            for gid in changed_gids[:5]:
                msgs = client.get_recent_group_messages(gid)
                for m in msgs[-5:]:
                    # Chỉ xử lý tin nhắn mới trong vòng 25 giây gần nhất
                    ts_ms = int(m.get("ts") or m.get(" cliMsgId") or 0)
                    if ts_ms > 0 and (time.time() * 1000 - ts_ms) > 25000:
                        continue
                    self._process_msg_item(client, acc_row, m, default_is_group=True, fallback_thread_id=str(gid))
            return dict(cur_map)
        except Exception:
            return last_ver_map

    def _run_ws_session(self, client, acc_row, ws_url, last_ver_map):
        """Kết nối WebSocket thuần Python (RFC-6455) nhận lệnh tức thì + kết hợp HTTP Poll định kỳ."""
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

        resp_buf = b""
        while b"\r\n\r\n" not in resp_buf:
            chunk = sock.recv(1024)
            if not chunk:
                sock.close()
                return last_ver_map
            resp_buf += chunk

        if b"101" not in resp_buf.split(b"\r\n")[0]:
            sock.close()
            return last_ver_map

        sock.settimeout(3.0)
        last_ping = time.time()
        last_http_poll = time.time()

        try:
            while not self.stop_ev.is_set():
                acc_now = self._get_acc_row()
                if not acc_now or not acc_now.get("chat_cmd_enabled", 1):
                    break

                if time.time() - last_http_poll >= 4.5:
                    last_ver_map = self._poll_http_once(client, acc_now, last_ver_map)
                    last_http_poll = time.time()

                if time.time() - last_ping >= 20.0:
                    # Gửi WebSocket Ping frame
                    mask_key = os.urandom(4)
                    sock.sendall(b"\x89\x80" + mask_key)
                    last_ping = time.time()

                try:
                    hdr = sock.recv(2)
                    if not hdr or len(hdr) < 2:
                        break
                    opcode = hdr[0] & 0x0F
                    masked = (hdr[1] & 0x80) != 0
                    payload_len = hdr[1] & 0x7F

                    if payload_len == 126:
                        ext = sock.recv(2)
                        payload_len = struct.unpack(">H", ext)[0]
                    elif payload_len == 127:
                        ext = sock.recv(8)
                        payload_len = struct.unpack(">Q", ext)[0]

                    mask_bytes = sock.recv(4) if masked else b""
                    data = b""
                    while len(data) < payload_len:
                        packet = sock.recv(payload_len - len(data))
                        if not packet:
                            break
                        data += packet

                    if masked and mask_bytes:
                        data = bytes(b ^ mask_bytes[i % 4] for i, b in enumerate(data))

                    if opcode == 0x8:  # Close
                        break
                    if opcode == 0x9:  # Ping -> Pong
                        mkey = os.urandom(4)
                        sock.sendall(b"\x8A\x80" + mkey)
                        continue

                    if opcode in (0x1, 0x2) and len(data) > 4:
                        # Zalo WS Frame: 4 byte đầu có thể là [ver, cmd_lo, cmd_hi, sub] hoặc trực tiếp JSON
                        cmd_id = 0
                        json_part = data
                        if data[0] != ord("{"):
                            cmd_id = struct.unpack("<H", data[1:3])[0]
                            json_part = data[4:]

                        outer = json.loads(json_part.decode("utf-8", errors="ignore"))
                        enc_type = int(outer.get("encrypt", 0))
                        inner = self._decode_ws_payload(client, outer.get("data", ""), enc_type)
                        if isinstance(inner, dict):
                            inner_data = inner.get("data") if isinstance(inner.get("data"), dict) else inner
                            msgs = (
                                inner_data.get("msgs")
                                or inner_data.get("groupMsgs")
                                or ([inner_data] if inner_data.get("content") else [])
                            )
                            is_grp_cmd = (cmd_id == 521) or bool(inner_data.get("groupMsgs"))
                            for m in msgs:
                                if isinstance(m, dict):
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
        return last_ver_map

    def _run_loop(self):
        last_ver_map = {}
        while not self.stop_ev.is_set():
            acc_row = self._get_acc_row()
            if not acc_row or acc_row.get("platform") != "zalo":
                break
            if not acc_row.get("chat_cmd_enabled", 1):
                self.stop_ev.wait(5.0)
                continue

            try:
                client = Zalo(acc_row["imei"], json.loads(acc_row["cookies"]))
                if client.ws_urls:
                    ws_url = client.ws_urls[0]
                    if "zpw_ver=" not in ws_url:
                        sep = "&" if "?" in ws_url else "?"
                        ws_url = f"{ws_url}{sep}zpw_ver=645&zpw_type=30"
                    last_ver_map = self._run_ws_session(client, acc_row, ws_url, last_ver_map)
                else:
                    # Nếu không có WS URL thì chạy vòng lặp HTTP Poll
                    for _ in range(15):
                        if self.stop_ev.is_set():
                            break
                        last_ver_map = self._poll_http_once(client, acc_row, last_ver_map)
                        self.stop_ev.wait(4.0)
            except Exception:
                self.stop_ev.wait(6.0)


def sync_all_zalo_listeners():
    """Đồng bộ hóa các luồng lắng nghe lệnh khung chat cho toàn bộ tài khoản Zalo đã lưu."""
    try:
        conn = db()
        rows = conn.execute("SELECT id, platform, chat_cmd_enabled FROM accounts").fetchall()
        conn.close()
        active_ids = set()
        for r in rows:
            aid = r["id"]
            if (r["platform"] or "zalo") == "zalo" and r["chat_cmd_enabled"]:
                active_ids.add(aid)
                if aid not in ACTIVE_LISTENERS or not ACTIVE_LISTENERS[aid].thread.is_alive():
                    listener = ZaloSelfBotListener(aid)
                    ACTIVE_LISTENERS[aid] = listener
                    listener.start()
        for aid in list(ACTIVE_LISTENERS.keys()):
            if aid not in active_ids:
                ACTIVE_LISTENERS[aid].stop()
                ACTIVE_LISTENERS.pop(aid, None)
    except Exception as e:
        print("Lỗi đồng bộ Self-Bot Listener:", e)


# ============================================================
# CSS GIAO DIỆN NOEL GIÁNG SINH PRO 4.0 (SIÊU MƯỢT & HIỆN ĐẠI)
# ============================================================
CSS_NOEL = """
:root {
  --bg-page: #07111e;
  --bg-card: rgba(16, 28, 52, 0.88);
  --bg-card-hover: rgba(22, 38, 68, 0.95);
  --border-color: rgba(231, 76, 60, 0.42);
  --border-gold: rgba(245, 176, 65, 0.65);
  --txt-0: #ffffff;
  --txt-1: #e8eef5;
  --txt-2: #9fb1c6;
  --noel-red: #ff4757;
  --noel-green: #2ed573;
  --noel-gold: #ffa502;
  --noel-cyan: #1e90ff;
  --grad-noel: linear-gradient(135deg, #c0392b 0%, #ff4757 52%, #ffa502 100%);
  --grad-green: linear-gradient(135deg, #0b8457 0%, #2ed573 100%);
  --grad-ocean: linear-gradient(135deg, #0052d4 0%, #4364f7 50%, #6fb1fc 100%);
  --grad-dark: linear-gradient(135deg, #1b2845 0%, #0b162c 100%);
  --shadow-noel: 0 10px 28px rgba(255, 71, 87, 0.28);
  --shadow-gold: 0 4px 20px rgba(255, 165, 2, 0.32);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html { touch-action: manipulation; -webkit-text-size-adjust: 100%; scroll-behavior: smooth; }
body {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background-color: var(--bg-page);
  color: var(--txt-1);
  min-height: 100vh;
  padding-bottom: 120px;
  position: relative;
  overflow-x: hidden;
  background-image:
    radial-gradient(circle at 15% 10%, rgba(255, 71, 87, 0.18) 0%, transparent 45%),
    radial-gradient(circle at 85% 15%, rgba(255, 165, 2, 0.14) 0%, transparent 45%),
    radial-gradient(circle at 50% 85%, rgba(46, 213, 115, 0.12) 0%, transparent 50%);
}

#snow-canvas {
  position: fixed; inset: 0; pointer-events: none !important; z-index: 1; width: 100%; height: 100%;
}

.header {
  background: rgba(7, 17, 30, 0.92); backdrop-filter: blur(28px);
  padding: 12px 18px; border-bottom: 1.5px solid var(--border-gold);
  position: sticky; top:0; z-index: 100; box-shadow: 0 6px 25px rgba(0, 0, 0, 0.55);
}
.header-inner { max-width: 1080px; margin: 0 auto; display: flex; align-items: center; gap: 14px; }
.logo-box {
  width: 50px; height: 50px; border-radius: 50%; overflow: hidden;
  border: 2px solid var(--noel-gold); box-shadow: 0 0 18px rgba(255, 165, 2, 0.65);
  background: #1b263b; flex-shrink: 0; position: relative; animation: glowLogo 3s ease-in-out infinite alternate;
}
@keyframes glowLogo { from { box-shadow: 0 0 10px rgba(255, 165, 2, 0.45); } to { box-shadow: 0 0 22px rgba(255, 71, 87, 0.85); } }
.logo-box img { width: 100%; height: 100%; object-fit: cover; }
.header-meta { flex: 1; min-width: 0; }
.header-meta h1 { font-family: 'Orbitron', sans-serif; font-size: 15.5px; font-weight: 900; color: var(--txt-0); display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pro-tag { font-size: 9.5px; padding: 2px 8px; border-radius: 99px; background: var(--grad-noel); color: #fff; font-family: 'Inter', sans-serif; letter-spacing: 0.5px; }
.header-meta p { font-size: 11px; color: var(--txt-2); font-weight: 700; margin-top: 3px; display: flex; align-items: center; gap: 5px; }
.v-badge { display: inline-flex; align-items: center; justify-content: center; color: #0084ff; font-weight: 900; }

.container { max-width: 1080px; margin: 0 auto; padding: 16px 14px; position: relative; z-index: 10; }

.stats-strip {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
  gap: 10px; margin-bottom: 16px;
}
.stat-box {
  background: rgba(16, 28, 52, 0.9); border: 1px solid rgba(255, 165, 2, 0.35);
  border-radius: 16px; padding: 12px 14px; display: flex; flex-direction: column; gap: 4px;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.3);
}
.stat-box .s-label { font-size: 10px; font-weight: 800; color: var(--txt-2); text-transform: uppercase; letter-spacing: 0.4px; }
.stat-box .s-val { font-family: 'Orbitron', sans-serif; font-size: 18px; font-weight: 900; color: var(--noel-gold); }
.stat-box .s-sub { font-size: 10px; color: var(--noel-green); font-weight: 700; }

.panel { display: none; animation: fadeIn .28s var(--ease) both; }
.panel.active { display: block; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

.card {
  background: var(--bg-card); backdrop-filter: blur(25px);
  padding: 18px; border-radius: 20px; border: 1.5px solid var(--border-color);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4); margin-bottom: 15px;
}
.card h2 {
  font-size: 13px; font-weight: 900; letter-spacing: .4px; margin-bottom: 14px;
  display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; color: var(--noel-gold);
}

.btn-pill {
  padding: 10px 16px; border-radius: 99px; border: none; cursor: pointer;
  font-size: 11px; font-weight: 800; letter-spacing: .3px;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  transition: all .22s var(--ease); position: relative; overflow: hidden; color: #fff;
}
.btn-pill:hover { transform: translateY(-2px); filter: brightness(1.1); }
.btn-pill:active { transform: translateY(0) scale(0.96); }
.btn-pill.primary { background: var(--grad-noel); box-shadow: var(--shadow-noel); }
.btn-pill.green { background: var(--grad-green); box-shadow: 0 4px 14px rgba(46, 213, 115, 0.35); }
.btn-pill.ocean { background: var(--grad-ocean); box-shadow: 0 4px 14px rgba(30, 144, 255, 0.35); }
.btn-pill.dark { background: var(--grad-dark); border: 1px solid var(--border-gold); }
.btn-pill.light { background: rgba(255, 255, 255, 0.1); border: 1px solid rgba(255, 255, 255, 0.22); }
.btn-pill.danger { background: rgba(255, 71, 87, 0.2); color: #ff6b81; border: 1px solid rgba(255, 71, 87, 0.5); }
.btn-pill.full { width: 100%; padding: 13px; font-size: 12px; }

.btn-round {
  width: 56px; height: 56px; border-radius: 50%; border: none; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  transition: all .25s var(--ease); margin: 6px;
}
.btn-round svg { width: 24px; height: 24px; }
.btn-round:hover { transform: scale(1.1); }
.btn-round.action-start { background: var(--grad-green); color: #fff; box-shadow: 0 6px 22px rgba(46, 213, 115, 0.55); }
.btn-round.action-stop { background: var(--grad-noel); color: #fff; box-shadow: 0 6px 22px rgba(255, 71, 87, 0.55); }

.file-upload-label {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; width: 100%; min-height: 96px; padding: 14px; border: 2px dashed var(--noel-gold);
  border-radius: 16px; background: rgba(255, 165, 2, 0.08); cursor: pointer;
  transition: all 0.3s var(--ease); text-align: center;
}
.file-upload-label:hover { background: rgba(255, 165, 2, 0.16); border-color: #fff; }
.file-upload-label svg { width: 32px; height: 32px; color: var(--noel-gold); }
.file-upload-label span { font-size: 12px; font-weight: 800; color: var(--txt-0); }

.upload-progress-wrap {
  display: none; margin-top: 12px; background: rgba(7, 17, 30, 0.9);
  border: 1px solid var(--border-gold); border-radius: 12px; padding: 10px 12px;
}
.upload-bar-bg { width: 100%; height: 8px; background: rgba(255,255,255,0.1); border-radius: 99px; overflow: hidden; margin-top: 6px; }
.upload-bar-fill { height: 100%; width: 0%; background: var(--grad-green); transition: width 0.15s linear; }

.form-group { margin-bottom: 12px; }
.form-group label { display: block; margin-bottom: 6px; font-size: 11px; font-weight: 800; color: var(--noel-gold); }
.form-group input:not([type="file"]):not([type="checkbox"]), .form-group textarea, .form-group select {
  width: 100%; padding: 12px 14px; border: 1.5px solid rgba(255, 255, 255, 0.16); border-radius: 14px;
  font-size: 12.5px; background: rgba(7, 17, 30, 0.88); color: var(--txt-0); transition: border-color .2s;
}
.form-group input:focus, .form-group textarea:focus, .form-group select:focus {
  outline: none; border-color: var(--noel-gold); box-shadow: 0 0 12px rgba(255, 165, 2, 0.3);
}
.form-group textarea { min-height: 96px; font-family: 'JetBrains Mono', monospace; font-size: 11.5px; line-height: 1.5; }

.chip-bar { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 5px; }
.chip-item {
  padding: 8px 14px; background: rgba(255, 255, 255, 0.08); color: var(--txt-1); border-radius: 99px;
  font-size: 11px; font-weight: 800; cursor: pointer; border: 1px solid rgba(255, 255, 255, 0.16); transition: all .2s;
}
.chip-item:hover { border-color: var(--noel-gold); color: #fff; transform: translateY(-1px); }
.chip-item.active { background: var(--grad-noel); color: #fff; border-color: transparent; box-shadow: 0 4px 12px rgba(255, 71, 87, 0.4); }

.toggle-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(148px, 1fr)); gap: 8px; margin-bottom: 12px; }
.toggle-item {
  padding: 11px 10px; border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 14px;
  cursor: pointer; text-align: center; font-weight: 800; font-size: 10.5px;
  background: rgba(255, 255, 255, 0.05); color: var(--txt-2); transition: all .2s;
}
.toggle-item.active { background: var(--grad-green); color: #fff; border-color: transparent; box-shadow: 0 4px 14px rgba(46, 213, 115, 0.38); }

.table-wrap { overflow-x: auto; border-radius: 14px; border: 1px solid rgba(255, 255, 255, 0.15); background: rgba(7, 17, 30, 0.9); }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { padding: 11px 10px; text-align: left; font-size: 11px; border-bottom: 1px solid rgba(255, 255, 255, 0.07); white-space: nowrap; color: var(--txt-1); }
.table th { background: rgba(255, 255, 255, 0.06); font-weight: 800; color: var(--noel-gold); font-size: 10px; text-transform: uppercase; }

.box-list { max-height: 290px; overflow-y: auto; border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 14px; padding: 8px; background: rgba(7, 17, 30, 0.9); }
.box-item {
  padding: 10px 12px; border-radius: 12px; background: rgba(255, 255, 255, 0.04); margin-bottom: 6px;
  cursor: pointer; border: 1px solid rgba(255, 255, 255, 0.08); display: flex; align-items: center; gap: 10px; transition: all .15s;
}
.box-item:hover { border-color: var(--noel-gold); background: rgba(255, 165, 2, 0.1); }
.box-item.selected { border-color: var(--noel-red); background: rgba(255, 71, 87, 0.25); }
.box-item .check-mark {
  width: 18px; height: 18px; border: 1.5px solid var(--txt-2); border-radius: 5px;
  display: flex; align-items: center; justify-content: center; font-size: 10px; color: transparent; font-weight: 900; flex-shrink: 0;
}
.box-item.selected .check-mark { background: var(--noel-red); border-color: var(--noel-red); color: #fff; }
.box-item .b-title { font-weight: 800; font-size: 12px; color: var(--txt-0); }
.box-item .b-sub { font-size: 10px; color: var(--txt-2); font-family: 'JetBrains Mono', monospace; }

.cmd-badge {
  display: inline-block; padding: 3px 8px; border-radius: 6px;
  background: rgba(255, 165, 2, 0.16); border: 1px solid rgba(255, 165, 2, 0.45);
  color: var(--noel-gold); font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 700;
}
.hint-banner {
  background: linear-gradient(135deg, rgba(30, 144, 255, 0.15), rgba(46, 213, 115, 0.12));
  border: 1px solid rgba(46, 213, 115, 0.45); border-radius: 14px; padding: 12px 14px;
  font-size: 11.5px; line-height: 1.6; color: var(--txt-1); margin-bottom: 12px;
}

.bottom-dock {
  position: fixed; bottom: 12px; left: 50%; transform: translateX(-50%);
  width: calc(100% - 20px); max-width: 640px;
  background: rgba(7, 17, 30, 0.96); backdrop-filter: blur(28px);
  border: 1.5px solid var(--border-gold);
  box-shadow: 0 14px 42px rgba(0, 0, 0, 0.7);
  border-radius: 99px; display: grid; grid-template-columns: repeat(6, 1fr);
  padding: 6px; gap: 4px; z-index: 999;
}
.bottom-dock .dock-btn {
  padding: 8px 2px; border-radius: 99px; cursor: pointer; font-size: 9.5px; font-weight: 800;
  text-align: center; color: var(--txt-2); display: flex; flex-direction: column; align-items: center;
  gap: 3px; background: transparent; border: none; transition: all .2s;
}
.bottom-dock .dock-btn svg { width: 17px; height: 17px; transition: transform 0.2s; }
.bottom-dock .dock-btn:hover svg { transform: scale(1.15) translateY(-2px); }
.bottom-dock .dock-btn.active { background: var(--grad-noel); color: #fff; box-shadow: var(--shadow-noel); transform: translateY(-2px); }

#toast-stack { position: fixed; top: 14px; right: 14px; z-index: 99999; max-width: 340px; width: calc(100% - 28px); pointer-events: none; }
.toast {
  pointer-events: auto; padding: 12px 16px; border-radius: 14px;
  background: rgba(16, 28, 52, 0.98); border: 1.5px solid var(--noel-gold);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.6); display: flex; flex-direction: column; gap: 3px;
  animation: toastIn .25s var(--ease) both;
}
.toast.swipe-up { animation: toastUp .2s ease-out forwards; }
@keyframes toastIn { from { opacity: 0; transform: translateY(-20px); } to { opacity: 1; transform: translateY(0); } }
@keyframes toastUp { to { opacity: 0; transform: translateY(-40px); } }
.toast .t-head { font-size: 11px; font-weight: 900; color: var(--noel-gold); display:flex; align-items:center; gap:5px; }
.toast .t-body { font-size: 11px; font-weight: 600; color: var(--txt-0); }
"""

HTML_GATE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Hệ Thống An Toàn Noel Pro</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_NOEL + """
body { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
.gate-card {
  background: rgba(16, 28, 52, 0.96); border: 2px solid var(--noel-gold);
  border-radius: 24px; padding: 40px 28px; max-width: 410px; width: 100%; text-align: center;
  box-shadow: 0 25px 60px rgba(0, 0, 0, 0.75); position: relative; overflow: hidden;
}
.radar-scanner {
  width: 96px; height: 96px; margin: 0 auto 20px; border-radius: 50%;
  position: relative; display: flex; align-items: center; justify-content: center;
  background: radial-gradient(circle, rgba(255,165,2,0.2) 0%, transparent 70%);
  border: 2px dashed var(--noel-gold);
}
.radar-scanner::before {
  content: ''; position: absolute; inset: 0; border-radius: 50%;
  border: 2px solid transparent; border-top-color: var(--noel-red);
  animation: spin 1.1s linear infinite;
}
@keyframes spin { 100% { transform: rotate(360deg); } }
.radar-icon { font-size: 38px; animation: pulse 1.5s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.15); } }
.progress-line { height: 7px; width: 100%; background: rgba(255,255,255,0.1); border-radius: 99px; overflow: hidden; margin: 20px 0; display: none; }
.progress-fill { height: 100%; width: 0%; background: var(--grad-noel); border-radius: 99px; transition: width 0.3s ease; }
</style>
</head>
<body>
<canvas id="snow-canvas"></canvas>
<div class="gate-card" style="z-index:10;">
  <div class="radar-scanner"><div class="radar-icon">🎄</div></div>
  <h1 style="font-family:'Orbitron',sans-serif; font-size:17px; margin-bottom:8px; color:var(--noel-gold);">BẢO MẬT NOEL PRO 4.0</h1>
  <p id="scan-status" style="font-size:12px; color:var(--txt-1); min-height:34px;">Xác thực danh tính & kích hoạt lá chắn Anti-Die-All.</p>
  <div class="progress-line" id="p-box"><div class="progress-fill" id="p-bar"></div></div>
  <button class="btn-pill primary full" id="start-btn" onclick="startVerification()" style="font-size:13px; padding:15px;">❄️ Bắt Đầu Xác Thực</button>
</div>
<script>
var pBox = document.getElementById('p-box');
var pBar = document.getElementById('p-bar');
var statusTxt = document.getElementById('scan-status');
var startBtn = document.getElementById('start-btn');
var steps = [
  { p: 30, txt: 'Đang nạp động cơ Multi-MB Streaming & WAL DB...' },
  { p: 65, txt: 'Đang khởi động Self-Bot 24/7 & Lá chắn Anti-Die-All...' },
  { p: 100, txt: 'Xác thực hoàn tất! Đang mở cổng điều khiển...' }
];
var idx = 0;
function startVerification(){
  startBtn.style.display = 'none';
  pBox.style.display = 'block';
  runStep();
}
function runStep(){
  if(idx < steps.length){
    pBar.style.width = steps[idx].p + '%';
    statusTxt.textContent = steps[idx].txt;
    idx++;
    setTimeout(runStep, 320);
  } else {
    finishScan();
  }
}
async function finishScan(){
  var r = await fetch('/api/verify_human', { method: 'POST' }).then(x => x.json());
  if(r.ok) window.location.href = '/login';
}
var snowCanvas = document.getElementById('snow-canvas');
var sCtx = snowCanvas.getContext('2d');
var sW = window.innerWidth, sH = window.innerHeight;
snowCanvas.width = sW; snowCanvas.height = sH;
var flakes = Array.from({ length: 60 }, () => ({
  x: Math.random() * sW, y: Math.random() * sH,
  r: Math.random() * 3 + 1.2, dY: Math.random() * 1.2 + 0.5, dX: Math.random() * 0.8 - 0.4, opacity: Math.random() * 0.7 + 0.3
}));
function renderSnow() {
  sCtx.clearRect(0, 0, sW, sH);
  flakes.forEach(f => {
    sCtx.beginPath(); sCtx.arc(f.x, f.y, f.r, 0, Math.PI * 2);
    sCtx.fillStyle = 'rgba(255, 255, 255, ' + f.opacity + ')'; sCtx.fill();
    f.y += f.dY; f.x += f.dX;
    if (f.y > sH) { f.y = -10; f.x = Math.random() * sW; }
  });
  requestAnimationFrame(renderSnow);
}
renderSnow();
</script>
</body>
</html>
"""

HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Đăng Nhập — ALB Forge Noel Pro</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_NOEL + """
body { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
.login-card {
  background: rgba(16, 28, 52, 0.96); border: 2px solid var(--noel-gold);
  border-radius: 24px; padding: 40px 28px; max-width: 410px; width: 100%; text-align: center;
  box-shadow: 0 25px 60px rgba(0, 0, 0, 0.75); position: relative; z-index: 10;
}
.login-logo { width: 88px; height: 88px; border-radius: 50%; overflow: hidden; margin: 0 auto 16px; border: 2.5px solid var(--noel-gold); box-shadow: 0 0 20px rgba(255, 165, 2, 0.55); }
.login-logo img { width: 100%; height: 100%; object-fit: cover; }
.err-msg { background: rgba(255, 71, 87, 0.22); border: 1px solid var(--noel-red); color: #ff6b81; padding: 11px; border-radius: 12px; font-size: 11.5px; font-weight: 800; margin-bottom: 16px; text-align: left; }
</style>
</head>
<body>
<canvas id="snow-canvas"></canvas>
<div class="login-card">
  <div class="login-logo">
    <img src="/static/logo.png" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 100 100\\'><circle cx=\\'50\\' cy=\\'50\\' r=\\'50\\' fill=\\'%23c0392b\\'/><text x=\\'50\\' y=\\'62\\' text-anchor=\\'middle\\' font-size=\\'40\\' fill=\\'white\\'>🎄</text></svg>'">
  </div>
  <h1 style="font-family:'Orbitron',sans-serif; font-size:18px; margin-bottom:6px; color:var(--noel-gold);">ALB FORGE NOEL PRO ❄️</h1>
  <p style="font-size:11px; color:var(--txt-1); font-weight:700; margin-bottom:22px; display:flex; align-items:center; justify-content:center; gap:5px;">
    Bản quyền: <span class="v-badge"><svg viewBox="0 0 24 24" width="14" height="14" fill="#0084ff"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></span> Phạm Anh Khôi
  </p>
  {% if error %}<div class="err-msg">⚠️ {{ error }}</div>{% endif %}
  <form method="POST">
    <div class="form-group" style="text-align:left;">
      <input type="password" name="password" placeholder="Nhập mật khẩu truy cập hệ thống..." required autofocus>
    </div>
    <button type="submit" class="btn-pill primary full" style="font-size:13px; padding:14px;">🎁 Đăng Nhập Hệ Thống</button>
  </form>
</div>
</body>
</html>
"""

HTML_INDEX = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>ALB Forge Noel Pro 4.0 — Zalo & Discord Self-Bot</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_NOEL + """
</style>
</head>
<body>
<canvas id="snow-canvas"></canvas>

<div class="header">
  <div class="header-inner">
    <div class="logo-box">
      <img id="header-logo" src="/static/logo.png" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 100 100\\'><circle cx=\\'50\\' cy=\\'50\\' r=\\'50\\' fill=\\'%23c0392b\\'/><text x=\\'50\\' y=\\'62\\' text-anchor=\\'middle\\' font-size=\\'40\\' fill=\\'white\\'>🎄</text></svg>'">
    </div>
    <div class="header-meta">
      <h1>ALB FORGE NOEL <span class="pro-tag">PRO v4.0</span></h1>
      <p>
        Bản quyền: <span class="v-badge"><svg viewBox="0 0 24 24" width="13" height="13" fill="#0084ff"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></span> <b>Phạm Anh Khôi</b> • Điều khiển Web & Gõ Lệnh Khung Chat 24/7
      </p>
    </div>
    <button class="btn-pill light" onclick="location.href='/logout'">Đăng xuất</button>
  </div>
</div>

<div id="toast-stack"></div>

<div class="container">

  <!-- THANH CHỈ SỐ TRẠNG THÁI TRỰC TIẾP -->
  <div class="stats-strip">
    <div class="stat-box">
      <span class="s-label">Tài Khoản Kết Nối</span>
      <span class="s-val" id="st-acc-count">0</span>
      <span class="s-sub">Zalo & Discord</span>
    </div>
    <div class="stat-box">
      <span class="s-label">Self-Bot Khung Chat</span>
      <span class="s-val" id="st-bot-count" style="color:var(--noel-green);">ON 24/7</span>
      <span class="s-sub">Tự chạy không cần bật Web</span>
    </div>
    <div class="stat-box">
      <span class="s-label">Tiến Trình Đang Chạy</span>
      <span class="s-val" id="st-task-count" style="color:var(--noel-red);">0</span>
      <span class="s-sub" id="st-sent-total">Đã gửi: 0 tin</span>
    </div>
    <div class="stat-box">
      <span class="s-label">Lá Chắn Anti-Die-All</span>
      <span class="s-val" id="st-shield-state" style="color:#1e90ff;">BẢO VỆ</span>
      <span class="s-sub">Circuit Breaker + Polymorphic</span>
    </div>
  </div>

  <!-- TAB 1: ACCOUNTS (ZALO & DISCORD + CẤU HÌNH SELF-BOT 24/7) -->
  <div class="panel active" id="panel-accounts">
    <div class="card">
      <h2>
        <span>➕ Thêm Tài Khoản Mới (Lưu Cookie + IMEI Chạy Cả Web & Khung Chat 24/7)</span>
        <button class="btn-pill green" onclick="checkAllAccounts()">Kiểm Tra Tất Cả</button>
      </h2>

      <div class="hint-banner">
        💡 <b>Tính năng Kép Đặc Biệt:</b> Ngay khi bạn lưu <b>IMEI + Cookie Zalo</b> vào đây, bạn vừa có thể điều khiển đầy đủ trên Web, vừa có thể <b>tắt Web đi và tự gõ lệnh trực tiếp (ví dụ: <code>.spam Nội dung @Tên</code> hoặc <code>.file 1 @All</code>) vào bất kỳ khung chat Zalo nào</b> trên điện thoại/máy tính!
      </div>

      <div class="form-group">
        <label>Chọn Nền Tảng Ứng Dụng</label>
        <div class="chip-bar" id="platform-selector">
          <div class="chip-item active" data-plat="zalo" onclick="selectPlat('zalo')">🔷 Zalo (IMEI + Cookie + Self-Bot 24/7)</div>
          <div class="chip-item" data-plat="discord" onclick="selectPlat('discord')">🟣 Discord (Bot / User Token)</div>
        </div>
        <input type="hidden" id="add-platform" value="zalo">
      </div>

      <div class="form-group"><label>Tên gợi nhớ</label><input id="add-label" placeholder="Ví dụ: Acc Chính Noel"></div>

      <div id="zalo-input-fields">
        <div class="form-group"><label>IMEI thiết bị Zalo</label><input id="add-imei" placeholder="Nhập chuỗi IMEI Zalo..."></div>
        <div class="form-group"><label>Cookie JSON Zalo</label><textarea id="add-cookies" placeholder='{"zpw_sek":"...","zpw_ver":"645","zpw_type":"30"}'></textarea></div>
        <div style="display:flex; gap:14px; flex-wrap:wrap; margin-bottom:12px;">
          <label style="display:flex; align-items:center; gap:7px; font-size:11.5px; color:var(--txt-0); cursor:pointer;">
            <input type="checkbox" id="add-chat-cmd" checked style="width:16px; height:16px;">
            ⚡ Bật nhận lệnh trực tiếp trên khung chat Zalo 24/7 (Khỏi cần bật Web)
          </label>
          <label style="display:flex; align-items:center; gap:7px; font-size:11.5px; color:var(--txt-1); cursor:pointer;">
            <input type="checkbox" id="add-allow-all" style="width:16px; height:16px;">
            Cho phép nick phụ khác trong nhóm gõ lệnh điều khiển acc này
          </label>
        </div>
      </div>

      <div id="discord-input-fields" style="display:none;">
        <div class="form-group">
          <label>Loại Token Discord</label>
          <div class="chip-bar" id="bot-type-selector">
            <div class="chip-item active" data-bot="1" onclick="selectBotType(1)">🤖 Bot Token (Khuyên dùng)</div>
            <div class="chip-item" data-bot="0" onclick="selectBotType(0)">👤 User Token (Self-bot)</div>
          </div>
          <input type="hidden" id="add-is-bot" value="1">
        </div>
        <div class="form-group"><label>Discord Token</label><input id="add-token" placeholder="MTAx... hoặc OTk..."></div>
      </div>

      <button class="btn-pill primary full" onclick="addAccount()">💾 Lưu Tài Khoản & Kích Hoạt Self-Bot</button>
    </div>

    <div class="card">
      <h2><span>📋 Danh Sách Tài Khoản & Trạng Thái Anti-Die-All</span></h2>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Nền tảng</th>
              <th>Tên hiển thị</th>
              <th>Lệnh Khung Chat 24/7</th>
              <th>Sức khỏe (Anti-Die)</th>
              <th>Trạng thái</th>
              <th>Thao tác</th>
            </tr>
          </thead>
          <tbody id="accounts-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 2: BOXES (ZALO & DISCORD) -->
  <div class="panel" id="panel-boxes">
    <div class="card">
      <h2><span>💬 Quản Lý Hội Thoại / Nhóm / Kênh Nhận Tin</span></h2>
      <div class="form-group"><label>Chọn tài khoản để nạp danh sách nhóm & bạn bè</label><select id="load-acc-select"><option value="">-- Chọn tài khoản --</option></select></div>
      <div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px;">
        <button class="btn-pill green" onclick="loadBoxes()">🔄 Nạp Danh Sách Hội Thoại</button>
        <button class="btn-pill light" onclick="selectAllBoxes()">Chọn Tất Cả</button>
        <button class="btn-pill danger" onclick="clearAllBoxes()">Bỏ Chọn</button>
      </div>
      <div class="form-group" style="margin-bottom:8px;">
        <input type="text" id="search-box-inp" placeholder="🔍 Tìm nhanh tên nhóm hoặc ID hội thoại..." oninput="filterBoxes()">
      </div>
      <div>
        <div style="font-size:11px; font-weight:800; color:var(--noel-gold); margin-bottom:6px;">
          ĐÃ CHỌN: <span id="selected-count" style="color:var(--noel-red); font-size:13px;">0</span> HỘI THOẠI / KÊNH
        </div>
        <div class="box-list" id="box-list"><div style="text-align:center; padding:18px; color:var(--txt-2); font-size:12px;">Chưa nạp dữ liệu hội thoại</div></div>
      </div>
    </div>
  </div>

  <!-- TAB 3: FILES (TẢI FILE NHIỀU MB SIÊU TỐC STREAMING) -->
  <div class="panel" id="panel-files">
    <div class="card">
      <h2><span>🚀 Tải Lên Tệp Văn Bản Nhiều MB Siêu Tốc (Streaming Engine)</span></h2>
      <div class="hint-banner">
        ⚡ <b>Công nghệ Multi-MB Streaming mới:</b> Hỗ trợ tải tệp văn bản <code>.txt</code> hàng chục đến hàng trăm MB cực nhanh với thanh tiến trình trực tiếp. Khi chạy gửi tin, máy chủ đọc trực tiếp từ bộ đệm RAM của Server (không tải ngược về trình duyệt), giúp phản hồi tức thì trong 0.01 giây!
      </div>

      <label class="file-upload-label" for="file-input">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        <span id="upload-txt">Nhấn để chọn tệp Văn bản (.txt dung lượng lớn) hoặc Ảnh Logo</span>
        <span id="upload-sub" style="font-size:10.5px; color:var(--txt-2); font-weight:600;">Hỗ trợ tới 500MB • Không giới hạn số dòng</span>
        <input type="file" id="file-input" style="display:none;" onchange="handleFileSelect(this)">
      </label>

      <div class="upload-progress-wrap" id="upload-prog-box">
        <div style="display:flex; justify-content:space-between; font-size:11px; font-weight:800; color:var(--noel-gold);">
          <span id="upload-prog-status">Đang tải lên...</span>
          <span id="upload-prog-pct">0%</span>
        </div>
        <div class="upload-bar-bg"><div class="upload-bar-fill" id="upload-prog-bar"></div></div>
      </div>

      <div style="display:flex; gap:8px; margin-top:12px;">
        <button class="btn-pill primary full" onclick="uploadFileFast()">📤 Tải Lên & Nạp Bộ Đệm (.txt)</button>
        <button class="btn-pill dark full" onclick="uploadLogo()">🖼️ Cập Nhật Logo Web</button>
      </div>
    </div>

    <div class="card">
      <h2><span>📂 Kho Tệp Văn Bản Đã Lưu (Dùng Cho Cả Web & Lệnh .file Trên Zalo)</span></h2>
      <div id="files-list"><div style="text-align:center; padding:18px; color:var(--txt-2); font-size:11.5px;">Chưa có tập tin</div></div>
    </div>
  </div>

  <!-- TAB 4: SPAM ENGINE (ĐỔI MÀU CHỮ CHUẨN ZALO + TAG CUỐI CÂU LIÊN TỤC) -->
  <div class="panel" id="panel-spam">
    <div class="card">
      <h2><span>🔥 Động Cơ Gửi Tin Đa Luồng (Đổi Màu Chữ Zalo RichText & Tag Liên Tục)</span></h2>

      <div class="hint-banner">
        🎯 <b>Mẹo Tag Liên Tục Cực Nhanh:</b> Bạn có thể chọn thành viên bên dưới <b>HOẶC gõ trực tiếp <code>@TênNgườiĐó</code> hay <code>@All</code> ở cuối ô nội dung văn bản</b> (ví dụ: <code>Nội dung cần gửi @Nguyễn Văn A</code>). Hệ thống sẽ tự động nhận diện người đó trong nhóm và <b>lặp lại việc tag tên người đó / @All liên tục ở mọi tin nhắn</b> cho đến khi bạn bấm Dừng!
      </div>

      <div class="form-group">
        <label>1. Chế độ gửi tin nhắn</label>
        <div class="chip-bar" id="mode-selector">
          <div class="chip-item active" data-mode="fast">⚡ Siêu Nhanh</div>
          <div class="chip-item" data-mode="treo_ngon">📜 Treo Ngôn (N Dòng / 1 Tin)</div>
          <div class="chip-item" data-mode="treo_nhay">🔥 Treo Nhây (Tách Từng Dòng Riêng)</div>
        </div>
        <input type="hidden" id="spam-mode" value="fast">
      </div>

      <div class="form-group">
        <label>2. Chọn tập tin văn bản đã lưu (Đọc trực tiếp từ RAM Server siêu tốc)</label>
        <select id="spam-file-select"><option value="">-- Không dùng file (Dùng nội dung nhập bên dưới) --</option></select>
      </div>

      <div class="form-group">
        <label>3. Nhập trực tiếp nội dung (Gõ thêm @Tên hoặc @All ở cuối nếu muốn tag liên tục người đó)</label>
        <textarea id="spam-messages" placeholder="Nhập nội dung nhiều dòng hoặc cách nhau dấu ';'...\nVí dụ: Gõ 'Chào buổi sáng @TênNgườiĐó' hoặc 'Thông báo khẩn @All' ở cuối -> Hệ thống sẽ tự động tag người đó / @All liên tục đến khi bạn tắt!"></textarea>
      </div>

      <div class="form-group">
        <label>4. Tag nhanh theo Tên ở cuối (Tùy chọn - Áp dụng cả khi chạy bằng File .txt)</label>
        <input id="quick-tail-tag" placeholder="Ví dụ: @Phạm Anh Khôi hoặc @All (Hệ thống sẽ gắn và tag liên tục vào cuối mỗi tin của File)">
      </div>

      <div class="form-group">
        <label>5. Đổi màu chữ chuẩn Zalo Rich-Text (ver: 0) & Discord ANSI</label>
        <div class="chip-bar" id="color-mode-bar">
          <div class="chip-item active" data-cmode="rainbow">🌈 Cầu Vồng Từng Dòng</div>
          <div class="chip-item" data-cmode="word_rainbow">✨ Cầu Vồng Từng Từ</div>
          <div class="chip-item" data-cmode="random">🎲 Đổi Màu Ngẫu Nhiên</div>
          <div class="chip-item" data-cmode="fixed">🎨 Cố Định Một Màu</div>
          <div class="chip-item" data-cmode="none">⚪ Tắt Màu</div>
        </div>
        <input type="hidden" id="color-mode" value="rainbow">
        <div id="fixed-colors-wrap" style="display:none; margin-top:8px;" class="chip-bar"></div>
      </div>

      <div class="form-group">
        <label>6. Khoảng cách thời gian (giây)</label>
        <div class="chip-bar" id="delay-bar">
          <div class="chip-item" data-delay="0.3">0.3s</div>
          <div class="chip-item" data-delay="0.5">0.5s</div>
          <div class="chip-item active" data-delay="1">1s</div>
          <div class="chip-item" data-delay="1.5">1.5s (An toàn)</div>
          <div class="chip-item" data-delay="2">2s</div>
          <div class="chip-item" data-delay="3">3s</div>
        </div>
        <input type="hidden" id="spam-delay" value="1">
      </div>

      <div class="form-group">
        <label>7. Số lượng Icon cảm xúc cuối câu</label>
        <div class="chip-bar" id="icon-bar">
          <div class="chip-item" data-icon="0">0 (Tắt)</div>
          <div class="chip-item" data-icon="2">2 Icon</div>
          <div class="chip-item active" data-icon="3">3 Icon</div>
          <div class="chip-item" data-icon="5">5 Icon</div>
        </div>
        <input type="hidden" id="icon-count" value="3">
      </div>

      <div class="toggle-grid">
        <div class="toggle-item active" id="tg-antiband" onclick="tgFlag('antiband')">🛡️ Anti-Ban Đa Tầng (Polymorphic)</div>
        <div class="toggle-item active" id="tg-antidieall" onclick="tgFlag('antidieall')">🔒 Anti-Die-All (Circuit Breaker)</div>
        <div class="toggle-item active" id="tg-heading" onclick="tgFlag('heading')">🔠 Chữ Lớn In Đậm Zalo (f_18)</div>
        <div class="toggle-item active" id="tg-multi" onclick="tgFlag('multi')">⚡ Chạy Tất Cả Acc Song Song</div>
        <div class="toggle-item" id="tg-all" onclick="tgFlag('all')">📢 Nhắc Cả Nhóm (@All Liên Tục)</div>
        <div class="toggle-item active" id="tg-emoji" onclick="tgFlag('emoji')">🎭 Sử Dụng Icon Cuối Câu</div>
      </div>

      <div class="form-group">
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer; font-size:11.5px; color:var(--txt-0);">
          <input type="checkbox" id="tg-tag" onchange="tgTag()" style="width:16px; height:16px;">
          📌 Mở danh sách tích chọn thành viên nhóm Zalo để Tag liên tục
        </label>
        <div id="tag-wrap" style="display:none; margin-top:10px;">
          <div class="form-group"><select id="member-acc-select"><option value="">-- Chọn tài khoản quét thành viên --</option></select></div>
          <div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px;">
            <button class="btn-pill dark" onclick="loadMembers()">Nạp Danh Sách Thành Viên</button>
            <button class="btn-pill green" onclick="selectAllMembers()">Chọn Tất Cả</button>
            <button class="btn-pill danger" onclick="clearAllMembers()">Bỏ Chọn Tất Cả</button>
          </div>
          <div class="form-group" style="margin-bottom:8px;">
            <input type="text" id="search-member-inp" placeholder="Tìm kiếm tên thành viên..." oninput="filterMembers()" style="padding:8px 12px; font-size:11.5px;">
          </div>
          <div style="font-size:11px; font-weight:800; color:var(--noel-gold); margin-bottom:6px;">
            ĐÃ CHỌN: <span id="tag-count" style="color:var(--noel-red); font-weight:900;">0</span> THÀNH VIÊN
          </div>
          <div class="box-list" id="tag-selector" style="margin-top:8px; max-height:220px; display:none;"></div>
        </div>
      </div>
    </div>

    <div style="text-align:center; margin-bottom:18px;">
      <button class="btn-round action-start" onclick="startSpam()" title="Bắt đầu chạy"><svg viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3"/></svg></button>
      <button class="btn-round action-stop" onclick="stopAll()" title="Dừng toàn bộ"><svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg></button>
    </div>

    <div class="card">
      <h2><span>⚙️ Tiến Trình Đang Hoạt Động (Web & Khung Chat Zalo)</span></h2>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Mã</th><th>Nguồn</th><th>Chế độ</th><th>Đã gửi</th><th>Trạng thái</th><th>Thao tác</th></tr></thead>
          <tbody id="tasks-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 5: SELF-BOT LỆNH KHUNG CHAT ZALO 24/7 -->
  <div class="panel" id="panel-chatbot">
    <div class="card">
      <h2>
        <span>🤖 Điều Khiển Bằng Lệnh Trực Tiếp Trên Khung Chat Zalo (Khỏi Cần Bật Web)</span>
        <button class="btn-pill ocean" onclick="loadBotLogs()">🔄 Làm Mới Nhật Ký</button>
      </h2>

      <div class="hint-banner">
        ✨ <b>Cách hoạt động:</b> Khi bạn đã thêm tài khoản Zalo (IMEI + Cookie) vào hệ thống, luồng <b>Self-Bot 24/7</b> sẽ tự động lắng nghe ngầm. Bạn có thể đóng trang Web này lại, mở ứng dụng Zalo trên điện thoại hoặc PC, vào <b>bất kỳ nhóm hoặc khung chat nào</b> và gõ các lệnh dưới đây để điều khiển trực tiếp!
      </div>

      <div class="table-wrap" style="margin-bottom:14px;">
        <table class="table">
          <thead>
            <tr><th>Cú pháp gõ vào khung chat Zalo</th><th>Chức năng thực thi tự động</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><span class="cmd-badge">.spam Nội dung cần gửi @TênNgườiĐó</span></td>
              <td>Chạy gửi siêu nhanh nội dung đó và <b>liên tục tag @TênNgườiĐó</b> ở cuối mỗi tin cho đến khi bạn gõ <code>.stop</code></td>
            </tr>
            <tr>
              <td><span class="cmd-badge">.spam Nội dung thông báo @All</span></td>
              <td>Chạy gửi liên tục nội dung và <b>tag @All (Cả nhóm)</b> liên tục đến khi bạn gõ <code>.stop</code></td>
            </tr>
            <tr>
              <td><span class="cmd-badge">.nhay Dòng 1; Dòng 2; Dòng 3 @Tên</span></td>
              <td>Chạy chế độ <b>Treo Nhây</b> từng dòng riêng biệt kèm đổi màu chữ Zalo và <b>tag liên tục @Tên</b> ở cuối</td>
            </tr>
            <tr>
              <td><span class="cmd-badge">.ngon Đoạn 1; Đoạn 2 @Tên</span></td>
              <td>Chạy chế độ <b>Treo Ngôn</b> (nhiều dòng trong 1 tin) kèm đổi màu chữ và <b>tag liên tục @Tên</b></td>
            </tr>
            <tr>
              <td><span class="cmd-badge">.file 1 @TênNgườiĐó</span> hoặc <span class="cmd-badge">.file 1 @All</span></td>
              <td>Lấy trực tiếp <b>File văn bản số 1</b> đã tải lên Web để chạy ngay tại khung chat đó và <b>tag liên tục @Tên / @All</b></td>
            </tr>
            <tr>
              <td><span class="cmd-badge">.file 1 delay=0.5 color=word_rainbow @Tên</span></td>
              <td>Tuỳ chỉnh tốc độ delay, kiểu màu cầu vồng từng chữ và tag liên tục người ở cuối câu</td>
            </tr>
            <tr>
              <td><span class="cmd-badge">.files</span> hoặc <span class="cmd-badge">.dsfile</span></td>
              <td>Hiển thị danh sách ID và tên các file <code>.txt</code> đã lưu trên hệ thống ngay trong khung chat</td>
            </tr>
            <tr>
              <td><span class="cmd-badge">.stop</span> hoặc <span class="cmd-badge">.dung</span> hoặc <span class="cmd-badge">.tat</span></td>
              <td><b>Dừng ngay lập tức</b> tiến trình đang chạy tại khung chat đó (hoặc <code>.stopall</code> để dừng tất cả)</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <h2><span>📜 Nhật Ký Lệnh Đã Nhận Từ Khung Chat Zalo</span></h2>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Thời gian</th><th>Acc ID</th><th>Hội thoại</th><th>Câu lệnh đã gõ</th><th>Kết quả xử lý</th></tr></thead>
          <tbody id="bot-logs-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 6: HƯỚNG DẪN TOKEN & AN TOÀN -->
  <div class="panel" id="panel-guide">
    <div class="card">
      <h2><span>📖 Hướng Dẫn Lấy Cookie Zalo & Token Discord An Toàn</span></h2>
      <div style="line-height:1.7; font-size:12.5px; color:var(--txt-1);">
        <h3 style="color:var(--noel-gold); font-size:14px; margin-bottom:6px;">1. Cách Lấy IMEI & Cookie Zalo Nhanh Nhất</h3>
        <ol style="padding-left:18px; margin-bottom:14px;">
          <li>Đăng nhập Zalo Web tại <code>https://chat.zalo.me</code> trên máy tính hoặc trình duyệt Kiwi Browser (điện thoại).</li>
          <li>Sử dụng tiện ích <b>ZaloDataExtractor</b> hoặc mở F12 Console gõ <code>localStorage.getItem('z_uuid')</code> để lấy <b>IMEI</b> và sao chép <b>Cookie JSON</b>.</li>
          <li>Dán vào mục <b>Tài khoản</b> trên hệ thống. Tích bật <b>Nhận lệnh trực tiếp trên khung chat Zalo 24/7</b> để có thể gõ lệnh ở bất kỳ khung chat nào mà không cần mở lại Web.</li>
        </ol>

        <h3 style="color:var(--noel-gold); font-size:14px; margin-bottom:6px;">2. Cơ Chế Bảo Vệ Kép Anti-Ban & Anti-Die-All Pro v4.0</h3>
        <ul style="padding-left:18px;">
          <li><b>Đổi màu chữ Zalo RichText chuẩn (ver: 0):</b> Tương thích hoàn toàn với cả Zalo Điện Thoại (iOS/Android) và Zalo PC/Web thông qua cấu trúc <code>params.styles</code> chính quy.</li>
          <li><b>Polymorphic Anti-Ban:</b> Tự động biến thiên mã băm (hash) tin nhắn bằng chữ ký vi phân tàng hình ở từng lượt gửi, ngăn chặn hoàn toàn bộ lọc quét nội dung trùng lặp của Zalo.</li>
          <li><b>Circuit Breaker Anti-Die-All:</b> Tự động theo dõi tần suất gửi (RPM) và mã phản hồi của máy chủ Zalo/Discord. Khi phát hiện dấu hiệu giới hạn tốc độ, hệ thống tự động cách ly tạm thời tài khoản đó và điều phối sang tài khoản khác để không bao giờ bị khóa hàng loạt.</li>
        </ul>
      </div>
    </div>
  </div>

</div>

<!-- BOTTOM DOCK 6 TABS -->
<div class="bottom-dock">
  <button class="dock-btn active" data-tab="accounts">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
    <span>Tài khoản</span>
  </button>
  <button class="dock-btn" data-tab="boxes">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
    <span>Hội thoại</span>
  </button>
  <button class="dock-btn" data-tab="files">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
    <span>File Siêu Tốc</span>
  </button>
  <button class="dock-btn" data-tab="spam">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
    <span>Gửi Tin</span>
  </button>
  <button class="dock-btn" data-tab="chatbot">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
    <span>Lệnh Chat</span>
  </button>
  <button class="dock-btn" data-tab="guide">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
    <span>Hướng Dẫn</span>
  </button>
</div>
<script>
var flags = { antiband: true, antidieall: true, heading: true, multi: true, all: false, emoji: true };
var selectedBoxes = [];
var selectedTags = [];
var _boxes = [];
var _members = [];
var currentMode = "fast";
var colorMode = "rainbow";
var fixedColor = "red";
var currentPlatform = "zalo";
var currentBotType = 1;
var ZALO_PALETTE = [];

var Toast = (function(){
  var stack = null;
  function ensure(){ if(!stack) stack = document.getElementById('toast-stack'); return stack; }
  function show(msg, title, duration){
    duration = duration || 1800;
    var s = ensure();
    if(!s) return;
    s.querySelectorAll('.toast').forEach(el => el.remove());

    var el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = '<div class="t-head">🎄 ' + (title || 'Thông Báo') + '</div>' +
      '<div class="t-body">' + msg + '</div>';
    s.appendChild(el);

    var timer = setTimeout(dismiss, duration);
    function dismiss(){
      clearTimeout(timer);
      el.classList.add('swipe-up');
      el.addEventListener('animationend', () => el.remove(), { once: true });
    }
  }
  return {
    success: (m, t, d) => show(m, t || 'Thành công', d),
    error: (m, t, d) => show(m, t || 'Lỗi', d || 2400),
    info: (m, t, d) => show(m, t || 'Thông báo', d)
  };
})();

document.querySelectorAll('.bottom-dock .dock-btn').forEach(b => {
  b.addEventListener('click', () => {
    document.querySelectorAll('.bottom-dock .dock-btn').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    var p = document.getElementById('panel-' + b.dataset.tab);
    if(p) p.classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    refreshAll();
  });
});

function selectPlat(plat){
  currentPlatform = plat;
  document.getElementById('add-platform').value = plat;
  document.querySelectorAll('#platform-selector .chip-item').forEach(x => x.classList.remove('active'));
  document.querySelector('#platform-selector [data-plat="' + plat + '"]').classList.add('active');
  document.getElementById('zalo-input-fields').style.display = (plat === 'zalo') ? 'block' : 'none';
  document.getElementById('discord-input-fields').style.display = (plat === 'zalo') ? 'none' : 'block';
}

function selectBotType(isBot){
  currentBotType = isBot;
  document.getElementById('add-is-bot').value = isBot;
  document.querySelectorAll('#bot-type-selector .chip-item').forEach(x => x.classList.remove('active'));
  document.querySelector('#bot-type-selector [data-bot="' + isBot + '"]').classList.add('active');
}

document.querySelectorAll('#mode-selector .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#mode-selector .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    currentMode = c.dataset.mode;
    document.getElementById('spam-mode').value = currentMode;
  });
});

document.querySelectorAll('#color-mode-bar .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#color-mode-bar .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    colorMode = c.dataset.cmode;
    document.getElementById('color-mode').value = colorMode;
    document.getElementById('fixed-colors-wrap').style.display = (colorMode === 'fixed') ? 'flex' : 'none';
  });
});

document.querySelectorAll('#delay-bar .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#delay-bar .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    document.getElementById('spam-delay').value = c.dataset.delay;
  });
});

document.querySelectorAll('#icon-bar .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#icon-bar .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    document.getElementById('icon-count').value = c.dataset.icon;
  });
});

function tgFlag(name){
  flags[name] = !flags[name];
  var el = document.getElementById('tg-' + name);
  if(el) el.classList.toggle('active', flags[name]);
}

function tgTag(){
  var c = document.getElementById('tg-tag');
  document.getElementById('tag-wrap').style.display = c.checked ? 'block' : 'none';
}

function handleFileSelect(input){
  if(input.files && input.files.length > 0){
    var f = input.files[0];
    var mb = (f.size / (1024 * 1024)).toFixed(2);
    document.getElementById('upload-txt').textContent = "Đã chọn: " + f.name + " (" + mb + " MB)";
    document.getElementById('upload-txt').style.color = "var(--noel-gold)";
  }
}

async function api(url, opts = {}){
  try {
    var r = await fetch(url, Object.assign({}, opts, {
      headers: Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {})
    }));
    return await r.json();
  } catch(e){
    return { error: 'Lỗi kết nối: ' + e.message };
  }
}

async function uploadLogo(){
  var inp = document.getElementById('file-input');
  if(!inp.files || !inp.files.length) return Toast.error('Vui lòng chọn hình ảnh logo');
  var fd = new FormData();
  fd.append('logo', inp.files[0]);
  Toast.info('Đang cập nhật logo...');
  var r = await fetch('/api/upload_logo', { method: 'POST', body: fd }).then(x => x.json());
  if(r.ok){
    Toast.success('Cập nhật logo thành công!');
    document.getElementById('header-logo').src = '/static/logo.png?t=' + Date.now();
    inp.value = '';
  } else {
    Toast.error(r.error || 'Lỗi tải ảnh');
  }
}

async function loadAccounts(){
  var accs = await api('/api/accounts');
  if(!Array.isArray(accs)) accs = [];
  document.getElementById('st-acc-count').textContent = accs.length;

  var botCount = accs.filter(a => (a.platform || 'zalo') === 'zalo' && a.chat_cmd_enabled).length;
  document.getElementById('st-bot-count').textContent = botCount + ' ACC BẬT';

  var tb = document.getElementById('accounts-tbody');
  tb.innerHTML = accs.map(a => {
    var isZalo = (a.platform || 'zalo') === 'zalo';
    var platIcon = isZalo ? '🔷 Zalo' : '🟣 Discord';
    var realName = a.display_name || a.zalo_name || a.username || a.label;
    var isLive = (a.status === 'live');
    var badge = isLive
      ? '<span style="color:#2ed573; font-weight:800;">● ONLINE</span>'
      : '<span style="color:#ff4757; font-weight:800;">● OFFLINE</span>';

    var health = a.health || {};
    var circuit = health.circuit || 'CLOSED';
    var healthBadge = '<span style="color:#2ed573; font-weight:800;">🟢 An Toàn (RPM: ' + (health.rpm || 0) + ')</span>';
    if(circuit === 'OPEN'){
      healthBadge = '<span style="color:#ff4757; font-weight:800;">🔴 Cách Ly (' + (health.cooldown_remaining || 0) + 's)</span>';
    } else if(circuit === 'HALF_OPEN'){
      healthBadge = '<span style="color:#ffa502; font-weight:800;">🟡 Thăm Dò</span>';
    }

    var cmdToggle = isZalo
      ? `<button class="btn-pill ${a.chat_cmd_enabled ? 'green' : 'light'}" onclick="toggleChatCmd(${a.id})" style="padding:4px 10px; font-size:9.5px;">
           ${a.chat_cmd_enabled ? '⚡ Đang Bật 24/7' : 'Đã Tắt'}
         </button>`
      : '<span style="color:var(--txt-2); font-size:10px;">Web Mode</span>';

    return `<tr>
      <td>#${a.id}</td>
      <td><b>${platIcon}</b></td>
      <td><b style="color:var(--noel-gold);">${realName}</b><br><span style="font-size:9.5px; color:var(--txt-2);">${a.label}</span></td>
      <td>${cmdToggle}</td>
      <td>${healthBadge}</td>
      <td id="status-${a.id}">${badge}</td>
      <td>
        <button class="btn-pill light" onclick="checkAccount(${a.id})" style="padding:4px 8px; font-size:9.5px;">Kiểm tra</button>
        <button class="btn-pill danger" onclick="delAcc(${a.id})" style="padding:4px 8px; font-size:9.5px;">Xóa</button>
      </td>
    </tr>`;
  }).join('') || '<tr><td colspan="7" style="text-align:center; color:var(--txt-2); padding:16px;">Chưa có tài khoản nào được lưu</td></tr>';

  var s1 = document.getElementById('load-acc-select');
  var s2 = document.getElementById('member-acc-select');
  var prev1 = s1.value, prev2 = s2.value;
  var opts = '<option value="">-- Chọn tài khoản --</option>' + accs.map(a => `<option value="${a.id}">[${(a.platform||'zalo').toUpperCase()}] ${a.label} (${a.display_name||'Sẵn sàng'})</option>`).join('');
  s1.innerHTML = opts; s2.innerHTML = opts;
  if(prev1) s1.value = prev1;
  if(prev2) s2.value = prev2;
}

async function toggleChatCmd(aid){
  var r = await api('/api/accounts/' + aid + '/toggle_chat_cmd', { method: 'POST' });
  if(r.ok){
    Toast.success(r.chat_cmd_enabled ? 'Đã BẬT nhận lệnh trực tiếp trên khung chat Zalo 24/7!' : 'Đã tắt nhận lệnh trên khung chat.');
    loadAccounts();
  }
}

async function checkAccount(aid){
  Toast.info('Đang kiểm tra kết nối...');
  var r = await api(`/api/accounts/${aid}/check`, { method: 'POST' });
  if(r.ok){
    Toast.success('Tài khoản hoạt động tốt!');
  } else {
    Toast.error('Kết nối thất bại: ' + (r.error || 'Hết hạn'));
  }
  loadAccounts();
}

async function checkAllAccounts(){
  Toast.info('Đang kiểm tra toàn bộ tài khoản...');
  var r = await api('/api/accounts/check_all', { method: 'POST' });
  Toast.success(`Hoàn tất: ${r.live}/${r.total} tài khoản đang hoạt động`);
  loadAccounts();
}

async function addAccount(){
  var plat = document.getElementById('add-platform').value;
  var label = document.getElementById('add-label').value.trim();

  if(plat === 'zalo'){
    var imei = document.getElementById('add-imei').value.trim();
    var cookies = document.getElementById('add-cookies').value.trim();
    var chat_cmd_enabled = document.getElementById('add-chat-cmd').checked ? 1 : 0;
    var allow_all_cmd = document.getElementById('add-allow-all').checked ? 1 : 0;
    if(!imei || !cookies) return Toast.error('Vui lòng điền đủ IMEI và Cookie Zalo');
    Toast.info('Đang xác thực Zalo & khởi chạy Self-Bot 24/7...');
    var r = await api('/api/accounts/add_zalo', {
      method: 'POST',
      body: JSON.stringify({ label, imei, cookies, chat_cmd_enabled, allow_all_cmd })
    });
    if(r.error) return Toast.error(r.error);
    Toast.success('Đã lưu Zalo & kích hoạt lắng nghe lệnh khung chat 24/7!');
    document.getElementById('add-imei').value = '';
    document.getElementById('add-cookies').value = '';
  } else {
    var token = document.getElementById('add-token').value.trim();
    var is_bot = parseInt(document.getElementById('add-is-bot').value) || 1;
    if(!token) return Toast.error('Vui lòng nhập Token Discord');
    Toast.info('Đang xác thực Token Discord...');
    var r = await api('/api/accounts/add_discord', {
      method: 'POST',
      body: JSON.stringify({ label, token, is_bot })
    });
    if(r.error) return Toast.error(r.error);
    Toast.success('Thêm tài khoản Discord thành công!');
    document.getElementById('add-token').value = '';
  }
  document.getElementById('add-label').value = '';
  refreshAll();
}

async function delAcc(id){
  if(!confirm('Xác nhận xóa tài khoản #' + id + '?')) return;
  await api('/api/accounts/' + id, { method: 'DELETE' });
  Toast.success('Đã xóa tài khoản');
  refreshAll();
}

function renderBoxList(){
  var q = (document.getElementById('search-box-inp').value || '').toLowerCase().trim();
  var bl = document.getElementById('box-list');
  var filtered = _boxes.filter(b => !q || (b.name || '').toLowerCase().includes(q) || String(b.id).includes(q));
  bl.innerHTML = filtered.map(b => {
    var isSel = selectedBoxes.some(x => String(x.id) === String(b.id));
    return `<div class="box-item ${isSel ? 'selected' : ''}" onclick="tgBoxById('${b.id}')">
      <div class="check-mark">${isSel ? '✓' : ''}</div>
      <div><div class="b-title">${b.name}</div><div class="b-sub">ID: ${b.id} | Loại: ${b.type}</div></div>
    </div>`;
  }).join('') || '<div style="text-align:center; padding:14px; color:var(--txt-2);">Không tìm thấy hội thoại phù hợp</div>';
}

function filterBoxes(){ renderBoxList(); }

async function loadBoxes(){
  var aid = document.getElementById('load-acc-select').value;
  if(!aid) return Toast.error('Vui lòng chọn tài khoản trước');
  Toast.info('Đang nạp danh sách hội thoại / kênh...');
  var r = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  _boxes = r.boxes || [];
  selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
  renderBoxList();
  Toast.success('Đã nạp ' + _boxes.length + ' hội thoại');
}

function tgBoxById(bid){
  var b = _boxes.find(x => String(x.id) === String(bid));
  if(!b) return;
  var exists = selectedBoxes.some(x => String(x.id) === String(bid));
  if(exists){
    selectedBoxes = selectedBoxes.filter(x => String(x.id) !== String(bid));
  } else {
    selectedBoxes.push(b);
  }
  document.getElementById('selected-count').textContent = selectedBoxes.length;
  renderBoxList();
}

function selectAllBoxes(){
  selectedBoxes = _boxes.slice();
  document.getElementById('selected-count').textContent = selectedBoxes.length;
  renderBoxList();
}

function clearAllBoxes(){
  selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
  renderBoxList();
}

function renderMemberItems(){
  var sel = document.getElementById('tag-selector');
  var query = (document.getElementById('search-member-inp').value || '').toLowerCase().trim();
  var filtered = _members.filter(m => !query || m.name.toLowerCase().includes(query) || m.id.includes(query));
  sel.innerHTML = filtered.map(m => {
    var isSel = selectedTags.some(t => t.id === m.id);
    return `<div class="box-item ${isSel ? 'selected' : ''}" onclick="toggleMemberById('${m.id}')">
      <div class="check-mark">${isSel ? '✓' : ''}</div>
      <div><div class="b-title">${m.name}</div><div class="b-sub">UID: ${m.id}</div></div>
    </div>`;
  }).join('') || '<div style="padding:14px; text-align:center; color:var(--txt-2);">Không tìm thấy thành viên</div>';
}

function toggleMemberById(mid){
  var m = _members.find(x => x.id === mid);
  if(!m) return;
  if(selectedTags.some(t => t.id === mid)){
    selectedTags = selectedTags.filter(t => t.id !== mid);
  } else {
    selectedTags.push({ id: m.id, uid: m.id, name: m.name });
  }
  document.getElementById('tag-count').textContent = selectedTags.length;
  renderMemberItems();
}

function selectAllMembers(){
  selectedTags = _members.map(m => ({ id: m.id, uid: m.id, name: m.name }));
  document.getElementById('tag-count').textContent = selectedTags.length;
  renderMemberItems();
  Toast.success('Đã chọn tất cả ' + selectedTags.length + ' thành viên');
}

function clearAllMembers(){
  selectedTags = [];
  document.getElementById('tag-count').textContent = '0';
  renderMemberItems();
}

function filterMembers(){ renderMemberItems(); }

async function loadMembers(){
  var aid = document.getElementById('member-acc-select').value;
  if(!aid) return Toast.error('Vui lòng chọn tài khoản quét');
  var box = selectedBoxes.find(b => b.type === 'group');
  if(!box) return Toast.error('Vui lòng chọn ít nhất 1 nhóm Zalo ở mục Hội Thoại trước');
  Toast.info('Đang quét thành viên nhóm ' + box.name + '...');
  var r = await api('/api/accounts/' + aid + '/members/' + box.id, { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  _members = r.members || [];
  selectedTags = [];
  document.getElementById('tag-count').textContent = '0';
  document.getElementById('tag-selector').style.display = 'block';
  renderMemberItems();
  Toast.success('Đã nạp ' + _members.length + ' thành viên');
}

// TẢI FILE NHIỀU MB SIÊU TỐC VỚI THANH TIẾN TRÌNH THỜI GIAN THỰC (XHR STREAM)
function uploadFileFast(){
  var inp = document.getElementById('file-input');
  if(!inp.files || !inp.files.length) return Toast.error('Vui lòng chọn tập tin văn bản .txt trước');
  var fileObj = inp.files[0];
  var fd = new FormData();
  fd.append('file', fileObj);

  var progBox = document.getElementById('upload-prog-box');
  var progBar = document.getElementById('upload-prog-bar');
  var progPct = document.getElementById('upload-prog-pct');
  var progStatus = document.getElementById('upload-prog-status');

  progBox.style.display = 'block';
  progBar.style.width = '0%';
  progPct.textContent = '0%';
  progStatus.textContent = 'Đang truyền tải luồng dữ liệu siêu tốc...';

  var startTime = Date.now();
  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/files/upload', true);

  xhr.upload.onprogress = function(e){
    if(e.lengthComputable){
      var pct = Math.round((e.loaded / e.total) * 100);
      var elapsed = Math.max(0.1, (Date.now() - startTime) / 1000);
      var mbps = ((e.loaded / (1024 * 1024)) / elapsed).toFixed(1);
      progBar.style.width = pct + '%';
      progPct.textContent = pct + '% (' + mbps + ' MB/s)';
      if(pct >= 100){
        progStatus.textContent = 'Đang lập chỉ mục bộ đệm RAM tại Server...';
      }
    }
  };

  xhr.onload = function(){
    progBox.style.display = 'none';
    try {
      var r = JSON.parse(xhr.responseText);
      if(r.error) return Toast.error(r.error);
      Toast.success(`Đã nạp siêu tốc: ${r.lines} khối (${r.total_lines || r.lines} dòng)!`);
      inp.value = '';
      document.getElementById('upload-txt').textContent = "Nhấn để chọn tệp Văn bản (.txt dung lượng lớn) hoặc Ảnh Logo";
      loadFiles();
    } catch(err){
      Toast.error('Lỗi phản hồi khi tải file');
    }
  };

  xhr.onerror = function(){
    progBox.style.display = 'none';
    Toast.error('Lỗi mạng khi tải tệp lên');
  };

  xhr.send(fd);
}

async function loadFiles(){
  var files = await api('/api/files');
  if(!Array.isArray(files)) files = [];
  var list = document.getElementById('files-list');
  list.innerHTML = files.map(f => {
    var sizeStr = (f.size > 1024 * 1024)
      ? (f.size / (1024 * 1024)).toFixed(2) + ' MB'
      : (f.size / 1024).toFixed(1) + ' KB';
    return `<div class="box-item" style="cursor:default;">
      <div style="flex:1;">
        <div class="b-title">📄 [ID: ${f.id}] ${f.filename}</div>
        <div class="b-sub">${f.lines} khối ngôn | ${f.total_lines || f.lines} dòng đơn | Dung lượng: ${sizeStr} | Gõ lệnh Zalo: <b>.file ${f.id} @Tên</b></div>
      </div>
      <button class="btn-pill danger" onclick="delFile(${f.id})" style="padding:4px 10px; font-size:9.5px;">Xóa</button>
    </div>`;
  }).join('') || '<div style="text-align:center; padding:14px; color:var(--txt-2);">Chưa có tập tin nào</div>';

  var s = document.getElementById('spam-file-select');
  var prevVal = s.value;
  s.innerHTML = '<option value="">-- Không dùng file (Dùng nội dung nhập bên dưới) --</option>' +
    files.map(f => `<option value="${f.id}">[ID: ${f.id}] ${f.filename} (${f.lines} khối | ${f.total_lines || f.lines} dòng)</option>`).join('');
  if(prevVal) s.value = prevVal;
}

async function delFile(id){
  if(!confirm('Xác nhận xóa tệp tin #' + id + '?')) return;
  await api('/api/files/' + id, { method: 'DELETE' });
  Toast.success('Đã xóa tệp tin');
  loadFiles();
}

// KHỞI CHẠY GỬI TIN SIÊU TỐC: TRUYỀN TRỰC TIẾP FILE_ID LÊN SERVER (KHÔNG TẢI NGƯỢC VỀ TRÌNH DUYỆT)
async function startSpam(){
  if(!selectedBoxes.length) return Toast.error('Chưa chọn hội thoại hoặc kênh nhận tin! Hãy qua tab Hội thoại để chọn.');
  var fid = document.getElementById('spam-file-select').value;
  var direct = document.getElementById('spam-messages').value.trim();
  var quickTailTag = document.getElementById('quick-tail-tag').value.trim();

  if(!fid && !direct) return Toast.error('Vui lòng chọn tập tin văn bản hoặc nhập trực tiếp nội dung cần gửi!');

  var blocks = [];
  if(!fid && direct){
    if(currentMode === "treo_ngon" || currentMode === "treo_nhay"){
      blocks = [direct];
    } else {
      blocks = direct.includes(';') ? direct.split(';').map(m => m.trim()).filter(Boolean) : [direct];
    }
  }

  var delay = parseFloat(document.getElementById('spam-delay').value) || 1;
  var iconCount = flags.emoji ? (parseInt(document.getElementById('icon-count').value) || 3) : 0;
  var tagUsers = document.getElementById('tg-tag').checked ? selectedTags : [];

  var payload = {
    targets: selectedBoxes,
    file_id: fid ? parseInt(fid) : null,
    blocks: blocks,
    quick_tail_tag: quickTailTag,
    delay: delay,
    use_emoji: flags.emoji,
    icon_count: iconCount,
    tag_users: tagUsers,
    tag_all: flags.all,
    is_heading: flags.heading,
    multi_acc: flags.multi,
    antiband: flags.antiband,
    antidieall: flags.antidieall,
    mode: currentMode,
    color_mode: colorMode,
    fixed_color: fixedColor
  };

  var res = await api('/api/tasks/start', { method: 'POST', body: JSON.stringify(payload) });
  if(res.error) return Toast.error(res.error);
  Toast.success('🚀 Đã khởi chạy tiến trình siêu tốc!');
  loadTasks();
}

async function stopAll(){
  await api('/api/tasks/stop_all', { method: 'POST' });
  Toast.info('🛑 Đã dừng toàn bộ tiến trình');
  loadTasks();
}

async function loadTasks(){
  var tasks = await api('/api/tasks');
  if(!Array.isArray(tasks)) tasks = [];

  var runningCount = tasks.filter(t => t.status === 'running').length;
  document.getElementById('st-task-count').textContent = runningCount;

  var totalSent = 0;
  tasks.forEach(t => {
    try {
      var st = JSON.parse(t.stats || '{}');
      totalSent += (st.sent || 0);
    } catch(e){}
  });
  document.getElementById('st-sent-total').textContent = 'Đã gửi: ' + totalSent + ' tin';

  var tb = document.getElementById('tasks-tbody');
  tb.innerHTML = tasks.map(t => {
    var running = (t.status === 'running');
    var st = {};
    var meta = {};
    try { st = JSON.parse(t.stats || '{}'); } catch(e){}
    try { meta = JSON.parse(t.meta || '{}'); } catch(e){}
    var srcBadge = (meta.source === 'chat')
      ? '<span class="cmd-badge">💬 Lệnh Chat</span>'
      : '<span style="color:var(--noel-cyan); font-weight:800;">🌐 Web UI</span>';
    return `<tr>
      <td><code>${t.id.slice(-7)}</code></td>
      <td>${srcBadge}</td>
      <td><b>${t.type}</b></td>
      <td><b style="color:var(--noel-gold);">${st.sent || 0}</b> tin</td>
      <td>${running ? '<span style="color:#2ed573; font-weight:800;">● Đang gửi</span>' : '<span style="color:var(--txt-2);">Đã dừng</span>'}</td>
      <td>${running ? `<button class="btn-pill danger" onclick="stopTask('${t.id}')" style="padding:4px 10px; font-size:9.5px;">Dừng</button>` : ''}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="6" style="text-align:center; padding:14px; color:var(--txt-2);">Chưa có tiến trình nào</td></tr>';
}

async function stopTask(tid){
  await api('/api/tasks/' + tid + '/stop', { method: 'POST' });
  Toast.info('Đã dừng tiến trình');
  loadTasks();
}

async function loadBotLogs(){
  var logs = await api('/api/bot_logs');
  if(!Array.isArray(logs)) logs = [];
  var tb = document.getElementById('bot-logs-tbody');
  tb.innerHTML = logs.map(l => {
    var d = new Date((l.created_at || 0) * 1000);
    var tStr = d.toLocaleTimeString('vi-VN');
    return `<tr>
      <td>${tStr}</td>
      <td>#${l.acc_id}</td>
      <td><code>${l.thread_id}</code></td>
      <td><span class="cmd-badge">${l.cmd_text}</span></td>
      <td style="color:#2ed573; font-weight:700;">${l.action_taken}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="5" style="text-align:center; padding:14px; color:var(--txt-2);">Chưa có lệnh nào được gõ từ khung chat Zalo</td></tr>';
}

async function loadColors(){
  var cols = await api('/api/colors');
  if(Array.isArray(cols)){
    ZALO_PALETTE = cols;
    var wrap = document.getElementById('fixed-colors-wrap');
    wrap.innerHTML = cols.map(c => `<div class="chip-item ${c.id === fixedColor ? 'active' : ''}" id="fc-${c.id}" style="border-color:${c.hex}; color:${c.hex};" onclick="setFixedColor('${c.id}')">${c.name}</div>`).join('');
  }
}

function setFixedColor(cid){
  fixedColor = cid;
  document.querySelectorAll('#fixed-colors-wrap .chip-item').forEach(x => x.classList.remove('active'));
  var el = document.getElementById('fc-' + cid);
  if(el) el.classList.add('active');
}

function refreshAll(){ loadAccounts(); loadFiles(); loadTasks(); loadBotLogs(); }

var snowCanvas = document.getElementById('snow-canvas');
var sCtx = snowCanvas.getContext('2d');
var sW = window.innerWidth, sH = window.innerHeight;
snowCanvas.width = sW; snowCanvas.height = sH;
var flakes = Array.from({ length: 60 }, () => ({
  x: Math.random() * sW, y: Math.random() * sH,
  r: Math.random() * 3.2 + 1.2, dY: Math.random() * 1.2 + 0.5, dX: Math.random() * 0.9 - 0.45, opacity: Math.random() * 0.7 + 0.3
}));
function renderSnow() {
  sCtx.clearRect(0, 0, sW, sH);
  flakes.forEach(f => {
    sCtx.beginPath(); sCtx.arc(f.x, f.y, f.r, 0, Math.PI * 2);
    sCtx.fillStyle = 'rgba(255, 255, 255, ' + f.opacity + ')'; sCtx.fill();
    f.y += f.dY; f.x += f.dX;
    if (f.y > sH) { f.y = -10; f.x = Math.random() * sW; }
    if (f.x > sW) f.x = 0; if (f.x < 0) f.x = sW;
  });
  requestAnimationFrame(renderSnow);
}
renderSnow();
window.addEventListener('resize', () => {
  sW = window.innerWidth; sH = window.innerHeight;
  snowCanvas.width = sW; snowCanvas.height = sH;
});

loadColors();
refreshAll();
setInterval(() => { loadTasks(); loadAccounts(); }, 4000);
</script>
</body>
</html>
"""


# ============================================================
# ROUTES & API ENDPOINTS
# ============================================================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.route("/verify_gate")
def verify_gate():
    return render_template_string(HTML_GATE)


@app.route("/api/verify_human", methods=["POST"])
def api_verify_human():
    session["human_verified"] = True
    return jsonify({"ok": True})


@app.route("/")
@login_required
def index():
    sync_all_zalo_listeners()
    return render_template_string(HTML_INDEX)


@app.route("/login", methods=["GET", "POST"])
def login():
    ip = get_client_ip()
    now = time.time()
    tracker = login_fail_tracker[ip]

    if tracker["locked_until"] > now:
        rem = int(tracker["locked_until"] - now)
        return render_template_string(HTML_LOGIN, error=f"Tạm khóa kết nối do nhập sai quá 5 lần. Thử lại sau {rem} giây.")

    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == APP_PASSWORD:
            session["logged_in"] = True
            login_fail_tracker[ip] = {"count": 0, "locked_until": 0}
            return redirect(url_for("index"))
        else:
            tracker["count"] += 1
            if tracker["count"] >= LOGIN_MAX_FAILS:
                tracker["locked_until"] = now + LOGIN_LOCKOUT_TIME
                return render_template_string(HTML_LOGIN, error="Nhập sai 5 lần! Tạm khóa kết nối trong 15 phút.")
            rem = LOGIN_MAX_FAILS - tracker["count"]
            return render_template_string(HTML_LOGIN, error=f"Mật khẩu không chính xác! Còn {rem} lần thử.")

    return render_template_string(HTML_LOGIN)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/upload_logo", methods=["POST"])
@login_required
def api_upload_logo():
    if "logo" not in request.files:
        return jsonify({"error": "Không có tệp logo"}), 400
    f = request.files["logo"]
    if not f.filename:
        return jsonify({"error": "Tên tệp rỗng"}), 400
    save_path = os.path.join(STATIC_DIR, "logo.png")
    f.save(save_path)
    return jsonify({"ok": True})


@app.route("/api/colors", methods=["GET"])
@login_required
def api_colors():
    return jsonify(ZALO_PALETTE)


@app.route("/api/accounts", methods=["GET"])
@login_required
def api_accounts():
    conn = db()
    rows = conn.execute("SELECT * FROM accounts ORDER BY id DESC").fetchall()
    conn.close()
    out = []
    for r in rows:
        item = dict(r)
        item["health"] = HEALTH_MGR.get_snapshot(r["id"])
        out.append(item)
    return jsonify(out)


@app.route("/api/accounts/add_zalo", methods=["POST"])
@login_required
def api_accounts_add_zalo():
    d = request.json or {}
    label = d.get("label", "").strip() or "zalo_" + str(int(time.time()))
    imei = d.get("imei", "").strip()
    ck = d.get("cookies", "").strip()
    chat_cmd_enabled = int(d.get("chat_cmd_enabled", 1))
    allow_all_cmd = int(d.get("allow_all_cmd", 0))

    if not imei or not ck:
        return jsonify({"error": "Vui lòng nhập đủ IMEI và Cookie Zalo"}), 400
    try:
        ck_obj = json.loads(ck) if isinstance(ck, str) else ck
        z = Zalo(imei, ck_obj)
        st = "live"
    except Exception as e:
        return jsonify({"error": "Không thể đăng nhập Zalo: " + str(e)}), 400

    conn = db()
    conn.execute("""
        INSERT INTO accounts (
            platform, label, imei, cookies, chat_cmd_enabled, allow_all_cmd,
            added_at, uid, display_name, zalo_name, username, status
        )
        VALUES ('zalo', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        label, imei, json.dumps(ck_obj, ensure_ascii=False), chat_cmd_enabled, allow_all_cmd,
        time.time(), z.uid, z.display_name or "", z.zalo_name or "", z.username or "", st
    ))
    conn.commit()
    conn.close()

    # Tự động kích hoạt luồng Self-Bot 24/7 ngay khi lưu Cookie + IMEI
    sync_all_zalo_listeners()
    return jsonify({"ok": True, "label": label, "uid": z.uid, "name": z.display_name})


@app.route("/api/accounts/add_discord", methods=["POST"])
@login_required
def api_accounts_add_discord():
    d = request.json or {}
    label = d.get("label", "").strip() or "discord_" + str(int(time.time()))
    token = d.get("token", "").strip()
    is_bot = int(d.get("is_bot", 1))
    if not token:
        return jsonify({"error": "Vui lòng nhập Token Discord"}), 400

    try:
        bot = DiscordBot(token, is_bot=bool(is_bot))
        if not bot.check():
            return jsonify({"error": "Token Discord không hợp lệ hoặc đã bị vô hiệu hóa"}), 400
        st = "live"
    except Exception as e:
        return jsonify({"error": "Lỗi xác thực Discord: " + str(e)}), 400

    conn = db()
    conn.execute("""
        INSERT INTO accounts (platform, label, token, is_bot, added_at,
                             uid, display_name, username, status)
        VALUES ('discord', ?, ?, ?, ?, ?, ?, ?, ?)
    """, (label, token, is_bot, time.time(),
          bot.user_id, bot.display_name or bot.username, bot.username, st))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "label": label})


@app.route("/api/accounts/<int:aid>/toggle_chat_cmd", methods=["POST"])
@login_required
def api_toggle_chat_cmd(aid):
    conn = db()
    row = conn.execute("SELECT id, chat_cmd_enabled FROM accounts WHERE id = ?", (aid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Không tìm thấy tài khoản"}), 404
    new_val = 0 if row["chat_cmd_enabled"] else 1
    conn.execute("UPDATE accounts SET chat_cmd_enabled = ? WHERE id = ?", (new_val, aid))
    conn.commit()
    conn.close()
    sync_all_zalo_listeners()
    return jsonify({"ok": True, "chat_cmd_enabled": new_val})


@app.route("/api/accounts/<int:aid>", methods=["DELETE"])
@login_required
def api_accounts_delete(aid):
    if aid in ACTIVE_LISTENERS:
        ACTIVE_LISTENERS[aid].stop()
        ACTIVE_LISTENERS.pop(aid, None)
    conn = db()
    conn.execute("DELETE FROM accounts WHERE id = ?", (aid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/accounts/<int:aid>/check", methods=["POST"])
@login_required
def api_accounts_check(aid):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Không tìm thấy tài khoản"}), 404

    plat = row["platform"] or "zalo"
    try:
        if plat == "zalo":
            z = Zalo(row["imei"], json.loads(row["cookies"]))
            name = z.display_name
        else:
            bot = DiscordBot(row["token"], is_bot=bool(row["is_bot"]))
            if not bot.check():
                raise Exception("Token không hợp lệ")
            name = bot.display_name or bot.username

        conn.execute("UPDATE accounts SET status = 'live', display_name = ? WHERE id = ?", (name or "", aid))
        conn.commit()
        conn.close()
        HEALTH_MGR.report_success(aid)
        return jsonify({"ok": True, "status": "live", "name": name})
    except Exception as e:
        conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": False, "status": "dead", "error": str(e)}), 400


@app.route("/api/accounts/check_all", methods=["POST"])
@login_required
def api_accounts_check_all():
    conn = db()
    rows = conn.execute("SELECT * FROM accounts").fetchall()
    live_count = 0
    for r in rows:
        plat = r["platform"] or "zalo"
        try:
            if plat == "zalo":
                Zalo(r["imei"], json.loads(r["cookies"]))
            else:
                bot = DiscordBot(r["token"], is_bot=bool(r["is_bot"]))
                if not bot.check():
                    raise Exception("Die")
            conn.execute("UPDATE accounts SET status = 'live' WHERE id = ?", (r["id"],))
            live_count += 1
        except Exception:
            conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (r["id"],))
    conn.commit()
    conn.close()
    sync_all_zalo_listeners()
    return jsonify({"ok": True, "total": len(rows), "live": live_count})


@app.route("/api/accounts/<int:aid>/load_boxes", methods=["POST"])
@login_required
def api_load_boxes(aid):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Không tìm thấy tài khoản"}), 404

    plat = row["platform"] or "zalo"
    boxes = []
    try:
        if plat == "zalo":
            z = Zalo(row["imei"], json.loads(row["cookies"]))
            grs = z.groups()
            frs = z.friends()
            boxes = grs + frs
        else:
            bot = DiscordBot(row["token"], is_bot=bool(row["is_bot"]))
            guilds = bot.get_guilds()
            for g in guilds:
                channels = bot.get_channels(g["id"])
                for c in channels:
                    boxes.append({
                        "id": c["id"],
                        "name": f"[{g['name']}] {c['name']}",
                        "type": "discord_channel"
                    })
        return jsonify({"ok": True, "boxes": boxes})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/accounts/<int:aid>/members/<group_id>", methods=["POST"])
@login_required
def api_load_members(aid, group_id):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Không tìm thấy tài khoản"}), 404
    try:
        z = Zalo(row["imei"], json.loads(row["cookies"]))
        members = z.get_members_full(group_id, use_cache=False)
        return jsonify({"ok": True, "members": members})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/files", methods=["GET"])
@login_required
def api_files_list():
    conn = db()
    rows = conn.execute("SELECT * FROM files ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/files/upload", methods=["POST"])
@login_required
def api_files_upload():
    """Tải file nhiều MB theo luồng bộ đệm 1MB (shutil.copyfileobj) và lập chỉ mục RAM tức thì."""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Vui lòng chọn một tệp văn bản hợp lệ"}), 400

    safe_name = re.sub(r"[^a-zA-Z0-9_.\-]", "_", f.filename)
    safe = f"{int(time.time() * 1000)}_{safe_name}"
    fp = os.path.join(UPLOAD_DIR, safe)

    try:
        with open(fp, "wb") as out_stream:
            shutil.copyfileobj(f.stream, out_stream, length=1024 * 1024)

        parsed = parse_file_stream_fast(fp)
    except Exception as e:
        return jsonify({"error": "Lỗi xử lý tệp dung lượng lớn: " + str(e)}), 400

    conn = db()
    conn.execute(
        "INSERT INTO files (filename, filepath, lines, total_lines, size, uploaded_at) VALUES (?, ?, ?, ?, ?, ?)",
        (f.filename, fp, parsed["block_count"], parsed["line_count"], parsed["size"], time.time())
    )
    conn.commit()
    conn.close()
    return jsonify({
        "ok": True,
        "filename": f.filename,
        "lines": parsed["block_count"],
        "total_lines": parsed["line_count"],
        "size": parsed["size"]
    })


@app.route("/api/files/<int:fid>", methods=["DELETE"])
@login_required
def api_files_delete(fid):
    conn = db()
    row = conn.execute("SELECT filepath FROM files WHERE id = ?", (fid,)).fetchone()
    if row and row["filepath"]:
        with FILE_CACHE_LOCK:
            FILE_MEMORY_CACHE.pop(row["filepath"], None)
        try:
            if os.path.exists(row["filepath"]):
                os.remove(row["filepath"])
        except Exception:
            pass
    conn.execute("DELETE FROM files WHERE id = ?", (fid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/files/<int:fid>/preview", methods=["GET"])
@login_required
def api_files_preview(fid):
    conn = db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Không tìm thấy tập tin"}), 404
    limit = int(request.args.get("limit", 100))
    parsed = parse_file_stream_fast(row["filepath"])
    return jsonify({
        "filename": row["filename"],
        "total_blocks": parsed["block_count"],
        "total_lines": parsed["line_count"],
        "all": parsed["blocks"][:limit]
    })


@app.route("/api/tasks", methods=["GET"])
@login_required
def api_tasks():
    conn = db()
    rows = conn.execute("SELECT * FROM tasks ORDER BY started_at DESC LIMIT 40").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/bot_logs", methods=["GET"])
@login_required
def api_bot_logs():
    conn = db()
    rows = conn.execute("SELECT * FROM bot_logs ORDER BY id DESC LIMIT 40").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tasks/start", methods=["POST"])
@login_required
def api_tasks_start():
    d = request.json or {}
    targets = d.get("targets", [])
    file_id = d.get("file_id")
    blocks = d.get("blocks", [])
    quick_tail_tag = (d.get("quick_tail_tag") or "").strip()
    delay = float(d.get("delay", 1.0))
    use_emoji = bool(d.get("use_emoji", True))
    icon_count = int(d.get("icon_count", 3))
    tag_users = d.get("tag_users", [])
    tag_all = bool(d.get("tag_all", False))
    is_heading = bool(d.get("is_heading", True))
    multi_acc = bool(d.get("multi_acc", True))
    antiband = bool(d.get("antiband", True))
    antidieall = bool(d.get("antidieall", True))
    mode = d.get("mode", "fast")
    color_mode = d.get("color_mode", "rainbow")
    fixed_color = d.get("fixed_color", "red")

    if file_id:
        blocks = get_blocks_from_file_id(int(file_id), mode=mode)

    if not targets or not blocks:
        return jsonify({"error": "Vui lòng chọn hội thoại / kênh và chọn File hoặc nhập nội dung cần gửi"}), 400

    # Nếu người dùng nhập thêm @Tên hoặc @All ở ô Tag nhanh cuối câu (áp dụng cho cả File .txt)
    if quick_tail_tag:
        if not quick_tail_tag.startswith("@"):
            quick_tail_tag = "@" + quick_tail_tag
        blocks = [f"{b} {quick_tail_tag}" for b in blocks]

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
        antidieall=antidieall,
        specific_acc_id=None,
        source_label="web"
    )
    return jsonify({"ok": True, "task_id": tid})


@app.route("/api/tasks/<tid>/stop", methods=["POST"])
@login_required
def api_tasks_stop(tid):
    if tid in ACTIVE_TASKS:
        ACTIVE_TASKS[tid]["stop"].set()
        return jsonify({"ok": True})
    conn = db()
    conn.execute("UPDATE tasks SET status = 'stopped' WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/tasks/stop_all", methods=["POST"])
@login_required
def api_tasks_stop_all():
    cnt = stop_tasks_for_thread(None)
    return jsonify({"ok": True, "count": cnt})


# Khởi chạy tự động các luồng lắng nghe lệnh khung chat Zalo 24/7 khi bật Server
sync_all_zalo_listeners()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
