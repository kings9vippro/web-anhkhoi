# ============================================================
# Bản quyền thuộc về Phạm Anh Khôi
# Hệ thống điều hành: ALB Forge — ThreeUI Sakura Edition 2026
# Thiết kế & Phát triển giao diện cao cấp lấy cảm hứng từ ThreeUI (MengTo)
# ============================================================
import os
import sys
import json
import time
import sqlite3
import threading
import random
import base64
import re
import hashlib
import mimetypes
import io
import shutil
from datetime import datetime
from functools import wraps
from collections import defaultdict, deque

from flask import (
    Flask, render_template_string, request, jsonify,
    session, redirect, url_for, send_from_directory, Response
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
app.secret_key = os.environ.get("SECRET_KEY", "phamanhkhoi-sakura-threeui-2026")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

# ============================================================
# BỘ LỌC BẢO MẬT & CHỐNG TẤN CÔNG DDOS CHUYÊN SÂU
# ============================================================
DDOS_LIMIT_PER_MINUTE = 150
DDOS_BURST_PER_SEC = 30
LOGIN_MAX_FAILS = 5
LOGIN_LOCKOUT_TIME = 900

ip_request_history = defaultdict(list)
ip_blocked_until = {}
login_fail_tracker = defaultdict(lambda: {"count": 0, "locked_until": 0})
security_lock = threading.Lock()
system_logs = deque(maxlen=200)

def log_event(level, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = {"ts": ts, "level": level, "msg": msg}
    system_logs.appendleft(entry)
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute("INSERT INTO logs (timestamp, level, message) VALUES (?, ?, ?)",
                     (time.time(), level, msg))
        conn.commit()
        conn.close()
    except Exception:
        pass

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
                    "error": "IP của bạn đang bị chặn do gửi yêu cầu quá nhanh. Vui lòng quay lại sau.",
                    "retry_after": int(ip_blocked_until[ip] - now)
                }), 429
            else:
                del ip_blocked_until[ip]

        history = [t for t in ip_request_history[ip] if now - t < 60]
        ip_request_history[ip] = history

        burst = sum(1 for t in history if now - t <= 1.0)
        if burst > DDOS_BURST_PER_SEC or len(history) > DDOS_LIMIT_PER_MINUTE:
            ip_blocked_until[ip] = now + 300
            log_event("WARN", f"Chặn IP {ip} trong 5 phút do vượt ngưỡng tần suất ({burst}/s)")
            return jsonify({"error": "Phát hiện lưu lượng bất thường. IP đã bị khóa trong 5 phút."}), 429

        ip_request_history[ip].append(now)

    if not session.get("human_verified") and request.endpoint not in ("verify_gate", "api_verify_human"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Chưa hoàn tất kiểm tra an toàn danh tính"}), 403
        return redirect(url_for("verify_gate"))

# ============================================================
# CƠ SỞ DỮ LIỆU & QUẢN LÝ CÀI ĐẶT HỆ THỐNG
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT, imei TEXT, cookies TEXT,
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
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            level TEXT,
            message TEXT
        )
    """)
    conn.commit()

    # Cài đặt mặc định nếu chưa có
    defaults = {
        "web_title": "I LOVE NGỌC HÂN 🌸",
        "designer_name": "Phạm Anh Khôi",
        "logo_path": "/static/logo.png",
        "theme_mode": "sakura_threeui",
        "font_size_default": "heading",
        "tag_all_mode": "native"
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

init_db()

def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def get_setting(key, default=""):
    try:
        conn = db()
        r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        conn.close()
        return r["value"] if r else default
    except Exception:
        return default

def set_setting(key, value):
    try:
        conn = db()
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

ACTIVE_TASKS = {}

def new_tid(p):
    return p + "_" + str(int(time.time() * 1000)) + "_" + str(random.randint(100, 999))

def utf16_len(s):
    return len(s.encode('utf-16-le')) // 2

# ============================================================
# BẢNG MÀU CHUẨN ZALO PALETTE (HEX SẠCH SẼ & ĐÚNG ĐỊNH DẠNG)
# ============================================================
ZALO_PALETTE = [
    {"id": "red",     "name": "Đỏ Rực Rỡ",      "hex": "#e8453c", "clean": "e8453c"},
    {"id": "yellow",  "name": "Vàng Ánh Kim",    "hex": "#f5c500", "clean": "f5c500"},
    {"id": "green",   "name": "Xanh Ngọc Lục",  "hex": "#00b14f", "clean": "00b14f"},
    {"id": "orange",  "name": "Cam Rực Lửa",    "hex": "#ff8c00", "clean": "ff8c00"},
    {"id": "ocean",   "name": "Xanh Biển Sâu",  "hex": "#0091ff", "clean": "0091ff"},
    {"id": "blue",    "name": "Xanh Dương Đậm", "hex": "#0068ff", "clean": "0068ff"},
    {"id": "purple",  "name": "Tím Pha Lê",     "hex": "#a05eff", "clean": "a05eff"},
    {"id": "pink",    "name": "Hồng Hoa Anh Đào","hex": "#ff47a8", "clean": "ff47a8"},
    {"id": "cyan",    "name": "Xanh Neon",      "hex": "#00f0ff", "clean": "00f0ff"},
    {"id": "crimson", "name": "Đỏ Thẫm",       "hex": "#d32f2f", "clean": "d32f2f"},
]

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
    "😹", "😈", "🔥", "😤", "🤮", "🤢", "🐒", "✌️", "☝️", "😁",
    "🌸", "✨", "⚡", "💥", "🎯", "👑", "🚀", "💎"
]

def get_icon_hard():
    if random.random() < 0.60:
        return random.choice(ZALO_ICON_HARD)
    return random.choice(ZALO_ICON_UNICODE)

# ============================================================
# ĐỘNG CƠ ĐỌC TỆP TIN DUNG LƯỢNG LỚN (SIÊU NHANH, O(1) MEMORY)
# ============================================================
class FileBlockReader:
    """
    Đọc tệp tin nhiều MB trực tiếp từ đĩa cứng theo cơ chế Stream/Generator.
    Khắc phục triệt để tình trạng đơ lag hoặc tải chậm khi tệp lớn.
    """
    @staticmethod
    def inspect_file(filepath):
        total_lines = 0
        total_blocks = 0
        current_block = []
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    total_lines += 1
                    s = line.strip()
                    if not s:
                        if current_block:
                            total_blocks += 1
                            current_block = []
                    else:
                        current_block.append(s)
                if current_block:
                    total_blocks += 1
        except Exception:
            pass
        return max(1, total_blocks), total_lines

    @staticmethod
    def get_preview(filepath, max_blocks=30):
        blocks = []
        current = []
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if len(blocks) >= max_blocks:
                        break
                    s = line.strip()
                    if not s:
                        if current:
                            blocks.append("\n".join(current))
                            current = []
                    else:
                        current.append(s)
                if current and len(blocks) < max_blocks:
                    blocks.append("\n".join(current))
        except Exception as e:
            return [f"Lỗi đọc tập tin: {e}"]
        return blocks

    @staticmethod
    def iterate_blocks_forever(filepath, mode="fast"):
        """
        Generator quay vòng vô tận, đọc từng khối trực tiếp từ tệp tin mà không giữ toàn bộ tệp trong RAM.
        """
        while True:
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    current = []
                    for line in f:
                        s = line.rstrip("\r\n")
                        if mode == "treo_nhay":
                            # Chế độ Treo Nhây: gửi từng dòng đơn lẻ
                            if s.strip():
                                yield s.strip()
                        else:
                            # Chế độ Khối/Treo Ngôn: gom khối theo dòng trống
                            if not s.strip():
                                if current:
                                    yield "\n".join(current)
                                    current = []
                            else:
                                current.append(s)
                    if current and mode != "treo_nhay":
                        yield "\n".join(current)
            except Exception as e:
                time.sleep(1)
                yield f"[Lỗi luồng đọc tệp: {e}]"


# ============================================================
# GIAO THỨC ĐIỀU KHIỂN ZALO CHUYÊN SÂU (ZALO PROTOCOL CLIENT)
# ============================================================
class Zalo:
    def __init__(self, imei, cookies):
        self.imei = str(imei).strip()
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/128.0.0.0 Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
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
        self.display_name = ud.get("displayName") or ud.get("zaloName") or ud.get("username")
        self.zalo_name = ud.get("zaloName")
        self.username = ud.get("username")
        if not self.secret_key:
            raise Exception("Không thể lấy khóa giải mã bảo mật zpw_enk")

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
            try:
                enc2 = self._enc({"grid": str(gid), "userIds": missing_uids, "friendId": missing_uids})
                r2 = self.s.post(
                    "https://tt-group-wpa.chat.zalo.me/api/group/getuserinfo",
                    params={"zpw_ver": 645, "zpw_type": 30},
                    data={"params": enc2}, timeout=18,
                )
                dec2 = self._dec(r2.json()["data"])
                profiles_data = json.loads(dec2).get("data", {})
                profiles = profiles_data.get("profiles", {}) if isinstance(profiles_data, dict) else {}
                for uid in missing_uids:
                    p = profiles.get(uid, {})
                    pname = (p.get("displayName") or p.get("zaloName") or p.get("username") or "").strip()
                    if pname:
                        members_dict[uid] = pname
            except Exception:
                pass

        out = []
        for uid in uids:
            real_name = members_dict.get(uid) or f"Thành viên {uid[-6:]}"
            out.append({
                "id": str(uid),
                "name": real_name
            })
        return out

    def build_colored_message(self, raw_text, color_mode, fixed_color, font_size_mode="heading", is_heading=True):
        """
        Khắc phục triệt để lỗi không in đậm to ra và không đổi được màu:
        1. Sử dụng mã HEX sạch không có dấu '#' cho Zalo Web Client (c_e8453c thay vì c_#e8453c).
        2. Tích hợp đồng thời cả Markdown (#, **) và các mã phong cách styles ('b', 'h1', 'font_24', 'large').
        3. Thiết lập msgColor theo bảng màu Zalo chính thức để đổi màu bóng tin nhắn.
        """
        lines = [l for l in str(raw_text).split("\n")]
        styled_lines = []
        styles = []
        current_u16_pos = 0

        RAINBOW_PALETTE = [
            {"clean": "e8453c", "id": "red"},
            {"clean": "ff8c00", "id": "orange"},
            {"clean": "f5c500", "id": "yellow"},
            {"clean": "00b14f", "id": "green"},
            {"clean": "0091ff", "id": "ocean"},
            {"clean": "a05eff", "id": "purple"},
            {"clean": "ff47a8", "id": "pink"},
            {"clean": "00f0ff", "id": "cyan"}
        ]
        first_color = "red"

        for i, ln in enumerate(lines):
            content = ln.strip()
            if not content:
                styled_lines.append("")
                current_u16_pos += 1
                continue

            # Xử lý định dạng chữ to / in đậm
            if font_size_mode == "giant":
                # Khổng lồ: Tiêu đề H1 kết hợp In đậm
                if not content.startswith("#"):
                    line_text = f"# **{content}**"
                else:
                    line_text = f"**{content}**"
            elif font_size_mode == "heading" or is_heading:
                # Tiêu đề lớn: Tiêu đề H1 Zalo
                if not content.startswith("#"):
                    line_text = f"# {content}"
                else:
                    line_text = content
            elif font_size_mode == "bold":
                # In đậm chuẩn
                line_text = f"**{content}**"
            else:
                # Chuẩn bình thường
                line_text = content

            styled_lines.append(line_text)
            l_len = utf16_len(line_text)

            # Xác định màu sắc từng dòng
            if color_mode in ("rainbow", "random"):
                chosen = RAINBOW_PALETTE[i % len(RAINBOW_PALETTE)] if color_mode == "rainbow" else random.choice(RAINBOW_PALETTE)
                c_clean = chosen["clean"]
                c_id = chosen["id"]
            elif color_mode == "fixed" and fixed_color:
                match = next((c for c in ZALO_PALETTE if c["id"] == fixed_color), None)
                if match:
                    c_clean = match["clean"]
                    c_id = match["id"]
                else:
                    c_clean = "e8453c"
                    c_id = "red"
            else:
                c_clean = None
                c_id = None

            if i == 0 and c_id:
                first_color = c_id

            # Đóng gói phong cách kiểu Zalo Web & Desktop
            if c_clean:
                # Mã phong cách màu Zalo chính thức (Bắt buộc không có dấu '#')
                styles.append({"start": current_u16_pos, "len": l_len, "st": f"c_{c_clean}"})
                styles.append({"offset": current_u16_pos, "len": l_len, "type": "color", "value": c_clean})
                styles.append({"offset": current_u16_pos, "len": l_len, "type": "color", "value": f"#{c_clean}"})

            # Bổ sung phong cách In đậm và To rõ vào styles
            if font_size_mode in ("giant", "heading", "bold") or is_heading:
                styles.append({"start": current_u16_pos, "len": l_len, "st": "b"})
                styles.append({"offset": current_u16_pos, "len": l_len, "type": "bold"})

            if font_size_mode in ("giant", "heading") or is_heading:
                styles.append({"start": current_u16_pos, "len": l_len, "st": "h1"})
                styles.append({"start": current_u16_pos, "len": l_len, "st": "font_24"})
                styles.append({"offset": current_u16_pos, "len": l_len, "type": "font", "size": "24"})

            current_u16_pos += l_len + 1

        final_msg = "\n".join(styled_lines)
        return final_msg, styles, first_color

    def attach_mentions(self, msg, mentions, tag_all=False, group_members=None):
        """
        Khắc phục triệt để lỗi Tag All (@All):
        1. Sử dụng đúng định dạng Zalo Mention All: uid='-1' và type=0 (hoặc 1).
        2. Tự động chèn token '@All' vào nội dung tin nhắn.
        3. Tùy chọn mở rộng: Tag toàn bộ danh sách thành viên nếu nhóm yêu cầu.
        """
        final = msg
        m_arr = []

        if tag_all:
            tag_token = "@All"
            pos = utf16_len(final) + (1 if final else 0)
            final = (final + " " + tag_token) if final else tag_token
            # Truyền đồng thời cả type 0 và type 1 để tương thích mọi phiên bản máy chủ Zalo
            m_arr.append({"uid": "-1", "pos": pos, "len": utf16_len(tag_token), "type": 0})
            m_arr.append({"uid": "-1", "pos": pos, "len": utf16_len(tag_token), "type": 1})
            return final, m_arr

        if mentions:
            for m in mentions:
                raw_name = str(m.get("name", "")).strip()
                name = raw_name.split(" (")[0] if " (" in raw_name else raw_name
                uid = str(m.get("uid") or m.get("id") or "").strip()
                if not name or not uid:
                    continue
                tag_token = f"@{name}"
                pos = utf16_len(final) + (1 if final else 0)
                final = (final + " " + tag_token) if final else tag_token
                m_arr.append({"uid": uid, "pos": pos, "len": utf16_len(tag_token), "type": 0})

        return final, m_arr

    def send_adv(self, raw_text, thread_id, color_mode="rainbow", fixed_color="red",
                 is_group=True, mentions=None, tag_all=False, font_size_mode="heading",
                 is_heading=True, group_members=None):
        url = ("https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
               if is_group
               else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms")

        final_msg, styles, first_color = self.build_colored_message(
            raw_text, color_mode, fixed_color, font_size_mode=font_size_mode, is_heading=is_heading
        )

        final_msg, m_arr = self.attach_mentions(
            final_msg, mentions, tag_all=tag_all, group_members=group_members
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
# CÁC LUỒNG TIẾN TRÌNH GỬI TIN & GIÁM SÁT HỆ THỐNG
# ============================================================
def single_acc_worker(acc_dict, targets, file_path, blocks, delay, use_emoji, icon_count,
                      tag_users, tag_all, font_size_mode, is_heading, mode, color_mode,
                      fixed_color, stop_ev, counter, lock):
    imei = acc_dict["imei"]
    aid = acc_dict["id"]
    label = acc_dict["label"]
    try:
        cookies = json.loads(acc_dict["cookies"])
        z = Zalo(imei, cookies)
    except Exception as e:
        log_event("ERROR", f"Tài khoản {label} lỗi khởi tạo: {e}")
        return

    log_event("INFO", f"Tài khoản {label} bắt đầu gửi tin nhắn...")
    t_idx = 0

    # Nếu có file_path thì dùng Stream Generator để không tốn RAM và không lag
    if file_path and os.path.exists(file_path):
        block_gen = FileBlockReader.iterate_blocks_forever(file_path, mode=mode)
    else:
        # Dùng danh sách blocks truyền trực tiếp
        def mem_gen():
            idx = 0
            while True:
                if not blocks:
                    yield "Tin nhắn mặc định từ ALB Forge"
                else:
                    yield blocks[idx % len(blocks)]
                    idx += 1
        block_gen = mem_gen()

    while not stop_ev.is_set():
        target = targets[t_idx % len(targets)]
        t_idx += 1
        is_group = (target.get("type") == "group")
        target_id = target.get("id")

        try:
            raw = next(block_gen)
        except Exception:
            raw = "Nội dung gửi"

        try:
            if mode == "treo_ngon":
                text = raw.replace("\r\n", "\n").replace("\r", "\n")
                if use_emoji and icon_count > 0:
                    text = text + " " + " ".join([get_icon_hard() for _ in range(icon_count)])
                z.send_adv(text, target_id, color_mode=color_mode, fixed_color=fixed_color,
                           is_group=is_group, mentions=tag_users, tag_all=tag_all,
                           font_size_mode=font_size_mode, is_heading=is_heading)
                with lock:
                    counter["sent"] += 1

            elif mode == "treo_nhay":
                # Gửi từng dòng nguyên văn, không kèm số thứ tự
                lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
                for ln in lines:
                    if stop_ev.is_set():
                        break
                    msg_line = ln
                    if use_emoji and icon_count > 0:
                        msg_line += " " + " ".join([get_icon_hard() for _ in range(icon_count)])
                    z.send_adv(msg_line, target_id, color_mode=color_mode, fixed_color=fixed_color,
                               is_group=is_group, mentions=tag_users, tag_all=tag_all,
                               font_size_mode=font_size_mode, is_heading=is_heading)
                    with lock:
                        counter["sent"] += 1
                    time.sleep(0.3)
            else:
                # Chế độ Siêu nhanh (Fast)
                text = raw
                if use_emoji and icon_count > 0:
                    text = text + " " + " ".join([get_icon_hard() for _ in range(icon_count)])
                z.send_adv(text, target_id, color_mode=color_mode, fixed_color=fixed_color,
                           is_group=is_group, mentions=tag_users, tag_all=tag_all,
                           font_size_mode=font_size_mode, is_heading=is_heading)
                with lock:
                    counter["sent"] += 1

        except Exception as ex:
            log_event("WARN", f"Lỗi gửi tin ({label}): {ex}")

        time.sleep(max(0.3, delay))

    log_event("INFO", f"Tài khoản {label} đã dừng gửi tin.")

def task_supervisor(tid, targets, file_path, blocks, delay, use_emoji, icon_count,
                    tag_users, tag_all, font_size_mode, is_heading, multi_acc, mode,
                    color_mode, fixed_color, stop_ev):
    conn = db()
    accs = conn.execute("SELECT * FROM accounts WHERE status = 'live' OR status = 'unknown'").fetchall()
    conn.close()
    if not accs:
        log_event("ERROR", f"Không có tài khoản nào sẵn sàng cho tiến trình {tid}")
        return

    counter = {"sent": 0}
    lock = threading.Lock()
    threads = []

    if multi_acc:
        for a in accs:
            t = threading.Thread(
                target=single_acc_worker,
                args=(dict(a), targets, file_path, blocks, delay, use_emoji, icon_count,
                      tag_users, tag_all, font_size_mode, is_heading, mode, color_mode,
                      fixed_color, stop_ev, counter, lock),
                daemon=True
            )
            threads.append(t)
            t.start()
    else:
        t = threading.Thread(
            target=single_acc_worker,
            args=(dict(accs[0]), targets, file_path, blocks, delay, use_emoji, icon_count,
                  tag_users, tag_all, font_size_mode, is_heading, mode, color_mode,
                  fixed_color, stop_ev, counter, lock),
            daemon=True
        )
        threads.append(t)
        t.start()

    while not stop_ev.is_set():
        time.sleep(1)

    for th in threads:
        th.join(timeout=0.2)

    conn = db()
    conn.execute("UPDATE tasks SET status = 'stopped', stats = ? WHERE id = ?",
                 (json.dumps({"sent": counter["sent"]}), tid))
    conn.commit()
    conn.close()
    ACTIVE_TASKS.pop(tid, None)
    log_event("SUCCESS", f"Tiến trình {tid} đã dừng thành công. Tổng tin đã gửi: {counter['sent']}")


# ============================================================
# HỆ THỐNG CSS PHONG CÁCH THREEUI (MENGTO) & HOA ANH ĐÀO CAO CẤP
# ============================================================
CSS_SAKURA_THREEUI = """
:root {
  --bg-page: #faf7f9;
  --bg-card: rgba(255, 255, 255, 0.88);
  --border-color: rgba(255, 183, 197, 0.45);
  --border-glow: rgba(255, 105, 180, 0.35);
  --txt-0: #0f172a;
  --txt-1: #1e293b;
  --txt-2: #64748b;
  --txt-muted: #94a3b8;
  --sakura: #ff69b4;
  --sakura-deep: #e11d48;
  --sakura-glow: rgba(255, 105, 180, 0.4);
  --leaf-green: #34d399;
  --grad-sakura: linear-gradient(135deg, #ff758c 0%, #ff7eb3 50%, #f472b6 100%);
  --grad-dark: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  --grad-glass: linear-gradient(135deg, rgba(255,255,255,0.92) 0%, rgba(255,245,247,0.75) 100%);
  --grad-neon: linear-gradient(135deg, #ff69b4 0%, #00f0ff 100%);
  --shadow-soft: 0 10px 35px -5px rgba(255, 117, 140, 0.12), 0 0 0 1px rgba(255, 255, 255, 0.8) inset;
  --shadow-glow: 0 0 25px rgba(255, 105, 180, 0.25);
  --shadow-dock: 0 15px 45px -5px rgba(255, 117, 140, 0.25);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
  -webkit-tap-highlight-color: transparent;
}

html {
  touch-action: manipulation;
  -webkit-text-size-adjust: 100%;
}

body {
  font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background-color: var(--bg-page);
  color: var(--txt-1);
  min-height: 100vh;
  padding-bottom: 120px;
  position: relative;
  overflow-x: hidden;
}

/* HÌNH NỀN AMBIENT PHÁT SÁNG */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  background: radial-gradient(circle at 85% 15%, rgba(255, 192, 203, 0.35) 0%, transparent 45%),
              radial-gradient(circle at 15% 85%, rgba(255, 182, 193, 0.25) 0%, transparent 40%),
              radial-gradient(circle at 50% 50%, rgba(255, 240, 245, 0.5) 0%, transparent 70%);
  pointer-events: none !important;
  z-index: -2;
}

body::after {
  content: '';
  position: fixed;
  inset: 0;
  background-image: url('/static/bg.jpg');
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  opacity: 0.12;
  filter: blur(5px);
  pointer-events: none !important;
  z-index: -1;
}

/* CANVAS HOA & LÁ ANH ĐÀO RƠI 60FPS */
#sakura-canvas {
  position: fixed;
  inset: 0;
  pointer-events: none !important;
  z-index: 1;
  width: 100%;
  height: 100%;
}

/* CÀNH HOA ANH ĐÀO ĐẶC SẮC (NHIỀU LÁ, HOA NỞ, ĐUNG ĐƯA THEO GIÓ) */
.cherry-blossom-tree-branch {
  position: fixed;
  top: -15px;
  right: -15px;
  width: 320px;
  max-width: 48vw;
  height: auto;
  pointer-events: none !important;
  z-index: 8;
  filter: drop-shadow(0 12px 25px rgba(255, 105, 180, 0.22));
  transform-origin: top right;
  animation: branchSway 6.5s ease-in-out infinite alternate;
}

@keyframes branchSway {
  0% { transform: rotate(0deg) scale(1); }
  50% { transform: rotate(1.8deg) scale(1.015) translateY(3px); }
  100% { transform: rotate(-1.2deg) scale(0.995) translateY(-2px); }
}

/* PRELOADER MÀN HÌNH TẢI TRANG THREEUI (MENGTO STYLE) */
#threeui-preloader {
  position: fixed;
  inset: 0;
  z-index: 999999;
  background: rgba(250, 247, 249, 0.96);
  backdrop-filter: blur(35px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  transition: opacity 0.6s var(--ease), visibility 0.6s var(--ease);
}
#threeui-preloader.loaded {
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
}
.preloader-emblem {
  position: relative;
  width: 110px;
  height: 110px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24px;
}
.preloader-ring-outer {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2px dashed rgba(255, 105, 180, 0.4);
  animation: preloaderSpin 8s linear infinite;
}
.preloader-ring-inner {
  position: absolute;
  inset: 10px;
  border-radius: 50%;
  border: 2.5px solid transparent;
  border-top-color: var(--sakura);
  border-right-color: #00f0ff;
  animation: preloaderSpinFast 1.4s cubic-bezier(0.4, 0, 0.2, 1) infinite;
}
.preloader-logo {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  overflow: hidden;
  border: 2px solid #fff;
  box-shadow: 0 0 25px rgba(255, 105, 180, 0.45);
  animation: pulsePreloader 2s ease-in-out infinite;
}
.preloader-logo img { width: 100%; height: 100%; object-fit: cover; }
@keyframes preloaderSpin { 100% { transform: rotate(360deg); } }
@keyframes preloaderSpinFast { 100% { transform: rotate(360deg); } }
@keyframes pulsePreloader { 0%, 100% { transform: scale(0.96); } 50% { transform: scale(1.05); } }

.preloader-title {
  font-family: 'Orbitron', sans-serif;
  font-size: 16px;
  font-weight: 900;
  letter-spacing: 1.5px;
  color: var(--txt-0);
  margin-bottom: 8px;
}
.preloader-sub {
  font-size: 11px;
  color: var(--txt-2);
  font-weight: 600;
  margin-bottom: 20px;
  min-height: 18px;
}
.preloader-bar-wrap {
  width: 260px;
  height: 6px;
  background: rgba(255, 183, 197, 0.25);
  border-radius: 99px;
  overflow: hidden;
  position: relative;
}
.preloader-bar-fill {
  height: 100%;
  width: 0%;
  background: var(--grad-sakura);
  border-radius: 99px;
  transition: width 0.3s ease;
  box-shadow: 0 0 12px rgba(255, 105, 180, 0.6);
}
.preloader-pct {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 800;
  color: var(--sakura);
  margin-top: 10px;
}

/* THANH TIÊU ĐỀ HEADER THREEUI */
.header {
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(28px);
  -webkit-backdrop-filter: blur(28px);
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-color);
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 4px 20px rgba(255, 117, 140, 0.06);
}
.header-inner {
  max-width: 1080px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 14px;
}
.logo-box {
  width: 50px;
  height: 50px;
  border-radius: 50%;
  overflow: hidden;
  border: 2.5px solid #fff;
  box-shadow: 0 4px 18px rgba(255, 105, 180, 0.35);
  background: #fff;
  flex-shrink: 0;
  animation: pulseLogo 3.5s ease-in-out infinite;
  cursor: pointer;
  transition: transform 0.25s var(--ease);
}
.logo-box:hover { transform: scale(1.08) rotate(5deg); }
@keyframes pulseLogo { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.06); } }
.logo-box img { width: 100%; height: 100%; object-fit: cover; }

.header-meta { flex: 1; min-width: 0; }
.header-meta h1 {
  font-family: 'Orbitron', sans-serif;
  font-size: 16px;
  font-weight: 900;
  color: var(--txt-0);
  display: flex;
  align-items: center;
  gap: 8px;
}
.header-meta p {
  font-size: 11px;
  color: var(--txt-2);
  font-weight: 700;
  margin-top: 2px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.v-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #0084ff;
  font-weight: 900;
  filter: drop-shadow(0 2px 4px rgba(0,132,255,0.3));
}
.status-pill-radar {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border-radius: 99px;
  font-size: 9.5px;
  font-weight: 800;
  background: rgba(16, 185, 129, 0.1);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.25);
}
.radar-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #10b981;
  position: relative;
}
.radar-dot::after {
  content: '';
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  border: 1.5px solid #10b981;
  animation: radarPing 1.6s cubic-bezier(0, 0, 0.2, 1) infinite;
}
@keyframes radarPing {
  0% { transform: scale(0.8); opacity: 1; }
  100% { transform: scale(2.4); opacity: 0; }
}

/* KHUNG CHỨA TOÀN BỘ NỘI DUNG */
.container {
  max-width: 1080px;
  margin: 0 auto;
  padding: 20px 16px;
  position: relative;
  z-index: 10;
}
.panel {
  display: none;
  animation: panelSlideIn 0.35s var(--ease) both;
}
.panel.active { display: block; }
@keyframes panelSlideIn {
  from { opacity: 0; transform: translateY(12px) scale(0.99); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

/* THẺ CARD PHONG CÁCH THREEUI GLASSMORPHISM */
.card {
  background: var(--bg-card);
  backdrop-filter: blur(28px);
  -webkit-backdrop-filter: blur(28px);
  padding: 22px;
  border-radius: 24px;
  border: 1px solid var(--border-color);
  box-shadow: var(--shadow-soft);
  margin-bottom: 18px;
  position: relative;
  overflow: hidden;
  transition: transform 0.25s var(--ease), box-shadow 0.25s var(--ease);
}
.card:hover {
  box-shadow: 0 14px 40px -5px rgba(255, 117, 140, 0.16), 0 0 0 1px rgba(255, 105, 180, 0.4) inset;
}
.card h2 {
  font-size: 13px;
  font-weight: 900;
  letter-spacing: 0.6px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--txt-0);
  border-bottom: 1px solid rgba(255, 183, 197, 0.25);
  padding-bottom: 10px;
}
.card-header-icon {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

/* NÚT BẤM DẠNG VIÊN THUỐC THREEUI CYBER PILL */
.btn-pill {
  padding: 11px 18px;
  border-radius: 99px;
  border: none;
  cursor: pointer;
  font-size: 11.5px;
  font-weight: 800;
  letter-spacing: 0.4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  transition: all 0.25s var(--ease);
  position: relative;
  overflow: hidden;
  text-decoration: none;
}
.btn-pill::after {
  content: '';
  position: absolute;
  top: -50%;
  left: -70%;
  width: 50%;
  height: 200%;
  background: linear-gradient(60deg, transparent, rgba(255,255,255,0.45), transparent);
  transform: rotate(25deg);
  transition: all 0.5s ease;
}
.btn-pill:hover::after { left: 140%; }
.btn-pill:hover {
  transform: translateY(-2px);
  filter: brightness(1.05);
}
.btn-pill:active { transform: translateY(0) scale(0.96); }

.btn-pill.primary {
  background: var(--grad-sakura);
  color: #fff;
  box-shadow: 0 5px 18px rgba(255, 117, 140, 0.4);
}
.btn-pill.dark {
  background: var(--grad-dark);
  color: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.25);
}
.btn-pill.light {
  background: #fff0f3;
  color: var(--sakura);
  border: 1px solid var(--border-color);
}
.btn-pill.danger {
  background: #fee2e2;
  color: #b91c1c;
  border: 1px solid rgba(239, 68, 68, 0.2);
}
.btn-pill.success {
  background: #d1fae5;
  color: #065f46;
  border: 1px solid rgba(16, 185, 129, 0.2);
}
.btn-pill.full {
  width: 100%;
  padding: 14px;
  font-size: 12.5px;
}

/* NÚT HÀNH ĐỘNG TRÒN LỚN BẮT ĐẦU / DỪNG */
.btn-round {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: none;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s var(--ease);
  margin: 6px;
  position: relative;
  outline: none;
}
.btn-round svg { width: 24px; height: 24px; }
.btn-round:hover { transform: scale(1.12); }
.btn-round:active { transform: scale(0.92); }
.btn-round.action-start {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: #fff;
  box-shadow: 0 6px 20px rgba(16, 185, 129, 0.4);
}
.btn-round.action-stop {
  background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%);
  color: #fff;
  box-shadow: 0 6px 20px rgba(239, 68, 68, 0.4);
}

/* KHU VỰC TÙY BIẾN VÀ QUẢN LÝ LOGO WEB */
.logo-manager-grid {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 18px;
  align-items: center;
  margin-bottom: 16px;
}
@media (max-width: 600px) {
  .logo-manager-grid { grid-template-columns: 1fr; justify-items: center; text-align: center; }
}
.logo-preview-box {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  position: relative;
  padding: 4px;
  background: linear-gradient(135deg, #ff758c, #00f0ff);
  box-shadow: 0 10px 30px rgba(255, 105, 180, 0.35);
  animation: logoGlow 4s ease-in-out infinite alternate;
}
@keyframes logoGlow {
  0% { filter: drop-shadow(0 0 10px rgba(255,105,180,0.4)); }
  100% { filter: drop-shadow(0 0 20px rgba(0,240,255,0.6)); }
}
.logo-preview-inner {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  overflow: hidden;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}
.logo-preview-inner img { width: 100%; height: 100%; object-fit: cover; }

/* KHU VỰC TẢI LÊN TẬP TIN DUNG LƯỢNG LỚN SIÊU NHANH */
.file-upload-wrapper {
  position: relative;
  width: 100%;
  height: 90px;
  border: 2px dashed var(--sakura);
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 183, 197, 0.12);
  transition: all 0.3s var(--ease);
  cursor: pointer;
  overflow: hidden;
}
.file-upload-wrapper:hover {
  background: rgba(255, 183, 197, 0.28);
  border-color: var(--sakura-deep);
  transform: translateY(-2px);
}
.file-upload-wrapper input[type="file"] {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
  width: 100%;
  height: 100%;
}
.file-upload-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 7px;
  pointer-events: none;
}
.file-upload-content svg { width: 32px; height: 32px; color: var(--sakura); }
.file-upload-content span { font-size: 12px; font-weight: 700; color: var(--txt-1); }

/* THANH TIẾN ĐỘ TẢI LÊN XHR THỜI GIAN THỰC */
.upload-progress-container {
  display: none;
  margin-top: 12px;
  background: rgba(255, 183, 197, 0.2);
  border-radius: 99px;
  height: 8px;
  overflow: hidden;
  position: relative;
}
.upload-progress-bar {
  height: 100%;
  width: 0%;
  background: var(--grad-sakura);
  border-radius: 99px;
  transition: width 0.15s linear;
}

/* CÁC PHẦN TỬ FORM */
.form-group { margin-bottom: 14px; }
.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 11px;
  font-weight: 800;
  color: var(--txt-2);
  letter-spacing: 0.3px;
}
.form-group input:not([type="file"]):not([type="checkbox"]),
.form-group textarea,
.form-group select {
  width: 100%;
  padding: 13px 16px;
  border: 1.5px solid var(--border-color);
  border-radius: 16px;
  font-size: 13px;
  background: #fff;
  color: var(--txt-0);
  transition: all 0.2s var(--ease);
}
.form-group input:focus, .form-group textarea:focus, .form-group select:focus {
  outline: none;
  border-color: var(--sakura);
  box-shadow: 0 0 15px rgba(255, 105, 180, 0.2);
}
.form-group textarea {
  min-height: 105px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  line-height: 1.5;
}

/* THANH CHỌN CHIP / THẺ TÙY CHỌN */
.chip-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 6px;
}
.chip-item {
  padding: 9px 15px;
  background: #fff;
  color: var(--txt-2);
  border-radius: 99px;
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
  border: 1px solid var(--border-color);
  transition: all 0.2s var(--ease);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.chip-item:hover {
  border-color: var(--sakura);
  color: var(--sakura);
  transform: translateY(-1px);
}
.chip-item.active {
  background: var(--grad-sakura);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 4px 12px rgba(255, 117, 140, 0.3);
}

/* LƯỚI BẬT TẮT CHỨC NĂNG (TOGGLES) */
.toggle-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 9px;
  margin-bottom: 14px;
}
.toggle-item {
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 16px;
  cursor: pointer;
  text-align: center;
  font-weight: 800;
  font-size: 11px;
  background: #fff;
  color: var(--txt-2);
  transition: all 0.2s var(--ease);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.toggle-item:hover { border-color: var(--sakura); }
.toggle-item.active {
  background: var(--grad-sakura);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 4px 14px rgba(255, 117, 140, 0.3);
}

/* BẢNG DỮ LIỆU HIỆN ĐẠI */
.table-wrap {
  overflow-x: auto;
  border-radius: 18px;
  border: 1px solid var(--border-color);
  background: #fff;
}
.table { width: 100%; border-collapse: collapse; }
.table th, .table td {
  padding: 12px 14px;
  text-align: left;
  font-size: 11.5px;
  border-bottom: 1px solid #fdf2f4;
  white-space: nowrap;
}
.table th {
  background: #fdf6f7;
  font-weight: 800;
  color: var(--txt-2);
  font-size: 10px;
  letter-spacing: 0.5px;
}

/* DANH SÁCH HỘI THOẠI VÀ THÀNH VIÊN */
.box-list {
  max-height: 290px;
  overflow-y: auto;
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 10px;
  background: #fff;
}
.box-item {
  padding: 11px 14px;
  border-radius: 14px;
  background: #fdfafb;
  margin-bottom: 7px;
  cursor: pointer;
  border: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  gap: 12px;
  transition: all 0.2s var(--ease);
}
.box-item:hover { border-color: var(--sakura); background: #fff; }
.box-item.selected {
  border-color: var(--sakura);
  background: #fff0f3;
  box-shadow: 0 2px 8px rgba(255, 105, 180, 0.15);
}
.box-item .check-mark {
  width: 20px;
  height: 20px;
  border: 1.5px solid var(--txt-2);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: transparent;
  font-weight: 900;
  flex-shrink: 0;
}
.box-item.selected .check-mark {
  background: var(--sakura);
  border-color: var(--sakura);
  color: #fff;
}
.box-item .b-title { font-weight: 800; font-size: 12.5px; color: var(--txt-0); }
.box-item .b-sub { font-size: 10px; color: var(--txt-2); font-family: 'JetBrains Mono', monospace; }

/* TRẠNG THÁI BADGE */
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 99px;
  font-size: 9.5px;
  font-weight: 800;
}
.status-badge.live { background: #d1fae5; color: #065f46; border: 1px solid rgba(16, 185, 129, 0.25); }
.status-badge.dead { background: #fee2e2; color: #b91c1c; border: 1px solid rgba(239, 68, 68, 0.25); }

/* KHUNG DOCK ĐIỀU HƯỚNG NỔI BO TRÒN PHONG CÁCH THREEUI */
.bottom-dock {
  position: fixed;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  width: calc(100% - 24px);
  max-width: 620px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(30px);
  -webkit-backdrop-filter: blur(30px);
  border: 1px solid rgba(255, 183, 197, 0.65);
  box-shadow: var(--shadow-dock);
  border-radius: 99px;
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  padding: 6px;
  gap: 4px;
  z-index: 999;
}
.bottom-dock .dock-btn {
  padding: 9px 2px;
  border-radius: 99px;
  cursor: pointer;
  font-size: 9.5px;
  font-weight: 800;
  text-align: center;
  color: var(--txt-2);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  background: transparent;
  border: none;
  transition: all 0.2s var(--ease);
}
.bottom-dock .dock-btn svg { width: 19px; height: 19px; transition: transform 0.2s; }
.bottom-dock .dock-btn:hover svg { transform: scale(1.18) translateY(-2px); }
.bottom-dock .dock-btn.active {
  background: var(--grad-sakura);
  color: #fff;
  box-shadow: 0 4px 14px rgba(255, 105, 180, 0.35);
  transform: translateY(-2px);
}

/* THÔNG BÁO TOAST THÔNG MINH */
#toast-stack {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 999999;
  max-width: 340px;
  width: calc(100% - 32px);
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  padding: 13px 18px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid var(--border-color);
  box-shadow: 0 14px 35px rgba(255, 117, 140, 0.18);
  display: flex;
  flex-direction: column;
  gap: 4px;
  animation: toastSlideIn 0.28s var(--ease) both;
  cursor: pointer;
}
.toast.swipe-up { animation: toastSwipeUp 0.22s ease-out forwards; }
@keyframes toastSlideIn { from { opacity: 0; transform: translateY(-20px); } to { opacity: 1; transform: translateY(0); } }
@keyframes toastSwipeUp { to { opacity: 0; transform: translateY(-40px); } }
.toast .t-head { font-size: 11.5px; font-weight: 900; color: var(--txt-0); display: flex; align-items: center; gap: 6px; }
.toast .t-body { font-size: 11px; font-weight: 600; color: var(--txt-2); }
"""

# ============================================================
# CÀNH HOA ANH ĐÀO NGHỆ THUẬT (CHI TIẾT CAO, NHIỀU LÁ, HOA NỞ)
# ============================================================
SVG_CHERRY_BRANCH = """
<svg class="cherry-blossom-tree-branch" viewBox="0 0 500 360" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <!-- GRADIENT GỖ VÀ CÀNH CÂY -->
    <linearGradient id="branchWoodGrad" x1="500" y1="0" x2="100" y2="280" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#3e2312"/>
      <stop offset="40%" stop-color="#603813"/>
      <stop offset="75%" stop-color="#8b4513"/>
      <stop offset="100%" stop-color="#a0522d"/>
    </linearGradient>
    <linearGradient id="twigGrad" x1="400" y1="20" x2="50" y2="220" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#543015"/>
      <stop offset="100%" stop-color="#7a421a"/>
    </linearGradient>

    <!-- GRADIENT CÁNH HOA ANH ĐÀO HỒNG PHẤN -->
    <radialGradient id="sakuraPetalGrad1" cx="30%" cy="30%" r="70%">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="45%" stop-color="#ffb7c5"/>
      <stop offset="85%" stop-color="#ff758c"/>
      <stop offset="100%" stop-color="#e11d48"/>
    </radialGradient>
    <radialGradient id="sakuraPetalGrad2" cx="30%" cy="30%" r="70%">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="50%" stop-color="#fbcfe8"/>
      <stop offset="90%" stop-color="#f472b6"/>
      <stop offset="100%" stop-color="#db2777"/>
    </radialGradient>

    <!-- GRADIENT LÁ ANH ĐÀO XANH NON TƯƠI SẮC -->
    <linearGradient id="leafGrad1" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#a7f3d0"/>
      <stop offset="40%" stop-color="#34d399"/>
      <stop offset="100%" stop-color="#059669"/>
    </linearGradient>
    <linearGradient id="leafGrad2" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#6ee7b7"/>
      <stop offset="60%" stop-color="#10b981"/>
      <stop offset="100%" stop-color="#047857"/>
    </linearGradient>

    <!-- TÂM HOA VÀ NHỤY VÀNG -->
    <radialGradient id="centerCupGrad" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#fff1f2"/>
      <stop offset="60%" stop-color="#fda4af"/>
      <stop offset="100%" stop-color="#e11d48"/>
    </radialGradient>
  </defs>

  <!-- THÂN CÀNH CHÍNH UỐN LƯỢN -->
  <path d="M500 0 C430 30 380 75 320 90 C260 105 200 80 150 115 C100 150 70 200 20 230 C12 236 4 240 0 242"
        stroke="url(#branchWoodGrad)" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M500 0 C430 30 380 75 320 90 C260 105 200 80 150 115"
        stroke="#27150a" stroke-width="3" stroke-linecap="round" opacity="0.4"/>

  <!-- CÁC NHÁNH PHỤ VƯƠN XA -->
  <path d="M410 40 C370 70 340 120 300 145 C270 165 240 180 200 195"
        stroke="url(#twigGrad)" stroke-width="7" stroke-linecap="round"/>
  <path d="M330 90 C300 125 280 180 230 215 C190 240 140 255 90 280"
        stroke="url(#twigGrad)" stroke-width="6" stroke-linecap="round"/>
  <path d="M220 100 C190 70 150 65 110 75 C80 82 50 105 25 125"
        stroke="url(#twigGrad)" stroke-width="5" stroke-linecap="round"/>
  <path d="M160 125 C130 155 105 175 75 220 C55 250 35 285 10 310"
        stroke="url(#twigGrad)" stroke-width="4.5" stroke-linecap="round"/>
  <path d="M290 150 C260 190 230 230 180 260 C150 280 120 305 80 325"
        stroke="url(#twigGrad)" stroke-width="4" stroke-linecap="round"/>
  <path d="M380 60 C360 25 330 10 290 15 C260 18 240 40 220 55"
        stroke="url(#twigGrad)" stroke-width="4" stroke-linecap="round"/>

  <!-- HỆ THỐNG LÁ ANH ĐÀO TƯƠI TỐT XANH MƯỚT (NHIỀU LÁ VÀ GÂN LÁ) -->
  <!-- Chùm lá 1 (Gốc cành) -->
  <g transform="translate(420, 25) rotate(-35)">
    <path d="M0 0 C-15 -35 15 -55 0 -80 C-15 -55 15 -35 0 0" fill="url(#leafGrad1)"/>
    <path d="M0 0 L0 -75" stroke="#047857" stroke-width="1.2" opacity="0.6"/>
  </g>
  <g transform="translate(390, 45) rotate(25)">
    <path d="M0 0 C-12 -28 12 -45 0 -65 C-12 -45 12 -28 0 0" fill="url(#leafGrad2)"/>
    <path d="M0 0 L0 -60" stroke="#047857" stroke-width="1" opacity="0.6"/>
  </g>

  <!-- Chùm lá 2 (Giữa cành) -->
  <g transform="translate(325, 85) rotate(-65)">
    <path d="M0 0 C-14 -32 14 -50 0 -72 C-14 -50 14 -32 0 0" fill="url(#leafGrad1)"/>
    <path d="M0 0 L0 -68" stroke="#047857" stroke-width="1.2" opacity="0.6"/>
  </g>
  <g transform="translate(310, 115) rotate(40)">
    <path d="M0 0 C-12 -26 12 -42 0 -60 C-12 -42 12 -26 0 0" fill="url(#leafGrad2)"/>
    <path d="M0 0 L0 -56" stroke="#047857" stroke-width="1" opacity="0.6"/>
  </g>
  <g transform="translate(265, 100) rotate(-15)">
    <path d="M0 0 C-13 -30 13 -48 0 -70 C-13 -48 13 -30 0 0" fill="url(#leafGrad1)"/>
    <path d="M0 0 L0 -65" stroke="#047857" stroke-width="1.1" opacity="0.6"/>
  </g>

  <!-- Chùm lá 3 (Nhánh vươn trái) -->
  <g transform="translate(180, 80) rotate(-80)">
    <path d="M0 0 C-15 -32 15 -52 0 -75 C-15 -52 15 -32 0 0" fill="url(#leafGrad2)"/>
    <path d="M0 0 L0 -70" stroke="#047857" stroke-width="1.2" opacity="0.6"/>
  </g>
  <g transform="translate(140, 70) rotate(-45)">
    <path d="M0 0 C-12 -26 12 -42 0 -62 C-12 -42 12 -26 0 0" fill="url(#leafGrad1)"/>
  </g>
  <g transform="translate(90, 85) rotate(-30)">
    <path d="M0 0 C-11 -24 11 -38 0 -55 C-11 -38 11 -24 0 0" fill="url(#leafGrad2)"/>
  </g>

  <!-- Chùm lá 4 (Nhánh rủ xuống) -->
  <g transform="translate(240, 175) rotate(70)">
    <path d="M0 0 C-14 -30 14 -48 0 -68 C-14 -48 14 -30 0 0" fill="url(#leafGrad1)"/>
  </g>
  <g transform="translate(190, 205) rotate(85)">
    <path d="M0 0 C-13 -28 13 -45 0 -65 C-13 -45 13 -28 0 0" fill="url(#leafGrad2)"/>
  </g>
  <g transform="translate(150, 245) rotate(60)">
    <path d="M0 0 C-12 -25 12 -40 0 -58 C-12 -40 12 -25 0 0" fill="url(#leafGrad1)"/>
  </g>
  <g transform="translate(100, 270) rotate(75)">
    <path d="M0 0 C-13 -28 13 -44 0 -64 C-13 -44 13 -28 0 0" fill="url(#leafGrad2)"/>
  </g>
  <g transform="translate(45, 235) rotate(-20)">
    <path d="M0 0 C-12 -25 12 -40 0 -58 C-12 -40 12 -25 0 0" fill="url(#leafGrad1)"/>
  </g>
  <g transform="translate(25, 300) rotate(45)">
    <path d="M0 0 C-10 -22 10 -35 0 -50 C-10 -35 10 -22 0 0" fill="url(#leafGrad2)"/>
  </g>

  <!-- HỆ THỐNG HOA ANH ĐÀO NỞ RỰC RỠ (NHIỀU HOA & NHỤY VÀNG) -->
  <!-- Macro tạo hoa 5 cánh -->
  <!-- Hoa 1 (Trung tâm nhánh lớn) -->
  <g transform="translate(340, 85)">
    <circle cx="0" cy="-14" r="13" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="13" cy="-4" r="13" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="8" cy="12" r="13" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="-8" cy="12" r="13" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="-13" cy="-4" r="13" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="0" cy="0" r="8" fill="url(#centerCupGrad)"/>
    <circle cx="0" cy="0" r="3.5" fill="#f59e0b"/>
  </g>

  <!-- Hoa 2 -->
  <g transform="translate(390, 50)">
    <circle cx="0" cy="-12" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="11" cy="-3" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="7" cy="10" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="-7" cy="10" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="-11" cy="-3" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="0" cy="0" r="6.5" fill="url(#centerCupGrad)"/>
    <circle cx="0" cy="0" r="3" fill="#fbbf24"/>
  </g>

  <!-- Hoa 3 -->
  <g transform="translate(290, 110)">
    <circle cx="0" cy="-15" r="14" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="14" cy="-4" r="14" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="9" cy="13" r="14" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="-9" cy="13" r="14" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="-14" cy="-4" r="14" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="0" cy="0" r="8.5" fill="url(#centerCupGrad)"/>
    <circle cx="0" cy="0" r="3.5" fill="#f59e0b"/>
  </g>

  <!-- Hoa 4 -->
  <g transform="translate(230, 90)">
    <circle cx="0" cy="-13" r="12" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="12" cy="-4" r="12" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="8" cy="11" r="12" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="-8" cy="11" r="12" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="-12" cy="-4" r="12" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="0" cy="0" r="7" fill="url(#centerCupGrad)"/>
    <circle cx="0" cy="0" r="3" fill="#f59e0b"/>
  </g>

  <!-- Hoa 5 -->
  <g transform="translate(170, 115)">
    <circle cx="0" cy="-14" r="13" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="13" cy="-4" r="13" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="8" cy="12" r="13" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="-8" cy="12" r="13" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="-13" cy="-4" r="13" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="0" cy="0" r="8" fill="url(#centerCupGrad)"/>
    <circle cx="0" cy="0" r="3.5" fill="#f59e0b"/>
  </g>

  <!-- Hoa 6 -->
  <g transform="translate(265, 170)">
    <circle cx="0" cy="-12" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="11" cy="-3" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="7" cy="10" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="-7" cy="10" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="-11" cy="-3" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="0" cy="0" r="6.5" fill="url(#centerCupGrad)"/>
    <circle cx="0" cy="0" r="3" fill="#f59e0b"/>
  </g>

  <!-- Hoa 7 -->
  <g transform="translate(205, 195)">
    <circle cx="0" cy="-13" r="12" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="12" cy="-4" r="12" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="8" cy="11" r="12" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="-8" cy="11" r="12" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="-12" cy="-4" r="12" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="0" cy="0" r="7" fill="url(#centerCupGrad)"/>
    <circle cx="0" cy="0" r="3" fill="#f59e0b"/>
  </g>

  <!-- Hoa 8 -->
  <g transform="translate(130, 205)">
    <circle cx="0" cy="-12" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="11" cy="-3" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="7" cy="10" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="-7" cy="10" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="-11" cy="-3" r="11" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="0" cy="0" r="6" fill="url(#centerCupGrad)"/>
    <circle cx="0" cy="0" r="2.8" fill="#f59e0b"/>
  </g>

  <!-- Hoa 9 -->
  <g transform="translate(75, 235)">
    <circle cx="0" cy="-13" r="12" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="12" cy="-4" r="12" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="8" cy="11" r="12" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="-8" cy="11" r="12" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="-12" cy="-4" r="12" fill="url(#sakuraPetalGrad1)"/>
    <circle cx="0" cy="0" r="7" fill="url(#centerCupGrad)"/>
    <circle cx="0" cy="0" r="3" fill="#f59e0b"/>
  </g>

  <!-- Hoa 10 (Đầu cành mảnh) -->
  <g transform="translate(30, 220)">
    <circle cx="0" cy="-10" r="9" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="9" cy="-3" r="9" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="6" cy="8" r="9" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="-6" cy="8" r="9" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="-9" cy="-3" r="9" fill="url(#sakuraPetalGrad2)"/>
    <circle cx="0" cy="0" r="5" fill="url(#centerCupGrad)"/>
    <circle cx="0" cy="0" r="2.5" fill="#f59e0b"/>
  </g>

  <!-- Nụ hoa chớm nở ở các đầu nhánh -->
  <circle cx="440" cy="20" r="6" fill="#f472b6"/>
  <circle cx="440" cy="20" r="3" fill="#e11d48"/>
  <circle cx="360" cy="15" r="5.5" fill="#f472b6"/>
  <circle cx="210" cy="45" r="5.5" fill="#f472b6"/>
  <circle cx="25" cy="120" r="5" fill="#f472b6"/>
  <circle cx="10" cy="305" r="5" fill="#f472b6"/>
  <circle cx="70" cy="320" r="5.5" fill="#f472b6"/>
</svg>
"""

# ============================================================
# CỔNG BẢO MẬT & TRANG ĐĂNG NHẬP THREEUI
# ============================================================
HTML_GATE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Hệ Thống An Toàn — ALB Forge</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_SAKURA_THREEUI + """
body {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 20px;
}
.gate-card {
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(35px);
  -webkit-backdrop-filter: blur(35px);
  border: 1px solid var(--border-color);
  border-radius: 28px;
  padding: 44px 32px;
  max-width: 420px;
  width: 100%;
  text-align: center;
  box-shadow: 0 25px 65px rgba(255, 117, 140, 0.2);
  position: relative;
  overflow: hidden;
  z-index: 10;
}
.radar-scanner {
  width: 105px;
  height: 105px;
  margin: 0 auto 24px;
  border-radius: 50%;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(circle, rgba(255,105,180,0.18) 0%, transparent 70%);
  border: 2px dashed rgba(255,105,180,0.55);
}
.radar-scanner::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2.5px solid transparent;
  border-top-color: var(--sakura);
  border-right-color: #00f0ff;
  animation: spin 1.2s linear infinite;
}
@keyframes spin { 100% { transform: rotate(360deg); } }
.radar-icon { font-size: 42px; animation: pulse 1.6s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.15); } }
.progress-line {
  height: 6px;
  width: 100%;
  background: #fdf2f4;
  border-radius: 99px;
  overflow: hidden;
  margin: 22px 0;
  display: none;
}
.progress-fill {
  height: 100%;
  width: 0%;
  background: var(--grad-sakura);
  border-radius: 99px;
  transition: width 0.35s ease;
  box-shadow: 0 0 10px rgba(255, 105, 180, 0.5);
}
</style>
</head>
<body>
<canvas id="sakura-canvas"></canvas>
""" + SVG_CHERRY_BRANCH + """

<div class="gate-card">
  <div class="radar-scanner"><div class="radar-icon">🌸</div></div>
  <h1 style="font-family:'Orbitron',sans-serif; font-size:18px; margin-bottom:8px; color:var(--txt-0);">KIỂM TRA AN TOÀN HỆ THỐNG</h1>
  <p id="scan-status" style="font-size:12px; color:var(--txt-2); min-height:36px; line-height:1.5;">Vui lòng xác thực danh tính để vào trung tâm điều khiển.</p>
  <div class="progress-line" id="p-box"><div class="progress-fill" id="p-bar"></div></div>
  <button class="btn-pill primary full" id="start-btn" onclick="startVerification()" style="font-size:13px; padding:15px; margin-top:8px;">🌸 Bắt Đầu Xác Thực</button>
</div>

<script>
var pBox = document.getElementById('p-box');
var pBar = document.getElementById('p-bar');
var statusTxt = document.getElementById('scan-status');
var startBtn = document.getElementById('start-btn');
var steps = [
  { p: 25, txt: 'Đang kiểm tra chứng chỉ bảo mật mạng...' },
  { p: 55, txt: 'Đang khởi tạo thuật toán mã hóa AES-CBC...' },
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
    setTimeout(runStep, 450);
  } else {
    finishScan();
  }
}
async function finishScan(){
  var r = await fetch('/api/verify_human', { method: 'POST' }).then(x => x.json());
  if(r.ok) window.location.href = '/login';
}

// CANVAS RƠI CÁNH HOA VÀ LÁ
var sCanvas = document.getElementById('sakura-canvas');
var sCtx = sCanvas.getContext('2d');
var sW = window.innerWidth, sH = window.innerHeight;
sCanvas.width = sW; sCanvas.height = sH;
var particles = Array.from({ length: 40 }, () => ({
  x: Math.random() * sW,
  y: Math.random() * sH - sH,
  size: Math.random() * 8 + 6,
  speedY: Math.random() * 1.4 + 0.8,
  speedX: Math.random() * 2 - 0.8,
  angle: Math.random() * 360,
  angVel: (Math.random() - 0.5) * 1.8,
  isLeaf: Math.random() < 0.28
}));
function renderParticles() {
  sCtx.clearRect(0, 0, sW, sH);
  particles.forEach(p => {
    sCtx.save();
    sCtx.translate(p.x, p.y);
    sCtx.rotate(p.angle * Math.PI / 180);
    if(p.isLeaf){
      sCtx.fillStyle = 'rgba(52, 211, 153, 0.75)';
      sCtx.beginPath();
      sCtx.ellipse(0, 0, p.size * 0.5, p.size, 0, 0, Math.PI * 2);
      sCtx.fill();
    } else {
      sCtx.fillStyle = 'rgba(255, 183, 197, 0.8)';
      sCtx.beginPath();
      sCtx.moveTo(0, 0);
      sCtx.bezierCurveTo(p.size / 2, -p.size / 2, p.size, 0, 0, p.size);
      sCtx.bezierCurveTo(-p.size, 0, -p.size / 2, -p.size / 2, 0, 0);
      sCtx.fill();
    }
    sCtx.restore();
    p.y += p.speedY; p.x += p.speedX; p.angle += p.angVel;
    if (p.y > sH + 20) { p.y = -20; p.x = Math.random() * sW; }
    if (p.x > sW + 20) p.x = -20; if (p.x < -20) p.x = sW + 20;
  });
  requestAnimationFrame(renderParticles);
}
renderParticles();
</script>
</body>
</html>
"""

HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Đăng Nhập Quản Trị — ALB Forge</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_SAKURA_THREEUI + """
body {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 20px;
}
.login-card {
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(35px);
  -webkit-backdrop-filter: blur(35px);
  border: 1px solid var(--border-color);
  border-radius: 28px;
  padding: 44px 32px;
  max-width: 420px;
  width: 100%;
  text-align: center;
  box-shadow: 0 25px 65px rgba(255, 117, 140, 0.2);
  position: relative;
  z-index: 10;
}
.login-logo {
  width: 90px;
  height: 90px;
  border-radius: 50%;
  overflow: hidden;
  margin: 0 auto 18px;
  border: 3px solid var(--sakura);
  box-shadow: 0 8px 25px rgba(255, 105, 180, 0.4);
  background: #fff;
}
.login-logo img { width: 100%; height: 100%; object-fit: cover; }
.err-msg {
  background: #fee2e2;
  color: #b91c1c;
  padding: 12px 14px;
  border-radius: 14px;
  font-size: 12px;
  font-weight: 800;
  margin-bottom: 18px;
  text-align: left;
  border: 1px solid rgba(239, 68, 68, 0.25);
}
</style>
</head>
<body>
<canvas id="sakura-canvas"></canvas>
""" + SVG_CHERRY_BRANCH + """

<div class="login-card">
  <div class="login-logo">
    <img src="{{ logo_url }}" onerror="this.src='/static/logo.png'">
  </div>
  <h1 style="font-family:'Orbitron',sans-serif; font-size:20px; margin-bottom:6px; color:var(--txt-0);">{{ web_title }}</h1>
  <p style="font-size:11px; color:var(--txt-2); font-weight:800; margin-bottom:24px; display:flex; align-items:center; justify-content:center; gap:5px;">
    Bản quyền thiết kế: <span class="v-badge"><svg viewBox="0 0 24 24" width="15" height="15" fill="#0084ff"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></span> {{ designer_name }}
  </p>

  {% if error %}<div class="err-msg">⚠️ {{ error }}</div>{% endif %}

  <form method="POST">
    <div class="form-group" style="text-align:left;">
      <label>Mã bảo mật hệ thống</label>
      <input type="password" name="password" placeholder="Nhập mã bảo mật truy cập..." required autofocus>
    </div>
    <button type="submit" class="btn-pill primary full" style="font-size:13.5px; padding:15px;">💖 Mở Khóa Hệ Thống</button>
  </form>
</div>

<script>
var sCanvas = document.getElementById('sakura-canvas');
var sCtx = sCanvas.getContext('2d');
var sW = window.innerWidth, sH = window.innerHeight;
sCanvas.width = sW; sCanvas.height = sH;
var particles = Array.from({ length: 45 }, () => ({
  x: Math.random() * sW,
  y: Math.random() * sH - sH,
  size: Math.random() * 8 + 6,
  speedY: Math.random() * 1.4 + 0.8,
  speedX: Math.random() * 2 - 0.8,
  angle: Math.random() * 360,
  angVel: (Math.random() - 0.5) * 1.8,
  isLeaf: Math.random() < 0.28
}));
function renderParticles() {
  sCtx.clearRect(0, 0, sW, sH);
  particles.forEach(p => {
    sCtx.save();
    sCtx.translate(p.x, p.y);
    sCtx.rotate(p.angle * Math.PI / 180);
    if(p.isLeaf){
      sCtx.fillStyle = 'rgba(52, 211, 153, 0.75)';
      sCtx.beginPath();
      sCtx.ellipse(0, 0, p.size * 0.5, p.size, 0, 0, Math.PI * 2);
      sCtx.fill();
    } else {
      sCtx.fillStyle = 'rgba(255, 183, 197, 0.8)';
      sCtx.beginPath();
      sCtx.moveTo(0, 0);
      sCtx.bezierCurveTo(p.size / 2, -p.size / 2, p.size, 0, 0, p.size);
      sCtx.bezierCurveTo(-p.size, 0, -p.size / 2, -p.size / 2, 0, 0);
      sCtx.fill();
    }
    sCtx.restore();
    p.y += p.speedY; p.x += p.speedX; p.angle += p.angVel;
    if (p.y > sH + 20) { p.y = -20; p.x = Math.random() * sW; }
    if (p.x > sW + 20) p.x = -20; if (p.x < -20) p.x = sW + 20;
  });
  requestAnimationFrame(renderParticles);
}
renderParticles();
</script>
</body>
</html>
"""

# ============================================================
# GIAO DIỆN BẢNG ĐIỀU KHIỂN CHÍNH THREEUI SAKURA
# ============================================================
HTML_INDEX = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>{{ web_title }}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<link rel="icon" type="image/png" id="page-favicon" href="{{ logo_url }}">
<style>
""" + CSS_SAKURA_THREEUI + """
</style>
</head>
<body>

<!-- MÀN HÌNH TẢI TRANG THREEUI (PRELOADER) -->
<div id="threeui-preloader">
  <div class="preloader-emblem">
    <div class="preloader-ring-outer"></div>
    <div class="preloader-ring-inner"></div>
    <div class="preloader-logo">
      <img id="preloader-logo-img" src="{{ logo_url }}" onerror="this.src='/static/logo.png'">
    </div>
  </div>
  <div class="preloader-title">{{ web_title }}</div>
  <div class="preloader-sub" id="preloader-status-text">Đang nạp lõi điều khiển ThreeUI...</div>
  <div class="preloader-bar-wrap">
    <div class="preloader-bar-fill" id="preloader-bar"></div>
  </div>
  <div class="preloader-pct" id="preloader-pct">0%</div>
</div>

<!-- CANVAS CÁNH HOA & LÁ ANH ĐÀO RƠI 60FPS -->
<canvas id="sakura-canvas"></canvas>

<!-- CÀNH HOA ANH ĐÀO NGHỆ THUẬT VƯƠN DÀI TỰ NHIÊN -->
""" + SVG_CHERRY_BRANCH + """

<!-- THANH TIÊU ĐỀ HEADER THREEUI CAO CẤP -->
<div class="header">
  <div class="header-inner">
    <div class="logo-box" onclick="switchTab('theme')" title="Nhấn để mở bộ quản lý Logo & Giao diện">
      <img id="header-logo" src="{{ logo_url }}" onerror="this.src='/static/logo.png'">
    </div>
    <div class="header-meta">
      <h1 id="header-web-title">{{ web_title }}</h1>
      <p>
        Bản quyền: <span class="v-badge"><svg viewBox="0 0 24 24" width="14" height="14" fill="#0084ff"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></span>
        <b id="header-designer">{{ designer_name }}</b>
        <span class="status-pill-radar" id="radar-live-pill"><span class="radar-dot"></span> SẴN SÀNG</span>
        <span style="font-family:'JetBrains Mono',monospace; font-size:10px; color:var(--txt-muted); margin-left:6px;" id="live-clock">--:--:--</span>
      </p>
    </div>
    <div style="display:flex; gap:8px;">
      <button class="btn-pill light" onclick="switchTab('theme')" style="padding:8px 14px; font-size:10.5px;">⚙️ Giao diện</button>
      <button class="btn-pill dark" onclick="location.href='/logout'" style="padding:8px 14px; font-size:10.5px;">Đăng xuất</button>
    </div>
  </div>
</div>

<div id="toast-stack"></div>

<div class="container">

  <!-- ========================================== -->
  <!-- TAB 1: TÀI KHOẢN ĐIỀU KHIỂN (ACCOUNTS) -->
  <!-- ========================================== -->
  <div class="panel active" id="panel-accounts">
    <div class="card">
      <h2>
        <span class="card-header-icon">🌸 Thêm Tài Khoản Zalo Điều Khiển</span>
        <button class="btn-pill dark" onclick="checkAllAccounts()">Kiểm Tra Tất Cả Acc</button>
      </h2>
      <div class="form-group">
        <label>Tên gợi nhớ tài khoản</label>
        <input id="add-label" placeholder="Ví dụ: Acc_Chinh_01, Bot_Spam_02...">
      </div>
      <div class="form-group">
        <label>IMEI thiết bị (Lấy từ Zalo PC hoặc Web Extension)</label>
        <input id="add-imei" placeholder="Nhập IMEI 15-16 chữ số...">
      </div>
      <div class="form-group">
        <label>Cookie JSON (Bao gồm zpw_sek, zpw_ver, zpw_type...)</label>
        <textarea id="add-cookies" placeholder='{"zpw_sek":"...","zpw_ver":"645","zpw_type":"30"}'></textarea>
      </div>
      <button class="btn-pill primary full" onclick="addAccount()">💖 Xác Thực & Lưu Tài Khoản</button>
    </div>

    <div class="card">
      <h2>
        <span class="card-header-icon">📋 Danh Sách Tài Khoản Đang Quản Lý</span>
        <span style="font-size:11px; font-weight:700; color:var(--txt-2);" id="accounts-count-badge">Tổng: 0 tài khoản</span>
      </h2>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Gợi nhớ</th>
              <th>Tên thật Zalo</th>
              <th>UID</th>
              <th>Trạng thái</th>
              <th>Thao tác</th>
            </tr>
          </thead>
          <tbody id="accounts-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ========================================== -->
  <!-- TAB 2: QUẢN LÝ HỘI THOẠI (BOXES) -->
  <!-- ========================================== -->
  <div class="panel" id="panel-boxes">
    <div class="card">
      <h2>
        <span class="card-header-icon">💬 Quản Lý Hội Thoại Nhận Tin Nhắn</span>
      </h2>
      <div class="form-group">
        <label>Chọn tài khoản để quét danh sách nhóm & bạn bè</label>
        <select id="load-acc-select"><option value="">-- Chọn tài khoản --</option></select>
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:14px;">
        <button class="btn-pill dark" onclick="loadBoxes()">🔍 Nạp Hội Thoại</button>
        <button class="btn-pill light" onclick="selectAllBoxes()">✓ Chọn Tất Cả</button>
        <button class="btn-pill danger" onclick="clearAllBoxes()">✕ Bỏ Chọn Tất Cả</button>
      </div>
      <div>
        <div style="font-size:11px; font-weight:800; color:var(--txt-2); margin-bottom:8px; display:flex; justify-content:space-between;">
          <span>ĐÃ CHỌN: <b id="selected-count" style="color:var(--sakura); font-size:13px;">0</b> HỘI THOẠI</span>
          <span style="color:var(--txt-muted);" id="boxes-total-count">Tổng có: 0 mục</span>
        </div>
        <div class="box-list" id="box-list">
          <div style="text-align:center; padding:24px; color:var(--txt-2); font-size:12px;">Vui lòng chọn tài khoản và bấm "Nạp Hội Thoại"</div>
        </div>
      </div>
    </div>
  </div>

  <!-- ========================================== -->
  <!-- TAB 3: TẬP TIN VĂN BẢN SIÊU TỐC (FILES) -->
  <!-- ========================================== -->
  <div class="panel" id="panel-files">
    <div class="card">
      <h2>
        <span class="card-header-icon">⚡ Tải Lên Tập Tin Văn Bản (Tối Ưu Siêu Nhanh)</span>
      </h2>
      <p style="font-size:11.5px; color:var(--txt-2); margin-bottom:14px; line-height:1.5;">
        Hệ thống được nâng cấp thuật toán đọc <b>Stream O(1) Memory</b>. Hỗ trợ tệp tin văn bản từ vài KB đến <b>hàng trăm MB</b> mà không gây đơ lag máy chủ hay trình duyệt!
      </p>

      <div class="file-upload-wrapper" onclick="document.getElementById('file-input').click()">
        <div class="file-upload-content">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
          <span id="upload-txt">Kéo thả hoặc Nhấn để chọn tệp Văn bản (.txt, .log)</span>
        </div>
        <input type="file" id="file-input" accept=".txt,.log" onchange="handleFileSelect(this)">
      </div>

      <!-- THANH TIẾN ĐỘ TẢI LÊN XHR -->
      <div class="upload-progress-container" id="upload-progress-wrap">
        <div class="upload-progress-bar" id="upload-progress-bar"></div>
      </div>
      <div id="upload-progress-text" style="display:none; font-size:10.5px; font-weight:800; color:var(--sakura); margin-top:6px; text-align:right;">0%</div>

      <div style="margin-top:14px;">
        <button class="btn-pill primary full" onclick="uploadTextFileStream()">🚀 Tải Lên & Xử Lý Tệp Tin</button>
      </div>
    </div>

    <div class="card">
      <h2>
        <span class="card-header-icon">📄 Danh Sách Tập Tin Đã Lưu Trữ</span>
      </h2>
      <div id="files-list">
        <div style="text-align:center; padding:20px; color:var(--txt-2); font-size:12px;">Chưa có tập tin nào trên máy chủ</div>
      </div>
    </div>
  </div>

  <!-- ========================================== -->
  <!-- TAB 4: ĐỘNG CƠ GỬI TIN TỰ ĐỘNG (SPAM ENGINE) -->
  <!-- ========================================== -->
  <div class="panel" id="panel-spam">
    <div class="card">
      <h2>
        <span class="card-header-icon">🔥 Thiết Lập Động Cơ Gửi Tin Tự Động</span>
      </h2>

      <!-- 1. Chế độ gửi -->
      <div class="form-group">
        <label>1. Chế độ gửi tin nhắn</label>
        <div class="chip-bar" id="mode-selector">
          <div class="chip-item active" data-mode="fast">⚡ Siêu Nhanh (Fast)</div>
          <div class="chip-item" data-mode="treo_ngon">📜 Treo Ngôn (Khối Dòng / 1 Tin)</div>
          <div class="chip-item" data-mode="treo_nhay">🎯 Treo Nhây (Từng Dòng Riêng Lẻ)</div>
        </div>
        <input type="hidden" id="spam-mode" value="fast">
      </div>

      <!-- 2. Chọn tập tin -->
      <div class="form-group">
        <label>2. Sử dụng nội dung từ tập tin đã lưu</label>
        <select id="spam-file-select" onchange="handleSpamFileChange()">
          <option value="">-- Hoặc nhập trực tiếp bên dưới --</option>
        </select>
        <div id="file-info-badge" style="font-size:10px; font-weight:700; color:var(--sakura); margin-top:4px; display:none;"></div>
      </div>

      <!-- 3. Nhập trực tiếp văn bản -->
      <div class="form-group">
        <label>3. Nội dung văn bản gửi (Nếu không chọn tệp tin)</label>
        <textarea id="spam-messages" placeholder="Dán văn bản nhiều dòng vào đây... Nếu chọn Treo Ngôn, toàn bộ văn bản sẽ được gửi trong 1 tin duy nhất. Nếu chọn Treo Nhây, mỗi dòng sẽ được gửi riêng biệt."></textarea>
      </div>

      <!-- 4. Kích thước & Định dạng chữ (Khắc phục lỗi in đậm to ra) -->
      <div class="form-group">
        <label>4. Cỡ chữ & Định dạng nổi bật (Khắc phục chữ nhỏ, không in đậm)</label>
        <div class="chip-bar" id="font-size-bar">
          <div class="chip-item" data-fsize="normal">Chuẩn (Thường)</div>
          <div class="chip-item" data-fsize="bold">In Đậm (**Bold**)</div>
          <div class="chip-item active" data-fsize="heading">Tiêu Đề Lớn (# H1)</div>
          <div class="chip-item" data-fsize="giant">Khổng Lồ (# **H1 Bold**)</div>
        </div>
        <input type="hidden" id="font-size-mode" value="heading">
      </div>

      <!-- 5. Màu sắc chữ (Khắc phục lỗi không đổi màu) -->
      <div class="form-group">
        <label>5. Màu sắc chữ Zalo (Khắc phục lỗi không đổi màu gửi)</label>
        <div class="chip-bar" id="color-mode-bar">
          <div class="chip-item active" data-cmode="rainbow">🌈 Trộn Màu Từng Dòng (Rainbow)</div>
          <div class="chip-item" data-cmode="random">🎲 Đổi Màu Ngẫu Nhiên (Random)</div>
          <div class="chip-item" data-cmode="fixed">🎨 Cố Định Một Màu (Fixed)</div>
          <div class="chip-item" data-cmode="none">⚪ Tắt Màu Sắc</div>
        </div>
        <input type="hidden" id="color-mode" value="rainbow">
        <div id="fixed-colors-wrap" style="display:none; margin-top:10px;" class="chip-bar"></div>
      </div>

      <!-- 6. Khoảng cách thời gian -->
      <div class="form-group">
        <label>6. Khoảng cách thời gian gửi giữa các tin (Delay)</label>
        <div class="chip-bar" id="delay-bar">
          <div class="chip-item" data-delay="0.3">0.3 giây</div>
          <div class="chip-item" data-delay="0.5">0.5 giây</div>
          <div class="chip-item active" data-delay="1">1.0 giây</div>
          <div class="chip-item" data-delay="2">2.0 giây</div>
          <div class="chip-item" data-delay="3">3.0 giây</div>
          <div class="chip-item" data-delay="5">5.0 giây</div>
        </div>
        <input type="hidden" id="spam-delay" value="1">
      </div>

      <!-- 7. Biểu tượng cảm xúc -->
      <div class="form-group">
        <label>7. Biểu tượng Icon kèm theo mỗi tin nhắn</label>
        <div class="chip-bar" id="icon-bar">
          <div class="chip-item" data-icon="0">Tắt (0)</div>
          <div class="chip-item" data-icon="2">2 Icon</div>
          <div class="chip-item active" data-icon="3">3 Icon</div>
          <div class="chip-item" data-icon="5">5 Icon</div>
          <div class="chip-item" data-icon="8">8 Icon Cực Mạnh</div>
        </div>
        <input type="hidden" id="icon-count" value="3">
      </div>

      <!-- 8. Các công tắc chức năng đặc biệt -->
      <div class="toggle-grid">
        <div class="toggle-item active" id="tg-all" onclick="tgFlag('all')">
          📢 Nhắc Cả Nhóm (@All)
        </div>
        <div class="toggle-item active" id="tg-multi" onclick="tgFlag('multi')">
          👥 Chạy Tất Cả Acc Song Song
        </div>
        <div class="toggle-item active" id="tg-emoji" onclick="tgFlag('emoji')">
          ✨ Bật Biểu Tượng Cảm Xúc
        </div>
        <div class="toggle-item" id="tg-tag-toggle" onclick="tgTagSection()">
          👤 Tag Từng Thành Viên Cụ Thể
        </div>
      </div>

      <!-- Khu vực chọn thành viên tag theo tên thật -->
      <div id="tag-section-wrap" style="display:none; margin-top:14px; padding:16px; background:#fff; border-radius:18px; border:1px solid var(--border-color);">
        <label style="font-size:11px; font-weight:800; color:var(--txt-2); margin-bottom:8px; display:block;">
          Chọn tài khoản để quét danh sách thành viên tên thật trong nhóm:
        </label>
        <div class="form-group">
          <select id="member-acc-select"><option value="">-- Chọn tài khoản quét --</option></select>
        </div>
        <button class="btn-pill dark" onclick="loadMembers()">👥 Quét Thành Viên Tên Thật</button>
        <div class="box-list" id="tag-selector" style="margin-top:10px; max-height:220px; display:none;"></div>
      </div>
    </div>

    <!-- NÚT BẮT ĐẦU VÀ DỪNG -->
    <div style="text-align:center; margin: 20px 0 24px;">
      <button class="btn-round action-start" onclick="startSpam()" title="Khởi Chạy Gửi Tin"><svg viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3"/></svg></button>
      <button class="btn-round action-stop" onclick="stopAll()" title="Dừng Toàn Bộ Tiến Trình"><svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg></button>
      <div style="font-size:11px; font-weight:800; color:var(--txt-2); margin-top:8px;">BẤM NÚT XANH ĐỂ CHẠY • NÚT ĐỎ ĐỂ DỪNG</div>
    </div>

    <!-- TIẾN TRÌNH ĐANG CHẠY -->
    <div class="card">
      <h2>
        <span class="card-header-icon">📊 Tiến Trình Đang Chạy Trong Hệ Thống</span>
      </h2>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Mã tiến trình</th>
              <th>Chế độ</th>
              <th>Trạng thái</th>
              <th>Đã gửi</th>
              <th>Thao tác</th>
            </tr>
          </thead>
          <tbody id="tasks-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ========================================== -->
  <!-- TAB 5: BỘ QUẢN LÝ LOGO & GIAO DIỆN WEB (THEME) -->
  <!-- ========================================== -->
  <div class="panel" id="panel-theme">
    <div class="card">
      <h2>
        <span class="card-header-icon">🌸 Tùy Biến Ảnh Logo & Thương Hiệu Web</span>
      </h2>
      <p style="font-size:11.5px; color:var(--txt-2); margin-bottom:18px;">
        Thêm hoặc thay đổi ảnh Logo trang web theo sở thích cá nhân. Logo mới sẽ được áp dụng ngay lập tức trên thanh tiêu đề, trang đăng nhập và biểu tượng trình duyệt!
      </p>

      <div class="logo-manager-grid">
        <div class="logo-preview-box">
          <div class="logo-preview-inner">
            <img id="theme-logo-preview" src="{{ logo_url }}" onerror="this.src='/static/logo.png'">
          </div>
        </div>
        <div>
          <div style="font-size:13px; font-weight:900; color:var(--txt-0); margin-bottom:6px;">Logo Hiện Tại Của Trang Web</div>
          <p style="font-size:11px; color:var(--txt-2); margin-bottom:12px;">Định dạng hỗ trợ: PNG, JPG, JPEG, SVG, WebP, GIF (khuyên dùng ảnh vuông 256x256)</p>
          <div style="display:flex; flex-wrap:wrap; gap:8px;">
            <button class="btn-pill light" onclick="document.getElementById('logo-file-input').click()">📁 Chọn Tệp Ảnh Mới</button>
            <button class="btn-pill danger" onclick="resetDefaultLogo()">↺ Đặt Lại Mặc Định</button>
          </div>
          <input type="file" id="logo-file-input" accept="image/*" style="display:none;" onchange="handleLogoFileSelect(this)">
        </div>
      </div>

      <div class="form-group" style="margin-top:16px;">
        <label>Hoặc nhập trực tiếp đường dẫn URL ảnh Logo</label>
        <div style="display:flex; gap:8px;">
          <input type="text" id="logo-url-input" placeholder="https://example.com/my-logo.png">
          <button class="btn-pill dark" onclick="applyLogoUrl()" style="white-space:nowrap;">Áp Dụng URL</button>
        </div>
      </div>

      <div class="form-group" style="margin-top:20px; border-top:1px solid rgba(255,183,197,0.25); padding-top:16px;">
        <label>Tiêu đề thương hiệu Web (Web Title)</label>
        <input type="text" id="setting-web-title" value="{{ web_title }}">
      </div>

      <div class="form-group">
        <label>Tên nhà thiết kế bản quyền</label>
        <input type="text" id="setting-designer-name" value="{{ designer_name }}">
      </div>

      <button class="btn-pill primary full" onclick="saveWebSettings()">💾 Lưu Tất Cả Cài Đặt Giao Diện</button>
    </div>
  </div>

  <!-- ========================================== -->
  <!-- TAB 6: NHẬT KÝ HỆ THỐNG & HOẠT ĐỘNG (LOGS) -->
  <!-- ========================================== -->
  <div class="panel" id="panel-logs">
    <div class="card">
      <h2>
        <span class="card-header-icon">📜 Nhật Ký Hoạt Động & Sự Kiện Hệ Thống</span>
        <button class="btn-pill light" onclick="loadLogs()" style="padding:5px 12px; font-size:10px;">Làm mới nhật ký</button>
      </h2>
      <div class="box-list" id="logs-container" style="max-height:380px; font-family:'JetBrains Mono',monospace; font-size:11px; background:#1e293b; color:#f1f5f9;">
        <div style="padding:14px; text-align:center; color:#94a3b8;">Đang tải nhật ký...</div>
      </div>
    </div>
  </div>

</div>

<!-- THANH DOCK ĐIỀU HƯỚNG NỔI BO TRÒN PHONG CÁCH THREEUI -->
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
  <button class="dock-btn" data-tab="theme">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
    <span>Logo & Giao diện</span>
  </button>
  <button class="dock-btn" data-tab="logs">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
    <span>Nhật ký</span>
  </button>
</div>

<script>
// ==========================================
// TRẠNG THÁI TOÀN CỤC & CẤU HÌNH
// ==========================================
var flags = {
  all: true,      // Mặc định BẬT @All theo yêu cầu
  multi: true,
  emoji: true
};
var selectedBoxes = [];
var selectedTags = [];
var _boxes = [];
var _members = [];
var currentMode = "fast";
var fontSizeMode = "heading";
var colorMode = "rainbow";
var fixedColor = "red";
var ZALO_PALETTE = [];
var activeFileId = null;

// ==========================================
// TOAST THÔNG MINH (VUỐT LÊN BIẾN MẤT, KHÔNG CHỒNG, 1.4S)
// ==========================================
var Toast = (function(){
  var stack = null;
  function ensure(){
    if(!stack) stack = document.getElementById('toast-stack');
    return stack;
  }
  function show(msg, title, duration){
    duration = duration || 1400;
    var s = ensure();
    if(!s) return;
    s.querySelectorAll('.toast').forEach(el => el.remove());

    var el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = '<div class="t-head">🌸 ' + (title || 'ALB Forge') + '</div>' +
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
    el.addEventListener('click', dismiss);
  }
  return {
    success: (m, t, d) => show(m, t || 'Thành công', d),
    error: (m, t, d) => show(m, t || 'Lỗi xử lý', d || 1800),
    info: (m, t, d) => show(m, t || 'Thông báo', d)
  };
})();

// ==========================================
// PRELOADER MÀN HÌNH TẢI TRANG THREEUI
// ==========================================
function initPreloader(){
  var bar = document.getElementById('preloader-bar');
  var pct = document.getElementById('preloader-pct');
  var txt = document.getElementById('preloader-status-text');
  var wrap = document.getElementById('threeui-preloader');
  if(!wrap) return;

  var current = 0;
  var statusMsgs = [
    { p: 20, t: 'Đang tải hoạt cảnh cành hoa anh đào ThreeUI...' },
    { p: 45, t: 'Đang kết nối cơ sở dữ liệu SQLite...' },
    { p: 70, t: 'Đang đồng bộ bảng màu chuẩn Zalo Palette...' },
    { p: 90, t: 'Đang tối ưu động cơ đọc tệp tin O(1)...' },
    { p: 100, t: 'Hệ thống đã sẵn sàng điều khiển!' }
  ];

  var interval = setInterval(() => {
    current += 5;
    if(bar) bar.style.width = current + '%';
    if(pct) pct.textContent = current + '%';

    var match = statusMsgs.find(s => s.p === current);
    if(match && txt) txt.textContent = match.t;

    if(current >= 100){
      clearInterval(interval);
      setTimeout(() => {
        wrap.classList.add('loaded');
      }, 350);
    }
  }, 40);
}

// ĐỒNG HỒ THỜI GIAN THỰC (GMT+7)
function updateClock(){
  var now = new Date();
  var s = now.toLocaleTimeString('vi-VN', { hour12: false });
  var el = document.getElementById('live-clock');
  if(el) el.textContent = s;
}
setInterval(updateClock, 1000);
updateClock();

// ĐIỀU HƯỚNG TAB
function switchTab(tabName){
  document.querySelectorAll('.bottom-dock .dock-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tabName);
  });
  document.querySelectorAll('.panel').forEach(p => {
    p.classList.toggle('active', p.id === 'panel-' + tabName);
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
  if(tabName === 'logs') loadLogs();
  if(tabName === 'accounts') loadAccounts();
  if(tabName === 'files') loadFiles();
}

document.querySelectorAll('.bottom-dock .dock-btn').forEach(b => {
  b.addEventListener('click', () => {
    switchTab(b.dataset.tab);
  });
});

// THANH CHỌN CHẾ ĐỘ
document.querySelectorAll('#mode-selector .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#mode-selector .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    currentMode = c.dataset.mode;
    document.getElementById('spam-mode').value = currentMode;
  });
});

// THANH CHỌN CỠ CHỮ (KHẮC PHỤC CHỮ CHƯA IN ĐẬM TO RA)
document.querySelectorAll('#font-size-bar .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#font-size-bar .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    fontSizeMode = c.dataset.fsize;
    document.getElementById('font-size-mode').value = fontSizeMode;
    Toast.info('Đã chọn cỡ chữ: ' + c.textContent.trim());
  });
});

// THANH CHỌN MÀU SẮC CHỮ
document.querySelectorAll('#color-mode-bar .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#color-mode-bar .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    colorMode = c.dataset.cmode;
    document.getElementById('color-mode').value = colorMode;
    document.getElementById('fixed-colors-wrap').style.display = (colorMode === 'fixed') ? 'flex' : 'none';
  });
});

// THANH CHỌN DELAY
document.querySelectorAll('#delay-bar .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#delay-bar .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    document.getElementById('spam-delay').value = c.dataset.delay;
  });
});

// THANH CHỌN ICON
document.querySelectorAll('#icon-bar .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#icon-bar .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    document.getElementById('icon-count').value = c.dataset.icon;
  });
});

// CÔNG TẮC BẬT TẮT
function tgFlag(name){
  flags[name] = !flags[name];
  var el = document.getElementById('tg-' + name);
  if(el) el.classList.toggle('active', flags[name]);
  if(name === 'all'){
    Toast.info(flags.all ? 'ĐÃ BẬT @ALL TOÀN NHÓM' : 'ĐÃ TẮT @ALL');
  }
}

function tgTagSection(){
  var wrap = document.getElementById('tag-section-wrap');
  var btn = document.getElementById('tg-tag-toggle');
  var isHidden = (wrap.style.display === 'none' || !wrap.style.display);
  wrap.style.display = isHidden ? 'block' : 'none';
  if(btn) btn.classList.toggle('active', isHidden);
}

function handleFileSelect(input){
  if(input.files && input.files.length > 0){
    var f = input.files[0];
    var sizeMB = (f.size / (1024 * 1024)).toFixed(2);
    document.getElementById('upload-txt').innerHTML = `Đã chọn: <b>${f.name}</b> (${sizeMB} MB)`;
    document.getElementById('upload-txt').style.color = "var(--sakura)";
  }
}

// API GỌI DỮ LIỆU CHUẨN
async function api(url, opts = {}){
  try {
    var r = await fetch(url, Object.assign({}, opts, {
      headers: Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {})
    }));
    return await r.json();
  } catch(e){
    return { error: 'Lỗi mạng: ' + e.message };
  }
}

// ==========================================
// TÙY BIẾN LOGO & GIAO DIỆN (THEME & LOGO MANAGER)
// ==========================================
function handleLogoFileSelect(input){
  if(input.files && input.files.length > 0){
    var file = input.files[0];
    var reader = new FileReader();
    reader.onload = function(e){
      document.getElementById('theme-logo-preview').src = e.target.result;
    };
    reader.readAsDataURL(file);
    uploadLogoFile(file);
  }
}

async function uploadLogoFile(file){
  var fd = new FormData();
  fd.append('logo', file);
  Toast.info('Đang tải lên ảnh logo mới...');
  try {
    var r = await fetch('/api/upload_logo', { method: 'POST', body: fd }).then(x => x.json());
    if(r.ok){
      Toast.success('Cập nhật Logo Web thành công!');
      var newUrl = r.url || ('/static/logo.png?t=' + Date.now());
      document.getElementById('header-logo').src = newUrl;
      document.getElementById('theme-logo-preview').src = newUrl;
      var f = document.getElementById('page-favicon');
      if(f) f.href = newUrl;
    } else {
      Toast.error(r.error || 'Lỗi tải ảnh logo');
    }
  } catch(e){
    Toast.error('Lỗi tải ảnh: ' + e.message);
  }
}

async function applyLogoUrl(){
  var url = document.getElementById('logo-url-input').value.trim();
  if(!url) return Toast.error('Vui lòng nhập đường dẫn URL ảnh Logo');
  Toast.info('Đang kiểm tra & áp dụng URL logo...');
  var r = await api('/api/set_logo_url', { method: 'POST', body: JSON.stringify({ url }) });
  if(r.ok){
    Toast.success('Đã áp dụng ảnh Logo từ URL!');
    var newUrl = r.url || url;
    document.getElementById('header-logo').src = newUrl;
    document.getElementById('theme-logo-preview').src = newUrl;
  } else {
    Toast.error(r.error || 'Không thể áp dụng URL ảnh');
  }
}

async function resetDefaultLogo(){
  if(!confirm('Đặt lại Logo trang web về mặc định hoa anh đào?')) return;
  var r = await api('/api/reset_logo', { method: 'POST' });
  if(r.ok){
    Toast.success('Đã đặt lại Logo mặc định');
    var defaultUrl = '/static/logo.png?t=' + Date.now();
    document.getElementById('header-logo').src = defaultUrl;
    document.getElementById('theme-logo-preview').src = defaultUrl;
  }
}

async function saveWebSettings(){
  var title = document.getElementById('setting-web-title').value.trim();
  var designer = document.getElementById('setting-designer-name').value.trim();
  if(!title) return Toast.error('Tiêu đề web không được để trống');
  var r = await api('/api/settings/update', {
    method: 'POST',
    body: JSON.stringify({ web_title: title, designer_name: designer })
  });
  if(r.ok){
    Toast.success('Đã lưu cài đặt giao diện!');
    document.getElementById('header-web-title').textContent = title;
    document.getElementById('header-designer').textContent = designer;
    document.title = title;
  } else {
    Toast.error(r.error || 'Lỗi lưu cài đặt');
  }
}

// ==========================================
// QUẢN LÝ TÀI KHOẢN (ACCOUNTS)
// ==========================================
async function loadAccounts(){
  var accs = await api('/api/accounts');
  if(!Array.isArray(accs)) accs = [];
  var tb = document.getElementById('accounts-tbody');
  var liveCount = 0;
  tb.innerHTML = accs.map(a => {
    var realName = a.display_name || a.zalo_name || a.username || 'Chưa cập nhật';
    var isLive = (a.status === 'live');
    if(isLive) liveCount++;
    var badge = isLive ? '<span class="status-badge live">● HOẠT ĐỘNG</span>' : '<span class="status-badge dead">● NGẮT KẾT NỐI</span>';
    return `<tr>
      <td>${a.id}</td>
      <td><b>${a.label}</b></td>
      <td><span style="color:var(--sakura); font-weight:800;">${realName}</span></td>
      <td><code>…${String(a.uid||'').slice(-6)}</code></td>
      <td id="status-${a.id}">${badge}</td>
      <td>
        <button class="btn-pill light" onclick="checkAccount(${a.id})" style="padding:6px 12px; font-size:10px;">Kiểm tra</button>
        <button class="btn-pill danger" onclick="delAcc(${a.id})" style="padding:6px 12px; font-size:10px;">Xóa</button>
      </td>
    </tr>`;
  }).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--txt-2); padding:18px;">Chưa có tài khoản nào được thêm</td></tr>';

  document.getElementById('accounts-count-badge').textContent = `Tổng: ${accs.length} acc (${liveCount} hoạt động)`;
  var s1 = document.getElementById('load-acc-select');
  var s2 = document.getElementById('member-acc-select');
  var opts = '<option value="">-- Chọn tài khoản --</option>' + accs.map(a => `<option value="${a.id}">${a.label} (${a.display_name||'Zalo'})</option>`).join('');
  if(s1) s1.innerHTML = opts;
  if(s2) s2.innerHTML = opts;
}

async function checkAccount(aid){
  Toast.info('Đang kiểm tra kết nối tài khoản...');
  var r = await api(`/api/accounts/${aid}/check`, { method: 'POST' });
  var el = document.getElementById(`status-${aid}`);
  if(r.ok){
    if(el) el.innerHTML = '<span class="status-badge live">● HOẠT ĐỘNG</span>';
    Toast.success('Tài khoản ' + (r.name || '') + ' hoạt động tốt!');
  } else {
    if(el) el.innerHTML = '<span class="status-badge dead">● NGẮT KẾT NỐI</span>';
    Toast.error('Tài khoản đã hết hạn hoặc cookie lỗi');
  }
}

async function checkAllAccounts(){
  Toast.info('Đang kiểm tra toàn bộ danh sách...');
  var r = await api('/api/accounts/check_all', { method: 'POST' });
  Toast.success(`Hoàn tất: ${r.live}/${r.total} tài khoản sống`);
  loadAccounts();
}

async function addAccount(){
  var label = document.getElementById('add-label').value.trim();
  var imei = document.getElementById('add-imei').value.trim();
  var cookies = document.getElementById('add-cookies').value.trim();
  if(!imei || !cookies) return Toast.error('Vui lòng điền đủ IMEI và Cookie');
  Toast.info('Đang xác thực thông tin đăng nhập...');
  var r = await api('/api/accounts/add', { method: 'POST', body: JSON.stringify({ label, imei, cookies }) });
  if(r.error) return Toast.error(r.error);
  Toast.success('Thêm tài khoản thành công!');
  document.getElementById('add-label').value = '';
  document.getElementById('add-imei').value = '';
  document.getElementById('add-cookies').value = '';
  loadAccounts();
}

async function delAcc(id){
  if(!confirm('Xác nhận xóa tài khoản #' + id + '?')) return;
  await api('/api/accounts/' + id, { method: 'DELETE' });
  Toast.success('Đã xóa tài khoản');
  loadAccounts();
}

// ==========================================
// QUẢN LÝ HỘI THOẠI (BOXES)
// ==========================================
async function loadBoxes(){
  var aid = document.getElementById('load-acc-select').value;
  if(!aid) return Toast.error('Vui lòng chọn tài khoản trước');
  Toast.info('Đang nạp danh sách hội thoại từ Zalo...');
  var r = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  var all = (r.groups||[]).concat(r.friends||[]);
  var bl = document.getElementById('box-list');
  bl.innerHTML = all.map((b,i) => `
    <div class="box-item" onclick="tgBox(this, ${i})">
      <div class="check-mark">✓</div>
      <div>
        <div class="b-title">${b.name}</div>
        <div class="b-sub">ID: ${b.id} • ${b.type === 'group' ? ('Nhóm (' + (b.members||'?') + ' tv)') : 'Bạn bè'}</div>
      </div>
    </div>
  `).join('') || '<div style="text-align:center; padding:18px;">Không tìm thấy cuộc trò chuyện nào</div>';
  _boxes = all;
  selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
  document.getElementById('boxes-total-count').textContent = 'Tổng có: ' + all.length + ' mục';
  Toast.success('Đã nạp thành công ' + all.length + ' hội thoại');
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
  Toast.info('Đã chọn tất cả ' + selectedBoxes.length + ' hội thoại');
}

function clearAllBoxes(){
  document.querySelectorAll('#box-list .box-item').forEach(el => el.classList.remove('selected'));
  selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
  Toast.info('Đã bỏ chọn tất cả');
}

// QUÉT THÀNH VIÊN TÊN THẬT
async function loadMembers(){
  var aid = document.getElementById('member-acc-select').value;
  if(!aid) return Toast.error('Vui lòng chọn tài khoản quét');
  var box = selectedBoxes.find(b => b.type === 'group');
  if(!box) return Toast.error('Cần chọn ít nhất 1 nhóm ở tab Hội Thoại');
  Toast.info('Đang quét tên thật thành viên trong nhóm ' + box.name + '...');
  var r = await api('/api/accounts/' + aid + '/members/' + box.id, { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  var mem = r.members || [];
  var sel = document.getElementById('tag-selector');
  sel.style.display = 'block';
  sel.innerHTML = mem.map((m, i) => `
    <div class="box-item" onclick="tgMember(this, ${i})">
      <div class="check-mark">✓</div>
      <div>
        <div class="b-title">${m.name}</div>
        <div class="b-sub">UID: ${m.id}</div>
      </div>
    </div>
  `).join('') || '<div style="padding:14px; text-align:center;">Không có thành viên nào</div>';
  _members = mem;
  selectedTags = [];
  Toast.success('Đã nạp ' + mem.length + ' thành viên tên thật');
}

function tgMember(el, idx){
  var m = _members[idx];
  if(!m) return;
  if(el.classList.contains('selected')){
    el.classList.remove('selected');
    selectedTags = selectedTags.filter(t => t.id !== m.id);
  } else {
    el.classList.add('selected');
    selectedTags.push({ id: m.id, name: m.name });
  }
}

// ==========================================
// TẢI LÊN TẬP TIN DUNG LƯỢNG LỚN SIÊU NHANH (STREAM XHR)
// ==========================================
function uploadTextFileStream(){
  var inp = document.getElementById('file-input');
  if(!inp.files || !inp.files.length) return Toast.error('Vui lòng chọn tệp tin văn bản trước');
  var file = inp.files[0];

  var pWrap = document.getElementById('upload-progress-wrap');
  var pBar = document.getElementById('upload-progress-bar');
  var pTxt = document.getElementById('upload-progress-text');
  pWrap.style.display = 'block';
  pTxt.style.display = 'block';
  pBar.style.width = '0%';
  pTxt.textContent = '0%';

  var fd = new FormData();
  fd.append('file', file);

  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/files/upload', true);

  xhr.upload.onprogress = function(e){
    if(e.lengthComputable){
      var pct = Math.round((e.loaded / e.total) * 100);
      pBar.style.width = pct + '%';
      pTxt.textContent = `Đang tải: ${pct}% (${(e.loaded/1048576).toFixed(1)}MB / ${(e.total/1048576).toFixed(1)}MB)`;
    }
  };

  xhr.onload = function(){
    pWrap.style.display = 'none';
    pTxt.style.display = 'none';
    if(xhr.status === 200){
      var res = JSON.parse(xhr.responseText);
      if(res.ok){
        Toast.success(`Lưu thành công! ${res.lines} khối, ${res.total_lines} dòng (${(res.size/1048576).toFixed(2)} MB)`);
        inp.value = '';
        document.getElementById('upload-txt').textContent = "Kéo thả hoặc Nhấn để chọn tệp Văn bản (.txt, .log)";
        loadFiles();
      } else {
        Toast.error(res.error || 'Lỗi lưu tệp tin');
      }
    } else {
      Toast.error('Lỗi máy chủ khi tải tệp: HTTP ' + xhr.status);
    }
  };

  xhr.onerror = function(){
    pWrap.style.display = 'none';
    pTxt.style.display = 'none';
    Toast.error('Lỗi kết nối khi tải tệp tin');
  };

  Toast.info('Bắt đầu tải tệp tin lên máy chủ...');
  xhr.send(fd);
}

async function loadFiles(){
  var files = await api('/api/files');
  if(!Array.isArray(files)) files = [];
  var list = document.getElementById('files-list');
  list.innerHTML = files.map(f => {
    var sizeMB = (f.size / (1024 * 1024)).toFixed(2);
    return `
      <div class="box-item" style="cursor:default;">
        <div style="flex:1;">
          <div class="b-title">📄 ${f.filename}</div>
          <div class="b-sub">${f.lines} khối văn bản • ${sizeMB} MB • ${new Date(f.uploaded_at*1000).toLocaleString('vi-VN')}</div>
        </div>
        <button class="btn-pill light" onclick="previewFile(${f.id})" style="padding:5px 12px; font-size:10px;">Xem thử</button>
        <button class="btn-pill danger" onclick="delFile(${f.id})" style="padding:5px 12px; font-size:10px;">Xóa</button>
      </div>
    `;
  }).join('') || '<div style="text-align:center; padding:18px; color:var(--txt-2);">Chưa có tập tin nào</div>';

  var s = document.getElementById('spam-file-select');
  if(s){
    s.innerHTML = '<option value="">-- Hoặc nhập trực tiếp bên dưới --</option>' +
      files.map(f => `<option value="${f.id}">📄 ${f.filename} (${f.lines} khối, ${(f.size/1048576).toFixed(1)}MB)</option>`).join('');
  }
}

async function delFile(id){
  if(!confirm('Xác nhận xóa tệp tin này?')) return;
  await api('/api/files/' + id, { method: 'DELETE' });
  Toast.success('Đã xóa tệp tin');
  loadFiles();
}

async function previewFile(fid){
  var r = await api('/api/files/' + fid + '/preview');
  if(r.error) return Toast.error(r.error);
  var sample = (r.preview || []).slice(0, 5).join('\n--- [Khối kế tiếp] ---\n');
  alert(`Xem trước tập tin "${r.filename}" (Tổng: ${r.total_blocks} khối, ${(r.size/1048576).toFixed(2)} MB):\n\n` + sample);
}

function handleSpamFileChange(){
  var fid = document.getElementById('spam-file-select').value;
  var b = document.getElementById('file-info-badge');
  if(fid){
    activeFileId = fid;
    b.style.display = 'block';
    b.textContent = '✓ Đang kích hoạt chế độ nạp trực tiếp Stream từ đĩa cứng O(1) Memory';
  } else {
    activeFileId = null;
    b.style.display = 'none';
  }
}

// ==========================================
// KHỞI CHẠY TIẾN TRÌNH GỬI TIN NHẮN TỰ ĐỘNG
// ==========================================
async function startSpam(){
  if(!selectedBoxes.length) return Toast.error('Vui lòng chọn ít nhất 1 hội thoại nhận tin');
  var fid = document.getElementById('spam-file-select').value;
  var direct = document.getElementById('spam-messages').value.trim();

  // Khắc phục triệt để việc lag khi tệp nhiều MB:
  // Nếu chọn file, ta chỉ gửi file_id sang server, KHÔNG tải hàng chục MB JSON về client rồi gửi lại!
  var payload = {
    targets: selectedBoxes,
    delay: parseFloat(document.getElementById('spam-delay').value) || 1,
    use_emoji: flags.emoji,
    icon_count: flags.emoji ? (parseInt(document.getElementById('icon-count').value) || 3) : 0,
    tag_users: selectedTags,
    tag_all: flags.all, // Luôn gửi cờ @All chuẩn
    font_size_mode: fontSizeMode, // Sửa lỗi in đậm to ra
    is_heading: (fontSizeMode === 'heading' || fontSizeMode === 'giant'),
    multi_acc: flags.multi,
    mode: currentMode,
    color_mode: colorMode, // Sửa lỗi đổi màu chữ
    fixed_color: fixedColor
  };

  if(fid){
    payload.file_id = parseInt(fid);
  } else if(direct){
    if(currentMode === "treo_ngon"){
      payload.blocks = [direct];
    } else if(currentMode === "treo_nhay"){
      payload.blocks = [direct];
    } else {
      payload.blocks = direct.includes(';') ? direct.split(';').map(m => m.trim()).filter(Boolean) : [direct];
    }
  } else {
    return Toast.error('Vui lòng chọn tệp tin hoặc nhập văn bản gửi');
  }

  Toast.info('Đang kích hoạt tiến trình gửi tin...');
  var res = await api('/api/tasks/start', { method: 'POST', body: JSON.stringify(payload) });
  if(res.error) return Toast.error(res.error);
  Toast.success('Khởi chạy tiến trình thành công! Đang gửi...');
  loadTasks();
}

async function stopAll(){
  await api('/api/tasks/stop_all', { method: 'POST' });
  Toast.info('Đã ra lệnh dừng toàn bộ tiến trình');
  loadTasks();
}

async function loadTasks(){
  var tasks = await api('/api/tasks');
  if(!Array.isArray(tasks)) tasks = [];
  var tb = document.getElementById('tasks-tbody');
  tb.innerHTML = tasks.map(t => {
    var running = (t.status === 'running');
    var sent = 0;
    try { sent = JSON.parse(t.stats||'{}').sent || 0; } catch(e){}
    return `<tr>
      <td><code>${t.id.slice(-8)}</code></td>
      <td><b>${t.type}</b></td>
      <td>${running ? '<span class="status-badge live">● ĐANG GỬI</span>' : '<span class="status-badge dead">● ĐÃ DỪNG</span>'}</td>
      <td><b style="color:var(--sakura);">${sent}</b> tin</td>
      <td>${running ? `<button class="btn-pill danger" onclick="stopTask('${t.id}')" style="padding:5px 12px; font-size:10px;">Dừng</button>` : ''}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="5" style="text-align:center; padding:16px; color:var(--txt-2);">Không có tiến trình nào</td></tr>';
}

async function stopTask(tid){
  await api('/api/tasks/' + tid + '/stop', { method: 'POST' });
  Toast.info('Đã gửi tín hiệu dừng tiến trình');
  loadTasks();
}

// BẢNG MÀU CHUẨN ZALO PALETTE
async function loadColors(){
  var cols = await api('/api/colors');
  if(Array.isArray(cols)){
    ZALO_PALETTE = cols;
    var wrap = document.getElementById('fixed-colors-wrap');
    if(wrap){
      wrap.innerHTML = cols.map(c => `
        <div class="chip-item" style="border-color:${c.hex}; color:${c.hex}; font-weight:800;" onclick="setFixedColor('${c.id}')">
          <span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:${c.hex};"></span> ${c.name}
        </div>
      `).join('');
    }
  }
}

function setFixedColor(cid){
  fixedColor = cid;
  Toast.info('Đã cố định màu: ' + cid);
}

// NHẬT KÝ HOẠT ĐỘNG
async function loadLogs(){
  var logs = await api('/api/logs');
  if(!Array.isArray(logs)) logs = [];
  var c = document.getElementById('logs-container');
  if(c){
    c.innerHTML = logs.map(l => {
      var col = (l.level === 'ERROR') ? '#f87171' : (l.level === 'WARN') ? '#fbbf24' : (l.level === 'SUCCESS') ? '#34d399' : '#38bdf8';
      return `<div style="padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.08);">
        <span style="color:#94a3b8;">[${l.ts}]</span>
        <span style="color:${col}; font-weight:bold;">[${l.level}]</span>
        <span>${l.msg}</span>
      </div>`;
    }).join('') || '<div style="padding:14px; text-align:center; color:#94a3b8;">Chưa có sự kiện nào được ghi nhận</div>';
  }
}

// ==========================================
// CANVAS CÁNH HOA & LÁ ANH ĐÀO RƠI 60FPS VỚI HIỆU ỨNG TƯƠNG TÁC CHUỘT
// ==========================================
(function(){
  var canvas = document.getElementById('sakura-canvas');
  if(!canvas) return;
  var ctx = canvas.getContext('2d');
  var w = window.innerWidth, h = window.innerHeight;
  canvas.width = w; canvas.height = h;

  var mouseX = -1000, mouseY = -1000;
  window.addEventListener('mousemove', e => { mouseX = e.clientX; mouseY = e.clientY; });
  window.addEventListener('touchmove', e => {
    if(e.touches.length > 0){
      mouseX = e.touches[0].clientX;
      mouseY = e.touches[0].clientY;
    }
  }, { passive: true });

  var particles = [];
  var particleCount = 55;

  for(var i = 0; i < particleCount; i++){
    particles.push({
      x: Math.random() * w,
      y: Math.random() * h - h,
      size: Math.random() * 9 + 6,
      speedY: Math.random() * 1.5 + 0.8,
      speedX: Math.random() * 2 - 1,
      angle: Math.random() * 360,
      angVel: (Math.random() - 0.5) * 2,
      isLeaf: Math.random() < 0.3,
      alpha: Math.random() * 0.35 + 0.65,
      tilt: Math.random() * 10 - 5
    });
  }

  function drawPetalShape(p){
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(p.angle * Math.PI / 180);
    ctx.scale(Math.cos(p.tilt), 1);

    if(p.isLeaf){
      // Vẽ Lá Anh Đào xanh non
      ctx.fillStyle = `rgba(52, 211, 153, ${p.alpha})`;
      ctx.shadowBlur = 4;
      ctx.shadowColor = 'rgba(5, 150, 105, 0.3)';
      ctx.beginPath();
      ctx.ellipse(0, 0, p.size * 0.45, p.size, 0, 0, Math.PI * 2);
      ctx.fill();
      // Gân lá
      ctx.strokeStyle = 'rgba(4, 120, 87, 0.4)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, -p.size * 0.8);
      ctx.lineTo(0, p.size * 0.8);
      ctx.stroke();
    } else {
      // Vẽ Cánh Hoa Anh Đào hồng phấn
      ctx.fillStyle = `rgba(255, 183, 197, ${p.alpha})`;
      ctx.shadowBlur = 5;
      ctx.shadowColor = 'rgba(255, 105, 180, 0.35)';
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.bezierCurveTo(p.size / 2, -p.size / 2, p.size, 0, 0, p.size);
      ctx.bezierCurveTo(-p.size, 0, -p.size / 2, -p.size / 2, 0, 0);
      ctx.fill();
    }
    ctx.restore();
  }

  function animate(){
    ctx.clearRect(0, 0, w, h);
    particles.forEach(p => {
      // Tương tác gió khi chuột lướt qua
      var dx = p.x - mouseX;
      var dy = p.y - mouseY;
      var dist = Math.sqrt(dx * dx + dy * dy);
      if(dist < 100){
        var force = (100 - dist) / 100;
        p.x += (dx / dist) * force * 5;
        p.y += (dy / dist) * force * 5;
      }

      drawPetalShape(p);

      p.y += p.speedY;
      p.x += p.speedX + Math.sin(p.y * 0.015) * 0.6;
      p.angle += p.angVel;
      p.tilt += 0.03;

      if(p.y > h + 25){
        p.y = -25;
        p.x = Math.random() * w;
      }
      if(p.x > w + 25) p.x = -25;
      if(p.x < -25) p.x = w + 25;
    });
    requestAnimationFrame(animate);
  }
  animate();

  window.addEventListener('resize', () => {
    w = window.innerWidth;
    h = window.innerHeight;
    canvas.width = w;
    canvas.height = h;
  });
})();

// KHỞI ĐỘNG HỆ THỐNG
function refreshAll(){
  loadAccounts();
  loadFiles();
  loadTasks();
  loadColors();
}

window.addEventListener('DOMContentLoaded', () => {
  initPreloader();
  refreshAll();
  setInterval(loadTasks, 4000);
});
</script>
</body>
</html>
"""

# ============================================================
# CÁC ĐƯỜNG DẪN ROUTE VÀ API ĐIỀU HÀNH HỆ THỐNG
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
    web_title = get_setting("web_title", "I LOVE NGỌC HÂN 🌸")
    designer_name = get_setting("designer_name", "Phạm Anh Khôi")
    logo_url = get_setting("logo_path", "/static/logo.png")
    return render_template_string(
        HTML_INDEX,
        web_title=web_title,
        designer_name=designer_name,
        logo_url=logo_url
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    ip = get_client_ip()
    now = time.time()
    tracker = login_fail_tracker[ip]

    web_title = get_setting("web_title", "I LOVE NGỌC HÂN 🌸")
    designer_name = get_setting("designer_name", "Phạm Anh Khôi")
    logo_url = get_setting("logo_path", "/static/logo.png")

    if tracker["locked_until"] > now:
        rem = int(tracker["locked_until"] - now)
        return render_template_string(
            HTML_LOGIN,
            error=f"Tạm khóa kết nối do nhập sai quá 5 lần. Vui lòng thử lại sau {rem} giây.",
            web_title=web_title,
            designer_name=designer_name,
            logo_url=logo_url
        )

    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == APP_PASSWORD:
            session["logged_in"] = True
            login_fail_tracker[ip] = {"count": 0, "locked_until": 0}
            log_event("SUCCESS", f"Đăng nhập thành công từ IP {ip}")
            return redirect(url_for("index"))
        else:
            tracker["count"] += 1
            log_event("WARN", f"Đăng nhập thất bại từ IP {ip} (Lần {tracker['count']})")
            if tracker["count"] >= LOGIN_MAX_FAILS:
                tracker["locked_until"] = now + LOGIN_LOCKOUT_TIME
                return render_template_string(
                    HTML_LOGIN,
                    error="Nhập sai 5 lần liên tiếp! Hệ thống tạm khóa IP này trong 15 phút.",
                    web_title=web_title,
                    designer_name=designer_name,
                    logo_url=logo_url
                )
            rem = LOGIN_MAX_FAILS - tracker["count"]
            return render_template_string(
                HTML_LOGIN,
                error=f"Mật khẩu bảo mật không chính xác! Bạn còn {rem} lần thử.",
                web_title=web_title,
                designer_name=designer_name,
                logo_url=logo_url
            )

    return render_template_string(
        HTML_LOGIN,
        web_title=web_title,
        designer_name=designer_name,
        logo_url=logo_url
    )

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ============================================================
# API QUẢN LÝ CÀI ĐẶT & LOGO WEB
# ============================================================
@app.route("/api/settings", methods=["GET"])
@login_required
def api_get_settings():
    conn = db()
    rows = conn.execute("SELECT * FROM settings").fetchall()
    conn.close()
    return jsonify({r["key"]: r["value"] for r in rows})

@app.route("/api/settings/update", methods=["POST"])
@login_required
def api_update_settings():
    d = request.json or {}
    for k, v in d.items():
        set_setting(k, v)
    log_event("INFO", "Đã cập nhật cài đặt giao diện web")
    return jsonify({"ok": True})

@app.route("/api/upload_logo", methods=["POST"])
@login_required
def api_upload_logo():
    if "logo" not in request.files:
        return jsonify({"error": "Không tìm thấy tệp ảnh logo"}), 400
    f = request.files["logo"]
    if not f or not f.filename:
        return jsonify({"error": "Tên tệp rỗng"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in [".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"]:
        return jsonify({"error": "Định dạng tệp không hợp lệ (hỗ trợ .png, .jpg, .webp, .svg)"}), 400

    save_path = os.path.join(STATIC_DIR, "logo.png")
    try:
        f.save(save_path)
        new_url = f"/static/logo.png?t={int(time.time()*1000)}"
        set_setting("logo_path", new_url)
        log_event("SUCCESS", "Đã thay đổi ảnh Logo Web mới thành công")
        return jsonify({"ok": True, "url": new_url})
    except Exception as e:
        return jsonify({"error": f"Lỗi lưu ảnh logo: {e}"}), 500

@app.route("/api/set_logo_url", methods=["POST"])
@login_required
def api_set_logo_url():
    d = request.json or {}
    url = d.get("url", "").strip()
    if not url:
        return jsonify({"error": "Đường dẫn URL ảnh rỗng"}), 400
    set_setting("logo_path", url)
    log_event("SUCCESS", f"Đã cập nhật Logo Web từ URL: {url}")
    return jsonify({"ok": True, "url": url})

@app.route("/api/reset_logo", methods=["POST"])
@login_required
def api_reset_logo():
    default_url = "/static/logo.png"
    set_setting("logo_path", default_url)
    log_event("INFO", "Đã đặt lại Logo Web về mặc định")
    return jsonify({"ok": True, "url": default_url})

@app.route("/api/colors", methods=["GET"])
@login_required
def api_colors():
    return jsonify(ZALO_PALETTE)

# ============================================================
# API QUẢN LÝ TÀI KHOẢN ZALO
# ============================================================
@app.route("/api/accounts", methods=["GET"])
@login_required
def api_accounts():
    conn = db()
    rows = conn.execute("SELECT * FROM accounts ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/accounts/add", methods=["POST"])
@login_required
def api_accounts_add():
    d = request.json or {}
    label = d.get("label", "").strip() or ("acc_" + str(int(time.time())))
    imei = d.get("imei", "").strip()
    ck = d.get("cookies", "").strip()
    if not imei or not ck:
        return jsonify({"error": "Vui lòng nhập đầy đủ IMEI và Cookie"}), 400
    try:
        ck_obj = json.loads(ck)
        z = Zalo(imei, ck_obj)
        st = "live"
    except Exception as e:
        return jsonify({"error": f"Không thể đăng nhập tài khoản Zalo: {e}"}), 400

    conn = db()
    conn.execute("""
        INSERT INTO accounts (label, imei, cookies, added_at,
                             uid, display_name, zalo_name, username, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (label, imei, json.dumps(ck_obj), time.time(),
          z.uid, z.display_name or "", z.zalo_name or "", z.username or "", st))
    conn.commit()
    conn.close()
    log_event("SUCCESS", f"Đã thêm tài khoản Zalo mới: {label} ({z.display_name})")
    return jsonify({"ok": True, "label": label})

@app.route("/api/accounts/<int:aid>", methods=["DELETE"])
@login_required
def api_accounts_delete(aid):
    conn = db()
    conn.execute("DELETE FROM accounts WHERE id = ?", (aid,))
    conn.commit()
    conn.close()
    log_event("INFO", f"Đã xóa tài khoản #{aid}")
    return jsonify({"ok": True})

@app.route("/api/accounts/<int:aid>/check", methods=["POST"])
@login_required
def api_accounts_check(aid):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Không tìm thấy tài khoản"}), 404
    try:
        z = Zalo(row["imei"], json.loads(row["cookies"]))
        conn.execute("UPDATE accounts SET status = 'live', display_name = ? WHERE id = ?",
                     (z.display_name or row["display_name"], aid))
        conn.commit()
        conn.close()
        log_event("SUCCESS", f"Kiểm tra tài khoản {row['label']}: Hoạt động tốt")
        return jsonify({"ok": True, "status": "live", "name": z.display_name})
    except Exception as e:
        conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
        conn.commit()
        conn.close()
        log_event("WARN", f"Kiểm tra tài khoản {row['label']}: Ngắt kết nối ({e})")
        return jsonify({"ok": False, "status": "dead", "error": str(e)}), 400

@app.route("/api/accounts/check_all", methods=["POST"])
@login_required
def api_accounts_check_all():
    conn = db()
    rows = conn.execute("SELECT * FROM accounts").fetchall()
    live_count = 0
    for r in rows:
        try:
            z = Zalo(r["imei"], json.loads(r["cookies"]))
            conn.execute("UPDATE accounts SET status = 'live', display_name = ? WHERE id = ?",
                         (z.display_name or r["display_name"], r["id"]))
            live_count += 1
        except Exception:
            conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (r["id"],))
    conn.commit()
    conn.close()
    log_event("INFO", f"Đã kiểm tra toàn bộ: {live_count}/{len(rows)} tài khoản hoạt động")
    return jsonify({"ok": True, "total": len(rows), "live": live_count})

@app.route("/api/accounts/<int:aid>/load_boxes", methods=["POST"])
@login_required
def api_load_boxes(aid):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Không tìm thấy tài khoản"}), 404
    try:
        z = Zalo(row["imei"], json.loads(row["cookies"]))
        groups = z.groups()
        friends = z.friends()
        log_event("INFO", f"Tài khoản {row['label']} nạp được {len(groups)} nhóm, {len(friends)} bạn bè")
        return jsonify({"ok": True, "groups": groups, "friends": friends})
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
        members = z.get_members_full(group_id)
        log_event("INFO", f"Quét thành công {len(members)} thành viên nhóm {group_id}")
        return jsonify({"ok": True, "members": members})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ============================================================
# API QUẢN LÝ TẬP TIN DUNG LƯỢNG LỚN (SIÊU TỐC)
# ============================================================
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
        return jsonify({"error": "Tập tin rỗng"}), 400

    safe_name = f"{int(time.time())}_{f.filename}"
    save_path = os.path.join(UPLOAD_DIR, safe_name)

    # Ghi tệp tin trực tiếp xuống ổ cứng qua luồng bộ đệm 64KB (Stream write)
    try:
        with open(save_path, "wb") as dest:
            shutil.copyfileobj(f.stream, dest, length=64*1024)
    except Exception as e:
        return jsonify({"error": f"Lỗi lưu trữ tệp: {e}"}), 500

    file_size = os.path.getsize(save_path)

    # Đếm số khối và số dòng bằng thuật toán Stream O(1) Memory
    total_blocks, total_lines = FileBlockReader.inspect_file(save_path)

    conn = db()
    conn.execute("""
        INSERT INTO files (filename, filepath, lines, size, uploaded_at)
        VALUES (?, ?, ?, ?, ?)
    """, (f.filename, save_path, total_blocks, file_size, time.time()))
    conn.commit()
    conn.close()

    log_event("SUCCESS", f"Đã lưu tệp {f.filename} ({total_blocks} khối, {total_lines} dòng, {(file_size/1048576):.2f}MB)")
    return jsonify({
        "ok": True,
        "filename": f.filename,
        "lines": total_blocks,
        "total_lines": total_lines,
        "size": file_size
    })

@app.route("/api/files/<int:fid>", methods=["DELETE"])
@login_required
def api_files_delete(fid):
    conn = db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    if row:
        try:
            if os.path.exists(row["filepath"]):
                os.remove(row["filepath"])
        except Exception:
            pass
        conn.execute("DELETE FROM files WHERE id = ?", (fid,))
        conn.commit()
        log_event("INFO", f"Đã xóa tệp tin {row['filename']}")
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

    # Chỉ đọc mẫu 25 khối đầu tiên, hoàn toàn không nạp toàn bộ tệp vào RAM
    preview_blocks = FileBlockReader.get_preview(row["filepath"], max_blocks=25)
    return jsonify({
        "filename": row["filename"],
        "preview": preview_blocks,
        "total_blocks": row["lines"],
        "size": row["size"]
    })

# ============================================================
# API QUẢN LÝ TIẾN TRÌNH & ĐỘNG CƠ GỬI TIN
# ============================================================
@app.route("/api/tasks", methods=["GET"])
@login_required
def api_tasks():
    conn = db()
    rows = conn.execute("SELECT * FROM tasks ORDER BY started_at DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/tasks/start", methods=["POST"])
@login_required
def api_tasks_start():
    d = request.json or {}
    targets = d.get("targets", [])
    file_id = d.get("file_id")
    blocks = d.get("blocks", [])
    delay = float(d.get("delay", 1.0))
    use_emoji = bool(d.get("use_emoji", True))
    icon_count = int(d.get("icon_count", 3))
    tag_users = d.get("tag_users", [])
    tag_all = bool(d.get("tag_all", True)) # Mặc định BẬT
    font_size_mode = d.get("font_size_mode", "heading")
    is_heading = bool(d.get("is_heading", True))
    multi_acc = bool(d.get("multi_acc", True))
    mode = d.get("mode", "fast")
    color_mode = d.get("color_mode", "rainbow")
    fixed_color = d.get("fixed_color", "red")

    if not targets:
        return jsonify({"error": "Vui lòng chọn ít nhất 1 cuộc trò chuyện nhận tin"}), 400

    file_path = None
    if file_id:
        conn = db()
        frow = conn.execute("SELECT filepath FROM files WHERE id = ?", (file_id,)).fetchone()
        conn.close()
        if frow and os.path.exists(frow["filepath"]):
            file_path = frow["filepath"]

    if not file_path and not blocks:
        return jsonify({"error": "Vui lòng chọn tệp tin hoặc nhập nội dung gửi"}), 400

    tid = new_tid("task")
    stop_ev = threading.Event()

    th = threading.Thread(
        target=task_supervisor,
        args=(tid, targets, file_path, blocks, delay, use_emoji, icon_count,
              tag_users, tag_all, font_size_mode, is_heading, multi_acc, mode,
              color_mode, fixed_color, stop_ev),
        daemon=True
    )

    conn = db()
    conn.execute("""
        INSERT INTO tasks (id, type, meta, status, started_at, stats)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tid, mode, json.dumps({
        "multi_acc": multi_acc,
        "color_mode": color_mode,
        "font_size_mode": font_size_mode,
        "tag_all": tag_all,
        "file_id": file_id
    }), "running", time.time(), "{}"))
    conn.commit()
    conn.close()

    ACTIVE_TASKS[tid] = {"stop": stop_ev, "thread": th}
    th.start()
    log_event("SUCCESS", f"Khởi chạy thành công tiến trình {tid} (Chế độ: {mode})")
    return jsonify({"ok": True, "task_id": tid})

@app.route("/api/tasks/<tid>/stop", methods=["POST"])
@login_required
def api_tasks_stop(tid):
    if tid in ACTIVE_TASKS:
        ACTIVE_TASKS[tid]["stop"].set()
        log_event("INFO", f"Yêu cầu dừng tiến trình {tid}")
        return jsonify({"ok": True})
    return jsonify({"error": "Không tìm thấy tiến trình đang chạy"}), 404

@app.route("/api/tasks/stop_all", methods=["POST"])
@login_required
def api_tasks_stop_all():
    count = 0
    for tid, t in list(ACTIVE_TASKS.items()):
        t["stop"].set()
        count += 1
    log_event("INFO", f"Đã dừng tất cả ({count}) tiến trình")
    return jsonify({"ok": True, "count": count})

@app.route("/api/logs", methods=["GET"])
@login_required
def api_get_logs():
    return jsonify(list(system_logs))

# ============================================================
# ĐIỂM KHỞI CHẠY CHÍNH CỦA MÁY CHỦ
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n=======================================================")
    print(f"🌸 ALB FORGE — THREEUI SAKURA EDITION 2026")
    print(f"🌸 Bản quyền thiết kế: Phạm Anh Khôi")
    print(f"🌸 Máy chủ đang lắng nghe trên cổng: http://0.0.0.0:{port}")
    print(f"=======================================================\n")
    app.run(host="0.0.0.0", port=port, debug=False)
