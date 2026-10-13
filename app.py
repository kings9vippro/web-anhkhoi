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

# BIẾN APP CHO GUNICORN (GIẢI QUYẾT LỖI GUNICORN TRÊN RENDER 100%)
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

# ---------------------------------------------------------
# BỘ GIÁP BẢO MẬT WEB & API
# ---------------------------------------------------------
class WebSecurityArmor:
    def __init__(self):
        self.lock = threading.Lock()
        self.req_history = defaultdict(list)
        self.failed_logins = defaultdict(list)
        self.blocked_ips = {}

    def check_rate_limit(self, ip, max_reqs=250, window=60):
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
                if len(fails) >= 6:
                    self.blocked_ips[ip] = now + 180
                    return False, "Đăng nhập sai quá 6 lần. Tạm khóa IP 3 phút."
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

    # Tự động nạp tài khoản từ biến môi trường Render nếu có
    z_imei = os.environ.get("ZALO_IMEI", "").strip()
    z_cookies = os.environ.get("ZALO_COOKIES", "").strip()
    d_token = os.environ.get("DISCORD_TOKEN", "").strip()

    if z_imei and z_cookies:
        exist = conn.execute("SELECT id FROM accounts WHERE platform = 'zalo' AND imei = ?", (z_imei,)).fetchone()
        if not exist:
            conn.execute("""
            INSERT INTO accounts (label, platform, imei, cookies, real_name, status, enabled, created_at)
            VALUES ('Zalo Env Account', 'zalo', ?, ?, 'Zalo User', 'live', 1, ?)
            """, (z_imei, z_cookies, time.time()))
            conn.commit()

    if d_token:
        exist = conn.execute("SELECT id FROM accounts WHERE platform = 'discord' AND token = ?", (d_token,)).fetchone()
        if not exist:
            conn.execute("""
            INSERT INTO accounts (label, platform, token, real_name, status, enabled, created_at)
            VALUES ('Discord Env Account', 'discord', ?, 'Discord User', 'live', 1, ?)
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

def apply_antiband_zalo_v4(text):
    if not text:
        return text
    SAFE_SPACES = [" ", "\u00a0", " \u200b", "\u2009", "\u200a", "\u202f"]
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
                if random.random() < 0.30:
                    new_words.append(random.choice(SAFE_SPACES))
                else:
                    new_words.append(" ")
        line_str = "".join(new_words)
        line_str = line_str.replace(". ", ".\u200b ").replace("! ", "!\u200b ").replace("? ", "?\u200b ")
        processed_lines.append(line_str)

    result = "\n".join(processed_lines)
    tail_len = random.randint(3, 6)
    tail = "".join(random.choice(SAFE_TAIL_CHARS) for _ in range(tail_len))
    result += tail
    return result

# ---------------------------------------------------------
# GIAO THỨC ZALO WEB NÂNG CAO
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
                              is_heading=True, color_offset=0, use_badge=True,
                              tag_header="", antiband=True):
        raw_lines = raw_text.split("\n")
        processed_lines = []

        for idx, line in enumerate(raw_lines):
            clean_line = line.strip()
            if not clean_line:
                processed_lines.append("")
                continue

            if antiband:
                clean_line = apply_antiband_zalo_v4(clean_line)

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
                styles.append({
                    "start": current_u16_pos,
                    "len": line_len,
                    "st": f"c_{clean_hex}"
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
                 mention_index=0, is_heading=True, color_offset=0, use_badge=True,
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
            time.sleep(random.uniform(0.5, 0.9))
        except Exception:
            pass

    def send_message(self, target_id, content, mentions=None, tag_all=False, antiband=True):
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
        if antiband:
            final_msg = apply_antiband_zalo_v4(final_msg)

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

def run_spam_task(task_id, payload, stop_ev):
    targets = payload.get("targets", [])
    file_path = payload.get("file_path")
    direct_blocks = payload.get("direct_blocks") or []
    delay = float(payload.get("delay", 1.2))
    mode = payload.get("mode", "fast")
    color_mode = payload.get("color_mode", "rainbow")
    fixed_color = payload.get("fixed_color", "red")
    tag_all = bool(payload.get("tag_all", False))
    antiband = bool(payload.get("antiband", True))
    combat_icon_mode = payload.get("combat_icon_mode", "mixed")
    combat_icon_count = int(payload.get("combat_icon_count", 3))

    reader = None
    if file_path and os.path.exists(file_path):
        reader = FastFileBlockReader(file_path)

    msg_idx = 0
    direct_idx = 0

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

            icon_str = ""
            if combat_icon_mode != "none":
                icon_str = " " + generate_combat_combo(combat_icon_mode, combat_icon_count)

            if mode == "treo_ngon":
                text = raw.replace("\r\n", "\n").replace("\r", "\n") + icon_str
                if target_plat == "zalo":
                    ok, res = client.send_adv(
                        text, target_id, color_mode=color_mode, fixed_color=fixed_color,
                        is_group=is_group, tag_all=tag_all, is_heading=True,
                        color_offset=msg_idx, antiband=antiband
                    )
                else:
                    ok, res = client.send_message(
                        target_id, text, tag_all=tag_all, antiband=antiband
                    )
                if ok:
                    with TASKS_LOCK:
                        if task_id in RUNNING_TASKS:
                            RUNNING_TASKS[task_id]["sent_count"] = RUNNING_TASKS[task_id].get("sent_count", 0) + 1
            else:
                lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
                for ln in lines:
                    if stop_ev.is_set():
                        break
                    msg_line = ln + icon_str
                    if target_plat == "zalo":
                        ok, res = client.send_adv(
                            msg_line, target_id, color_mode=color_mode, fixed_color=fixed_color,
                            is_group=is_group, tag_all=tag_all, is_heading=True,
                            color_offset=msg_idx, antiband=antiband
                        )
                    else:
                        ok, res = client.send_message(
                            target_id, msg_line, tag_all=tag_all, antiband=antiband
                        )
                    if ok:
                        with TASKS_LOCK:
                            if task_id in RUNNING_TASKS:
                                RUNNING_TASKS[task_id]["sent_count"] = RUNNING_TASKS[task_id].get("sent_count", 0) + 1
                    msg_idx += 1
                    time.sleep(delay * random.uniform(0.9, 1.2))
                continue

            msg_idx += 1
            time.sleep(delay * random.uniform(0.9, 1.2))

    if reader:
        reader.close()

    with TASKS_LOCK:
        if task_id in RUNNING_TASKS:
            RUNNING_TASKS[task_id]["status"] = "stopped"

MENU_TEXT = """👑 RICKI VIP — ĐIỀU HÀNH BẰNG LỆNH (ZALO & DISCORD) 👑
Bản quyền © Phạm Anh Khôi (Verified ✔)
────────────────────────────
📋 BẢNG DANH SÁCH LỆNH CHÍNH XÁC:

1️⃣ .menu | !menu
   👉 Hiện bảng hướng dẫn và danh sách toàn bộ lệnh.

2️⃣ .spam [nhanh|ngon|nhay] [delay] [màu]
   👉 Bắt đầu gửi tin tự động vào box chat này!
   👉 Ví dụ: .spam nhanh 1.2 rainbow
   👉 Ví dụ: .spam ngon 2.0 red

3️⃣ .stop | .stopall
   👉 Dừng ngay lập tức toàn bộ tiến trình đang gửi tin.

4️⃣ .tagall [nội dung]
   👉 Tag toàn bộ thành viên (@All trên Zalo / @everyone trên Discord).
   👉 Ví dụ: .tagall Dậy anh em ơi chiến nào!

5️⃣ .file [tên_file.txt]
   👉 Chọn tệp nội dung ngôn (VD: .file ngon.txt).
   👉 Bỏ trống để xem tệp đang chọn & danh sách tệp có sẵn.

6️⃣ .listfiles
   👉 Xem danh sách toàn bộ tệp ngôn đã lưu trên máy chủ.

7️⃣ .addfile <tên_file.txt> <nội dung>
   👉 Tạo hoặc lưu tệp ngôn mới trực tiếp từ box chat!

8️⃣ .settext <nội dung>
   👉 Dán trực tiếp văn bản cần gửi (thay thế tệp).

9️⃣ .color <rainbow|random|red|gold|green|blue|purple|pink|cyan>
   👉 Đổi màu chữ Zalo (áp dụng chuẩn 100% trong nhóm).

🔟 .status
   👉 Xem trạng thái tài khoản, tiến trình và số tin đã gửi.

1️⃣1️⃣ .boxes
   👉 Liệt kê danh sách các box chat / nhóm gần đây để lấy ID.

1️⃣2️⃣ .target <here | all | id1,id2>
   👉 Đặt mục tiêu gửi (mặc định: here - chính nhóm đang gõ lệnh).
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

    if cmd_name in ["menu", "help"]:
        return MENU_TEXT

    elif cmd_name == "status":
        z_clients, d_clients = get_active_clients()
        with TASKS_LOCK:
            running_tasks = [t for t in RUNNING_TASKS.values() if t.get("status") == "running"]
            total_sent = sum(t.get("sent_count", 0) for t in RUNNING_TASKS.values())

        file_name = os.path.basename(BOT_STATE["active_file"]) if BOT_STATE["active_file"] else "Chưa chọn (Dùng .file hoặc .settext)"
        if BOT_STATE["active_text"]:
            file_name = f"Văn bản trực tiếp ({len(BOT_STATE['active_text'])} ký tự)"

        rep = [
            "⚡ TRẠNG THÁI HỆ THỐNG RICKI VIP ⚡",
            "👤 Bản quyền: Phạm Anh Khôi (Verified ✔)",
            "────────────────────────────",
            f"🔷 Tài khoản Zalo hoạt động: {len(z_clients)}",
            f"🟣 Tài khoản Discord hoạt động: {len(d_clients)}",
            f"📁 Nguồn nội dung: {file_name}",
            f"🎯 Mục tiêu: {BOT_STATE['target_mode']} (ID: {target_id})",
            f"🎨 Màu chữ Zalo: {BOT_STATE['color_mode']} ({BOT_STATE['fixed_color']})",
            f"🚀 Tiến trình đang chạy: {len(running_tasks)}",
            f"📊 Tổng số tin đã gửi: {total_sent}",
            "────────────────────────────",
            "👉 Gõ .menu để xem hướng dẫn đầy đủ."
        ]
        return "\n".join(rep)

    elif cmd_name in ["listfiles", "files"]:
        txt_files = [f for f in os.listdir(UPLOAD_DIR) if f.endswith(".txt")]
        if not txt_files:
            return "📁 Thư mục hiện chưa có tệp .txt nào! Dùng lệnh: .addfile <tên_file.txt> <nội dung> để tạo mới."
        rep = ["📁 DANH SÁCH TỆP NGÔN TRÊN HỆ THỐNG:"]
        for idx, fn in enumerate(txt_files, 1):
            fp = os.path.join(UPLOAD_DIR, fn)
            sz = round(os.path.getsize(fp) / 1024, 1)
            rep.append(f"{idx}. {fn} ({sz} KB)")
        rep.append("────────────────────────────")
        rep.append("👉 Dùng lệnh: .file <tên_file> để chọn tệp cần gửi.")
        return "\n".join(rep)

    elif cmd_name == "file":
        if not cmd_args:
            current = os.path.basename(BOT_STATE["active_file"]) if BOT_STATE["active_file"] else "Chưa chọn"
            return f"📁 Tệp hiện tại: {current}\n👉 Dùng lệnh: .file <tên_tệp.txt> để chọn, hoặc .listfiles để xem danh sách."

        target_file = cmd_args.strip()
        fp = os.path.join(UPLOAD_DIR, target_file)
        if not os.path.exists(fp):
            candidates = [f for f in os.listdir(UPLOAD_DIR) if target_file.lower() in f.lower()]
            if candidates:
                fp = os.path.join(UPLOAD_DIR, candidates[0])
                target_file = candidates[0]
            else:
                return f"❌ Không tìm thấy tệp '{target_file}'! Gõ .listfiles để xem các tệp có sẵn."

        BOT_STATE["active_file"] = fp
        BOT_STATE["active_text"] = None
        sz = round(os.path.getsize(fp) / 1024, 1)
        return f"✔️ ĐÃ CHỌN TỆP: {target_file} ({sz} KB)!\n👉 Gõ .spam để bắt đầu gửi ngay lập tức!"

    elif cmd_name == "addfile":
        if " " not in cmd_args:
            return "⚠️ Cú pháp: .addfile <tên_file.txt> <nội dung văn bản>"
        fname, content = cmd_args.split(" ", 1)
        if not fname.endswith(".txt"):
            fname += ".txt"
        fp = os.path.join(UPLOAD_DIR, fname)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)
        BOT_STATE["active_file"] = fp
        BOT_STATE["active_text"] = None
        return f"✔️ ĐÃ TẠO TỆP THÀNH CÔNG: {fname}!\nĐã tự động đặt làm tệp nội dung chính. Gõ .spam để bắn tin!"

    elif cmd_name == "settext":
        if not cmd_args:
            return "⚠️ Cú pháp: .settext <nội dung văn bản cần gửi>"
        BOT_STATE["active_text"] = cmd_args
        BOT_STATE["active_file"] = None
        return f"✔️ ĐÃ LƯU VĂN BẢN TRỰC TIẾP ({len(cmd_args)} ký tự)!\n👉 Gõ .spam để gửi ngay!"

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

    elif cmd_name == "tagall":
        text = cmd_args if cmd_args else "Thông báo đến toàn thể thành viên!"
        if platform == "zalo" and client:
            client.send_adv(text, target_id, is_group=is_group, tag_all=True, is_heading=True)
            return None
        elif platform == "discord" and client:
            client.send_message(target_id, text, tag_all=True)
            return None
        return f"📢 Đã kích hoạt Tag @All: {text}"

    elif cmd_name == "spam":
        mode = "fast"
        delay = 1.2
        color = BOT_STATE["fixed_color"]
        color_mode = BOT_STATE["color_mode"]

        args = cmd_args.split()
        if len(args) >= 1:
            if args[0] in ["nhanh", "fast"]:
                mode = "fast"
            elif args[0] in ["ngon", "treo_ngon"]:
                mode = "treo_ngon"
            elif args[0] in ["nhay", "treo_nhay"]:
                mode = "treo_nhay"

        if len(args) >= 2:
            try:
                delay = float(args[1])
            except Exception:
                pass

        if len(args) >= 3:
            if args[2].lower() in ["rainbow", "random"]:
                color_mode = args[2].lower()
            else:
                color_mode = "fixed"
                color = args[2].lower()

        file_path = BOT_STATE["active_file"]
        direct_blocks = []
        if not file_path:
            if BOT_STATE["active_text"]:
                direct_blocks = [b.strip() for b in BOT_STATE["active_text"].split("\n\n") if b.strip()]
            else:
                return "❌ Chưa có nội dung gửi! Hãy dùng lệnh .file <tên_file> hoặc .settext <nội dung> trước."

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

        if not targets:
            return "❌ Không tìm thấy mục tiêu nhận tin! Mặc định gửi vào box chat hiện tại."

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

        return f"🚀 ĐÃ BẮT ĐẦU CHIẾN DỊCH GỬI TIN!\n🔹 Mã: {task_id}\n🔹 Chế độ: {mode.upper()}\n🔹 Tốc độ: {delay}s\n🔹 Màu: {color_mode.upper()}\n🔹 Mục tiêu: {len(targets)} box\n👉 Gõ .stop để dừng bất kỳ lúc nào."

    elif cmd_name in ["stop", "stopall"]:
        stopped = 0
        with TASKS_LOCK:
            for tid, tinfo in RUNNING_TASKS.items():
                if tinfo.get("status") == "running":
                    tinfo["stop_ev"].set()
                    tinfo["status"] = "stopped"
                    stopped += 1
        return f"🛑 ĐÃ DỪNG TOÀN BỘ TIẾN TRÌNH ({stopped} tiến trình đã dừng)! Hệ thống trở về trạng thái nghỉ."

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

# Luồng lắng nghe tự động Zalo
def zalo_listener_loop():
    print("🔷 [Zalo Listener] Khởi động luồng bắt lệnh tự động...")
    while True:
        try:
            z_clients, _ = get_active_clients()
            for acc_id, label, zc in z_clients:
                convs = zc.get_conversations()
                for c in convs[:15]:
                    grid = c["id"]
                    try:
                        pl = json.dumps({"grid": str(grid), "page": 1, "count": 4})
                        params = {"params": zc.encrypt(pl), "imei": zc.imei}
                        r = zc.session.post("https://chat.zalo.me/api/group/getmsg", data=params, timeout=6)
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
                                    if len(SEEN_MESSAGES) > 2000:
                                        SEEN_MESSAGES.clear()

                                text = str(m.get("message") or m.get("content") or "").strip()
                                if text.startswith((".", "!", "/")) or text.lower() == "menu":
                                    print(f"🔷 [Zalo Command] Nhận lệnh '{text}' từ nhóm {c['name']}")
                                    reply = execute_command(text, "zalo", grid, is_group=True, client=zc)
                                    if reply:
                                        zc.send_adv(reply, grid, is_group=True, is_heading=True)
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(3)

# Luồng lắng nghe tự động Discord
def discord_listener_loop():
    print("🟣 [Discord Listener] Khởi động luồng bắt lệnh tự động...")
    while True:
        try:
            _, d_clients = get_active_clients()
            for acc_id, label, dc in d_clients:
                boxes = dc.get_all_chat_boxes()
                for b in boxes[:15]:
                    cid = b["id"]
                    if cid.startswith("user_"):
                        continue
                    try:
                        r = dc.session.get(f"https://discord.com/api/v9/channels/{cid}/messages?limit=4", timeout=6)
                        if r.status_code == 200:
                            arr = r.json()
                            for m in arr:
                                mid = str(m.get("id"))
                                with SEEN_LOCK:
                                    if mid in SEEN_MESSAGES:
                                        continue
                                    SEEN_MESSAGES.add(mid)
                                    if len(SEEN_MESSAGES) > 2000:
                                        SEEN_MESSAGES.clear()

                                text = m.get("content", "").strip()
                                if text.startswith((".", "!", "/")) or text.lower() == "menu":
                                    print(f"🟣 [Discord Command] Nhận lệnh '{text}' từ {b['name']}")
                                    reply = execute_command(text, "discord", cid, is_group=(b["type"]=="group"), client=dc)
                                    if reply:
                                        dc.send_message(cid, reply)
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(3)

# KÍCH HOẠT CÁC LUỒNG BẮT LỆNH NGẦM NGAY KHI GUNICORN HOẶC PYTHON KHỞI CHẠY
LISTENERS_STARTED = False
LISTENERS_LOCK = threading.Lock()

def start_background_listeners():
    global LISTENERS_STARTED
    with LISTENERS_LOCK:
        if not LISTENERS_STARTED:
            LISTENERS_STARTED = True
            threading.Thread(target=zalo_listener_loop, daemon=True).start()
            threading.Thread(target=discord_listener_loop, daemon=True).start()
            print("🚀 [Ricki Vip] Đã kích hoạt nền Zalo & Discord Command Listeners!")

start_background_listeners()

# ---------------------------------------------------------
# CÁC TUYẾN ĐƯỜNG HTTP (FLASK ENDPOINTS)
# ---------------------------------------------------------
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

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Ricki Vip — Điều Hành Tự Động</title>
<style>
:root {
  --bg-page: #080c16;
  --bg-card: rgba(16, 24, 44, 0.94);
  --accent-primary: #3b82f6;
  --accent-indigo: #6366f1;
  --accent-green: #10b981;
  --accent-red: #ef4444;
  --txt-0: #ffffff;
  --txt-1: #e2e8f0;
  --txt-2: #94a3b8;
  --border-card: rgba(99, 102, 241, 0.22);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg-page); color: var(--txt-1); min-height: 100vh; padding: 18px 14px;
}
.container { max-width: 860px; margin: 0 auto; }
.card {
  background: var(--bg-card); border: 1px solid var(--border-card);
  border-radius: 18px; padding: 22px 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.4);
  margin-bottom: 18px;
}
.card h2 { font-size: 16px; font-weight: 800; color: #fff; margin-bottom: 14px; display: flex; align-items: center; justify-content: space-between; }
.header-box { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; flex-wrap: wrap; gap: 12px; }
.logo-title { display: flex; align-items: center; gap: 12px; }
.logo-img { width: 46px; height: 46px; border-radius: 12px; border: 1.5px solid var(--accent-primary); }
.verified-icon { width: 18px; height: 18px; vertical-align: middle; filter: drop-shadow(0 0 6px rgba(29, 155, 240, 0.7)); }
.live-pill { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 700; color: var(--accent-green); background: rgba(16, 185, 129, 0.12); padding: 6px 12px; border-radius: 20px; border: 1px solid rgba(16, 185, 129, 0.3); }
.live-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-green); box-shadow: 0 0 8px var(--accent-green); }
.form-group { margin-bottom: 14px; }
.form-group label { display: block; font-size: 11.5px; font-weight: 700; text-transform: uppercase; color: var(--txt-2); margin-bottom: 6px; }
input[type="text"], input[type="password"], textarea {
  width: 100%; padding: 11px 13px; background: rgba(8,12,22,0.9); border: 1px solid var(--border-card);
  border-radius: 10px; color: #fff; font-size: 13.5px; font-family: inherit;
}
input:focus, textarea:focus { outline: none; border-color: var(--accent-primary); box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25); }
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 11px 18px; border-radius: 10px; font-weight: 700; font-size: 13px;
  cursor: pointer; border: none; transition: all 0.2s ease;
}
.btn-primary { background: linear-gradient(135deg, var(--accent-indigo) 0%, var(--accent-primary) 100%); color: #fff; }
.btn-green { background: linear-gradient(135deg, #059669 0%, #10b981 100%); color: #fff; }
.cmd-box { background: rgba(8,12,22,0.92); border: 1px solid var(--border-card); border-radius: 12px; padding: 16px; font-family: monospace; font-size: 13px; line-height: 1.8; color: #38bdf8; overflow-x: auto; white-space: pre-wrap; }
</style>
</head>
<body>
<div class="container">
  <div class="header-box">
    <div class="logo-title">
      <img src="/logo" class="logo-img" alt="Logo">
      <div>
        <h1 style="font-size:19px; font-weight:800; color:#fff; display:flex; align-items:center; gap:6px;">
          Ricki Vip
          <svg viewBox="0 0 24 24" class="verified-icon"><path fill="#1d9bf0" d="M22.5 12.5c0-1.58-.875-2.95-2.148-3.6.154-.435.238-.905.238-1.4 0-2.21-1.79-4-4-4-.495 0-.965.084-1.4.238C14.45 2.475 13.08 1.6 11.5 1.6s-2.95.875-3.6 2.148c-.435-.154-.905-.238-1.4-.238-2.21 0-4 1.79-4 4 0 .495.084.965.238 1.4C1.475 9.55.6 10.92.6 12.5s.875 2.95 2.148 3.6c-.154.435-.238.905-.238 1.4 0 2.21 1.79 4 4 4 .495 0 .965-.084 1.4-.238 1.15 1.273 2.52 2.148 4.1 2.148s2.95-.875 3.6-2.148c.435.154.905.238 1.4.238 2.21 0 4-1.79 4-4 0-.495-.084-.965-.238-1.4 1.273-.65 2.148-2.02 2.148-3.6zm-12.79 4.31l-4.2-4.2 1.41-1.41 2.79 2.79 6.79-6.79 1.41 1.41-8.2 8.2z"/></svg>
        </h1>
        <p style="font-size:12px; color:var(--txt-2);">Bản quyền © Phạm Anh Khôi • Bot Lệnh Zalo & Discord</p>
      </div>
    </div>
    <div class="live-pill"><span class="live-dot"></span> Đang Chạy Trên Render</div>
  </div>

  <div class="card">
    <h2><span>Cấu Hình Nhanh Token & IMEI (Lưu 1 Lần)</span></h2>
    <form id="acc-form" onsubmit="saveAcc(event)">
      <div class="form-group">
        <label>Zalo IMEI (Zalo Web)</label>
        <input type="text" id="z-imei" placeholder="Nhập chuỗi IMEI Zalo...">
      </div>
      <div class="form-group">
        <label>Zalo Cookie (Dạng JSON hoặc String)</label>
        <textarea id="z-cookie" style="min-height:70px;" placeholder='[{"name":"zpw_sek","value":"..."}, ...]'></textarea>
      </div>
      <div class="form-group">
        <label>Discord User Account Token</label>
        <input type="password" id="d-token" placeholder="Dán mã Token tài khoản Discord...">
      </div>
      <button type="submit" class="btn btn-green" style="width:100%;">LƯU TÀI KHOẢN VÀ KÍCH HOẠT BOT ⚡</button>
    </form>
    <div id="save-msg" style="margin-top:10px; font-size:13px; font-weight:700;"></div>
  </div>

  <div class="card">
    <h2><span>Hướng Dẫn Gõ Lệnh Trực Tiếp (Zalo & Discord)</span></h2>
    <div style="font-size:13px; color:var(--txt-2); margin-bottom:12px;">
      Bạn chỉ cần mở Zalo hoặc Discord lên, nhắn tin vào <b>Nhóm</b>, <b>Bạn bè</b>, hoặc <b>Cloud của tôi (Zalo)</b> các lệnh bên dưới:
    </div>
    <div class="cmd-box">
.menu                        👉 Hiện bảng hướng dẫn & toàn bộ lệnh
.spam nhanh 1.2 rainbow       👉 Bắt đầu gửi tin siêu tốc đổi màu
.spam ngon 2.0 red           👉 Treo khối ngôn (2 giây / 1 tin)
.stop                        👉 Dừng toàn bộ tiến trình gửi tin
.tagall [nội dung]           👉 Tag @All Zalo & @everyone Discord
.file [tên_file.txt]         👉 Chọn tệp nội dung ngôn để gửi
.listfiles                   👉 Liệt kê toàn bộ tệp ngôn đã lưu
.addfile &lt;tên&gt; &lt;nội dung&gt;    👉 Tạo tệp mới ngay trong box chat
.color &lt;màu&gt;                👉 Đổi màu chữ Zalo (red, gold, green, blue...)
.status                      👉 Xem số tin đã gửi & tiến trình đang chạy
    </div>
  </div>
</div>

<script>
async function saveAcc(e){
  e.preventDefault();
  var imei = document.getElementById('z-imei').value.trim();
  var cookie = document.getElementById('z-cookie').value.trim();
  var token = document.getElementById('d-token').value.trim();
  var msg = document.getElementById('save-msg');
  msg.textContent = 'Đang lưu và khởi động...';
  msg.style.color = '#38bdf8';

  var res = await fetch('/api/quick_setup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ imei: imei, cookies: cookie, token: token })
  }).then(function(x){ return x.json(); });

  if(res.ok){
    msg.textContent = '✔️ Đã lưu thành công! Giờ bạn có thể vào Zalo/Discord gõ .menu là chạy luôn!';
    msg.style.color = '#10b981';
  } else {
    msg.textContent = '❌ Lỗi: ' + (res.error || 'Không thể lưu');
    msg.style.color = '#ef4444';
  }
}
</script>
</body>
</html>"""

@app.route("/")
def route_root():
    return render_template_string(HTML_DASHBOARD)

@app.route("/api/quick_setup", methods=["POST"])
def api_quick_setup():
    data = request.get_json(silent=True) or {}
    imei = data.get("imei", "").strip()
    cookies = data.get("cookies", "").strip()
    token = data.get("token", "").strip()

    conn = db()
    saved = []
    if imei and cookies:
        conn.execute("""
        INSERT INTO accounts (label, platform, imei, cookies, real_name, status, enabled, created_at)
        VALUES ('Zalo Main', 'zalo', ?, ?, 'Zalo User', 'live', 1, ?)
        """, (imei, cookies, time.time()))
        saved.append("Zalo")

    if token:
        conn.execute("""
        INSERT INTO accounts (label, platform, token, real_name, status, enabled, created_at)
        VALUES ('Discord Main', 'discord', ?, 'Discord User', 'live', 1, ?)
        """, (token, time.time()))
        saved.append("Discord")

    conn.commit()
    conn.close()

    start_background_listeners()

    if not saved:
        return jsonify({"error": "Vui lòng nhập ít nhất tài khoản Zalo hoặc Discord"}), 400

    return jsonify({"ok": True, "saved": saved})

# ---------------------------------------------------------
# KHỞI CHẠY BẰNG PYTHON HOẶC GUNICORN
# ---------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 [Ricki Vip] Đang chạy tại cổng: {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
