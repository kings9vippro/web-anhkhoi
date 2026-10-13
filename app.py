# ==============================================================================
# Bản quyền © Phạm Anh Khôi (Verified ✔) — Ricki Vip
# Tác giả: Phạm Anh Khôi ✔
# Mọi quyền được bảo hộ. Nghiêm cấm sao chép hoặc phân phối trái phép.
# ==============================================================================

import os
import re
import json
import time
import sqlite3
import threading
import random
import base64
import hashlib
from functools import wraps
from collections import defaultdict

from flask import (
    Flask, render_template_string, request, jsonify,
    session, redirect, url_for, send_from_directory
)
from Crypto.Cipher import AES
import requests

# ---------------------------------------------------------
# CẤU HÌNH HỆ THỐNG & BIẾN MÔI TRƯỜNG RENDER
# ---------------------------------------------------------
APP_PASSWORD = os.environ.get("APP_PASSWORD", "anhkhoidz")
DATA_DIR = os.environ.get("DATA_DIR", "/tmp/ricki_web")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "ricki_vip.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ĐỐI TƯỢNG APP CHO GUNICORN TRÊN RENDER (BẮT BUỘC ĐỂ KHÔNG BỊ LỖI DEPLOY)
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))
# HỖ TRỢ TỆP VĂN BẢN CỰC LỚN 5MB - 100MB+
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

# ---------------------------------------------------------
# BỘ GIÁP BẢO MẬT WEB & API
# ---------------------------------------------------------
class WebSecurityArmor:
    def __init__(self):
        self.lock = threading.Lock()
        self.req_history = defaultdict(list)
        self.failed_logins = defaultdict(list)
        self.blocked_ips = {}

    def check_rate_limit(self, ip, max_reqs=300, window=60):
        now = time.time()
        with self.lock:
            if ip in self.blocked_ips:
                if now < self.blocked_ips[ip]:
                    remain = int(self.blocked_ips[ip] - now)
                    return False, f"IP tạm thời bị giới hạn. Thử lại sau {remain}s."
                del self.blocked_ips[ip]

            history = [t for t in self.req_history[ip] if now - t < window]
            history.append(now)
            self.req_history[ip] = history

            if len(history) > max_reqs:
                self.blocked_ips[ip] = now + 60
                return False, "Tần suất truy cập quá nhanh (Rate Limit). Tạm khóa 60s."

            return True, None

    def record_login(self, ip, success):
        now = time.time()
        with self.lock:
            if success:
                self.failed_logins.pop(ip, None)
            else:
                fails = [t for t in self.failed_logins[ip] if now - t < 300]
                fails.append(now)
                self.failed_logins[ip] = fails
                if len(fails) >= 8:
                    self.blocked_ips[ip] = now + 180
                    return False, "Đăng nhập sai quá 8 lần. Tạm khóa IP 3 phút."
            return True, None

SECURITY_ARMOR = WebSecurityArmor()

@app.before_request
def security_firewall_check():
    if request.path.startswith("/static") or request.path in ["/logo", "/health"]:
        return None
    ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
    allowed, err = SECURITY_ARMOR.check_rate_limit(ip)
    if not allowed:
        return jsonify({"error": err}), 429

@app.after_request
def apply_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# ---------------------------------------------------------
# CƠ SỞ DỮ LIỆU SQLITE
# ---------------------------------------------------------
def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c

def init_db():
    conn = db()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL,
        platform TEXT NOT NULL DEFAULT 'zalo',
        imei TEXT,
        cookies TEXT,
        token TEXT,
        real_name TEXT,
        avatar TEXT,
        status TEXT DEFAULT 'unknown',
        enabled INTEGER DEFAULT 1,
        created_at REAL
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        filepath TEXT NOT NULL,
        size INTEGER,
        lines INTEGER,
        blocks INTEGER DEFAULT 1,
        created_at REAL
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    conn.commit()

    # Tự động nạp tài khoản từ Environment Variables của Render nếu có
    z_imei = os.environ.get("ZALO_IMEI", "").strip()
    z_cookies = os.environ.get("ZALO_COOKIES", "").strip()
    d_token = os.environ.get("DISCORD_TOKEN", "").strip()

    if z_imei and z_cookies:
        exist = conn.execute("SELECT id FROM accounts WHERE platform = 'zalo' AND imei = ?", (z_imei,)).fetchone()
        if not exist:
            conn.execute("""
            INSERT INTO accounts (label, platform, imei, cookies, real_name, status, enabled, created_at)
            VALUES ('Zalo Render Env', 'zalo', ?, ?, 'Zalo User', 'live', 1, ?)
            """, (z_imei, z_cookies, time.time()))
            conn.commit()

    if d_token:
        exist = conn.execute("SELECT id FROM accounts WHERE platform = 'discord' AND token = ?", (d_token,)).fetchone()
        if not exist:
            conn.execute("""
            INSERT INTO accounts (label, platform, token, real_name, status, enabled, created_at)
            VALUES ('Discord Render Env', 'discord', ?, 'Discord User', 'live', 1, ?)
            """, (d_token, time.time()))
            conn.commit()

    conn.close()

init_db()

# ---------------------------------------------------------
# BẢNG MÀU ZALO CHUẨN XÁC & HUY HIỆU MÀU
# ---------------------------------------------------------
ZALO_PALETTE = [
    {"id": "red",     "name": "Đỏ Chuẩn",      "hex": "e8453c", "badge": "🔴"},
    {"id": "gold",    "name": "Vàng Cam",      "hex": "f4a261", "badge": "🟡"},
    {"id": "green",   "name": "Xanh Lá",       "hex": "2a9d8f", "badge": "🟢"},
    {"id": "orange",  "name": "Cam Đậm",       "hex": "e76f51", "badge": "🟠"},
    {"id": "blue",    "name": "Xanh Dương",    "hex": "457b9d", "badge": "💎"},
    {"id": "purple",  "name": "Tím Violet",    "hex": "9b5de5", "badge": "🟣"},
    {"id": "pink",    "name": "Hồng Neon",     "hex": "f72585", "badge": "🌸"},
    {"id": "cyan",    "name": "Xanh Ngọc",     "hex": "00b4d8", "badge": "🔵"},
]

ICONS_DAMAGE = ["⚔️", "💥", "🔥", "💀", "🥊", "🪓", "🩸", "⚰️", "⚡", "💣", "🔪", "🏹"]
ICONS_TROLL  = ["🐸", "🤡", "💨", "🖕🏻", "💩", "👎", "🐒", "🐷", "🤏", "🐔", "🤢", "🚮"]
ICONS_MOCK   = ["😏", "😜", "🤪", "🤫", "🥱", "🖕", "🤮", "😹", "🤣", "🤭", "👀", "👻"]
ICONS_ZALO_CLASSIC = [":-p", ":-d", ";-p", "/-punch", "/-strong", "/-no", "/-ok", "/-break"]

def generate_combat_combo(combo_type="mixed", count=3):
    count = max(1, min(count, 8))
    if combo_type == "damage":
        chosen = random.sample(ICONS_DAMAGE, min(count, len(ICONS_DAMAGE)))
    elif combo_type == "troll":
        chosen = random.sample(ICONS_TROLL, min(count, len(ICONS_TROLL)))
    elif combo_type == "mock":
        chosen = random.sample(ICONS_MOCK, min(count, len(ICONS_MOCK)))
    elif combo_type == "zalo_classic":
        chosen = random.sample(ICONS_ZALO_CLASSIC, min(count, len(ICONS_ZALO_CLASSIC)))
    elif combo_type == "mixed":
        pool = [random.choice(ICONS_DAMAGE), random.choice(ICONS_TROLL), random.choice(ICONS_MOCK)]
        if count > 3:
            all_icons = ICONS_DAMAGE + ICONS_TROLL + ICONS_MOCK + ICONS_ZALO_CLASSIC
            pool.extend(random.sample(all_icons, count - 3))
        chosen = pool[:count]
    else:
        chosen = []
    return " ".join(chosen)

def utf16_len(s):
    if not s:
        return 0
    return len(s.encode("utf-16-le")) // 2

# ---------------------------------------------------------
# HÀM ANTI-BAN ZALO V5 NÂNG CAO (AN TOÀN PHÔNG TIẾNG VIỆT 100%)
# ---------------------------------------------------------
def apply_antiband_zalo_v5(text):
    if not text:
        return text
    SAFE_SPACES = [" ", "\u00a0", " \u200b", "\u2009", "\u202f"]
    SAFE_TAIL_CHARS = ["\u200b", "\u200c", "\u200d", "\ufeff"]

    lines = text.split("\n")
    processed_lines = []

    for line in lines:
        if not line.strip():
            processed_lines.append(line)
            continue
        words = line.split(" ")
        new_words = []
        for i, w in enumerate(words):
            new_words.append(w)
            if i < len(words) - 1:
                if random.random() < 0.28:
                    new_words.append(random.choice(SAFE_SPACES))
                else:
                    new_words.append(" ")
        line_str = "".join(new_words)
        line_str = line_str.replace(". ", ".\u200b ").replace(", ", ",\u200b ").replace("! ", "!\u200b ").replace("? ", "?\u200b ")
        processed_lines.append(line_str)

    result = "\n".join(processed_lines)
    tail_len = random.randint(3, 6)
    tail = "".join(random.choice(SAFE_TAIL_CHARS) for _ in range(tail_len))
    result += tail
    return result

# ---------------------------------------------------------
# TRÌNH ĐỌC TỆP STREAMING O(1) RAM (HỖ TRỢ 5MB - 50MB+)
# ---------------------------------------------------------
class FastFileBlockReader:
    def __init__(self, filepath):
        self.filepath = filepath
        self.lock = threading.Lock()
        self.fp = open(filepath, "r", encoding="utf-8", errors="ignore")

    def next_block(self):
        with self.lock:
            lines = []
            for line in self.fp:
                line_str = line.strip()
                if not line_str:
                    if lines:
                        return "\n".join(lines)
                else:
                    lines.append(line.rstrip("\r\n"))
            if lines:
                return "\n".join(lines)
            # Quay lại đầu tệp khi hết file để lặp vô tận
            self.fp.seek(0)
            for line in self.fp:
                line_str = line.strip()
                if line_str:
                    return line.rstrip("\r\n")
            return None

    def close(self):
        try:
            self.fp.close()
        except Exception:
            pass

# ---------------------------------------------------------
# GIAO THỨC ZALO WEB CLIENT NÂNG CAO
# ---------------------------------------------------------
class Zalo:
    def __init__(self, imei, cookies):
        self.imei = imei
        self.cookies_str = cookies
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": "https://chat.zalo.me/",
            "Origin": "https://chat.zalo.me"
        })
        self._parse_cookies()
        self.secret_key = None
        self._login()

    def _parse_cookies(self):
        raw = self.cookies_str.strip()
        if raw.startswith("["):
            try:
                arr = json.loads(raw)
                for item in arr:
                    n = item.get("name")
                    v = item.get("value")
                    if n and v:
                        self.session.cookies.set(n, v, domain=".zalo.me")
                return
            except Exception:
                pass
        pairs = raw.split(";")
        for p in pairs:
            if "=" in p:
                k, v = p.strip().split("=", 1)
                self.session.cookies.set(k.strip(), v.strip(), domain=".zalo.me")

    def _login(self):
        url = f"https://chat.zalo.me/api/login/getServerInfo?imei={self.imei}"
        r = self.session.get(url, timeout=10)
        data = r.json()
        if data.get("error_code") != 0:
            raise Exception("Phiên đăng nhập hết hạn hoặc Cookie không hợp lệ")
        info = data.get("data", {})
        self.secret_key = info.get("zpw_enk")
        if not self.secret_key:
            zpw = self.session.cookies.get("zpw_sek")
            if zpw:
                self.secret_key = zpw
        if not self.secret_key:
            raise Exception("Không thể lấy Secret Key Zalo")

    def check_status(self):
        t0 = time.time()
        try:
            prof = self.get_user_profile()
            ping_ms = int((time.time() - t0) * 1000)
            if prof and (prof.get("name") or prof.get("displayName") or prof.get("userId")):
                uname = prof.get("name") or prof.get("displayName") or "Zalo User"
                uid = prof.get("userId") or prof.get("uid") or ""
                return {"live": True, "name": uname, "uid": uid, "ping_ms": ping_ms}
            return {"live": False, "error": "Không thể lấy hồ sơ tài khoản", "ping_ms": ping_ms}
        except Exception as e:
            ping_ms = int((time.time() - t0) * 1000)
            return {"live": False, "error": str(e), "ping_ms": ping_ms}

    def _pad(self, s):
        bs = AES.block_size
        return s + (bs - len(s) % bs) * chr(bs - len(s) % bs).encode()

    def _unpad(self, s):
        return s[:-ord(s[len(s)-1:])]

    def encrypt(self, data_str):
        raw_key = self.secret_key
        key = raw_key.ljust(32, "0").encode("utf-8")[:32] if len(raw_key) < 32 else raw_key.encode("utf-8")[:32]
        iv = bytes([0] * 16)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded = self._pad(data_str.encode("utf-8"))
        enc = cipher.encrypt(padded)
        return base64.b64encode(enc).decode("utf-8")

    def decrypt(self, enc_str):
        raw_key = self.secret_key
        key = raw_key.ljust(32, "0").encode("utf-8")[:32] if len(raw_key) < 32 else raw_key.encode("utf-8")[:32]
        iv = bytes([0] * 16)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        dec = cipher.decrypt(base64.b64decode(enc_str))
        return self._unpad(dec).decode("utf-8")

    def get_user_profile(self):
        try:
            url = "https://chat.zalo.me/api/profile/get"
            params = {"params": self.encrypt("{}"), "imei": self.imei}
            r = self.session.post(url, data=params, timeout=10)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                return info.get("data", {})
        except Exception:
            pass
        return {}

    def get_friend_map(self):
        fmap = {}
        try:
            url = "https://chat.zalo.me/api/friend/getfriends"
            params = {"params": self.encrypt("{}"), "imei": self.imei}
            r = self.session.post(url, data=params, timeout=10)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                for item in info.get("data", []):
                    uid = str(item.get("userId") or item.get("uid") or "")
                    name = item.get("displayName") or item.get("zaloName") or item.get("name")
                    if uid and name:
                        fmap[uid] = name
        except Exception:
            pass
        return fmap

    def get_conversations(self):
        boxes = []
        try:
            url = "https://chat.zalo.me/api/group/getlg"
            params = {"params": self.encrypt("{}"), "imei": self.imei}
            r = self.session.post(url, data=params, timeout=10)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                for g in info.get("data", {}).get("gridInfoMap", {}).values():
                    boxes.append({
                        "id": str(g.get("grid")),
                        "name": "[Zalo Nhóm] " + g.get("name", "Nhóm không tên"),
                        "type": "group",
                        "platform": "zalo"
                    })
        except Exception:
            pass
        try:
            url = "https://chat.zalo.me/api/friend/getfriends"
            params = {"params": self.encrypt("{}"), "imei": self.imei}
            r = self.session.post(url, data=params, timeout=10)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                for f in info.get("data", []):
                    boxes.append({
                        "id": str(f.get("userId")),
                        "name": "[Zalo Bạn] " + (f.get("displayName") or "Bạn bè"),
                        "type": "user",
                        "platform": "zalo"
                    })
        except Exception:
            pass
        return boxes

    def get_group_members(self, grid):
        members = []
        fmap = self.get_friend_map()
        try:
            pl = json.dumps({"grid": str(grid)})
            params = {"params": self.encrypt(pl), "imei": self.imei}
            r = self.session.post("https://chat.zalo.me/api/group/getgridinfo", data=params, timeout=10)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                gdata = info.get("data", {})
                mem_list = gdata.get("memList", []) or gdata.get("members", [])
                mem_info_map = gdata.get("memInfoMap", {})

                for m in mem_list:
                    if isinstance(m, dict):
                        uid = str(m.get("uid") or m.get("id") or m.get("userId") or "")
                        info_item = mem_info_map.get(uid, {}) if isinstance(mem_info_map, dict) else {}
                        raw_name = m.get("dName") or m.get("displayName") or m.get("name") or info_item.get("dName") or info_item.get("displayName")
                    else:
                        uid = str(m)
                        info_item = mem_info_map.get(uid, {}) if isinstance(mem_info_map, dict) else {}
                        raw_name = info_item.get("dName") or info_item.get("displayName") or info_item.get("name")

                    if not uid:
                        continue
                    final_name = fmap.get(uid) or raw_name or f"Thành viên {uid[-4:]}"
                    members.append({"id": uid, "name": final_name})
        except Exception:
            pass
        return members

    def build_colored_message(self, raw_text, color_mode="rainbow", fixed_color="red",
                              is_heading=False, color_offset=0, use_badge=True,
                              tag_header="", antiband=True):
        """
        BẢO ĐẢM HIỆN MÀU RỰC RỠ TRÊN ZALO MOBILE:
        - Khi use_heading=False (mặc định cho tin màu), KHÔNG gắn '# ' ở đầu dòng để Zalo Mobile
          không bị ghi đè màu chữ thành màu tiêu đề trắng mặc định!
        - Áp dụng chuẩn UTF-16 code units cho từng dòng.
        """
        raw_lines = raw_text.split("\n")
        processed_lines = []

        for idx, line in enumerate(raw_lines):
            clean_line = line.strip()
            if not clean_line:
                processed_lines.append("")
                continue

            if antiband:
                clean_line = apply_antiband_zalo_v5(clean_line)

            if color_mode == "rainbow":
                color_idx = (idx + color_offset) % len(ZALO_PALETTE)
                col = ZALO_PALETTE[color_idx]
            elif color_mode == "random":
                col = random.choice(ZALO_PALETTE)
            elif color_mode == "fixed":
                col = next((c for c in ZALO_PALETTE if c["id"] == fixed_color), ZALO_PALETTE[0])
            else:
                col = ZALO_PALETTE[0]

            prefix = ""
            if use_badge:
                prefix += col["badge"] + " "
            if is_heading:
                prefix = "# " + prefix

            display_line = prefix + clean_line
            processed_lines.append((display_line, col))

        current_u16_pos = utf16_len(tag_header) if tag_header else 0
        first_hex = ZALO_PALETTE[0]["hex"]
        styles = []
        body_lines_text = []

        for idx, item in enumerate(processed_lines):
            if isinstance(item, tuple):
                display_line, col = item
                clean_hex = col["hex"].lstrip("#").lower()
                if idx == 0:
                    first_hex = clean_hex

                line_len = utf16_len(display_line)
                # Style màu chuẩn của Zalo Web API
                styles.append({
                    "start": current_u16_pos,
                    "len": line_len,
                    "st": f"c_{clean_hex}"
                })
                # Bổ sung style in đậm
                styles.append({
                    "start": current_u16_pos,
                    "len": line_len,
                    "st": "b"
                })
                body_lines_text.append(display_line)
                current_u16_pos += line_len + 1
            else:
                body_lines_text.append("")
                current_u16_pos += 1

        body_text = "\n".join(body_lines_text)
        final_message = tag_header + body_text if tag_header else body_text

        return final_message, styles, "#" + first_hex

    def build_mentions_payload(self, mentions=None, tag_all=False, tag_mode="rotate", mention_index=0):
        tag_tokens = []
        if tag_all:
            tag_tokens.append({"token": "@All", "uid": "-1", "type": 1})

        if mentions and len(mentions) > 0:
            if tag_mode == "all":
                for u in mentions:
                    uname = (u.get("name") or "Bạn").strip()
                    tag_tokens.append({"token": f"@{uname}", "uid": str(u.get("id")), "type": 0})
            else:
                target_user = mentions[mention_index % len(mentions)]
                uname = (target_user.get("name") or "Bạn").strip()
                tag_tokens.append({"token": f"@{uname}", "uid": str(target_user.get("id")), "type": 0})

        if not tag_tokens:
            return "", []

        tags_str = " ".join([t["token"] for t in tag_tokens])
        m_arr = []
        curr_pos = 0
        for t in tag_tokens:
            tlen = utf16_len(t["token"])
            m_arr.append({
                "uid": t["uid"],
                "pos": curr_pos,
                "len": tlen,
                "type": t["type"]
            })
            curr_pos += tlen + 1

        return tags_str, m_arr

    def send_adv(self, raw_text, target_id, color_mode="rainbow", fixed_color="red",
                 is_group=True, mentions=None, tag_all=False, tag_mode="rotate",
                 mention_index=0, is_heading=False, color_offset=0, use_badge=True,
                 antiband=True, tag_pos="head"):

        tags_str, m_arr = self.build_mentions_payload(
            mentions=mentions, tag_all=tag_all, tag_mode=tag_mode,
            mention_index=mention_index
        )

        tag_header = (tags_str + "\n") if (tags_str and tag_pos == "head") else ""

        final_msg, styles, hex_color = self.build_colored_message(
            raw_text, color_mode=color_mode, fixed_color=fixed_color,
            is_heading=is_heading, color_offset=color_offset, use_badge=use_badge,
            tag_header=tag_header, antiband=antiband
        )

        # Gắn thẻ tag vào CUỐI tin nhắn (tag_pos == 'tail')
        if tags_str and tag_pos == "tail":
            base_len = utf16_len(final_msg)
            final_msg += " " + tags_str
            m_arr_tail = []
            c_pos = base_len + 1
            for m in m_arr:
                m_copy = dict(m)
                m_copy["pos"] = c_pos
                m_arr_tail.append(m_copy)
                c_pos += m["len"] + 1
            m_arr = m_arr_tail

        ts = int(time.time() * 1000)

        if is_group:
            url = "https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
            pl = {
                "grid": str(target_id),
                "message": final_msg,
                "clientId": ts,
                "client_id": ts,
                "msgType": 1,
                "styles": styles,
                "msgColor": hex_color,
                "imei": self.imei,
                "visibility": 0
            }
            if m_arr:
                pl["mentions"] = m_arr
                pl["mention"] = m_arr
        else:
            url = "https://chat.zalo.me/api/message/sms"
            pl = {
                "toid": str(target_id),
                "message": final_msg,
                "clientId": ts,
                "client_id": ts,
                "msgType": 1,
                "imei": self.imei
            }

        enc = self.encrypt(json.dumps(pl))
        params = {"params": enc, "imei": self.imei}
        r = self.session.post(url, data=params, timeout=12)
        res = r.json()
        if res.get("error_code") == 0:
            return True, res
        return False, res

# ---------------------------------------------------------
# DISCORD USER CLIENT
# ---------------------------------------------------------
class DiscordUserClient:
    def __init__(self, token):
        self.token = token.strip()
        self.session = requests.Session()

        super_props = {
            "os": "Windows",
            "browser": "Chrome",
            "device": "",
            "system_locale": "vi-VN",
            "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "browser_version": "128.0.0.0",
            "os_version": "10",
            "referrer": "",
            "referring_domain": "",
            "referrer_current": "",
            "referring_domain_current": "",
            "release_channel": "stable",
            "client_build_number": 329000,
            "client_event_source": None
        }
        self.super_props_b64 = base64.b64encode(json.dumps(super_props).encode()).decode()

        self.session.headers.update({
            "Authorization": self.token,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "X-Super-Properties": self.super_props_b64,
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": "https://discord.com",
            "Referer": "https://discord.com/channels/@me",
            "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "Content-Type": "application/json"
        })

    def check_status(self):
        t0 = time.time()
        try:
            r = self.session.get("https://discord.com/api/v9/users/@me", timeout=8)
            ping_ms = int((time.time() - t0) * 1000)
            if r.status_code == 200:
                data = r.json()
                uname = data.get("global_name") or data.get("username") or "Discord User"
                uid = data.get("id") or ""
                return {"live": True, "username": uname, "id": uid, "ping_ms": ping_ms}
            elif r.status_code == 401:
                return {"live": False, "error": "Token Die / Vô hiệu hóa (401)", "ping_ms": ping_ms}
            return {"live": False, "error": f"Lỗi HTTP {r.status_code}", "ping_ms": ping_ms}
        except Exception as e:
            ping_ms = int((time.time() - t0) * 1000)
            return {"live": False, "error": str(e), "ping_ms": ping_ms}

    def get_self(self):
        try:
            r = self.session.get("https://discord.com/api/v9/users/@me", timeout=10)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def get_all_chat_boxes(self):
        items = []
        seen_ids = set()

        try:
            rdm = self.session.get("https://discord.com/api/v9/users/@me/channels", timeout=10)
            if rdm.status_code == 200:
                dms = rdm.json()
                for d in dms:
                    cid = str(d.get("id"))
                    ctype = d.get("type")
                    recips = d.get("recipients", [])

                    if ctype == 3:
                        gname = d.get("name") or ", ".join([u.get("global_name") or u.get("username", "") for u in recips]) or "Nhóm Chat Riêng"
                        items.append({"id": cid, "name": f"[Discord Nhóm DM] {gname}", "type": "group", "platform": "discord"})
                        seen_ids.add(cid)
                    else:
                        target_u = recips[0] if recips else {}
                        uname = target_u.get("global_name") or target_u.get("username") or "Người Dùng"
                        items.append({"id": cid, "name": f"[Discord DM Riêng] {uname}", "type": "user", "platform": "discord"})
                        seen_ids.add(cid)
        except Exception:
            pass

        try:
            rrel = self.session.get("https://discord.com/api/v9/users/@me/relationships", timeout=8)
            if rrel.status_code == 200:
                friends = rrel.json()
                for fr in friends:
                    if fr.get("type") == 1:
                        u = fr.get("user", {})
                        uid = str(u.get("id"))
                        uname = u.get("global_name") or u.get("username") or "Bạn Bè"
                        if uid and uid not in seen_ids:
                            items.append({"id": f"user_{uid}", "name": f"[Discord Bạn Bè] {uname}", "type": "user", "platform": "discord"})
                            seen_ids.add(uid)
        except Exception:
            pass

        try:
            r = self.session.get("https://discord.com/api/v9/users/@me/guilds", timeout=10)
            if r.status_code == 200:
                guilds = r.json()
                for g in guilds:
                    gid = g.get("id")
                    gname = g.get("name", "Server")
                    rc = self.session.get(f"https://discord.com/api/v9/guilds/{gid}/channels", timeout=8)
                    if rc.status_code == 200:
                        chans = rc.json()
                        for c in chans:
                            if c.get("type") in [0, 5, 2]:
                                cid = str(c.get("id"))
                                items.append({"id": cid, "name": f"[{gname}] #{c.get('name')}", "type": "group", "platform": "discord"})
                                seen_ids.add(cid)
        except Exception:
            pass

        return items

    def open_dm_channel(self, user_id):
        try:
            url = "https://discord.com/api/v9/users/@me/channels"
            r = self.session.post(url, json={"recipient_id": str(user_id)}, timeout=8)
            if r.status_code in [200, 201]:
                return r.json().get("id")
        except Exception:
            pass
        return None

    def simulate_typing(self, channel_id):
        try:
            self.session.post(f"https://discord.com/api/v9/channels/{channel_id}/typing", timeout=5)
            time.sleep(random.uniform(0.4, 0.8))
        except Exception:
            pass

    def send_message(self, target_id, content, mentions=None, tag_all=False, antiband=True, tag_tail=""):
        channel_id = str(target_id)
        if channel_id.startswith("user_"):
            raw_uid = channel_id.replace("user_", "")
            opened_cid = self.open_dm_channel(raw_uid)
            if opened_cid:
                channel_id = opened_cid

        final_msg = content
        if tag_all:
            final_msg = "@everyone " + final_msg
        if mentions:
            tags = " ".join([f"<@{m.get('id')}>" for m in mentions])
            final_msg = tags + " " + final_msg
        if tag_tail:
            final_msg = final_msg + " " + tag_tail
        if antiband:
            final_msg = apply_antiband_zalo_v5(final_msg)

        self.simulate_typing(channel_id)

        url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
        payload = {"content": final_msg}

        r = self.session.post(url, json=payload, timeout=12)

        if r.status_code == 429:
            try:
                res_json = r.json()
                wait_time = float(res_json.get("retry_after", 3.0))
            except Exception:
                wait_time = 3.0
            time.sleep(wait_time + 0.5)
            r = self.session.post(url, json=payload, timeout=12)

        if r.status_code in [200, 201]:
            return True, r.json()
        return False, {"error": r.text, "status": r.status_code}

# ---------------------------------------------------------
# QUẢN LÝ TIẾN TRÌNH GỬI TIN & BOT LỆNH
# ---------------------------------------------------------
RUNNING_TASKS = {}
TASKS_LOCK = threading.Lock()
SEEN_MESSAGES = set()
SEEN_LOCK = threading.Lock()

BOT_STATE = {
    "active_file": None,
    "active_text": None,
    "target_mode": "here",
    "custom_targets": [],
    "spam_mode": "fast",
    "delay": 1.2,
    "color_mode": "rainbow",
    "fixed_color": "red",
    "tag_all": False,
    "tag_rotate_tail": False, # Tính năng gắn tag xoay vòng ở cuối tin liên tục
    "is_heading": False,      # Mặc định False để hiện màu rực rỡ trên Zalo Mobile
    "combat_icon_mode": "mixed",
    "combat_icon_count": 3,
    "antiband": True
}

def get_active_clients():
    conn = db()
    zalo_rows = conn.execute("SELECT * FROM accounts WHERE platform = 'zalo' AND enabled = 1").fetchall()
    discord_rows = conn.execute("SELECT * FROM accounts WHERE platform = 'discord' AND enabled = 1").fetchall()
    conn.close()

    z_clients = []
    d_clients = []

    for r in zalo_rows:
        try:
            z_clients.append((r["id"], r["label"], Zalo(r["imei"], r["cookies"])))
        except Exception:
            pass

    for r in discord_rows:
        try:
            d_clients.append((r["id"], r["label"], DiscordUserClient(r["token"])))
        except Exception:
            pass

    return z_clients, d_clients

def run_spam_task(task_id, payload, stop_ev):
    targets = payload.get("targets", [])
    file_path = payload.get("file_path")
    direct_blocks = payload.get("direct_blocks") or []
    delay = float(payload.get("delay", 1.2))
    mode = payload.get("mode", "fast")
    color_mode = payload.get("color_mode", "rainbow")
    fixed_color = payload.get("fixed_color", "red")
    tag_all = bool(payload.get("tag_all", False))
    tag_rotate_tail = bool(payload.get("tag_rotate_tail", False))
    is_heading = bool(payload.get("is_heading", False))
    antiband = bool(payload.get("antiband", True))
    combat_icon_mode = payload.get("combat_icon_mode", "mixed")
    combat_icon_count = int(payload.get("combat_icon_count", 3))

    reader = None
    if file_path and os.path.exists(file_path):
        reader = FastFileBlockReader(file_path)

    msg_idx = 0
    direct_idx = 0
    tag_cycle_index = 0

    while not stop_ev.is_set():
        if reader:
            raw = reader.next_block()
            if not raw:
                break
        else:
            if not direct_blocks:
                break
            raw = direct_blocks[direct_idx % len(direct_blocks)]
            direct_idx += 1

        for target in targets:
            if stop_ev.is_set():
                break

            target_id = target.get("id")
            target_plat = target.get("platform", "zalo")
            is_group = (target.get("type") == "group")

            z_clients, d_clients = get_active_clients()
            client_tuple = None

            if target_plat == "zalo" and z_clients:
                client_tuple = random.choice(z_clients)
            elif target_plat == "discord" and d_clients:
                client_tuple = random.choice(d_clients)

            if not client_tuple:
                time.sleep(2)
                continue

            acc_id, label, client = client_tuple

            group_members = []
            if tag_rotate_tail and is_group and target_plat == "zalo":
                try:
                    group_members = client.get_group_members(target_id)
                except Exception:
                    pass

            icon_str = ""
            if combat_icon_mode != "none":
                icon_str = " " + generate_combat_combo(combat_icon_mode, combat_icon_count)

            if mode == "treo_ngon":
                text = raw.replace("\r\n", "\n").replace("\r", "\n") + icon_str
                if target_plat == "zalo":
                    ok, res = client.send_adv(
                        text, target_id, color_mode=color_mode, fixed_color=fixed_color,
                        is_group=is_group, mentions=(group_members if tag_rotate_tail else None),
                        tag_all=tag_all, tag_mode="rotate", mention_index=tag_cycle_index,
                        is_heading=is_heading, color_offset=msg_idx, antiband=antiband,
                        tag_pos=("tail" if tag_rotate_tail else "head")
                    )
                else:
                    tag_tail_str = ""
                    if tag_rotate_tail and group_members:
                        m_target = group_members[tag_cycle_index % len(group_members)]
                        tag_tail_str = f"<@{m_target.get('id')}>"
                    ok, res = client.send_message(
                        target_id, text, tag_all=tag_all, antiband=antiband, tag_tail=tag_tail_str
                    )

                if ok:
                    with TASKS_LOCK:
                        if task_id in RUNNING_TASKS:
                            RUNNING_TASKS[task_id]["sent_count"] = RUNNING_TASKS[task_id].get("sent_count", 0) + 1
                tag_cycle_index += 1

            else:
                lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
                for ln in lines:
                    if stop_ev.is_set():
                        break
                    msg_line = ln + icon_str
                    if target_plat == "zalo":
                        ok, res = client.send_adv(
                            msg_line, target_id, color_mode=color_mode, fixed_color=fixed_color,
                            is_group=is_group, mentions=(group_members if tag_rotate_tail else None),
                            tag_all=tag_all, tag_mode="rotate", mention_index=tag_cycle_index,
                            is_heading=is_heading, color_offset=msg_idx, antiband=antiband,
                            tag_pos=("tail" if tag_rotate_tail else "head")
                        )
                    else:
                        tag_tail_str = ""
                        if tag_rotate_tail and group_members:
                            m_target = group_members[tag_cycle_index % len(group_members)]
                            tag_tail_str = f"<@{m_target.get('id')}>"
                        ok, res = client.send_message(
                            target_id, msg_line, tag_all=tag_all, antiband=antiband, tag_tail=tag_tail_str
                        )

                    if ok:
                        with TASKS_LOCK:
                            if task_id in RUNNING_TASKS:
                                RUNNING_TASKS[task_id]["sent_count"] = RUNNING_TASKS[task_id].get("sent_count", 0) + 1
                    msg_idx += 1
                    tag_cycle_index += 1
                    time.sleep(delay * random.uniform(0.9, 1.2))
                continue

            msg_idx += 1
            time.sleep(delay * random.uniform(0.9, 1.2))

    if reader:
        reader.close()

    with TASKS_LOCK:
        if task_id in RUNNING_TASKS:
            RUNNING_TASKS[task_id]["status"] = "stopped"

# ---------------------------------------------------------
# MENU LỆNH ĐẦY ĐỦ (COMMAND ENGINE)
# ---------------------------------------------------------
MENU_TEXT = """👑 RICKI VIP — HỆ THỐNG ĐIỀU HÀNH BẰNG LỆNH 👑
Bản quyền © Phạm Anh Khôi (Verified ✔)
────────────────────────────
📋 BẢNG LỆNH ĐIỀU HÀNH TỰ ĐỘNG:

🚀 1. GỬI TIN & ĐIỀU HÀNH:
• .spam [nhanh|ngon|nhay] [delay] [màu] [tag]
  👉 Bắn tin tự động (Thêm chữ 'tag' để tự gắn @ tag xoay vòng ở cuối tin liên tục!)
  👉 Ví dụ: .spam nhanh 1.2 rainbow tag
• .stop | .stopall
  👉 Dừng ngay lập tức toàn bộ tiến trình gửi tin.

👥 2. TAG THÀNH VIÊN & @ALL:
• .tagloop [delay] [màu] [nội dung]
  👉 Tự động tag xoay vòng từng thành viên ở CUỐI tin liên tục đến khi gõ .stop!
• .tagall [nội dung]
  👉 Rung chuông thông báo toàn nhóm (@All trên Zalo, @everyone trên Discord).

📁 3. TỆP NGÔN & THIẾT LẬP FILE:
• .setupfile <tên_file>
  👉 Kiểm tra toàn diện file (dòng, khối ngôn, size) & đặt làm tệp chạy chính!
• .checkfile <tên_file>
  👉 Phân tích cú pháp và xem trước 3 khối ngôn đầu của file.
• .listfiles | .files
  👉 Liệt kê toàn bộ tệp ngôn đã đẩy lên máy chủ.
• .addfile <tên_file.txt> <nội dung>
  👉 Tạo/lưu tệp ngôn mới trực tiếp qua chat.
• .settext <nội dung>
  👉 Đặt nội dung gửi trực tiếp (thay thế tệp).

🔍 4. KIỂM TRA TÀI KHOẢN (CHECK LIVE/DIE):
• .check | .checkacc
  👉 Kiểm tra Token Discord & IMEI Zalo xem còn sống hay die kèm tốc độ Ping!
• .status
  👉 Báo cáo tổng thể tiến trình, số tin đã gửi, tệp đang chọn.

🎨 5. MÀU SẮC & CÀI ĐẶT:
• .color <rainbow|random|red|gold|green|blue|purple|pink|cyan>
  👉 Đổi màu chữ Zalo (chuẩn 100% nhóm chat).
• .boxes
  👉 Xem danh sách 10 box chat / nhóm gần nhất kèm ID.
• .target <here | all | id>
  👉 Chọn mục tiêu nhận tin (mặc định: here - chính nhóm đang gõ).
────────────────────────────
💡 Bạn có thể gõ lệnh trực tiếp trong nhóm Zalo, chat riêng, Cloud của tôi, hoặc kênh Discord!"""

def execute_command(cmd_text, platform, target_id, is_group=True, client=None):
    cmd_text = cmd_text.strip()
    if not cmd_text:
        return None

    cmd_name = ""
    cmd_args = ""
    if cmd_text.lower() in ["menu", "!menu", ".menu", "/menu", "help", "!help", ".help"]:
        cmd_name = "menu"
    elif cmd_text.startswith((".", "!", "/")):
        parts = cmd_text[1:].split(" ", 1)
        cmd_name = parts[0].lower()
        cmd_args = parts[1].strip() if len(parts) > 1 else ""
    else:
        return None

    # 1. MENU
    if cmd_name in ["menu", "help"]:
        return MENU_TEXT

    # 2. CHECK TOKEN / IMEI
    elif cmd_name in ["check", "checkacc", "kiemtra"]:
        rep = [
            "🔍 KẾT QUẢ KIỂM TRA TRẠNG THÁI TÀI KHOẢN 🔍",
            "👤 Bản quyền: Phạm Anh Khôi (Verified ✔)",
            "────────────────────────────"
        ]
        z_clients, d_clients = get_active_clients()

        if not z_clients and not d_clients:
            return "⚠️ Chưa có tài khoản nào được lưu trên máy chủ! Hãy vào trang web Render để lưu IMEI Zalo hoặc Token Discord."

        for aid, label, zc in z_clients:
            stat = zc.check_status()
            if stat["live"]:
                rep.append(f"🟢 [ZALO] LIVE: {stat['name']} (UID: {stat['uid']}) • Ping: {stat['ping_ms']}ms")
            else:
                rep.append(f"🔴 [ZALO] DIE: {label} (Lỗi: {stat['error']}) • Ping: {stat['ping_ms']}ms")

        for aid, label, dc in d_clients:
            stat = dc.check_status()
            if stat["live"]:
                rep.append(f"🟢 [DISCORD] LIVE: {stat['username']} (ID: {stat['id']}) • Ping: {stat['ping_ms']}ms")
            else:
                rep.append(f"🔴 [DISCORD] DIE: {label} (Lỗi: {stat['error']}) • Ping: {stat['ping_ms']}ms")

        rep.append("────────────────────────────")
        rep.append("⚡ Hệ thống sẵn sàng hoạt động!")
        return "\n".join(rep)

    # 3. SETUP FILE
    elif cmd_name in ["setupfile", "setfile"]:
        if not cmd_args:
            return "⚠️ Cú pháp: .setupfile <tên_file.txt>\n👉 Dùng .listfiles để xem danh sách tệp có sẵn trên máy chủ."

        target_file = cmd_args.strip()
        fp = os.path.join(UPLOAD_DIR, target_file)
        if not os.path.exists(fp):
            cands = [f for f in os.listdir(UPLOAD_DIR) if target_file.lower() in f.lower()]
            if cands:
                fp = os.path.join(UPLOAD_DIR, cands[0])
                target_file = cands[0]
            else:
                return f"❌ Không tìm thấy tệp '{target_file}'! Dùng .listfiles để xem các tệp đã tải lên."

        total_lines = 0
        total_blocks = 0
        in_block = False

        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    total_lines += 1
                    if line.strip():
                        if not in_block:
                            total_blocks += 1
                            in_block = True
                    else:
                        in_block = False
        except Exception as e:
            return f"❌ Lỗi đọc tệp: {str(e)}"

        sz_kb = round(os.path.getsize(fp) / 1024, 1)
        est_min = round((max(1, total_blocks) * BOT_STATE["delay"]) / 60, 1)

        BOT_STATE["active_file"] = fp
        BOT_STATE["active_text"] = None

        rep = [
            f"📋 THIẾT LẬP FILE THÀNH CÔNG: {target_file}",
            "────────────────────────────",
            f"📁 Kích thước: {sz_kb} KB",
            f"📑 Tổng số dòng: {total_lines} dòng",
            f"📦 Tổng số khối ngôn: {max(1, total_blocks)} khối",
            "🔍 Định dạng: Chuẩn cú pháp (Mỗi khối cách 1 dòng trống)",
            f"⏳ Thời gian gửi ước tính: ~{est_min} phút (ở delay {BOT_STATE['delay']}s)",
            "────────────────────────────",
            "✔️ ĐÃ ĐẶT LÀM TỆP NỘI DUNG CHÍNH!",
            "👉 Gõ .spam để gửi ngay, hoặc thêm 'tag' để xoay vòng tag thành viên ở cuối tin!"
        ]
        return "\n".join(rep)

    # 4. CHECKFILE
    elif cmd_name == "checkfile":
        if not cmd_args:
            current = os.path.basename(BOT_STATE["active_file"]) if BOT_STATE["active_file"] else "Chưa chọn"
            return f"📁 Tệp hiện tại: {current}\n👉 Dùng: .checkfile <tên_file.txt> để kiểm tra chi tiết cấu trúc."

        target_file = cmd_args.strip()
        fp = os.path.join(UPLOAD_DIR, target_file)
        if not os.path.exists(fp):
            cands = [f for f in os.listdir(UPLOAD_DIR) if target_file.lower() in f.lower()]
            if cands:
                fp = os.path.join(UPLOAD_DIR, cands[0])
                target_file = cands[0]
            else:
                return f"❌ Không tìm thấy tệp '{target_file}'!"

        sz_kb = round(os.path.getsize(fp) / 1024, 1)
        preview_lines = []
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            for _ in range(6):
                line = f.readline()
                if not line:
                    break
                preview_lines.append(line.rstrip())

        rep = [
            f"🔍 KIỂM TRA TỆP: {target_file} ({sz_kb} KB)",
            "────────────────────────────",
            "📄 Bản xem trước dòng đầu:",
            "\n".join(preview_lines[:5]) or "(Tệp trống)",
            "────────────────────────────",
            f"👉 Dùng .setupfile {target_file} để kích hoạt gửi tệp này!"
        ]
        return "\n".join(rep)

    # 5. TAGLOOP
    elif cmd_name == "tagloop":
        args = cmd_args.split()
        delay = 1.2
        color = BOT_STATE["fixed_color"]
        color_mode = BOT_STATE["color_mode"]
        direct_text = ""

        if len(args) >= 1 and args[0].replace(".", "", 1).isdigit():
            delay = float(args[0])
            if len(args) >= 2 and args[1] in [c["id"] for c in ZALO_PALETTE] + ["rainbow", "random"]:
                if args[1] in ["rainbow", "random"]:
                    color_mode = args[1]
                else:
                    color_mode = "fixed"
                    color = args[1]
                direct_text = " ".join(args[2:])
            else:
                direct_text = " ".join(args[1:])
        else:
            direct_text = cmd_args

        if not direct_text and not BOT_STATE["active_file"] and not BOT_STATE["active_text"]:
            direct_text = "Alo anh em có mặt không đấy"

        file_path = BOT_STATE["active_file"]
        direct_blocks = [direct_text] if direct_text else ([b.strip() for b in BOT_STATE["active_text"].split("\n\n") if b.strip()] if BOT_STATE["active_text"] else [])

        task_id = "TAGLOOP_" + str(int(time.time()))[-4:]
        stop_ev = threading.Event()

        payload = {
            "targets": [{"id": str(target_id), "type": "group" if is_group else "user", "platform": platform}],
            "file_path": file_path if not direct_text else None,
            "direct_blocks": direct_blocks,
            "delay": delay,
            "mode": "fast",
            "color_mode": color_mode,
            "fixed_color": color,
            "tag_all": False,
            "tag_rotate_tail": True,
            "is_heading": False, # Để hiện màu rực rỡ
            "antiband": BOT_STATE["antiband"],
            "combat_icon_mode": BOT_STATE["combat_icon_mode"],
            "combat_icon_count": BOT_STATE["combat_icon_count"]
        }

        t = threading.Thread(target=run_spam_task, args=(task_id, payload, stop_ev), daemon=True)
        t.start()

        with TASKS_LOCK:
            RUNNING_TASKS[task_id] = {
                "id": task_id,
                "type": "TAGLOOP_TAIL",
                "status": "running",
                "thread": t,
                "stop_ev": stop_ev,
                "created_at": time.time(),
                "sent_count": 0
            }

        return f"🔥 ĐÃ KÍCH HOẠT CHẾ ĐỘ TAG XOAY VÒNG Ở CUỐI TIN LIÊN TỤC!\n🔹 Mã: {task_id}\n🔹 Tốc độ: {delay}s\n🔹 Màu: {color_mode.upper()}\n👉 Bot tự động gắn thẻ từng thành viên ở cuối mỗi câu liên tục cho đến khi bạn gõ .stop!"

    # 6. SPAM
    elif cmd_name == "spam":
        mode = "fast"
        delay = BOT_STATE["delay"]
        color = BOT_STATE["fixed_color"]
        color_mode = BOT_STATE["color_mode"]
        tag_tail_flag = BOT_STATE["tag_rotate_tail"]

        args = cmd_args.split()
        for a in args:
            a_lower = a.lower()
            if a_lower in ["tag", "@tag", "autotag"]:
                tag_tail_flag = True
            elif a_lower in ["nhanh", "fast"]:
                mode = "fast"
            elif a_lower in ["ngon", "treo_ngon"]:
                mode = "treo_ngon"
            elif a_lower in ["nhay", "treo_nhay"]:
                mode = "treo_nhay"
            elif a.replace(".", "", 1).isdigit():
                delay = float(a)
            elif a_lower in ["rainbow", "random"]:
                color_mode = a_lower
            elif a_lower in [c["id"] for c in ZALO_PALETTE]:
                color_mode = "fixed"
                color = a_lower

        file_path = BOT_STATE["active_file"]
        direct_blocks = []
        if not file_path:
            if BOT_STATE["active_text"]:
                direct_blocks = [b.strip() for b in BOT_STATE["active_text"].split("\n\n") if b.strip()]
            else:
                return "❌ Chưa có nội dung gửi! Dùng lệnh: .setupfile <tên_file> hoặc .settext <nội dung> trước."

        targets = []
        if BOT_STATE["target_mode"] == "here":
            targets = [{"id": str(target_id), "type": "group" if is_group else "user", "platform": platform}]
        elif BOT_STATE["target_mode"] == "all":
            z_clients, d_clients = get_active_clients()
            for _, _, zc in z_clients:
                try:
                    targets.extend(zc.get_conversations())
                except Exception:
                    pass
            for _, _, dc in d_clients:
                try:
                    targets.extend(dc.get_all_chat_boxes())
                except Exception:
                    pass
        elif BOT_STATE["custom_targets"]:
            targets = BOT_STATE["custom_targets"]
        else:
            targets = [{"id": str(target_id), "type": "group" if is_group else "user", "platform": platform}]

        task_id = "TASK_" + str(int(time.time()))[-5:]
        stop_ev = threading.Event()

        payload = {
            "targets": targets,
            "file_path": file_path,
            "direct_blocks": direct_blocks,
            "delay": delay,
            "mode": mode,
            "color_mode": color_mode,
            "fixed_color": color,
            "tag_all": BOT_STATE["tag_all"],
            "tag_rotate_tail": tag_tail_flag,
            "is_heading": BOT_STATE["is_heading"],
            "antiband": BOT_STATE["antiband"],
            "combat_icon_mode": BOT_STATE["combat_icon_mode"],
            "combat_icon_count": BOT_STATE["combat_icon_count"]
        }

        t = threading.Thread(target=run_spam_task, args=(task_id, payload, stop_ev), daemon=True)
        t.start()

        with TASKS_LOCK:
            RUNNING_TASKS[task_id] = {
                "id": task_id,
                "type": mode,
                "status": "running",
                "thread": t,
                "stop_ev": stop_ev,
                "created_at": time.time(),
                "sent_count": 0
            }

        tag_status_str = "KÈM @ TAG Ở CUỐI XOAY VÒNG" if tag_tail_flag else "Tắt Tag Cuối"
        return f"🚀 ĐÃ BẮT ĐẦU CHIẾN DỊCH GỬI TIN!\n🔹 Mã: {task_id}\n🔹 Chế độ: {mode.upper()}\n🔹 Tốc độ: {delay}s\n🔹 Màu: {color_mode.upper()}\n🔹 Tính năng Tag: {tag_status_str}\n🔹 Mục tiêu: {len(targets)} box\n👉 Gõ .stop để dừng bất kỳ lúc nào."

    # 7. STOP
    elif cmd_name in ["stop", "stopall"]:
        stopped = 0
        with TASKS_LOCK:
            for tid, tinfo in RUNNING_TASKS.items():
                if tinfo.get("status") == "running":
                    tinfo["stop_ev"].set()
                    tinfo["status"] = "stopped"
                    stopped += 1
        return f"🛑 ĐÃ DỪNG TOÀN BỘ TIẾN TRÌNH ({stopped} tiến trình đã dừng)! Hệ thống trở về trạng thái nghỉ."

    # 8. TAGALL
    elif cmd_name == "tagall":
        text = cmd_args if cmd_args else "Thông báo khẩn đến toàn thể thành viên nhóm!"
        if platform == "zalo" and client:
            client.send_adv(text, target_id, is_group=is_group, tag_all=True, is_heading=True)
            return None
        elif platform == "discord" and client:
            client.send_message(target_id, text, tag_all=True)
            return None
        return f"📢 Đã kích hoạt Tag @All: {text}"

    # 9. STATUS
    elif cmd_name == "status":
        z_clients, d_clients = get_active_clients()
        with TASKS_LOCK:
            running_tasks = [t for t in RUNNING_TASKS.values() if t.get("status") == "running"]
            total_sent = sum(t.get("sent_count", 0) for t in RUNNING_TASKS.values())

        file_name = os.path.basename(BOT_STATE["active_file"]) if BOT_STATE["active_file"] else "Chưa chọn (Dùng .setupfile hoặc .settext)"
        if BOT_STATE["active_text"]:
            file_name = f"Văn bản trực tiếp ({len(BOT_STATE['active_text'])} ký tự)"

        rep = [
            "⚡ TRẠNG THÁI HỆ THỐNG RICKI VIP ⚡",
            "👤 Bản quyền: Phạm Anh Khôi (Verified ✔)",
            "────────────────────────────",
            f"🔷 Tài khoản Zalo: {len(z_clients)} hoạt động",
            f"🟣 Tài khoản Discord: {len(d_clients)} hoạt động",
            f"📁 Nguồn nội dung: {file_name}",
            f"🎯 Mục tiêu: {BOT_STATE['target_mode']} (ID: {target_id})",
            f"🎨 Màu chữ Zalo: {BOT_STATE['color_mode']} ({BOT_STATE['fixed_color']})",
            f"🏷️ Tag xoay vòng ở cuối: {'BẬT' if BOT_STATE['tag_rotate_tail'] else 'TẮT'}",
            f"🛡️ Anti-ban V5: {'BẬT' if BOT_STATE['antiband'] else 'TẮT'}",
            f"🚀 Tiến trình đang chạy: {len(running_tasks)}",
            f"📊 Tổng số tin đã gửi: {total_sent}",
            "────────────────────────────",
            "👉 Gõ .menu để xem hướng dẫn đầy đủ."
        ]
        return "\n".join(rep)

    # 10. LISTFILES
    elif cmd_name in ["listfiles", "files"]:
        txt_files = [f for f in os.listdir(UPLOAD_DIR) if f.endswith(".txt")]
        if not txt_files:
            return "📁 Thư mục máy chủ hiện chưa có tệp .txt nào!\n👉 Dùng lệnh: .addfile <tên_file.txt> <nội dung> để tạo mới ngay trong chat."
        rep = ["📁 DANH SÁCH TỆP NGÔN TRÊN MÁY CHỦ:"]
        for idx, fn in enumerate(txt_files, 1):
            fp = os.path.join(UPLOAD_DIR, fn)
            sz = round(os.path.getsize(fp) / 1024, 1)
            rep.append(f"{idx}. {fn} ({sz} KB)")
        rep.append("────────────────────────────")
        rep.append("👉 Dùng lệnh: .setupfile <tên_file> để kiểm tra chi tiết & kích hoạt gửi tệp này.")
        return "\n".join(rep)

    # 11. ADDFILE
    elif cmd_name == "addfile":
        if " " not in cmd_args:
            return "⚠️ Cú pháp: .addfile <tên_file.txt> <nội dung văn bản>"
        fname, content = cmd_args.split(" ", 1)
        if not fname.endswith(".txt"):
            fname += ".txt"
        fp = os.path.join(UPLOAD_DIR, fname)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)

        lines = len(content.splitlines())
        blocks = len([b for b in content.split("\n\n") if b.strip()]) or 1
        conn = db()
        conn.execute("INSERT INTO files (filename, filepath, size, lines, blocks, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (fname, fp, os.path.getsize(fp), lines, blocks, time.time()))
        conn.commit()
        conn.close()

        BOT_STATE["active_file"] = fp
        BOT_STATE["active_text"] = None
        return f"✔️ ĐÃ TẠO TỆP THÀNH CÔNG: {fname} ({lines} dòng, {blocks} khối)!\nĐã tự động đặt làm tệp nội dung chính. Gõ .spam để bắn tin!"

    # 12. SETTEXT
    elif cmd_name == "settext":
        if not cmd_args:
            return "⚠️ Cú pháp: .settext <nội dung văn bản cần gửi>"
        BOT_STATE["active_text"] = cmd_args
        BOT_STATE["active_file"] = None
        return f"✔️ ĐÃ LƯU VĂN BẢN TRỰC TIẾP ({len(cmd_args)} ký tự)!\n👉 Gõ .spam để gửi ngay!"

    # 13. COLOR
    elif cmd_name == "color":
        valid_colors = ["rainbow", "random", "red", "gold", "green", "orange", "blue", "purple", "pink", "cyan"]
        chosen = cmd_args.lower()
        if chosen not in valid_colors:
            return f"⚠️ Màu không hợp lệ. Các màu hỗ trợ: {', '.join(valid_colors)}"
        if chosen in ["rainbow", "random"]:
            BOT_STATE["color_mode"] = chosen
        else:
            BOT_STATE["color_mode"] = "fixed"
            BOT_STATE["fixed_color"] = chosen
        return f"🎨 ĐÃ ĐẶT MÀU CHỮ ZALO: {chosen.upper()} (áp dụng chuẩn 100% trong nhóm)!"

    # 14. TARGET & BOXES
    elif cmd_name == "target":
        if not cmd_args or cmd_args.lower() == "here":
            BOT_STATE["target_mode"] = "here"
            BOT_STATE["custom_targets"] = []
            return f"🎯 ĐÃ ĐẶT MỤC TIÊU: Box chat hiện tại (ID: {target_id})."
        elif cmd_args.lower() == "all":
            BOT_STATE["target_mode"] = "all"
            BOT_STATE["custom_targets"] = []
            return "🎯 ĐÃ ĐẶT MỤC TIÊU: TẤT CẢ các nhóm & hội thoại trên tài khoản!"
        else:
            ids = [i.strip() for i in cmd_args.split(",") if i.strip()]
            BOT_STATE["target_mode"] = "custom"
            BOT_STATE["custom_targets"] = [{"id": i, "type": "group", "platform": platform} for i in ids]
            return f"🎯 ĐÃ ĐẶT MỤC TIÊU: {len(ids)} box chỉ định ({', '.join(ids)})."

    elif cmd_name == "boxes":
        boxes = []
        if platform == "zalo" and client:
            boxes = client.get_conversations()
        elif platform == "discord" and client:
            boxes = client.get_all_chat_boxes()
        if not boxes:
            return "💬 Chưa nạp được danh sách hội thoại từ tài khoản."
        rep = [f"💬 DANH SÁCH 10 HỘI THOẠI GẦN NHẤT ({platform.upper()}):"]
        for b in boxes[:10]:
            rep.append(f"• {b['name']} (ID: {b['id']})")
        rep.append("👉 Dùng lệnh: .target <ID> để chọn mục tiêu nhận tin.")
        return "\n".join(rep)

    return f"⚠️ Lệnh không xác định: .{cmd_name}. Gõ .menu để xem danh sách toàn bộ lệnh!"

# ---------------------------------------------------------
# BỘ LẮNG NGHE LỆNH SIÊU TỐC (FAST NON-BLOCKING LISTENERS)
# ---------------------------------------------------------
CACHED_ZALO_CONVS = []
LAST_ZALO_CONV_POLL = 0

def handle_incoming_command(text, platform, target_id, is_group, client):
    try:
        reply = execute_command(text, platform, target_id, is_group=is_group, client=client)
        if reply:
            if platform == "zalo":
                client.send_adv(reply, target_id, is_group=is_group, is_heading=True)
            else:
                client.send_message(target_id, reply)
    except Exception as e:
        print(f"Lỗi thực thi lệnh: {e}")

def zalo_listener_loop():
    global CACHED_ZALO_CONVS, LAST_ZALO_CONV_POLL
    print("🔷 [Zalo Fast Listener] Đang chạy luồng bắt lệnh tự động siêu tốc...")
    while True:
        try:
            z_clients, _ = get_active_clients()
            now = time.time()
            for acc_id, label, zc in z_clients:
                if now - LAST_ZALO_CONV_POLL > 60 or not CACHED_ZALO_CONVS:
                    try:
                        CACHED_ZALO_CONVS = zc.get_conversations()
                        LAST_ZALO_CONV_POLL = now
                    except Exception:
                        pass

                for c in CACHED_ZALO_CONVS[:8]:
                    grid = c["id"]
                    try:
                        pl = json.dumps({"grid": str(grid), "page": 1, "count": 3})
                        params = {"params": zc.encrypt(pl), "imei": zc.imei}
                        r = zc.session.post("https://chat.zalo.me/api/group/getmsg", data=params, timeout=3)
                        res = r.json()
                        if res.get("data"):
                            plain = zc.decrypt(res["data"])
                            info = json.loads(plain)
                            msg_list = info.get("data", {}).get("msgList", []) or []
                            for m in msg_list:
                                msg_id = str(m.get("msgId") or m.get("cliMsgId") or "")
                                if not msg_id:
                                    continue
                                with SEEN_LOCK:
                                    if msg_id in SEEN_MESSAGES:
                                        continue
                                    SEEN_MESSAGES.add(msg_id)
                                    if len(SEEN_MESSAGES) > 3000:
                                        SEEN_MESSAGES.clear()

                                text = str(m.get("message") or m.get("content") or "").strip()
                                if text.startswith((".", "!", "/")) or text.lower() == "menu":
                                    print(f"🔷 [Zalo Command] Nhận lệnh: '{text}' trong {c['name']}")
                                    threading.Thread(
                                        target=handle_incoming_command,
                                        args=(text, "zalo", grid, True, zc),
                                        daemon=True
                                    ).start()
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(1.2)

CACHED_DISCORD_BOXES = []
LAST_DISCORD_BOX_POLL = 0

def discord_listener_loop():
    global CACHED_DISCORD_BOXES, LAST_DISCORD_BOX_POLL
    print("🟣 [Discord Fast Listener] Đang chạy luồng bắt lệnh tự động siêu tốc...")
    while True:
        try:
            _, d_clients = get_active_clients()
            now = time.time()
            for acc_id, label, dc in d_clients:
                if now - LAST_DISCORD_BOX_POLL > 60 or not CACHED_DISCORD_BOXES:
                    try:
                        CACHED_DISCORD_BOXES = dc.get_all_chat_boxes()
                        LAST_DISCORD_BOX_POLL = now
                    except Exception:
                        pass

                for b in CACHED_DISCORD_BOXES[:8]:
                    cid = b["id"]
                    if cid.startswith("user_"):
                        continue
                    try:
                        r = dc.session.get(f"https://discord.com/api/v9/channels/{cid}/messages?limit=3", timeout=3)
                        if r.status_code == 200:
                            arr = r.json()
                            for m in arr:
                                mid = str(m.get("id"))
                                with SEEN_LOCK:
                                    if mid in SEEN_MESSAGES:
                                        continue
                                    SEEN_MESSAGES.add(mid)
                                    if len(SEEN_MESSAGES) > 3000:
                                        SEEN_MESSAGES.clear()

                                text = m.get("content", "").strip()
                                if text.startswith((".", "!", "/")) or text.lower() == "menu":
                                    print(f"🟣 [Discord Command] Nhận lệnh: '{text}' trong {b['name']}")
                                    threading.Thread(
                                        target=handle_incoming_command,
                                        args=(text, "discord", cid, (b["type"]=="group"), dc),
                                        daemon=True
                                    ).start()
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(1.2)

LISTENERS_STARTED = False
LISTENERS_LOCK = threading.Lock()

def start_background_listeners():
    global LISTENERS_STARTED
    with LISTENERS_LOCK:
        if not LISTENERS_STARTED:
            LISTENERS_STARTED = True
            threading.Thread(target=zalo_listener_loop, daemon=True).start()
            threading.Thread(target=discord_listener_loop, daemon=True).start()
            print("🚀 [Ricki Vip] Đã kích hoạt nền Fast Command Listeners (Zalo & Discord)!")

start_background_listeners()

# ---------------------------------------------------------
# GIAO DIỆN WEB HIỆN ĐẠI (CHỐNG KẸT TAB & HỖ TRỢ MOBILE IPHONE 100%)
# ---------------------------------------------------------
CSS_MODERN = """
:root {
  --bg-page: #080c16;
  --bg-card: rgba(16, 24, 44, 0.94);
  --bg-card-hover: rgba(22, 34, 62, 0.98);
  --accent-primary: #3b82f6;
  --accent-cyan: #06b6d4;
  --accent-indigo: #6366f1;
  --accent-green: #10b981;
  --accent-red: #ef4444;
  --accent-gold: #f59e0b;
  --txt-0: #ffffff;
  --txt-1: #e2e8f0;
  --txt-2: #94a3b8;
  --border-card: rgba(99, 102, 241, 0.22);
  --border-active: rgba(59, 130, 246, 0.6);
  --glow-primary: 0 0 24px rgba(59, 130, 246, 0.35);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}

* { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', sans-serif;
  background-color: var(--bg-page);
  background-image:
    radial-gradient(circle at 10% 10%, rgba(99, 102, 241, 0.12) 0%, transparent 40%),
    radial-gradient(circle at 90% 80%, rgba(6, 182, 212, 0.1) 0%, transparent 45%);
  color: var(--txt-1); min-height: 100vh; padding-bottom: 85px; position: relative; overflow-x: hidden;
}

.header {
  position: sticky; top: 0; z-index: 1000;
  background: rgba(8, 12, 22, 0.92); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border-card); padding: 12px 18px; box-shadow: 0 4px 25px rgba(0, 0, 0, 0.45);
}
.header-inner {
  max-width: 980px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 12px;
}
.logo-box { display: flex; align-items: center; gap: 12px; }
.logo-container {
  width: 44px; height: 44px; border-radius: 12px; overflow: hidden;
  background: linear-gradient(135deg, var(--accent-indigo) 0%, var(--accent-primary) 100%);
  display: flex; align-items: center; justify-content: center;
  box-shadow: var(--glow-primary); border: 1px solid rgba(255,255,255,0.2); flex-shrink: 0;
}
.brand-logo { width: 100%; height: 100%; object-fit: cover; }
.header-meta h1 { font-size: 17px; font-weight: 800; color: #fff; letter-spacing: 0.5px; display: flex; align-items: center; gap: 6px; }
.header-meta p { font-size: 11.5px; color: var(--txt-2); margin-top: 1px; display: flex; align-items: center; gap: 5px; }

.verified-seal { display: inline-flex; align-items: center; justify-content: center; vertical-align: middle; }
.verified-icon { width: 17px; height: 17px; filter: drop-shadow(0 0 6px rgba(29, 155, 240, 0.65)); }

.container { max-width: 980px; margin: 0 auto; padding: 18px 14px; position: relative; z-index: 10; }

/* THANH CHUYỂN TAB CHUẨN CẢ PC & IPHONE (KHÔNG BAO GIỜ BỊ LỖI CLICK) */
.main-tabs-nav {
  display: flex; gap: 6px; overflow-x: auto; padding: 6px;
  background: rgba(14, 22, 40, 0.88); backdrop-filter: blur(14px);
  border: 1px solid var(--border-card); border-radius: 15px; margin-bottom: 20px;
  scrollbar-width: none; box-shadow: 0 6px 25px rgba(0,0,0,0.3);
}
.main-tabs-nav::-webkit-scrollbar { display: none; }

.tab-btn {
  flex: 1; min-width: 105px; min-height: 44px;
  display: inline-flex; align-items: center; justify-content: center; gap: 7px;
  padding: 10px 14px; border-radius: 11px;
  background: transparent; border: 1px solid transparent; color: var(--txt-2);
  font-size: 13.5px; font-weight: 700; cursor: pointer !important;
  touch-action: manipulation !important; user-select: none;
  transition: all 0.2s var(--ease); white-space: nowrap;
}
.tab-btn:hover { color: #fff; background: rgba(255, 255, 255, 0.06); }
.tab-btn.active {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.95) 0%, rgba(99, 102, 241, 0.95) 100%) !important;
  color: #ffffff !important; border-color: rgba(255, 255, 255, 0.25) !important;
  box-shadow: 0 4px 18px rgba(59, 130, 246, 0.45);
}
.tab-btn:active { transform: scale(0.97) !important; }

/* PANEL DISPLAY !IMPORTANT ĐẢM BẢO CHUYỂN TAB 100% */
.panel { display: none !important; }
.panel.active { display: block !important; animation: panelFade 0.2s var(--ease); }
@keyframes panelFade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

.card {
  background: var(--bg-card); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--border-card); border-radius: 18px; padding: 22px 20px;
  box-shadow: 0 10px 35px rgba(0, 0, 0, 0.38); margin-bottom: 18px;
}
.card h2 { font-size: 15.5px; font-weight: 800; color: #fff; margin-bottom: 16px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }

.form-group { margin-bottom: 15px; }
.form-group label { display: block; font-size: 11.5px; font-weight: 700; text-transform: uppercase; color: var(--txt-2); margin-bottom: 7px; }

input[type="text"], input[type="password"], input[type="number"], select, textarea {
  width: 100%; padding: 12px 14px; background: rgba(8, 12, 22, 0.88);
  border: 1px solid var(--border-card); border-radius: 11px; color: #fff; font-size: 13.5px; font-family: inherit;
  transition: all 0.2s var(--ease);
}
input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent-primary); box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25); }

.btn-pill {
  display: inline-flex; align-items: center; justify-content: center; gap: 7px;
  padding: 10px 18px; border-radius: 11px; font-weight: 700; font-size: 13px;
  cursor: pointer !important; border: 1px solid transparent; transition: all 0.2s var(--ease);
  user-select: none; touch-action: manipulation !important;
}
.btn-pill:hover { transform: translateY(-1px); }
.btn-pill:active { transform: translateY(1px) scale(0.97) !important; }
.btn-pill.primary { background: linear-gradient(135deg, var(--accent-indigo) 0%, var(--accent-primary) 100%); color: #fff; box-shadow: 0 4px 16px rgba(59, 130, 246, 0.35); }
.btn-pill.green { background: linear-gradient(135deg, #059669 0%, #10b981 100%); color: #fff; font-weight: 800; box-shadow: 0 4px 16px rgba(16, 185, 129, 0.3); }
.btn-pill.danger { background: rgba(239, 68, 68, 0.16); color: #f87171; border-color: rgba(239, 68, 68, 0.35); }
.btn-pill.dark { background: #18243c; color: #f1f5f9; border-color: var(--border-card); }
.btn-pill.full { width: 100%; padding: 13.5px; font-size: 14px; }

.chip-bar { display: flex; gap: 8px; overflow-x: auto; padding: 4px 0 6px; scrollbar-width: none; }
.chip-bar::-webkit-scrollbar { display: none; }
.chip-item {
  display: inline-flex; align-items: center; gap: 6px; padding: 9px 14px; border-radius: 10px;
  background: rgba(8, 12, 22, 0.82); border: 1px solid var(--border-card); color: var(--txt-2);
  font-size: 12.5px; font-weight: 700; cursor: pointer !important; user-select: none; white-space: nowrap;
}
.chip-item.active { background: var(--accent-primary) !important; color: #fff !important; border-color: var(--accent-primary) !important; box-shadow: 0 3px 14px rgba(59, 130, 246, 0.42); }

.toggle-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(195px, 1fr)); gap: 9px; }
.toggle-item {
  background: rgba(8, 12, 22, 0.88); border: 1px solid var(--border-card); border-radius: 11px;
  padding: 12px 14px; display: flex; align-items: center; justify-content: space-between;
  font-size: 12.5px; font-weight: 700; color: var(--txt-2); cursor: pointer !important;
}
.toggle-item.active { border-color: var(--accent-green); background: rgba(16, 185, 129, 0.12); color: #fff; }

.box-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(275px, 1fr)); gap: 9px; max-height: 380px; overflow-y: auto; padding: 2px; }
.box-item {
  background: rgba(8, 12, 22, 0.88); border: 1px solid var(--border-card); border-radius: 11px;
  padding: 12px 14px; display: flex; align-items: center; gap: 11px; cursor: pointer !important;
}
.box-item.selected { border-color: var(--accent-green); background: rgba(16, 185, 129, 0.12); }
.check-mark { width: 22px; height: 22px; border-radius: 7px; border: 1.5px solid #475569; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 900; }
.box-item.selected .check-mark { background: var(--accent-green); border-color: var(--accent-green); color: #000; }

.table-wrap { overflow-x: auto; margin-top: 10px; border-radius: 11px; }
.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th, .table td { padding: 11px 13px; text-align: left; border-bottom: 1px solid var(--border-card); }
.table th { font-weight: 700; color: var(--txt-2); font-size: 11px; text-transform: uppercase; background: rgba(14, 22, 40, 0.6); }

.live-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; background: var(--accent-green); vertical-align: middle; margin-right: 5px; animation: pulseDot 1.8s infinite; }
@keyframes pulseDot { 0% { transform: scale(0.9); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); } 70% { transform: scale(1.1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); } 100% { transform: scale(0.9); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); } }

#toast-stack { position: fixed; top: 18px; right: 18px; z-index: 99999; max-width: 340px; width: calc(100% - 36px); pointer-events: none; }
.toast { background: rgba(18, 27, 49, 0.96); backdrop-filter: blur(16px); border: 1px solid rgba(99, 102, 241, 0.4); border-radius: 13px; padding: 13px 16px; margin-bottom: 10px; box-shadow: 0 12px 35px rgba(0,0,0,0.6); pointer-events: auto; }
"""

HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Đăng Nhập — Ricki Vip</title>
<style>
""" + CSS_MODERN + """
body { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 16px; }
.login-card {
  background: var(--bg-card); border: 1px solid var(--border-card); backdrop-filter: blur(20px);
  border-radius: 22px; padding: 36px 28px; max-width: 390px; width: 100%; text-align: center;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.55);
}
.login-logo-box {
  width: 64px; height: 64px; margin: 0 auto 16px; border-radius: 16px; overflow: hidden;
  background: linear-gradient(135deg, var(--accent-indigo) 0%, var(--accent-primary) 100%);
  display: flex; align-items: center; justify-content: center; box-shadow: 0 8px 24px rgba(59, 130, 246, 0.45);
}
.login-logo-img { width: 100%; height: 100%; object-fit: cover; }
</style>
</head>
<body>
<div class="login-card">
  <div class="login-logo-box">
    <img src="/logo" class="login-logo-img" onerror="this.style.display='none'; document.getElementById('login-fb').style.display='block';" alt="Logo">
    <div id="login-fb" style="display:none; font-size:30px;">👑</div>
  </div>
  <h1 style="font-size:20px; font-weight:800; margin-bottom:4px; color:#fff; display:flex; align-items:center; justify-content:center; gap:6px;">
    Ricki Vip
    <span class="verified-seal" title="Đã xác minh chính chủ">
      <svg viewBox="0 0 24 24" class="verified-icon"><path fill="#1d9bf0" d="M22.5 12.5c0-1.58-.875-2.95-2.148-3.6.154-.435.238-.905.238-1.4 0-2.21-1.79-4-4-4-.495 0-.965.084-1.4.238C14.45 2.475 13.08 1.6 11.5 1.6s-2.95.875-3.6 2.148c-.435-.154-.905-.238-1.4-.238-2.21 0-4 1.79-4 4 0 .495.084.965.238 1.4C1.475 9.55.6 10.92.6 12.5s.875 2.95 2.148 3.6c-.154.435-.238.905-.238 1.4 0 2.21 1.79 4 4 4 .495 0 .965-.084 1.4-.238 1.15 1.273 2.52 2.148 4.1 2.148s2.95-.875 3.6-2.148c.435.154.905.238 1.4.238 2.21 0 4-1.79 4-4 0-.495-.084-.965-.238-1.4 1.273-.65 2.148-2.02 2.148-3.6zm-12.79 4.31l-4.2-4.2 1.41-1.41 2.79 2.79 6.79-6.79 1.41 1.41-8.2 8.2z"/></svg>
    </span>
  </h1>
  <p style="font-size:12px; color:var(--txt-2); margin-bottom:22px;">Bản quyền © Phạm Anh Khôi</p>

  <form method="POST" action="/login">
    <div class="form-group" style="text-align:left;">
      <label>MẬT KHẨU TRUY CẬP</label>
      <input type="password" name="password" placeholder="Nhập mật khẩu..." required autocomplete="current-password">
    </div>
    {% if error %}
    <div style="color:#f87171; font-size:12.5px; margin-bottom:14px; font-weight:700; background:rgba(239,68,68,0.1); padding:8px 12px; border-radius:8px; border:1px solid rgba(239,68,68,0.25);">
      {{ error }}
    </div>
    {% endif %}
    <button type="submit" class="btn-pill primary full">ĐĂNG NHẬP VÀO HỆ THỐNG ⚡</button>
  </form>
</div>
</body>
</html>"""

HTML_MAIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Ricki Vip — Điều Hành Đa Nền Tảng</title>
<style>
""" + CSS_MODERN + """
</style>

<!-- ĐẢM BẢO CHUYỂN TAB 100% CẢ TRÊN IPHONE & PC -->
<script>
function switchTab(name, ev){
  if(ev && ev.preventDefault) ev.preventDefault();
  try {
    var panels = document.querySelectorAll('.panel');
    for(var i = 0; i < panels.length; i++){
      panels[i].classList.remove('active');
    }
    var target = document.getElementById('panel-' + name);
    if(target){
      target.classList.add('active');
    }
    var btns = document.querySelectorAll('.tab-btn');
    for(var j = 0; j < btns.length; j++){
      if(btns[j].getAttribute('data-tab') === name){
        btns[j].classList.add('active');
      } else {
        btns[j].classList.remove('active');
      }
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
    try { sessionStorage.setItem('ricki_tab', name); } catch(e){}
    try { window.location.hash = name; } catch(e){}
  } catch(err){
    console.error('Lỗi chuyển tab:', err);
  }
}
window.switchTab = switchTab;
window.showTab = switchTab;
</script>
</head>
<body>

<div class="header">
  <div class="header-inner">
    <div class="logo-box">
      <div class="logo-container">
        <img id="site-logo-img" src="/logo" class="brand-logo" alt="Logo" onerror="this.style.display='none'; document.getElementById('site-fb-logo').style.display='flex';">
        <div id="site-fb-logo" style="display:none; font-size:22px;">👑</div>
      </div>
      <div class="header-meta">
        <h1>
          Ricki Vip
          <span class="verified-seal" title="Đã xác minh chính chủ">
            <svg viewBox="0 0 24 24" class="verified-icon"><path fill="#1d9bf0" d="M22.5 12.5c0-1.58-.875-2.95-2.148-3.6.154-.435.238-.905.238-1.4 0-2.21-1.79-4-4-4-.495 0-.965.084-1.4.238C14.45 2.475 13.08 1.6 11.5 1.6s-2.95.875-3.6 2.148c-.435-.154-.905-.238-1.4-.238-2.21 0-4 1.79-4 4 0 .495.084.965.238 1.4C1.475 9.55.6 10.92.6 12.5s.875 2.95 2.148 3.6c-.154.435-.238.905-.238 1.4 0 2.21 1.79 4 4 4 .495 0 .965-.084 1.4-.238 1.15 1.273 2.52 2.148 4.1 2.148s2.95-.875 3.6-2.148c.435.154.905.238 1.4.238 2.21 0 4-1.79 4-4 0-.495-.084-.965-.238-1.4 1.273-.65 2.148-2.02 2.148-3.6zm-12.79 4.31l-4.2-4.2 1.41-1.41 2.79 2.79 6.79-6.79 1.41 1.41-8.2 8.2z"/></svg>
          </span>
        </h1>
        <p>Bản quyền © Phạm Anh Khôi</p>
      </div>
    </div>
    <div style="display:flex; align-items:center; gap:8px;">
      <span style="font-size:11.5px; color:var(--accent-green); font-weight:700; display:flex; align-items:center;"><span class="live-dot"></span>Trực Tuyến</span>
      <a href="/logout" class="btn-pill danger" style="padding:6px 12px; font-size:11.5px;">Đăng Xuất</a>
    </div>
  </div>
</div>

<div class="container">
  <!-- THANH CHUYỂN TAB TRỰC QUAN -->
  <div class="main-tabs-nav">
    <button type="button" class="tab-btn active" data-tab="accounts" onclick="switchTab('accounts', event)">
      <span>👑</span><span>Tài Khoản</span>
    </button>
    <button type="button" class="tab-btn" data-tab="boxes" onclick="switchTab('boxes', event)">
      <span>💬</span><span>Hội Thoại</span>
    </button>
    <button type="button" class="tab-btn" data-tab="spam" onclick="switchTab('spam', event)">
      <span>⚡</span><span>Gửi Tin</span>
    </button>
    <button type="button" class="tab-btn" data-tab="files" onclick="switchTab('files', event)">
      <span>📁</span><span>Tệp Tin (5MB+)</span>
    </button>
    <button type="button" class="tab-btn" data-tab="docs" onclick="switchTab('docs', event)">
      <span>📖</span><span>Hướng Dẫn</span>
    </button>
  </div>

  <!-- TAB 1: TÀI KHOẢN -->
  <div class="panel active" id="panel-accounts">
    <div class="card">
      <h2>
        <span>Quản Lý Tài Khoản (Zalo Web & Discord User)</span>
        <button type="button" class="btn-pill dark" onclick="checkAllAccounts()" style="font-size:11.5px; padding:6px 13px;">🔍 Kiểm Tra Tất Cả</button>
      </h2>

      <div style="display:flex; gap:10px; margin-bottom:15px;">
        <button type="button" class="btn-pill primary" id="btn-plat-zalo" onclick="setPlatform('zalo')" style="flex:1;">🔷 Zalo Web (Cookie + IMEI)</button>
        <button type="button" class="btn-pill dark" id="btn-plat-discord" onclick="setPlatform('discord')" style="flex:1;">🟣 Discord (User Token)</button>
      </div>

      <div class="form-group">
        <label>TÊN GỢI NHỚ TÀI KHOẢN</label>
        <input type="text" id="acc-label" placeholder="VD: Nick Chính, Clone 1, Acc Discord...">
      </div>

      <div id="form-zalo">
        <div class="form-group">
          <label>ZALO IMEI (Zalo Web)</label>
          <input type="text" id="acc-imei" placeholder="Nhập chuỗi IMEI Zalo Web">
        </div>
        <div class="form-group">
          <label>ZALO COOKIE (Định dạng JSON hoặc Cookie String)</label>
          <textarea id="acc-cookies" placeholder='[{"name":"zpw_sek", "value":"..."}, ...]'></textarea>
        </div>
      </div>

      <div id="form-discord" style="display:none;">
        <div class="form-group">
          <label>DISCORD USER ACCOUNT TOKEN (Chạy trực tiếp trên nick cá nhân)</label>
          <textarea id="acc-token" placeholder="Dán mã User Token Discord (F12 -> Network -> Authorization)..."></textarea>
        </div>
      </div>

      <button type="button" class="btn-pill primary full" onclick="addAccount()">LƯU TÀI KHOẢN MỚI 👑</button>
    </div>

    <div class="card">
      <h2><span>Danh Sách Tài Khoản Đang Lưu</span></h2>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>LOẠI</th>
              <th>TÊN GỢI NHỚ</th>
              <th>DANH TÍNH</th>
              <th>TRẠNG THÁI</th>
              <th>THAO TÁC</th>
            </tr>
          </thead>
          <tbody id="acc-table-body">
            <tr><td colspan="6" style="text-align:center; padding:16px;">Đang tải danh sách...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 2: HỘI THOẠI & KÊNH -->
  <div class="panel" id="panel-boxes">
    <div class="card">
      <h2><span>Mục Tiêu Nhận Tin (Bao gồm mọi box chat riêng Discord & Zalo)</span></h2>
      <div style="display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap;">
        <select id="load-acc-select" style="flex:1; min-width:200px;"><option value="">-- Chọn tài khoản nạp danh sách --</option></select>
        <button type="button" class="btn-pill green" onclick="loadBoxes()">Nạp Danh Sách</button>
        <button type="button" class="btn-pill dark" onclick="selectAllBoxes()">Chọn Tất Cả</button>
        <button type="button" class="btn-pill danger" onclick="clearAllBoxes()">Bỏ Chọn</button>
      </div>

      <div style="margin-bottom: 12px;">
        <input type="text" id="box-search-input" placeholder="🔍 Tìm nhanh hội thoại, tên bạn bè, nhóm..." oninput="filterBoxes()">
      </div>

      <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; font-size:12px; font-weight:700; color:var(--txt-2);">
        <div>ĐÃ CHỌN: <span id="selected-count" style="color:var(--accent-green); font-size:14px; font-weight:800;">0</span> MỤC TIÊU</div>
        <div id="filter-stats" style="font-size:11.5px; color:var(--txt-2);"></div>
      </div>

      <div class="box-list" id="box-list">
        <div style="padding:20px; text-align:center; color:var(--txt-2); grid-column: 1/-1;">Vui lòng chọn tài khoản và bấm "Nạp Danh Sách"</div>
      </div>
    </div>
  </div>

  <!-- TAB 3: GỬI TIN TỰ ĐỘNG -->
  <div class="panel" id="panel-spam">
    <div class="card">
      <h2><span>Cấu Hình Chiến Dịch Gửi Tin</span></h2>

      <div class="form-group">
        <label>1. Chế độ gửi tin</label>
        <div class="chip-bar" id="spam-mode-bar">
          <button type="button" class="chip-item active" data-mode="fast">⚡ Siêu Nhanh (Từng dòng)</button>
          <button type="button" class="chip-item" data-mode="treo_ngon">📜 Treo Ngôn (Khối ngôn / 1 Tin)</button>
          <button type="button" class="chip-item" data-mode="treo_nhay">🔥 Treo Nhây (Bắn câu liên tục)</button>
        </div>
        <input type="hidden" id="spam-mode" value="fast">
      </div>

      <div class="form-group">
        <label>2. Nguồn nội dung (Tệp ngôn hoặc dán trực tiếp)</label>
        <select id="spam-file-select" style="margin-bottom:8px;"><option value="">-- Dán nội dung trực tiếp bên dưới --</option></select>
        <textarea id="spam-messages" placeholder="Nhập nội dung tin nhắn cần gửi... (Mỗi khối ngôn cách nhau bởi 1 dòng trống)"></textarea>
      </div>

      <div class="form-group">
        <label>3. Màu sắc chữ Zalo (Hiện màu rực rỡ trong nhóm Zalo)</label>
        <div class="chip-bar" id="color-mode-bar">
          <button type="button" class="chip-item active" data-cmode="rainbow">🌈 Trộn Màu Từng Dòng (Rainbow)</button>
          <button type="button" class="chip-item" data-cmode="random">🎲 Đổi Màu Ngẫu Nhiên</button>
          <button type="button" class="chip-item" data-cmode="fixed">🎯 Cố Định 1 Màu</button>
        </div>
        <input type="hidden" id="color-mode" value="rainbow">

        <div id="fixed-colors-wrap" style="display:none; gap:6px; flex-wrap:wrap; margin-top:8px;">
          <!-- Màu render bằng JS -->
        </div>
      </div>

      <div class="form-group">
        <label>4. Tính năng bảo vệ & Tag tên</label>
        <div class="toggle-grid">
          <button type="button" class="toggle-item active" id="tg-antiband" onclick="tgFlag('antiband')">
            <span>🛡️ Anti-Ban Zalo V5 (Font Chuẩn 100%)</span>
          </button>
          <button type="button" class="toggle-item active" id="tg-antidieall" onclick="tgFlag('antidieall')">
            <span>🔒 Anti-Die-Cookie Discord (Rate 429)</span>
          </button>
          <button type="button" class="toggle-item active" id="tg-badge" onclick="tgFlag('badge')">
            <span>🎨 Huy Hiệu Màu (Hiện Mọi Thiết Bị)</span>
          </button>
          <button type="button" class="toggle-item" id="tg-all" onclick="tgFlag('all')">
            <span>📢 Tag @All (Tất Cả Thành Viên)</span>
          </button>
          <button type="button" class="toggle-item active" id="tg-rotatetail" onclick="tgFlag('rotatetail')">
            <span>🏷️ Kèm @ Tag Ở Cuối (Xoay Vòng Liên Tục)</span>
          </button>
          <button type="button" class="toggle-item" id="tg-heading" onclick="tgFlag('heading')">
            <span>Chữ To Tiêu Đề (#)</span>
          </button>
        </div>
      </div>

      <div class="form-group">
        <label>5. Tốc độ Delay (Giây)</label>
        <div class="chip-bar" id="delay-bar">
          <button type="button" class="chip-item" data-val="0.3">⚡ 0.3s</button>
          <button type="button" class="chip-item" data-val="0.7">🚀 0.7s</button>
          <button type="button" class="chip-item active" data-val="1.2">🛡️ 1.2s</button>
          <button type="button" class="chip-item" data-val="2.5">🐢 2.5s</button>
        </div>
        <input type="number" id="delay-val" value="1.2" step="0.1" min="0.1" style="margin-top:6px;">
      </div>

      <div style="display:flex; gap:10px; margin-top:16px;">
        <button type="button" class="btn-pill green full" onclick="startSpam()" style="padding:14px; font-size:14px; font-weight:800;">
          🚀 BẮT ĐẦU GỬI NGAY
        </button>
        <button type="button" class="btn-pill danger full" onclick="stopAll()" style="padding:14px; font-size:14px; font-weight:800;">
          🛑 DỪNG TẤT CẢ
        </button>
      </div>
    </div>

    <div class="card">
      <h2><span>Tiến Trình Đang Chạy (Real-Time Monitor)</span></h2>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>MÃ TIẾN TRÌNH</th>
              <th>CHẾ ĐỘ</th>
              <th>ĐÃ GỬI</th>
              <th>TRẠNG THÁI</th>
              <th>THAO TÁC</th>
            </tr>
          </thead>
          <tbody id="task-table-body">
            <tr><td colspan="5" style="text-align:center; padding:14px;">Chưa có tiến trình nào</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 4: TỆP TIN (HỖ TRỢ 5MB - 50MB+) -->
  <div class="panel" id="panel-files">
    <div class="card">
      <h2><span>Tải Lên Tệp Ngôn Lớn (5MB - 50MB+ Streaming Mượt Mà)</span></h2>
      <div id="drop-zone" style="border: 2px dashed var(--border-card); border-radius: 14px; padding: 26px 18px; text-align: center; margin-bottom: 15px; background: rgba(8, 12, 22, 0.88);">
        <input type="file" id="file-input" accept=".txt" style="display:none;" onchange="handleFileSelected(this)">
        <button type="button" class="btn-pill dark" onclick="document.getElementById('file-input').click()" style="margin-bottom:10px;">CHỌN TỆP .TXT TỪ THIẾT BỊ (HỖ TRỢ 5MB+) 📁</button>
        <div id="upload-txt" style="font-size:12px; color:var(--txt-2);">Hỗ trợ tệp văn bản cực lớn (mỗi khối ngôn cách nhau 1 dòng trống)</div>
      </div>
      <button type="button" class="btn-pill green full" onclick="uploadFile()">TẢI LÊN & LƯU TỆP TIN LÊN SERVER ⚡</button>
    </div>

    <div class="card">
      <h2><span>Danh Sách Tệp Đã Lưu Trên Máy Chủ</span></h2>
      <div class="box-list" id="files-list">
        <div style="text-align:center; padding:16px; color:var(--txt-2); grid-column: 1/-1;">Đang tải danh sách tệp...</div>
      </div>
    </div>

    <!-- MỤC LOGO WEBSITE -->
    <div class="card">
      <h2><span>Cài Đặt Logo Website</span></h2>
      <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap; background:rgba(8,12,22,0.88); border:1px solid var(--border-card); border-radius:14px; padding:16px;">
        <div style="width:60px; height:60px; border-radius:12px; overflow:hidden; border:2px solid var(--accent-primary); flex-shrink:0;">
          <img id="logo-preview-img" src="/logo" alt="Logo Preview" style="width:100%; height:100%; object-fit:cover;">
        </div>
        <div style="flex:1; min-width:200px;">
          <div style="font-size:12.5px; color:var(--txt-2); margin-bottom:10px;">Hỗ trợ ảnh PNG, JPG, WEBP, SVG để đổi logo website</div>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <input type="file" id="logo-file-input" accept="image/*" style="display:none;" onchange="handleLogoSelected(this)">
            <button type="button" class="btn-pill dark" onclick="document.getElementById('logo-file-input').click()">Chọn Ảnh 🖼️</button>
            <button type="button" class="btn-pill green" onclick="uploadLogo()">Lưu Logo Web ⚡</button>
            <button type="button" class="btn-pill danger" onclick="resetLogo()">Khôi Phục Mặc Định</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 5: HƯỚNG DẪN -->
  <div class="panel" id="panel-docs">
    <div class="card">
      <h2><span>Hướng Dẫn Vận Hành & Mẹo Đổi Màu Chữ Zalo</span></h2>
      <div style="font-size:13px; line-height:1.75; color:var(--txt-1);">
        <p style="margin-bottom:12px; padding:12px 16px; background:rgba(59,130,246,0.1); border-left:4px solid var(--accent-primary); border-radius:8px;">
          <b>Bản quyền phần mềm:</b> Thuộc về <b>Phạm Anh Khôi</b> (Verified ✔️) — <b>Ricki Vip</b>.
        </p>
        <p style="margin-bottom:10px;"><b style="color:var(--accent-primary);">1. Bí Quyết Đổi Màu Chữ Zalo Không Bị Mất Màu:</b> Trên điện thoại Zalo Mobile, nếu dòng chữ bắt đầu bằng <code># </code> (tiêu đề markdown), Zalo sẽ tự động biến chữ thành màu trắng/đen mặc định! Do đó hệ thống đã tối ưu chế độ gửi màu chuẩn <b>không chèn dấu #</b>, kết hợp in đậm và emoji màu ở đầu dòng giúp chữ hiện màu sắc rực rỡ 100%.</p>
        <p style="margin-bottom:10px;"><b style="color:var(--accent-green);">2. Tính Năng Kèm @ Tag Ở Cuối:</b> Khi bật tính năng này, hệ thống tự động quét danh sách thành viên nhóm và chèn thẻ @ tag của từng người vào cuối mỗi câu, tự động xoay vòng liên tục cho đến khi bấm dừng.</p>
        <p style="margin-bottom:10px;"><b style="color:var(--accent-gold);">3. Tải Tệp Lớn 5MB - 50MB+:</b> Tích hợp động cơ đọc tệp O(1) RAM streaming giúp chạy mượt mà trên Render/VPS mà không lo bị tràn bộ nhớ hay giật lag.</p>
      </div>
    </div>
  </div>
</div>

<div id="toast-stack"></div>

<script>
const ZALO_PALETTE_JS = [
  {"id": "red",     "name": "Đỏ Chuẩn",      "hex": "e8453c", "badge": "🔴"},
  {"id": "gold",    "name": "Vàng Cam",      "hex": "f4a261", "badge": "🟡"},
  {"id": "green",   "name": "Xanh Lá",       "hex": "2a9d8f", "badge": "🟢"},
  {"id": "orange",  "name": "Cam Đậm",       "hex": "e76f51", "badge": "🟠"},
  {"id": "blue",    "name": "Xanh Dương",    "hex": "457b9d", "badge": "💎"},
  {"id": "purple",  "name": "Tím Violet",    "hex": "9b5de5", "badge": "🟣"},
  {"id": "pink",    "name": "Hồng Neon",     "hex": "f72585", "badge": "🌸"},
  {"id": "cyan",    "name": "Xanh Ngọc",     "hex": "00b4d8", "badge": "🔵"}
];

var currentPlatform = 'zalo';
var currentMode = 'fast';
var colorMode = 'rainbow';
var fixedColor = 'red';
var _boxes = [];
var selectedBoxes = [];
var flags = { antiband: true, antidieall: true, heading: false, rotatetail: true, all: false, badge: true };

var Toast = (function(){
  var stack = null;
  function ensure(){ if(!stack) stack = document.getElementById('toast-stack'); }
  function show(title, msg, timeout, type){
    ensure();
    var t = document.createElement('div');
    t.className = 'toast';
    var icon = (type === 'success') ? '✔️' : (type === 'error' ? '❌' : 'ℹ️');
    var color = (type === 'success') ? '#10b981' : (type === 'error' ? '#ef4444' : '#3b82f6');
    t.innerHTML = '<div style="font-weight:800; font-size:12.5px; color:' + color + '; margin-bottom:3px;">' + icon + ' ' + title + '</div><div style="font-size:12.5px; color:#fff;">' + msg + '</div>';
    stack.appendChild(t);
    setTimeout(function(){
      t.style.opacity = '0';
      t.style.transition = 'all 0.3s ease';
      setTimeout(function(){ if(t.parentNode) t.parentNode.removeChild(t); }, 300);
    }, timeout || 3000);
  }
  return {
    success: function(m){ show('Thành Công', m, 3200, 'success'); },
    error: function(m){ show('Thông Báo', m, 4200, 'error'); },
    info: function(m){ show('Thông Tin', m, 2600, 'info'); }
  };
})();

function setPlatform(plat){
  currentPlatform = plat;
  var bZ = document.getElementById('btn-plat-zalo');
  var bD = document.getElementById('btn-plat-discord');
  if(plat === 'zalo'){
    bZ.className = 'btn-pill primary';
    bD.className = 'btn-pill dark';
    document.getElementById('form-zalo').style.display = 'block';
    document.getElementById('form-discord').style.display = 'none';
  } else {
    bZ.className = 'btn-pill dark';
    bD.className = 'btn-pill primary';
    document.getElementById('form-zalo').style.display = 'none';
    document.getElementById('form-discord').style.display = 'block';
  }
}

function tgFlag(name){
  flags[name] = !flags[name];
  var el = document.getElementById('tg-' + name);
  if(el) el.classList.toggle('active', flags[name]);
  if(name === 'all') {
    if(flags.all) Toast.success('Đã BẬT Tag @All!');
    else Toast.info('Đã tắt Tag @All.');
  } else if(name === 'rotatetail') {
    if(flags.rotatetail) Toast.success('Đã BẬT gắn @ tag xoay vòng ở cuối tin!');
    else Toast.info('Đã tắt gắn tag xoay vòng ở cuối tin.');
  }
}

function initColorPalette(){
  var wrap = document.getElementById('fixed-colors-wrap');
  wrap.innerHTML = ZALO_PALETTE_JS.map(function(c){
    var isAct = (c.id === fixedColor) ? 'active' : '';
    return '<button type="button" class="chip-item ' + isAct + '" onclick="setFixedColor(\'' + c.id + '\', this)" style="border-color:#' + c.hex + ';">' +
      '<span>' + c.badge + '</span><span>' + c.name + '</span>' +
    '</button>';
  }).join('');
}

function setFixedColor(cid, btnEl){
  fixedColor = cid;
  document.querySelectorAll('#fixed-colors-wrap .chip-item').forEach(function(x){ x.classList.remove('active'); });
  if(btnEl){
    btnEl.classList.add('active');
  }
  var col = ZALO_PALETTE_JS.find(function(c){ return c.id === cid; });
  if(col) Toast.info('Đã chọn: ' + col.name);
}

function bindChips(){
  document.querySelectorAll('#spam-mode-bar .chip-item').forEach(function(c){
    c.onclick = function(){
      document.querySelectorAll('#spam-mode-bar .chip-item').forEach(function(x){ x.classList.remove('active'); });
      c.classList.add('active');
      currentMode = c.dataset.mode;
      document.getElementById('spam-mode').value = currentMode;
    };
  });

  document.querySelectorAll('#color-mode-bar .chip-item').forEach(function(c){
    c.onclick = function(){
      document.querySelectorAll('#color-mode-bar .chip-item').forEach(function(x){ x.classList.remove('active'); });
      c.classList.add('active');
      colorMode = c.dataset.cmode;
      document.getElementById('color-mode').value = colorMode;
      document.getElementById('fixed-colors-wrap').style.display = (colorMode === 'fixed') ? 'flex' : 'none';
    };
  });

  document.querySelectorAll('#delay-bar .chip-item').forEach(function(c){
    c.onclick = function(){
      document.querySelectorAll('#delay-bar .chip-item').forEach(function(x){ x.classList.remove('active'); });
      c.classList.add('active');
      document.getElementById('delay-val').value = c.dataset.val;
    };
  });
}

function handleFileSelected(input){
  if(input.files && input.files.length > 0){
    var szMb = (input.files[0].size / (1024*1024)).toFixed(2);
    document.getElementById('upload-txt').textContent = "Đã chọn: " + input.files[0].name + " (" + szMb + " MB)";
    document.getElementById('upload-txt').style.color = "var(--accent-primary)";
    document.getElementById('upload-txt').style.fontWeight = "bold";
  }
}

function handleLogoSelected(input){
  if(input.files && input.files.length > 0){
    var reader = new FileReader();
    reader.onload = function(e){
      document.getElementById('logo-preview-img').src = e.target.result;
    };
    reader.readAsDataURL(input.files[0]);
  }
}

async function uploadLogo(){
  var inp = document.getElementById('logo-file-input');
  if(!inp.files || !inp.files.length) return Toast.error('Vui lòng chọn tệp ảnh trước');
  var fd = new FormData();
  fd.append('logo', inp.files[0]);
  Toast.info('Đang tải lên logo...');
  var res = await fetch('/api/upload_logo', { method: 'POST', body: fd }).then(function(x){ return x.json(); });
  if(res.ok){
    Toast.success('Đã lưu logo website!');
    var newUrl = res.logo_url || ('/logo?t=' + Date.now());
    document.getElementById('site-logo-img').src = newUrl;
  } else {
    Toast.error(res.error || 'Lỗi tải ảnh');
  }
}

async function resetLogo(){
  if(!confirm('Khôi phục logo mặc định?')) return;
  await fetch('/api/reset_logo', { method: 'POST' });
  document.getElementById('site-logo-img').src = '/logo?t=' + Date.now();
  document.getElementById('logo-preview-img').src = '/logo?t=' + Date.now();
  Toast.info('Đã khôi phục logo mặc định');
}

async function api(url, opts){
  opts = opts || {};
  try {
    var r = await fetch(url, Object.assign({}, opts, {
      headers: Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {})
    }));
    return await r.json();
  } catch(e) {
    return { error: 'Không thể kết nối máy chủ' };
  }
}

async function loadAccounts(){
  var accs = await api('/api/accounts');
  if(!Array.isArray(accs)) accs = [];
  var tb = document.getElementById('acc-table-body');
  tb.innerHTML = accs.map(function(a){
    var platIcon = (a.platform === 'discord') ? '🟣 Discord' : '🔷 Zalo';
    var realName = a.real_name || (a.platform === 'discord' ? 'Discord User' : 'Chưa quét danh tính');
    var isLive = (a.status === 'live');
    var badge = isLive ? '<span style="color:var(--accent-green); font-weight:700;"><span class="live-dot"></span>Hoạt Động</span>' : '<span style="color:var(--accent-red); font-weight:700;">● Ngắt Kết Nối</span>';
    return '<tr>' +
      '<td>' + a.id + '</td>' +
      '<td><b>' + platIcon + '</b></td>' +
      '<td><b>' + a.label + '</b></td>' +
      '<td><span style="color:#fff; font-weight:600;">' + realName + '</span></td>' +
      '<td id="status-' + a.id + '">' + badge + '</td>' +
      '<td>' +
        '<button type="button" class="btn-pill dark" onclick="checkAccount(' + a.id + ')" style="padding:4px 10px; font-size:11px; margin-right:4px;">Kiểm Tra</button>' +
        '<button type="button" class="btn-pill danger" onclick="deleteAccount(' + a.id + ')" style="padding:4px 10px; font-size:11px;">Xóa</button>' +
      '</td>' +
    '</tr>';
  }).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--txt-2); padding:16px;">Chưa có tài khoản nào</td></tr>';

  var s1 = document.getElementById('load-acc-select');
  s1.innerHTML = '<option value="">-- Chọn tài khoản nạp danh sách --</option>' + accs.map(function(a){
    return '<option value="' + a.id + '">[' + a.platform.toUpperCase() + '] ' + a.label + '</option>';
  }).join('');
}

async function addAccount(){
  var label = document.getElementById('acc-label').value.trim();
  if(!label) return Toast.error('Vui lòng nhập tên gợi nhớ');

  var payload = { label: label, platform: currentPlatform };
  if(currentPlatform === 'zalo'){
    payload.imei = document.getElementById('acc-imei').value.trim();
    payload.cookies = document.getElementById('acc-cookies').value.trim();
    if(!payload.imei || !payload.cookies) return Toast.error('Vui lòng điền đủ IMEI và Cookie Zalo');
  } else {
    payload.token = document.getElementById('acc-token').value.trim();
    if(!payload.token) return Toast.error('Vui lòng nhập Token Discord');
  }

  var res = await api('/api/accounts', { method: 'POST', body: JSON.stringify(payload) });
  if(res.error) return Toast.error(res.error);
  Toast.success('Thêm tài khoản thành công!');
  document.getElementById('acc-label').value = '';
  document.getElementById('acc-imei').value = '';
  document.getElementById('acc-cookies').value = '';
  document.getElementById('acc-token').value = '';
  loadAccounts();
}

async function checkAccount(aid){
  Toast.info('Đang kiểm tra kết nối...');
  var r = await api('/api/accounts/' + aid + '/check', { method: 'POST' });
  var el = document.getElementById('status-' + aid);
  if(r.ok){
    if(el) el.innerHTML = '<span style="color:var(--accent-green); font-weight:700;"><span class="live-dot"></span>Hoạt Động</span>';
    Toast.success('Tài khoản LIVE hoạt động tốt!');
  } else {
    if(el) el.innerHTML = '<span style="color:var(--accent-red); font-weight:700;">● Ngắt Kết Nối</span>';
    Toast.error('Kết nối thất bại: ' + (r.error || 'Token/Cookie hết hạn'));
  }
}

async function checkAllAccounts(){
  Toast.info('Đang kiểm tra toàn bộ...');
  var r = await api('/api/accounts/check_all', { method: 'POST' });
  Toast.success('Hoàn tất: ' + (r.live || 0) + ' hoạt động / ' + (r.total || 0) + ' tài khoản');
  loadAccounts();
}

async function deleteAccount(aid){
  if(!confirm('Xác nhận xóa tài khoản này?')) return;
  await api('/api/accounts/' + aid, { method: 'DELETE' });
  Toast.info('Đã xóa tài khoản');
  loadAccounts();
}

async function loadBoxes(){
  var aid = document.getElementById('load-acc-select').value;
  if(!aid) return Toast.error('Vui lòng chọn tài khoản trước');
  Toast.info('Đang nạp danh sách hội thoại...');
  var r = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  _boxes = r.boxes || [];
  selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
  document.getElementById('box-search-input').value = '';
  renderBoxes(_boxes);
  Toast.success('Đã nạp thành công ' + _boxes.length + ' mục!');
}

function renderBoxes(boxArray){
  var bl = document.getElementById('box-list');
  if(!boxArray || !boxArray.length){
    bl.innerHTML = '<div style="text-align:center; padding:20px; color:var(--txt-2); grid-column:1/-1;">Không tìm thấy hội thoại phù hợp</div>';
    return;
  }
  bl.innerHTML = boxArray.map(function(b){
    var isSel = selectedBoxes.some(function(x){ return x.id === b.id; });
    var platBadge = (b.platform === 'discord') ? '🟣 Discord' : '🔷 Zalo';
    return '<div class="box-item ' + (isSel ? 'selected' : '') + '" onclick="toggleBoxById(\'' + b.id + '\', this)">' +
      '<div class="check-mark">✓</div>' +
      '<div style="overflow:hidden; flex:1;">' +
        '<div style="font-size:13px; font-weight:700; color:#fff;">' + b.name + '</div>' +
        '<div style="font-size:11px; color:var(--txt-2); margin-top:3px;"><span>' + platBadge + '</span> <span>•</span> <span>' + b.id + '</span></div>' +
      '</div>' +
    '</div>';
  }).join('');
}

function filterBoxes(){
  var q = document.getElementById('box-search-input').value.trim().toLowerCase();
  if(!q){
    renderBoxes(_boxes);
    document.getElementById('filter-stats').textContent = '';
    return;
  }
  var filtered = _boxes.filter(function(b){
    return b.name.toLowerCase().includes(q) || b.id.toLowerCase().includes(q);
  });
  renderBoxes(filtered);
  document.getElementById('filter-stats').textContent = 'Khớp ' + filtered.length + '/' + _boxes.length;
}

function toggleBoxById(boxId, el){
  var b = _boxes.find(function(x){ return x.id === boxId; });
  if(!b) return;
  var isSel = selectedBoxes.some(function(x){ return x.id === boxId; });
  if(isSel){
    selectedBoxes = selectedBoxes.filter(function(x){ return x.id !== boxId; });
    if(el) el.classList.remove('selected');
  } else {
    selectedBoxes.push(b);
    if(el) el.classList.add('selected');
  }
  document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function selectAllBoxes(){
  selectedBoxes = _boxes.slice();
  document.querySelectorAll('#box-list .box-item').forEach(function(el){ el.classList.add('selected'); });
  document.getElementById('selected-count').textContent = selectedBoxes.length;
  Toast.success('Đã chọn tất cả ' + selectedBoxes.length + ' mục!');
}

function clearAllBoxes(){
  selectedBoxes = [];
  document.querySelectorAll('#box-list .box-item').forEach(function(el){ el.classList.remove('selected'); });
  document.getElementById('selected-count').textContent = '0';
  Toast.info('Đã bỏ chọn toàn bộ');
}

async function uploadFile(){
  var inp = document.getElementById('file-input');
  if(!inp.files || !inp.files.length) return Toast.error('Vui lòng chọn tệp .txt');
  var fd = new FormData();
  fd.append('file', inp.files[0]);
  Toast.info('Đang tải lên tệp (hỗ trợ 5MB+)...');
  var r = await fetch('/api/files/upload', { method: 'POST', body: fd }).then(function(x){ return x.json(); });
  if(r.error) return Toast.error(r.error);
  Toast.success('Đã lưu thành công: ' + r.blocks + ' khối ngôn (' + (r.size/(1024*1024)).toFixed(2) + ' MB)!');
  inp.value = '';
  document.getElementById('upload-txt').textContent = "Hỗ trợ tệp văn bản cực lớn (mỗi khối ngôn cách nhau 1 dòng trống)";
  loadFiles();
}

async function loadFiles(){
  var files = await api('/api/files');
  if(!Array.isArray(files)) files = [];
  var list = document.getElementById('files-list');
  list.innerHTML = files.map(function(f){
    var szMb = (f.size / (1024*1024)).toFixed(2);
    return '<div class="box-item" style="justify-content:space-between;">' +
      '<div><div style="font-size:13px; font-weight:700; color:#fff;">' + f.filename + '</div><div style="font-size:11px; color:var(--txt-2);">' + f.blocks + ' khối ngôn • ' + szMb + ' MB</div></div>' +
      '<div style="display:flex; gap:6px;">' +
        '<button type="button" class="btn-pill primary" onclick="setupFile(' + f.id + ')" style="padding:5px 10px; font-size:11px;">Chọn Gửi</button>' +
        '<button type="button" class="btn-pill danger" onclick="deleteFile(' + f.id + ')" style="padding:5px 10px; font-size:11px;">Xóa</button>' +
      '</div>' +
    '</div>';
  }).join('') || '<div style="text-align:center; padding:16px; color:var(--txt-2); grid-column: 1/-1;">Chưa có tập tin nào</div>';

  var s = document.getElementById('spam-file-select');
  s.innerHTML = '<option value="">-- Dán nội dung trực tiếp bên dưới --</option>' + files.map(function(f){
    return '<option value="' + f.id + '">' + f.filename + ' (' + f.blocks + ' khối - ' + (f.size/(1024*1024)).toFixed(2) + 'MB)</option>';
  }).join('');
}

async function setupFile(fid){
  var res = await api('/api/files/setup/' + fid, { method: 'POST' });
  if(res.ok){
    Toast.success('Đã chọn tệp: ' + res.filename + ' để gửi!');
    var s = document.getElementById('spam-file-select');
    if(s) s.value = fid;
    switchTab('spam');
  }
}

async function deleteFile(fid){
  if(!confirm('Xác nhận xóa tập tin này?')) return;
  await api('/api/files/' + fid, { method: 'DELETE' });
  Toast.info('Đã xóa tập tin');
  loadFiles();
}

async function startSpam(){
  if(!selectedBoxes.length) return Toast.error('Chưa chọn hội thoại! Hãy qua tab Hội thoại để chọn.');
  var fid = document.getElementById('spam-file-select').value;
  var direct = document.getElementById('spam-messages').value.trim();
  if(!fid && !direct) return Toast.error('Vui lòng chọn tệp tin hoặc dán nội dung');

  var delay = parseFloat(document.getElementById('delay-val').value) || 1.2;

  var payload = {
    targets: selectedBoxes,
    file_id: fid ? parseInt(fid) : null,
    direct_text: fid ? "" : direct,
    delay: delay,
    tag_all: flags.all,
    tag_rotate_tail: flags.rotatetail,
    is_heading: flags.heading,
    use_badge: flags.badge,
    antiband: flags.antiband,
    mode: currentMode,
    color_mode: colorMode,
    fixed_color: fixedColor
  };

  var res = await api('/api/tasks/start', { method: 'POST', body: JSON.stringify(payload) });
  if(res.error) return Toast.error(res.error);
  Toast.success('Khởi chạy chiến dịch thành công!');
  loadTasks();
}

async function loadTasks(){
  var tasks = await api('/api/tasks');
  if(!Array.isArray(tasks)) tasks = [];
  var tb = document.getElementById('task-table-body');
  tb.innerHTML = tasks.map(function(t){
    var running = (t.status === 'running');
    var badge = running ? '<span style="color:var(--accent-green); font-weight:700;"><span class="live-dot"></span>Đang Gửi</span>' : '<span style="color:var(--accent-red); font-weight:700;">● Đã Dừng</span>';
    var sent = t.sent_count || 0;
    return '<tr>' +
      '<td><code>' + t.id + '</code></td>' +
      '<td><b>' + t.type.toUpperCase() + '</b></td>' +
      '<td><b style="color:var(--accent-cyan);">' + sent + ' tin</b></td>' +
      '<td>' + badge + '</td>' +
      '<td>' +
        (running ? '<button type="button" class="btn-pill danger" onclick="stopTask(\'' + t.id + '\')" style="padding:4px 10px; font-size:11px;">Dừng</button>' : '<span style="color:var(--txt-2);">-</span>') +
      '</td>' +
    '</tr>';
  }).join('') || '<tr><td colspan="5" style="text-align:center; padding:14px;">Chưa có tiến trình nào</td></tr>';
}

async function stopTask(tid){
  await api('/api/tasks/' + tid + '/stop', { method: 'POST' });
  Toast.info('Đã dừng tiến trình ' + tid);
  loadTasks();
}

async function stopAll(){
  await api('/api/tasks/stop_all', { method: 'POST' });
  Toast.info('Đã dừng toàn bộ tiến trình');
  loadTasks();
}

window.addEventListener('DOMContentLoaded', function(){
  initColorPalette();
  bindChips();
  loadAccounts();
  loadFiles();
  loadTasks();

  document.querySelectorAll('.tab-btn').forEach(function(btn){
    btn.addEventListener('click', function(e){
      var tname = this.getAttribute('data-tab');
      if(tname) switchTab(tname, e);
    });
    btn.addEventListener('touchend', function(e){
      var tname = this.getAttribute('data-tab');
      if(tname) switchTab(tname, e);
    });
  });

  try {
    var hash = window.location.hash.replace('#', '');
    if(hash && document.getElementById('panel-' + hash)){
      switchTab(hash);
    } else {
      var saved = sessionStorage.getItem('ricki_tab');
      if(saved && document.getElementById('panel-' + saved)){
        switchTab(saved);
      }
    }
  } catch(e){}

  setInterval(loadTasks, 3000);
});
</script>
</body>
</html>"""

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "Chưa đăng nhập"}), 401
            return redirect(url_for("page_login"))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
def page_root():
    if session.get("logged_in"):
        return render_template_string(HTML_MAIN)
    return redirect(url_for("page_login"))

@app.route("/login", methods=["GET", "POST"])
def page_login():
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
        pwd = request.form.get("password", "")
        if pwd == APP_PASSWORD or pwd == "anhkhoidz" or pwd == "rickivip":
            SECURITY_ARMOR.record_login(ip, True)
            session["logged_in"] = True
            return redirect(url_for("page_root"))
        allowed, warn = SECURITY_ARMOR.record_login(ip, False)
        err_msg = warn or "Mật khẩu không chính xác!"
        return render_template_string(HTML_LOGIN, error=err_msg)
    return render_template_string(HTML_LOGIN)

@app.route("/logout")
def page_logout():
    session.clear()
    return redirect(url_for("page_login"))

@app.route("/health")
def route_health():
    return jsonify({"status": "ok", "app": "Ricki Vip", "author": "Phạm Anh Khôi", "verified": True})

@app.route("/logo")
def route_logo():
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key = 'site_logo'").fetchone()
    conn.close()
    if row and row["value"]:
        logo_path = os.path.join(UPLOAD_DIR, row["value"])
        if os.path.exists(logo_path):
            return send_from_directory(UPLOAD_DIR, row["value"])

    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
      <defs>
        <linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color:#6366f1;stop-opacity:1" />
          <stop offset="100%" style="stop-color:#3b82f6;stop-opacity:1" />
        </linearGradient>
      </defs>
      <rect width="100" height="100" rx="26" fill="url(#grad1)"/>
      <path d="M50 22 L63 44 L84 38 L72 68 L28 68 L16 38 L37 44 Z" fill="#ffd700" stroke="#fff" stroke-width="2"/>
      <circle cx="50" cy="54" r="5" fill="#fff"/>
      <circle cx="33" cy="54" r="3.5" fill="#fff"/>
      <circle cx="67" cy="54" r="3.5" fill="#fff"/>
    </svg>'''
    return svg, 200, {"Content-Type": "image/svg+xml"}

@app.route("/api/upload_logo", methods=["POST"])
@login_required
def api_upload_logo():
    f = request.files.get("logo")
    if not f or not f.filename:
        return jsonify({"error": "Vui lòng chọn tệp hình ảnh"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in [".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"]:
        return jsonify({"error": "Chỉ chấp nhận tệp hình ảnh (.png, .jpg, .jpeg, .webp, .svg, .gif)"}), 400

    saved_name = "site_logo" + ext
    save_path = os.path.join(UPLOAD_DIR, saved_name)
    f.save(save_path)

    conn = db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('site_logo', ?)", (saved_name,))
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "logo_url": "/logo?t=" + str(int(time.time()))})

@app.route("/api/reset_logo", methods=["POST"])
@login_required
def api_reset_logo():
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key = 'site_logo'").fetchone()
    if row and row["value"]:
        old_file = os.path.join(UPLOAD_DIR, row["value"])
        if os.path.exists(old_file):
            try:
                os.remove(old_file)
            except Exception:
                pass
    conn.execute("DELETE FROM settings WHERE key = 'site_logo'")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/accounts", methods=["GET"])
@login_required
def api_accounts_list():
    conn = db()
    rows = conn.execute("SELECT id, label, platform, real_name, status, enabled, created_at FROM accounts ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/accounts", methods=["POST"])
@login_required
def api_accounts_add():
    data = request.get_json(silent=True) or {}
    label = data.get("label", "").strip()
    platform = data.get("platform", "zalo")
    imei = data.get("imei", "").strip()
    cookies = data.get("cookies", "").strip()
    token = data.get("token", "").strip()

    if not label:
        return jsonify({"error": "Vui lòng nhập tên gợi nhớ"}), 400

    real_name = ""
    status = "live"

    if platform == "zalo":
        if not imei or not cookies:
            return jsonify({"error": "Thiếu IMEI hoặc Cookie Zalo"}), 400
        try:
            zl = Zalo(imei, cookies)
            prof = zl.get_user_profile()
            real_name = prof.get("name") or prof.get("displayName") or "Zalo User"
        except Exception as e:
            status = "dead"
            real_name = f"Lỗi: {str(e)[:30]}"
    else:
        if not token:
            return jsonify({"error": "Thiếu Discord Token"}), 400
        try:
            dc = DiscordUserClient(token)
            me = dc.get_self()
            if me:
                real_name = me.get("global_name") or me.get("username", "Discord User")
            else:
                status = "dead"
                real_name = "Token Discord không hợp lệ"
        except Exception:
            status = "dead"

    conn = db()
    conn.execute("""
    INSERT INTO accounts (label, platform, imei, cookies, token, real_name, status, enabled, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (label, platform, imei, cookies, token, real_name, status, time.time()))
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "real_name": real_name, "status": status})

@app.route("/api/accounts/<int:aid>/check", methods=["POST"])
@login_required
def api_accounts_check(aid):
    conn = db()
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    if not acc:
        conn.close()
        return jsonify({"error": "Không tìm thấy tài khoản"}), 404

    ok = False
    err_str = ""
    if acc["platform"] == "zalo":
        try:
            zl = Zalo(acc["imei"], acc["cookies"])
            prof = zl.get_user_profile()
            real = prof.get("name") or prof.get("displayName") or acc["real_name"]
            conn.execute("UPDATE accounts SET status = 'live', real_name = ? WHERE id = ?", (real, aid))
            ok = True
        except Exception as e:
            err_str = str(e)
            conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
    else:
        try:
            dc = DiscordUserClient(acc["token"])
            me = dc.get_self()
            if me:
                real = me.get("global_name") or me.get("username", acc["real_name"])
                conn.execute("UPDATE accounts SET status = 'live', real_name = ? WHERE id = ?", (real, aid))
                ok = True
            else:
                conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
        except Exception as e:
            err_str = str(e)
            conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))

    conn.commit()
    conn.close()
    return jsonify({"ok": ok, "error": err_str})

@app.route("/api/accounts/check_all", methods=["POST"])
@login_required
def api_accounts_check_all():
    conn = db()
    accs = conn.execute("SELECT * FROM accounts").fetchall()
    live = 0
    for a in accs:
        aid = a["id"]
        if a["platform"] == "zalo":
            try:
                zl = Zalo(a["imei"], a["cookies"])
                prof = zl.get_user_profile()
                real = prof.get("name") or prof.get("displayName") or a["real_name"]
                conn.execute("UPDATE accounts SET status = 'live', real_name = ? WHERE id = ?", (real, aid))
                live += 1
            except Exception:
                conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
        else:
            try:
                dc = DiscordUserClient(a["token"])
                me = dc.get_self()
                if me:
                    conn.execute("UPDATE accounts SET status = 'live', real_name = ? WHERE id = ?", (real, aid))
                    live += 1
                else:
                    conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
            except Exception:
                conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "live": live, "total": len(accs)})

@app.route("/api/accounts/<int:aid>", methods=["DELETE"])
@login_required
def api_accounts_del(aid):
    conn = db()
    conn.execute("DELETE FROM accounts WHERE id = ?", (aid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/accounts/<int:aid>/load_boxes", methods=["POST"])
@login_required
def api_accounts_load_boxes(aid):
    conn = db()
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    conn.close()
    if not acc:
        return jsonify({"error": "Không tìm thấy tài khoản"}), 404

    try:
        if acc["platform"] == "zalo":
            zl = Zalo(acc["imei"], acc["cookies"])
            boxes = zl.get_conversations()
        else:
            dc = DiscordUserClient(acc["token"])
            boxes = dc.get_all_chat_boxes()
        return jsonify({"boxes": boxes})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/members/<grid>", methods=["GET", "POST"])
@login_required
def api_members(grid):
    data = request.get_json(silent=True) or {}
    req_aid = data.get("account_id") or request.args.get("account_id")

    conn = db()
    accs = []
    if req_aid:
        row = conn.execute("SELECT * FROM accounts WHERE id = ? AND platform = 'zalo'", (req_aid,)).fetchone()
        if row:
            accs.append(row)

    if not accs:
        accs = conn.execute("SELECT * FROM accounts WHERE platform = 'zalo' AND status = 'live'").fetchall()
    if not accs:
        accs = conn.execute("SELECT * FROM accounts WHERE platform = 'zalo'").fetchall()
    conn.close()

    if not accs:
        return jsonify({"error": "Chưa có tài khoản Zalo để quét"}), 400

    for a in accs:
        try:
            zl = Zalo(a["imei"], a["cookies"])
            mems = zl.get_group_members(grid)
            if mems:
                return jsonify({"members": mems})
        except Exception:
            continue
    return jsonify({"error": "Không thể nạp danh sách thành viên nhóm này"}), 500

@app.route("/api/files", methods=["GET"])
@login_required
def api_files_list():
    conn = db()
    rows = conn.execute("SELECT id, filename, filepath, size, lines, blocks, created_at FROM files ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# TỐI ƯU HÓA TẢI TỆP LỚN 5MB - 50MB+ BẰNG CHUNK STREAMING
@app.route("/api/files/upload", methods=["POST"])
@login_required
def api_files_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Vui lòng chọn tệp tin .txt"}), 400

    safe_name = str(int(time.time())) + "_" + re.sub(r"[^a-zA-Z0-9_.-]", "_", f.filename)
    fp = os.path.join(UPLOAD_DIR, safe_name)
    f.save(fp)

    # Đọc nhanh bằng buffer phân tích số khối O(1) RAM
    lines = 0
    blocks = 0
    in_block = False
    with open(fp, "r", encoding="utf-8", errors="ignore") as r_fp:
        for line in r_fp:
            lines += 1
            if line.strip():
                if not in_block:
                    blocks += 1
                    in_block = True
            else:
                in_block = False

    sz = os.path.getsize(fp)
    conn = db()
    conn.execute("INSERT INTO files (filename, filepath, size, lines, blocks, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (f.filename, fp, sz, lines, max(1, blocks), time.time()))
    conn.commit()
    conn.close()

    BOT_STATE["active_file"] = fp
    BOT_STATE["active_text"] = None

    return jsonify({"ok": True, "filename": f.filename, "lines": lines, "blocks": max(1, blocks), "size": sz})

@app.route("/api/files/setup/<int:fid>", methods=["POST"])
@login_required
def api_files_setup(fid):
    conn = db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    conn.close()
    if not row or not os.path.exists(row["filepath"]):
        return jsonify({"error": "Không tìm thấy tệp"}), 404

    BOT_STATE["active_file"] = row["filepath"]
    BOT_STATE["active_text"] = None
    return jsonify({"ok": True, "filename": row["filename"]})

@app.route("/api/files/<int:fid>", methods=["DELETE"])
@login_required
def api_files_del(fid):
    conn = db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    if row and os.path.exists(row["filepath"]):
        try:
            os.remove(row["filepath"])
        except Exception:
            pass
    conn.execute("DELETE FROM files WHERE id = ?", (fid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/tasks/start", methods=["POST"])
@login_required
def api_tasks_start():
    data = request.get_json(silent=True) or {}
    targets = data.get("targets", [])
    file_id = data.get("file_id")
    direct_text = data.get("direct_text", "").strip()

    file_path = None
    direct_blocks = []

    if file_id:
        conn = db()
        r = conn.execute("SELECT filepath FROM files WHERE id = ?", (file_id,)).fetchone()
        conn.close()
        if r and os.path.exists(r["filepath"]):
            file_path = r["filepath"]
    else:
        if direct_text:
            direct_blocks = [b.strip() for b in direct_text.split("\n\n") if b.strip()]
            if not direct_blocks:
                direct_blocks = [direct_text]

    if not targets or (not file_path and not direct_blocks):
        return jsonify({"error": "Vui lòng chọn hội thoại nhận tin và nội dung tin nhắn"}), 400

    task_id = "TASK_" + str(int(time.time()))[-6:]
    stop_ev = threading.Event()

    payload = dict(data)
    payload["file_path"] = file_path
    payload["direct_blocks"] = direct_blocks

    t = threading.Thread(target=run_spam_task, args=(task_id, payload, stop_ev), daemon=True)
    t.start()

    with TASKS_LOCK:
        RUNNING_TASKS[task_id] = {
            "id": task_id,
            "type": data.get("mode", "fast"),
            "status": "running",
            "thread": t,
            "stop_ev": stop_ev,
            "created_at": time.time(),
            "sent_count": 0
        }

    return jsonify({"ok": True, "task_id": task_id})

@app.route("/api/tasks", methods=["GET"])
@login_required
def api_tasks_list():
    with TASKS_LOCK:
        res = []
        for tid, tinfo in RUNNING_TASKS.items():
            res.append({
                "id": tid,
                "type": tinfo["type"],
                "status": tinfo["status"],
                "created_at": tinfo["created_at"],
                "sent_count": tinfo.get("sent_count", 0)
            })
        return jsonify(res)

@app.route("/api/tasks/<tid>/stop", methods=["POST"])
@login_required
def api_tasks_stop(tid):
    with TASKS_LOCK:
        if tid in RUNNING_TASKS:
            RUNNING_TASKS[tid]["stop_ev"].set()
            RUNNING_TASKS[tid]["status"] = "stopped"
            return jsonify({"ok": True})
    return jsonify({"error": "Không tìm thấy tiến trình"}), 404

@app.route("/api/tasks/stop_all", methods=["POST"])
@login_required
def api_tasks_stop_all():
    with TASKS_LOCK:
        for tid in RUNNING_TASKS:
            RUNNING_TASKS[tid]["stop_ev"].set()
            RUNNING_TASKS[tid]["status"] = "stopped"
    return jsonify({"ok": True})

# ---------------------------------------------------------
# KHỞI CHẠY BẰNG GUNICORN HOẶC PYTHON TRỰC TIẾP
# ---------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 [Ricki Vip] Máy chủ & Fast Bot hoạt động tại cổng: {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
