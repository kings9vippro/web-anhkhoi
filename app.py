# Bản quyền thuộc về Ricki Vip — Phiên Bản Giáng Sinh Noel Cao Cấp
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

# Cấu hình hệ thống & Mật khẩu truy cập
APP_PASSWORD = os.environ.get("APP_PASSWORD", "anhkhoidz")
DATA_DIR = os.environ.get("DATA_DIR", "/tmp/ricki_web")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "ricki_vip.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Khởi tạo Flask Application
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

# Bộ giáp bảo mật Web & API (Ricki Vip Security Armor)
class WebSecurityArmor:
    def __init__(self):
        self.lock = threading.Lock()
        self.req_history = defaultdict(list)
        self.failed_logins = defaultdict(list)
        self.blocked_ips = {}

    def check_rate_limit(self, ip, max_reqs=150, window=60):
        now = time.time()
        with self.lock:
            if ip in self.blocked_ips:
                if now < self.blocked_ips[ip]:
                    remain = int(self.blocked_ips[ip] - now)
                    return False, f"IP tạm thời bị giới hạn. Vui lòng chờ {remain}s."
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
                if len(fails) >= 5:
                    self.blocked_ips[ip] = now + 180
                    return False, "Đăng nhập sai quá 5 lần. Tạm khóa IP trong 3 phút."
            return True, None

SECURITY_ARMOR = WebSecurityArmor()

@app.before_request
def security_firewall_check():
    if request.path.startswith("/static"):
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

# Cơ sở dữ liệu SQLite
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
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT,
        platform TEXT,
        account_id INTEGER,
        target_id TEXT,
        status TEXT,
        message TEXT,
        created_at REAL
    )
    """)
    conn.commit()
    conn.close()

init_db()

# Bảng màu Zalo chuẩn xác & Huy hiệu màu tương thích mọi thiết bị
ZALO_PALETTE = [
    {"id": "red",     "name": "Đỏ Noel",      "hex": "e8453c", "badge": "🔴"},
    {"id": "gold",    "name": "Vàng Kim",     "hex": "f4a261", "badge": "🟡"},
    {"id": "green",   "name": "Xanh Thông",   "hex": "2a9d8f", "badge": "🟢"},
    {"id": "orange",  "name": "Cam Lửa",      "hex": "e76f51", "badge": "🟠"},
    {"id": "blue",    "name": "Xanh Băng",    "hex": "457b9d", "badge": "💎"},
    {"id": "purple",  "name": "Tím Mộng",     "hex": "9b5de5", "badge": "🟣"},
    {"id": "pink",    "name": "Hồng Tuyết",   "hex": "f72585", "badge": "🌸"},
    {"id": "cyan",    "name": "Xanh Ngọc",    "hex": "00b4d8", "badge": "🔵"},
]

# Kho icon sát thương & Cà khịa đối thủ
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
        pool = []
        pool.append(random.choice(ICONS_DAMAGE))
        pool.append(random.choice(ICONS_TROLL))
        pool.append(random.choice(ICONS_MOCK))
        if count > 3:
            all_icons = ICONS_DAMAGE + ICONS_TROLL + ICONS_MOCK + ICONS_ZALO_CLASSIC
            pool.extend(random.sample(all_icons, count - 3))
        chosen = pool[:count]
    else:
        chosen = []
    return " ".join(chosen)

# Hàm chống ban V3 siêu cấp: An toàn phông chữ tiếng Việt 100%
def apply_antiband_advanced(text):
    if not text:
        return text
    SAFE_SPACES = [" ", "\u00a0", " \u200b", "\u2009", "\u200a"]
    SAFE_TAIL_CHARS = ["\u200b", "\u200c", "\u200d", "\ufeff"]

    words = text.split(" ")
    out_words = []
    for i, w in enumerate(words):
        out_words.append(w)
        if i < len(words) - 1:
            if random.random() < 0.35:
                out_words.append(random.choice(SAFE_SPACES))
            else:
                out_words.append(" ")
    result = "".join(out_words)
    tail_len = random.randint(3, 7)
    tail = "".join(random.choice(SAFE_TAIL_CHARS) for _ in range(tail_len))
    result += tail
    return result

# Cơ chế Anti-Die-All bảo vệ tài khoản khi gặp Rate Limit
class AccountHealthManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.cool_down = {}
        self.fail_streak = defaultdict(int)

    def is_usable(self, acc_id):
        with self.lock:
            cd_until = self.cool_down.get(acc_id, 0)
            return time.time() >= cd_until

    def report_success(self, acc_id):
        with self.lock:
            self.fail_streak[acc_id] = 0

    def report_failure(self, acc_id, is_rate_limit=False):
        with self.lock:
            self.fail_streak[acc_id] += 1
            if is_rate_limit:
                self.cool_down[acc_id] = time.time() + 45
            elif self.fail_streak[acc_id] >= 3:
                self.cool_down[acc_id] = time.time() + 60

HEALTH_MGR = AccountHealthManager()

# Trình đọc tệp O(1) RAM streaming cho file 5MB+
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

# Tính độ dài UTF-16 code units chính xác cho Zalo Mention & Styles
def utf16_len(s):
    return len(s.encode("utf-16-le")) // 2

# Giao thức Zalo Web API Client
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
            raise Exception("Không thể trích xuất Secret Key (zpw_enk)")

    def _pad(self, s):
        bs = AES.block_size
        return s + (bs - len(s) % bs) * chr(bs - len(s) % bs).encode()

    def _unpad(self, s):
        return s[:-ord(s[len(s)-1:])]

    def encrypt(self, data_str):
        raw_key = self.secret_key
        if len(raw_key) < 32:
            key = raw_key.ljust(32, "0").encode("utf-8")[:32]
        else:
            key = raw_key.encode("utf-8")[:32]
        iv = bytes([0] * 16)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded = self._pad(data_str.encode("utf-8"))
        enc = cipher.encrypt(padded)
        return base64.b64encode(enc).decode("utf-8")

    def decrypt(self, enc_str):
        raw_key = self.secret_key
        if len(raw_key) < 32:
            key = raw_key.ljust(32, "0").encode("utf-8")[:32]
        else:
            key = raw_key.encode("utf-8")[:32]
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
                data_list = info.get("data", [])
                if isinstance(data_list, list):
                    for item in data_list:
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
                        "name": g.get("name", "Nhóm không tên"),
                        "type": "group"
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
                        "name": f.get("displayName", "Bạn bè"),
                        "type": "user"
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
                for m in mem_list:
                    if isinstance(m, dict):
                        uid = str(m.get("uid") or m.get("id") or m.get("userId") or "")
                        raw_name = m.get("dName") or m.get("displayName") or m.get("name")
                    else:
                        uid = str(m)
                        raw_name = None

                    if not uid:
                        continue

                    final_name = fmap.get(uid) or raw_name or f"Thành viên {uid[-4:]}"
                    members.append({"id": uid, "name": final_name})
        except Exception:
            pass
        return members

    def build_colored_message(self, raw_text, color_mode, fixed_color, is_heading=True, color_offset=0, use_badge=True):
        lines = [l for l in raw_text.split("\n")]
        styled_lines = []
        styles = []
        current_u16_pos = 0
        first_color = "red"

        for idx, line in enumerate(lines):
            clean_line = line.strip()
            if not clean_line:
                styled_lines.append("")
                current_u16_pos += 1
                continue

            if color_mode == "rainbow":
                color_idx = (idx + color_offset) % len(ZALO_PALETTE)
                col = ZALO_PALETTE[color_idx]
            elif color_mode == "random":
                col = random.choice(ZALO_PALETTE)
            elif color_mode == "fixed":
                col = next((c for c in ZALO_PALETTE if c["id"] == fixed_color), ZALO_PALETTE[0])
            else:
                col = ZALO_PALETTE[0]

            if idx == 0:
                first_color = col["id"]

            prefix = ""
            if use_badge:
                prefix += col["badge"] + " "
            if is_heading:
                prefix = "# " + prefix

            display_line = prefix + clean_line
            styled_lines.append(display_line)

            clean_hex = col["hex"].lstrip("#")
            l_len = utf16_len(display_line)

            styles.append({"start": current_u16_pos, "len": l_len, "st": f"c_{clean_hex}"})
            styles.append({"start": current_u16_pos, "len": l_len, "st": f"c_#{clean_hex}"})
            styles.append({"offset": current_u16_pos, "len": l_len, "type": "color", "value": f"#{clean_hex}"})

            current_u16_pos += l_len + 1

        final_msg = "\n".join(styled_lines)
        return final_msg, styles, first_color

    def attach_mentions(self, msg, mentions=None, tag_all=False, tag_mode="rotate", mention_index=0, tag_pos="head"):
        m_arr = []
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
            return msg, []

        if tag_pos == "head":
            tags_str = " ".join([t["token"] for t in tag_tokens])
            curr_pos = 0
            for t in tag_tokens:
                tlen = utf16_len(t["token"])
                m_arr.append({
                    "uid": t["uid"],
                    "pos": curr_pos,
                    "offset": curr_pos,
                    "len": tlen,
                    "length": tlen,
                    "type": t["type"]
                })
                curr_pos += tlen + 1
            final_msg = tags_str + "\n" + msg
        else:
            base = msg.rstrip()
            curr_pos = utf16_len(base) + 1
            for t in tag_tokens:
                tlen = utf16_len(t["token"])
                m_arr.append({
                    "uid": t["uid"],
                    "pos": curr_pos,
                    "offset": curr_pos,
                    "len": tlen,
                    "length": tlen,
                    "type": t["type"]
                })
                curr_pos += tlen + 1
            final_msg = base + " " + " ".join([t["token"] for t in tag_tokens])

        return final_msg, m_arr

    def send_adv(self, raw_text, target_id, color_mode="rainbow", fixed_color="red",
                 is_group=True, mentions=None, tag_all=False, tag_mode="rotate",
                 mention_index=0, is_heading=True, color_offset=0, use_badge=True,
                 antiband=True, tag_pos="head"):

        content, styles, chosen_col = self.build_colored_message(
            raw_text, color_mode=color_mode, fixed_color=fixed_color,
            is_heading=is_heading, color_offset=color_offset, use_badge=use_badge
        )

        final_msg, m_arr = self.attach_mentions(
            content, mentions=mentions, tag_all=tag_all, tag_mode=tag_mode,
            mention_index=mention_index, tag_pos=tag_pos
        )

        if antiband:
            final_msg = apply_antiband_advanced(final_msg)

        ts = int(time.time() * 1000)
        c_item = next((c for c in ZALO_PALETTE if c["id"] == chosen_col), ZALO_PALETTE[0])
        hex_color = "#" + c_item["hex"].lstrip("#")

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
                "styles": styles,
                "msgColor": hex_color,
                "imei": self.imei
            }

        enc = self.encrypt(json.dumps(pl))
        params = {"params": enc, "imei": self.imei}
        r = self.session.post(url, data=params, timeout=12)
        res = r.json()
        if res.get("error_code") == 0:
            return True, res
        return False, res

# Discord Client dùng User Token cá nhân trực tiếp
class DiscordUserClient:
    def __init__(self, token):
        self.token = token.strip()
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": self.token,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Content-Type": "application/json"
        })

    def get_self(self):
        r = self.session.get("https://discord.com/api/v9/users/@me", timeout=10)
        if r.status_code == 200:
            return r.json()
        return None

    def get_channels_and_guilds(self):
        items = []
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
                            if c.get("type") in [0, 5]:
                                items.append({
                                    "id": str(c.get("id")),
                                    "name": f"[{gname}] #{c.get('name')}",
                                    "type": "group"
                                })
        except Exception:
            pass

        try:
            rdm = self.session.get("https://discord.com/api/v9/users/@me/channels", timeout=10)
            if rdm.status_code == 200:
                dms = rdm.json()
                for d in dms:
                    recips = d.get("recipients", [])
                    rname = ", ".join([u.get("username", "") for u in recips]) or "Kênh DM"
                    items.append({
                        "id": str(d.get("id")),
                        "name": f"[DM] {rname}",
                        "type": "user"
                    })
        except Exception:
            pass

        return items

    def send_message(self, channel_id, content, mentions=None, tag_all=False, antiband=True):
        final_msg = content
        if tag_all:
            final_msg = "@everyone " + final_msg
        if mentions:
            tags = " ".join([f"<@{m.get('id')}>" for m in mentions])
            final_msg = tags + " " + final_msg
        if antiband:
            final_msg = apply_antiband_advanced(final_msg)

        url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
        payload = {"content": final_msg}
        r = self.session.post(url, json=payload, timeout=12)
        if r.status_code in [200, 201]:
            return True, r.json()
        return False, {"error": r.text, "status": r.status_code}

# Giao diện Noel Glassmorphism CSS tối ưu 100% cho mọi thiết bị
CSS_NOEL = """
:root {
  --bg-page: #070b14;
  --bg-card: rgba(13, 22, 38, 0.88);
  --bg-glass: rgba(18, 30, 52, 0.7);
  --noel-red: #ef4444;
  --noel-red-dark: #b91c1c;
  --noel-green: #10b981;
  --noel-green-dark: #047857;
  --noel-gold: #fbbf24;
  --noel-ice: #38bdf8;
  --txt-0: #ffffff;
  --txt-1: #cbd5e1;
  --txt-2: #94a3b8;
  --border-gold: rgba(251, 191, 36, 0.3);
  --border-noel: rgba(239, 68, 68, 0.35);
  --shadow-gold: 0 0 20px rgba(251, 191, 36, 0.35);
  --shadow-red: 0 0 25px rgba(239, 68, 68, 0.45);
  --shadow-green: 0 0 25px rgba(16, 185, 129, 0.45);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}

* { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background-color: var(--bg-page);
  color: var(--txt-1);
  min-height: 100vh;
  padding-bottom: 120px;
  position: relative;
  overflow-x: hidden;
  background-image:
    radial-gradient(circle at 50% 0%, rgba(239, 68, 68, 0.18) 0%, transparent 60%),
    radial-gradient(circle at 85% 85%, rgba(16, 185, 129, 0.14) 0%, transparent 50%),
    radial-gradient(circle at 15% 90%, rgba(56, 189, 248, 0.12) 0%, transparent 50%);
}

#snow-canvas {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  pointer-events: none !important; z-index: 0 !important;
}

.header {
  position: sticky; top: 0; z-index: 100;
  background: rgba(7, 11, 20, 0.92);
  backdrop-filter: blur(25px); -webkit-backdrop-filter: blur(25px);
  border-bottom: 1.5px solid var(--border-gold);
  box-shadow: 0 4px 30px rgba(0, 0, 0, 0.7);
  padding: 12px 18px;
}
.header-inner {
  max-width: 980px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 12px;
}
.logo-box { display: flex; align-items: center; gap: 12px; }
.logo-badge {
  width: 44px; height: 44px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; font-size: 22px;
  background: linear-gradient(135deg, #ef4444 0%, #fbbf24 100%);
  border: 2px solid var(--noel-gold); box-shadow: var(--shadow-gold);
}
.header-meta h1 {
  font-family: 'Orbitron', sans-serif; font-size: 16px; font-weight: 900;
  color: #fff; letter-spacing: 0.6px; display: flex; align-items: center; gap: 6px;
  text-shadow: 0 0 12px rgba(251, 191, 36, 0.5);
}
.header-meta p {
  font-size: 11px; color: var(--txt-2); font-weight: 600; margin-top: 2px;
}

.container {
  max-width: 980px; margin: 0 auto; padding: 18px 14px;
  position: relative; z-index: 10;
}

.panel { display: none; }
.panel.active { display: block; animation: fadeIn .3s var(--ease); }
@keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

.card {
  background: var(--bg-card);
  backdrop-filter: blur(25px); -webkit-backdrop-filter: blur(25px);
  padding: 22px 18px; border-radius: 22px;
  border: 1.5px solid var(--border-gold);
  box-shadow: 0 15px 40px rgba(0, 0, 0, 0.6);
  margin-bottom: 18px; position: relative; overflow: hidden;
}
.card::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, var(--noel-red), var(--noel-gold), var(--noel-green));
}
.card h2 {
  font-size: 15px; font-weight: 900; color: #fff; margin-bottom: 16px;
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;
}

.form-group { margin-bottom: 16px; }
.form-group label {
  display: block; font-size: 11px; font-weight: 800; text-transform: uppercase;
  letter-spacing: 0.6px; color: var(--noel-gold); margin-bottom: 6px;
}

input[type="text"], input[type="password"], input[type="number"], select, textarea {
  width: 100%; padding: 12px 14px;
  background: rgba(6, 12, 22, 0.85);
  border: 1.5px solid rgba(255, 255, 255, 0.14);
  border-radius: 14px; color: #fff; font-size: 13px; font-family: inherit;
  transition: all 0.25s var(--ease);
}
input:focus, select:focus, textarea:focus {
  outline: none; border-color: var(--noel-gold);
  box-shadow: 0 0 15px rgba(251, 191, 36, 0.35);
  background: rgba(10, 18, 32, 0.95);
}
textarea { resize: vertical; min-height: 90px; }

.btn-pill {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  padding: 11px 20px; border-radius: 99px; font-weight: 800; font-size: 12px;
  cursor: pointer !important; border: none; transition: all 0.25s var(--ease);
  user-select: none; touch-action: manipulation !important;
}
.btn-pill:active { transform: scale(0.96) translateY(1px) !important; }
.btn-pill.primary {
  background: linear-gradient(135deg, var(--noel-red) 0%, var(--noel-red-dark) 100%);
  color: #fff; box-shadow: var(--shadow-red);
}
.btn-pill.green {
  background: linear-gradient(135deg, var(--noel-green) 0%, var(--noel-green-dark) 100%);
  color: #fff; font-weight: 900; box-shadow: var(--shadow-green);
}
.btn-pill.danger {
  background: rgba(239, 68, 68, 0.2); color: #fca5a5;
  border: 1.5px solid var(--noel-red);
}
.btn-pill.dark {
  background: rgba(255, 255, 255, 0.08); color: #fff;
  border: 1.5px solid var(--border-gold);
}
.btn-pill.full { width: 100%; padding: 13px; font-size: 13px; }

.chip-bar {
  display: flex; gap: 8px; overflow-x: auto; padding: 4px 0 8px;
  scrollbar-width: none;
}
.chip-bar::-webkit-scrollbar { display: none; }
.chip-item {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 14px; border-radius: 99px;
  background: rgba(255, 255, 255, 0.07);
  border: 1.5px solid rgba(255, 255, 255, 0.12);
  color: var(--txt-1); font-size: 11.5px; font-weight: 700;
  cursor: pointer !important; user-select: none;
  touch-action: manipulation !important; white-space: nowrap;
}
.chip-item:hover { border-color: var(--noel-gold); color: #fff; }
.chip-item.active {
  background: linear-gradient(135deg, var(--noel-red) 0%, var(--noel-gold) 100%) !important;
  color: #fff !important; border-color: transparent !important;
  box-shadow: 0 0 15px rgba(251, 191, 36, 0.5) !important;
}

.toggle-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px;
}
.toggle-item {
  background: rgba(6, 12, 22, 0.7);
  border: 1.5px solid rgba(255, 255, 255, 0.12);
  border-radius: 14px; padding: 12px 14px;
  display: flex; align-items: center; justify-content: space-between;
  font-size: 12px; font-weight: 700; color: var(--txt-1);
  cursor: pointer !important; user-select: none;
  touch-action: manipulation !important;
}
.toggle-item.active {
  border-color: var(--noel-green); background: rgba(16, 185, 129, 0.12);
  color: #fff; box-shadow: 0 0 15px rgba(16, 185, 129, 0.2);
}

.box-list {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px; max-height: 380px; overflow-y: auto; padding: 4px;
}
.box-item {
  background: rgba(6, 12, 22, 0.75);
  border: 1.5px solid rgba(255, 255, 255, 0.12);
  border-radius: 14px; padding: 12px;
  display: flex; align-items: center; gap: 10px;
  cursor: pointer !important; touch-action: manipulation !important;
}
.box-item:hover { border-color: var(--noel-gold); }
.box-item.selected {
  border-color: var(--noel-green); background: rgba(16, 185, 129, 0.15);
}
.check-mark {
  width: 22px; height: 22px; border-radius: 6px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 900;
}
.box-item.selected .check-mark {
  background: var(--noel-green); border-color: var(--noel-green); color: #000;
}
.b-title { font-size: 12.5px; font-weight: 800; color: #fff; }
.b-sub { font-size: 10.5px; color: var(--txt-2); margin-top: 2px; }

.bottom-dock {
  position: fixed; bottom: 14px; left: 50%; transform: translateX(-50%);
  width: calc(100% - 24px); max-width: 500px;
  background: rgba(10, 18, 32, 0.94);
  backdrop-filter: blur(30px); -webkit-backdrop-filter: blur(30px);
  border: 1.5px solid var(--border-gold); border-radius: 99px;
  padding: 6px 10px; display: flex; justify-content: space-around;
  box-shadow: 0 14px 45px rgba(0, 0, 0, 0.8), 0 0 20px rgba(251, 191, 36, 0.2);
  z-index: 999;
}
.dock-btn {
  background: none; border: none; color: var(--txt-2);
  cursor: pointer !important; touch-action: manipulation !important;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 2px; padding: 6px 12px; border-radius: 18px; transition: all 0.2s var(--ease);
}
.dock-btn svg { width: 20px; height: 20px; }
.dock-btn .dock-label { font-size: 10px; font-weight: 800; }
.dock-btn:hover { color: #fff; }
.dock-btn.active {
  background: linear-gradient(135deg, var(--noel-red) 0%, var(--noel-gold) 100%);
  color: #fff !important; box-shadow: 0 0 15px rgba(239, 68, 68, 0.6);
}

.table-wrap { overflow-x: auto; margin-top: 10px; }
.table { width: 100%; border-collapse: collapse; font-size: 12px; }
.table th, .table td { padding: 10px 12px; text-align: left; border-bottom: 1px solid rgba(255, 255, 255, 0.08); }
.table th { font-weight: 800; color: var(--noel-gold); font-size: 10.5px; }

#toast-stack {
  position: fixed; top: 16px; right: 16px; z-index: 99999;
  max-width: 320px; width: calc(100% - 32px); pointer-events: none;
}
.toast {
  background: rgba(13, 22, 38, 0.96); border: 1.5px solid var(--border-gold);
  border-radius: 16px; padding: 12px 16px; margin-bottom: 8px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.8); pointer-events: auto;
  animation: slideIn .25s var(--ease);
}
@keyframes slideIn { from { transform: translateX(50px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
.toast .t-head { font-weight: 900; font-size: 12px; color: var(--noel-gold); margin-bottom: 3px; display: flex; align-items: center; gap: 6px; }
.toast .t-body { font-size: 11.5px; color: #fff; }
"""

HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Đăng Nhập — RICKI VIP NOEL ❄️</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_NOEL + """
body { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 16px; }
.login-card {
  background: rgba(13, 22, 38, 0.92); border: 2px solid var(--border-gold);
  border-radius: 26px; padding: 34px 24px; max-width: 380px; width: 100%; text-align: center;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.8), var(--shadow-gold);
  position: relative; z-index: 10;
}
.login-logo {
  width: 76px; height: 76px; margin: 0 auto 16px; border-radius: 50%;
  background: linear-gradient(135deg, #ef4444 0%, #fbbf24 100%);
  display: flex; align-items: center; justify-content: center; font-size: 38px;
  border: 3px solid var(--noel-gold); box-shadow: var(--shadow-gold);
}
</style>
</head>
<body>
<canvas id="snow-canvas"></canvas>

<div class="login-card">
  <div class="login-logo">🎄</div>
  <h1 style="font-family:'Orbitron',sans-serif; font-size:18px; margin-bottom:4px; color:#fff;">RICKI VIP ❄️</h1>
  <p style="font-size:11.5px; color:var(--txt-2); margin-bottom:20px;">Hệ Thống Auto Đa Nền Tảng Giáng Sinh</p>

  <form method="POST" action="/login">
    <div class="form-group" style="text-align:left;">
      <label>MẬT KHẨU BẢO MẬT</label>
      <input type="password" name="password" placeholder="Nhập mật khẩu truy cập..." required autocomplete="current-password">
    </div>
    {% if error %}
    <div style="color:#fca5a5; font-size:12px; margin-bottom:14px; font-weight:700;">{{ error }}</div>
    {% endif %}
    <button type="submit" class="btn-pill primary full">ĐĂNG NHẬP HỆ THỐNG NOEL 🎄</button>
  </form>
</div>

<script>
var canvas = document.getElementById('snow-canvas');
var ctx = canvas.getContext('2d');
var width = canvas.width = window.innerWidth;
var height = canvas.height = window.innerHeight;
var flakes = [];
for (var i = 0; i < 75; i++) {
  flakes.push({ x: Math.random() * width, y: Math.random() * height, r: Math.random() * 3 + 1, d: Math.random() * 1.5 });
}
function drawSnow() {
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
  ctx.beginPath();
  for (var i = 0; i < flakes.length; i++) {
    var f = flakes[i];
    ctx.moveTo(f.x, f.y);
    ctx.arc(f.x, f.y, f.r, 0, Math.PI * 2, true);
  }
  ctx.fill();
  for (var i = 0; i < flakes.length; i++) {
    var f = flakes[i];
    f.y += Math.cos(f.d) + 1.2 + f.r / 2;
    f.x += Math.sin(f.d) * 0.7;
    if (f.x > width + 5 || f.x < -5 || f.y > height) {
      flakes[i] = { x: Math.random() * width, y: -10, r: f.r, d: f.d };
    }
  }
  requestAnimationFrame(drawSnow);
}
drawSnow();
window.onresize = function(){ width = canvas.width = window.innerWidth; height = canvas.height = window.innerHeight; };
</script>
</body>
</html>"""

HTML_MAIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>RICKI VIP — CHIẾN HẠM GIÁNG SINH NOEL 🎄</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_NOEL + """
</style>
</head>
<body>
<canvas id="snow-canvas"></canvas>

<div class="header">
  <div class="header-inner">
    <div class="logo-box">
      <div class="logo-badge">🎄</div>
      <div class="header-meta">
        <h1>RICKI VIP ❄️</h1>
        <p>Phiên Bản Giáng Sinh Noel • Zalo & Discord Acc</p>
      </div>
    </div>
    <div>
      <a href="/logout" class="btn-pill danger" style="padding:6px 14px; font-size:11px;">Đăng Xuất</a>
    </div>
  </div>
</div>

<div class="container">
  <!-- TAB 1: TÀI KHOẢN -->
  <div class="panel active" id="panel-accounts">
    <div class="card">
      <h2>
        <span>Quản Lý Tài Khoản Đa Nền Tảng</span>
        <button type="button" class="btn-pill dark" onclick="checkAllAccounts()" style="font-size:10.5px; padding:6px 12px;">Kiểm Tra Toàn Bộ</button>
      </h2>

      <div style="display:flex; gap:10px; margin-bottom:16px;">
        <button type="button" class="btn-pill primary" id="btn-plat-zalo" onclick="setPlatform('zalo')" style="flex:1;">🔷 Zalo Web (Cookie + IMEI)</button>
        <button type="button" class="btn-pill dark" id="btn-plat-discord" onclick="setPlatform('discord')" style="flex:1;">🟣 Discord (User Token)</button>
      </div>

      <div class="form-group">
        <label>TÊN GỢI NHỚ NICK</label>
        <input type="text" id="acc-label" placeholder="VD: Nick Chính, Clone 1, Acc Discord...">
      </div>

      <!-- FORM ZALO -->
      <div id="form-zalo">
        <div class="form-group">
          <label>ZALO IMEI</label>
          <input type="text" id="acc-imei" placeholder="Nhập chuỗi IMEI Zalo Web">
        </div>
        <div class="form-group">
          <label>ZALO COOKIE (Định dạng JSON hoặc Cookie String)</label>
          <textarea id="acc-cookies" placeholder='[{"name":"zpw_sek", "value":"..."}, ...]'></textarea>
        </div>
      </div>

      <!-- FORM DISCORD -->
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
            <tr><td colspan="6" style="text-align:center; padding:16px;">Đang tải dữ liệu...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 2: HỘI THOẠI & KÊNH -->
  <div class="panel" id="panel-boxes">
    <div class="card">
      <h2><span>Chọn Mục Tiêu Gửi Tin (Nhóm Zalo / Kênh Discord)</span></h2>
      <div style="display:flex; gap:10px; margin-bottom:14px; flex-wrap:wrap;">
        <select id="load-acc-select" style="flex:1; min-width:200px;"><option value="">-- Chọn tài khoản nạp danh sách --</option></select>
        <button type="button" class="btn-pill green" onclick="loadBoxes()">Nạp Danh Sách</button>
        <button type="button" class="btn-pill dark" onclick="selectAllBoxes()">Chọn Tất Cả</button>
        <button type="button" class="btn-pill danger" onclick="clearAllBoxes()">Bỏ Chọn</button>
      </div>

      <div style="font-size:12px; font-weight:800; color:var(--noel-gold); margin-bottom:10px;">
        ĐÃ CHỌN: <span id="selected-count" style="color:var(--noel-green); font-size:15px; font-weight:900;">0</span> HỘI THOẠI
      </div>

      <div class="box-list" id="box-list">
        <div style="padding:16px; text-align:center; color:var(--txt-2); grid-column: 1/-1;">Vui lòng chọn tài khoản và bấm "Nạp Danh Sách"</div>
      </div>
    </div>
  </div>

  <!-- TAB 3: TẬP TIN NỘI DUNG (HỖ TRỢ 5MB+) -->
  <div class="panel" id="panel-files">
    <div class="card">
      <h2><span>Quản Lý Tệp Ngôn Lớn (5MB - 50MB+ Streaming O(1) RAM)</span></h2>
      <div style="border: 2px dashed var(--border-gold); border-radius: 18px; padding: 24px; text-align: center; margin-bottom: 16px; background: rgba(251, 191, 36, 0.04);">
        <input type="file" id="file-input" accept=".txt" style="display:none;" onchange="handleFileSelected(this)">
        <button type="button" class="btn-pill dark" onclick="document.getElementById('file-input').click()" style="margin-bottom:8px;">CHỌN TỆP .TXT TỪ THIẾT BỊ 📁</button>
        <div id="upload-txt" style="font-size:12px; color:var(--txt-2);">Hỗ trợ tệp văn bản cực lớn (mỗi khối ngôn cách nhau 1 dòng trống)</div>
      </div>
      <button type="button" class="btn-pill green full" onclick="uploadFile()">TẢI LÊN & XỬ LÝ TỆP TIN ⚡</button>
    </div>

    <div class="card">
      <h2><span>Danh Sách Tệp Đã Lưu Trên Máy Chủ</span></h2>
      <div class="box-list" id="files-list">
        <div style="text-align:center; padding:16px; color:var(--txt-2); grid-column: 1/-1;">Chưa có tập tin nào</div>
      </div>
    </div>
  </div>

  <!-- TAB 4: GỬI TIN TỰ ĐỘNG -->
  <div class="panel" id="panel-spam">
    <div class="card">
      <h2><span>Cấu Hình Chiến Dịch Gửi Tin Noel 🎄</span></h2>

      <div class="form-group">
        <label>1. Chế độ gửi tin</label>
        <div class="chip-bar" id="spam-mode-bar">
          <button type="button" class="chip-item active" data-mode="fast">⚡ Siêu Nhanh (Gửi từng dòng)</button>
          <button type="button" class="chip-item" data-mode="treo_ngon">📜 Treo Ngôn (N Dòng / 1 Tin)</button>
          <button type="button" class="chip-item" data-mode="treo_nhay">🔥 Treo Nhây (Bắn câu liên tục)</button>
        </div>
        <input type="hidden" id="spam-mode" value="fast">
      </div>

      <div class="form-group">
        <label>2. Nguồn nội dung tin nhắn</label>
        <select id="spam-file-select" style="margin-bottom:8px;"><option value="">-- Dán nội dung trực tiếp bên dưới --</option></select>
        <textarea id="spam-messages" placeholder="Nhập nội dung tin nhắn cần gửi... (Mỗi khối ngôn cách nhau bởi 1 dòng trống)"></textarea>
      </div>

      <div class="form-group" style="background:rgba(239,68,68,0.06); border:1.5px solid rgba(239,68,68,0.25); border-radius:18px; padding:14px;">
        <label style="color:var(--noel-red); font-size:11.5px;">💥 PHỐI ICON SÁT THƯƠNG & CHỌC TỨC ĐỐI THỦ</label>
        <div class="chip-bar" id="combat-icon-bar">
          <button type="button" class="chip-item active" data-ic="mixed">👑 Combo Đồ Sát (1 Sát Thương + 1 Chọc Tức + 1 Cười Đểu)</button>
          <button type="button" class="chip-item" data-ic="damage">💀 Icon Sát Thương (💀💥🔥⚡🩸⚰️)</button>
          <button type="button" class="chip-item" data-ic="troll">🤡 Icon Chọc Tức (🤡🤫🖕💩👎🥱)</button>
          <button type="button" class="chip-item" data-ic="mock">🤣 Icon Cười Đểu (🤣😏🤪🤭😹👀)</button>
          <button type="button" class="chip-item" data-ic="none">Tắt Icon</button>
        </div>
        <input type="hidden" id="combat-icon-mode" value="mixed">
        <div style="display:flex; align-items:center; gap:8px; margin-top:8px;">
          <span style="font-size:11px; color:var(--txt-1);">Số lượng icon ghép mỗi tin:</span>
          <select id="combat-icon-count" style="width:85px; padding:5px 8px; font-size:11px;">
            <option value="2">2 Icon</option>
            <option value="3" selected>3 Icon</option>
            <option value="4">4 Icon</option>
            <option value="6">6 Icon</option>
          </select>
        </div>
      </div>

      <div class="form-group">
        <label>3. Tính năng bảo vệ & Tag tên</label>
        <div class="toggle-grid">
          <button type="button" class="toggle-item active" id="tg-antiband" onclick="tgFlag('antiband')">
            <span>🛡️ Anti-Ban V3 (An Toàn Font 100%)</span>
          </button>
          <button type="button" class="toggle-item active" id="tg-antidieall" onclick="tgFlag('antidieall')">
            <span>🔒 Anti-Die-All (Tự Cách Ly 429)</span>
          </button>
          <button type="button" class="toggle-item active" id="tg-badge" onclick="tgFlag('badge')">
            <span>🎨 Huy Hiệu Màu (Hiện Mọi Thiết Bị)</span>
          </button>
          <button type="button" class="toggle-item" id="tg-all" onclick="tgFlag('all')">
            <span>📢 Tag @All (Tất Cả Thành Viên)</span>
          </button>
          <button type="button" class="toggle-item active" id="tg-heading" onclick="tgFlag('heading')">
            <span>Chữ To Tiêu Đề (#)</span>
          </button>
          <button type="button" class="toggle-item active" id="tg-multi" onclick="tgFlag('multi')">
            <span>Gửi Cả 2 App (Zalo & Discord)</span>
          </button>
        </div>
      </div>

      <!-- TÙY CHỌN VỊ TRÍ TAG @ALL -->
      <div id="tag-all-options" style="display:none; margin-bottom:14px; background:rgba(56,189,248,0.06); border:1.5px solid rgba(56,189,248,0.25); border-radius:14px; padding:12px;">
        <label style="color:var(--noel-ice); font-size:11px;">VỊ TRÍ GẮN THẺ @ALL</label>
        <div style="display:flex; gap:16px; margin-top:6px; font-size:12px;">
          <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
            <input type="radio" name="tag_pos" value="head" checked> Đặt ở ĐẦU tin nhắn (Khuyên dùng - Nổ chuông 100%)
          </label>
          <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
            <input type="radio" name="tag_pos" value="tail"> Đặt ở CUỐI tin nhắn
          </label>
        </div>
      </div>

      <!-- MÀU SẮC -->
      <div class="form-group">
        <label>4. Màu sắc chữ Zalo (Đổi màu chuẩn 100% trong nhóm)</label>
        <div class="chip-bar" id="color-mode-bar">
          <button type="button" class="chip-item active" data-cmode="rainbow">🌈 Trộn Màu Từng Dòng (Rainbow)</button>
          <button type="button" class="chip-item" data-cmode="random">🎲 Đổi Màu Ngẫu Nhiên</button>
          <button type="button" class="chip-item" data-cmode="fixed">🎯 Cố Định 1 Màu</button>
        </div>
        <input type="hidden" id="color-mode" value="rainbow">

        <div id="fixed-colors-wrap" style="display:none; gap:6px; flex-wrap:wrap; margin-top:10px;">
          <button type="button" class="chip-item active" onclick="setFixedColor('red')" style="border-color:#e8453c;">🔴 Đỏ Noel</button>
          <button type="button" class="chip-item" onclick="setFixedColor('gold')" style="border-color:#f4a261;">🟡 Vàng Kim</button>
          <button type="button" class="chip-item" onclick="setFixedColor('green')" style="border-color:#2a9d8f;">🟢 Xanh Thông</button>
          <button type="button" class="chip-item" onclick="setFixedColor('orange')" style="border-color:#e76f51;">🟠 Cam Lửa</button>
          <button type="button" class="chip-item" onclick="setFixedColor('blue')" style="border-color:#457b9d;">💎 Xanh Băng</button>
          <button type="button" class="chip-item" onclick="setFixedColor('purple')" style="border-color:#9b5de5;">🟣 Tím Mộng</button>
          <button type="button" class="chip-item" onclick="setFixedColor('pink')" style="border-color:#f72585;">🌸 Hồng Tuyết</button>
        </div>
      </div>

      <!-- TỐC ĐỘ GỬI -->
      <div class="form-group">
        <label>5. Tốc độ gửi tin (Thời gian Delay)</label>
        <div class="chip-bar" id="delay-bar">
          <button type="button" class="chip-item" data-val="0.3">⚡ Siêu Tốc (0.3s)</button>
          <button type="button" class="chip-item" data-val="0.7">🚀 Nhanh (0.7s)</button>
          <button type="button" class="chip-item active" data-val="1.2">🛡️ Vừa Phải (1.2s - An toàn)</button>
          <button type="button" class="chip-item" data-val="2.5">🐢 Chậm Rãi (2.5s)</button>
        </div>
        <input type="number" id="delay-val" value="1.2" step="0.1" min="0.1" style="margin-top:6px;">
      </div>

      <!-- QUẢN LÝ TAG THÀNH VIÊN -->
      <div class="form-group" style="background:rgba(255,255,255,0.03); border:1.5px solid rgba(255,255,255,0.1); border-radius:18px; padding:14px;">
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
          <input type="checkbox" id="tg-tag" onchange="tgTag()">
          <span>BẬT TAG TÊN THÀNH VIÊN NHÓM</span>
        </label>

        <div id="tag-wrap" style="display:none; margin-top:10px;">
          <div style="display:flex; gap:14px; margin-bottom:10px; font-size:12px;">
            <label style="cursor:pointer;"><input type="radio" name="tag_mode" value="rotate" checked> 🔄 Tag Luân Phiên (Xoay Vòng)</label>
            <label style="cursor:pointer;"><input type="radio" name="tag_mode" value="all"> 👥 Tag Cùng Lúc Toàn Bộ</label>
          </div>

          <div style="margin-bottom:10px;">
            <label style="font-size:10.5px;">NHẬP TRỰC TIẾP TÊN/UID CẦN TAG (Cách nhau bởi dấu phẩy):</label>
            <input type="text" id="manual-tags-inp" placeholder="VD: Khôi, Admin, Nam, 123456...">
          </div>

          <div style="display:flex; gap:8px; margin-bottom:8px; flex-wrap:wrap;">
            <select id="member-group-select" style="flex:1; min-width:180px;"><option value="">-- Chọn nhóm Zalo để quét --</option></select>
            <button type="button" class="btn-pill dark" onclick="loadMembers()">Quét Thành Viên</button>
            <button type="button" class="btn-pill green" onclick="selectAllMembers()">Chọn Tất Cả</button>
            <button type="button" class="btn-pill danger" onclick="clearAllMembers()">Bỏ Chọn</button>
          </div>

          <div style="font-size:11.5px; font-weight:800; color:var(--noel-gold); margin-bottom:6px;">
            ĐÃ CHỌN: <span id="tag-count" style="color:var(--noel-red); font-size:13px; font-weight:900;">0</span> THÀNH VIÊN
          </div>
          <div class="box-list" id="tag-selector" style="display:none; max-height:200px;"></div>
        </div>
      </div>

      <!-- BẢNG ĐIỀU KHIỂN TÁC VỤ NOEL -->
      <div style="display:flex; gap:12px; margin-top:20px;">
        <button type="button" class="btn-pill green full" onclick="startSpam()" style="padding:15px; font-size:14px; font-weight:900;">
          🚀 BẮT ĐẦU GỬI NGAY
        </button>
        <button type="button" class="btn-pill danger full" onclick="stopAll()" style="padding:15px; font-size:14px; font-weight:900;">
          🛑 DỪNG TẤT CẢ
        </button>
      </div>
    </div>

    <!-- TIẾN TRÌNH ĐANG CHẠY -->
    <div class="card">
      <h2><span>Tiến Trình Gửi Tin Đang Chạy</span></h2>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>CHẾ ĐỘ</th>
              <th>TRẠNG THÁI</th>
              <th>THAO TÁC</th>
            </tr>
          </thead>
          <tbody id="task-table-body">
            <tr><td colspan="4" style="text-align:center; padding:14px;">Chưa có tiến trình nào</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 5: HƯỚNG DẪN & TÀI LIỆU -->
  <div class="panel" id="panel-docs">
    <div class="card">
      <h2><span>Hướng Dẫn Vận Hành & Khắc Phục Lỗi</span></h2>
      <div style="font-size:12.5px; line-height:1.7; color:var(--txt-1);">
        <p style="margin-bottom:12px;"><b style="color:var(--noel-gold);">1. Đổi màu chữ Zalo 100%:</b> Để tin nhắn đổi màu rực rỡ, bắt buộc phải gửi vào <b>Nhóm Chat (Group)</b>. Hệ thống tự động nhúng cả 3 mã màu CSS Web, Desktop và mã màu Mobile kèm <b>Huy hiệu màu emoji</b> (🔴 🟡 🟢 💎) ở đầu dòng giúp hiển thị màu sắc rực rỡ trên cả màn hình điện thoại!</p>
        <p style="margin-bottom:12px;"><b style="color:var(--noel-gold);">2. Tag @All & Tag Tên 100%:</b> Thẻ tag được gắn ở đầu tin nhắn dạng JSON Array độc lập, không bị xung đột với Markdown Header (#), đảm bảo rung chuông thông báo 100% cho mọi người.</p>
        <p style="margin-bottom:12px;"><b style="color:var(--noel-gold);">3. Cách lấy Discord User Token:</b> Mở Discord trên trình duyệt máy tính -> Nhấn F12 -> Chuyển sang tab Network -> Gửi 1 tin nhắn -> Bấm vào request messages -> Tìm dòng <code>authorization</code> trong Request Headers.</p>
        <p style="margin-bottom:12px;"><b style="color:var(--noel-gold);">4. Anti-Ban V3 & Tệp 5MB+:</b> Động cơ streaming O(1) RAM xử lý tệp 5MB - 50MB+ siêu tốc. Hàm Anti-Ban V3 không cắt vào giữa từ tiếng Việt, đảm bảo phông chữ hiển thị nguyên vẹn 100% không bao giờ vỡ nét hay rớt dấu.</p>
      </div>
    </div>
  </div>
</div>

<!-- DOCK ĐIỀU HƯỚNG NOEL DUY NHẤT Ở ĐÁY MÀN HÌNH -->
<div class="bottom-dock">
  <button type="button" class="dock-btn active" data-tab="accounts" onclick="showTab('accounts')">
    <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
    <span class="dock-label">Tài khoản</span>
  </button>
  <button type="button" class="dock-btn" data-tab="boxes" onclick="showTab('boxes')">
    <svg viewBox="0 0 24 24" fill="currentColor"><path d="M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM6 9h12v2H6V9zm8 5H6v-2h8v2zm4-6H6V6h12v2z"/></svg>
    <span class="dock-label">Hội thoại</span>
  </button>
  <button type="button" class="dock-btn" data-tab="files" onclick="showTab('files')">
    <svg viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>
    <span class="dock-label">Tập tin</span>
  </button>
  <button type="button" class="dock-btn" data-tab="spam" onclick="showTab('spam')">
    <svg viewBox="0 0 24 24" fill="currentColor"><path d="M13 2.05v3.03c3.39.49 6 3.39 6 6.92 0 .9-.18 1.75-.48 2.54l2.6 1.53c.56-1.24.88-2.62.88-4.07 0-5.18-3.95-9.45-9-9.95zM12 19c-3.87 0-7-3.13-7-7 0-3.53 2.61-6.43 6-6.92V2.05c-5.05.5-9 4.76-9 9.95 0 5.52 4.47 10 9.99 10 3.31 0 6.24-1.61 8.01-4.07l-2.49-1.46c-1.4 1.56-3.39 2.53-5.51 2.53z"/></svg>
    <span class="dock-label">Gửi tin</span>
  </button>
  <button type="button" class="dock-btn" data-tab="docs" onclick="showTab('docs')">
    <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z"/></svg>
    <span class="dock-label">Hướng dẫn</span>
  </button>
</div>

<div id="toast-stack"></div>

<script>
// Quản lý biến trạng thái hệ thống
var currentPlatform = 'zalo';
var currentMode = 'fast';
var colorMode = 'rainbow';
var fixedColor = 'red';
var _boxes = [];
var selectedBoxes = [];
var _members = [];
var selectedTags = [];
var flags = { antiband: true, antidieall: true, heading: true, multi: true, all: false, badge: true };

// Hệ thống Toast thông báo Noel
var Toast = (function(){
  var stack = null;
  function ensure(){ if(!stack) stack = document.getElementById('toast-stack'); }
  function show(title, msg, timeout){
    ensure();
    var t = document.createElement('div');
    t.className = 'toast';
    t.innerHTML = '<div class="t-head"><span>🎄</span><span>' + title + '</span></div><div class="t-body">' + msg + '</div>';
    stack.appendChild(t);
    setTimeout(function(){
      t.style.opacity = '0';
      t.style.transform = 'translateY(-10px)';
      setTimeout(function(){ if(t.parentNode) t.parentNode.removeChild(t); }, 300);
    }, timeout || 3000);
  }
  return {
    success: function(m){ show('Thành Công', m, 3000); },
    error: function(m){ show('Thông Báo', m, 4000); },
    info: function(m){ show('Thông Tin', m, 2500); }
  };
})();

// Chuyển Tab duy nhất mượt mà
function showTab(name){
  document.querySelectorAll('.panel').forEach(function(p){ p.classList.remove('active'); });
  document.querySelectorAll('.dock-btn').forEach(function(b){ b.classList.remove('active'); });
  var p = document.getElementById('panel-' + name);
  if(p) p.classList.add('active');
  var b = document.querySelector('.dock-btn[data-tab="' + name + '"]');
  if(b) b.classList.add('active');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Chuyển nền tảng Zalo / Discord
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

// Bật tắt cờ cấu hình
function tgFlag(name){
  flags[name] = !flags[name];
  var el = document.getElementById('tg-' + name);
  if(el) el.classList.toggle('active', flags[name]);
  if(name === 'all') {
    document.getElementById('tag-all-options').style.display = flags.all ? 'block' : 'none';
    if(flags.all) Toast.success('Đã BẬT Tag @All! Vị trí: ĐẦU tin nhắn (Nổ thông báo 100%)');
    else Toast.info('Đã tắt Tag @All.');
  }
}

function tgTag(){
  var c = document.getElementById('tg-tag');
  document.getElementById('tag-wrap').style.display = c.checked ? 'block' : 'none';
  if(c.checked) updateMemberGroupSelect();
}

function updateMemberGroupSelect(){
  var s = document.getElementById('member-group-select');
  var groups = _boxes.filter(function(b){ return b.type === 'group'; });
  if(!groups.length) groups = selectedBoxes.filter(function(b){ return b.type === 'group'; });
  var html = '<option value="">-- Chọn nhóm Zalo mục tiêu --</option>';
  groups.forEach(function(g){
    html += '<option value="' + g.id + '">' + g.name + ' (' + g.id + ')</option>';
  });
  s.innerHTML = html;
  if(groups.length > 0) s.value = groups[0].id;
}

// Đăng ký sự kiện các chip chọn chế độ
function bindChips(){
  document.querySelectorAll('#spam-mode-bar .chip-item').forEach(function(c){
    c.onclick = function(){
      document.querySelectorAll('#spam-mode-bar .chip-item').forEach(function(x){ x.classList.remove('active'); });
      c.classList.add('active');
      currentMode = c.dataset.mode;
      document.getElementById('spam-mode').value = currentMode;
    };
  });

  document.querySelectorAll('#combat-icon-bar .chip-item').forEach(function(c){
    c.onclick = function(){
      document.querySelectorAll('#combat-icon-bar .chip-item').forEach(function(x){ x.classList.remove('active'); });
      c.classList.add('active');
      document.getElementById('combat-icon-mode').value = c.dataset.ic;
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

function setFixedColor(cid){
  fixedColor = cid;
  document.querySelectorAll('#fixed-colors-wrap .chip-item').forEach(function(x){ x.classList.remove('active'); });
  if(event && event.target) event.target.classList.add('active');
  var col = ZALO_PALETTE.find(function(c){ return c.id === cid; });
  if(col) Toast.info('Đã chọn: ' + col.name);
}

function handleFileSelected(input){
  if(input.files && input.files.length > 0){
    document.getElementById('upload-txt').textContent = "Đã chọn: " + input.files[0].name + " (" + Math.round(input.files[0].size/1024) + " KB)";
    document.getElementById('upload-txt').style.color = "var(--noel-gold)";
  }
}

// Hàm gọi API trung tâm
async function api(url, opts){
  opts = opts || {};
  try {
    var r = await fetch(url, Object.assign({}, opts, {
      headers: Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {})
    }));
    return await r.json();
  } catch(e) {
    return { error: 'Không thể kết nối đến máy chủ' };
  }
}

// Quản lý Tài khoản
async function loadAccounts(){
  var accs = await api('/api/accounts');
  if(!Array.isArray(accs)) accs = [];
  var tb = document.getElementById('acc-table-body');
  tb.innerHTML = accs.map(function(a){
    var platIcon = (a.platform === 'discord') ? '🟣 Discord' : '🔷 Zalo';
    var realName = a.real_name || (a.platform === 'discord' ? 'Discord User' : 'Chưa quét danh tính');
    var isLive = (a.status === 'live');
    var badge = isLive ? '<span style="color:var(--noel-green); font-weight:900;">● HOẠT ĐỘNG</span>' : '<span style="color:var(--noel-red); font-weight:900;">● NGẮT KẾT NỐI</span>';
    return '<tr>' +
      '<td>' + a.id + '</td>' +
      '<td><b>' + platIcon + '</b></td>' +
      '<td><b>' + a.label + '</b></td>' +
      '<td><span style="color:var(--noel-gold); font-weight:800;">' + realName + '</span></td>' +
      '<td id="status-' + a.id + '">' + badge + '</td>' +
      '<td>' +
        '<button type="button" class="btn-pill dark" onclick="checkAccount(' + a.id + ')" style="padding:4px 10px; font-size:10px; margin-right:4px;">Kiểm Tra</button>' +
        '<button type="button" class="btn-pill danger" onclick="deleteAccount(' + a.id + ')" style="padding:4px 10px; font-size:10px;">Xóa</button>' +
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
    if(!payload.token) return Toast.error('Vui lòng nhập Token tài khoản Discord');
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
    if(el) el.innerHTML = '<span style="color:var(--noel-green); font-weight:900;">● HOẠT ĐỘNG</span>';
    Toast.success('Tài khoản hoạt động rất tốt!');
  } else {
    if(el) el.innerHTML = '<span style="color:var(--noel-red); font-weight:900;">● NGẮT KẾT NỐI</span>';
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

// Quản lý Hội thoại & Kênh
async function loadBoxes(){
  var aid = document.getElementById('load-acc-select').value;
  if(!aid) return Toast.error('Vui lòng chọn tài khoản trước');
  Toast.info('Đang nạp danh sách hội thoại...');
  var r = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  var all = r.boxes || [];
  var bl = document.getElementById('box-list');
  bl.innerHTML = all.map(function(b, i){
    return '<div class="box-item" onclick="tgBox(this, ' + i + ')">' +
      '<div class="check-mark">✓</div>' +
      '<div><div class="b-title">' + b.name + '</div><div class="b-sub">' + b.id + ' | ' + b.type + '</div></div>' +
    '</div>';
  }).join('') || '<div style="text-align:center; padding:16px;">Không tìm thấy hội thoại</div>';
  _boxes = all; selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
  Toast.success('Đã nạp ' + all.length + ' mục');
  updateMemberGroupSelect();
}

function tgBox(el, idx){
  var b = _boxes[idx];
  if(!b) return;
  if(el.classList.contains('selected')){
    el.classList.remove('selected');
    selectedBoxes = selectedBoxes.filter(function(x){ return x.id !== b.id; });
  } else {
    el.classList.add('selected');
    selectedBoxes.push(b);
  }
  document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function selectAllBoxes(){
  document.querySelectorAll('#box-list .box-item').forEach(function(el){ el.classList.add('selected'); });
  selectedBoxes = _boxes.slice();
  document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function clearAllBoxes(){
  document.querySelectorAll('#box-list .box-item').forEach(function(el){ el.classList.remove('selected'); });
  selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
}

// Quản lý Thành viên nhóm Zalo
function renderMemberItems(){
  var sel = document.getElementById('tag-selector');
  sel.innerHTML = _members.map(function(m){
    var isSel = selectedTags.some(function(t){ return t.id === m.id; });
    return '<div class="box-item ' + (isSel ? 'selected' : '') + '" onclick="toggleMemberById(\'' + m.id + '\')">' +
      '<div class="check-mark">✓</div>' +
      '<div><div class="b-title">' + m.name + '</div><div class="b-sub">UID: ' + m.id + '</div></div>' +
    '</div>';
  }).join('') || '<div style="padding:14px; text-align:center;">Không tìm thấy thành viên</div>';
}

function toggleMemberById(mid){
  var m = _members.find(function(x){ return x.id === mid; });
  if(!m) return;
  var exists = selectedTags.some(function(t){ return t.id === mid; });
  if(exists){
    selectedTags = selectedTags.filter(function(t){ return t.id !== mid; });
  } else {
    selectedTags.push({ id: m.id, name: m.name });
  }
  document.getElementById('tag-count').textContent = selectedTags.length;
  renderMemberItems();
}

function selectAllMembers(){
  selectedTags = _members.map(function(m){ return { id: m.id, name: m.name }; });
  document.getElementById('tag-count').textContent = selectedTags.length;
  renderMemberItems();
  Toast.success('Đã chọn tất cả ' + selectedTags.length + ' thành viên');
}

function clearAllMembers(){
  selectedTags = [];
  document.getElementById('tag-count').textContent = '0';
  renderMemberItems();
  Toast.info('Đã bỏ chọn tất cả thành viên');
}

async function loadMembers(){
  var gid = document.getElementById('member-group-select').value;
  if(!gid){
    var box = selectedBoxes.find(function(b){ return b.type === 'group'; });
    if(box) gid = box.id;
  }
  if(!gid) return Toast.error('Vui lòng chọn 1 nhóm Zalo để quét thành viên');
  Toast.info('Đang nạp danh sách thành viên...');
  var r = await api('/api/members/' + gid, { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  _members = r.members || [];
  selectedTags = [];
  document.getElementById('tag-count').textContent = '0';
  document.getElementById('tag-selector').style.display = 'grid';
  renderMemberItems();
  Toast.success('Đã nạp thành công ' + _members.length + ' thành viên!');
}

// Quản lý Tệp tin 5MB+
async function uploadFile(){
  var inp = document.getElementById('file-input');
  if(!inp.files || !inp.files.length) return Toast.error('Vui lòng chọn tệp .txt');
  var fd = new FormData();
  fd.append('file', inp.files[0]);
  Toast.info('Đang tải lên và xử lý tệp...');
  var r = await fetch('/api/files/upload', { method: 'POST', body: fd }).then(function(x){ return x.json(); });
  if(r.error) return Toast.error(r.error);
  Toast.success('Đã lưu: ' + r.lines + ' khối nội dung!');
  inp.value = '';
  document.getElementById('upload-txt').textContent = "Hỗ trợ tệp văn bản cực lớn (mỗi khối ngôn cách nhau 1 dòng trống)";
  loadFiles();
}

async function loadFiles(){
  var files = await api('/api/files');
  if(!Array.isArray(files)) files = [];
  var list = document.getElementById('files-list');
  list.innerHTML = files.map(function(f){
    return '<div class="box-item" style="justify-content:space-between;">' +
      '<div><div class="b-title">' + f.filename + '</div><div class="b-sub">' + f.lines + ' khối | ' + Math.round(f.size/1024) + ' KB</div></div>' +
      '<button type="button" class="btn-pill danger" onclick="deleteFile(' + f.id + ')" style="padding:4px 10px; font-size:10px;">Xóa</button>' +
    '</div>';
  }).join('') || '<div style="text-align:center; padding:16px; color:var(--txt-2); grid-column: 1/-1;">Chưa có tập tin nào</div>';

  var s = document.getElementById('spam-file-select');
  s.innerHTML = '<option value="">-- Dán nội dung trực tiếp bên dưới --</option>' + files.map(function(f){
    return '<option value="' + f.id + '">' + f.filename + ' (' + f.lines + ' khối - ' + Math.round(f.size/1024) + 'KB)</option>';
  }).join('');
}

async function deleteFile(fid){
  await api('/api/files/' + fid, { method: 'DELETE' });
  Toast.info('Đã xóa tập tin');
  loadFiles();
}

// Bắt đầu & Dừng tiến trình gửi tin
async function startSpam(){
  if(!selectedBoxes.length) return Toast.error('Chưa chọn hội thoại nhận tin! Hãy qua tab Hội thoại để chọn.');
  var fid = document.getElementById('spam-file-select').value;
  var direct = document.getElementById('spam-messages').value.trim();
  if(!fid && !direct) return Toast.error('Vui lòng nhập nội dung hoặc chọn tập tin');

  var delay = parseFloat(document.getElementById('delay-val').value) || 1.2;
  var combatIconMode = document.getElementById('combat-icon-mode').value;
  var combatIconCount = parseInt(document.getElementById('combat-icon-count').value) || 3;

  var tagUsers = document.getElementById('tg-tag').checked ? selectedTags.slice() : [];
  var manualTags = document.getElementById('manual-tags-inp').value.trim();
  if(manualTags){
    var rawNames = manualTags.split(/[,\n]/).map(function(x){ return x.trim(); }).filter(Boolean);
    rawNames.forEach(function(nm, idx){
      var clean = nm.replace(/^@/, '');
      tagUsers.push({ id: 'manual_' + idx, name: clean });
    });
  }

  var tagMode = document.querySelector('input[name="tag_mode"]:checked') ? document.querySelector('input[name="tag_mode"]:checked').value : 'rotate';
  var tagPos = document.querySelector('input[name="tag_pos"]:checked') ? document.querySelector('input[name="tag_pos"]:checked').value : 'head';

  var payload = {
    targets: selectedBoxes,
    file_id: fid ? parseInt(fid) : null,
    direct_text: fid ? "" : direct,
    delay: delay,
    combat_icon_mode: combatIconMode,
    combat_icon_count: combatIconCount,
    tag_users: tagUsers,
    tag_all: flags.all,
    tag_mode: tagMode,
    tag_pos: tagPos,
    use_badge: flags.badge,
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
  Toast.success('Khởi chạy chiến dịch Noel thành công!');
  loadTasks();
}

async function loadTasks(){
  var tasks = await api('/api/tasks');
  if(!Array.isArray(tasks)) tasks = [];
  var tb = document.getElementById('task-table-body');
  tb.innerHTML = tasks.map(function(t){
    var running = (t.status === 'running');
    return '<tr>' +
      '<td><code>' + t.id + '</code></td>' +
      '<td><b>' + t.type + '</b></td>' +
      '<td>' + (running ? '<span style="color:var(--noel-green); font-weight:900;">Đang gửi</span>' : '<span style="color:var(--noel-red); font-weight:900;">Đã dừng</span>') + '</td>' +
      '<td>' +
        (running ? '<button type="button" class="btn-pill danger" onclick="stopTask(\'' + t.id + '\')" style="padding:4px 10px; font-size:10px;">Dừng</button>' : '-') +
      '</td>' +
    '</tr>';
  }).join('') || '<tr><td colspan="4" style="text-align:center; padding:14px;">Chưa có tiến trình nào</td></tr>';
}

async function stopTask(tid){
  await api('/api/tasks/' + tid + '/stop', { method: 'POST' });
  Toast.info('Đã dừng tiến trình');
  loadTasks();
}

async function stopAll(){
  await api('/api/tasks/stop_all', { method: 'POST' });
  Toast.info('Đã dừng toàn bộ tiến trình');
  loadTasks();
}

// Khởi chạy khi DOM sẵn sàng
window.addEventListener('DOMContentLoaded', function(){
  bindChips();
  loadAccounts();
  loadFiles();
  loadTasks();
  setInterval(loadTasks, 4000);
});

// Canvas Tuyết Rơi 60 FPS
var canvas = document.getElementById('snow-canvas');
var ctx = canvas.getContext('2d');
var width = canvas.width = window.innerWidth;
var height = canvas.height = window.innerHeight;
var flakes = [];
for (var i = 0; i < 75; i++) {
  flakes.push({ x: Math.random() * width, y: Math.random() * height, r: Math.random() * 3 + 1, d: Math.random() * 1.5 });
}
function drawSnow() {
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
  ctx.beginPath();
  for (var i = 0; i < flakes.length; i++) {
    var f = flakes[i];
    ctx.moveTo(f.x, f.y);
    ctx.arc(f.x, f.y, f.r, 0, Math.PI * 2, true);
  }
  ctx.fill();
  for (var i = 0; i < flakes.length; i++) {
    var f = flakes[i];
    f.y += Math.cos(f.d) + 1.2 + f.r / 2;
    f.x += Math.sin(f.d) * 0.7;
    if (f.x > width + 5 || f.x < -5 || f.y > height) {
      flakes[i] = { x: Math.random() * width, y: -10, r: f.r, d: f.d };
    }
  }
  requestAnimationFrame(drawSnow);
}
drawSnow();
window.onresize = function(){ width = canvas.width = window.innerWidth; height = canvas.height = window.innerHeight; };
</script>
</body>
</html>"""

# Các Route điều hướng & API Flask
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
        # Chấp nhận mật khẩu chính thức anhkhoidz hoặc rickivip
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
            real_name = f"Lỗi kết nối: {str(e)[:30]}"
    else:
        if not token:
            return jsonify({"error": "Thiếu Discord Token"}), 400
        try:
            dc = DiscordUserClient(token)
            me = dc.get_self()
            if me:
                real_name = me.get("username", "Discord User")
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
                real = me.get("username", acc["real_name"])
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
                    conn.execute("UPDATE accounts SET status = 'live' WHERE id = ?", (aid,))
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

    boxes = []
    try:
        if acc["platform"] == "zalo":
            zl = Zalo(acc["imei"], acc["cookies"])
            boxes = zl.get_conversations()
        else:
            dc = DiscordUserClient(acc["token"])
            boxes = dc.get_channels_and_guilds()
        return jsonify({"boxes": boxes})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/members/<grid>", methods=["POST"])
@login_required
def api_members(grid):
    conn = db()
    accs = conn.execute("SELECT * FROM accounts WHERE platform = 'zalo' AND status = 'live'").fetchall()
    if not accs:
        accs = conn.execute("SELECT * FROM accounts WHERE platform = 'zalo'").fetchall()
    conn.close()
    if not accs:
        return jsonify({"error": "Chưa có tài khoản Zalo nào để quét"}), 400

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
    rows = conn.execute("SELECT * FROM files ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/files/upload", methods=["POST"])
@login_required
def api_files_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Vui lòng chọn tệp tin"}), 400

    safe = str(int(time.time())) + "_" + re.sub(r"[^a-zA-Z0-9_.-]", "_", f.filename)
    fp = os.path.join(UPLOAD_DIR, safe)
    f.save(fp)

    block_count = 0
    in_block = False
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as fp_read:
            for line in fp_read:
                if line.strip():
                    if not in_block:
                        block_count += 1
                        in_block = True
                else:
                    in_block = False
    except Exception:
        block_count = 1

    sz = os.path.getsize(fp)
    conn = db()
    conn.execute("INSERT INTO files (filename, filepath, size, lines, created_at) VALUES (?, ?, ?, ?, ?)",
                 (f.filename, fp, sz, block_count, time.time()))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "lines": block_count, "size": sz})

@app.route("/api/files/<int:fid>", methods=["DELETE"])
@login_required
def api_files_del(fid):
    conn = db()
    r = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    if r and os.path.exists(r["filepath"]):
        try:
            os.remove(r["filepath"])
        except Exception:
            pass
    conn.execute("DELETE FROM files WHERE id = ?", (fid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# Động cơ quản lý tiến trình gửi tin ngầm
RUNNING_TASKS = {}
TASKS_LOCK = threading.Lock()

def run_spam_worker(task_id, payload, stop_ev):
    targets = payload.get("targets", [])
    file_path = payload.get("file_path")
    direct_blocks = payload.get("direct_blocks") or []
    delay = float(payload.get("delay", 1.2))
    combat_icon_mode = payload.get("combat_icon_mode", "none")
    combat_icon_count = int(payload.get("combat_icon_count", 3))

    tag_users = payload.get("tag_users") or []
    tag_all = bool(payload.get("tag_all", False))
    tag_mode = payload.get("tag_mode", "rotate")
    tag_pos = payload.get("tag_pos", "head")

    use_badge = bool(payload.get("use_badge", True))
    is_heading = bool(payload.get("is_heading", True))
    antiband = bool(payload.get("antiband", True))
    mode = payload.get("mode", "fast")
    color_mode = payload.get("color_mode", "rainbow")
    fixed_color = payload.get("fixed_color", "red")

    reader = None
    if file_path:
        reader = FastFileBlockReader(file_path)

    msg_idx = 0
    mention_turn = 0
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
            is_group = (target.get("type") == "group")

            conn = db()
            zalo_accs = conn.execute("SELECT * FROM accounts WHERE platform = 'zalo' AND enabled = 1").fetchall()
            discord_accs = conn.execute("SELECT * FROM accounts WHERE platform = 'discord' AND enabled = 1").fetchall()
            conn.close()

            active_clients = []
            for a in zalo_accs:
                if HEALTH_MGR.is_usable(a["id"]):
                    try:
                        active_clients.append(("zalo", a["id"], Zalo(a["imei"], a["cookies"])))
                    except Exception:
                        pass

            for a in discord_accs:
                if HEALTH_MGR.is_usable(a["id"]):
                    try:
                        active_clients.append(("discord", a["id"], DiscordUserClient(a["token"])))
                    except Exception:
                        pass

            if not active_clients:
                time.sleep(2)
                continue

            plat, acc_id, client = random.choice(active_clients)

            icon_str = ""
            if combat_icon_mode != "none":
                icon_str = " " + generate_combat_combo(combat_icon_mode, combat_icon_count)

            if mode == "treo_ngon":
                text = raw.replace("\r\n", "\n").replace("\r", "\n") + icon_str
                if plat == "zalo":
                    ok, res = client.send_adv(
                        text, target_id, color_mode=color_mode, fixed_color=fixed_color,
                        is_group=is_group, mentions=(tag_users if is_group else None),
                        tag_all=(tag_all if is_group else False), is_heading=is_heading,
                        color_offset=msg_idx, use_badge=use_badge, antiband=antiband,
                        tag_pos=tag_pos, tag_mode=tag_mode, mention_index=mention_turn
                    )
                else:
                    ok, res = client.send_message(
                        target_id, text, mentions=(tag_users if is_group else None),
                        tag_all=(tag_all if is_group else False), antiband=antiband
                    )

                if ok:
                    HEALTH_MGR.report_success(acc_id)
                else:
                    HEALTH_MGR.report_failure(acc_id, is_rate_limit=("429" in str(res)))

            elif mode == "treo_nhay":
                lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
                for ln in lines:
                    if stop_ev.is_set():
                        break
                    msg_line = ln + icon_str
                    if plat == "zalo":
                        ok, res = client.send_adv(
                            msg_line, target_id, color_mode=color_mode, fixed_color=fixed_color,
                            is_group=is_group, mentions=(tag_users if is_group else None),
                            tag_all=(tag_all if is_group else False), is_heading=is_heading,
                            color_offset=msg_idx, use_badge=use_badge, antiband=antiband,
                            tag_pos=tag_pos, tag_mode=tag_mode, mention_index=mention_turn
                        )
                    else:
                        ok, res = client.send_message(
                            target_id, msg_line, mentions=(tag_users if is_group else None),
                            tag_all=(tag_all if is_group else False), antiband=antiband
                        )
                    msg_idx += 1
                    mention_turn += 1
                    actual_delay = delay * random.uniform(0.85, 1.25)
                    time.sleep(actual_delay)
                continue

            else:
                lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
                for ln in lines:
                    if stop_ev.is_set():
                        break
                    msg_line = ln + icon_str
                    if plat == "zalo":
                        ok, res = client.send_adv(
                            msg_line, target_id, color_mode=color_mode, fixed_color=fixed_color,
                            is_group=is_group, mentions=(tag_users if is_group else None),
                            tag_all=(tag_all if is_group else False), is_heading=is_heading,
                            color_offset=msg_idx, use_badge=use_badge, antiband=antiband,
                            tag_pos=tag_pos, tag_mode=tag_mode, mention_index=mention_turn
                        )
                    else:
                        ok, res = client.send_message(
                            target_id, msg_line, mentions=(tag_users if is_group else None),
                            tag_all=(tag_all if is_group else False), antiband=antiband
                        )
                    msg_idx += 1
                    mention_turn += 1
                    actual_delay = delay * random.uniform(0.85, 1.25)
                    time.sleep(actual_delay)
                continue

            msg_idx += 1
            mention_turn += 1
            actual_delay = delay * random.uniform(0.85, 1.25)
            time.sleep(actual_delay)

    if reader:
        reader.close()

    with TASKS_LOCK:
        if task_id in RUNNING_TASKS:
            RUNNING_TASKS[task_id]["status"] = "stopped"

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

    t = threading.Thread(target=run_spam_worker, args=(task_id, payload, stop_ev), daemon=True)
    t.start()

    with TASKS_LOCK:
        RUNNING_TASKS[task_id] = {
            "id": task_id,
            "type": data.get("mode", "fast"),
            "status": "running",
            "thread": t,
            "stop_ev": stop_ev,
            "created_at": time.time()
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
                "created_at": tinfo["created_at"]
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🎄 [RICKI VIP NOEL EDITION] Máy chủ đang hoạt động tại cổng: {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
