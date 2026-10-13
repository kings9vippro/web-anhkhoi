# ============================================================
# Bản quyền thuộc về Phạm Anh Khôi
# Hệ thống điều hành: ALB Forge — Phiên Bản Giáng Sinh (Noel Edition)
# Hỗ trợ Đa Nền Tảng: Zalo & Discord | Tích hợp Anti-Ban & Anti-Die-All
# ============================================================
import os
import re
import json
import time
import sqlite3
import threading
import random
import base64
from functools import wraps
from collections import defaultdict

from flask import (
    Flask, render_template_string, request, jsonify,
    session, redirect, url_for, send_from_directory
)
from Crypto.Cipher import AES
import requests

APP_PASSWORD = os.environ.get("APP_PASSWORD", "anhkhoidz")
DATA_DIR = os.environ.get("DATA_DIR", "/tmp/alb_web")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "alb.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "phamanhkhoi-noel-2026")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

# ============================================================
# BỘ LỌC BẢO MẬT & CHỐNG TẤN CÔNG DDOS
# ============================================================
DDOS_LIMIT_PER_MINUTE = 120
DDOS_BURST_PER_SEC = 25
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
            ip_blocked_until[ip] = now + 300
            return jsonify({"error": "Phát hiện lưu lượng bất thường. Đã tạm khóa kết nối 5 phút."}), 429

        ip_request_history[ip].append(now)

    if not session.get("human_verified") and request.endpoint not in ("verify_gate", "api_verify_human"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Chưa hoàn tất kiểm tra an toàn danh tính"}), 403
        return redirect(url_for("verify_gate"))


# ============================================================
# CƠ SỞ DỮ LIỆU SQLITE
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
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
    try:
        c.execute("ALTER TABLE accounts ADD COLUMN platform TEXT DEFAULT 'zalo'")
    except Exception: pass
    try:
        c.execute("ALTER TABLE accounts ADD COLUMN token TEXT DEFAULT ''")
    except Exception: pass
    try:
        c.execute("ALTER TABLE accounts ADD COLUMN is_bot INTEGER DEFAULT 1")
    except Exception: pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, type TEXT, meta TEXT,
            status TEXT, started_at REAL, stats TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT, filepath TEXT,
            lines INTEGER DEFAULT 0, size INTEGER DEFAULT 0,
            uploaded_at REAL
        )
    """)
    conn.commit()
    conn.close()


init_db()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


ACTIVE_TASKS = {}


def new_tid(p):
    return p + "_" + str(int(time.time() * 1000))


def utf16_len(s):
    return len(s.encode('utf-16-le')) // 2


# ============================================================
# BỘ CÔNG CỤ ANTI-BAN & ANTI-DIE-ALL
# ============================================================
ZERO_WIDTH_CHARS = ["\u200b", "\u200c", "\u200d", "\ufeff"]

def apply_antiband(text):
    """Hàm chống ban: Chèn ký tự tàng hình zero-width ngẫu nhiên vào văn bản
    làm thay đổi mã băm (hash) của tin nhắn trên từng lượt gửi, vượt qua bộ lọc chống spam
    tin nhắn trùng lặp (Anti-Spam / AutoMod) của Zalo và Discord mà không làm biến dạng chữ."""
    if not text:
        return text
    words = text.split(" ")
    new_words = []
    for w in words:
        if len(w) > 2 and random.random() < 0.35:
            pos = random.randint(1, len(w) - 1)
            zw = random.choice(ZERO_WIDTH_CHARS)
            w = w[:pos] + zw + w[pos:]
        new_words.append(w)
    res = " ".join(new_words)
    res += random.choice(ZERO_WIDTH_CHARS)
    return res


class AccountHealthManager:
    """Cơ chế Anti-Die-All: Giám sát trạng thái từng tài khoản, tự động cách ly
    khi gặp lỗi xác thực hoặc 429 Too Many Requests (Rate Limit), bảo vệ toàn bộ dàn tài khoản
    không bị khóa đồng loạt."""
    def __init__(self):
        self.lock = threading.Lock()
        self.cooldowns = {}
        self.fail_streak = defaultdict(int)

    def is_usable(self, acc_id):
        with self.lock:
            now = time.time()
            if acc_id in self.cooldowns:
                if now < self.cooldowns[acc_id]:
                    return False
                else:
                    del self.cooldowns[acc_id]
            return True

    def report_success(self, acc_id):
        with self.lock:
            self.fail_streak[acc_id] = 0

    def report_rate_limit(self, acc_id, retry_after=30):
        with self.lock:
            self.cooldowns[acc_id] = time.time() + max(10, retry_after)

    def report_error(self, acc_id):
        with self.lock:
            self.fail_streak[acc_id] += 1
            if self.fail_streak[acc_id] >= 3:
                self.cooldowns[acc_id] = time.time() + 60


HEALTH_MGR = AccountHealthManager()


# BẢNG MÀU CHUẨN ZALO & DISCORD
ZALO_PALETTE = [
    {"id": "red",    "name": "Đỏ Noel",       "hex": "#e8453c", "ansi": "31"},
    {"id": "yellow", "name": "Vàng Kim Tuyến", "hex": "#f5c500", "ansi": "33"},
    {"id": "green",  "name": "Xanh Thông",    "hex": "#00b14f", "ansi": "32"},
    {"id": "orange", "name": "Cam Lửa",       "hex": "#ff8c00", "ansi": "33"},
    {"id": "ocean",  "name": "Xanh Tuyết",    "hex": "#0091ff", "ansi": "36"},
    {"id": "blue",   "name": "Xanh Đêm",      "hex": "#0068ff", "ansi": "34"},
    {"id": "purple", "name": "Tím Pha Lê",    "hex": "#a05eff", "ansi": "35"},
    {"id": "pink",   "name": "Hồng Đào",      "hex": "#ff47a8", "ansi": "35"},
]

RAINBOW_HEX = [c["hex"] for c in ZALO_PALETTE]
COLOR_IDS = [c["id"] for c in ZALO_PALETTE]

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


# ============================================================
# CLIENT GIAO THỨC ZALO
# ============================================================
class Zalo:
    def __init__(self, imei, cookies):
        self.imei = str(imei).strip()
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0.0.0 Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
            "Origin": "https://chat.zalo.me",
            "Referer": "https://chat.zalo.me/",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        })
        self.s.cookies.update(cookies)
        self.secret_key = None
        self.uid = None
        self.display_name = None
        self.zalo_name = None
        self.username = None
        self._login()

    def _login(self):
        r = self.s.get(
            "https://wpa.chat.zalo.me/api/login/getLoginInfo",
            params={"imei": self.imei, "type": 30,
                    "client_version": 645,
                    "ts": int(time.time() * 1000)},
            timeout=15,
        )
        d = r.json()
        ud = d.get("data")
        if not isinstance(ud, dict):
            raise Exception("Phiên đăng nhập hết hạn hoặc Cookie không hợp lệ")
        self.uid = ud.get("send2me_id")
        self.secret_key = ud.get("zpw_enk")
        self.display_name = ud.get("displayName") or ud.get("zaloName")
        self.zalo_name = ud.get("zaloName")
        self.username = ud.get("username")
        if not self.secret_key:
            raise Exception("Không thể lấy khóa giải mã bảo mật")

    def _enc(self, params):
        key = base64.b64decode(self.secret_key)
        cipher = AES.new(key, AES.MODE_CBC, bytes(16))
        pt = json.dumps(params, ensure_ascii=False).encode("utf-8")
        pad = AES.block_size - len(pt) % AES.block_size
        pt += bytes([pad]) * pad
        return base64.b64encode(cipher.encrypt(pt)).decode()

    def _dec(self, enc):
        key = base64.b64decode(self.secret_key)
        cipher = AES.new(key, AES.MODE_CBC, bytes(16))
        d = cipher.decrypt(base64.b64decode(enc))
        return d[:-d[-1]].decode("utf-8", "ignore")

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
                out.append({"id": str(gid), "name": info["name"],
                            "type": "group", "members": info["totalMember"]})
            except Exception:
                continue
        return out

    def group_info(self, gid):
        enc = self._enc({"gridVerMap": json.dumps({str(gid): 0})})
        r = self.s.post(
            "https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2",
            params={"zpw_ver": 645, "zpw_type": 30},
            data={"params": enc}, timeout=15,
        )
        dec = self._dec(r.json()["data"])
        info = json.loads(dec).get("data", {}).get("gridInfoMap", {}).get(str(gid), {})
        return {"name": info.get("name", "Nhóm Zalo"),
                "totalMember": info.get("totalMember", "?")}

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
            return [{"id": str(u.get("userId")),
                     "name": u.get("displayName") or u.get("zaloName") or f"Bạn_{str(u.get('userId'))[-6:]}",
                     "type": "user"} for u in users]
        except Exception:
            return []

    def get_members_full(self, gid):
        enc = self._enc({"gridVerMap": json.dumps({str(gid): 0})})
        r = self.s.post(
            "https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2",
            params={"zpw_ver": 645, "zpw_type": 30},
            data={"params": enc}, timeout=20,
        )
        dec = self._dec(r.json()["data"])
        info = json.loads(dec).get("data", {}).get("gridInfoMap", {}).get(str(gid), {})

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
            for chunk in [missing_uids[i:i+50] for i in range(0, len(missing_uids), 50)]:
                try:
                    enc2 = self._enc({"grid": str(gid), "userIds": chunk, "friendId": chunk})
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
            out.append({
                "id": str(uid),
                "name": real_name
            })
        return out

    def build_colored_message(self, raw_text, color_mode, fixed_color, is_heading=True, color_offset=0):
        lines = [l for l in raw_text.split("\n")]
        styled_lines = []
        styles = []
        current_u16_pos = 0
        first_color = "red"

        # Nhận diện cấu trúc khối ngôn (phân tách bởi dòng trống hoặc bắt đầu bằng #)
        has_blocks = any(ln.strip() == "" for ln in lines) or sum(1 for ln in lines if ln.strip().startswith("#")) > 1
        block_idx = color_offset

        for i, ln in enumerate(lines):
            content = ln.strip()
            if not content:
                styled_lines.append("")
                current_u16_pos += 1
                if has_blocks:
                    block_idx += 1
                continue

            if is_heading and not content.startswith("#"):
                if not has_blocks or (i == 0 or lines[i-1].strip() == ""):
                    line_text = f"# {content}"
                else:
                    line_text = content
            else:
                line_text = content

            styled_lines.append(line_text)
            l_len = utf16_len(line_text)

            color_num = block_idx if has_blocks else (color_offset + i)

            if color_mode in ("rainbow", "random"):
                if color_mode == "random":
                    pal = random.choice(ZALO_PALETTE)
                    c_hex = pal["hex"]
                    c_id = pal["id"]
                else:
                    c_hex = RAINBOW_HEX[color_num % len(RAINBOW_HEX)]
                    c_id = ZALO_PALETTE[color_num % len(ZALO_PALETTE)]["id"]
            elif color_mode == "fixed" and fixed_color:
                c_hex = next((c["hex"] for c in ZALO_PALETTE if c["id"] == fixed_color), "#e8453c")
                c_id = fixed_color
            else:
                c_hex = None
                c_id = None

            if i == 0 and c_id:
                first_color = c_id

            if c_hex:
                clean_hex = c_hex.lstrip("#").lower()
                # Cả 3 định dạng style tương thích tối đa Zalo Mobile và Zalo Web
                styles.append({"offset": current_u16_pos, "len": l_len, "type": "color", "value": c_hex})
                styles.append({"start": current_u16_pos, "len": l_len, "st": f"c_{c_hex}"})
                styles.append({"start": current_u16_pos, "len": l_len, "st": f"c_{clean_hex}"})

            current_u16_pos += l_len + 1

        final_msg = "\n".join(styled_lines)
        return final_msg, styles, first_color

    def attach_mentions(self, msg, mentions=None, tag_all=False):
        final = msg.rstrip() if msg else ""
        m_arr = []

        if tag_all:
            tag_token = "@All"
            pos = utf16_len(final) + (1 if final else 0)
            final = (final + " " + tag_token) if final else tag_token
            m_arr.append({
                "uid": "-1",
                "pos": pos,
                "len": utf16_len(tag_token),
                "type": 1
            })

        if mentions:
            for m in mentions:
                raw_name = str(m.get("name", "")).strip()
                name = raw_name.split(" (")[0] if " (" in raw_name else raw_name
                uid = str(m.get("uid") or m.get("id") or "").strip()
                if not name or not uid or uid in ("-1", "0"):
                    continue

                tag_token = f"@{name}"
                pos = utf16_len(final) + (1 if final else 0)
                final = (final + " " + tag_token) if final else tag_token
                m_arr.append({
                    "uid": uid,
                    "pos": pos,
                    "len": utf16_len(tag_token),
                    "type": 0
                })

        return final, m_arr

    def send_adv(self, raw_text, thread_id, color_mode="rainbow", fixed_color="red",
                 is_group=True, mentions=None, tag_all=False, is_heading=True,
                 color_offset=0, antiband=True):
        url = ("https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
               if is_group
               else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms")

        processed_text = apply_antiband(raw_text) if antiband else raw_text

        final_msg, styles, first_color = self.build_colored_message(
            processed_text, color_mode, fixed_color, is_heading=is_heading, color_offset=color_offset
        )

        final_msg, m_arr = self.attach_mentions(
            final_msg,
            mentions=(mentions if is_group else None),
            tag_all=(tag_all if is_group else False)
        )

        pl = {
            "message": final_msg,
            "clientId": str(int(time.time() * 1000)) + str(random.randint(100, 999)),
            "imei": self.imei,
        }
        if m_arr:
            pl["mentions"] = json.dumps(m_arr, ensure_ascii=False)

        if color_mode != "none":
            pl["msgColor"] = first_color
            if styles:
                pl["styles"] = json.dumps(styles, ensure_ascii=False)

        if is_group:
            pl["visibility"] = 0
            pl["grid"] = str(thread_id)
        else:
            pl["toid"] = str(thread_id)

        enc = self._enc(pl)
        return self.s.post(url, params={"zpw_ver": 645, "zpw_type": 30},
                           data={"params": enc}, timeout=15)


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
                           "Chrome/124.0.0.0 Safari/537.36" if not self.is_bot
                           else "DiscordBot (ALBForgeNoel, 2.5.0)")
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
            "red": "31",
            "green": "32",
            "yellow": "33",
            "orange": "33",
            "blue": "34",
            "purple": "35",
            "ocean": "36",
            "pink": "35"
        }

        if color_mode != "none":
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
# CSS GIAO DIỆN NOEL GIÁNG SINH SANG TRỌNG & RỰC RỠ
# ============================================================
CSS_NOEL = """
:root {
  --bg-page: #0d1b2a;
  --bg-card: rgba(22, 33, 62, 0.92);
  --border-color: rgba(231, 76, 60, 0.45);
  --border-gold: rgba(243, 156, 18, 0.6);
  --txt-0: #ffffff;
  --txt-1: #e0e1dd;
  --txt-2: #a4b0be;
  --noel-red: #e74c3c;
  --noel-green: #27ae60;
  --noel-gold: #f39c12;
  --grad-noel: linear-gradient(135deg, #c0392b 0%, #e74c3c 50%, #f39c12 100%);
  --grad-green: linear-gradient(135deg, #145a32 0%, #27ae60 100%);
  --grad-dark: linear-gradient(135deg, #1b263b 0%, #0d1b2a 100%);
  --shadow-noel: 0 10px 30px rgba(231, 76, 60, 0.2);
  --shadow-gold: 0 4px 18px rgba(243, 156, 18, 0.35);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html { touch-action: manipulation; -webkit-text-size-adjust: 100%; }
body {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background-color: var(--bg-page);
  color: var(--txt-1);
  min-height: 100vh;
  padding-bottom: 110px;
  position: relative;
  overflow-x: hidden;
  background-image: radial-gradient(circle at 50% 10%, rgba(192, 57, 43, 0.2) 0%, transparent 60%);
}

#snow-canvas {
  position: fixed; inset: 0; pointer-events: none !important; z-index: 1; width: 100%; height: 100%;
}

.header {
  background: rgba(13, 27, 42, 0.95); backdrop-filter: blur(25px);
  padding: 12px 18px; border-bottom: 1.5px solid var(--border-gold);
  position: sticky; top:0; z-index: 100; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
}
.header-inner { max-width: 1000px; margin: 0 auto; display: flex; align-items: center; gap: 12px; }
.logo-box {
  width: 48px; height: 48px; border-radius: 50%; overflow: hidden;
  border: 2px solid var(--noel-gold); box-shadow: 0 0 15px rgba(243, 156, 18, 0.6);
  background: #1b263b; flex-shrink: 0; position: relative; animation: glowLogo 3s ease-in-out infinite alternate;
}
@keyframes glowLogo { from { box-shadow: 0 0 10px rgba(243, 156, 18, 0.4); } to { box-shadow: 0 0 20px rgba(231, 76, 60, 0.7); } }
.logo-box img { width: 100%; height: 100%; object-fit: cover; }
.header-meta { flex: 1; min-width: 0; }
.header-meta h1 { font-family: 'Orbitron', sans-serif; font-size: 15px; font-weight: 900; color: var(--txt-0); display: flex; align-items: center; gap: 6px; }
.header-meta p { font-size: 10.5px; color: var(--txt-2); font-weight: 700; margin-top: 2px; display: flex; align-items: center; gap: 4px; }
.v-badge { display: inline-flex; align-items: center; justify-content: center; color: #0084ff; font-weight: 900; }

.container { max-width: 1000px; margin: 0 auto; padding: 16px 14px; position: relative; z-index: 10; }
.panel { display: none; animation: fadeIn .3s var(--ease) both; }
.panel.active { display: block; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

.card {
  background: var(--bg-card); backdrop-filter: blur(25px);
  padding: 18px; border-radius: 20px; border: 1.5px solid var(--border-color);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35); margin-bottom: 14px;
}
.card h2 {
  font-size: 12.5px; font-weight: 900; letter-spacing: .5px; margin-bottom: 14px;
  display: flex; align-items: center; justify-content: space-between; color: var(--noel-gold);
}

.btn-pill {
  padding: 10px 16px; border-radius: 99px; border: none; cursor: pointer;
  font-size: 11px; font-weight: 800; letter-spacing: .4px;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  transition: all .25s var(--ease); position: relative; overflow: hidden;
}
.btn-pill::after {
  content: ''; position: absolute; top: -50%; left: -60%; width: 40%; height: 200%;
  background: linear-gradient(60deg, transparent, rgba(255,255,255,0.4), transparent);
  transform: rotate(25deg); transition: all 0.5s;
}
.btn-pill:hover::after { left: 130%; }
.btn-pill:hover { transform: translateY(-2px); filter: brightness(1.1); }
.btn-pill:active { transform: translateY(0) scale(0.96); }
.btn-pill.primary { background: var(--grad-noel); color: #fff; box-shadow: var(--shadow-noel); }
.btn-pill.green { background: var(--grad-green); color: #fff; box-shadow: 0 4px 14px rgba(39, 174, 96, 0.4); }
.btn-pill.dark { background: var(--grad-dark); color: #fff; border: 1px solid var(--border-gold); }
.btn-pill.light { background: rgba(255, 255, 255, 0.1); color: #fff; border: 1px solid rgba(255, 255, 255, 0.2); }
.btn-pill.danger { background: rgba(231, 76, 60, 0.2); color: #ff6b6b; border: 1px solid rgba(231, 76, 60, 0.5); }
.btn-pill.full { width: 100%; padding: 13px; font-size: 12px; }

.btn-round {
  width: 52px; height: 52px; border-radius: 50%; border: none; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  transition: all .25s var(--ease); margin: 6px;
}
.btn-round svg { width: 22px; height: 22px; }
.btn-round:hover { transform: scale(1.1); }
.btn-round.action-start { background: var(--noel-green); color: #fff; box-shadow: 0 4px 18px rgba(39, 174, 96, 0.5); }
.btn-round.action-stop { background: var(--noel-red); color: #fff; box-shadow: 0 4px 18px rgba(231, 76, 60, 0.5); }

/* UPLOAD TỆP TIN CHUẨN XÁC NATIVE */
.file-upload-label {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; width: 100%; height: 85px; border: 2px dashed var(--noel-gold);
  border-radius: 16px; background: rgba(243, 156, 18, 0.08); cursor: pointer;
  transition: all 0.3s var(--ease);
}
.file-upload-label:hover { background: rgba(243, 156, 18, 0.18); border-color: #fff; }
.file-upload-label svg { width: 30px; height: 30px; color: var(--noel-gold); }
.file-upload-label span { font-size: 12px; font-weight: 700; color: var(--txt-0); }

.form-group { margin-bottom: 12px; }
.form-group label { display: block; margin-bottom: 6px; font-size: 10.5px; font-weight: 800; color: var(--noel-gold); }
.form-group input:not([type="file"]), .form-group textarea, .form-group select {
  width: 100%; padding: 12px 14px; border: 1.5px solid rgba(255, 255, 255, 0.15); border-radius: 14px;
  font-size: 12.5px; background: rgba(13, 27, 42, 0.85); color: var(--txt-0); transition: border-color .2s;
}
.form-group input:focus, .form-group textarea:focus, .form-group select:focus { outline: none; border-color: var(--noel-gold); box-shadow: 0 0 10px rgba(243, 156, 18, 0.3); }
.form-group textarea { min-height: 90px; font-family: 'JetBrains Mono', monospace; font-size: 11.5px; }

.chip-bar { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 5px; }
.chip-item {
  padding: 8px 14px; background: rgba(255, 255, 255, 0.08); color: var(--txt-1); border-radius: 99px;
  font-size: 10.5px; font-weight: 800; cursor: pointer; border: 1px solid rgba(255, 255, 255, 0.15); transition: all .2s;
}
.chip-item:hover { border-color: var(--noel-gold); color: #fff; transform: translateY(-1px); }
.chip-item.active { background: var(--grad-noel); color: #fff; border-color: transparent; box-shadow: 0 4px 12px rgba(231, 76, 60, 0.4); }

.toggle-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; margin-bottom: 12px; }
.toggle-item {
  padding: 11px; border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 14px;
  cursor: pointer; text-align: center; font-weight: 800; font-size: 10.5px;
  background: rgba(255, 255, 255, 0.06); color: var(--txt-2); transition: all .2s;
}
.toggle-item.active { background: var(--grad-green); color: #fff; border-color: transparent; box-shadow: 0 4px 14px rgba(39, 174, 96, 0.4); }

.table-wrap { overflow-x: auto; border-radius: 14px; border: 1px solid rgba(255, 255, 255, 0.15); background: rgba(13, 27, 42, 0.9); }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { padding: 11px 10px; text-align: left; font-size: 11px; border-bottom: 1px solid rgba(255, 255, 255, 0.07); white-space: nowrap; color: var(--txt-1); }
.table th { background: rgba(255, 255, 255, 0.05); font-weight: 800; color: var(--noel-gold); font-size: 9.5px; }

.box-list { max-height: 280px; overflow-y: auto; border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 14px; padding: 8px; background: rgba(13, 27, 42, 0.9); }
.box-item {
  padding: 10px 12px; border-radius: 12px; background: rgba(255, 255, 255, 0.04); margin-bottom: 6px;
  cursor: pointer; border: 1px solid rgba(255, 255, 255, 0.08); display: flex; align-items: center; gap: 10px; transition: all .15s;
}
.box-item:hover { border-color: var(--noel-gold); background: rgba(243, 156, 18, 0.1); }
.box-item.selected { border-color: var(--noel-red); background: rgba(231, 76, 60, 0.25); }
.box-item .check-mark {
  width: 18px; height: 18px; border: 1.5px solid var(--txt-2); border-radius: 5px;
  display: flex; align-items: center; justify-content: center; font-size: 10px; color: transparent; font-weight: 900;
}
.box-item.selected .check-mark { background: var(--noel-red); border-color: var(--noel-red); color: #fff; }
.box-item .b-title { font-weight: 800; font-size: 12px; color: var(--txt-0); }
.box-item .b-sub { font-size: 9.5px; color: var(--txt-2); font-family: 'JetBrains Mono', monospace; }

.bottom-dock {
  position: fixed; bottom: 14px; left: 50%; transform: translateX(-50%);
  width: calc(100% - 24px); max-width: 540px;
  background: rgba(13, 27, 42, 0.95); backdrop-filter: blur(28px);
  border: 1.5px solid var(--border-gold);
  box-shadow: 0 14px 40px rgba(0, 0, 0, 0.6);
  border-radius: 99px; display: grid; grid-template-columns: repeat(5, 1fr);
  padding: 6px; gap: 4px; z-index: 999;
}
.bottom-dock .dock-btn {
  padding: 9px 2px; border-radius: 99px; cursor: pointer; font-size: 9.5px; font-weight: 800;
  text-align: center; color: var(--txt-2); display: flex; flex-direction: column; align-items: center;
  gap: 3px; background: transparent; border: none; transition: all .2s;
}
.bottom-dock .dock-btn svg { width: 18px; height: 18px; transition: transform 0.2s; }
.bottom-dock .dock-btn:hover svg { transform: scale(1.15) translateY(-2px); }
.bottom-dock .dock-btn.active { background: var(--grad-noel); color: #fff; box-shadow: var(--shadow-noel); transform: translateY(-2px); }

#toast-stack { position: fixed; top: 14px; right: 14px; z-index: 99999; max-width: 320px; width: calc(100% - 28px); pointer-events: none; }
.toast {
  pointer-events: auto; padding: 12px 16px; border-radius: 14px;
  background: rgba(22, 33, 62, 0.98); border: 1px solid var(--noel-gold);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.5); display: flex; flex-direction: column; gap: 3px;
  animation: toastIn .25s var(--ease) both;
}
.toast.swipe-up { animation: toastUp .2s ease-out forwards; }
@keyframes toastIn { from { opacity: 0; transform: translateY(-20px); } to { opacity: 1; transform: translateY(0); } }
@keyframes toastUp { to { opacity: 0; transform: translateY(-40px); } }
.toast .t-head { font-size: 11px; font-weight: 900; color: var(--noel-gold); display:flex; align-items:center; gap:5px; }
.toast .t-body { font-size: 10.5px; font-weight: 600; color: var(--txt-0); }
"""

# ============================================================
# CỔNG BẢO MẬT & TRANG ĐĂNG NHẬP NOEL
# ============================================================
HTML_GATE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Hệ Thống An Toàn Noel</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_NOEL + """
body { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
.gate-card {
  background: rgba(22, 33, 62, 0.98); border: 2px solid var(--noel-gold);
  border-radius: 24px; padding: 40px 28px; max-width: 400px; width: 100%; text-align: center;
  box-shadow: 0 25px 60px rgba(0, 0, 0, 0.7); position: relative; overflow: hidden;
}
.radar-scanner {
  width: 96px; height: 96px; margin: 0 auto 20px; border-radius: 50%;
  position: relative; display: flex; align-items: center; justify-content: center;
  background: radial-gradient(circle, rgba(243,156,18,0.2) 0%, transparent 70%);
  border: 2px dashed var(--noel-gold);
}
.radar-scanner::before {
  content: ''; position: absolute; inset: 0; border-radius: 50%;
  border: 2px solid transparent; border-top-color: var(--noel-red);
  animation: spin 1.2s linear infinite;
}
@keyframes spin { 100% { transform: rotate(360deg); } }
.radar-icon { font-size: 38px; animation: pulse 1.5s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.15); } }
.progress-line { height: 6px; width: 100%; background: rgba(255,255,255,0.1); border-radius: 99px; overflow: hidden; margin: 20px 0; display: none; }
.progress-fill { height: 100%; width: 0%; background: var(--grad-noel); border-radius: 99px; transition: width 0.35s ease; }
</style>
</head>
<body>
<canvas id="snow-canvas"></canvas>
<div class="gate-card" style="z-index:10;">
  <div class="radar-scanner"><div class="radar-icon">🎄</div></div>
  <h1 style="font-family:'Orbitron',sans-serif; font-size:17px; margin-bottom:8px; color:var(--noel-gold);">BẢO MẬT NOEL 2026</h1>
  <p id="scan-status" style="font-size:12px; color:var(--txt-1); min-height:34px;">Vui lòng xác thực danh tính để vào hệ thống.</p>
  <div class="progress-line" id="p-box"><div class="progress-fill" id="p-bar"></div></div>
  <button class="btn-pill primary full" id="start-btn" onclick="startVerification()" style="font-size:13px; padding:15px;">❄️ Bắt Đầu Xác Thực</button>
</div>
<script>
var pBox = document.getElementById('p-box');
var pBar = document.getElementById('p-bar');
var statusTxt = document.getElementById('scan-status');
var startBtn = document.getElementById('start-btn');
var steps = [
  { p: 25, txt: 'Đang kiểm tra chứng chỉ an toàn...' },
  { p: 55, txt: 'Đang khởi động lá chắn Anti-Ban & Anti-Die...' },
  { p: 85, txt: 'Xác thực hoàn tất, đang cấp quyền...' },
  { p: 100, txt: 'Đang chuyển hướng vào hệ thống...' }
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
    setTimeout(runStep, 400);
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
var flakes = Array.from({ length: 65 }, () => ({
  x: Math.random() * sW, y: Math.random() * sH - sH,
  r: Math.random() * 3.5 + 1.2,
  dY: Math.random() * 1.3 + 0.6,
  dX: Math.random() * 1.0 - 0.5,
  opacity: Math.random() * 0.7 + 0.3
}));
function renderSnow() {
  sCtx.clearRect(0, 0, sW, sH);
  flakes.forEach(f => {
    sCtx.beginPath();
    sCtx.arc(f.x, f.y, f.r, 0, Math.PI * 2);
    sCtx.fillStyle = 'rgba(255, 255, 255, ' + f.opacity + ')';
    sCtx.fill();
    f.y += f.dY; f.x += f.dX;
    if (f.y > sH) { f.y = -10; f.x = Math.random() * sW; }
    if (f.x > sW) f.x = 0; if (f.x < 0) f.x = sW;
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
<title>Đăng Nhập — ALB Forge Noel</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_NOEL + """
body { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
.login-card {
  background: rgba(22, 33, 62, 0.98); border: 2px solid var(--noel-gold);
  border-radius: 24px; padding: 40px 28px; max-width: 400px; width: 100%; text-align: center;
  box-shadow: 0 25px 60px rgba(0, 0, 0, 0.7); position: relative; z-index: 10;
}
.login-logo { width: 88px; height: 88px; border-radius: 50%; overflow: hidden; margin: 0 auto 16px; border: 2.5px solid var(--noel-gold); box-shadow: 0 0 20px rgba(243, 156, 18, 0.5); }
.login-logo img { width: 100%; height: 100%; object-fit: cover; }
.err-msg { background: rgba(231, 76, 60, 0.25); border: 1px solid var(--noel-red); color: #ff6b6b; padding: 11px; border-radius: 12px; font-size: 11.5px; font-weight: 800; margin-bottom: 16px; text-align: left; }
</style>
</head>
<body>
<canvas id="snow-canvas"></canvas>
<div class="login-card">
  <div class="login-logo">
    <img src="/static/logo.png" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 100 100\\'><circle cx=\\'50\\' cy=\\'50\\' r=\\'50\\' fill=\\'%23c0392b\\'/><text x=\\'50\\' y=\\'62\\' text-anchor=\\'middle\\' font-size=\\'40\\' fill=\\'white\\'>🎄</text></svg>'">
  </div>
  <h1 style="font-family:'Orbitron',sans-serif; font-size:18px; margin-bottom:6px; color:var(--noel-gold);">ALB FORGE NOEL ❄️</h1>
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
<script>
var snowCanvas = document.getElementById('snow-canvas');
var sCtx = snowCanvas.getContext('2d');
var sW = window.innerWidth, sH = window.innerHeight;
snowCanvas.width = sW; snowCanvas.height = sH;
var flakes = Array.from({ length: 65 }, () => ({
  x: Math.random() * sW, y: Math.random() * sH - sH,
  r: Math.random() * 3.5 + 1.2,
  dY: Math.random() * 1.3 + 0.6,
  dX: Math.random() * 1.0 - 0.5,
  opacity: Math.random() * 0.7 + 0.3
}));
function renderSnow() {
  sCtx.clearRect(0, 0, sW, sH);
  flakes.forEach(f => {
    sCtx.beginPath();
    sCtx.arc(f.x, f.y, f.r, 0, Math.PI * 2);
    sCtx.fillStyle = 'rgba(255, 255, 255, ' + f.opacity + ')';
    sCtx.fill();
    f.y += f.dY; f.x += f.dX;
    if (f.y > sH) { f.y = -10; f.x = Math.random() * sW; }
    if (f.x > sW) f.x = 0; if (f.x < 0) f.x = sW;
  });
  requestAnimationFrame(renderSnow);
}
renderSnow();
</script>
</body>
</html>
"""

HTML_INDEX = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>ALB Forge — Phiên Bản Giáng Sinh Noel</title>
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
      <h1>ALB FORGE NOEL 🎄 ❄️</h1>
      <p>
        Bản quyền thiết kế: <span class="v-badge"><svg viewBox="0 0 24 24" width="13" height="13" fill="#0084ff"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></span> <b>Phạm Anh Khôi</b> (Zalo & Discord)
      </p>
    </div>
    <button class="btn-pill light" onclick="location.href='/logout'">Đăng xuất</button>
  </div>
</div>

<div id="toast-stack"></div>

<div class="container">

  <!-- TAB 1: ACCOUNTS (ZALO & DISCORD) -->
  <div class="panel active" id="panel-accounts">
    <div class="card">
      <h2>
        <span>Thêm Tài Khoản Mới (Zalo / Discord)</span>
        <button class="btn-pill green" onclick="checkAllAccounts()">Kiểm Tra Tất Cả</button>
      </h2>
      <div class="form-group">
        <label>Chọn Nền Tảng Ứng Dụng</label>
        <div class="chip-bar" id="platform-selector">
          <div class="chip-item active" data-plat="zalo" onclick="selectPlat('zalo')">🔷 Zalo (IMEI + Cookie)</div>
          <div class="chip-item" data-plat="discord" onclick="selectPlat('discord')">🟣 Discord (Bot / User Token)</div>
        </div>
        <input type="hidden" id="add-platform" value="zalo">
      </div>

      <div class="form-group"><label>Tên gợi nhớ</label><input id="add-label" placeholder="acc_1"></div>

      <div id="zalo-input-fields">
        <div class="form-group"><label>IMEI thiết bị</label><input id="add-imei" placeholder="000000000000000"></div>
        <div class="form-group"><label>Cookie JSON</label><textarea id="add-cookies" placeholder='{"zpw_sek":"...","zpw_ver":"645","zpw_type":"30"}'></textarea></div>
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

      <button class="btn-pill primary full" onclick="addAccount()">Lưu Tài Khoản</button>
    </div>

    <div class="card">
      <h2><span>Danh Sách Tài Khoản Hoạt Động</span></h2>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>ID</th><th>App</th><th>Gợi nhớ</th><th>Tên hiển thị</th><th>Trạng thái</th><th>Thao tác</th></tr></thead>
          <tbody id="accounts-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 2: BOXES (ZALO & DISCORD) -->
  <div class="panel" id="panel-boxes">
    <div class="card">
      <h2><span>Quản Lý Hội Thoại / Kênh Nhận Tin</span></h2>
      <div class="form-group"><label>Chọn tài khoản để nạp hội thoại hoặc kênh</label><select id="load-acc-select"><option value="">-- Chọn tài khoản --</option></select></div>
      <div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px;">
        <button class="btn-pill green" onclick="loadBoxes()">Nạp Danh Sách</button>
        <button class="btn-pill light" onclick="selectAllBoxes()">Chọn Tất Cả</button>
        <button class="btn-pill danger" onclick="clearAllBoxes()">Bỏ Chọn</button>
      </div>
      <div>
        <div style="font-size:11px; font-weight:800; color:var(--noel-gold); margin-bottom:6px;">
          ĐÃ CHỌN: <span id="selected-count" style="color:var(--noel-red); font-size:13px;">0</span> HỘI THOẠI / KÊNH
        </div>
        <div class="box-list" id="box-list"><div style="text-align:center; padding:18px; color:var(--txt-2); font-size:12px;">Chưa nạp dữ liệu hội thoại</div></div>
      </div>
    </div>
  </div>

  <!-- TAB 3: FILES (FIXED NATIVE UPLOAD) -->
  <div class="panel" id="panel-files">
    <div class="card">
      <h2><span>Tải Lên Văn Bản Hoặc Logo Web</span></h2>
      
      <label class="file-upload-label" for="file-input">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        <span id="upload-txt">Nhấn để chọn tệp Văn bản (.txt) hoặc Ảnh Logo</span>
        <input type="file" id="file-input" style="display:none;" onchange="handleFileSelect(this)">
      </label>

      <div style="display:flex; gap:8px; margin-top:12px;">
        <button class="btn-pill primary full" onclick="uploadFile()">Lưu Tệp Văn Bản (.txt)</button>
        <button class="btn-pill dark full" onclick="uploadLogo()">Cập Nhật Logo Web</button>
      </div>
    </div>
    <div class="card">
      <h2><span>Tập Tin Văn Bản Đã Lưu Trong Hệ Thống</span></h2>
      <div id="files-list"><div style="text-align:center; padding:18px; color:var(--txt-2); font-size:11.5px;">Chưa có tập tin</div></div>
    </div>
  </div>

  <!-- TAB 4: SPAM ENGINE (MULTI-APP, ANTI-BAN, ANTI-DIE) -->
  <div class="panel" id="panel-spam">
    <div class="card">
      <h2><span>Thiết Lập Động Cơ Gửi Tin Tự Động</span></h2>

      <div class="form-group">
        <label>1. Chế độ gửi tin nhắn</label>
        <div class="chip-bar" id="mode-selector">
          <div class="chip-item active" data-mode="fast">Siêu Nhanh</div>
          <div class="chip-item" data-mode="treo_ngon">Treo Ngôn (N Dòng / 1 Tin)</div>
          <div class="chip-item" data-mode="treo_nhay">Treo Nhây (Từng Dòng Riêng)</div>
        </div>
        <input type="hidden" id="spam-mode" value="fast">
      </div>

      <div class="form-group">
        <label>2. Chọn tập tin có sẵn</label>
        <select id="spam-file-select"><option value="">-- Chọn tập tin văn bản --</option></select>
      </div>

      <div class="form-group">
        <label>3. Hoặc nhập trực tiếp văn bản</label>
        <textarea id="spam-messages" placeholder="Dán văn bản nhiều dòng vào đây... Nếu có dòng tiêu đề, bạn có thể gõ '# Tiêu Đề'. Khi chọn Treo Ngôn, toàn bộ văn bản sẽ được gửi trong 1 tin duy nhất."></textarea>
      </div>

      <div class="form-group">
        <label>4. Màu sắc chữ (Đổi màu chuẩn Zalo Group & Discord ANSI)</label>
        <div class="chip-bar" id="color-mode-bar">
          <div class="chip-item active" data-cmode="rainbow">Trộn Màu Từng Dòng (Rainbow)</div>
          <div class="chip-item" data-cmode="random">Đổi Màu Ngẫu Nhiên</div>
          <div class="chip-item" data-cmode="fixed">Cố Định Một Màu</div>
          <div class="chip-item" data-cmode="none">Tắt Màu</div>
        </div>
        <input type="hidden" id="color-mode" value="rainbow">
        <div id="fixed-colors-wrap" style="display:none; margin-top:8px;" class="chip-bar"></div>
      </div>

      <div class="form-group">
        <label>5. Khoảng cách thời gian (giây)</label>
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
        <label>6. Biểu tượng cảm xúc cuối câu</label>
        <div class="chip-bar" id="icon-bar">
          <div class="chip-item" data-icon="0">0</div>
          <div class="chip-item" data-icon="2">2</div>
          <div class="chip-item active" data-icon="3">3</div>
          <div class="chip-item" data-icon="5">5</div>
        </div>
        <input type="hidden" id="icon-count" value="3">
      </div>

      <div class="toggle-grid">
        <div class="toggle-item active" id="tg-antiband" onclick="tgFlag('antiband')">🛡️ Bật Anti-Ban (Chống Quét Hash)</div>
        <div class="toggle-item active" id="tg-antidieall" onclick="tgFlag('antidieall')">🔒 Anti-Die-All (Tự Cách Ly 429)</div>
        <div class="toggle-item active" id="tg-heading" onclick="tgFlag('heading')">Chữ To Tiêu Đề Zalo (#)</div>
        <div class="toggle-item active" id="tg-multi" onclick="tgFlag('multi')">Chạy Tất Cả Acc Song Song</div>
        <div class="toggle-item" id="tg-all" onclick="tgFlag('all')">Nhắc Cả Nhóm (@All)</div>
        <div class="toggle-item active" id="tg-emoji" onclick="tgFlag('emoji')">Sử Dụng Icon Cuối Câu</div>
      </div>

      <div class="form-group">
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer; font-size:11.5px; color:var(--txt-0);">
          <input type="checkbox" id="tg-tag" onchange="tgTag()" style="width:16px; height:16px;">
          Bật chọn từng thành viên Zalo theo tên thật
        </label>
        <div id="tag-wrap" style="display:none; margin-top:10px;">
          <div class="form-group"><select id="member-acc-select"><option value="">-- Chọn tài khoản quét --</option></select></div>
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
          <input type="hidden" id="tag-selected" value="">
        </div>
      </div>
    </div>

    <div style="text-align:center; margin-bottom:18px;">
      <button class="btn-round action-start" onclick="startSpam()" title="Bắt đầu"><svg viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3"/></svg></button>
      <button class="btn-round action-stop" onclick="stopAll()" title="Dừng lại"><svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg></button>
    </div>

    <div class="card">
      <h2><span>Tiến Trình Đang Chạy</span></h2>
      <div class="table-wrap">
        <table class="table"><thead><tr><th>Mã</th><th>Chế độ</th><th>Trạng thái</th><th>Thao tác</th></tr></thead><tbody id="tasks-tbody"></tbody></table>
      </div>
    </div>
  </div>

  <!-- TAB 5: HƯỚNG DẪN TOKEN DISCORD (CHỐNG DIE) -->
  <div class="panel" id="panel-guide">
    <div class="card">
      <h2><span>📖 Hướng Dẫn Lấy Token Discord (Bảo Vệ Token Không Die)</span></h2>
      
      <div style="line-height:1.7; font-size:12.5px; color:var(--txt-1);">
        <h3 style="color:var(--noel-gold); font-size:14px; margin-top:6px; margin-bottom:6px;">Cách 1: Tạo Bot Token Chính Thức (Khuyên dùng - Bất tử 100%)</h3>
        <ol style="padding-left:18px; margin-bottom:14px;">
          <li>Truy cập cổng nhà phát triển: <a href="https://discord.com/developers/applications" target="_blank" style="color:var(--noel-red); font-weight:bold;">discord.com/developers/applications</a>.</li>
          <li>Nhấn <b>New Application</b>, đặt tên bot (ví dụ: <code>ALB Bot</code>) rồi bấm Create.</li>
          <li>Ở cột bên trái, chọn mục <b>Bot</b> ➔ Nhấn <b>Reset Token</b> và <b>Copy</b> chuỗi token.</li>
          <li>Kéo xuống mục <b>Privileged Gateway Intents</b>: Bật cả 3 công tắc (<b>Presence Intent</b>, <b>Server Members Intent</b>, <b>Message Content Intent</b>).</li>
          <li>Vào mục <b>OAuth2</b> ➔ <b>URL Generator</b>: Tích chọn <code>bot</code> và cấp quyền <code>Administrator</code> hoặc <code>Send Messages</code>, sau đó copy link dán vào trình duyệt để mời Bot vào Server của bạn.</li>
        </ol>

        <h3 style="color:var(--noel-gold); font-size:14px; margin-top:12px; margin-bottom:6px;">Cách 2: Lấy User Token Cá Nhân (Self-Bot)</h3>
        <ol style="padding-left:18px; margin-bottom:14px;">
          <li>Mở Discord trên trình duyệt Chrome/Cốc Cốc tại <a href="https://discord.com/app" target="_blank" style="color:var(--noel-red); font-weight:bold;">discord.com/app</a> và đăng nhập tài khoản.</li>
          <li>Bấm phím <b>F12</b> (hoặc chuột phải chọn Kiểm tra) ➔ Chuyển qua tab <b>Network</b> (Mạng).</li>
          <li>Gõ một tin nhắn bất kỳ trong một kênh hoặc bấm chuyển kênh để sinh ra yêu cầu mạng.</li>
          <li>Tại ô lọc (Filter), gõ <code>messages</code> hoặc <code>science</code> ➔ Bấm vào một dòng request.</li>
          <li>Ở khung bên phải (Headers), kéo xuống phần <b>Request Headers</b> ➔ Tìm dòng <b>Authorization</b> ➔ Đó chính là Token của bạn.</li>
        </ol>

        <h3 style="color:#e74c3c; font-size:14px; margin-top:12px; margin-bottom:6px;">⚠️ 5 Nguyên Tắc Giữ Token Discord Không Bao Giờ Bị Khóa (Anti-Die)</h3>
        <ul style="padding-left:18px;">
          <li><b>1. Luôn bật tính năng "Anti-Ban":</b> Hệ thống tự động chèn ký tự tàng hình để mã hash tin nhắn không bị trùng lặp, AutoMod của Discord sẽ không thể phát hiện spam.</li>
          <li><b>2. Giữ delay an toàn:</b> Đặt khoảng cách thời gian giữa các tin từ <b>1.5s - 2.5s</b> trở lên khi chạy bằng User Token.</li>
          <li><b>3. Kích hoạt "Anti-Die-All":</b> Nếu gặp lỗi 429 (Rate Limit), hệ thống sẽ lập tức tạm dừng cách ly tài khoản đó, tránh bị Discord trừng phạt.</li>
          <li><b>4. Không bao giờ đổi mật khẩu:</b> Đổi mật khẩu sẽ làm toàn bộ Token cũ lập tức bị vô hiệu hóa (Die).</li>
          <li><b>5. Hạn chế tag @everyone quá nhiều:</b> Không nên tag @everyone liên tục trên cùng một kênh nếu không có quyền admin.</li>
        </ul>
      </div>
    </div>
  </div>

</div>

<!-- BOTTOM DOCK NOEL -->
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
    <span>Tập tin</span>
  </button>
  <button class="dock-btn" data-tab="spam">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
    <span>Gửi tin</span>
  </button>
  <button class="dock-btn" data-tab="guide">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
    <span>HD Token</span>
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

// TOAST THÔNG MINH
var Toast = (function(){
  var stack = null;
  function ensure(){ if(!stack) stack = document.getElementById('toast-stack'); return stack; }
  function show(msg, title, duration){
    duration = duration || 1600;
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

    var startY = 0;
    el.addEventListener('touchstart', e => { startY = e.touches[0].clientY; }, { passive: true });
    el.addEventListener('touchend', e => {
      if(e.changedTouches[0].clientY - startY < -15) dismiss();
    });
  }
  return {
    success: (m, t, d) => show(m, t || 'Thành công', d),
    error: (m, t, d) => show(m, t || 'Lỗi', d || 2000),
    info: (m, t, d) => show(m, t || 'Thông báo', d)
  };
})();

// CHUYỂN TAB DOCK DƯỚI
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
  if(plat === 'zalo'){
    document.getElementById('zalo-input-fields').style.display = 'block';
    document.getElementById('discord-input-fields').style.display = 'none';
  } else {
    document.getElementById('zalo-input-fields').style.display = 'none';
    document.getElementById('discord-input-fields').style.display = 'block';
  }
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
    document.getElementById('upload-txt').textContent = "Đã chọn: " + input.files[0].name;
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
    inp.value = ''; document.getElementById('upload-txt').textContent = "Nhấn để chọn tệp Văn bản (.txt) hoặc Ảnh Logo";
  } else {
    Toast.error(r.error || 'Lỗi tải ảnh');
  }
}

async function loadAccounts(){
  var accs = await api('/api/accounts');
  if(!Array.isArray(accs)) accs = [];
  var tb = document.getElementById('accounts-tbody');
  tb.innerHTML = accs.map(a => {
    var platIcon = (a.platform === 'discord') ? '🟣 Discord' : '🔷 Zalo';
    var realName = a.display_name || a.zalo_name || a.username || 'Chưa cập nhật';
    var isLive = (a.status === 'live');
    var badge = isLive ? '<span class="status-badge live" style="color:#2ecc71;">● HOẠT ĐỘNG</span>' : '<span class="status-badge dead" style="color:#e74c3c;">● NGẮT KẾT NỐI</span>';
    return `<tr>
      <td>${a.id}</td>
      <td><b>${platIcon}</b></td>
      <td><b>${a.label}</b></td>
      <td><span style="color:var(--noel-gold); font-weight:800;">${realName}</span></td>
      <td id="status-${a.id}">${badge}</td>
      <td>
        <button class="btn-pill light" onclick="checkAccount(${a.id})" style="padding:4px 8px; font-size:9.5px;">Kiểm tra</button>
        <button class="btn-pill danger" onclick="delAcc(${a.id})" style="padding:4px 8px; font-size:9.5px;">Xóa</button>
      </td>
    </tr>`;
  }).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--txt-2); padding:16px;">Chưa có tài khoản</td></tr>';

  var s1 = document.getElementById('load-acc-select');
  var s2 = document.getElementById('member-acc-select');
  var opts = '<option value="">-- Chọn tài khoản --</option>' + accs.map(a => `<option value="${a.id}">[${(a.platform||'zalo').toUpperCase()}] ${a.label} (${a.display_name||'Sẵn sàng'})</option>`).join('');
  s1.innerHTML = opts; s2.innerHTML = opts;
}

async function checkAccount(aid){
  Toast.info('Đang kiểm tra kết nối...');
  var r = await api(`/api/accounts/${aid}/check`, { method: 'POST' });
  var el = document.getElementById(`status-${aid}`);
  if(r.ok){
    if(el) el.innerHTML = '<span class="status-badge live" style="color:#2ecc71;">● HOẠT ĐỘNG</span>';
    Toast.success('Tài khoản hoạt động rất tốt!');
  } else {
    if(el) el.innerHTML = '<span class="status-badge dead" style="color:#e74c3c;">● NGẮT KẾT NỐI</span>';
    Toast.error('Kết nối thất bại: ' + (r.error || 'Token/Cookie hết hạn'));
  }
}

async function checkAllAccounts(){
  Toast.info('Đang kiểm tra toàn bộ...');
  var r = await api('/api/accounts/check_all', { method: 'POST' });
  Toast.success(`Hoàn tất: ${r.live}/${r.total} tài khoản hoạt động`);
  loadAccounts();
}

async function addAccount(){
  var plat = document.getElementById('add-platform').value;
  var label = document.getElementById('add-label').value.trim();

  if(plat === 'zalo'){
    var imei = document.getElementById('add-imei').value.trim();
    var cookies = document.getElementById('add-cookies').value.trim();
    if(!imei || !cookies) return Toast.error('Vui lòng điền đủ IMEI và Cookie Zalo');
    Toast.info('Đang xác thực thông tin Zalo...');
    var r = await api('/api/accounts/add_zalo', { method: 'POST', body: JSON.stringify({ label, imei, cookies }) });
    if(r.error) return Toast.error(r.error);
    Toast.success('Thêm tài khoản Zalo thành công!');
    document.getElementById('add-imei').value = '';
    document.getElementById('add-cookies').value = '';
  } else {
    var token = document.getElementById('add-token').value.trim();
    var is_bot = parseInt(document.getElementById('add-is-bot').value) || 1;
    if(!token) return Toast.error('Vui lòng nhập Token Discord');
    Toast.info('Đang xác thực Token Discord...');
    var r = await api('/api/accounts/add_discord', { method: 'POST', body: JSON.stringify({ label, token, is_bot }) });
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

async function loadBoxes(){
  var aid = document.getElementById('load-acc-select').value;
  if(!aid) return Toast.error('Vui lòng chọn tài khoản trước');
  Toast.info('Đang nạp danh sách hội thoại / kênh...');
  var r = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  var all = r.boxes || [];
  var bl = document.getElementById('box-list');
  bl.innerHTML = all.map((b,i) => `
    <div class="box-item" onclick="tgBox(this, ${i})">
      <div class="check-mark">✓</div>
      <div><div class="b-title">${b.name}</div><div class="b-sub">${b.id} | ${b.type}</div></div>
    </div>
  `).join('') || '<div style="text-align:center; padding:14px;">Không tìm thấy hội thoại</div>';
  _boxes = all; selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
  Toast.success('Đã nạp ' + all.length + ' mục');
}

function tgBox(el, idx){
  var b = _boxes[idx];
  if(!b) return;
  if(el.classList.contains('selected')){
    el.classList.remove('selected');
    selectedBoxes = selectedBoxes.filter(x => x.id !== b.id);
  } else {
    el.classList.add('selected');
    selectedBoxes.push(b);
  }
  document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function selectAllBoxes(){
  document.querySelectorAll('#box-list .box-item').forEach(el => el.classList.add('selected'));
  selectedBoxes = _boxes.slice();
  document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function clearAllBoxes(){
  document.querySelectorAll('#box-list .box-item').forEach(el => el.classList.remove('selected'));
  selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
}

function renderMemberItems(){
  var sel = document.getElementById('tag-selector');
  var query = (document.getElementById('search-member-inp').value || '').toLowerCase().trim();
  var filtered = _members.filter(m => !query || m.name.toLowerCase().includes(query) || m.id.includes(query));
  sel.innerHTML = filtered.map((m, i) => {
    var isSel = selectedTags.some(t => t.id === m.id);
    return `<div class="box-item ${isSel ? 'selected' : ''}" onclick="toggleMemberById('${m.id}')">
      <div class="check-mark">${isSel ? '✓' : ''}</div>
      <div><div class="b-title">${m.name}</div><div class="b-sub">ID: ${m.id}</div></div>
    </div>`;
  }).join('') || '<div style="padding:14px; text-align:center; color:var(--txt-2);">Không tìm thấy thành viên</div>';
}

function toggleMemberById(mid){
  var m = _members.find(x => x.id === mid);
  if(!m) return;
  var exists = selectedTags.some(t => t.id === mid);
  if(exists){
    selectedTags = selectedTags.filter(t => t.id !== mid);
  } else {
    selectedTags.push({ id: m.id, name: m.name });
  }
  document.getElementById('tag-count').textContent = selectedTags.length;
  renderMemberItems();
}

function selectAllMembers(){
  selectedTags = _members.map(m => ({ id: m.id, name: m.name }));
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

function filterMembers(){
  renderMemberItems();
}

async function loadMembers(){
  var aid = document.getElementById('member-acc-select').value;
  if(!aid) return Toast.error('Vui lòng chọn tài khoản quét');
  var box = selectedBoxes.find(b => b.type === 'group');
  if(!box) return Toast.error('Cần chọn ít nhất 1 nhóm Zalo ở mục Hội Thoại');
  Toast.info('Đang nạp thành viên nhóm ' + box.name + '...');
  var r = await api('/api/accounts/' + aid + '/members/' + box.id, { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  _members = r.members || [];
  selectedTags = [];
  document.getElementById('tag-count').textContent = '0';
  document.getElementById('tag-selector').style.display = 'block';
  renderMemberItems();
  Toast.success('Đã nạp ' + _members.length + ' thành viên');
}

async function uploadFile(){
  var inp = document.getElementById('file-input');
  if(!inp.files || !inp.files.length) return Toast.error('Vui lòng bấm chọn tập tin văn bản .txt trước');
  var fd = new FormData();
  fd.append('file', inp.files[0]);
  Toast.info('Đang tải lên tập tin...');
  var r = await fetch('/api/files/upload', { method: 'POST', body: fd }).then(x => x.json());
  if(r.error) return Toast.error(r.error);
  Toast.success('Đã lưu ' + r.lines + ' khối văn bản');
  inp.value = ''; document.getElementById('upload-txt').textContent = "Nhấn để chọn tệp Văn bản (.txt) hoặc Ảnh Logo";
  loadFiles();
}

async function loadFiles(){
  var files = await api('/api/files');
  if(!Array.isArray(files)) files = [];
  var list = document.getElementById('files-list');
  list.innerHTML = files.map(f => `
    <div class="box-item" style="cursor:default;">
      <div style="flex:1;"><div class="b-title">📄 ${f.filename}</div><div class="b-sub">${f.lines} khối | ${(f.size/1024).toFixed(1)} KB</div></div>
      <button class="btn-pill danger" onclick="delFile(${f.id})" style="padding:4px 10px; font-size:9.5px;">Xóa</button>
    </div>
  `).join('') || '<div style="text-align:center; padding:14px; color:var(--txt-2);">Chưa có tập tin</div>';
  var s = document.getElementById('spam-file-select');
  s.innerHTML = '<option value="">-- Chọn tập tin --</option>' + files.map(f => `<option value="${f.id}">${f.filename} (${f.lines} khối)</option>`).join('');
}

async function delFile(id){
  if(!confirm('Xác nhận xóa tệp tin này?')) return;
  await api('/api/files/' + id, { method: 'DELETE' });
  Toast.success('Đã xóa tệp tin');
  loadFiles();
}

async function startSpam(){
  if(!selectedBoxes.length) return Toast.error('Chưa chọn hội thoại hoặc kênh nhận tin! Hãy qua tab Hội thoại để chọn.');
  var fid = document.getElementById('spam-file-select').value;
  var direct = document.getElementById('spam-messages').value.trim();
  var blocks = [];

  if(fid){
    var r = await api('/api/files/' + fid + '/preview');
    blocks = r.all || [];
  } else if(direct){
    if(currentMode === "treo_ngon"){
      blocks = [direct];
    } else if(currentMode === "treo_nhay"){
      blocks = [direct];
    } else {
      blocks = direct.includes(';') ? direct.split(';').map(m => m.trim()).filter(Boolean) : [direct];
    }
  }

  if(!blocks.length) return Toast.error('Vui lòng nhập văn bản cần gửi');
  var delay = parseFloat(document.getElementById('spam-delay').value) || 1;
  var iconCount = flags.emoji ? (parseInt(document.getElementById('icon-count').value) || 3) : 0;
  var tagUsers = document.getElementById('tg-tag').checked ? selectedTags : [];

  var payload = {
    targets: selectedBoxes,
    blocks: blocks,
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
  Toast.success('Khởi chạy tiến trình thành công!');
  loadTasks();
}

async function stopAll(){
  await api('/api/tasks/stop_all', { method: 'POST' });
  Toast.info('Đã ra lệnh dừng tiến trình');
  loadTasks();
}

async function loadTasks(){
  var tasks = await api('/api/tasks');
  if(!Array.isArray(tasks)) tasks = [];
  var tb = document.getElementById('tasks-tbody');
  tb.innerHTML = tasks.map(t => {
    var running = (t.status === 'running');
    return `<tr>
      <td><code>${t.id.slice(-6)}</code></td>
      <td><b>${t.type}</b></td>
      <td>${running ? '<span class="status-badge live" style="color:#2ecc71;">Đang gửi</span>' : '<span class="status-badge dead" style="color:#e74c3c;">Đã dừng</span>'}</td>
      <td>${running ? `<button class="btn-pill danger" onclick="stopTask('${t.id}')" style="padding:4px 10px; font-size:9.5px;">Dừng</button>` : ''}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="4" style="text-align:center; padding:12px; color:var(--txt-2);">Không có tiến trình</td></tr>';
}

async function stopTask(tid){
  await api('/api/tasks/' + tid + '/stop', { method: 'POST' });
  Toast.info('Đã dừng tiến trình');
  loadTasks();
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
  var col = ZALO_PALETTE.find(c => c.id === cid);
  Toast.info('Đã chọn màu: ' + (col ? col.name : cid));
}

function refreshAll(){ loadAccounts(); loadFiles(); loadTasks(); }

var snowCanvas = document.getElementById('snow-canvas');
var sCtx = snowCanvas.getContext('2d');
var sW = window.innerWidth;
var sH = window.innerHeight;
snowCanvas.width = sW; snowCanvas.height = sH;

var flakes = Array.from({ length: 65 }, () => ({
  x: Math.random() * sW,
  y: Math.random() * sH - sH,
  r: Math.random() * 3.5 + 1.2,
  dY: Math.random() * 1.3 + 0.6,
  dX: Math.random() * 1.0 - 0.5,
  opacity: Math.random() * 0.7 + 0.3
}));

function renderSnow() {
  sCtx.clearRect(0, 0, sW, sH);
  flakes.forEach(f => {
    sCtx.beginPath();
    sCtx.arc(f.x, f.y, f.r, 0, Math.PI * 2);
    sCtx.fillStyle = 'rgba(255, 255, 255, ' + f.opacity + ')';
    sCtx.fill();
    f.y += f.dY; f.x += f.dX;
    if (f.y > sH) { f.y = -10; f.x = Math.random() * sW; }
    if (f.x > sW) f.x = 0; if (f.x < 0) f.x = sW;
  });
  requestAnimationFrame(renderSnow);
}
renderSnow();

window.addEventListener('resize', () => {
  sW = window.innerWidth;
  sH = window.innerHeight;
  snowCanvas.width = sW;
  snowCanvas.height = sH;
});

loadColors();
refreshAll();
setInterval(loadTasks, 5000);
</script>
</body>
</html>
"""

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
    return jsonify([dict(r) for r in rows])


@app.route("/api/accounts/add_zalo", methods=["POST"])
@login_required
def api_accounts_add_zalo():
    d = request.json
    label = d.get("label", "").strip() or "zalo_" + str(int(time.time()))
    imei = d.get("imei", "").strip()
    ck = d.get("cookies", "").strip()
    if not imei or not ck:
        return jsonify({"error": "Vui lòng nhập đủ IMEI và Cookie Zalo"}), 400
    try:
        ck_obj = json.loads(ck)
        z = Zalo(imei, ck_obj)
        st = "live"
    except Exception as e:
        return jsonify({"error": "Không thể đăng nhập Zalo: " + str(e)}), 400

    conn = db()
    conn.execute("""
        INSERT INTO accounts (platform, label, imei, cookies, added_at,
                             uid, display_name, zalo_name, username, status)
        VALUES ('zalo', ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (label, imei, json.dumps(ck_obj), time.time(),
          z.uid, z.display_name or "", z.zalo_name or "", z.username or "", st))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "label": label})


@app.route("/api/accounts/add_discord", methods=["POST"])
@login_required
def api_accounts_add_discord():
    d = request.json
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


@app.route("/api/accounts/<int:aid>", methods=["DELETE"])
@login_required
def api_accounts_delete(aid):
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

        conn.execute("UPDATE accounts SET status = 'live' WHERE id = ?", (aid,))
        conn.commit()
        conn.close()
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
                z = Zalo(r["imei"], json.loads(r["cookies"]))
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
    return jsonify({"ok": True, "total": len(rows), "live": live_count})


@app.route("/api/accounts/<int:aid>/load_boxes", methods=["POST"])
@login_required
def api_load_boxes(aid):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    conn.close()
    if not row: return jsonify({"error": "Không tìm thấy tài khoản"}), 404

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
    if not row: return jsonify({"error": "Không tìm thấy tài khoản"}), 404
    try:
        z = Zalo(row["imei"], json.loads(row["cookies"]))
        members = z.get_members_full(group_id)
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
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Vui lòng chọn một tệp văn bản hợp lệ"}), 400
    safe = str(int(time.time())) + "_" + f.filename
    fp = os.path.join(UPLOAD_DIR, safe)
    f.save(fp)

    blocks = []
    current = []
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as file_read:
            content = file_read.read()
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        for line in content.split("\n"):
            if len(blocks) >= 5000: break
            if line.strip() == "":
                if current:
                    blocks.append("\n".join(current))
                    current = []
            else:
                current.append(line)
        if current:
            blocks.append("\n".join(current))
    except Exception as e:
        return jsonify({"error": "Lỗi đọc tệp: " + str(e)}), 400

    conn = db()
    conn.execute("INSERT INTO files (filename, filepath, lines, size, uploaded_at) VALUES (?, ?, ?, ?, ?)",
                 (f.filename, fp, len(blocks), os.path.getsize(fp), time.time()))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "filename": f.filename, "lines": len(blocks)})


@app.route("/api/files/<int:fid>", methods=["DELETE"])
@login_required
def api_files_delete(fid):
    conn = db()
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
    if not row: return jsonify({"error": "Không tìm thấy tập tin"}), 404

    blocks = []
    current = []
    try:
        with open(row["filepath"], "r", encoding="utf-8", errors="ignore") as file_read:
            content = file_read.read()
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        for line in content.split("\n"):
            if len(blocks) >= 5000: break
            if line.strip() == "":
                if current:
                    blocks.append("\n".join(current))
                    current = []
            else:
                current.append(line)
        if current:
            blocks.append("\n".join(current))
    except Exception:
        pass

    return jsonify({"filename": row["filename"], "all": blocks})


@app.route("/api/tasks", methods=["GET"])
@login_required
def api_tasks():
    conn = db()
    rows = conn.execute("SELECT * FROM tasks ORDER BY started_at DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ============================================================
# WORKER ĐA NỀN TẢNG (ZALO & DISCORD)
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
        except Exception as e:
            print(f"Lỗi đăng nhập Zalo #{acc_id}: {e}")
            HEALTH_MGR.report_error(acc_id)
            return
    else:
        token = acc_dict["token"]
        try:
            client = DiscordBot(token, is_bot=bool(acc_dict.get("is_bot", 1)))
            if not client.check():
                raise Exception("Token không hợp lệ")
        except Exception as e:
            print(f"Lỗi đăng nhập Discord #{acc_id}: {e}")
            HEALTH_MGR.report_error(acc_id)
            return

    b_idx, t_idx = 0, 0
    color_counter = 0

    while not stop_ev.is_set():
        if not targets or not blocks:
            break

        if antidieall and not HEALTH_MGR.is_usable(acc_id):
            time.sleep(2)
            continue

        target = targets[t_idx % len(targets)]
        t_idx += 1
        target_type = target.get("type", "group")
        target_id = target.get("id")

        is_discord_target = (target_type == "discord_channel")
        if (plat == "zalo" and is_discord_target) or (plat == "discord" and not is_discord_target):
            continue

        is_group = (target_type == "group")
        raw = blocks[b_idx % len(blocks)]
        b_idx += 1

        try:
            if mode == "treo_ngon":
                text = raw.replace("\r\n", "\n").replace("\r", "\n")
                if use_emoji and icon_count > 0:
                    text = text + " " + " ".join([get_icon_hard() for _ in range(icon_count)])

                if plat == "zalo":
                    client.send_adv(text, target_id, color_mode=color_mode, fixed_color=fixed_color,
                                    is_group=is_group, mentions=(tag_users if is_group else None),
                                    tag_all=(tag_all if is_group else False), is_heading=is_heading,
                                    color_offset=color_counter, antiband=antiband)
                else:
                    client.send_message(target_id, text, color_mode=color_mode,
                                        fixed_color=fixed_color, antiband=antiband)

                color_counter += 1
                with lock: counter["sent"] += 1
                HEALTH_MGR.report_success(acc_id)

            elif mode == "treo_nhay":
                lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
                for ln in lines:
                    if stop_ev.is_set(): break
                    msg_line = ln
                    if use_emoji and icon_count > 0:
                        msg_line += " " + " ".join([get_icon_hard() for _ in range(icon_count)])

                    if plat == "zalo":
                        client.send_adv(msg_line, target_id, color_mode=color_mode, fixed_color=fixed_color,
                                        is_group=is_group, mentions=(tag_users if is_group else None),
                                        tag_all=(tag_all if is_group else False), is_heading=is_heading,
                                        color_offset=color_counter, antiband=antiband)
                    else:
                        client.send_message(target_id, msg_line, color_mode=color_mode,
                                            fixed_color=fixed_color, antiband=antiband)

                    color_counter += 1
                    with lock: counter["sent"] += 1
                    HEALTH_MGR.report_success(acc_id)
                    time.sleep(0.3)
            else:
                text = raw
                if use_emoji and icon_count > 0:
                    text = text + " " + " ".join([get_icon_hard() for _ in range(icon_count)])

                if plat == "zalo":
                    client.send_adv(text, target_id, color_mode=color_mode, fixed_color=fixed_color,
                                    is_group=is_group, mentions=(tag_users if is_group else None),
                                    tag_all=(tag_all if is_group else False), is_heading=is_heading,
                                    color_offset=color_counter, antiband=antiband)
                else:
                    client.send_message(target_id, text, color_mode=color_mode,
                                        fixed_color=fixed_color, antiband=antiband)

                color_counter += 1
                with lock: counter["sent"] += 1
                HEALTH_MGR.report_success(acc_id)

        except Exception as e:
            err_str = str(e)
            print(f"[Worker #{acc_id}] Lỗi gửi: {err_str}")
            if "429:RateLimit:" in err_str:
                try:
                    retry_after = float(err_str.split(":")[-1])
                except Exception:
                    retry_after = 20
                HEALTH_MGR.report_rate_limit(acc_id, retry_after)
            else:
                HEALTH_MGR.report_error(acc_id)

        actual_delay = delay
        if antiband:
            actual_delay += random.uniform(0.1, 0.35)
        time.sleep(max(0.3, actual_delay))


def task_supervisor(tid, targets, blocks, delay, use_emoji, icon_count,
                    tag_users, tag_all, is_heading, multi_acc, mode, color_mode, fixed_color,
                    stop_ev, antiband=True, antidieall=True):
    conn = db()
    accs = conn.execute("SELECT * FROM accounts WHERE enabled = 1").fetchall()
    if not accs:
        accs = conn.execute("SELECT * FROM accounts").fetchall()
    conn.close()

    if not accs:
        conn = db()
        conn.execute("UPDATE tasks SET status = 'stopped', stats = ? WHERE id = ?",
                     (json.dumps({"error": "Không có tài khoản nào trong hệ thống"}), tid))
        conn.commit()
        conn.close()
        ACTIVE_TASKS.pop(tid, None)
        return

    counter = {"sent": 0}
    lock = threading.Lock()
    threads = []

    if multi_acc:
        for a in accs:
            t = threading.Thread(
                target=single_acc_worker,
                args=(dict(a), targets, blocks, delay, use_emoji, icon_count,
                      tag_users, tag_all, is_heading, mode, color_mode, fixed_color,
                      stop_ev, counter, lock, antiband, antidieall),
                daemon=True
            )
            threads.append(t)
            t.start()
    else:
        t = threading.Thread(
            target=single_acc_worker,
            args=(dict(accs[0]), targets, blocks, delay, use_emoji, icon_count,
                  tag_users, tag_all, is_heading, mode, color_mode, fixed_color,
                  stop_ev, counter, lock, antiband, antidieall),
            daemon=True
        )
        threads.append(t)
        t.start()

    while not stop_ev.is_set():
        alive = [t for t in threads if t.is_alive()]
        if not alive:
            break
        time.sleep(1)

    for th in threads:
        th.join(timeout=0.2)

    conn = db()
    conn.execute("UPDATE tasks SET status = 'stopped', stats = ? WHERE id = ?",
                 (json.dumps({"sent": counter["sent"]}), tid))
    conn.commit()
    conn.close()
    ACTIVE_TASKS.pop(tid, None)


@app.route("/api/tasks/start", methods=["POST"])
@login_required
def api_tasks_start():
    d = request.json
    targets = d.get("targets", [])
    blocks = d.get("blocks", [])
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

    if not targets or not blocks:
        return jsonify({"error": "Vui lòng chọn hội thoại / kênh và nhập nội dung cần gửi"}), 400

    tid = new_tid("task")
    stop_ev = threading.Event()

    th = threading.Thread(
        target=task_supervisor,
        args=(tid, targets, blocks, delay, use_emoji, icon_count,
              tag_users, tag_all, is_heading, multi_acc, mode, color_mode, fixed_color,
              stop_ev, antiband, antidieall),
        daemon=True
    )

    conn = db()
    conn.execute("INSERT INTO tasks (id, type, meta, status, started_at, stats) VALUES (?, ?, ?, ?, ?, ?)",
                 (tid, mode, json.dumps({"multi_acc": multi_acc, "color_mode": color_mode}), "running", time.time(), "{}"))
    conn.commit()
    conn.close()

    ACTIVE_TASKS[tid] = {"stop": stop_ev, "thread": th}
    th.start()
    return jsonify({"ok": True, "task_id": tid})


@app.route("/api/tasks/<tid>/stop", methods=["POST"])
@login_required
def api_tasks_stop(tid):
    if tid in ACTIVE_TASKS:
        ACTIVE_TASKS[tid]["stop"].set()
        return jsonify({"ok": True})
    return jsonify({"error": "Không tìm thấy tiến trình"}), 404


@app.route("/api/tasks/stop_all", methods=["POST"])
@login_required
def api_tasks_stop_all():
    for tid, t in list(ACTIVE_TASKS.items()):
        t["stop"].set()
    return jsonify({"ok": True, "count": len(ACTIVE_TASKS)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
