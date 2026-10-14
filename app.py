# -*- coding: utf-8 -*-
"""
================================================================================
  ALB FORGE v8.0 ULTRA - DUAL STEALTH AUTOMATION & COMMAND SUITE
  Author: ALB FORGE (0986776109)
  Architecture: Single-File Enterprise Flask Application (5500+ Lines)
  Key Upgrades in v8.0 ULTRA:
  1. Dual Specialized Anti-Ban Engines:
     - ZaloAntiBanEngine (ZALO MATRIX STEALTH v8.0): Monotonic 13-digit clientId,
       IMEI-bound Chrome fingerprint, Gaussian+Poisson micro-jitter, burst coffee
       breaks, error circuit-breaker, and zero-shift cryptographic tail.
     - DiscordStealthAntiBanEngine (DISCORD PHANTOM ROUTE v8.0): Full route &
       telemetry cloaking (X-Super-Properties Base64, X-Discord-Locale,
       X-Discord-Timezone, X-Debug-Options, dynamic channel Referer, authentic
       64-bit Discord Epoch Snowflake nonce, human /typing simulation, and
       per-bucket rate-limit preemptive throttling).
  2. Account & Token Privacy Shield: Automatic masking of UIDs, tokens, cookies,
     and account logs across UI & terminal with toggleable Stealth Mask mode.
  3. Unboxed Full-Size Discord Typography: Removed ```ansi``` dark code-block
     boxes; messages now expand out naturally at full size using native Discord
     Markdown (# Big Heading, **Bold**, > Quote) + real clickable <@uid> tags.
  4. 100% Accurate Zalo Auto-@Tag per Chat Box: Fixed UTF-16 boundary clamping,
     memVerList version suffix normalization (uid_0, uid_1), recent group message
     dName harvesting, and per-box automatic member resolution in both Web UI
     and in-chat commands.
  5. Discord Reg / Safe Token Extractor & Session Warmer: Built-in tool to get
     or extract Discord tokens via Reg/Login (with X-Fingerprint warming),
     cURL/Network/HAR/LocalStorage parser, and persistent fingerprint binding.
  6. Streamlined UI & Zero Mobile Auto-Zoom: Removed user account creation/login
     clutter, compacted buttons, and locked 16px input font + viewport rules so
     tapping never triggers accidental screen zoom on iOS/Android.
================================================================================
"""

import os
import re
import sys
import json
import time
import uuid
import math
import zlib
import base64
import random
import string
import hashlib
import sqlite3
import logging
import threading
import traceback
import urllib.parse
from datetime import datetime, timedelta
from functools import wraps
from collections import deque, defaultdict

import requests
import urllib3
from flask import (
    Flask, request, jsonify, session, redirect,
    url_for, render_template_string, Response, make_response
)

try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
except ImportError:
    try:
        from Cryptodome.Cipher import AES
        from Cryptodome.Util.Padding import pad, unpad
    except ImportError:
        from cryptography.hazmat.primitives.ciphers import Cipher as _Cipher, algorithms as _alg, modes as _modes
        from cryptography.hazmat.primitives import padding as _padding

        class _AESWrapper:
            MODE_CBC = 2
            block_size = 16

            class _CBCImpl:
                def __init__(self, key, iv):
                    self._cipher = _Cipher(_alg.AES(key), _modes.CBC(iv))

                def encrypt(self, data):
                    enc = self._cipher.encryptor()
                    return enc.update(data) + enc.finalize()

                def decrypt(self, data):
                    dec = self._cipher.decryptor()
                    return dec.update(data) + dec.finalize()

            @classmethod
            def new(cls, key, mode, iv):
                return cls._CBCImpl(key, iv)

        AES = _AESWrapper

        def pad(data_to_pad, block_size):
            padder = _padding.PKCS7(block_size * 8).padder()
            return padder.update(data_to_pad) + padder.finalize()

        def unpad(padded_data, block_size):
            unpadder = _padding.PKCS7(block_size * 8).unpadder()
            return unpadder.update(padded_data) + unpadder.finalize()

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================================================================
#  SECTION 1: CORE APPLICATION CONFIGURATION & STEALTH PRIVACY LOGGING
# ==============================================================================

app = Flask(__name__)
app.secret_key = os.environ.get("ALB_SECRET_KEY", "ALB_FORGE_V8_ULTRA_SECRET_9988776655_KEY")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

APP_VERSION = "8.0.0-ULTRA-STEALTH"
APP_TITLE = "ALB FORGE v8.0 ULTRA"
AUTHOR_NAME = "ALB FORGE"
AUTHOR_ZALO = "0986776109"
DEFAULT_GATE_KEY = "alb2026"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "DATA")
TXT_DIR = os.path.join(DATA_DIR, "TXT")
MEDIA_DIR = os.path.join(DATA_DIR, "MEDIA")
BACKUP_DIR = os.path.join(DATA_DIR, "BACKUP")
DB_PATH = os.path.join(BASE_DIR, "alb_forge_v8_database.db")

for d_path in (DATA_DIR, TXT_DIR, MEDIA_DIR, BACKUP_DIR):
    os.makedirs(d_path, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ALB_FORGE_V8")

# Global state locks and structures
GLOBAL_LOCK = threading.RLock()
DB_LOCK = threading.RLock()

# Privacy & Stealth Masking Flag (Default: ON so account logs/tokens are hidden)
STEALTH_LOG_MASK_ENABLED = True

# Active Bot Clients in Memory
ZALO_BOTS = {}       # { uid: Zalo instance }
DISCORD_BOTS = {}    # { uid: DiscordBot instance }

# Active Self-Bot Listeners (In-Chat Command Listeners)
ZALO_LISTENERS = {}     # { uid: ZaloSelfBotListener }
DISCORD_LISTENERS = {}  # { uid: DiscordSelfBotListener }

# Active Spam / Automation Tasks
ACTIVE_TASKS = {}    # { task_id: dict }

# Global Live Telemetry Ring Buffer
SYSTEM_LOGS = deque(maxlen=400)


def mask_sensitive_id(val, keep_prefix=2, keep_suffix=3):
    """Masks sensitive UIDs, channel IDs, IMEIs, or tokens for stealth display."""
    s = str(val or "").strip()
    if not s:
        return "***"
    if not STEALTH_LOG_MASK_ENABLED:
        return s
    if len(s) <= (keep_prefix + keep_suffix + 2):
        return s[:1] + "***" + s[-1:] if len(s) > 2 else "***"
    return f"{s[:keep_prefix]}***{s[-keep_suffix:]}"


def mask_account_name(name):
    """Masks account name partially when stealth log masking is active."""
    s = str(name or "").strip()
    if not s:
        return "Acc-Ẩn"
    if not STEALTH_LOG_MASK_ENABLED:
        return s
    if len(s) <= 3:
        return s[0] + "**"
    return s[:2] + "***" + s[-1:]


def mask_token_string(token_str):
    """Always masks raw Discord tokens / Zalo cookies so they never leak."""
    s = str(token_str or "").strip()
    if not s:
        return "[TRỐNG]"
    if len(s) <= 12:
        return "[ĐÃ ẨN BẢO MẬT]"
    return f"{s[:4]}••••••••{s[-4:]} [ẨN BẢO MẬT]"


def scrub_log_message(msg):
    """Automatically scrubs tokens, cookies, long numeric UIDs, and emails in logs."""
    text = str(msg or "")
    # Mask Discord tokens (pattern: xxx.yyy.zzz)
    text = re.sub(
        r"\b([A-Za-z0-9_\-]{18,28})\.([A-Za-z0-9_\-]{6,10})\.([A-Za-z0-9_\-]{20,45})\b",
        r"\1.***.[TOKEN-ẨN]",
        text
    )
    # Mask Bearer/Authorization headers
    text = re.sub(r"(Authorization['\"\s:]+)([^\s,'\"]+)", r"\1[TOKEN-ẨN]", text, flags=re.I)
    if STEALTH_LOG_MASK_ENABLED:
        # Mask long numeric UIDs/Snowflakes (10 to 22 digits) -> keep first 2 and last 3
        def _uid_repl(m):
            num = m.group(0)
            return f"{num[:2]}***{num[-3:]}"
        text = re.sub(r"\b\d{10,22}\b", _uid_repl, text)
    return text


def push_sys_log(level, category, message):
    """Thread-safe helper to record system events with automatic stealth scrubbing."""
    ts = datetime.now().strftime("%H:%M:%S")
    safe_msg = scrub_log_message(message)
    entry = {
        "id": str(uuid.uuid4())[:8],
        "time": ts,
        "level": level.upper(),
        "category": category.upper(),
        "message": safe_msg
    }
    with GLOBAL_LOCK:
        SYSTEM_LOGS.appendleft(entry)
    logger.info(f"[{category.upper()}] {safe_msg}")


# ==============================================================================
#  SECTION 2: FIREWALL & HTTP SECURITY SHIELD
# ==============================================================================

class SecurityShield:
    """In-memory rate limiter, IP ban manager, and request sanitizer."""
    def __init__(self):
        self.ip_requests = defaultdict(deque)
        self.failed_logins = defaultdict(int)
        self.banned_ips = {}
        self.lock = threading.Lock()
        self.max_req_per_10s = 250
        self.ban_duration = 300

    def check_ip(self, ip):
        if not ip or ip in ("127.0.0.1", "::1", "localhost"):
            return True, ""
        now = time.time()
        with self.lock:
            if ip in self.banned_ips:
                if now < self.banned_ips[ip]:
                    rem = int(self.banned_ips[ip] - now)
                    return False, f"IP tạm khóa ({rem}s)."
                else:
                    del self.banned_ips[ip]
                    self.failed_logins[ip] = 0
            dq = self.ip_requests[ip]
            while dq and now - dq[0] > 10.0:
                dq.popleft()
            dq.append(now)
            if len(dq) > self.max_req_per_10s:
                self.banned_ips[ip] = now + self.ban_duration
                return False, "Rate limit exceeded."
        return True, ""

    def record_failed_auth(self, ip):
        if not ip or ip in ("127.0.0.1", "::1", "localhost"):
            return
        with self.lock:
            self.failed_logins[ip] += 1
            if self.failed_logins[ip] >= 12:
                self.banned_ips[ip] = time.time() + 600
                push_sys_log("WARN", "SECURITY", f"Khóa tạm thời IP nhập sai Gate Key: {ip}")

    def reset_auth(self, ip):
        with self.lock:
            self.failed_logins.pop(ip, None)


SECURITY_SHIELD = SecurityShield()


@app.before_request
def middleware_security_check():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1").split(",")[0].strip()
    allowed, reason = SECURITY_SHIELD.check_ip(ip)
    if not allowed:
        return jsonify({"ok": False, "msg": reason}), 429


@app.after_request
def middleware_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


# ==============================================================================
#  SECTION 3: SQLITE DATABASE ENGINE & PERSISTENCE LAYER
# ==============================================================================

def get_db_conn():
    """Returns a thread-safe SQLite connection with WAL / fallback support."""
    global DB_PATH
    try:
        conn = sqlite3.connect(DB_PATH, timeout=25, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=MEMORY;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn
    except sqlite3.OperationalError:
        DB_PATH = "/tmp/alb_forge_v8_database.db"
        conn = sqlite3.connect(DB_PATH, timeout=25, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn


def init_database():
    """Initializes SQLite tables and default sample files."""
    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                k TEXT PRIMARY KEY,
                v TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS zalo_accounts (
                uid TEXT PRIMARY KEY,
                name TEXT,
                imei TEXT,
                cookie_json TEXT,
                user_agent TEXT,
                proxy TEXT DEFAULT '',
                selfbot_enabled INTEGER DEFAULT 1,
                command_prefix TEXT DEFAULT '.',
                status TEXT DEFAULT 'ONLINE',
                created_at TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS discord_accounts (
                uid TEXT PRIMARY KEY,
                name TEXT,
                username TEXT,
                token TEXT,
                proxy TEXT DEFAULT '',
                super_props_b64 TEXT DEFAULT '',
                fingerprint TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                selfbot_enabled INTEGER DEFAULT 1,
                command_prefix TEXT DEFAULT '.',
                status TEXT DEFAULT 'ONLINE',
                created_at TEXT
            )
        """)

        # Ensure new columns exist if migrating from older DB
        try:
            cur.execute("ALTER TABLE discord_accounts ADD COLUMN super_props_b64 TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE discord_accounts ADD COLUMN fingerprint TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE discord_accounts ADD COLUMN user_agent TEXT DEFAULT ''")
        except Exception:
            pass

        cur.execute("""
            CREATE TABLE IF NOT EXISTS task_history (
                task_id TEXT PRIMARY KEY,
                platform TEXT,
                acc_uid TEXT,
                acc_name TEXT,
                target_id TEXT,
                target_name TEXT,
                mode TEXT,
                delay REAL,
                sent_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                status TEXT,
                started_at TEXT
            )
        """)

        cur.execute("SELECT v FROM settings WHERE k='gate_key'")
        if not cur.fetchone():
            cur.execute("INSERT INTO settings (k, v) VALUES ('gate_key', ?)", (DEFAULT_GATE_KEY,))

        cur.execute("SELECT v FROM settings WHERE k='stealth_mask'")
        if not cur.fetchone():
            cur.execute("INSERT INTO settings (k, v) VALUES ('stealth_mask', '1')")

        conn.commit()
        conn.close()

    _seed_default_txt_files()
    push_sys_log("INFO", "DB", "Khởi tạo cơ sở dữ liệu SQLite v8.0 ULTRA thành công.")


def _seed_default_txt_files():
    """Creates starter text files in DATA/TXT if none exist."""
    samples = {
        "nhay_vip_2026.txt": (
            "Chào mừng đến với hệ thống tự động hóa ALB FORGE v8.0 ULTRA!\n"
            "Tốc độ xử lý siêu mượt - Anti-Ban Thế Hệ Mới Đa Tầng\n"
            "Tự động Tag tên chuẩn xác trên cả Zalo và Discord\n"
            "Chữ Discord bung toàn màn hình cực nét không đóng khung\n"
            "Đẳng cấp công nghệ tự động hóa 2026 - ALB FORGE"
        ),
        "chao_hoi_box.txt": (
            "Chào anh em trong nhóm nhé!\n"
            "Chúc mọi người một ngày làm việc và giải trí thật nhiều năng lượng!\n"
            "Hệ thống trợ lý tự động ALB FORGE v8.0 đang trực tuyến."
        ),
        "ca_dao_tuc_ngu.txt": (
            "Công cha như núi Thái Sơn\nNghĩa mẹ như nước trong nguồn chảy ra\n"
            "Một cây làm chẳng nên non\nBa cây chụm lại nên hòn núi cao\n"
            "Nhiễu điều phủ lấy giá gương\nNgười trong một nước phải thương nhau cùng\n"
            "Ăn quả nhớ kẻ trồng cây\nUống nước nhớ nguồn, trọn nghĩa vẹn tình"
        )
    }
    for fname, content in samples.items():
        fpath = os.path.join(TXT_DIR, fname)
        if not os.path.exists(fpath):
            try:
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception:
                pass


def get_setting(key, default_val=""):
    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT v FROM settings WHERE k=?", (key,))
        row = cur.fetchone()
        conn.close()
        return row["v"] if row else default_val


def set_setting(key, val):
    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO settings (k, v) VALUES (?, ?)", (key, str(val)))
        conn.commit()
        conn.close()


# ==============================================================================
#  SECTION 4: DUAL SPECIALIZED ANTI-BAN ENGINES (ZALO vs DISCORD)
# ==============================================================================

ZALO_SAFE_2CHAR_ICONS = [":d", ":p", ":v", ":3", ":>", ":$", ":x", ":o", ":)", ":("]
DISCORD_DECOR_ICONS = ["⚡", "🔥", "💎", "🚀", "✨", "👑", "🎯", "💥", "🌟", "🛡️"]
ZERO_WIDTH_POOL = ["\u200b", "\u200c", "\u200d", "\u2060"]

ZALO_BROWSER_PROFILES = [
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "platform": '"Windows"'
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
        "platform": '"Windows"'
    },
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "platform": '"macOS"'
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
        "sec_ch_ua": '"Not(A:Brand";v="99", "Microsoft Edge";v="133", "Chromium";v="133"',
        "platform": '"Windows"'
    }
]


class ZaloAntiBanEngine:
    """
    ENGINE #1: ZALO MATRIX STEALTH v8.0
    Specifically engineered for Zalo Web/PC (zpw_ver=645, zpw_type=30):
    1. Monotonic 13-Digit ClientId Generator: Prevents duplicate millisecond
       timestamps when dispatching across multiple Zalo boxes simultaneously.
    2. IMEI-Coherent Browser Header Binding: Locks Sec-Ch-Ua, Sec-Ch-Ua-Platform,
       and User-Agent consistently to each account's IMEI hash.
    3. Adaptive Gaussian + Poisson Micro-Jitter & Burst Coffee Breaks:
       Prevents robotic cadence signatures while keeping messages responsive.
    4. Error-Code Circuit Breaker: Detects Zalo rate-limit codes (-13, -112, 429)
       and triggers automatic self-healing cool-downs.
    5. Zero-Shift Cryptographic Tail: Appends invisible polymorphism strictly
       AFTER all @Tag offsets so UTF-16 mentionInfo positions never drift!
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.acc_state = defaultdict(lambda: {
            "sent_total": 0,
            "burst_count": 0,
            "next_break_at": random.randint(18, 26),
            "consec_errors": 0,
            "cooldown_until": 0.0,
            "last_send_ts": 0.0,
            "last_client_id": 0,
            "health_score": 100
        })

    def next_client_id(self, acc_uid):
        """Returns a strictly increasing 13-digit millisecond clientId per account."""
        now_ms = int(time.time() * 1000)
        with self.lock:
            st = self.acc_state[f"zalo:{acc_uid}"]
            if now_ms <= st["last_client_id"]:
                now_ms = st["last_client_id"] + random.randint(1, 5)
            st["last_client_id"] = now_ms
            return str(now_ms)

    def build_coherent_headers(self, imei, custom_ua=None, origin="https://chat.zalo.me"):
        """Builds a coherent Chrome header profile deterministically bound to IMEI."""
        idx = zlib.crc32(str(imei or "zalo").encode("utf-8")) % len(ZALO_BROWSER_PROFILES)
        prof = ZALO_BROWSER_PROFILES[idx]
        ua = custom_ua if (custom_ua and len(custom_ua) > 20) else prof["ua"]
        return {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": origin,
            "Referer": f"{origin}/",
            "Sec-Ch-Ua": prof["sec_ch_ua"],
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": prof["platform"],
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site"
        }

    def compute_adaptive_delay(self, acc_uid, base_delay, text_len=20):
        """Calculates human-like delay with Gaussian jitter, warm-up, and burst rests."""
        base = max(0.4, float(base_delay))
        key = f"zalo:{acc_uid}"
        now = time.time()

        with self.lock:
            st = self.acc_state[key]
            if now < st["cooldown_until"]:
                wait_rem = st["cooldown_until"] - now
                return wait_rem, f"Zalo Circuit-Breaker Cooldown ({wait_rem:.1f}s)"

            st["burst_count"] += 1
            st["sent_total"] += 1

            # Warm-up protection on first 4 messages
            warmup_mult = 1.30 if st["sent_total"] <= 4 else 1.0

            # Gaussian + Poisson micro-jitter
            sigma = max(0.06, base * 0.16)
            jitter = random.gauss(0, sigma) + random.expovariate(1.0 / max(0.05, base * 0.07))
            typing_sim = min(0.85, (text_len / 52.0) * random.uniform(0.10, 0.22))

            delay = max(0.35, (base * warmup_mult) + jitter + typing_sim)

            # Periodic burst coffee break every 18-26 messages
            if st["burst_count"] >= st["next_break_at"]:
                coffee_break = random.uniform(2.2, 4.8)
                st["burst_count"] = 0
                st["next_break_at"] = random.randint(18, 26)
                delay += coffee_break
                return delay, f"Zalo Anti-Ban nghỉ nhịp tự nhiên (+{coffee_break:.1f}s)"

        return delay, "Zalo Matrix Stealth Jitter"

    def record_result(self, acc_uid, success, err_code=0):
        """Updates Zalo account health and triggers backoff on rate-limit codes."""
        key = f"zalo:{acc_uid}"
        now = time.time()
        with self.lock:
            st = self.acc_state[key]
            st["last_send_ts"] = now
            if success:
                st["consec_errors"] = 0
                st["health_score"] = min(100, st["health_score"] + 1)
            else:
                st["consec_errors"] += 1
                st["health_score"] = max(15, st["health_score"] - 12)
                # Zalo rate-limit / anti-spam codes: -13, -112, 429, 302
                if err_code in (-13, -112, 429) or st["consec_errors"] >= 3:
                    backoff = min(65.0, (2.0 ** min(5, st["consec_errors"])) + random.uniform(2.0, 5.5))
                    st["cooldown_until"] = now + backoff
                    push_sys_log(
                        "WARN", "ANTIBAN-ZALO",
                        f"Zalo Anti-Ban kích hoạt bảo vệ tài khoản {mask_sensitive_id(acc_uid)} trong {backoff:.1f}s (Code={err_code})"
                    )

    @staticmethod
    def apply_invisible_tail(text):
        """
        Appends 2-4 zero-width characters strictly at the END of the message.
        Because it is placed at the tail, UTF-16 offsets of preceding @Mentions
        are 100% preserved!
        """
        if not text:
            return text
        tail_len = random.randint(2, 4)
        zw_tail = "".join(random.choice(ZERO_WIDTH_POOL) for _ in range(tail_len))
        return f"{text}{zw_tail}"

    def get_account_telemetry(self, acc_uid):
        key = f"zalo:{acc_uid}"
        with self.lock:
            st = dict(self.acc_state[key])
        now = time.time()
        st["in_cooldown"] = now < st["cooldown_until"]
        st["cooldown_remaining"] = max(0.0, round(st["cooldown_until"] - now, 1))
        st["engine_name"] = "ZALO MATRIX STEALTH v8.0"
        return st


class DiscordStealthAntiBanEngine:
    """
    ENGINE #2: DISCORD PHANTOM ROUTE v8.0
    ("Antiband ẩn đường chuyển của Discord để cho Discord không phát hiện")
    Specifically engineered to cloak Discord API routing, telemetry, and cadence:
    1. X-Super-Properties Telemetry Cloaking: Deterministic per-account Base64
       browser telemetry payload (os, browser, client_build_number=369842,
       native_build_number, system_locale="vi-VN", release_channel="stable")
       so Discord's anti-abuse pipeline sees an authentic desktop/web browser session.
    2. Full Route Cloaking Headers: Injects X-Discord-Locale, X-Discord-Timezone,
       X-Debug-Options: bugReporterEnabled, Sec-Ch-Ua, Origin: https://discord.com,
       and dynamic channel-specific Referer: https://discord.com/channels/@me/{channel_id}
       to mask automated API routing.
    3. Authentic 64-Bit Discord Epoch Snowflake Nonce: Calculates
       ((int(time.time() * 1000) - 1420070400000) << 22) | random_22bit
       on every outgoing message so nonces match official Discord client behavior.
    4. Smart Human /typing Cadence + Preemptive Bucket Throttling: Sends throttled
       /typing indicators and honors X-RateLimit-Remaining before hitting 429.
    5. Zero-Shift Anti-AutoMod Tail: Randomizes message hash invisibly at the end.
    """
    DISCORD_EPOCH = 1420070400000

    DISCORD_CLIENT_PROFILES = [
        {
            "os": "Windows",
            "browser": "Chrome",
            "browser_version": "131.0.0.0",
            "os_version": "10",
            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "platform": '"Windows"',
            "build_num": 369842
        },
        {
            "os": "Windows",
            "browser": "Chrome",
            "browser_version": "132.0.0.0",
            "os_version": "10",
            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
            "sec_ch_ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
            "platform": '"Windows"',
            "build_num": 370118
        },
        {
            "os": "Mac OS X",
            "browser": "Chrome",
            "browser_version": "131.0.0.0",
            "os_version": "10.15.7",
            "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "platform": '"macOS"',
            "build_num": 369842
        }
    ]

    def __init__(self):
        self.lock = threading.Lock()
        self.acc_state = defaultdict(lambda: {
            "sent_total": 0,
            "burst_count": 0,
            "next_break_at": random.randint(15, 23),
            "consec_errors": 0,
            "cooldown_until": 0.0,
            "last_typing_ts": 0.0,
            "last_nonce": 0,
            "health_score": 100
        })

    def get_or_build_identity(self, seed_str, saved_super_b64="", saved_ua="", saved_fp=""):
        """Deterministically generates X-Super-Properties Base64 & UA for a Discord token/account."""
        idx = zlib.crc32(str(seed_str or "discord").encode("utf-8")) % len(self.DISCORD_CLIENT_PROFILES)
        prof = self.DISCORD_CLIENT_PROFILES[idx]
        ua = saved_ua if (saved_ua and len(saved_ua) > 20) else prof["ua"]

        if saved_super_b64 and len(saved_super_b64) > 30:
            super_b64 = saved_super_b64
        else:
            super_dict = {
                "os": prof["os"],
                "browser": prof["browser"],
                "device": "",
                "system_locale": "vi-VN",
                "browser_user_agent": ua,
                "browser_version": prof["browser_version"],
                "os_version": prof["os_version"],
                "referrer": "",
                "referring_domain": "",
                "referrer_current": "",
                "referring_domain_current": "",
                "release_channel": "stable",
                "client_build_number": prof["build_num"],
                "client_event_source": None,
                "design_id": 0
            }
            raw_json = json.dumps(super_dict, separators=(",", ":"))
            super_b64 = base64.b64encode(raw_json.encode("utf-8")).decode("utf-8")

        return {
            "ua": ua,
            "super_props_b64": super_b64,
            "sec_ch_ua": prof["sec_ch_ua"],
            "platform": prof["platform"],
            "fingerprint": saved_fp or ""
        }

    def build_stealth_headers(self, token, seed_str="", channel_id="@me", saved_super_b64="", saved_ua="", saved_fp=""):
        """
        Builds full Discord Route-Cloaking HTTP headers so Discord's edge/WAF
        sees an organic browser request from https://discord.com/channels/...
        """
        ident = self.get_or_build_identity(seed_str or token, saved_super_b64, saved_ua, saved_fp)
        ref_path = f"https://discord.com/channels/@me/{channel_id}" if str(channel_id) != "@me" else "https://discord.com/channels/@me"
        headers = {
            "Authorization": token.strip(),
            "User-Agent": ident["ua"],
            "Accept": "*/*",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://discord.com",
            "Referer": ref_path,
            "X-Super-Properties": ident["super_props_b64"],
            "X-Discord-Locale": "vi",
            "X-Discord-Timezone": "Asia/Ho_Chi_Minh",
            "X-Debug-Options": "bugReporterEnabled",
            "Sec-Ch-Ua": ident["sec_ch_ua"],
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": ident["platform"],
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Priority": "u=1, i"
        }
        if ident["fingerprint"]:
            headers["X-Fingerprint"] = ident["fingerprint"]
        return headers, ident

    def generate_snowflake_nonce(self, acc_uid=""):
        """Generates an authentic 64-bit Discord Epoch Snowflake nonce."""
        now_ms = int(time.time() * 1000)
        elapsed = max(0, now_ms - self.DISCORD_EPOCH)
        rand_bits = random.randint(1, 4194302)
        nonce_int = (elapsed << 22) | rand_bits
        with self.lock:
            st = self.acc_state[f"discord:{acc_uid}"]
            if nonce_int <= st["last_nonce"]:
                nonce_int = st["last_nonce"] + random.randint(1, 99)
            st["last_nonce"] = nonce_int
        return str(nonce_int)

    def should_send_typing(self, acc_uid):
        """Throttles /typing calls to at most once every 7.5 seconds per account."""
        now = time.time()
        with self.lock:
            st = self.acc_state[f"discord:{acc_uid}"]
            if now - st["last_typing_ts"] >= 7.5:
                st["last_typing_ts"] = now
                return True
            return False

    def compute_adaptive_delay(self, acc_uid, base_delay, text_len=20):
        """Calculates Discord stealth cadence with Gaussian jitter & burst micro-breaks."""
        base = max(0.45, float(base_delay))
        key = f"discord:{acc_uid}"
        now = time.time()

        with self.lock:
            st = self.acc_state[key]
            if now < st["cooldown_until"]:
                wait_rem = st["cooldown_until"] - now
                return wait_rem, f"Discord Route-Cloak Cooldown ({wait_rem:.1f}s)"

            st["burst_count"] += 1
            st["sent_total"] += 1

            warmup_mult = 1.25 if st["sent_total"] <= 4 else 1.0
            sigma = max(0.06, base * 0.15)
            jitter = random.gauss(0, sigma) + random.expovariate(1.0 / max(0.05, base * 0.08))
            typing_sim = min(0.75, (text_len / 58.0) * random.uniform(0.09, 0.20))

            delay = max(0.40, (base * warmup_mult) + jitter + typing_sim)

            if st["burst_count"] >= st["next_break_at"]:
                pause = random.uniform(2.0, 4.5)
                st["burst_count"] = 0
                st["next_break_at"] = random.randint(15, 23)
                delay += pause
                return delay, f"Discord Phantom Route nghỉ nhịp (+{pause:.1f}s)"

        return delay, "Discord Phantom Route Jitter"

    def record_result(self, acc_uid, success, status_code=200, retry_after=0.0):
        """Tracks Discord account health and respects 429 retry_after headers."""
        key = f"discord:{acc_uid}"
        now = time.time()
        with self.lock:
            st = self.acc_state[key]
            if success:
                st["consec_errors"] = 0
                st["health_score"] = min(100, st["health_score"] + 1)
            else:
                st["consec_errors"] += 1
                st["health_score"] = max(15, st["health_score"] - 12)
                if status_code == 429 or retry_after > 0 or st["consec_errors"] >= 3:
                    wait_s = max(float(retry_after or 0.0) + random.uniform(0.6, 1.8), min(45.0, 2.0 ** min(5, st["consec_errors"])))
                    st["cooldown_until"] = now + wait_s
                    push_sys_log(
                        "WARN", "ANTIBAN-DISCORD",
                        f"Discord Phantom Route tạm giảm tốc acc {mask_sensitive_id(acc_uid)} trong {wait_s:.1f}s (HTTP {status_code})"
                    )

    @staticmethod
    def apply_invisible_tail(text):
        """Appends zero-width anti-automod signature at the end of Discord message."""
        if not text:
            return text
        zw_tail = "".join(random.choice(ZERO_WIDTH_POOL) for _ in range(random.randint(2, 4)))
        return f"{text}{zw_tail}"

    def get_account_telemetry(self, acc_uid):
        key = f"discord:{acc_uid}"
        with self.lock:
            st = dict(self.acc_state[key])
        now = time.time()
        st["in_cooldown"] = now < st["cooldown_until"]
        st["cooldown_remaining"] = max(0.0, round(st["cooldown_until"] - now, 1))
        st["engine_name"] = "DISCORD PHANTOM ROUTE v8.0"
        return st


ZALO_ANTIBAN = ZaloAntiBanEngine()
DISCORD_ANTIBAN = DiscordStealthAntiBanEngine()


def strip_invisible_chars(text):
    """Removes zero-width characters from incoming messages before command parsing."""
    if not text:
        return ""
    for zw in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"):
        text = text.replace(zw, "")
    return text.strip()


# ==============================================================================
#  SECTION 5: ZALO ENCRYPTION & ZALO CLIENT ENGINE (100% ACCURATE BOX @TAG)
# ==============================================================================

class ZaloCrypto:
    """Handles Zalo Web/PC zpw_enk AES-128-CBC parameter encryption & decryption."""
    @staticmethod
    def encode_aes(secret_key_b64, plain_text):
        try:
            key = base64.b64decode(secret_key_b64)
            iv = b"\x00" * 16
            cipher = AES.new(key, AES.MODE_CBC, iv)
            padded = pad(plain_text.encode("utf-8"), AES.block_size)
            encrypted = cipher.encrypt(padded)
            return base64.b64encode(encrypted).decode("utf-8")
        except Exception as e:
            logger.error(f"Zalo AES Encode Error: {e}")
            return None

    @staticmethod
    def decode_aes(secret_key_b64, encrypted_b64):
        if not secret_key_b64 or not encrypted_b64:
            return None
        try:
            raw_b64 = urllib.parse.unquote(str(encrypted_b64).strip())
            missing_padding = len(raw_b64) % 4
            if missing_padding:
                raw_b64 += "=" * (4 - missing_padding)
            key = base64.b64decode(secret_key_b64)
            iv = b"\x00" * 16
            cipher = AES.new(key, AES.MODE_CBC, iv)
            enc_bytes = base64.b64decode(raw_b64)
            dec_padded = cipher.decrypt(enc_bytes)
            try:
                dec_bytes = unpad(dec_padded, AES.block_size)
            except Exception:
                dec_bytes = dec_padded.rstrip(b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10")
            return dec_bytes.decode("utf-8", errors="ignore")
        except Exception:
            return None


def utf16_len(s):
    """Calculates exact UTF-16LE code unit length required by Zalo mentionInfo & textProperties."""
    if not s:
        return 0
    return len(s.encode("utf-16-le")) // 2


def normalize_vn_text(s):
    """Normalizes Vietnamese text for fuzzy member name matching inside Zalo chat boxes."""
    if not s:
        return ""
    s = str(s).strip().lower()
    s = re.sub(r"[àáạảãâầấậẩẫăằắặẳẵ]", "a", s)
    s = re.sub(r"[èéẹẻẽêềếệểễ]", "e", s)
    s = re.sub(r"[ìíịỉĩ]", "i", s)
    s = re.sub(r"[òóọỏõôồốộổỗơờớợởỡ]", "o", s)
    s = re.sub(r"[ùúụủũưừứựửữ]", "u", s)
    s = re.sub(r"[ỳýỵỷỹ]", "y", s)
    s = re.sub(r"[đ]", "d", s)
    return re.sub(r"\s+", " ", s).strip()


class Zalo:
    """
    Full-featured Zalo Web/PC Client Engine (zpw_ver=645, zpw_type=30)
    Powered by ZaloAntiBanEngine (ZALO MATRIX STEALTH v8.0) and upgraded
    Multi-Layer Group Member & Chat-Box @Tag Resolver.
    """
    ZPW_VER = 645
    ZPW_TYPE = 30

    def __init__(self, uid, name, imei, cookies_dict, user_agent=None, proxy=None):
        self.uid = str(uid).strip()
        self.name = str(name or f"Zalo-{self.uid[-4:]}").strip()
        self.imei = str(imei).strip()
        self.cookies = cookies_dict if isinstance(cookies_dict, dict) else {}
        self.user_agent = user_agent or ZALO_BROWSER_PROFILES[0]["ua"]
        self.proxy = (proxy or "").strip()

        self.session = requests.Session()
        self.session.verify = False
        self._apply_cookies_and_proxy()

        self.secret_key = None
        self.ws_url = None
        self.zpw_ws = []
        self.online = False
        self.last_login_ts = 0

        # Caches for groups, friends, and per-box members
        self.groups_cache = []
        self.friends_cache = []
        self.members_cache = {}       # { gid: [ {uid, name}, ... ] }
        self.member_name_map = {}     # { gid: { uid: dName } }
        self.global_uid_name_map = {} # { uid: dName }

    def _apply_cookies_and_proxy(self):
        self.session.cookies.clear()
        for k, v in self.cookies.items():
            self.session.cookies.set(str(k), str(v))
        if self.proxy:
            p_url = self.proxy if "://" in self.proxy else f"http://{self.proxy}"
            self.session.proxies = {"http": p_url, "https": p_url}
        else:
            self.session.proxies = {}

    def _headers(self, origin="https://chat.zalo.me"):
        return ZALO_ANTIBAN.build_coherent_headers(self.imei, self.user_agent, origin=origin)

    def get_login_info(self):
        """Authenticates with Zalo getLoginInfo to retrieve zpw_enk (secret_key) and WebSocket URLs."""
        try:
            url = "https://wpa.chat.zalo.me/api/login/getLoginInfo"
            params = {
                "imei": self.imei,
                "computer_name": "Web",
                "language": "vi",
                "ts": int(time.time() * 1000),
                "zpw_ver": self.ZPW_VER,
                "zpw_type": self.ZPW_TYPE
            }
            r = self.session.get(url, params=params, headers=self._headers(), timeout=15)
            js = r.json()
            if js.get("error_code") == 0 and js.get("data"):
                data = js["data"]
                zpw_enk = data.get("zpw_enk")
                if zpw_enk:
                    self.secret_key = zpw_enk
                    self.online = True
                    self.last_login_ts = time.time()
                    uid_found = str(data.get("uid") or self.uid)
                    if uid_found and uid_found != "None":
                        self.uid = uid_found
                    d_name = data.get("display_name") or data.get("zalo_name")
                    if d_name:
                        self.name = str(d_name)
                    ws_list = data.get("zpw_ws") or []
                    if isinstance(ws_list, list) and ws_list:
                        self.zpw_ws = ws_list
                        self.ws_url = ws_list[0]
                    elif isinstance(ws_list, str):
                        self.ws_url = ws_list
                        self.zpw_ws = [ws_list]
                    push_sys_log("SUCCESS", "ZALO", f"Kết nối thành công Zalo: {mask_account_name(self.name)} (UID: {mask_sensitive_id(self.uid)})")
                    return True, "Kết nối Zalo thành công!"
            err_msg = js.get("error_message") or f"Mã lỗi {js.get('error_code')}"
            self.online = False
            return False, f"Zalo từ chối phiên: {err_msg}"
        except Exception as e:
            self.online = False
            return False, f"Lỗi kết nối Zalo: {e}"

    def ensure_ready(self):
        if not self.secret_key or (time.time() - self.last_login_ts > 1800):
            ok, _ = self.get_login_info()
            return ok
        return True

    def _decrypt_response(self, resp_json):
        """Decrypts Zalo API response data payload."""
        if not isinstance(resp_json, dict):
            return None
        data_field = resp_json.get("data")
        if isinstance(data_field, dict):
            return data_field
        if isinstance(data_field, str) and self.secret_key:
            dec_str = ZaloCrypto.decode_aes(self.secret_key, data_field)
            if dec_str:
                try:
                    inner = json.loads(dec_str)
                    if isinstance(inner, dict) and "data" in inner and isinstance(inner["data"], (dict, list)):
                        return inner["data"]
                    return inner
                except Exception:
                    return None
        return None

    def get_groups(self):
        """Fetches all joined Zalo groups and resolves their names & avatars."""
        if not self.ensure_ready():
            return self.groups_cache

        groups_out = []
        try:
            url = f"https://tt-group-wpa.chat.zalo.me/api/group/getlg/v4?zpw_ver={self.ZPW_VER}&zpw_type={self.ZPW_TYPE}"
            r = self.session.get(url, headers=self._headers("https://chat.zalo.me"), timeout=15)
            dec = self._decrypt_response(r.json())
            if not isinstance(dec, dict):
                return self.groups_cache

            grid_ver_map = dec.get("gridVerMap") or {}
            gids = [str(k).split("_")[0] for k in grid_ver_map.keys() if k]
            if not gids:
                return self.groups_cache

            batch_size = 45
            for i in range(0, len(gids), batch_size):
                chunk = gids[i:i + batch_size]
                grid_map = {gid: 0 for gid in chunk}
                raw_pl = json.dumps({"gridVerMap": json.dumps(grid_map)})
                enc_pl = ZaloCrypto.encode_aes(self.secret_key, raw_pl)
                info_url = f"https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2?zpw_ver={self.ZPW_VER}&zpw_type={self.ZPW_TYPE}"
                r_info = self.session.post(info_url, data={"params": enc_pl}, headers=self._headers(), timeout=15)
                dec_info = self._decrypt_response(r_info.json())
                if isinstance(dec_info, dict):
                    removed = dec_info.get("gridInfoMap") or {}
                    for gid, ginfo in removed.items():
                        if isinstance(ginfo, dict):
                            gname = ginfo.get("name") or f"Nhóm {gid[-4:]}"
                            total_m = ginfo.get("totalMember") or len(ginfo.get("memVerList") or [])
                            avt = ginfo.get("avt") or ginfo.get("fullAvt") or ""
                            clean_gid = str(gid).split("_")[0]
                            groups_out.append({
                                "id": clean_gid,
                                "name": gname,
                                "total_member": total_m,
                                "avatar": avt,
                                "type": "group"
                            })
                            # Pre-populate any profiles embedded in group info
                            m_profiles = ginfo.get("memize") or ginfo.get("profiles") or []
                            if isinstance(m_profiles, list):
                                box_map = self.member_name_map.setdefault(clean_gid, {})
                                for mp in m_profiles:
                                    if isinstance(mp, dict) and mp.get("id"):
                                        muid = str(mp["id"]).split("_")[0]
                                        mname = mp.get("dName") or mp.get("zaloName") or mp.get("displayName")
                                        if mname:
                                            box_map[muid] = str(mname).strip()
                                            self.global_uid_name_map[muid] = str(mname).strip()
        except Exception as e:
            logger.warning(f"Zalo get_groups warning: {e}")

        if groups_out:
            self.groups_cache = groups_out
        return self.groups_cache

    def get_friends(self):
        """Fetches friend list for DM targeting and member name enrichment."""
        if not self.ensure_ready():
            return self.friends_cache

        friends_out = []
        try:
            raw_pl = json.dumps({"page": 1, "count": 20000, "imei": self.imei})
            enc_pl = ZaloCrypto.encode_aes(self.secret_key, raw_pl)
            url = f"https://profile-wpa.chat.zalo.me/api/social/friend/getfriends?zpw_ver={self.ZPW_VER}&zpw_type={self.ZPW_TYPE}&params={urllib.parse.quote(enc_pl)}"
            r = self.session.get(url, headers=self._headers(), timeout=15)
            dec = self._decrypt_response(r.json())
            data_list = dec if isinstance(dec, list) else (dec.get("data") if isinstance(dec, dict) else [])
            if isinstance(data_list, list):
                for fr in data_list:
                    if isinstance(fr, dict) and fr.get("userId"):
                        fuid = str(fr["userId"]).split("_")[0]
                        fname = fr.get("displayName") or fr.get("zaloName") or fr.get("username") or f"Bạn {fuid[-4:]}"
                        avt = fr.get("avatar") or ""
                        friends_out.append({
                            "id": fuid,
                            "name": str(fname).strip(),
                            "avatar": avt,
                            "type": "friend"
                        })
                        self.global_uid_name_map[fuid] = str(fname).strip()
        except Exception as e:
            logger.warning(f"Zalo get_friends warning: {e}")

        if friends_out:
            self.friends_cache = friends_out
        return self.friends_cache

    def get_members_full(self, gid):
        """
        UPGRADED MULTI-LAYER ZALO GROUP MEMBER RESOLVER (v8.0 ULTRA):
        Fixes the exact bug where non-friend group members had version suffixes
        (e.g. "849123456_1") in getprofiles/v2 or lacked resolved display names!
        Layers:
          1. Fetch memVerList from getmg-v2 (keeping both raw "uid_ver" and clean "uid").
          2. Harvest any embedded profiles in getmg-v2 response.
          3. Harvest recent chat messages in that group box via get_recent_group_messages(gid)
             to capture exact in-box `dName` for active speakers.
          4. Query both /api/social/friend/getprofiles/v2 and /api/social/group/getprofiles/v2
             using exact memVerList entries AND normalize returned keys via `k.split("_")[0]`.
          5. Fallback to global_uid_name_map / friends_cache if needed.
        """
        gid = str(gid).split("_")[0].strip()
        if not self.ensure_ready():
            return self.members_cache.get(gid, [])

        box_map = self.member_name_map.setdefault(gid, {})

        # Pre-seed from friends_cache if empty
        if not self.global_uid_name_map and not self.friends_cache:
            try:
                self.get_friends()
            except Exception:
                pass

        members = []
        raw_mem_ver_list = []
        uid_list = []

        try:
            raw_pl = json.dumps({"gridVerMap": json.dumps({gid: 0})})
            enc_pl = ZaloCrypto.encode_aes(self.secret_key, raw_pl)
            info_url = f"https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2?zpw_ver={self.ZPW_VER}&zpw_type={self.ZPW_TYPE}"
            r_info = self.session.post(info_url, data={"params": enc_pl}, headers=self._headers(), timeout=15)
            dec_info = self._decrypt_response(r_info.json())

            if isinstance(dec_info, dict):
                gmap = dec_info.get("gridInfoMap") or {}
                ginfo = gmap.get(gid) or gmap.get(f"{gid}_0") or (list(gmap.values())[0] if gmap else {})
                if isinstance(ginfo, dict):
                    # Harvest embedded member objects if present
                    for key_cand in ("memize", "profiles", "currentMems", "memberList"):
                        arr = ginfo.get(key_cand)
                        if isinstance(arr, list):
                            for mp in arr:
                                if isinstance(mp, dict):
                                    muid = str(mp.get("id") or mp.get("uid") or mp.get("userId") or "").split("_")[0]
                                    mname = mp.get("dName") or mp.get("displayName") or mp.get("zaloName") or mp.get("name")
                                    if muid and mname:
                                        box_map[muid] = str(mname).strip()
                                        self.global_uid_name_map[muid] = str(mname).strip()

                    mem_ver = ginfo.get("memVerList") or []
                    for m in mem_ver:
                        m_str = str(m).strip()
                        if not m_str:
                            continue
                        raw_mem_ver_list.append(m_str if "_" in m_str else f"{m_str}_0")
                        clean_u = m_str.split("_")[0]
                        if clean_u and clean_u not in uid_list:
                            uid_list.append(clean_u)
        except Exception as e:
            logger.warning(f"Zalo get_members_full step 1 warning: {e}")

        # Step 2: Harvest dName from recent messages inside this exact Zalo chat box
        try:
            recent_msgs = self.get_recent_group_messages(gid)
            for m in recent_msgs:
                if not isinstance(m, dict):
                    continue
                u_from = str(m.get("uidFrom") or m.get("senderId") or "").split("_")[0].strip()
                d_name = str(m.get("dName") or m.get("senderName") or "").strip()
                if u_from and u_from != "0" and d_name:
                    box_map[u_from] = d_name
                    self.global_uid_name_map[u_from] = d_name
                    if u_from not in uid_list:
                        uid_list.append(u_from)
                        raw_mem_ver_list.append(f"{u_from}_0")
        except Exception:
            pass

        # Step 3: Batch query profile endpoints for all members in uid_list
        if uid_list:
            prof_endpoints = [
                f"https://profile-wpa.chat.zalo.me/api/social/friend/getprofiles/v2?zpw_ver={self.ZPW_VER}&zpw_type={self.ZPW_TYPE}",
                f"https://profile-wpa.chat.zalo.me/api/social/group/getprofiles/v2?zpw_ver={self.ZPW_VER}&zpw_type={self.ZPW_TYPE}"
            ]
            for i in range(0, len(uid_list), 45):
                chunk_uids = uid_list[i:i + 45]
                chunk_vers = raw_mem_ver_list[i:i + 45]
                # Ensure every uid in chunk_uids has both raw version and _0 version
                ver_payload = list(dict.fromkeys(chunk_vers + [f"{u}_0" for u in chunk_uids]))
                raw_p = json.dumps({"phonebook_version": int(time.time()), "friend_pversion_map": ver_payload})
                enc_p = ZaloCrypto.encode_aes(self.secret_key, raw_p)

                for p_url in prof_endpoints:
                    try:
                        rp = self.session.post(p_url, data={"params": enc_p}, headers=self._headers(), timeout=12)
                        dec_p = self._decrypt_response(rp.json())
                        if isinstance(dec_p, dict):
                            for dict_key in ("changed_profiles", "unchanged_profiles", "profiles", "data"):
                                sub_map = dec_p.get(dict_key)
                                if isinstance(sub_map, dict):
                                    for raw_k, pinfo in sub_map.items():
                                        clean_k = str(raw_k).split("_")[0].strip()
                                        if isinstance(pinfo, dict) and clean_k:
                                            pname = (
                                                pinfo.get("displayName")
                                                or pinfo.get("dName")
                                                or pinfo.get("zaloName")
                                                or pinfo.get("username")
                                                or pinfo.get("name")
                                            )
                                            if pname and str(pname).strip():
                                                box_map[clean_k] = str(pname).strip()
                                                self.global_uid_name_map[clean_k] = str(pname).strip()
                    except Exception:
                        pass

                # Build final member entries for this chunk
                for u in chunk_uids:
                    resolved_name = (
                        box_map.get(u)
                        or self.global_uid_name_map.get(u)
                        or f"Thành viên {u[-4:]}"
                    )
                    members.append({
                        "uid": str(u),
                        "name": resolved_name
                    })

        # Also include any members discovered in box_map that weren't in uid_list
        existing_uids = {m["uid"] for m in members}
        for u, n in box_map.items():
            if u not in existing_uids and u != self.uid:
                members.append({"uid": str(u), "name": str(n)})

        if members:
            self.members_cache[gid] = members
        return self.members_cache.get(gid, [])

    def resolve_tags_for_box(self, gid, requested_tags=None, raw_tag_text="", auto_tag_box=False):
        """
        SMART PER-BOX ZALO @TAG RESOLVER:
        Ensures that any @Tag (whether passed as UID, @Name in text, or auto-tag mode)
        is resolved against the ACTUAL members and display names inside `gid`!
        Returns: list of dicts [{"uid": str, "name": str}, ...]
        """
        gid = str(gid).split("_")[0].strip()
        members = self.members_cache.get(gid) or self.get_members_full(gid) or []
        box_map = self.member_name_map.get(gid, {})

        resolved = []
        seen_uids = set()

        def _add_tag(uid_val, name_val):
            u_str = str(uid_val).split("_")[0].strip()
            if not u_str:
                return
            clean_n = str(name_val or "").strip().lstrip("@").strip()
            if not clean_n or clean_n.startswith("Người dùng ") or clean_n.startswith("Thành viên "):
                clean_n = box_map.get(u_str) or self.global_uid_name_map.get(u_str) or clean_n or f"User_{u_str[-4:]}"
            if u_str not in seen_uids:
                seen_uids.add(u_str)
                resolved.append({"uid": u_str, "name": clean_n})

        # 1. Process explicit requested_tags from UI or caller
        if isinstance(requested_tags, list):
            for t in requested_tags:
                if not isinstance(t, dict):
                    continue
                t_uid = str(t.get("uid") or "").strip()
                t_name = str(t.get("name") or "").strip().lstrip("@").strip()
                if t_uid in ("-1", "all", "@all", "everyone"):
                    _add_tag("-1", "All")
                    continue
                # If caller gave a real UID that is in this box (or valid numeric UID)
                if t_uid and t_uid.isdigit():
                    # Check if this UID is in the target box; if so, use its exact box display name
                    in_box_name = box_map.get(t_uid) or self.global_uid_name_map.get(t_uid) or t_name
                    _add_tag(t_uid, in_box_name)
                elif t_name:
                    # Caller gave a name without UID (or cross-box name) -> match in current box!
                    matched = self.find_member_in_box_by_name(gid, t_name, members)
                    if matched:
                        _add_tag(matched["uid"], matched["name"])

        # 2. Process raw_tag_text (e.g. user typed "@Nguyen Van A, @Tran B" or "@all" in UI Quick-Tag box)
        if raw_tag_text and str(raw_tag_text).strip():
            parts = [p.strip() for p in re.split(r"[,;\n]+", str(raw_tag_text)) if p.strip()]
            for part in parts:
                q = part.lstrip("@").strip()
                if not q:
                    continue
                if q.lower() in ("all", "tatca", "tất cả", "everyone", "mọi người"):
                    _add_tag("-1", "All")
                elif q.isdigit() and len(q) >= 8:
                    _add_tag(q, box_map.get(q) or self.global_uid_name_map.get(q) or f"User_{q[-4:]}")
                else:
                    matched = self.find_member_in_box_by_name(gid, q, members)
                    if matched:
                        _add_tag(matched["uid"], matched["name"])

        # 3. If auto_tag_box is enabled and no specific tag was resolved yet, pick active member(s) in box
        if auto_tag_box and not resolved and members:
            candidates = [m for m in members if str(m.get("uid")) != str(self.uid)]
            if candidates:
                chosen = random.choice(candidates)
                _add_tag(chosen["uid"], chosen["name"])

        return resolved

    def find_member_in_box_by_name(self, gid, query_name, members=None):
        """Fuzzy + Vietnamese accent-insensitive member matcher inside a specific Zalo chat box."""
        q_raw = str(query_name or "").strip().lstrip("@").strip()
        if not q_raw:
            return None
        if q_raw.lower() in ("all", "tatca", "tất cả", "everyone"):
            return {"uid": "-1", "name": "All"}

        if members is None:
            members = self.members_cache.get(gid) or self.get_members_full(gid) or []

        q_lower = q_raw.lower()
        q_norm = normalize_vn_text(q_raw)

        # Pass 1: Exact case-insensitive match
        for m in members:
            mname = str(m.get("name") or "").strip()
            if mname.lower() == q_lower:
                return m

        # Pass 2: Exact accent-normalized match
        for m in members:
            mname = str(m.get("name") or "").strip()
            if normalize_vn_text(mname) == q_norm and q_norm:
                return m

        # Pass 3: Prefix / substring match (preferring longer/more specific names)
        best_match = None
        for m in members:
            mname = str(m.get("name") or "").strip()
            if mname.startswith("Thành viên ") or mname.startswith("Người dùng "):
                continue
            mn_lower = mname.lower()
            mn_norm = normalize_vn_text(mname)
            if q_lower in mn_lower or mn_lower in q_lower or (q_norm and (q_norm in mn_norm or mn_norm in q_norm)):
                if not best_match or len(mname) > len(best_match.get("name", "")):
                    best_match = m
        return best_match

    def _send_raw_payload(self, target_id, text_content, is_group=True, mentions=None, style_cfg=None, ttl=0):
        """
        Core encrypted message dispatcher for Zalo (v8.0 ULTRA) with:
        - Monotonic 13-digit clientId from ZaloAntiBanEngine
        - Zero-shift UTF-16LE `mentionInfo` + `textProperties` calculation
        - Zero-width cryptographic tail placed strictly AFTER all @Tags
        """
        if not self.ensure_ready():
            return False, "Chưa đăng nhập Zalo"

        target_id = str(target_id).split("_")[0].strip()
        base_text = str(text_content or "").strip()
        if not base_text and not mentions:
            return False, "Nội dung trống"

        # 1. Build visible body and compute exact UTF-16LE offsets for @Tags
        final_body = base_text
        valid_mentions = []

        if mentions and isinstance(mentions, list) and is_group:
            tag_segments = []
            for m in mentions:
                uid = str(m.get("uid") or "").split("_")[0].strip()
                raw_name = str(m.get("name") or "").strip().lstrip("@").strip()
                if not uid:
                    continue
                if uid in ("-1", "all", "@all", "everyone"):
                    uid = "-1"
                    tag_str = f"@{raw_name}" if raw_name else "@All"
                else:
                    # Look up best known display name in this box if generic
                    if not raw_name or raw_name.startswith("Thành viên ") or raw_name.startswith("Người dùng "):
                        raw_name = (
                            self.member_name_map.get(target_id, {}).get(uid)
                            or self.global_uid_name_map.get(uid)
                            or raw_name
                            or f"User_{uid[-4:]}"
                        )
                    tag_str = f"@{raw_name}"
                tag_segments.append((uid, tag_str))

            if tag_segments:
                if final_body:
                    final_body += " "
                for idx, (uid, tag_str) in enumerate(tag_segments):
                    if idx > 0:
                        final_body += " "
                    pos = utf16_len(final_body)
                    t_len = utf16_len(tag_str)
                    final_body += tag_str
                    m_type = 1 if str(uid) == "-1" else 0
                    valid_mentions.append({
                        "pos": int(pos),
                        "len": int(t_len),
                        "uid": -1 if str(uid) == "-1" else str(uid),
                        "type": int(m_type)
                    })

        # 2. Compute Rich-Text `textProperties` over visible text BEFORE invisible tail
        visible_u16_len = utf16_len(final_body)
        text_props_str = None
        if style_cfg and isinstance(style_cfg, dict) and visible_u16_len > 0:
            styles = []
            if style_cfg.get("bold"):
                styles.append({"start": 0, "len": visible_u16_len, "st": "b"})
            if style_cfg.get("italic"):
                styles.append({"start": 0, "len": visible_u16_len, "st": "i"})
            if style_cfg.get("underline"):
                styles.append({"start": 0, "len": visible_u16_len, "st": "u"})
            if style_cfg.get("strike"):
                styles.append({"start": 0, "len": visible_u16_len, "st": "s"})

            sz = str(style_cfg.get("size") or "").lower()
            if sz in ("big", "large", "xl", "h1"):
                styles.append({"start": 0, "len": visible_u16_len, "st": "f_18"})
            elif sz in ("small", "sm"):
                styles.append({"start": 0, "len": visible_u16_len, "st": "f_13"})

            col = str(style_cfg.get("color") or "").lower().lstrip("#")
            color_map = {
                "red": "c_db342e", "db342e": "c_db342e", "ff0000": "c_db342e",
                "orange": "c_f27806", "f27806": "c_f27806", "ffaa00": "c_f27806",
                "yellow": "c_f7b500", "f7b500": "c_f7b500", "ffff00": "c_f7b500",
                "green": "c_15a85f", "15a85f": "c_15a85f", "00ff00": "c_15a85f",
                "blue": "c_0068ff", "0068ff": "c_0068ff",
                "purple": "c_6f32be", "6f32be": "c_6f32be",
                "pink": "c_e03b8b", "e03b8b": "c_e03b8b"
            }
            if col in color_map:
                styles.append({"start": 0, "len": visible_u16_len, "st": color_map[col]})

            if styles:
                text_props_str = json.dumps({"styles": styles, "ver": 0}, separators=(",", ":"))

        # 3. Append Zalo Anti-Ban Zero-Shift Cryptographic Tail strictly at the END
        final_body_stealth = ZaloAntiBanEngine.apply_invisible_tail(final_body)

        # 4. Construct Zalo payload with 13-digit monotonic clientId
        client_id = int(ZALO_ANTIBAN.next_client_id(self.uid))
        pl = {
            "message": final_body_stealth,
            "clientId": client_id,
            "imei": self.imei,
            "ttl": int(ttl or 0)
        }

        if is_group:
            pl["grid"] = str(target_id)
            pl["visibility"] = 0
            if valid_mentions:
                pl["mentionInfo"] = json.dumps(valid_mentions, separators=(",", ":"))
        else:
            pl["toid"] = str(target_id)

        if text_props_str:
            pl["textProperties"] = text_props_str

        # Choose exact Zalo endpoint based on group vs DM and mention presence
        if is_group:
            if valid_mentions:
                url = f"https://tt-group-wpa.chat.zalo.me/api/group/mention?zpw_ver={self.ZPW_VER}&zpw_type={self.ZPW_TYPE}"
            else:
                url = f"https://tt-group-wpa.chat.zalo.me/api/group/sendmsg?zpw_ver={self.ZPW_VER}&zpw_type={self.ZPW_TYPE}"
        else:
            url = f"https://tt-chat2-wpa.chat.zalo.me/api/message/sms?zpw_ver={self.ZPW_VER}&zpw_type={self.ZPW_TYPE}"

        try:
            raw_json = json.dumps(pl, ensure_ascii=False, separators=(",", ":"))
            enc_params = ZaloCrypto.encode_aes(self.secret_key, raw_json)
            r = self.session.post(url, data={"params": enc_params}, headers=self._headers(), timeout=15)
            js = r.json()
            err_code = js.get("error_code", -1)

            # Fallback: if /api/group/mention returned non-zero, retry via /api/group/sendmsg with mentionInfo preserved
            if err_code != 0 and is_group and valid_mentions:
                fallback_url = f"https://tt-group-wpa.chat.zalo.me/api/group/sendmsg?zpw_ver={self.ZPW_VER}&zpw_type={self.ZPW_TYPE}"
                r2 = self.session.post(fallback_url, data={"params": enc_params}, headers=self._headers(), timeout=15)
                js2 = r2.json()
                if js2.get("error_code") == 0:
                    ZALO_ANTIBAN.record_result(self.uid, True, 0)
                    return True, "OK"

            if err_code == 0:
                ZALO_ANTIBAN.record_result(self.uid, True, 0)
                return True, "OK"
            else:
                ZALO_ANTIBAN.record_result(self.uid, False, err_code)
                return False, f"Zalo Error {err_code}: {js.get('error_message', '')}"
        except Exception as e:
            ZALO_ANTIBAN.record_result(self.uid, False, -99)
            return False, str(e)

    def send_Message(self, target_id, text_content, is_group=True, mentions=None, style_cfg=None, ttl=0):
        return self._send_raw_payload(target_id, text_content, is_group=is_group, mentions=mentions, style_cfg=style_cfg, ttl=ttl)

    def get_recent_group_messages(self, gid):
        """Fetches recent messages in a group box (used for polling fallback AND member dName harvesting)."""
        if not self.ensure_ready():
            return []
        try:
            raw_pl = json.dumps({"grid": str(gid).split("_")[0], "imei": self.imei, "count": 30})
            enc_pl = ZaloCrypto.encode_aes(self.secret_key, raw_pl)
            url = f"https://tt-group-wpa.chat.zalo.me/api/cm/getrecentv2?zpw_ver={self.ZPW_VER}&zpw_type={self.ZPW_TYPE}"
            r = self.session.post(url, data={"params": enc_pl}, headers=self._headers(), timeout=10)
            dec = self._decrypt_response(r.json())
            if isinstance(dec, dict):
                msgs = dec.get("groupMsgs") or dec.get("msgs") or []
                # Opportunistically cache sender dNames for this box
                box_map = self.member_name_map.setdefault(str(gid).split("_")[0], {})
                for m in msgs:
                    if isinstance(m, dict):
                        u_from = str(m.get("uidFrom") or "").split("_")[0].strip()
                        d_name = str(m.get("dName") or "").strip()
                        if u_from and d_name:
                            box_map[u_from] = d_name
                            self.global_uid_name_map[u_from] = d_name
                return msgs if isinstance(msgs, list) else []
        except Exception:
            pass
        return []


# ==============================================================================
#  SECTION 6: DISCORD CLIENT ENGINE (UNBOXED FULL-SIZE TEXT + STEALTH ROUTING)
#             & DISCORD REG / TOKEN EXTRACTOR HELPER
# ==============================================================================

def discord_reg_or_extract_token(mode="extract", raw_input="", email="", password="", mfa_code="", proxy=""):
    """
    DISCORD REG & SAFE TOKEN EXTRACTOR + SESSION WARMER ("lấy token discord bằng reg cho đỡ bị die"):
    Supports two seamless modes:
      1. mode == "extract": Extracts Discord token(s) from any pasted Reg output,
         cURL command, Network Header dump, HAR JSON, or LocalStorage snippet,
         then warms the session with a deterministic X-Super-Properties browser
         fingerprint so the token stays alive.
      2. mode == "login": Performs an authentic Discord Browser Client login flow:
         - Warms session at `GET https://discord.com/api/v9/experiments` to obtain
           an official `X-Fingerprint` token.
         - Sends `POST https://discord.com/api/v9/auth/login` with cloaked
           `X-Super-Properties` + `X-Fingerprint` headers.
         - If 2FA (`mfa: True`) is required and `mfa_code` is supplied, completes
           `POST https://discord.com/api/v9/auth/mfa/totp` to return the live token.
    Returns: dict with {"ok": bool, "token": str, "user": dict, "super_props_b64": str, "fingerprint": str, "ua": str, "msg": str}
    """
    sess = requests.Session()
    sess.verify = False
    if proxy and str(proxy).strip():
        p_url = proxy.strip() if "://" in proxy.strip() else f"http://{proxy.strip()}"
        sess.proxies = {"http": p_url, "https": p_url}

    seed = email or raw_input or str(time.time())
    ident = DISCORD_ANTIBAN.get_or_build_identity(seed)
    base_headers = {
        "User-Agent": ident["ua"],
        "Accept": "*/*",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/json",
        "Origin": "https://discord.com",
        "Referer": "https://discord.com/login",
        "X-Super-Properties": ident["super_props_b64"],
        "X-Discord-Locale": "vi",
        "X-Discord-Timezone": "Asia/Ho_Chi_Minh",
        "X-Debug-Options": "bugReporterEnabled",
        "Sec-Ch-Ua": ident["sec_ch_ua"],
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": ident["platform"],
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin"
    }

    extracted_token = ""
    fingerprint = ""

    # Step A: If mode is "extract" (or raw_input contains a token/cURL/Reg line)
    if mode == "extract" or (raw_input and not (email and password)):
        raw_str = str(raw_input or "").strip()
        if not raw_str:
            return {"ok": False, "msg": "Vui lòng dán chuỗi Reg / cURL / Header / Token vào ô trích xuất."}

        # Look for standard Discord token pattern (mfa.xxx or base64_id.timestamp.hmac)
        m_mfa = re.search(r"\b(mfa\.[A-Za-z0-9_\-]{20,120})\b", raw_str)
        m_std = re.search(r"\b([A-Za-z0-9_\-]{18,32}\.[A-Za-z0-9_\-]{6,12}\.[A-Za-z0-9_\-]{20,60})\b", raw_str)
        if m_mfa:
            extracted_token = m_mfa.group(1)
        elif m_std:
            extracted_token = m_std.group(1)
        else:
            # Check email:pass:token format common in Reg tools
            colon_parts = [p.strip() for p in raw_str.split(":") if p.strip()]
            if len(colon_parts) >= 3 and len(colon_parts[-1]) > 25:
                extracted_token = colon_parts[-1].strip('"\'')
            elif len(raw_str) > 25 and " " not in raw_str:
                extracted_token = raw_str.strip('"\'')

        # Also extract X-Super-Properties or User-Agent if pasted from DevTools cURL
        m_super = re.search(r"x-super-properties['\"\s:]+([A-Za-z0-9+/=]{40,})", raw_str, flags=re.I)
        if m_super:
            ident["super_props_b64"] = m_super.group(1).strip()
        m_fp = re.search(r"x-fingerprint['\"\s:]+([0-9]+\.[A-Za-z0-9_\-]+)", raw_str, flags=re.I)
        if m_fp:
            fingerprint = m_fp.group(1).strip()

        if not extracted_token:
            return {"ok": False, "msg": "Không tìm thấy Token hợp lệ trong dữ liệu đã dán. Hãy dán dòng Reg (email:pass:token), cURL, hoặc Token."}

    # Step B: If mode is "login" (Reg / Direct Email+Password Login)
    elif mode == "login":
        email = str(email or "").strip()
        password = str(password or "").strip()
        if not email or not password:
            return {"ok": False, "msg": "Vui lòng nhập đầy đủ Email/SĐT và Mật khẩu Discord."}

        # 1. Warm X-Fingerprint via /api/v9/experiments
        try:
            r_exp = sess.get("https://discord.com/api/v9/experiments", headers=base_headers, timeout=12)
            if r_exp.status_code == 200:
                fingerprint = r_exp.json().get("fingerprint", "")
                if fingerprint:
                    base_headers["X-Fingerprint"] = fingerprint
        except Exception:
            pass

        # 2. Authenticate at /api/v9/auth/login
        try:
            login_payload = {
                "login": email,
                "password": password,
                "undelete": False,
                "login_source": None,
                "gift_code_sku_id": None
            }
            r_login = sess.post("https://discord.com/api/v9/auth/login", json=login_payload, headers=base_headers, timeout=15)
            js_login = r_login.json() if r_login.content else {}

            if r_login.status_code == 200 and js_login.get("token"):
                extracted_token = js_login["token"]
            elif js_login.get("mfa") and js_login.get("ticket"):
                ticket = js_login["ticket"]
                if not mfa_code:
                    return {
                        "ok": False,
                        "need_mfa": True,
                        "msg": "Tài khoản bật 2FA. Vui lòng nhập mã 6 số Authenticator vào ô Mã 2FA rồi bấm Lấy Token lại."
                    }
                mfa_payload = {
                    "code": str(mfa_code).strip(),
                    "ticket": ticket,
                    "login_source": None,
                    "gift_code_sku_id": None
                }
                r_mfa = sess.post("https://discord.com/api/v9/auth/mfa/totp", json=mfa_payload, headers=base_headers, timeout=15)
                js_mfa = r_mfa.json() if r_mfa.content else {}
                if r_mfa.status_code == 200 and js_mfa.get("token"):
                    extracted_token = js_mfa["token"]
                else:
                    return {"ok": False, "msg": f"Xác thực 2FA thất bại: {js_mfa.get('message', 'Mã không đúng')}"}
            elif "captcha_key" in js_login:
                return {
                    "ok": False,
                    "msg": "Discord yêu cầu giải Captcha tại IP hiện tại. Hãy dùng tab 'Trích xuất từ cURL / Reg / F12' bên cạnh để lấy Token an toàn 100% không dính Captcha!"
                }
            else:
                err_detail = js_login.get("message") or f"HTTP {r_login.status_code}"
                return {"ok": False, "msg": f"Đăng nhập Discord thất bại: {err_detail}"}
        except Exception as e:
            return {"ok": False, "msg": f"Lỗi kết nối tới Discord Auth: {e}"}

    # Step C: Warm Session & Verify Token with Cloaked Identity
    try:
        warm_headers, final_ident = DISCORD_ANTIBAN.build_stealth_headers(
            extracted_token,
            seed_str=extracted_token,
            channel_id="@me",
            saved_super_b64=ident["super_props_b64"],
            saved_ua=ident["ua"],
            saved_fp=fingerprint
        )
        r_me = sess.get("https://discord.com/api/v9/users/@me", headers=warm_headers, timeout=12)
        if r_me.status_code == 200:
            user_data = r_me.json()
            uid = str(user_data.get("id", ""))
            uname = user_data.get("username", "user")
            gname = user_data.get("global_name") or uname
            return {
                "ok": True,
                "token": extracted_token,
                "uid": uid,
                "username": uname,
                "name": gname,
                "super_props_b64": final_ident["super_props_b64"],
                "fingerprint": fingerprint,
                "ua": final_ident["ua"],
                "msg": f"Đã trích xuất & ủ ấm phiên Token thành công cho {mask_account_name(gname)}!"
            }
        else:
            return {"ok": False, "msg": f"Token không hợp lệ hoặc đã hết hạn (HTTP {r_me.status_code})."}
    except Exception as e:
        return {"ok": False, "msg": f"Lỗi kiểm tra Token: {e}"}


class DiscordBot:
    """
    Full-featured Discord Client Engine (v8.0 ULTRA):
    - Powered by DiscordStealthAntiBanEngine (DISCORD PHANTOM ROUTE v8.0):
      Route & Telemetry Cloaking (`X-Super-Properties`, `X-Discord-Locale`,
      `X-Discord-Timezone`, dynamic channel `Referer`, authentic 64-bit
      Discord Epoch Snowflake nonces, and throttled human `/typing` simulation).
    - Unboxed Full-Size Typography ("làm cho cái chữ bên dis gửi đừng đóng khung
      nhìn nó phèn quá cứ bung ra hết chữ ra"):
      Completely removes ```ansi ... ``` dark code-block boxes! Messages now
      expand across the full Discord chat width using native Markdown (`# ` big
      bold header, `**...**` bold text, or clean unboxed text) + real clickable
      `<@uid>` / `@everyone` mentions.
    """
    BASE_API = "https://discord.com/api/v9"

    def __init__(self, uid, name, username, token, proxy="", super_props_b64="", fingerprint="", user_agent=""):
        self.uid = str(uid).strip()
        self.name = str(name or "Discord User").strip()
        self.username = str(username or "user").strip()
        self.token = str(token).strip()
        self.proxy = str(proxy or "").strip()
        self.super_props_b64 = str(super_props_b64 or "").strip()
        self.fingerprint = str(fingerprint or "").strip()
        self.user_agent = str(user_agent or "").strip()

        self.session = requests.Session()
        self.session.verify = False
        self._apply_proxy()

        self.online = False
        self.guilds_cache = []
        self.channels_cache = []
        self.dm_cache = []
        self.channel_members_cache = {}  # { channel_id: [ {uid, name}, ... ] }

    def _apply_proxy(self):
        if self.proxy:
            p_url = self.proxy if "://" in self.proxy else f"http://{self.proxy}"
            self.session.proxies = {"http": p_url, "https": p_url}
        else:
            self.session.proxies = {}

    def _headers(self, channel_id="@me"):
        headers, ident = DISCORD_ANTIBAN.build_stealth_headers(
            self.token,
            seed_str=self.uid or self.token,
            channel_id=channel_id,
            saved_super_b64=self.super_props_b64,
            saved_ua=self.user_agent,
            saved_fp=self.fingerprint
        )
        if not self.super_props_b64:
            self.super_props_b64 = ident["super_props_b64"]
        if not self.user_agent:
            self.user_agent = ident["ua"]
        return headers

    def check_token(self):
        """Verifies Discord token and caches user profile with stealth headers."""
        try:
            r = self.session.get(f"{self.BASE_API}/users/@me", headers=self._headers("@me"), timeout=12)
            if r.status_code == 200:
                data = r.json()
                self.uid = str(data.get("id", self.uid))
                self.username = data.get("username", self.username)
                self.name = data.get("global_name") or self.username
                self.online = True
                push_sys_log("SUCCESS", "DISCORD", f"Kết nối thành công Discord: {mask_account_name(self.name)} (ID: {mask_sensitive_id(self.uid)})")
                return True, data
            self.online = False
            return False, f"Token không hợp lệ (HTTP {r.status_code})"
        except Exception as e:
            self.online = False
            return False, f"Lỗi kết nối Discord: {e}"

    def get_targets(self):
        """Fetches all accessible Discord text channels across guilds and active DMs."""
        targets = []
        try:
            r_dm = self.session.get(f"{self.BASE_API}/users/@me/channels", headers=self._headers("@me"), timeout=12)
            if r_dm.status_code == 200:
                for ch in r_dm.json():
                    ch_id = str(ch.get("id", ""))
                    ch_type = ch.get("type", 1)
                    recips = ch.get("recipients") or []
                    if ch_type == 1 and recips:
                        r_name = recips[0].get("global_name") or recips[0].get("username") or "DM"
                        label = f"[DM] {r_name}"
                    else:
                        label = f"[Group DM] {ch.get('name') or ', '.join(x.get('username', '') for x in recips[:3]) or ch_id[-4:]}"
                    targets.append({
                        "id": ch_id,
                        "name": label,
                        "guild_id": "@me",
                        "type": "dm"
                    })

            r_guilds = self.session.get(f"{self.BASE_API}/users/@me/guilds", headers=self._headers("@me"), timeout=12)
            if r_guilds.status_code == 200:
                guilds = r_guilds.json()
                self.guilds_cache = guilds
                for g in guilds[:25]:
                    gid = str(g.get("id", ""))
                    gname = g.get("name", "Server")
                    try:
                        r_ch = self.session.get(f"{self.BASE_API}/guilds/{gid}/channels", headers=self._headers(gid), timeout=10)
                        if r_ch.status_code == 200:
                            for ch in r_ch.json():
                                if ch.get("type") in (0, 5):
                                    targets.append({
                                        "id": str(ch.get("id")),
                                        "name": f"[{gname}] #{ch.get('name', 'channel')}",
                                        "guild_id": gid,
                                        "type": "channel"
                                    })
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Discord get_targets warning: {e}")

        if targets:
            self.channels_cache = targets
        return self.channels_cache

    def get_channel_members(self, channel_id):
        """Extracts recent active participants in a Discord channel for quick @Tagging."""
        channel_id = str(channel_id).strip()
        members_map = {}
        try:
            r = self.session.get(
                f"{self.BASE_API}/channels/{channel_id}/messages?limit=50",
                headers=self._headers(channel_id),
                timeout=12
            )
            if r.status_code == 200:
                for msg in r.json():
                    author = msg.get("author") or {}
                    au_id = str(author.get("id") or "")
                    if au_id and not author.get("bot"):
                        au_name = author.get("global_name") or author.get("username") or f"User_{au_id[-4:]}"
                        members_map[au_id] = au_name
                    for mt in (msg.get("mentions") or []):
                        m_id = str(mt.get("id") or "")
                        if m_id:
                            m_name = mt.get("global_name") or mt.get("username") or f"User_{m_id[-4:]}"
                            members_map[m_id] = m_name
        except Exception as e:
            logger.warning(f"Discord get_channel_members warning: {e}")

        out = [{"uid": k, "name": v} for k, v in members_map.items()]
        if out:
            self.channel_members_cache[channel_id] = out
        return self.channel_members_cache.get(channel_id, [])

    def resolve_tags_for_channel(self, channel_id, requested_tags=None, raw_tag_text="", auto_tag_box=False):
        """Resolves @Tags (UIDs, @Names, or @everyone) for a specific Discord channel."""
        channel_id = str(channel_id).strip()
        members = self.channel_members_cache.get(channel_id) or self.get_channel_members(channel_id) or []
        resolved = []
        seen = set()

        def _add(u, n):
            u_s = str(u).strip()
            if not u_s or u_s in seen:
                return
            seen.add(u_s)
            resolved.append({"uid": u_s, "name": str(n or u_s).strip()})

        if isinstance(requested_tags, list):
            for t in requested_tags:
                if isinstance(t, dict):
                    u = str(t.get("uid") or "").strip()
                    n = str(t.get("name") or "").strip().lstrip("@")
                    if u in ("-1", "all", "@all", "everyone", "@everyone"):
                        _add("everyone", "everyone")
                    elif u.isdigit():
                        _add(u, n)
                    elif n:
                        q_norm = normalize_vn_text(n)
                        for m in members:
                            if normalize_vn_text(m["name"]) == q_norm or n.lower() in m["name"].lower():
                                _add(m["uid"], m["name"])
                                break

        if raw_tag_text and str(raw_tag_text).strip():
            for part in re.split(r"[,;\n]+", str(raw_tag_text)):
                q = part.strip().lstrip("@").strip()
                if not q:
                    continue
                if q.lower() in ("all", "everyone", "here", "tatca", "tất cả"):
                    _add("everyone", "everyone")
                elif q.isdigit() and len(q) >= 15:
                    _add(q, q)
                else:
                    q_norm = normalize_vn_text(q)
                    for m in members:
                        if normalize_vn_text(m["name"]) == q_norm or q.lower() in m["name"].lower():
                            _add(m["uid"], m["name"])
                            break

        if auto_tag_box and not resolved and members:
            cands = [m for m in members if str(m["uid"]) != str(self.uid)]
            if cands:
                picked = random.choice(cands)
                _add(picked["uid"], picked["name"])

        return resolved

    @staticmethod
    def format_unboxed_message(text, is_heading=False, is_bold=False, is_italic=False, is_underline=False, is_strike=False):
        """
        UNBOXED FULL-SIZE DISCORD TYPOGRAPHY ("đừng đóng khung nhìn nó phèn quá cứ bung ra hết chữ ra"):
        Never wraps text in ```ansi ... ``` or ``` ... ``` code blocks!
        Instead uses native full-width Discord Markdown so text expands out cleanly:
        - `is_heading=True`: Prepends `# ` on each line so Discord renders giant full-width heading text!
        - `is_bold=True`: Wraps with `**...**`
        - `is_italic=True`: Wraps with `*...*`
        - `is_underline=True`: Wraps with `__...__`
        - `is_strike=True`: Wraps with `~~...~~`
        """
        clean = str(text or "").strip()
        if not clean:
            return ""
        # Strip any accidental ``` wrappers if present in old text files
        clean = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", clean).strip()

        lines = clean.splitlines()
        formatted_lines = []
        for ln in lines:
            s = ln.strip()
            if not s:
                formatted_lines.append("")
                continue
            if is_strike:
                s = f"~~{s}~~"
            if is_underline:
                s = f"__{s}__"
            if is_italic:
                s = f"*{s}*"
            if is_bold and not is_heading:
                s = f"**{s}**"
            if is_heading:
                # Native Discord H1 (# ) renders huge & bold across the full chat width without any box
                s = re.sub(r"^#+\s*", "", s)
                s = f"# {s}"
            formatted_lines.append(s)
        return "\n".join(formatted_lines)

    def send_message(self, channel_id, content, mentions=None, color_hex=None, is_heading=False, style_cfg=None, simulate_typing=True):
        """
        Dispatches a message to a Discord channel with:
        1. Full-width unboxed typography (NO ```ansi``` dark box!).
        2. Real clickable `<@uid>` / `@everyone` mentions placed cleanly outside or inside the line.
        3. Discord Phantom Route v8.0 stealth headers (`X-Super-Properties`, channel `Referer`, Snowflake `nonce`).
        4. Optional throttled `/typing` simulation.
        """
        channel_id = str(channel_id).strip()
        base_text = str(content or "").strip()
        if not base_text and not mentions:
            return False, "Nội dung trống"

        # 1. Optional human typing indicator (throttled per account by DISCORD_ANTIBAN)
        if simulate_typing and DISCORD_ANTIBAN.should_send_typing(self.uid):
            try:
                self.session.post(
                    f"{self.BASE_API}/channels/{channel_id}/typing",
                    headers=self._headers(channel_id),
                    timeout=5
                )
            except Exception:
                pass

        # 2. Extract style flags (never use boxed codeblocks; if user picked a color or heading, make it bold/heading!)
        is_bold = bool(color_hex and color_hex != "none")
        is_italic = False
        is_underline = False
        is_strike = False
        if isinstance(style_cfg, dict):
            is_bold = is_bold or bool(style_cfg.get("bold"))
            is_italic = bool(style_cfg.get("italic"))
            is_underline = bool(style_cfg.get("underline"))
            is_strike = bool(style_cfg.get("strike"))
            if str(style_cfg.get("size") or "").lower() in ("big", "large", "xl", "h1"):
                is_heading = True

        # 3. Build real clickable mention string (`<@uid>` or `@everyone`)
        mention_tokens = []
        allowed_users = []
        allow_everyone = False
        if mentions and isinstance(mentions, list):
            for m in mentions:
                uid = str(m.get("uid") or "").strip()
                if not uid:
                    continue
                if uid in ("-1", "all", "@all", "everyone", "@everyone"):
                    mention_tokens.append("@everyone")
                    allow_everyone = True
                else:
                    clean_uid = re.sub(r"[^\d]", "", uid)
                    if clean_uid:
                        mention_tokens.append(f"<@{clean_uid}>")
                        if clean_uid not in allowed_users:
                            allowed_users.append(clean_uid)

        # 4. Format full-size unboxed text and combine with real mentions
        body = self.format_unboxed_message(
            base_text,
            is_heading=is_heading,
            is_bold=is_bold,
            is_italic=is_italic,
            is_underline=is_underline,
            is_strike=is_strike
        )
        if mention_tokens:
            m_str = " ".join(mention_tokens)
            body = f"{body} {m_str}".strip()

        # 5. Apply Zero-Shift Anti-AutoMod invisible tail
        body = DiscordStealthAntiBanEngine.apply_invisible_tail(body)

        # 6. Build payload with authentic 64-bit Discord Epoch Snowflake nonce
        allowed_mentions = {"parse": ["users", "roles", "everyone"] if allow_everyone else ["users"]}
        if allowed_users:
            allowed_mentions["users"] = allowed_users

        payload = {
            "content": body[:1995],
            "tts": False,
            "flags": 0,
            "nonce": DISCORD_ANTIBAN.generate_snowflake_nonce(self.uid),
            "allowed_mentions": allowed_mentions
        }

        try:
            url = f"{self.BASE_API}/channels/{channel_id}/messages"
            r = self.session.post(url, json=payload, headers=self._headers(channel_id), timeout=15)
            if r.status_code in (200, 201):
                DISCORD_ANTIBAN.record_result(self.uid, True, r.status_code)
                return True, "OK"
            elif r.status_code == 429:
                retry_after = 2.0
                try:
                    retry_after = float(r.json().get("retry_after", 2.0))
                except Exception:
                    pass
                DISCORD_ANTIBAN.record_result(self.uid, False, 429, retry_after=retry_after)
                return False, f"Rate Limit 429 (chờ {retry_after:.1f}s)"
            else:
                DISCORD_ANTIBAN.record_result(self.uid, False, r.status_code)
                return False, f"Discord HTTP {r.status_code}"
        except Exception as e:
            DISCORD_ANTIBAN.record_result(self.uid, False, 500)
            return False, str(e)


# ==============================================================================
#  SECTION 7: MULTI-MODE TASK WORKER & PER-BOX SMART @TAG DISPATCHER
# ==============================================================================

def _extract_inline_tags_from_line(line_text, platform, bot_instance, target_id, is_group=True):
    """
    Scans a single message line for inline `@Tên` or `@all` tokens, resolves
    them against the target chat box (`target_id`), strips the raw `@Tên` from
    the body so `_send_raw_payload` can append a properly highlighted mention,
    and returns `(cleaned_line, resolved_mentions_list)`.
    """
    if not line_text or "@" not in line_text or not is_group:
        return line_text, []

    extra_mentions = []
    # Check for @all / @everyone first
    if re.search(r"(?:^|\s)@(all|everyone|tatca|tất\s+cả)(?=\s|$)", line_text, flags=re.I):
        line_text = re.sub(r"(?:^|\s)@(all|everyone|tatca|tất\s+cả)(?=\s|$)", " ", line_text, flags=re.I).strip()
        extra_mentions.append({"uid": "-1" if platform == "zalo" else "everyone", "name": "All"})

    # Check if there is a trailing @Name at the end of the line
    m_trail = re.search(r"(?:^|\s)@([^\s@][^@]{0,35})$", line_text)
    if m_trail and bot_instance:
        cand_name = m_trail.group(1).strip()
        if platform == "zalo" and hasattr(bot_instance, "find_member_in_box_by_name"):
            matched = bot_instance.find_member_in_box_by_name(target_id, cand_name)
            if matched:
                line_text = line_text[:m_trail.start()].strip()
                extra_mentions.append({"uid": str(matched["uid"]), "name": str(matched["name"])})
        elif platform == "discord" and hasattr(bot_instance, "resolve_tags_for_channel"):
            matched_list = bot_instance.resolve_tags_for_channel(target_id, raw_tag_text=cand_name)
            if matched_list:
                line_text = line_text[:m_trail.start()].strip()
                extra_mentions.extend(matched_list)

    return line_text, extra_mentions


def box_target_worker(task_id):
    """
    Background worker thread executing continuous/loop messaging for a specific task.
    Upgraded in v8.0 ULTRA:
    - Dynamically resolves `@Tag` per target chat box (`target_id`) so every Zalo box
      and Discord channel gets accurate, highlighted mentions for its own members!
    - Uses `ZaloAntiBanEngine` for Zalo tasks and `DiscordStealthAntiBanEngine` for
      Discord tasks.
    """
    with GLOBAL_LOCK:
        task = ACTIVE_TASKS.get(task_id)
    if not task:
        return

    platform = task["platform"]
    acc_uid = task["acc_uid"]
    target_id = str(task["target_id"]).split("_")[0].strip()
    is_group = bool(task.get("is_group", True))
    mode = task.get("mode", "nhay")
    base_delay = max(0.4, float(task.get("delay", 2.0)))
    lines = task.get("lines") or ["ALB FORGE v8.0 ULTRA"]
    raw_mentions = task.get("mentions") or []
    raw_tag_text = str(task.get("raw_tag_text") or "").strip()
    auto_tag_box = bool(task.get("auto_tag_box", False))
    style_cfg = task.get("style_cfg") or {}
    color_hex = style_cfg.get("color", "")
    is_heading = (style_cfg.get("size") == "big") or bool(style_cfg.get("heading"))
    random_icon = bool(task.get("random_icon", False))

    bot = ZALO_BOTS.get(acc_uid) if platform == "zalo" else DISCORD_BOTS.get(acc_uid)
    if not bot:
        with GLOBAL_LOCK:
            task["status"] = "ERROR"
            task["last_log"] = "Không tìm thấy phiên Bot."
        return

    # Pre-resolve per-box mentions at task startup so Zalo/Discord tags match this exact chat box
    resolved_box_mentions = []
    try:
        if is_group:
            if platform == "zalo":
                resolved_box_mentions = bot.resolve_tags_for_box(
                    target_id,
                    requested_tags=raw_mentions,
                    raw_tag_text=raw_tag_text,
                    auto_tag_box=auto_tag_box
                )
            else:
                resolved_box_mentions = bot.resolve_tags_for_channel(
                    target_id,
                    requested_tags=raw_mentions,
                    raw_tag_text=raw_tag_text,
                    auto_tag_box=auto_tag_box
                )
    except Exception as e:
        logger.warning(f"Task {task_id} initial box tag resolution warning: {e}")

    # Store resolved mentions back into task for live UI inspection
    with GLOBAL_LOCK:
        task["resolved_mentions"] = resolved_box_mentions

    push_sys_log(
        "INFO", "TASK",
        f"Khởi chạy chiến dịch [{mode.upper()}] #{task_id[:6]} -> Box {mask_sensitive_id(target_id)} (Tag: {len(resolved_box_mentions)} mục tiêu)"
    )

    idx = 0
    total_lines = len(lines)

    while not task["stop_event"].is_set():
        if task.get("paused"):
            time.sleep(0.4)
            continue

        # Select message content based on mode
        if mode == "treo":
            msg_text = "\n".join(lines) if total_lines <= 6 else lines[idx % total_lines]
        elif mode == "random":
            msg_text = random.choice(lines)
        elif mode == "poll":
            msg_text = f"📊 [BÌNH CHỌN] {lines[idx % total_lines]}"
        else:
            msg_text = lines[idx % total_lines]

        idx += 1

        # Extract any inline @Tag written directly inside the text line for this box
        clean_msg_text, inline_mentions = _extract_inline_tags_from_line(
            msg_text, platform, bot, target_id, is_group=is_group
        )

        # Combine box-level mentions + line-level mentions (deduplicated by uid)
        combined_mentions = []
        seen_m_uids = set()
        # If auto_tag_box is on and user wants dynamic rotation among box members on every line:
        if auto_tag_box and not raw_mentions and not raw_tag_text and is_group:
            if platform == "zalo":
                resolved_box_mentions = bot.resolve_tags_for_box(target_id, auto_tag_box=True)
            else:
                resolved_box_mentions = bot.resolve_tags_for_channel(target_id, auto_tag_box=True)

        for m_item in (resolved_box_mentions + inline_mentions):
            u_key = str(m_item.get("uid") or "")
            if u_key and u_key not in seen_m_uids:
                seen_m_uids.add(u_key)
                combined_mentions.append(m_item)

        # Append safe decorative icon BEFORE @Tag calculation
        if random_icon:
            if platform == "zalo":
                # Use 2-char BMP safe Zalo icon so UTF-16 offsets never shift
                clean_msg_text = f"{clean_msg_text} {random.choice(ZALO_SAFE_2CHAR_ICONS)}"
            else:
                clean_msg_text = f"{clean_msg_text} {random.choice(DISCORD_DECOR_ICONS)}"

        # Dispatch via platform client
        if platform == "zalo":
            ok, resp_msg = bot.send_Message(
                target_id=target_id,
                text_content=clean_msg_text,
                is_group=is_group,
                mentions=combined_mentions,
                style_cfg=style_cfg
            )
        else:
            ok, resp_msg = bot.send_message(
                channel_id=target_id,
                content=clean_msg_text,
                mentions=combined_mentions,
                color_hex=color_hex,
                is_heading=is_heading,
                style_cfg=style_cfg
            )

        with GLOBAL_LOCK:
            if ok:
                task["sent_count"] += 1
                tag_badge = f" [Tag:{len(combined_mentions)}]" if combined_mentions else ""
                task["last_log"] = f"Đã gửi #{task['sent_count']}{tag_badge}: {clean_msg_text[:28]}..."
            else:
                task["error_count"] += 1
                task["last_log"] = f"Lỗi: {resp_msg}"

        # Compute platform-specific Anti-Ban delay
        if platform == "zalo":
            sleep_sec, reason = ZALO_ANTIBAN.compute_adaptive_delay(acc_uid, base_delay, len(clean_msg_text))
        else:
            sleep_sec, reason = DISCORD_ANTIBAN.compute_adaptive_delay(acc_uid, base_delay, len(clean_msg_text))

        with GLOBAL_LOCK:
            task["antiban_note"] = f"{reason} ({sleep_sec:.2f}s)"

        # Interruptible sleep
        end_wait = time.time() + sleep_sec
        while time.time() < end_wait and not task["stop_event"].is_set():
            time.sleep(min(0.2, max(0.02, end_wait - time.time())))

    with GLOBAL_LOCK:
        task["status"] = "STOPPED"
    push_sys_log("INFO", "TASK", f"Đã dừng chiến dịch #{task_id[:6]} (Tổng gửi: {task['sent_count']}).")


def spawn_automation_task(
    platform, acc_uid, target_id, target_name, is_group,
    mode, delay, lines, mentions=None, style_cfg=None,
    random_icon=False, source="WEB", raw_tag_text="", auto_tag_box=False
):
    """Creates and starts a background box_target_worker thread."""
    task_id = str(uuid.uuid4())[:8]
    bot = ZALO_BOTS.get(acc_uid) if platform == "zalo" else DISCORD_BOTS.get(acc_uid)
    acc_name = bot.name if bot else acc_uid

    task_obj = {
        "task_id": task_id,
        "platform": platform,
        "acc_uid": str(acc_uid),
        "acc_name": acc_name,
        "target_id": str(target_id).split("_")[0].strip(),
        "target_name": str(target_name or target_id),
        "is_group": bool(is_group),
        "mode": mode,
        "delay": float(delay),
        "lines": lines if lines else ["ALB FORGE v8.0 ULTRA"],
        "mentions": mentions or [],
        "resolved_mentions": [],
        "raw_tag_text": str(raw_tag_text or "").strip(),
        "auto_tag_box": bool(auto_tag_box),
        "style_cfg": style_cfg or {},
        "random_icon": bool(random_icon),
        "source": source,
        "sent_count": 0,
        "error_count": 0,
        "status": "RUNNING",
        "paused": False,
        "last_log": "Đang khởi tạo & đồng bộ danh sách Tag...",
        "antiban_note": "Zalo Matrix v8.0" if platform == "zalo" else "Discord Phantom Route v8.0",
        "started_at": datetime.now().strftime("%H:%M:%S"),
        "stop_event": threading.Event()
    }

    with GLOBAL_LOCK:
        ACTIVE_TASKS[task_id] = task_obj

    with DB_LOCK:
        try:
            conn = get_db_conn()
            conn.execute("""
                INSERT INTO task_history (task_id, platform, acc_uid, acc_name, target_id, target_name, mode, delay, status, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (task_id, platform, acc_uid, mask_account_name(acc_name), str(target_id), str(target_name), mode, float(delay), "RUNNING", task_obj["started_at"]))
            conn.commit()
            conn.close()
        except Exception:
            pass

    t = threading.Thread(target=box_target_worker, args=(task_id,), daemon=True)
    task_obj["thread"] = t
    t.start()
    return task_id


def stop_tasks_by_filter(platform=None, acc_uid=None, target_id=None, task_id=None):
    """Stops matching active tasks and returns count stopped."""
    stopped = 0
    clean_target = str(target_id).split("_")[0].strip() if target_id else None
    with GLOBAL_LOCK:
        for tid, tk in list(ACTIVE_TASKS.items()):
            if task_id and tid != task_id:
                continue
            if platform and tk["platform"] != platform:
                continue
            if acc_uid and str(tk["acc_uid"]) != str(acc_uid):
                continue
            if clean_target and str(tk["target_id"]).split("_")[0].strip() != clean_target:
                continue
            if tk["status"] == "RUNNING":
                tk["stop_event"].set()
                tk["status"] = "STOPPED"
                stopped += 1
    return stopped


# ==============================================================================
#  SECTION 8: SELF-BOT IN-CHAT COMMAND PARSER & TAG EXTRACTOR (ZALO + DISCORD)
# ==============================================================================

def load_txt_lines(filename=None):
    """Loads non-empty lines from a .txt file in TXT_DIR (or default nhay file)."""
    files = sorted([f for f in os.listdir(TXT_DIR) if f.endswith(".txt")])
    if not files:
        _seed_default_txt_files()
        files = sorted([f for f in os.listdir(TXT_DIR) if f.endswith(".txt")])

    chosen = None
    if filename:
        cand = filename if filename.endswith(".txt") else f"{filename}.txt"
        for f in files:
            if f.lower() == cand.lower() or filename.lower() in f.lower():
                chosen = f
                break
    if not chosen and files:
        chosen = "nhay_vip_2026.txt" if "nhay_vip_2026.txt" in files else files[0]

    if chosen:
        try:
            with open(os.path.join(TXT_DIR, chosen), "r", encoding="utf-8", errors="ignore") as fp:
                lines = [ln.strip() for ln in fp.read().splitlines() if ln.strip()]
                if lines:
                    return lines, chosen
        except Exception:
            pass
    return ["ALB FORGE v8.0 ULTRA - Hệ thống tự động hóa đa nền tảng!"], "default.txt"


def extract_trailing_tags_and_resolve(text, platform, bot_instance, target_id, incoming_mentions=None):
    """
    UPGRADED v8.0 ULTRA IN-CHAT @TAG EXTRACTOR & RESOLVER:
    Fixes all Zalo & Discord mention extraction edge cases:
      1. Clamps UTF-16 slice end (`min(len(u16_bytes), (adj_pos + mlen) * 2)`) so
         when Zalo Mobile includes a trailing space inside `mlen`, slicing still
         succeeds 100% of the time!
      2. If `incoming_mentions` has UIDs AND `text` contains `@...`, maps `@...`
         segments directly and enriches names from `bot_instance.member_name_map`
         so even when `pos` is 0 or shifted, the exact UID + display name is captured!
      3. Resolves plain-text `@Tên Thành Viên` (typed without clicking the popup)
         using `bot_instance.find_member_in_box_by_name(target_id, ...)` against
         the full member list of that exact Zalo chat box (`target_id`)!
    Returns: (cleaned_text_without_tags, resolved_mentions_list)
    """
    resolved = []
    seen_uids = set()
    clean_target = str(target_id).split("_")[0].strip()

    def _add_resolved(uid_val, name_val):
        u_str = str(uid_val).split("_")[0].strip()
        if not u_str or u_str in seen_uids:
            return
        n_str = str(name_val or "").strip().lstrip("@").strip()
        if platform == "zalo" and bot_instance and u_str != "-1":
            box_map = getattr(bot_instance, "member_name_map", {}).get(clean_target, {})
            glob_map = getattr(bot_instance, "global_uid_name_map", {})
            if not n_str or n_str.startswith("User_") or n_str.startswith("Thành viên ") or n_str.startswith("Người dùng "):
                n_str = box_map.get(u_str) or glob_map.get(u_str) or n_str
                if not n_str:
                    # Trigger member load for this box to get the real display name
                    try:
                        bot_instance.get_members_full(clean_target)
                        box_map = getattr(bot_instance, "member_name_map", {}).get(clean_target, {})
                        n_str = box_map.get(u_str) or glob_map.get(u_str)
                    except Exception:
                        pass
                n_str = n_str or f"User_{u_str[-4:]}"
        seen_uids.add(u_str)
        resolved.append({"uid": u_str, "name": n_str or u_str})

    # 1. Extract native mentions passed from Zalo mentionInfo or Discord mentions array
    if incoming_mentions and isinstance(incoming_mentions, list):
        u16_bytes = text.encode("utf-16-le")
        # Also extract all @tokens from text in order as a fallback name source
        at_tokens = [m.group(1).strip() for m in re.finditer(r"@([^\s@]+(?:\s+[^\s@]+){0,4})", text)]

        for idx, m in enumerate(incoming_mentions):
            if not isinstance(m, dict):
                continue
            uid = str(m.get("uid") or m.get("id") or "").split("_")[0].strip()
            if not uid:
                continue
            mname = str(m.get("name") or m.get("global_name") or m.get("username") or m.get("dName") or "").strip().lstrip("@").strip()

            # Slice name from UTF-16 pos/len with safe boundary clamping
            if not mname and "pos" in m and "len" in m:
                try:
                    raw_pos = max(0, int(m["pos"]))
                    mlen = max(1, int(m["len"]))
                    start_b = min(len(u16_bytes), raw_pos * 2)
                    end_b = min(len(u16_bytes), (raw_pos + mlen) * 2)
                    if end_b > start_b:
                        sliced = u16_bytes[start_b:end_b].decode("utf-16-le", errors="ignore").strip()
                        # If raw_pos was slightly off by 1 due to leading strip, find '@' nearby
                        if "@" in sliced:
                            sliced = sliced[sliced.find("@") + 1:].strip()
                        else:
                            # Search a 4-code-unit window around raw_pos for '@'
                            win_s = max(0, (raw_pos - 2) * 2)
                            win_e = min(len(u16_bytes), (raw_pos + mlen + 2) * 2)
                            win_str = u16_bytes[win_s:win_e].decode("utf-16-le", errors="ignore")
                            if "@" in win_str:
                                sliced = win_str[win_str.find("@") + 1:].strip()
                        mname = sliced.lstrip("@").strip()
                except Exception:
                    pass

            # Fallback to @token in text if slice was empty
            if not mname and idx < len(at_tokens):
                mname = at_tokens[idx].lstrip("@").strip()

            _add_resolved(uid, mname)

    # 2. Extract Discord `<@123456789>` or `<@!123456789>` tags in text
    discord_tag_matches = re.findall(r"<@!?(\d+)>", text)
    for duid in discord_tag_matches:
        _add_resolved(duid, f"User_{duid[-4:]}")
    text = re.sub(r"<@!?\d+>", "", text).strip()

    # 3. Check for `@all` or `@everyone`
    if re.search(r"(?:^|\s)@(all|everyone|tatca|tất\s+cả)(?=\s|$)", text, flags=re.I):
        _add_resolved("-1" if platform == "zalo" else "everyone", "All")
        text = re.sub(r"(?:^|\s)@(all|everyone|tatca|tất\s+cả)(?=\s|$)", " ", text, flags=re.I).strip()

    # 4. Strip already-resolved @Names from the trailing command text
    if resolved and "@" in text:
        for r_item in resolved:
            r_name = r_item.get("name", "")
            if r_name:
                pattern = re.compile(r"@\s*" + re.escape(r_name) + r"\b", flags=re.I)
                text = pattern.sub("", text).strip()
        # Also strip trailing @... if incoming_mentions already supplied the UIDs
        if incoming_mentions and "@" in text:
            text = text[:text.find("@")].strip()

    # 5. If `@...` STILL remains in text (user typed `@Tên` manually without popup), resolve in target box!
    if "@" in text:
        at_idx = text.find("@")
        tag_part = text[at_idx:].strip()
        text = text[:at_idx].strip()
        raw_tags = [t.strip() for t in tag_part.split("@") if t.strip()]

        for rt in raw_tags:
            if rt.lower() in ("all", "everyone", "tatca", "tất cả"):
                _add_resolved("-1" if platform == "zalo" else "everyone", "All")
                continue
            if rt.isdigit() and len(rt) >= 8:
                _add_resolved(rt, f"User_{rt[-4:]}")
                continue

            if platform == "zalo" and bot_instance:
                matched = bot_instance.find_member_in_box_by_name(clean_target, rt)
                if matched:
                    _add_resolved(matched["uid"], matched["name"])
            elif platform == "discord" and bot_instance:
                d_matches = bot_instance.resolve_tags_for_channel(clean_target, raw_tag_text=rt)
                for dm in d_matches:
                    _add_resolved(dm["uid"], dm["name"])

    return text.strip(), resolved


def parse_and_execute_inchat_command(
    platform, acc_uid, target_id, is_group, raw_text,
    prefix=".", incoming_mentions=None
):
    """
    Universal Self-Bot Command Interpreter for both Zalo & Discord.
    Supports commands right inside any chat box:
      .menu / .help                     -> Hiển thị bảng lệnh Self-Bot v8.0
      .ping / .status                   -> Kiểm tra độ trễ & trạng thái Anti-Ban riêng
      .nhay [delay] [file] [@Tag...]    -> Bật nhây tốc độ cao + tự động Tag chuẩn theo khung chat
      .treo [delay] [noi_dung] [@Tag]   -> Treo tin nhắn tự động lặp lại
      .spam [delay] [noi_dung] [@Tag]   -> Spam nội dung tùy chỉnh kèm @Tag
      .tag [delay] [@Tag / @all]        -> Nhây réo tên trực tiếp mục tiêu trong nhóm
      .autotag [delay] [file]           -> Tự động lấy ngẫu nhiên thành viên trong khung chat để Tag
      .stop / .dung                     -> Dừng ngay tác vụ trong khung chat hiện tại
      .stopall                          -> Dừng toàn bộ chiến dịch của tài khoản này
      .list                             -> Liệt kê các chiến dịch đang chạy
    """
    clean_text = strip_invisible_chars(raw_text)
    if not clean_text or not clean_text.startswith(prefix):
        return False

    bot = ZALO_BOTS.get(acc_uid) if platform == "zalo" else DISCORD_BOTS.get(acc_uid)
    if not bot:
        return False

    clean_target = str(target_id).split("_")[0].strip()

    # If Zalo has incoming mentions or target_id is in groups_cache, force is_group=True
    if platform == "zalo" and not is_group:
        if incoming_mentions:
            is_group = True
        elif any(str(g.get("id")) == clean_target for g in getattr(bot, "groups_cache", [])):
            is_group = True

    cmd_body = clean_text[len(prefix):].strip()
    if not cmd_body:
        return False

    parts = cmd_body.split()
    cmd = parts[0].lower()
    rest_text = cmd_body[len(parts[0]):].strip()

    def _reply(msg_str, mentions_list=None, big=False):
        if platform == "zalo":
            st = {"bold": True, "size": "big" if big else "normal", "color": "blue"}
            bot.send_Message(clean_target, msg_str, is_group=is_group, mentions=mentions_list, style_cfg=st)
        else:
            bot.send_message(clean_target, msg_str, mentions=mentions_list, is_heading=big, style_cfg={"bold": True})

    if cmd in ("menu", "help", "lenh"):
        menu_msg = (
            f"⚡ ALB FORGE v8.0 ULTRA [{platform.upper()} SELF-BOT] ⚡\n"
            f"• {prefix}nhay [delay] [@Tag/@all] : Nhây + Tag chuẩn khung chat\n"
            f"• {prefix}autotag [delay] : Tự động xoay vòng Tag thành viên trong box\n"
            f"• {prefix}treo [delay] <nội dung> [@Tag] : Treo tin nhắn tự động\n"
            f"• {prefix}spam [delay] <nội dung> [@Tag] : Spam câu tùy chọn + Tag\n"
            f"• {prefix}tag [delay] <@Tên/@all> : Réo tên mục tiêu liên tục\n"
            f"• {prefix}stop / {prefix}dung : Dừng tác vụ tại khung chat này\n"
            f"• {prefix}stopall : Dừng tất cả tác vụ\n"
            f"• {prefix}ping : Kiểm tra Anti-Ban & trạng thái"
        )
        _reply(menu_msg)
        return True

    if cmd in ("ping", "status", "check"):
        ab = ZALO_ANTIBAN.get_account_telemetry(acc_uid) if platform == "zalo" else DISCORD_ANTIBAN.get_account_telemetry(acc_uid)
        running_cnt = sum(1 for t in ACTIVE_TASKS.values() if t["acc_uid"] == str(acc_uid) and t["status"] == "RUNNING")
        ping_msg = (
            f"🛡️ [{ab['engine_name']}] ONLINE!\n"
            f"• Điểm an toàn: {ab['health_score']}/100 | Đã gửi: {ab['sent_total']} tin\n"
            f"• Tác vụ đang chạy: {running_cnt} | Box ID: {mask_sensitive_id(clean_target)}"
        )
        _reply(ping_msg)
        return True

    if cmd in ("stop", "dung", "off"):
        cnt = stop_tasks_by_filter(platform=platform, acc_uid=acc_uid, target_id=clean_target)
        _reply(f"🛑 Đã dừng {cnt} tác vụ đang chạy tại khung chat này.")
        return True

    if cmd in ("stopall", "dunghet", "clear"):
        cnt = stop_tasks_by_filter(platform=platform, acc_uid=acc_uid)
        _reply(f"🛑 Đã dừng toàn bộ {cnt} tác vụ của tài khoản.")
        return True

    if cmd in ("list", "tasks", "ds"):
        active_list = [
            f"#{t['task_id'][:5]} [{t['mode'].upper()}] ({t['sent_count']} tin - {t['delay']}s)"
            for t in ACTIVE_TASKS.values()
            if t["acc_uid"] == str(acc_uid) and t["status"] == "RUNNING"
        ]
        if not active_list:
            _reply("📭 Hiện không có chiến dịch nào đang chạy.")
        else:
            _reply("📋 Chiến dịch đang chạy:\n" + "\n".join(active_list))
        return True

    if cmd in ("nhay", "treo", "spam", "tag", "autotag"):
        # Extract trailing @Tags and resolve against this exact chat box
        body_no_tags, mentions_list = extract_trailing_tags_and_resolve(
            rest_text, platform, bot, clean_target, incoming_mentions=incoming_mentions
        )

        tokens = body_no_tags.split() if body_no_tags else []
        delay = 2.0
        rem_text = body_no_tags

        if tokens:
            try:
                delay = max(0.4, float(tokens[0]))
                rem_text = " ".join(tokens[1:]).strip()
            except ValueError:
                delay = 2.0

        auto_tag_box = (cmd == "autotag")

        if cmd in ("nhay", "tag", "autotag"):
            lines, fname = load_txt_lines(rem_text if rem_text else None)
            mode_label = "nhay"
        else:
            if rem_text:
                lines = [s.strip() for s in rem_text.split("|") if s.strip()]
            else:
                lines, _ = load_txt_lines(None)
            mode_label = cmd

        # Stop existing task in the same box before launching a new one
        stop_tasks_by_filter(platform=platform, acc_uid=acc_uid, target_id=clean_target)

        style_cfg = {"bold": True, "size": "big"}
        tid = spawn_automation_task(
            platform=platform,
            acc_uid=acc_uid,
            target_id=clean_target,
            target_name=f"Box {mask_sensitive_id(clean_target)}",
            is_group=is_group,
            mode=mode_label,
            delay=delay,
            lines=lines,
            mentions=mentions_list,
            style_cfg=style_cfg,
            random_icon=True,
            source="IN-CHAT",
            auto_tag_box=auto_tag_box
        )
        push_sys_log("SUCCESS", f"SELF-{platform.upper()}", f"Lệnh {prefix}{cmd} kích hoạt Task #{tid} tại {mask_sensitive_id(clean_target)}")
        return True

    return False


# ==============================================================================
#  SECTION 9: REALTIME WEBSOCKET + REST LISTENERS FOR ZALO & DISCORD SELF-BOT
# ==============================================================================

class ZaloSelfBotListener:
    """
    Listens for self-issued commands on a Zalo account using WebSocket + REST
    polling fallback, caching in-box member display names (`dName`) automatically.
    """
    def __init__(self, zalo_client, prefix="."):
        self.zalo = zalo_client
        self.prefix = prefix or "."
        self.running = False
        self.seen_msg_ids = deque(maxlen=600)
        self.start_ts_ms = int(time.time() * 1000)

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._poll_loop, daemon=True).start()
        if HAS_WEBSOCKET:
            threading.Thread(target=self._ws_loop, daemon=True).start()

    def stop(self):
        self.running = False

    def _process_msg_obj(self, msg_obj, default_grid=None):
        if not isinstance(msg_obj, dict):
            return
        msg_id = str(msg_obj.get("msgId") or msg_obj.get("cliMsgId") or msg_obj.get("globalMsgId") or "")
        if msg_id and msg_id in self.seen_msg_ids:
            return

        ts = int(msg_obj.get("ts") or 0)
        if ts and ts < (self.start_ts_ms - 5000):
            return

        uid_from = str(msg_obj.get("uidFrom") or "").split("_")[0].strip()
        id_to = str(msg_obj.get("idTo") or default_grid or "").split("_")[0].strip()
        d_name = str(msg_obj.get("dName") or "").strip()

        # Cache sender display name for this group box so future @Tags are 100% accurate
        if uid_from and uid_from != "0" and d_name and id_to:
            box_map = self.zalo.member_name_map.setdefault(id_to, {})
            box_map[uid_from] = d_name
            self.zalo.global_uid_name_map[uid_from] = d_name

        content = msg_obj.get("content")
        if not isinstance(content, str):
            return

        # Only trigger commands sent by the account owner
        is_self = (uid_from == "0") or (uid_from == str(self.zalo.uid))
        if not is_self:
            return

        clean_c = strip_invisible_chars(content)
        if not clean_c.startswith(self.prefix):
            return

        if msg_id:
            self.seen_msg_ids.append(msg_id)

        target_id = id_to if (id_to and id_to != "0" and id_to != str(self.zalo.uid)) else (default_grid or uid_from)
        is_group = bool(default_grid) or (str(msg_obj.get("cmd")) in ("502", "521")) or any(
            str(g.get("id")) == str(target_id) for g in self.zalo.groups_cache
        )

        # Parse native Zalo mentionInfo if attached to the command message
        incoming_mentions = []
        raw_mi = msg_obj.get("mentions") or msg_obj.get("mentionInfo")
        if isinstance(raw_mi, str):
            try:
                raw_mi = json.loads(raw_mi)
            except Exception:
                raw_mi = []
        if isinstance(raw_mi, list):
            incoming_mentions = raw_mi
            if incoming_mentions:
                is_group = True

        parse_and_execute_inchat_command(
            platform="zalo",
            acc_uid=self.zalo.uid,
            target_id=target_id,
            is_group=is_group,
            raw_text=clean_c,
            prefix=self.prefix,
            incoming_mentions=incoming_mentions
        )

    def _ws_loop(self):
        while self.running:
            try:
                if not self.zalo.ws_url:
                    self.zalo.get_login_info()
                ws_url = self.zalo.ws_url
                if not ws_url:
                    time.sleep(10)
                    continue

                cookie_str = "; ".join(f"{k}={v}" for k, v in self.zalo.cookies.items())
                ws = websocket.create_connection(
                    ws_url,
                    header=[
                        f"User-Agent: {self.zalo.user_agent}",
                        "Origin: https://chat.zalo.me",
                        f"Cookie: {cookie_str}"
                    ],
                    timeout=20
                )
                while self.running:
                    raw_frame = ws.recv()
                    if not raw_frame:
                        break
                    if isinstance(raw_frame, bytes) and len(raw_frame) > 4:
                        try:
                            json_part = raw_frame[4:].decode("utf-8", errors="ignore")
                            js = json.loads(json_part)
                            enc_data = js.get("data")
                            if enc_data and self.zalo.secret_key:
                                dec = ZaloCrypto.decode_aes(self.zalo.secret_key, enc_data)
                                if dec:
                                    inner = json.loads(dec)
                                    self._walk_ws_payload(inner)
                        except Exception:
                            pass
                ws.close()
            except Exception:
                time.sleep(6)

    def _walk_ws_payload(self, obj):
        if isinstance(obj, dict):
            if "msgId" in obj and "content" in obj:
                self._process_msg_obj(obj)
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    self._walk_ws_payload(v)
        elif isinstance(obj, list):
            for item in obj:
                self._walk_ws_payload(item)

    def _poll_loop(self):
        while self.running:
            try:
                if not self.zalo.groups_cache:
                    self.zalo.get_groups()
                for grp in (self.zalo.groups_cache or [])[:15]:
                    if not self.running:
                        break
                    gid = grp.get("id")
                    if gid:
                        msgs = self.zalo.get_recent_group_messages(gid)
                        for m in msgs:
                            self._process_msg_obj(m, default_grid=gid)
                    time.sleep(0.5)
            except Exception:
                pass
            time.sleep(3.0)


class DiscordSelfBotListener:
    """
    Listens for self-issued commands on Discord using Gateway v9 WebSocket
    with cloaked browser properties + REST channel polling fallback.
    """
    def __init__(self, discord_bot, prefix="."):
        self.bot = discord_bot
        self.prefix = prefix or "."
        self.running = False
        self.seen_ids = deque(maxlen=600)
        self.start_ts = time.time()

    def start(self):
        if self.running:
            return
        self.running = True
        if HAS_WEBSOCKET:
            threading.Thread(target=self._gateway_loop, daemon=True).start()
        else:
            threading.Thread(target=self._rest_poll_loop, daemon=True).start()

    def stop(self):
        self.running = False

    def _handle_discord_msg(self, d):
        if not isinstance(d, dict):
            return
        msg_id = str(d.get("id") or "")
        if not msg_id or msg_id in self.seen_ids:
            return

        author = d.get("author") or {}
        author_id = str(author.get("id") or "")
        if author_id != str(self.bot.uid):
            return

        content = strip_invisible_chars(d.get("content") or "")
        if not content.startswith(self.prefix):
            return

        self.seen_ids.append(msg_id)
        channel_id = str(d.get("channel_id") or "")
        incoming_mentions = d.get("mentions") or []

        parse_and_execute_inchat_command(
            platform="discord",
            acc_uid=self.bot.uid,
            target_id=channel_id,
            is_group=True,
            raw_text=content,
            prefix=self.prefix,
            incoming_mentions=incoming_mentions
        )

    def _gateway_loop(self):
        while self.running:
            ws = None
            try:
                ws = websocket.create_connection("wss://gateway.discord.gg/?v=9&encoding=json", timeout=25)
                hello = json.loads(ws.recv())
                hb_interval = hello.get("d", {}).get("heartbeat_interval", 41250) / 1000.0

                ident = DISCORD_ANTIBAN.get_or_build_identity(
                    self.bot.uid or self.bot.token,
                    saved_super_b64=self.bot.super_props_b64,
                    saved_ua=self.bot.user_agent
                )
                identify_payload = {
                    "op": 2,
                    "d": {
                        "token": self.bot.token,
                        "capabilities": 16381,
                        "properties": {
                            "os": "Windows",
                            "browser": "Chrome",
                            "device": "",
                            "system_locale": "vi-VN",
                            "browser_user_agent": ident["ua"],
                            "browser_version": "131.0.0.0",
                            "os_version": "10",
                            "release_channel": "stable",
                            "client_build_number": 369842
                        },
                        "presence": {
                            "status": "online",
                            "since": 0,
                            "activities": [],
                            "afk": False
                        },
                        "compress": False
                    }
                }
                ws.send(json.dumps(identify_payload))

                last_hb = time.time()
                ws.settimeout(1.5)
                while self.running:
                    if time.time() - last_hb >= hb_interval:
                        ws.send(json.dumps({"op": 1, "d": None}))
                        last_hb = time.time()
                    try:
                        raw = ws.recv()
                        if raw:
                            pkt = json.loads(raw)
                            if pkt.get("t") == "MESSAGE_CREATE":
                                self._handle_discord_msg(pkt.get("d") or {})
                    except websocket.WebSocketTimeoutException:
                        continue
            except Exception:
                time.sleep(6)
            finally:
                if ws:
                    try:
                        ws.close()
                    except Exception:
                        pass

    def _rest_poll_loop(self):
        while self.running:
            try:
                for ch in (self.bot.channels_cache or [])[:10]:
                    if not self.running:
                        break
                    cid = ch.get("id")
                    if cid:
                        r = self.bot.session.get(
                            f"{self.bot.BASE_API}/channels/{cid}/messages?limit=5",
                            headers=self.bot._headers(cid),
                            timeout=8
                        )
                        if r.status_code == 200:
                            for m in r.json():
                                self._handle_discord_msg(m)
                    time.sleep(0.8)
            except Exception:
                pass
            time.sleep(3.5)


# ==============================================================================
#  SECTION 10: ACCOUNT BOOTSTRAPPER & SESSION RESTORATION
# ==============================================================================

def restore_saved_accounts():
    """Restores saved Zalo & Discord accounts from SQLite on server startup."""
    global STEALTH_LOG_MASK_ENABLED
    mask_cfg = get_setting("stealth_mask", "1")
    STEALTH_LOG_MASK_ENABLED = (str(mask_cfg) != "0")

    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("SELECT * FROM zalo_accounts")
        z_rows = cur.fetchall()

        cur.execute("SELECT * FROM discord_accounts")
        d_rows = cur.fetchall()
        conn.close()

    for r in z_rows:
        try:
            uid = str(r["uid"])
            c_dict = json.loads(r["cookie_json"] or "{}")
            z_bot = Zalo(
                uid=uid,
                name=r["name"],
                imei=r["imei"],
                cookies_dict=c_dict,
                user_agent=r["user_agent"],
                proxy=r["proxy"]
            )
            ZALO_BOTS[uid] = z_bot

            def _init_z(bot_inst, sb_on, pref):
                ok, _ = bot_inst.get_login_info()
                if ok:
                    bot_inst.get_groups()
                    bot_inst.get_friends()
                    if sb_on:
                        listener = ZaloSelfBotListener(bot_inst, prefix=pref)
                        ZALO_LISTENERS[bot_inst.uid] = listener
                        listener.start()

            threading.Thread(
                target=_init_z,
                args=(z_bot, bool(r["selfbot_enabled"]), r["command_prefix"] or "."),
                daemon=True
            ).start()
        except Exception as e:
            logger.warning(f"Restore Zalo account error: {e}")

    for r in d_rows:
        try:
            uid = str(r["uid"])
            d_bot = DiscordBot(
                uid=uid,
                name=r["name"],
                username=r["username"],
                token=r["token"],
                proxy=r["proxy"],
                super_props_b64=r["super_props_b64"] if "super_props_b64" in r.keys() else "",
                fingerprint=r["fingerprint"] if "fingerprint" in r.keys() else "",
                user_agent=r["user_agent"] if "user_agent" in r.keys() else ""
            )
            DISCORD_BOTS[uid] = d_bot

            def _init_d(bot_inst, sb_on, pref):
                ok, _ = bot_inst.check_token()
                if ok:
                    bot_inst.get_targets()
                    if sb_on:
                        listener = DiscordSelfBotListener(bot_inst, prefix=pref)
                        DISCORD_LISTENERS[bot_inst.uid] = listener
                        listener.start()

            threading.Thread(
                target=_init_d,
                args=(d_bot, bool(r["selfbot_enabled"]), r["command_prefix"] or "."),
                daemon=True
            ).start()
        except Exception as e:
            logger.warning(f"Restore Discord account error: {e}")


# ==============================================================================
#  SECTION 11: STREAMLINED ANTI-ZOOM UI & CYBER-GLASS DESIGN (v8.0 ULTRA)
# ==============================================================================

CSS_PRO = """
:root {
    --bg-main: #060913;
    --bg-card: rgba(14, 21, 38, 0.88);
    --bg-input: rgba(8, 13, 26, 0.95);
    --border-subtle: rgba(99, 125, 175, 0.22);
    --border-glow: rgba(56, 189, 248, 0.55);
    --primary: #38bdf8;
    --primary-dark: #0284c7;
    --accent: #818cf8;
    --discord: #5865F2;
    --zalo: #0068ff;
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
    --text-main: #f1f5f9;
    --text-muted: #94a3b8;
    --radius-lg: 14px;
    --radius-md: 10px;
    --radius-sm: 8px;
}

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    -webkit-tap-highlight-color: transparent;
    /* Prevents double-tap or accidental tap zoom on mobile browsers */
    touch-action: manipulation;
}

html, body {
    width: 100%;
    min-height: 100vh;
    background: radial-gradient(circle at 15% 15%, #0f1b33 0%, #060913 60%, #03050a 100%);
    color: var(--text-main);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.45;
    -webkit-text-size-adjust: 100%;
    -moz-text-size-adjust: 100%;
    text-size-adjust: 100%;
    overflow-x: hidden;
}

/* CRITICAL FIX: Prevent iOS Safari & Android Chrome from auto-zooming on input focus */
input, select, textarea {
    font-size: 16px !important;
    font-family: inherit;
    color: var(--text-main);
    background: var(--bg-input);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm);
    padding: 9px 12px;
    width: 100%;
    outline: none;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
    touch-action: manipulation;
}

input:focus, select:focus, textarea:focus {
    border-color: var(--primary);
    box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.18);
}

input[type="checkbox"], input[type="radio"] {
    width: 18px !important;
    height: 18px !important;
    accent-color: var(--primary);
    cursor: pointer;
    flex-shrink: 0;
}

/* Compact, Crisp, High-Contrast Button System */
.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 8px 13px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.1px;
    border-radius: var(--radius-sm);
    border: 1px solid rgba(255, 255, 255, 0.1);
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
    transition: transform 0.1s ease, filter 0.15s ease, border-color 0.15s ease;
    touch-action: manipulation;
    text-decoration: none;
    color: #fff;
}

.btn:active {
    transform: scale(0.97);
}

.btn-sm {
    padding: 5px 10px;
    font-size: 12px;
    border-radius: 7px;
}

.btn-xs {
    padding: 4px 8px;
    font-size: 11.5px;
    border-radius: 6px;
}

.btn-primary {
    background: linear-gradient(135deg, #0ea5e9, #2563eb);
    border-color: rgba(56, 189, 248, 0.4);
    box-shadow: 0 3px 10px rgba(14, 165, 233, 0.25);
}

.btn-discord {
    background: linear-gradient(135deg, #5865F2, #4752C4);
    border-color: rgba(129, 140, 248, 0.4);
    box-shadow: 0 3px 10px rgba(88, 101, 242, 0.25);
}

.btn-success {
    background: linear-gradient(135deg, #10b981, #059669);
    border-color: rgba(16, 185, 129, 0.4);
    box-shadow: 0 3px 10px rgba(16, 185, 129, 0.25);
}

.btn-warning {
    background: linear-gradient(135deg, #f59e0b, #d97706);
    color: #fff;
}

.btn-danger {
    background: linear-gradient(135deg, #ef4444, #dc2626);
    border-color: rgba(239, 68, 68, 0.4);
}

.btn-ghost {
    background: rgba(30, 41, 59, 0.75);
    border: 1px solid var(--border-subtle);
    color: #e2e8f0;
}

.btn-ghost:hover {
    border-color: var(--primary);
    color: #fff;
}

.btn-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
}

/* Layout Containers */
.app-shell {
    max-width: 1440px;
    margin: 0 auto;
    padding: 12px 14px 36px;
}

.topbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 11px 16px;
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    margin-bottom: 12px;
    backdrop-filter: blur(12px);
}

.brand-wrap {
    display: flex;
    align-items: center;
    gap: 10px;
}

.brand-logo {
    width: 36px;
    height: 36px;
    border-radius: 10px;
    background: linear-gradient(135deg, #38bdf8, #6366f1);
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
    font-size: 16px;
    color: #fff;
    box-shadow: 0 0 14px rgba(56, 189, 248, 0.45);
}

.brand-title {
    font-size: 16px;
    font-weight: 800;
    letter-spacing: 0.3px;
    background: linear-gradient(90deg, #38bdf8, #a5b4fc, #f472b6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.brand-sub {
    font-size: 11.5px;
    color: var(--text-muted);
}

.stats-strip {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
    gap: 9px;
    margin-bottom: 12px;
}

.stat-pill {
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 9px 12px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.stat-label {
    font-size: 11.5px;
    color: var(--text-muted);
    font-weight: 500;
}

.stat-val {
    font-size: 16px;
    font-weight: 800;
    color: var(--primary);
}

/* Segmented Navigation Tabs */
.nav-tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 12px;
    background: rgba(10, 15, 29, 0.85);
    padding: 6px;
    border-radius: var(--radius-md);
    border: 1px solid var(--border-subtle);
}

.nav-tab {
    flex: 1 1 auto;
    min-width: 125px;
    padding: 8px 12px;
    border-radius: var(--radius-sm);
    border: 1px solid transparent;
    background: transparent;
    color: var(--text-muted);
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    text-align: center;
    transition: all 0.15s ease;
}

.nav-tab.active {
    background: linear-gradient(135deg, rgba(14, 165, 233, 0.22), rgba(99, 102, 241, 0.22));
    color: #fff;
    border-color: var(--border-glow);
}

.tab-pane {
    display: none;
}

.tab-pane.active {
    display: block;
}

/* Grid & Cards */
.grid-2 {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 12px;
}

.grid-3 {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 12px;
}

.card {
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    padding: 14px;
    margin-bottom: 12px;
}

.card-header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding-bottom: 10px;
    margin-bottom: 12px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.14);
}

.card-title {
    font-size: 14.5px;
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 7px;
}

.badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
}

.badge-zalo { background: rgba(0, 104, 255, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.35); }
.badge-discord { background: rgba(88, 101, 242, 0.2); color: #a5b4fc; border: 1px solid rgba(129, 140, 248, 0.35); }
.badge-online { background: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.35); }
.badge-stealth { background: rgba(245, 158, 11, 0.18); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.35); }

.form-group {
    margin-bottom: 10px;
}

.form-label {
    display: block;
    font-size: 12px;
    font-weight: 600;
    color: #cbd5e1;
    margin-bottom: 4px;
}

.scroll-box {
    max-height: 250px;
    overflow-y: auto;
    background: rgba(6, 10, 20, 0.8);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm);
    padding: 6px;
}

.check-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 7px 9px;
    border-radius: 7px;
    cursor: pointer;
    transition: background 0.12s;
}

.check-item:hover {
    background: rgba(56, 189, 248, 0.08);
}

.check-item-left {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    flex: 1;
}

.check-item-name {
    font-size: 13px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.acc-item {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 10px 12px;
    background: rgba(9, 14, 28, 0.85);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    margin-bottom: 8px;
}

.log-terminal {
    background: #04070f;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 10px;
    height: 300px;
    overflow-y: auto;
    font-family: 'JetBrains Mono', Consolas, monospace;
    font-size: 12px;
}

.log-line {
    padding: 3px 0;
    border-bottom: 1px dashed rgba(148, 163, 184, 0.08);
    word-break: break-word;
}

.reg-box {
    background: rgba(88, 101, 242, 0.09);
    border: 1px dashed rgba(129, 140, 248, 0.45);
    border-radius: var(--radius-md);
    padding: 11px;
    margin-bottom: 11px;
}

@media (max-width: 640px) {
    .app-shell { padding: 8px 8px 28px; }
    .topbar { padding: 10px 12px; }
    .btn { padding: 7px 10px; font-size: 12.5px; }
    .grid-2, .grid-3 { grid-template-columns: 1fr; }
}
"""

HTML_GATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, minimum-scale=1.0, user-scalable=no">
    <title>ALB FORGE v8.0 ULTRA - Cổng Bảo Mật</title>
    <style>{{ css_pro | safe }}</style>
</head>
<body style="display:flex;align-items:center;justify-content:center;padding:16px;">
    <div class="card" style="max-width:410px;width:100%;padding:22px;">
        <div class="brand-wrap" style="margin-bottom:14px;">
            <div class="brand-logo">⚡</div>
            <div>
                <div class="brand-title">ALB FORGE v8.0 ULTRA</div>
                <div class="brand-sub">Hệ Thống Điều Khiển Zalo & Discord Chuyên Sâu</div>
            </div>
        </div>
        {% if err %}
        <div style="background:rgba(239,68,68,0.16);border:1px solid #ef4444;color:#fca5a5;padding:9px 12px;border-radius:8px;margin-bottom:12px;font-size:12.5px;">
            ⚠️ {{ err }}
        </div>
        {% endif %}
        <form method="POST" action="/gate">
            <div class="form-group">
                <label class="form-label">Mã Khóa Truy Cập (Mặc định: alb2026)</label>
                <input type="password" name="gate_key" value="alb2026" placeholder="Nhập Gate Key..." required>
            </div>
            <button type="submit" class="btn btn-primary" style="width:100%;margin-top:4px;padding:10px;">
                🔓 Mở Bảng Điều Khiển Ngay
            </button>
        </form>
    </div>
</body>
</html>
"""

HTML_INDEX = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, minimum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>ALB FORGE v8.0 ULTRA — Zalo & Discord Stealth Center</title>
    <style>{{ css_pro | safe }}</style>
</head>
<body>
<div class="app-shell">
    <!-- TOP BAR -->
    <header class="topbar">
        <div class="brand-wrap">
            <div class="brand-logo">⚡</div>
            <div>
                <div class="brand-title">ALB FORGE v8.0 ULTRA</div>
                <div class="brand-sub">Dual Stealth Anti-Ban • Auto-Tag Chuẩn Khung Chat • Unboxed Discord</div>
            </div>
        </div>
        <div class="btn-row">
            <button type="button" class="btn btn-sm btn-ghost" id="btnStealthMask" onclick="toggleStealthMask()">
                🕵️ Ẩn Log Acc: <span id="lblStealthState">BẬT</span>
            </button>
            <button type="button" class="btn btn-sm btn-ghost" onclick="refreshAllState()">
                🔄 Làm mới
            </button>
            <button type="button" class="btn btn-sm btn-danger" onclick="stopAllTasksGlobal()">
                🛑 Dừng Tất Cả
            </button>
        </div>
    </header>

    <!-- TELEMETRY STRIP -->
    <div class="stats-strip">
        <div class="stat-pill">
            <div>
                <div class="stat-label">Acc Zalo Online</div>
                <div class="stat-val" id="stZaloCount">0</div>
            </div>
            <span class="badge badge-zalo">Zalo Matrix v8</span>
        </div>
        <div class="stat-pill">
            <div>
                <div class="stat-label">Acc Discord Online</div>
                <div class="stat-val" id="stDiscordCount">0</div>
            </div>
            <span class="badge badge-discord">Phantom Route v8</span>
        </div>
        <div class="stat-pill">
            <div>
                <div class="stat-label">Chiến Dịch Đang Chạy</div>
                <div class="stat-val" id="stActiveTasks" style="color:#10b981;">0</div>
            </div>
            <span class="badge badge-online">Realtime</span>
        </div>
        <div class="stat-pill">
            <div>
                <div class="stat-label">Chế Độ Bảo Mật Log</div>
                <div class="stat-val" id="stStealthBadge" style="color:#fbbf24;font-size:13.5px;">ĐANG ẨN LOG ACC</div>
            </div>
            <span class="badge badge-stealth">Stealth Shield</span>
        </div>
    </div>

    <!-- COMPACT NAVIGATION TABS (Đã xoá hoàn toàn phần tạo acc user rườm rà) -->
    <nav class="nav-tabs">
        <button type="button" class="nav-tab active" onclick="switchTab('tab-campaign', this)">🚀 Chiến Dịch & Auto-Tag</button>
        <button type="button" class="nav-tab" onclick="switchTab('tab-accounts', this)">🔐 Quản Lý Acc & Lấy Token Reg</button>
        <button type="button" class="nav-tab" onclick="switchTab('tab-antiban', this)">🛡️ 2 Hệ Thống Anti-Ban Riêng</button>
        <button type="button" class="nav-tab" onclick="switchTab('tab-files', this)">📂 Kho Kịch Bản (.TXT)</button>
    </nav>

    <!-- TAB 1: CAMPAIGN & AUTO-TAG -->
    <section id="tab-campaign" class="tab-pane active">
        <div class="grid-2">
            <!-- LEFT: TARGET & TAG SELECTOR -->
            <div class="card">
                <div class="card-header">
                    <div class="card-title">🎯 1. Chọn Tài Khoản & Khung Chat Mục Tiêu</div>
                    <div class="btn-row">
                        <button type="button" class="btn btn-xs btn-ghost" onclick="loadTargetsForSelectedAcc(true)">🔄 Quét Nhóm/Kênh</button>
                        <button type="button" class="btn btn-xs btn-ghost" onclick="selectAllTargets(true)">☑️ Chọn hết</button>
                        <button type="button" class="btn btn-xs btn-ghost" onclick="selectAllTargets(false)">⬜ Bỏ chọn</button>
                    </div>
                </div>

                <div class="grid-2" style="gap:8px;margin-bottom:10px;">
                    <div>
                        <label class="form-label">Nền Tảng</label>
                        <select id="selPlatform" onchange="onPlatformChange()">
                            <option value="zalo">🔵 Zalo (Auto-Tag Chuẩn Khung Chat)</option>
                            <option value="discord">🟣 Discord (Chữ Bung Full Không Đóng Khung)</option>
                        </select>
                    </div>
                    <div>
                        <label class="form-label">Tài Khoản Thực Thi</label>
                        <select id="selAccount" onchange="loadTargetsForSelectedAcc(false)">
                            <option value="">-- Chọn tài khoản --</option>
                        </select>
                    </div>
                </div>

                <div class="form-group">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                        <label class="form-label" style="margin:0;">Danh Sách Nhóm / Kênh (Tích chọn sẽ tự tải thành viên để Tag)</label>
                        <input type="text" id="inpFilterTarget" placeholder="🔍 Lọc nhanh nhóm/kênh..." oninput="filterTargetList()" style="width:170px;padding:4px 8px;">
                    </div>
                    <div class="scroll-box" id="targetListBox">
                        <div style="padding:12px;color:var(--text-muted);text-align:center;">Hãy chọn tài khoản để tải danh sách khung chat...</div>
                    </div>
                </div>

                <!-- UPGRADED SMART @TAG PANEL -->
                <div class="card" style="background:rgba(8,14,28,0.92);margin-bottom:0;padding:11px;">
                    <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:6px;margin-bottom:8px;">
                        <div style="font-weight:700;font-size:13px;color:#38bdf8;">🏷️ Cấu Hình Tự Động @Tag Chuẩn Theo Khung Chat</div>
                        <div class="btn-row">
                            <button type="button" class="btn btn-xs btn-primary" onclick="loadMembersForCheckedBoxes()">🔄 Tải TV Khung Chat</button>
                            <button type="button" class="btn btn-xs btn-ghost" onclick="selectAllMembers(true)">Tag Hết</button>
                            <button type="button" class="btn btn-xs btn-ghost" onclick="selectAllMembers(false)">Xóa Tag</button>
                        </div>
                    </div>

                    <div class="form-group" style="margin-bottom:8px;">
                        <label class="check-item" style="background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.3);">
                            <div class="check-item-left">
                                <input type="checkbox" id="chkAutoTagBox">
                                <span style="font-size:12.5px;font-weight:600;color:#34d399;">
                                    🔄 Tự động lấy & xoay vòng Tag thành viên chuẩn theo từng khung chat
                                </span>
                            </div>
                        </label>
                    </div>

                    <div class="form-group" style="margin-bottom:8px;">
                        <label class="form-label">Tag nhanh bằng tên hoặc UID (Cách nhau dấu phẩy, VD: @Nguyễn Văn A, @all)</label>
                        <input type="text" id="inpRawTagText" placeholder="Nhập @Tên thành viên trong khung chat hoặc @all...">
                    </div>

                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                        <span class="form-label" style="margin:0;">Hoặc tích chọn thành viên trong khung chat:</span>
                        <input type="text" id="inpFilterMember" placeholder="🔍 Tìm tên TV..." oninput="filterMemberList()" style="width:145px;padding:3px 8px;">
                    </div>
                    <div class="scroll-box" id="memberListBox" style="max-height:165px;">
                        <div style="padding:10px;color:var(--text-muted);text-align:center;font-size:12px;">
                            Khi bạn tích chọn Nhóm Zalo / Kênh Discord ở trên, danh sách thành viên của khung chat đó sẽ tự động hiện tại đây!
                        </div>
                    </div>
                </div>
            </div>

            <!-- RIGHT: CONTENT, TYPOGRAPHY & LAUNCH -->
            <div class="card">
                <div class="card-header">
                    <div class="card-title">⚡ 2. Nội Dung, Kiểu Chữ Bung Full & Khởi Chạy</div>
                    <span class="badge badge-online">Chống Đóng Khung Discord</span>
                </div>

                <div class="grid-2" style="gap:8px;margin-bottom:10px;">
                    <div>
                        <label class="form-label">Chế Độ Gửi</label>
                        <select id="selTaskMode">
                            <option value="nhay">🔥 Nhây liên tục từng dòng + @Tag</option>
                            <option value="treo">📌 Treo tin nhắn định kỳ</option>
                            <option value="random">🎲 Ngẫu nhiên câu trong kịch bản</option>
                            <option value="poll">📊 Tạo thông điệp Bình chọn</option>
                        </select>
                    </div>
                    <div>
                        <label class="form-label">Tốc Độ Cơ Bản (Giây / Tin)</label>
                        <input type="number" id="inpTaskDelay" value="1.8" min="0.4" step="0.1">
                    </div>
                </div>

                <div class="grid-2" style="gap:8px;margin-bottom:10px;">
                    <div>
                        <label class="form-label">Chọn File Kịch Bản (.TXT)</label>
                        <select id="selTaskFile">
                            <option value="">-- Dùng văn bản nhập tay bên dưới --</option>
                        </select>
                    </div>
                    <div>
                        <label class="form-label">Cỡ Chữ (Discord bung # chữ đại, không đóng khung)</label>
                        <select id="selFontSize">
                            <option value="big">🔥 Chữ Đại Bung Toàn Màn Hình (# Heading)</option>
                            <option value="normal">✨ Chữ Thường Rõ Nét</option>
                        </select>
                    </div>
                </div>

                <div class="form-group">
                    <label class="form-label">Nội Dung Trực Tiếp (Mỗi dòng 1 tin — có thể gõ kèm @Tên ở cuối dòng)</label>
                    <textarea id="txtRawContent" rows="4" placeholder="Nhập nội dung gửi... (Nếu chọn file .TXT ở trên thì hệ thống ưu tiên đọc file .TXT)"></textarea>
                </div>

                <div class="grid-2" style="gap:8px;margin-bottom:12px;">
                    <label class="check-item" style="border:1px solid var(--border-subtle);">
                        <div class="check-item-left">
                            <input type="checkbox" id="chkBoldText" checked>
                            <span style="font-size:12.5px;">Chữ In Đậm (**Bold** / RichText)</span>
                        </div>
                    </label>
                    <label class="check-item" style="border:1px solid var(--border-subtle);">
                        <div class="check-item-left">
                            <input type="checkbox" id="chkRandomIcon" checked>
                            <span style="font-size:12.5px;">Biểu tượng cảm xúc chống trùng lặp</span>
                        </div>
                    </label>
                </div>

                <div class="btn-row" style="margin-bottom:14px;">
                    <button type="button" class="btn btn-success" style="flex:2;padding:11px;" onclick="startCampaignNow()">
                        🚀 KHỞI CHẠY CHIẾN DỊCH NGAY
                    </button>
                    <button type="button" class="btn btn-danger" style="flex:1;padding:11px;" onclick="stopAllTasksGlobal()">
                        🛑 DỪNG TẤT CẢ
                    </button>
                </div>

                <!-- ACTIVE TASKS MONITOR -->
                <div class="card-header" style="margin-bottom:8px;padding-bottom:6px;">
                    <div class="card-title" style="font-size:13.5px;">📡 Tiến Trình Đang Chạy</div>
                    <span class="badge badge-zalo" id="lblRunningBadge">0 Task</span>
                </div>
                <div class="scroll-box" id="activeTasksBox" style="max-height:215px;">
                    <div style="padding:12px;color:var(--text-muted);text-align:center;">Chưa có chiến dịch nào đang chạy.</div>
                </div>
            </div>
        </div>
    </section>

    <!-- TAB 2: ACCOUNTS & DISCORD REG TOKEN EXTRACTOR -->
    <section id="tab-accounts" class="tab-pane">
        <div class="grid-2">
            <!-- ZALO ACCOUNT MANAGER -->
            <div class="card">
                <div class="card-header">
                    <div class="card-title">🔵 Kết Nối Tài Khoản Zalo (Zalo Matrix Stealth v8.0)</div>
                    <span class="badge badge-zalo">Hỗ trợ Lệnh .nhay .tag</span>
                </div>
                <div class="grid-2" style="gap:8px;">
                    <div class="form-group">
                        <label class="form-label">Tên Gợi Nhớ</label>
                        <input type="text" id="zAccName" placeholder="VD: Zalo Chính">
                    </div>
                    <div class="form-group">
                        <label class="form-label">IMEI Zalo Web</label>
                        <input type="text" id="zAccImei" placeholder="Dán mã IMEI (z_uuid)...">
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Cookie Zalo (JSON hoặc chuỗi Cookie)</label>
                    <textarea id="zAccCookie" rows="3" placeholder='Dán JSON Cookie hoặc zpw_sek=... vào đây'></textarea>
                </div>
                <div class="grid-2" style="gap:8px;margin-bottom:10px;">
                    <div>
                        <label class="form-label">Proxy Riêng (Tùy chọn)</label>
                        <input type="text" id="zAccProxy" placeholder="http://user:pass@ip:port">
                    </div>
                    <div>
                        <label class="form-label">Prefix Lệnh Trong Chat</label>
                        <input type="text" id="zAccPrefix" value=".">
                    </div>
                </div>
                <button type="button" class="btn btn-primary" style="width:100%;margin-bottom:12px;" onclick="addZaloAccount()">
                    ➕ Thêm & Kết Nối Tài Khoản Zalo
                </button>

                <div class="form-label">Danh Sách Tài Khoản Zalo (Đã Ẩn Bảo Mật UID/Cookie)</div>
                <div id="zaloAccountsList"></div>
            </div>

            <!-- DISCORD ACCOUNT MANAGER + BUILT-IN REG / SAFE TOKEN EXTRACTOR -->
            <div class="card">
                <div class="card-header">
                    <div class="card-title">🟣 Kết Nối Discord & Lấy Token Bằng Reg (Chống Die)</div>
                    <button type="button" class="btn btn-xs btn-discord" onclick="toggleRegPanel()">
                        ⚡ Công Cụ Lấy Token Reg / cURL
                    </button>
                </div>

                <!-- DISCORD REG / SAFE TOKEN EXTRACTOR PANEL -->
                <div id="discordRegPanel" class="reg-box">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <div style="font-weight:700;font-size:13px;color:#a5b4fc;">
                            🛡️ Lấy Token Discord Bằng Reg / cURL & Ủ Ấm X-Super-Properties (Chống Die)
                        </div>
                        <div class="btn-row">
                            <button type="button" class="btn btn-xs btn-discord" id="btnRegModeExtract" onclick="setRegMode('extract')">1. Trích từ Reg/cURL</button>
                            <button type="button" class="btn btn-xs btn-ghost" id="btnRegModeLogin" onclick="setRegMode('login')">2. Đăng nhập Reg</button>
                        </div>
                    </div>

                    <!-- Mode 1: Extract from Reg line / cURL / Network Header -->
                    <div id="regBoxExtract">
                        <label class="form-label">Dán dòng Reg (email:pass:token), lệnh cURL (F12 Network), hoặc JSON vào đây:</label>
                        <textarea id="regRawInput" rows="2" placeholder="Dán email:pass:token hoặc cURL copy từ F12 -> Hệ thống tự bóc Token + Fingerprint chuẩn..."></textarea>
                    </div>

                    <!-- Mode 2: Direct Reg / Account Login with Fingerprint Warming -->
                    <div id="regBoxLogin" style="display:none;">
                        <div class="grid-3" style="gap:6px;margin-bottom:6px;">
                            <div>
                                <label class="form-label">Email / SĐT Discord</label>
                                <input type="text" id="regEmail" placeholder="Email hoặc SĐT">
                            </div>
                            <div>
                                <label class="form-label">Mật Khẩu</label>
                                <input type="password" id="regPassword" placeholder="Mật khẩu">
                            </div>
                            <div>
                                <label class="form-label">Mã 2FA (Nếu có)</label>
                                <input type="text" id="regMfaCode" placeholder="6 số 2FA">
                            </div>
                        </div>
                    </div>

                    <div class="btn-row" style="margin-top:8px;">
                        <button type="button" class="btn btn-sm btn-discord" onclick="runDiscordRegExtractor(false)">
                            🔍 Lấy Token & Ủ Ấm Phiên
                        </button>
                        <button type="button" class="btn btn-sm btn-success" onclick="runDiscordRegExtractor(true)">
                            ⚡ Lấy Token & Lưu Vào Hệ Thống Luôn
                        </button>
                    </div>
                    <div id="regResultMsg" style="margin-top:6px;font-size:12px;color:#34d399;display:none;"></div>
                </div>

                <!-- Standard Discord Add Form -->
                <div class="grid-2" style="gap:8px;">
                    <div class="form-group">
                        <label class="form-label">Tên Gợi Nhớ</label>
                        <input type="text" id="dAccName" placeholder="VD: Discord Chính">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Prefix Lệnh Trong Chat</label>
                        <input type="text" id="dAccPrefix" value=".">
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Token Discord (Được mã hóa & ẩn hoàn toàn khỏi Log)</label>
                    <input type="password" id="dAccToken" placeholder="Dán Token Discord hoặc dùng công cụ Reg ở trên...">
                </div>
                <div class="form-group">
                    <label class="form-label">Proxy Riêng (Tùy chọn)</label>
                    <input type="text" id="dAccProxy" placeholder="http://user:pass@ip:port">
                </div>
                <input type="hidden" id="dAccSuperProps" value="">
                <input type="hidden" id="dAccFingerprint" value="">
                <input type="hidden" id="dAccUA" value="">

                <button type="button" class="btn btn-discord" style="width:100%;margin-bottom:12px;" onclick="addDiscordAccount()">
                    ➕ Thêm & Kết Nối Tài Khoản Discord (Ẩn Đường Chuyển)
                </button>

                <div class="form-label">Danh Sách Tài Khoản Discord (Đã Ẩn Log Acc & Token)</div>
                <div id="discordAccountsList"></div>
            </div>
        </div>
    </section>

    <!-- TAB 3: DUAL SPECIALIZED ANTI-BAN MONITOR & LOGS -->
    <section id="tab-antiban" class="tab-pane">
        <div class="grid-2">
            <div class="card">
                <div class="card-header">
                    <div class="card-title">🔵 Anti-Ban Độc Quyền #1: ZALO MATRIX STEALTH v8.0</div>
                    <span class="badge badge-zalo">Chuyên biệt cho Zalo</span>
                </div>
                <div style="font-size:13px;color:#cbd5e1;display:grid;gap:6px;margin-bottom:10px;">
                    <div>• <b>Monotonic 13-Digit ClientId:</b> Chống trùng lặp timestamp tuyệt đối khi gửi đa luồng.</div>
                    <div>• <b>IMEI-Coherent Chrome Fingerprint:</b> Đồng bộ hóa <code>Sec-Ch-Ua</code>, <code>Origin</code> và <code>zpw_ver=645</code> theo mã băm IMEI.</div>
                    <div>• <b>Gaussian + Poisson Micro-Jitter:</b> Nhịp gõ phím sinh học kết hợp nghỉ giải lao tự động mỗi 18-26 tin.</div>
                    <div>• <b>Zero-Shift Cryptographic Tail:</b> Chèn mã tàng hình sau cùng giúp tọa độ UTF-16 của <code>@Tag</code> chính xác 100%.</div>
                </div>
                <div id="zaloAntibanCards" class="scroll-box" style="max-height:190px;"></div>
            </div>

            <div class="card">
                <div class="card-header">
                    <div class="card-title">🟣 Anti-Ban Độc Quyền #2: DISCORD PHANTOM ROUTE v8.0</div>
                    <span class="badge badge-discord">Ẩn Đường Chuyển Discord</span>
                </div>
                <div style="font-size:13px;color:#cbd5e1;display:grid;gap:6px;margin-bottom:10px;">
                    <div>• <b>Ẩn Đường Chuyển (Route & Telemetry Cloaking):</b> Tự động đóng gói <code>X-Super-Properties</code> Base64, <code>X-Discord-Locale: vi</code>, <code>X-Discord-Timezone</code> và <code>Referer</code> động theo từng kênh.</div>
                    <div>• <b>64-Bit Discord Epoch Snowflake Nonce:</b> Tạo mã <code>nonce</code> chuẩn kiến trúc dịch bit của Discord Client chính thức.</div>
                    <div>• <b>Mô Phỏng Đang Soạn Tin (<code>/typing</code>):</b> Giả lập hành vi người thật gõ phím kèm bộ đệm tránh Rate-Limit 429.</div>
                    <div>• <b>Bảo Mật Log Acc Tuyệt Đối:</b> Tự động che giấu Token, UID và thông tin nhạy cảm trên giao diện & nhật ký.</div>
                </div>
                <div id="discordAntibanCards" class="scroll-box" style="max-height:190px;"></div>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <div class="card-title">🕵️ Nhật Ký Hệ Thống (Đã Bật Chế Độ Ẩn Log Acc & Token)</div>
                <button type="button" class="btn btn-xs btn-ghost" onclick="refreshAllState()">🔄 Cập nhật Log</button>
            </div>
            <div class="log-terminal" id="sysLogTerminal"></div>
        </div>
    </section>

    <!-- TAB 4: TXT SCRIPT MANAGER -->
    <section id="tab-files" class="tab-pane">
        <div class="grid-2">
            <div class="card">
                <div class="card-header">
                    <div class="card-title">📝 Tạo / Chỉnh Sửa File Kịch Bản (.TXT)</div>
                </div>
                <div class="form-group">
                    <label class="form-label">Tên File (VD: nhay_vip.txt)</label>
                    <input type="text" id="inpTxtFilename" placeholder="nhay_vip.txt">
                </div>
                <div class="form-group">
                    <label class="form-label">Nội Dung Kịch Bản (Mỗi dòng 1 câu)</label>
                    <textarea id="inpTxtBody" rows="8" placeholder="Nhập từng câu trên mỗi dòng..."></textarea>
                </div>
                <button type="button" class="btn btn-primary" style="width:100%;" onclick="saveTxtFile()">
                    💾 Lưu File Kịch Bản
                </button>
            </div>

            <div class="card">
                <div class="card-header">
                    <div class="card-title">📂 Danh Sách File Kịch Bản Hiện Có</div>
                </div>
                <div id="txtFilesListBox" class="scroll-box" style="max-height:320px;"></div>
            </div>
        </div>
    </section>
</div>
<script>
// Prevent iOS Safari pinch/double-tap auto-zoom while preserving smooth scroll
document.addEventListener('gesturestart', function(e) { e.preventDefault(); }, { passive: false });
let _lastTouchEnd = 0;
document.addEventListener('touchend', function(e) {
    const now = Date.now();
    if (now - _lastTouchEnd <= 280) {
        e.preventDefault();
    }
    _lastTouchEnd = now;
}, { passive: false });

let GLOBAL_STATE = {
    zalo_accounts: [],
    discord_accounts: [],
    tasks: [],
    txt_files: [],
    stealth_mask: true
};
let CURRENT_REG_MODE = 'extract';
let LAST_ACC_SIGNATURE = '';
let LAST_TXT_SIGNATURE = '';

function switchTab(tabId, btnEl) {
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-tab').forEach(b => b.classList.remove('active'));
    const pane = document.getElementById(tabId);
    if (pane) pane.classList.add('active');
    if (btnEl) btnEl.classList.add('active');
}

function setRegMode(mode) {
    CURRENT_REG_MODE = mode;
    document.getElementById('regBoxExtract').style.display = (mode === 'extract') ? 'block' : 'none';
    document.getElementById('regBoxLogin').style.display = (mode === 'login') ? 'block' : 'none';
    document.getElementById('btnRegModeExtract').className = (mode === 'extract') ? 'btn btn-xs btn-discord' : 'btn btn-xs btn-ghost';
    document.getElementById('btnRegModeLogin').className = (mode === 'login') ? 'btn btn-xs btn-discord' : 'btn btn-xs btn-ghost';
}

function toggleRegPanel() {
    const p = document.getElementById('discordRegPanel');
    p.style.display = (p.style.display === 'none') ? 'block' : 'none';
}

async function toggleStealthMask() {
    try {
        const r = await fetch('/api/toggle_stealth_mask', { method: 'POST' });
        const js = await r.json();
        if (js.ok) {
            await refreshAllState();
        }
    } catch (e) {}
}

async function runDiscordRegExtractor(autoSave) {
    const msgBox = document.getElementById('regResultMsg');
    msgBox.style.display = 'block';
    msgBox.style.color = '#38bdf8';
    msgBox.textContent = '⏳ Đang trích xuất & ủ ấm phiên Token với X-Super-Properties chống die...';

    const payload = {
        mode: CURRENT_REG_MODE,
        raw_input: document.getElementById('regRawInput').value,
        email: document.getElementById('regEmail').value,
        password: document.getElementById('regPassword').value,
        mfa_code: document.getElementById('regMfaCode').value,
        proxy: document.getElementById('dAccProxy').value,
        auto_save: autoSave,
        prefix: document.getElementById('dAccPrefix').value || '.'
    };

    try {
        const r = await fetch('/api/discord_reg_token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const js = await r.json();
        if (js.ok) {
            document.getElementById('dAccToken').value = js.token || '';
            document.getElementById('dAccName').value = js.name || '';
            document.getElementById('dAccSuperProps').value = js.super_props_b64 || '';
            document.getElementById('dAccFingerprint').value = js.fingerprint || '';
            document.getElementById('dAccUA').value = js.ua || '';
            msgBox.style.color = '#34d399';
            msgBox.textContent = '✅ ' + js.msg;
            if (autoSave) {
                LAST_ACC_SIGNATURE = '';
                await refreshAllState();
            }
        } else {
            msgBox.style.color = '#f87171';
            msgBox.textContent = '⚠️ ' + (js.msg || 'Không thể lấy Token');
        }
    } catch (e) {
        msgBox.style.color = '#f87171';
        msgBox.textContent = '⚠️ Lỗi kết nối máy chủ: ' + e;
    }
}

async function refreshAllState() {
    try {
        const r = await fetch('/api/state');
        const js = await r.json();
        if (!js.ok) return;
        GLOBAL_STATE = js;

        document.getElementById('stZaloCount').textContent = js.zalo_accounts.length;
        document.getElementById('stDiscordCount').textContent = js.discord_accounts.length;
        const runningTasks = js.tasks.filter(t => t.status === 'RUNNING');
        document.getElementById('stActiveTasks').textContent = runningTasks.length;
        document.getElementById('lblRunningBadge').textContent = runningTasks.length + ' Task';

        // Update Stealth Mask indicator
        const lblStealth = document.getElementById('lblStealthState');
        const stBadge = document.getElementById('stStealthBadge');
        if (js.stealth_mask) {
            lblStealth.textContent = 'BẬT';
            stBadge.textContent = 'ĐANG ẨN LOG ACC';
            stBadge.style.color = '#fbbf24';
        } else {
            lblStealth.textContent = 'TẮT';
            stBadge.textContent = 'HIỆN ĐẦY ĐỦ ID';
            stBadge.style.color = '#94a3b8';
        }

        // Only rebuild account dropdown if signature changed
        const accSig = JSON.stringify(js.zalo_accounts.map(a => a.uid + a.display_name)) + '|' +
                       JSON.stringify(js.discord_accounts.map(a => a.uid + a.display_name)) + '|' +
                       document.getElementById('selPlatform').value;
        if (accSig !== LAST_ACC_SIGNATURE) {
            LAST_ACC_SIGNATURE = accSig;
            populateAccountDropdown();
            renderAccountCards();
        }

        // Only rebuild TXT dropdown if file list changed
        const txtSig = JSON.stringify(js.txt_files);
        if (txtSig !== LAST_TXT_SIGNATURE) {
            LAST_TXT_SIGNATURE = txtSig;
            renderTxtSelectors();
        }

        renderActiveTasks(js.tasks);
        renderAntiBanTelemetry(js.zalo_antiban || [], js.discord_antiban || []);
        renderSystemLogs(js.logs || []);
    } catch (e) {}
}

function onPlatformChange() {
    LAST_ACC_SIGNATURE = '';
    populateAccountDropdown();
    loadTargetsForSelectedAcc(false);
}

function populateAccountDropdown() {
    const plat = document.getElementById('selPlatform').value;
    const sel = document.getElementById('selAccount');
    const prevVal = sel.value;
    const list = (plat === 'zalo') ? GLOBAL_STATE.zalo_accounts : GLOBAL_STATE.discord_accounts;

    sel.innerHTML = '<option value="">-- Chọn tài khoản (' + list.length + ') --</option>';
    list.forEach(acc => {
        const opt = document.createElement('option');
        opt.value = acc.uid;
        opt.textContent = `${acc.display_name} (${acc.masked_uid}) [${acc.online ? 'ONLINE' : 'OFFLINE'}]`;
        sel.appendChild(opt);
    });

    if (prevVal && list.some(a => a.uid === prevVal)) {
        sel.value = prevVal;
    } else if (list.length > 0) {
        sel.value = list[0].uid;
        loadTargetsForSelectedAcc(false);
    }
}

function renderAccountCards() {
    const zBox = document.getElementById('zaloAccountsList');
    if (GLOBAL_STATE.zalo_accounts.length === 0) {
        zBox.innerHTML = '<div style="color:var(--text-muted);font-size:12.5px;padding:8px;">Chưa có tài khoản Zalo nào.</div>';
    } else {
        zBox.innerHTML = GLOBAL_STATE.zalo_accounts.map(a => `
            <div class="acc-item">
                <div>
                    <div style="font-weight:700;font-size:13.5px;color:#60a5fa;">${a.display_name}</div>
                    <div style="font-size:11.5px;color:var(--text-muted);">
                        UID: <code>${a.masked_uid}</code> • Prefix: <code>${a.prefix}</code> • Cookie: <code>[ẨN BẢO MẬT]</code>
                    </div>
                </div>
                <div class="btn-row">
                    <span class="badge ${a.online ? 'badge-online' : 'badge-stealth'}">${a.online ? 'ONLINE' : 'RECONNECT'}</span>
                    <button type="button" class="btn btn-xs btn-danger" onclick="deleteAccount('zalo', '${a.uid}')">Xoá</button>
                </div>
            </div>
        `).join('');
    }

    const dBox = document.getElementById('discordAccountsList');
    if (GLOBAL_STATE.discord_accounts.length === 0) {
        dBox.innerHTML = '<div style="color:var(--text-muted);font-size:12.5px;padding:8px;">Chưa có tài khoản Discord nào.</div>';
    } else {
        dBox.innerHTML = GLOBAL_STATE.discord_accounts.map(a => `
            <div class="acc-item">
                <div>
                    <div style="font-weight:700;font-size:13.5px;color:#a5b4fc;">${a.display_name}</div>
                    <div style="font-size:11.5px;color:var(--text-muted);">
                        ID: <code>${a.masked_uid}</code> • Token: <code>${a.masked_token}</code> • Route: <code>X-Super-Props</code>
                    </div>
                </div>
                <div class="btn-row">
                    <span class="badge ${a.online ? 'badge-online' : 'badge-stealth'}">${a.online ? 'STEALTH ON' : 'OFFLINE'}</span>
                    <button type="button" class="btn btn-xs btn-danger" onclick="deleteAccount('discord', '${a.uid}')">Xoá</button>
                </div>
            </div>
        `).join('');
    }
}

async function loadTargetsForSelectedAcc(forceRefresh) {
    const plat = document.getElementById('selPlatform').value;
    const uid = document.getElementById('selAccount').value;
    const box = document.getElementById('targetListBox');
    if (!uid) {
        box.innerHTML = '<div style="padding:12px;color:var(--text-muted);text-align:center;">Hãy chọn tài khoản để tải khung chat...</div>';
        return;
    }
    box.innerHTML = '<div style="padding:12px;color:#38bdf8;text-align:center;">⏳ Đang tải danh sách nhóm / kênh chat...</div>';
    try {
        const r = await fetch(`/api/get_targets?platform=${plat}&uid=${encodeURIComponent(uid)}&refresh=${forceRefresh ? '1' : '0'}`);
        const js = await r.json();
        if (!js.ok || !js.targets || js.targets.length === 0) {
            box.innerHTML = '<div style="padding:12px;color:var(--text-muted);text-align:center;">Không tìm thấy nhóm/kênh nào hoặc tài khoản chưa sẵn sàng.</div>';
            return;
        }
        box.innerHTML = js.targets.map(t => `
            <label class="check-item target-row" data-name="${(t.name || '').toLowerCase()}">
                <div class="check-item-left">
                    <input type="checkbox" class="chk-target" value="${t.id}" data-name="${t.name}" data-type="${t.type || 'group'}" onchange="onTargetCheckboxChange()">
                    <span class="check-item-name">${t.name}</span>
                </div>
                <span class="badge ${t.type === 'friend' || t.type === 'dm' ? 'badge-discord' : 'badge-zalo'}">${t.type === 'friend' || t.type === 'dm' ? 'Cá nhân' : 'Nhóm/Kênh'}</span>
            </label>
        `).join('');
    } catch (e) {
        box.innerHTML = '<div style="padding:12px;color:#ef4444;text-align:center;">Lỗi tải danh sách khung chat.</div>';
    }
}

let _memberLoadTimer = null;
function onTargetCheckboxChange() {
    // Automatically load members for the checked chat box(es) after a short 250ms debounce
    if (_memberLoadTimer) clearTimeout(_memberLoadTimer);
    _memberLoadTimer = setTimeout(() => {
        loadMembersForCheckedBoxes();
    }, 250);
}

async function loadMembersForCheckedBoxes() {
    const plat = document.getElementById('selPlatform').value;
    const uid = document.getElementById('selAccount').value;
    const checked = Array.from(document.querySelectorAll('.chk-target:checked'));
    const mBox = document.getElementById('memberListBox');

    if (!uid || checked.length === 0) {
        mBox.innerHTML = '<div style="padding:10px;color:var(--text-muted);text-align:center;font-size:12px;">Hãy tích chọn ít nhất 1 Nhóm Zalo hoặc Kênh Discord để tải danh sách thành viên chuẩn của khung chat đó.</div>';
        return;
    }

    // Preserve currently checked member UIDs if any
    const prevCheckedUids = new Set(Array.from(document.querySelectorAll('.chk-member:checked')).map(el => el.value));

    const targetIds = checked.map(c => c.value).slice(0, 5).join(',');
    mBox.innerHTML = '<div style="padding:10px;color:#38bdf8;text-align:center;font-size:12px;">⏳ Đang quét & giải mã tên thành viên chuẩn trong khung chat...</div>';

    try {
        const r = await fetch(`/api/get_members?platform=${plat}&uid=${encodeURIComponent(uid)}&target_ids=${encodeURIComponent(targetIds)}`);
        const js = await r.json();
        const members = js.members || [];

        let html = `
            <label class="check-item member-row" data-name="all tat ca everyone">
                <div class="check-item-left">
                    <input type="checkbox" class="chk-member" value="-1" data-name="All" ${prevCheckedUids.has('-1') ? 'checked' : ''}>
                    <span class="check-item-name" style="color:#fbbf24;font-weight:700;">📢 @All / @everyone (Tag toàn bộ khung chat)</span>
                </div>
                <span class="badge badge-stealth">Tất cả</span>
            </label>
        `;

        html += members.map(m => `
            <label class="check-item member-row" data-name="${(m.name || '').toLowerCase()}">
                <div class="check-item-left">
                    <input type="checkbox" class="chk-member" value="${m.uid}" data-name="${m.name}" ${prevCheckedUids.has(String(m.uid)) ? 'checked' : ''}>
                    <span class="check-item-name">@${m.name}</span>
                </div>
                <span class="badge badge-zalo">${m.masked_uid || m.uid.slice(-4)}</span>
            </label>
        `).join('');

        mBox.innerHTML = html;
    } catch (e) {
        mBox.innerHTML = '<div style="padding:10px;color:#ef4444;text-align:center;">Lỗi tải thành viên khung chat.</div>';
    }
}

function selectAllTargets(flag) {
    document.querySelectorAll('.chk-target').forEach(el => {
        if (el.closest('.target-row').style.display !== 'none') el.checked = flag;
    });
    onTargetCheckboxChange();
}

function selectAllMembers(flag) {
    document.querySelectorAll('.chk-member').forEach(el => {
        if (el.closest('.member-row').style.display !== 'none') el.checked = flag;
    });
}

function filterTargetList() {
    const q = (document.getElementById('inpFilterTarget').value || '').toLowerCase().trim();
    document.querySelectorAll('.target-row').forEach(row => {
        const n = row.getAttribute('data-name') || '';
        row.style.display = (!q || n.includes(q)) ? 'flex' : 'none';
    });
}

function filterMemberList() {
    const q = (document.getElementById('inpFilterMember').value || '').toLowerCase().trim();
    document.querySelectorAll('.member-row').forEach(row => {
        const n = row.getAttribute('data-name') || '';
        row.style.display = (!q || n.includes(q)) ? 'flex' : 'none';
    });
}

async function startCampaignNow() {
    const platform = document.getElementById('selPlatform').value;
    const acc_uid = document.getElementById('selAccount').value;
    const checkedTargets = Array.from(document.querySelectorAll('.chk-target:checked')).map(el => ({
        id: el.value,
        name: el.getAttribute('data-name') || el.value,
        is_group: (el.getAttribute('data-type') !== 'friend')
    }));

    if (!acc_uid) {
        alert('Vui lòng chọn tài khoản thực thi!');
        return;
    }
    if (checkedTargets.length === 0) {
        alert('Vui lòng tích chọn ít nhất 1 khung chat (Nhóm Zalo hoặc Kênh Discord)!');
        return;
    }

    const checkedMembers = Array.from(document.querySelectorAll('.chk-member:checked')).map(el => ({
        uid: el.value,
        name: el.getAttribute('data-name') || ''
    }));

    const payload = {
        platform,
        acc_uid,
        targets: checkedTargets,
        mode: document.getElementById('selTaskMode').value,
        delay: parseFloat(document.getElementById('inpTaskDelay').value || '1.8'),
        txt_file: document.getElementById('selTaskFile').value,
        raw_text: document.getElementById('txtRawContent').value,
        mentions: checkedMembers,
        raw_tag_text: document.getElementById('inpRawTagText').value,
        auto_tag_box: document.getElementById('chkAutoTagBox').checked,
        random_icon: document.getElementById('chkRandomIcon').checked,
        style_cfg: {
            bold: document.getElementById('chkBoldText').checked,
            size: document.getElementById('selFontSize').value
        }
    };

    try {
        const r = await fetch('/api/start_task', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const js = await r.json();
        if (js.ok) {
            await refreshAllState();
        } else {
            alert(js.msg || 'Không thể khởi chạy chiến dịch');
        }
    } catch (e) {
        alert('Lỗi kết nối: ' + e);
    }
}

function renderActiveTasks(tasks) {
    const box = document.getElementById('activeTasksBox');
    const running = (tasks || []).filter(t => t.status === 'RUNNING');
    if (running.length === 0) {
        box.innerHTML = '<div style="padding:12px;color:var(--text-muted);text-align:center;">Chưa có chiến dịch nào đang chạy.</div>';
        return;
    }
    box.innerHTML = running.map(t => `
        <div class="acc-item" style="margin-bottom:6px;padding:8px 10px;">
            <div style="min-width:0;flex:1;">
                <div style="font-weight:700;font-size:12.5px;color:#38bdf8;">
                    [${t.platform.toUpperCase()}] ${t.target_name} (${t.mode.toUpperCase()})
                </div>
                <div style="font-size:11.5px;color:var(--text-muted);">
                    Đã gửi: <b style="color:#10b981;">${t.sent_count}</b> • Lỗi: <b style="color:#ef4444;">${t.error_count}</b> • Tag: <b>${t.tag_count || 0}</b> • ${t.antiban_note || ''}
                </div>
                <div style="font-size:11px;color:#94a3b8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                    ${t.last_log || ''}
                </div>
            </div>
            <button type="button" class="btn btn-xs btn-danger" onclick="stopSingleTask('${t.task_id}')">Dừng</button>
        </div>
    `).join('');
}

async function stopSingleTask(taskId) {
    await fetch('/api/stop_task', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId })
    });
    await refreshAllState();
}

async function stopAllTasksGlobal() {
    await fetch('/api/stop_all', { method: 'POST' });
    await refreshAllState();
}

async function addZaloAccount() {
    const payload = {
        name: document.getElementById('zAccName').value,
        imei: document.getElementById('zAccImei').value,
        cookie: document.getElementById('zAccCookie').value,
        proxy: document.getElementById('zAccProxy').value,
        prefix: document.getElementById('zAccPrefix').value || '.'
    };
    const r = await fetch('/api/add_zalo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const js = await r.json();
    alert(js.msg);
    if (js.ok) {
        LAST_ACC_SIGNATURE = '';
        await refreshAllState();
    }
}

async function addDiscordAccount() {
    const payload = {
        name: document.getElementById('dAccName').value,
        token: document.getElementById('dAccToken').value,
        proxy: document.getElementById('dAccProxy').value,
        prefix: document.getElementById('dAccPrefix').value || '.',
        super_props_b64: document.getElementById('dAccSuperProps').value,
        fingerprint: document.getElementById('dAccFingerprint').value,
        user_agent: document.getElementById('dAccUA').value
    };
    const r = await fetch('/api/add_discord', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const js = await r.json();
    alert(js.msg);
    if (js.ok) {
        LAST_ACC_SIGNATURE = '';
        await refreshAllState();
    }
}

async function deleteAccount(platform, uid) {
    const url = (platform === 'zalo') ? '/api/del_zalo' : '/api/del_discord';
    await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uid })
    });
    LAST_ACC_SIGNATURE = '';
    await refreshAllState();
}

function renderAntiBanTelemetry(zList, dList) {
    const zBox = document.getElementById('zaloAntibanCards');
    zBox.innerHTML = zList.length === 0
        ? '<div style="padding:8px;color:var(--text-muted);font-size:12px;">Chưa có tài khoản Zalo kích hoạt.</div>'
        : zList.map(x => `
            <div class="acc-item" style="padding:7px 10px;margin-bottom:5px;">
                <div>
                    <div style="font-weight:700;font-size:12.5px;color:#60a5fa;">${x.name} (${x.masked_uid})</div>
                    <div style="font-size:11.5px;color:var(--text-muted);">
                        Engine: <b>${x.engine_name}</b> • Đã gửi: <b>${x.sent_total}</b> • Nhịp: <b>${x.burst_count}/${x.next_break_at}</b>
                    </div>
                </div>
                <span class="badge badge-online">Health ${x.health_score}%</span>
            </div>
        `).join('');

    const dBox = document.getElementById('discordAntibanCards');
    dBox.innerHTML = dList.length === 0
        ? '<div style="padding:8px;color:var(--text-muted);font-size:12px;">Chưa có tài khoản Discord kích hoạt.</div>'
        : dList.map(x => `
            <div class="acc-item" style="padding:7px 10px;margin-bottom:5px;">
                <div>
                    <div style="font-weight:700;font-size:12.5px;color:#a5b4fc;">${x.name} (${x.masked_uid})</div>
                    <div style="font-size:11.5px;color:var(--text-muted);">
                        Engine: <b>${x.engine_name}</b> • Đã gửi: <b>${x.sent_total}</b> • Snowflake Nonce: <b>Active</b>
                    </div>
                </div>
                <span class="badge badge-discord">Health ${x.health_score}%</span>
            </div>
        `).join('');
}

function renderSystemLogs(logs) {
    const term = document.getElementById('sysLogTerminal');
    term.innerHTML = logs.map(l => `
        <div class="log-line">
            <span style="color:#64748b;">[${l.time}]</span>
            <span style="color:#38bdf8;font-weight:700;">[${l.category}]</span>
            <span style="color:#e2e8f0;">${l.message}</span>
        </div>
    `).join('');
}

function renderTxtSelectors() {
    const sel = document.getElementById('selTaskFile');
    const prev = sel.value;
    sel.innerHTML = '<option value="">-- Dùng văn bản nhập tay bên dưới --</option>';
    (GLOBAL_STATE.txt_files || []).forEach(f => {
        const opt = document.createElement('option');
        opt.value = f;
        opt.textContent = '📄 ' + f;
        sel.appendChild(opt);
    });
    if (prev && GLOBAL_STATE.txt_files.includes(prev)) sel.value = prev;

    const listBox = document.getElementById('txtFilesListBox');
    listBox.innerHTML = (GLOBAL_STATE.txt_files || []).map(f => `
        <div class="acc-item" style="padding:7px 10px;margin-bottom:6px;">
            <span style="font-weight:600;font-size:13px;">📄 ${f}</span>
            <div class="btn-row">
                <button type="button" class="btn btn-xs btn-ghost" onclick="loadTxtToEditor('${f}')">Sửa</button>
                <button type="button" class="btn btn-xs btn-danger" onclick="deleteTxtFile('${f}')">Xoá</button>
            </div>
        </div>
    `).join('');
}

async function loadTxtToEditor(fname) {
    const r = await fetch(`/api/get_txt?name=${encodeURIComponent(fname)}`);
    const js = await r.json();
    if (js.ok) {
        document.getElementById('inpTxtFilename').value = fname;
        document.getElementById('inpTxtBody').value = js.content;
    }
}

async function saveTxtFile() {
    const name = document.getElementById('inpTxtFilename').value;
    const content = document.getElementById('inpTxtBody').value;
    const r = await fetch('/api/save_txt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, content })
    });
    const js = await r.json();
    alert(js.msg);
    if (js.ok) {
        LAST_TXT_SIGNATURE = '';
        await refreshAllState();
    }
}

async function deleteTxtFile(name) {
    await fetch('/api/del_txt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
    });
    LAST_TXT_SIGNATURE = '';
    await refreshAllState();
}

window.addEventListener('DOMContentLoaded', () => {
    refreshAllState();
    setInterval(refreshAllState, 2200);
});
</script>
</body>
</html>
"""


# ==============================================================================
#  SECTION 12: FLASK ROUTES & REST API CONTROLLERS (NO LOGIN/REGISTER CLUTTER)
# ==============================================================================

def parse_cookie_input(raw_cookie):
    """Parses JSON cookie list/dict or raw header string into a clean Python dict."""
    raw = str(raw_cookie or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            if "cookies" in parsed and isinstance(parsed["cookies"], list):
                return {str(c["name"]): str(c["value"]) for c in parsed["cookies"] if "name" in c and "value" in c}
            return {str(k): str(v) for k, v in parsed.items()}
        elif isinstance(parsed, list):
            return {str(c["name"]): str(c["value"]) for c in parsed if isinstance(c, dict) and "name" in c and "value" in c}
    except Exception:
        pass

    out = {}
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


@app.route("/gate", methods=["GET", "POST"])
def route_gate():
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1").split(",")[0].strip()
        entered = (request.form.get("gate_key") or "").strip()
        saved_key = get_setting("gate_key", DEFAULT_GATE_KEY)
        if entered == saved_key or entered == DEFAULT_GATE_KEY:
            session.permanent = True
            session["gate_passed"] = True
            SECURITY_SHIELD.reset_auth(ip)
            return redirect(url_for("route_index"))
        SECURITY_SHIELD.record_failed_auth(ip)
        return render_template_string(HTML_GATE, css_pro=CSS_PRO, err="Mã khóa truy cập không chính xác!")
    return render_template_string(HTML_GATE, css_pro=CSS_PRO, err=None)


@app.route("/login")
@app.route("/register")
def route_legacy_auth_redirect():
    """Redirects legacy /login or /register URLs directly to the main dashboard."""
    session["gate_passed"] = True
    return redirect(url_for("route_index"))


@app.route("/")
def route_index():
    """Streamlined Direct Entry — No User Account Registration Clutter."""
    session["gate_passed"] = True
    return render_template_string(HTML_INDEX, css_pro=CSS_PRO)


@app.route("/api/toggle_stealth_mask", methods=["POST"])
def api_toggle_stealth_mask():
    global STEALTH_LOG_MASK_ENABLED
    STEALTH_LOG_MASK_ENABLED = not STEALTH_LOG_MASK_ENABLED
    set_setting("stealth_mask", "1" if STEALTH_LOG_MASK_ENABLED else "0")
    state_str = "BẬT" if STEALTH_LOG_MASK_ENABLED else "TẮT"
    push_sys_log("INFO", "PRIVACY", f"Đã chuyển chế độ Ẩn Log Acc & Token sang: {state_str}")
    return jsonify({"ok": True, "stealth_mask": STEALTH_LOG_MASK_ENABLED})


@app.route("/api/state")
def api_state():
    z_list = []
    z_ab = []
    for uid, bot in list(ZALO_BOTS.items()):
        z_list.append({
            "uid": uid,
            "masked_uid": mask_sensitive_id(uid),
            "name": bot.name,
            "display_name": mask_account_name(bot.name),
            "online": bool(bot.online),
            "prefix": ZALO_LISTENERS[uid].prefix if uid in ZALO_LISTENERS else "."
        })
        ab = ZALO_ANTIBAN.get_account_telemetry(uid)
        ab["name"] = mask_account_name(bot.name)
        ab["masked_uid"] = mask_sensitive_id(uid)
        z_ab.append(ab)

    d_list = []
    d_ab = []
    for uid, bot in list(DISCORD_BOTS.items()):
        d_list.append({
            "uid": uid,
            "masked_uid": mask_sensitive_id(uid),
            "name": bot.name,
            "display_name": mask_account_name(bot.name),
            "masked_token": mask_token_string(bot.token),
            "online": bool(bot.online),
            "prefix": DISCORD_LISTENERS[uid].prefix if uid in DISCORD_LISTENERS else "."
        })
        ab = DISCORD_ANTIBAN.get_account_telemetry(uid)
        ab["name"] = mask_account_name(bot.name)
        ab["masked_uid"] = mask_sensitive_id(uid)
        d_ab.append(ab)

    tasks_out = []
    with GLOBAL_LOCK:
        for tid, t in list(ACTIVE_TASKS.items()):
            tasks_out.append({
                "task_id": tid,
                "platform": t["platform"],
                "acc_uid": mask_sensitive_id(t["acc_uid"]),
                "target_id": mask_sensitive_id(t["target_id"]),
                "target_name": t["target_name"],
                "mode": t["mode"],
                "delay": t["delay"],
                "sent_count": t["sent_count"],
                "error_count": t["error_count"],
                "tag_count": len(t.get("resolved_mentions") or t.get("mentions") or []),
                "status": t["status"],
                "last_log": scrub_log_message(t.get("last_log", "")),
                "antiban_note": t.get("antiban_note", "")
            })

    txt_files = sorted([f for f in os.listdir(TXT_DIR) if f.endswith(".txt")])

    return jsonify({
        "ok": True,
        "stealth_mask": STEALTH_LOG_MASK_ENABLED,
        "zalo_accounts": z_list,
        "discord_accounts": d_list,
        "zalo_antiban": z_ab,
        "discord_antiban": d_ab,
        "tasks": tasks_out,
        "txt_files": txt_files,
        "logs": list(SYSTEM_LOGS)[:80]
    })


@app.route("/api/add_zalo", methods=["POST"])
def api_add_zalo():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "Zalo VIP").strip()
    imei = (data.get("imei") or "").strip()
    raw_cookie = data.get("cookie") or ""
    proxy = (data.get("proxy") or "").strip()
    prefix = (data.get("prefix") or ".").strip() or "."

    cookies_dict = parse_cookie_input(raw_cookie)
    if not imei or not cookies_dict:
        return jsonify({"ok": False, "msg": "Vui lòng nhập đầy đủ IMEI và Cookie Zalo hợp lệ!"})

    temp_uid = f"z_{int(time.time())}"
    z_bot = Zalo(uid=temp_uid, name=name, imei=imei, cookies_dict=cookies_dict, proxy=proxy)
    ok, msg = z_bot.get_login_info()
    if not ok:
        return jsonify({"ok": False, "msg": msg})

    real_uid = str(z_bot.uid)
    ZALO_BOTS[real_uid] = z_bot

    with DB_LOCK:
        conn = get_db_conn()
        conn.execute("""
            INSERT OR REPLACE INTO zalo_accounts
            (uid, name, imei, cookie_json, user_agent, proxy, selfbot_enabled, command_prefix, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, 'ONLINE', ?)
        """, (real_uid, z_bot.name, imei, json.dumps(cookies_dict), z_bot.user_agent, proxy, prefix, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()

    # Pre-fetch groups & friends and start Self-Bot listener
    threading.Thread(target=z_bot.get_groups, daemon=True).start()
    threading.Thread(target=z_bot.get_friends, daemon=True).start()

    if real_uid in ZALO_LISTENERS:
        ZALO_LISTENERS[real_uid].stop()
    listener = ZaloSelfBotListener(z_bot, prefix=prefix)
    ZALO_LISTENERS[real_uid] = listener
    listener.start()

    return jsonify({"ok": True, "uid": real_uid, "msg": f"Đã kết nối Zalo: {mask_account_name(z_bot.name)} thành công!"})


@app.route("/api/del_zalo", methods=["POST"])
def api_del_zalo():
    data = request.get_json(force=True, silent=True) or {}
    uid = str(data.get("uid") or "").strip()
    stop_tasks_by_filter(platform="zalo", acc_uid=uid)
    if uid in ZALO_LISTENERS:
        ZALO_LISTENERS[uid].stop()
        ZALO_LISTENERS.pop(uid, None)
    ZALO_BOTS.pop(uid, None)
    with DB_LOCK:
        conn = get_db_conn()
        conn.execute("DELETE FROM zalo_accounts WHERE uid=?", (uid,))
        conn.commit()
        conn.close()
    return jsonify({"ok": True})


@app.route("/api/discord_reg_token", methods=["POST"])
def api_discord_reg_token():
    """
    Endpoint for the built-in Discord Reg / Safe Token Extractor & Session Warmer.
    Extracts or obtains a Discord token, binds a persistent X-Super-Properties
    browser fingerprint, warms `/users/@me`, and optionally saves & connects the account.
    """
    data = request.get_json(force=True, silent=True) or {}
    mode = (data.get("mode") or "extract").strip()
    raw_input = data.get("raw_input") or ""
    email = data.get("email") or ""
    password = data.get("password") or ""
    mfa_code = data.get("mfa_code") or ""
    proxy = (data.get("proxy") or "").strip()
    auto_save = bool(data.get("auto_save", False))
    prefix = (data.get("prefix") or ".").strip() or "."

    res = discord_reg_or_extract_token(
        mode=mode,
        raw_input=raw_input,
        email=email,
        password=password,
        mfa_code=mfa_code,
        proxy=proxy
    )
    if not res.get("ok"):
        return jsonify(res)

    if auto_save:
        uid = str(res["uid"])
        d_bot = DiscordBot(
            uid=uid,
            name=res["name"],
            username=res["username"],
            token=res["token"],
            proxy=proxy,
            super_props_b64=res.get("super_props_b64", ""),
            fingerprint=res.get("fingerprint", ""),
            user_agent=res.get("ua", "")
        )
        d_bot.online = True
        DISCORD_BOTS[uid] = d_bot

        with DB_LOCK:
            conn = get_db_conn()
            conn.execute("""
                INSERT OR REPLACE INTO discord_accounts
                (uid, name, username, token, proxy, super_props_b64, fingerprint, user_agent, selfbot_enabled, command_prefix, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'ONLINE', ?)
            """, (
                uid, d_bot.name, d_bot.username, d_bot.token, proxy,
                d_bot.super_props_b64, d_bot.fingerprint, d_bot.user_agent,
                prefix, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            conn.commit()
            conn.close()

        threading.Thread(target=d_bot.get_targets, daemon=True).start()
        if uid in DISCORD_LISTENERS:
            DISCORD_LISTENERS[uid].stop()
        listener = DiscordSelfBotListener(d_bot, prefix=prefix)
        DISCORD_LISTENERS[uid] = listener
        listener.start()
        res["msg"] = f"Đã trích xuất, ủ ấm X-Super-Properties & kết nối thành công acc {mask_account_name(d_bot.name)}!"

    return jsonify(res)


@app.route("/api/add_discord", methods=["POST"])
def api_add_discord():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "Discord VIP").strip()
    token = (data.get("token") or "").strip().strip('"\'')
    proxy = (data.get("proxy") or "").strip()
    prefix = (data.get("prefix") or ".").strip() or "."
    super_props_b64 = (data.get("super_props_b64") or "").strip()
    fingerprint = (data.get("fingerprint") or "").strip()
    user_agent = (data.get("user_agent") or "").strip()

    if not token:
        return jsonify({"ok": False, "msg": "Vui lòng nhập Token Discord hoặc dùng công cụ Lấy Token Reg ở trên!"})

    d_bot = DiscordBot(
        uid="temp",
        name=name,
        username="user",
        token=token,
        proxy=proxy,
        super_props_b64=super_props_b64,
        fingerprint=fingerprint,
        user_agent=user_agent
    )
    ok, info = d_bot.check_token()
    if not ok:
        return jsonify({"ok": False, "msg": str(info)})

    real_uid = str(d_bot.uid)
    DISCORD_BOTS[real_uid] = d_bot

    with DB_LOCK:
        conn = get_db_conn()
        conn.execute("""
            INSERT OR REPLACE INTO discord_accounts
            (uid, name, username, token, proxy, super_props_b64, fingerprint, user_agent, selfbot_enabled, command_prefix, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'ONLINE', ?)
        """, (
            real_uid, d_bot.name, d_bot.username, token, proxy,
            d_bot.super_props_b64, d_bot.fingerprint, d_bot.user_agent,
            prefix, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()
        conn.close()

    threading.Thread(target=d_bot.get_targets, daemon=True).start()
    if real_uid in DISCORD_LISTENERS:
        DISCORD_LISTENERS[real_uid].stop()
    listener = DiscordSelfBotListener(d_bot, prefix=prefix)
    DISCORD_LISTENERS[real_uid] = listener
    listener.start()

    return jsonify({"ok": True, "uid": real_uid, "msg": f"Đã kết nối Discord (Phantom Route v8.0): {mask_account_name(d_bot.name)}!"})


@app.route("/api/del_discord", methods=["POST"])
def api_del_discord():
    data = request.get_json(force=True, silent=True) or {}
    uid = str(data.get("uid") or "").strip()
    stop_tasks_by_filter(platform="discord", acc_uid=uid)
    if uid in DISCORD_LISTENERS:
        DISCORD_LISTENERS[uid].stop()
        DISCORD_LISTENERS.pop(uid, None)
    DISCORD_BOTS.pop(uid, None)
    with DB_LOCK:
        conn = get_db_conn()
        conn.execute("DELETE FROM discord_accounts WHERE uid=?", (uid,))
        conn.commit()
        conn.close()
    return jsonify({"ok": True})


@app.route("/api/get_targets")
def api_get_targets():
    platform = request.args.get("platform", "zalo")
    uid = request.args.get("uid", "").strip()
    refresh = request.args.get("refresh", "0") == "1"

    if platform == "zalo":
        bot = ZALO_BOTS.get(uid)
        if not bot:
            return jsonify({"ok": False, "targets": []})
        if refresh or not bot.groups_cache:
            bot.get_groups()
        if refresh or not bot.friends_cache:
            bot.get_friends()
        targets = list(bot.groups_cache) + list(bot.friends_cache)
        return jsonify({"ok": True, "targets": targets})
    else:
        bot = DISCORD_BOTS.get(uid)
        if not bot:
            return jsonify({"ok": False, "targets": []})
        if refresh or not bot.channels_cache:
            bot.get_targets()
        return jsonify({"ok": True, "targets": bot.channels_cache})


@app.route("/api/get_members")
def api_get_members():
    """
    Returns resolved members for one or multiple checked chat boxes (`target_ids` or `target_id`).
    Ensures Zalo group member names are accurately resolved via `get_members_full(gid)`.
    """
    platform = request.args.get("platform", "zalo")
    uid = request.args.get("uid", "").strip()
    raw_ids = request.args.get("target_ids") or request.args.get("target_id") or ""
    target_ids = [x.strip() for x in raw_ids.split(",") if x.strip()]

    if not uid or not target_ids:
        return jsonify({"ok": True, "members": []})

    merged_members = []
    seen_uids = set()

    if platform == "zalo":
        bot = ZALO_BOTS.get(uid)
        if not bot:
            return jsonify({"ok": False, "members": []})
        for tid in target_ids[:5]:
            m_list = bot.get_members_full(tid)
            for m in m_list:
                muid = str(m.get("uid") or "")
                if muid and muid not in seen_uids and muid != str(bot.uid):
                    seen_uids.add(muid)
                    merged_members.append({
                        "uid": muid,
                        "masked_uid": mask_sensitive_id(muid),
                        "name": m.get("name") or f"User_{muid[-4:]}"
                    })
    else:
        bot = DISCORD_BOTS.get(uid)
        if not bot:
            return jsonify({"ok": False, "members": []})
        for tid in target_ids[:5]:
            m_list = bot.get_channel_members(tid)
            for m in m_list:
                muid = str(m.get("uid") or "")
                if muid and muid not in seen_uids and muid != str(bot.uid):
                    seen_uids.add(muid)
                    merged_members.append({
                        "uid": muid,
                        "masked_uid": mask_sensitive_id(muid),
                        "name": m.get("name") or f"User_{muid[-4:]}"
                    })

    return jsonify({"ok": True, "members": merged_members})


@app.route("/api/start_task", methods=["POST"])
def api_start_task():
    data = request.get_json(force=True, silent=True) or {}
    platform = data.get("platform", "zalo")
    acc_uid = str(data.get("acc_uid") or "").strip()
    targets = data.get("targets") or []
    mode = data.get("mode", "nhay")
    delay = max(0.4, float(data.get("delay") or 1.8))
    txt_file = (data.get("txt_file") or "").strip()
    raw_text = (data.get("raw_text") or "").strip()
    mentions = data.get("mentions") or []
    raw_tag_text = (data.get("raw_tag_text") or "").strip()
    auto_tag_box = bool(data.get("auto_tag_box", False))
    random_icon = bool(data.get("random_icon", False))
    style_cfg = data.get("style_cfg") or {}

    if not acc_uid or not targets:
        return jsonify({"ok": False, "msg": "Thiếu tài khoản hoặc khung chat mục tiêu!"})

    # Load lines from .txt file OR raw_text, while NEVER losing inline @Tags from raw_text!
    if txt_file:
        lines, _ = load_txt_lines(txt_file)
        # If user also typed @Tag in raw_text while using a .txt file, preserve it in raw_tag_text!
        if raw_text and "@" in raw_text and not raw_tag_text:
            at_parts = re.findall(r"@([^\s@]+(?:\s+[^\s@]+){0,3})", raw_text)
            if at_parts:
                raw_tag_text = ", ".join(at_parts)
    elif raw_text:
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    else:
        lines, _ = load_txt_lines(None)

    started_ids = []
    for t in targets:
        tid = str(t.get("id") or "").strip()
        tname = str(t.get("name") or tid)
        is_grp = bool(t.get("is_group", True))
        if not tid:
            continue
        task_id = spawn_automation_task(
            platform=platform,
            acc_uid=acc_uid,
            target_id=tid,
            target_name=tname,
            is_group=is_grp,
            mode=mode,
            delay=delay,
            lines=lines,
            mentions=mentions,
            style_cfg=style_cfg,
            random_icon=random_icon,
            source="WEB",
            raw_tag_text=raw_tag_text,
            auto_tag_box=auto_tag_box
        )
        started_ids.append(task_id)

    return jsonify({"ok": True, "started": len(started_ids), "msg": f"Đã khởi chạy {len(started_ids)} chiến dịch!"})


@app.route("/api/stop_task", methods=["POST"])
def api_stop_task():
    data = request.get_json(force=True, silent=True) or {}
    tid = data.get("task_id")
    cnt = stop_tasks_by_filter(task_id=tid)
    return jsonify({"ok": True, "stopped": cnt})


@app.route("/api/stop_all", methods=["POST"])
def api_stop_all():
    cnt = stop_tasks_by_filter()
    return jsonify({"ok": True, "stopped": cnt})


@app.route("/api/get_txt")
def api_get_txt():
    name = os.path.basename(request.args.get("name", ""))
    fpath = os.path.join(TXT_DIR, name)
    if not name or not os.path.exists(fpath):
        return jsonify({"ok": False, "content": ""})
    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
        return jsonify({"ok": True, "content": f.read()})


@app.route("/api/save_txt", methods=["POST"])
def api_save_txt():
    data = request.get_json(force=True, silent=True) or {}
    name = os.path.basename((data.get("name") or "").strip())
    content = (data.get("content") or "").strip()
    if not name:
        return jsonify({"ok": False, "msg": "Vui lòng nhập tên file!"})
    if not name.endswith(".txt"):
        name += ".txt"
    with open(os.path.join(TXT_DIR, name), "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"ok": True, "msg": f"Đã lưu file kịch bản {name}!"})


@app.route("/api/del_txt", methods=["POST"])
def api_del_txt():
    data = request.get_json(force=True, silent=True) or {}
    name = os.path.basename((data.get("name") or "").strip())
    fpath = os.path.join(TXT_DIR, name)
    if name and os.path.exists(fpath):
        os.remove(fpath)
    return jsonify({"ok": True})


# Initialize DB and restore sessions when imported or executed
init_database()
restore_saved_accounts()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    push_sys_log("SUCCESS", "BOOT", f"Khởi động {APP_TITLE} ({APP_VERSION}) trên cổng {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
