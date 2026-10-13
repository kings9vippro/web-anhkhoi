# ============================================================
# Bản quyền thuộc về Ricki Vip
# Hệ Thống: RICKI VIP — CHIẾN HẠM PRO (MAX COMBAT & SECURITY EDITION) ❄️
# Hỗ trợ Đa Nền Tảng: Zalo & Discord (Acc User Token Trực Tiếp)
# Tích hợp: Anti-Ban Siêu Cấp, Anti-Die-All, Tag @All & Tag Tên Chuẩn 100%
# Bộ Phối Icon Sát Thương Cực Cao Chọc Tức Đối Thủ | Tối Ưu Tệp 5MB+
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
import requests

# Hỗ trợ tương thích cả PyCryptodome (Crypto) lẫn Cryptography
try:
    from Crypto.Cipher import AES
    def aes_cbc_encrypt(key, iv, data):
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return cipher.encrypt(data)
    def aes_cbc_decrypt(key, iv, data):
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return cipher.decrypt(data)
except ImportError:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        def aes_cbc_encrypt(key, iv, data):
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
            enc = cipher.encryptor()
            return enc.update(data) + enc.finalize()
        def aes_cbc_decrypt(key, iv, data):
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
            dec = cipher.decryptor()
            return dec.update(data) + dec.finalize()
    except Exception:
        raise ImportError("Vui lòng cài đặt pycryptodome hoặc cryptography để chạy mã hóa Zalo.")

APP_PASSWORD = os.environ.get("APP_PASSWORD", "rickivip")
DATA_DIR = os.environ.get("DATA_DIR", "/tmp/ricki_web")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "ricki_vip.db")

# ============================================================
# LỚP BẢO MẬT WEB & API TÂN TIẾN TỐI ĐA (RICKI VIP SECURITY ARMOR)
# ============================================================
class WebSecurityArmor:
    """Bộ giáp bảo mật Web & API siêu cấp Ricki Vip:
    - Adaptive Rate Limiter chống DDoS / spam request
    - Anti-Brute-Force bảo vệ đăng nhập (khóa IP sau 5 lần sai)
    - Phòng vệ Path Traversal & Injection
    - Quản lý phiên an toàn chống giả mạo
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.req_history = defaultdict(list)    # ip -> [timestamps]
        self.failed_logins = defaultdict(list)  # ip -> [timestamps]
        self.blocked_ips = {}                   # ip -> unblock_timestamp

    def check_rate_limit(self, ip, max_reqs=120, window=60):
        now = time.time()
        with self.lock:
            # Kiểm tra nếu IP đang trong danh sách cách ly
            if ip in self.blocked_ips:
                if now < self.blocked_ips[ip]:
                    remain = int(self.blocked_ips[ip] - now)
                    return False, f"IP của bạn tạm thời bị cách ly bảo vệ. Vui lòng thử lại sau {remain} giây."
                else:
                    del self.blocked_ips[ip]

            # Dọn dẹp request cũ
            history = [t for t in self.req_history[ip] if now - t < window]
            history.append(now)
            self.req_history[ip] = history

            if len(history) > max_reqs:
                self.blocked_ips[ip] = now + 60
                return False, "Phát hiện tần suất truy cập bất thường (Rate Limit Exceeded). Tạm khóa 60s để bảo vệ hệ thống."

            return True, None

    def record_login_attempt(self, ip, success):
        now = time.time()
        with self.lock:
            if success:
                self.failed_logins.pop(ip, None)
            else:
                fails = [t for t in self.failed_logins[ip] if now - t < 300]
                fails.append(now)
                self.failed_logins[ip] = fails
                if len(fails) >= 5:
                    self.blocked_ips[ip] = now + 180  # Khóa 3 phút sau 5 lần sai
                    return False, "CẢNH BÁO BẢO MẬT: Đăng nhập sai quá 5 lần! IP bị khóa trong 3 phút."
            return True, None


SECURITY_ARMOR = WebSecurityArmor()


UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "phamanhkhoi-vip-noel-2026")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

# ============================================================
# CƠ CHẾ BẢO MẬT & CHỐNG TẤN CÔNG
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
def security_firewall():
    ip = get_client_ip()
    now = time.time()

    with security_lock:
        if ip in ip_blocked_until:
            if now < ip_blocked_until[ip]:
                return jsonify({"error": "IP bị tạm khóa do nghi vấn spam/DDoS. Vui lòng thử lại sau.", "status": 429}), 429
            else:
                del ip_blocked_until[ip]

        history = ip_request_history[ip]
        history = [t for t in history if now - t < 60]
        history.append(now)
        ip_request_history[ip] = history

        burst = [t for t in history if now - t < 1]
        if len(burst) > DDOS_BURST_PER_SEC or len(history) > DDOS_LIMIT_PER_MINUTE:
            ip_blocked_until[ip] = now + 180
            return jsonify({"error": "Phát hiện tần suất truy cập bất thường. Đã chặn 3 phút.", "status": 429}), 429


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "Chưa đăng nhập", "status": 401}), 401
            return redirect(url_for("page_gate"))
        return f(*args, **kwargs)
    return decorated


# ============================================================
# CƠ SỞ DỮ LIỆU SQLITE
# ============================================================
def db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
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
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        meta TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at REAL NOT NULL,
        ended_at REAL,
        stats TEXT DEFAULT '{}'
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        filepath TEXT NOT NULL,
        lines INTEGER NOT NULL,
        size INTEGER NOT NULL,
        uploaded_at REAL NOT NULL
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()


init_db()

# ============================================================
# BẢNG MÀU CHUẨN ZALO VÀ HUY HIỆU MÀU HIỆN TRÊN MỌI THIẾT BỊ
# ============================================================
ZALO_PALETTE = [
    {"id": "red", "hex": "#e8453c", "name": "Đỏ Ruby", "badge": "🔴"},
    {"id": "yellow", "hex": "#f1c40f", "name": "Vàng Kim", "badge": "🟡"},
    {"id": "green", "hex": "#2ecc71", "name": "Xanh Lá", "badge": "🟢"},
    {"id": "orange", "hex": "#e67e22", "name": "Cam Lửa", "badge": "🟠"},
    {"id": "cyan", "hex": "#00cec9", "name": "Xanh Biển", "badge": "💎"},
    {"id": "blue", "hex": "#0984e3", "name": "Xanh Dương", "badge": "🔵"},
    {"id": "purple", "hex": "#9b59b6", "name": "Tím Violet", "badge": "🟣"},
    {"id": "pink", "hex": "#fd79a8", "name": "Hồng Sen", "badge": "🌸"},
]

RAINBOW_HEX = [c["hex"] for c in ZALO_PALETTE]
COLOR_BADGES = {c["id"]: c["badge"] for c in ZALO_PALETTE}

# ============================================================
# KHO ICON SÁT THƯƠNG CỰC CAO & BỘ PHỐI ICON CHỌC TỨC ĐỐI THỦ
# ============================================================
ICONS_DAMAGE = ["💀", "☠️", "💣", "💥", "🔥", "⚡", "🔨", "🔪", "🪓", "🩸", "⚰️", "🪦", "🥊", "⚔️"]
ICONS_TROLL = ["🤡", "🤫", "🖕", "🖕🏻", "💩", "👎", "🥱", "🤮", "🐷", "🐸", "🐶", "🐒", "🥴", "💨", "🎪", "🫵"]
ICONS_MOCK = ["🤣", "😂", "😏", "🤪", "😜", "🤭", "😹", "👀", "😎", "👻"]
ICONS_ZALO_CLASSIC = ["/-punch", "/-break", "/-liar", "/-strong", "/-no", "/-ok", ":-p", ":-d", ":-*", ";)"]


def generate_combat_combo(combo_type="mixed", count=3):
    """Tạo chuỗi icon phối hợp có sát thương cao và chọc tức đối thủ tột đỉnh."""
    if combo_type == "damage":
        chosen = [random.choice(ICONS_DAMAGE) for _ in range(count)]
    elif combo_type == "troll":
        chosen = [random.choice(ICONS_TROLL) for _ in range(count)]
    elif combo_type == "mock":
        chosen = [random.choice(ICONS_MOCK) for _ in range(count)]
    elif combo_type == "classic":
        chosen = [random.choice(ICONS_ZALO_CLASSIC) for _ in range(count)]
    else: # mixed (God mode: 1 Sát thương + 1 Chọc tức + 1 Cười đểu + 1 Zalo Classic)
        chosen = [
            random.choice(ICONS_DAMAGE),
            random.choice(ICONS_TROLL),
            random.choice(ICONS_MOCK),
            random.choice(ICONS_ZALO_CLASSIC)
        ]
        if count > 4:
            for _ in range(count - 4):
                chosen.append(random.choice(ICONS_DAMAGE + ICONS_TROLL))
        elif count < 4:
            chosen = chosen[:count]
    return " ".join(chosen)


def utf16_len(s):
    return len(s.encode('utf-16-le')) // 2


# ============================================================
# BỘ CÔNG CỤ ANTI-BAN SIÊU CẤP ĐA TẦNG & ANTI-DIE-ALL
# ============================================================
ZERO_WIDTH_CHARS = ["​", "‌", "‍", "﻿", "⁠", "⁢", "⁣", "⁤"]


def apply_antiband_advanced(text):
    """Hàm chống ban siêu cấp V3 - Độc quyền Ricki Vip:
    1. Giữ nguyên 100% từng từ tiếng Việt, tuyệt đối KHÔNG cắt xẻ vào giữa từ
       (Khắc phục triệt để lỗi vỡ phông chữ, lỗi dấu thanh tiếng Việt và ô vuông tofu).
    2. Biến thiên khoảng trắng an toàn giữa các từ (Standard Space, Non-Breaking Space, Thin Space).
    3. Dynamic Tail Hash Signature: Tạo chữ ký băm vô hình ở cuối văn bản (3-7 ký tự zero-width),
       đảm bảo mỗi tin gửi đi đều có mã băm SHA256 hoàn toàn khác biệt mà mắt thường không thấy.
    4. 100% mắt người đọc nhìn thấy hoàn hảo trên Zalo Mobile, PC và Discord."""
    if not text:
        return text
    
    # Danh sách khoảng trắng unicode an toàn không làm hỏng font
    SAFE_SPACES = [" ", "\u00a0", " \u200b", "\u2009", "\u200a"]
    SAFE_TAIL_CHARS = ["\u200b", "\u200c", "\u200d", "\ufeff"]
    
    # Tách theo khoảng trắng thông thường, giữ nguyên vẹn 100% từ ngữ tiếng Việt
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
    
    # Tạo mã băm tàng hình ở CUỐI tin nhắn (không chạm vào chữ cái, không vỡ font)
    tail_len = random.randint(3, 7)
    tail = "".join(random.choice(SAFE_TAIL_CHARS) for _ in range(tail_len))
    result += tail
    return result


class AccountHealthManager:
    """Cơ chế Anti-Die-All: Giám sát trạng thái từng tài khoản, tự động cách ly
    khi gặp Rate-Limit (429) hoặc lỗi liên tiếp, bảo vệ dàn account không bị chết chùm."""
    def __init__(self):
        self.lock = threading.Lock()
        self.cool_down = {}
        self.fail_streak = defaultdict(int)

    def is_usable(self, acc_id):
        with self.lock:
            cd_until = self.cool_down.get(acc_id, 0)
            if time.time() < cd_until:
                return False
            return True

    def report_success(self, acc_id):
        with self.lock:
            self.fail_streak[acc_id] = 0

    def report_rate_limit(self, acc_id, retry_after=30):
        with self.lock:
            self.cool_down[acc_id] = time.time() + max(retry_after, 25)
            print(f"🔒 [Anti-Die] Tài khoản #{acc_id} dính Rate Limit (429). Tạm nghỉ {retry_after}s.")

    def report_error(self, acc_id):
        with self.lock:
            self.fail_streak[acc_id] += 1
            if self.fail_streak[acc_id] >= 4:
                self.cool_down[acc_id] = time.time() + 60
                print(f"🔒 [Anti-Die] Tài khoản #{acc_id} lỗi 4 lần liên tiếp. Tạm cách ly 60s.")


HEALTH_MGR = AccountHealthManager()


# ============================================================
# TRÌNH ĐỌC FILE STREAMING TỐC ĐỘ CAO (XỬ LÝ TỆP 5MB+ KHÔNG LAG)
# ============================================================
class FastFileBlockReader:
    """Đọc tệp văn bản cực lớn (5MB - 50MB+) theo luồng O(1) RAM.
    Không bao giờ nạp toàn bộ file vào bộ nhớ trình duyệt hay server."""
    def __init__(self, filepath):
        self.filepath = filepath
        self.fp = open(filepath, "r", encoding="utf-8", errors="ignore")

    def next_block(self):
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
        # Hết file thì tự động tua lại từ đầu để lặp liên tục
        self.fp.seek(0)
        for line in self.fp:
            line_str = line.strip()
            if line_str:
                return line.rstrip("\r\n")
        return None

    def close(self):
        try: self.fp.close()
        except Exception: pass


# ============================================================
# CLIENT GIAO THỨC ZALO WEB API (CHUẨN XÁC CAO CẤP)
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
            raise Exception("Không thể lấy khóa giải mã bảo mật Zalo")

    def _enc(self, params):
        key = base64.b64decode(self.secret_key)
        iv = bytes(16)
        pt = json.dumps(params, ensure_ascii=False).encode("utf-8")
        pad = 16 - len(pt) % 16
        pt += bytes([pad]) * pad
        ct = aes_cbc_encrypt(key, iv, pt)
        return base64.b64encode(ct).decode()

    def _dec(self, enc):
        key = base64.b64decode(self.secret_key)
        iv = bytes(16)
        d = aes_cbc_decrypt(key, iv, base64.b64decode(enc))
        pad = d[-1]
        return d[:-pad].decode("utf-8", "ignore")

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
        """Lấy toàn bộ danh sách thành viên nhóm kèm tên hiển thị thật,
        kết hợp cross-reference với danh bạ bạn bè để luôn có tên chính xác."""
        try:
            enc = self._enc({"gridVerMap": json.dumps({str(gid): 0})})
            r = self.s.post(
                "https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2",
                params={"zpw_ver": 645, "zpw_type": 30},
                data={"params": enc}, timeout=20,
            )
            data_raw = r.json()
            if "data" not in data_raw:
                return []
            dec = self._dec(data_raw["data"])
            info = json.loads(dec).get("data", {}).get("gridInfoMap", {}).get(str(gid), {})
        except Exception as e:
            print(f"Lỗi lấy thông tin nhóm {gid}: {e}")
            return []

        members_dict = {}
        # Quét danh bạ bạn bè trước để lưu tên chuẩn
        try:
            frs = self.friends()
            for f in frs:
                members_dict[f["id"]] = f["name"]
        except Exception:
            pass

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
                        data={"params": enc2}, timeout=15,
                    )
                    r2_json = r2.json()
                    if "data" in r2_json:
                        dec2 = self._dec(r2_json["data"])
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

        if not out and members_dict:
            out = [{"id": uid, "name": name} for uid, name in members_dict.items()]

        return out

    def build_colored_message(self, raw_text, color_mode, fixed_color, is_heading=True, color_offset=0, use_badge=True):
        """Định dạng màu sắc và huy hiệu cho từng dòng/khối văn bản."""
        lines = [l for l in raw_text.split("\n")]
        styled_lines = []
        styles = []
        current_u16_pos = 0
        first_color = "red"

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

            clean_content = content
            if clean_content.startswith("#"):
                clean_content = clean_content.lstrip("#").strip()

            badge_str = ""
            if use_badge and c_id:
                badge_str = COLOR_BADGES.get(c_id, "🔴") + " "

            if is_heading:
                line_text = f"# {badge_str}{clean_content}"
            else:
                line_text = f"{badge_str}{clean_content}"

            styled_lines.append(line_text)
            l_len = utf16_len(line_text)

            if c_hex:
                clean_hex = c_hex.lstrip("#").lower()
                styles.append({
                    "start": current_u16_pos,
                    "offset": current_u16_pos,
                    "len": l_len,
                    "length": l_len,
                    "st": f"c_{clean_hex}",
                    "type": "color",
                    "value": f"#{clean_hex}"
                })

            current_u16_pos += l_len + 1

        final_msg = "\n".join(styled_lines)
        return final_msg, styles, first_color

    def attach_mentions(self, msg, mentions=None, tag_all=False, tag_mode="rotate", mention_index=0, tag_pos="head"):
        """Gắn thẻ tag @All và tag tên người chuẩn xác 100% vào tin nhắn Zalo.
        Khắc phục hoàn toàn lỗi trôi offset UTF-16 và xung đột với Markdown Header."""
        m_arr = []
        tag_tokens = []

        if tag_all:
            tag_tokens.append({"token": "@All", "uid": "-1", "type": 1})

        if mentions and len(mentions) > 0:
            if tag_mode == "rotate":
                target_user = mentions[mention_index % len(mentions)]
                raw_name = str(target_user.get("name", "")).strip()
                name = raw_name.split(" (")[0] if " (" in raw_name else raw_name
                uid = str(target_user.get("id") or target_user.get("uid") or "").strip()
                if name and uid:
                    tag_tokens.append({"token": f"@{name}", "uid": uid, "type": 0})
            else:
                for target_user in mentions:
                    raw_name = str(target_user.get("name", "")).strip()
                    name = raw_name.split(" (")[0] if " (" in raw_name else raw_name
                    uid = str(target_user.get("id") or target_user.get("uid") or "").strip()
                    if name and uid:
                        tag_tokens.append({"token": f"@{name}", "uid": uid, "type": 0})

        if not tag_tokens:
            return msg, []

        # Ghép chuỗi tag
        tags_str = " ".join([t["token"] for t in tag_tokens])

        # Đặt ở đầu (Head) giúp 100% không bị xung đột với Markdown # và offset = 0
        if tag_pos == "head":
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
                curr_pos += tlen + 1 # +1 khoảng trắng
            final_msg = tags_str + "\n" + msg
        else: # Đặt ở cuối
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
            final_msg = base + " " + tags_str

        return final_msg, m_arr

    def send_adv(self, raw_text, thread_id, color_mode="rainbow", fixed_color="red",
                 is_group=True, mentions=None, tag_all=False, is_heading=True,
                 color_offset=0, antiband=True, use_badge=True, tag_mode="rotate",
                 mention_index=0, tag_pos="head"):
        url = ("https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
               if is_group
               else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms")

        processed_text = apply_antiband_advanced(raw_text) if antiband else raw_text

        styled_msg, styles, first_color = self.build_colored_message(
            processed_text, color_mode, fixed_color, is_heading=is_heading,
            color_offset=color_offset, use_badge=use_badge
        )

        final_msg, m_arr = self.attach_mentions(
            styled_msg,
            mentions=(mentions if is_group else None),
            tag_all=(tag_all if is_group else False),
            tag_mode=tag_mode,
            mention_index=mention_index,
            tag_pos=tag_pos
        )

        # Cân chỉnh lại offset của styles nếu tag được chèn ở đầu
        if tag_pos == "head" and m_arr:
            prefix_len = utf16_len(final_msg) - utf16_len(styled_msg)
            for s in styles:
                s["start"] += prefix_len
                s["offset"] += prefix_len

        pl = {
            "message": final_msg,
            "clientId": str(int(time.time() * 1000)) + str(random.randint(100, 999)),
            "imei": self.imei,
        }
        if m_arr:
            pl["mentions"] = m_arr

        if color_mode != "none":
            pl["msgColor"] = first_color
            if styles:
                pl["styles"] = styles

        if is_group:
            pl["visibility"] = 0
            pl["grid"] = str(thread_id)
        else:
            pl["toid"] = str(thread_id)

        enc = self._enc(pl)
        return self.s.post(url, params={"zpw_ver": 645, "zpw_type": 30},
                           data={"params": enc}, timeout=15)


# ============================================================
# CLIENT DISCORD TÀI KHOẢN CÁ NHÂN (USER TOKEN DIRECT - CHUẨN XỊN)
# ============================================================
class DiscordUserClient:
    """Điều khiển trực tiếp tài khoản Discord cá nhân (User Token).
    Không dùng Bot Discord, dùng thẳng quyền của tài khoản người dùng."""
    def __init__(self, user_token):
        self.token = str(user_token).strip()
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": self.token,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        })
        self.user_info = None

    def check(self):
        try:
            r = self.s.get("https://discord.com/api/v10/users/@me", timeout=12)
            if r.status_code == 200:
                self.user_info = r.json()
                return True
        except Exception:
            pass
        return False

    def get_guilds(self):
        try:
            r = self.s.get("https://discord.com/api/v10/users/@me/guilds", timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return []

    def get_channels(self, guild_id):
        try:
            r = self.s.get(f"https://discord.com/api/v10/guilds/{guild_id}/channels", timeout=15)
            if r.status_code == 200:
                channels = r.json()
                return [c for c in channels if c.get("type") in (0, 5)]
        except Exception:
            pass
        return []

    def get_dm_channels(self):
        try:
            r = self.s.get("https://discord.com/api/v10/users/@me/channels", timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return []

    def send_message(self, channel_id, content, color_mode="none", fixed_color=None, antiband=True):
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        msg_text = apply_antiband_advanced(content) if antiband else content

        DISCORD_ANSI_CODES = {
            "red": "31",
            "yellow": "33",
            "green": "32",
            "orange": "33",
            "cyan": "36",
            "blue": "34",
            "purple": "35",
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
            retry = r.json().get("retry_after", 15)
            raise Exception(f"429:RateLimit:{retry}")
        if r.status_code not in (200, 201):
            raise Exception(f"HTTP {r.status_code}: {r.text}")
        return r


# ============================================================
# GIAO DIỆN SIÊU VIP CYBER GLASSMORPHISM NOEL (HIỆU ỨNG CỰC ĐẸP)
# ============================================================
CSS_VIP = """
/* NÂNG CẤP ĐỘ NHẠY & TƯƠNG TÁC CHO NÚT BẤM RICKI VIP */
#snow-canvas {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  pointer-events: none !important; z-index: 0 !important;
}

.container {
  max-width: 1080px; margin: 0 auto; padding: 18px 16px;
  position: relative; z-index: 25;
}

.btn-pill, .btn-round, .dock-btn, .top-nav-btn, .chip-item, .toggle-item {
  position: relative; z-index: 30;
  cursor: pointer !important;
  user-select: none;
  touch-action: manipulation !important;
  -webkit-tap-highlight-color: transparent;
}
.btn-pill:hover, .btn-round:hover, .top-nav-btn:hover {
  filter: brightness(1.18);
}
.btn-pill:active, .btn-round:active, .top-nav-btn:active {
  transform: scale(0.96) translateY(1px) !important;
}

/* THANH ĐIỀU HƯỚNG TABS PHÍA TRÊN (TOP NAV BAR) */
.top-nav-bar {
  display: flex; gap: 8px; overflow-x: auto; padding: 10px 0 14px;
  margin-bottom: 14px; scrollbar-width: none;
}
.top-nav-bar::-webkit-scrollbar { display: none; }
.top-nav-btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 10px 18px; border-radius: 99px;
  background: rgba(13, 23, 42, 0.85); border: 1.5px solid var(--border-neon);
  color: var(--txt-1); font-size: 12px; font-weight: 800; white-space: nowrap;
  transition: all 0.25s var(--ease); backdrop-filter: blur(15px);
}
.top-nav-btn .nav-ic { font-size: 15px; }
.top-nav-btn:hover {
  color: #fff; border-color: var(--neon-gold); background: rgba(255, 183, 3, 0.12);
}
.top-nav-btn.active {
  background: var(--grad-vip) !important; color: #fff !important;
  border-color: transparent !important;
  box-shadow: 0 0 20px rgba(255, 51, 68, 0.6) !important;
}

/* THANH DOCK BÊN DƯỚI KÈM CHỮ GỢI NHỚ */
.dock-btn {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 3px; padding: 8px 12px; border-radius: 18px;
}
.dock-label {
  font-size: 9.5px; font-weight: 800; letter-spacing: 0.3px;
}

/* TRUNG TÂM BẢO MẬT & ANTI-BAN CARD */
.sec-badge {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 99px; font-size: 10.5px; font-weight: 800;
  background: rgba(0, 255, 136, 0.15); color: var(--neon-green); border: 1px solid var(--neon-green);
}
.sec-card-box {
  background: rgba(6, 11, 20, 0.7); border: 1.5px solid var(--border-neon);
  border-radius: 18px; padding: 16px; margin-bottom: 12px;
}

/* THANH ĐIỀU KHIỂN NỔI PRO (FLOATING ACTION BAR TRONG GỬI TIN) */
.action-control-banner {
  background: rgba(13, 23, 42, 0.95); border: 2px solid var(--border-gold);
  border-radius: 24px; padding: 18px; margin: 20px 0;
  display: flex; align-items: center; justify-content: space-around; flex-wrap: wrap; gap: 14px;
  box-shadow: 0 10px 40px rgba(0,0,0,0.8), 0 0 20px rgba(255, 183, 3, 0.3);
}

:root {
  --bg-page: #060b14;
  --bg-card: rgba(13, 23, 42, 0.88);
  --border-neon: rgba(231, 76, 60, 0.55);
  --border-gold: rgba(243, 156, 18, 0.7);
  --txt-0: #ffffff;
  --txt-1: #e2e8f0;
  --txt-2: #94a3b8;
  --neon-red: #ff3344;
  --neon-green: #00ff88;
  --neon-gold: #ffb703;
  --neon-blue: #00d4ff;
  --grad-vip: linear-gradient(135deg, #ff0844 0%, #ff4e50 50%, #f9d423 100%);
  --grad-green: linear-gradient(135deg, #00b09b 0%, #96c93d 100%);
  --grad-dark: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  --shadow-neon-red: 0 0 25px rgba(255, 51, 68, 0.5), 0 4px 15px rgba(0, 0, 0, 0.5);
  --shadow-neon-green: 0 0 25px rgba(0, 255, 136, 0.5), 0 4px 15px rgba(0, 0, 0, 0.5);
  --shadow-neon-gold: 0 0 25px rgba(255, 183, 3, 0.5), 0 4px 15px rgba(0, 0, 0, 0.5);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html { touch-action: manipulation; -webkit-text-size-adjust: 100%; }
body {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background-color: var(--bg-page);
  color: var(--txt-1);
  min-height: 100vh;
  padding-bottom: 115px;
  position: relative;
  overflow-x: hidden;
  background-image: radial-gradient(circle at 50% 5%, rgba(255, 51, 68, 0.22) 0%, transparent 55%),
                    radial-gradient(circle at 85% 85%, rgba(0, 255, 136, 0.15) 0%, transparent 50%),
                    radial-gradient(circle at 15% 90%, rgba(0, 212, 255, 0.15) 0%, transparent 50%);
}

#snow-canvas {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  pointer-events: none; z-index: 1;
}

.header {
  position: sticky; top: 0; z-index: 1000;
  background: rgba(6, 11, 20, 0.94);
  backdrop-filter: blur(25px);
  border-bottom: 1.5px solid var(--border-neon);
  box-shadow: 0 4px 30px rgba(0, 0, 0, 0.7);
  padding: 14px 18px;
}
.header-inner { max-width: 1050px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.logo-box { display: flex; align-items: center; gap: 12px; }
.logo-box img {
  width: 44px; height: 44px; border-radius: 50%; object-fit: cover;
  border: 2px solid var(--neon-gold); box-shadow: var(--shadow-neon-gold);
}
.header-meta { min-width: 0; }
.header-meta h1 {
  font-family: 'Orbitron', sans-serif; font-size: 16px; font-weight: 900;
  letter-spacing: 0.8px; color: var(--txt-0); display: flex; align-items: center; gap: 8px;
  text-shadow: 0 0 12px rgba(255, 183, 3, 0.6);
}
.header-meta p { font-size: 11px; color: var(--txt-2); font-weight: 700; margin-top: 3px; display: flex; align-items: center; gap: 5px; }
.v-badge { display: inline-flex; align-items: center; justify-content: center; color: var(--neon-blue); font-weight: 900; }

.container { max-width: 1050px; margin: 0 auto; padding: 18px 16px; position: relative; z-index: 10; }
.panel { display: none; animation: slideUp .35s var(--ease) both; }
.panel.active { display: block; }
@keyframes slideUp { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }

.card {
  background: var(--bg-card);
  backdrop-filter: blur(35px);
  padding: 22px; border-radius: 24px; border: 1.5px solid rgba(255, 255, 255, 0.12);
  box-shadow: 0 15px 45px rgba(0, 0, 0, 0.6); margin-bottom: 16px;
  position: relative; overflow: hidden;
}
.card::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: var(--grad-vip);
}
.card h2 {
  font-size: 13px; font-weight: 900; letter-spacing: .6px; margin-bottom: 16px;
  display: flex; align-items: center; justify-content: space-between; color: var(--neon-gold);
}

.btn-pill {
  padding: 12px 20px; border-radius: 99px; border: none; cursor: pointer;
  font-size: 11.5px; font-weight: 800; letter-spacing: .5px;
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  transition: all 0.25s var(--ease); text-decoration: none; position: relative;
}
.btn-pill:hover { transform: translateY(-2px) scale(1.02); }
.btn-pill:active { transform: translateY(0) scale(0.96); }
.btn-pill.primary { background: var(--grad-vip); color: #fff; box-shadow: var(--shadow-neon-red); }
.btn-pill.green { background: var(--grad-green); color: #000; font-weight: 900; box-shadow: var(--shadow-neon-green); }
.btn-pill.dark { background: var(--grad-dark); color: #fff; border: 1.5px solid var(--border-gold); }
.btn-pill.light { background: rgba(255, 255, 255, 0.08); color: #fff; border: 1px solid rgba(255, 255, 255, 0.2); }
.btn-pill.danger { background: rgba(255, 51, 68, 0.2); color: #ff6b6b; border: 1.5px solid var(--neon-red); }
.btn-pill.full { width: 100%; padding: 14px; font-size: 12.5px; }

.btn-round {
  width: 58px; height: 58px; border-radius: 50%; border: none; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  transition: all 0.3s var(--ease); margin: 0 8px;
}
.btn-round svg { width: 26px; height: 26px; }
.btn-round:hover { transform: scale(1.15) translateY(-3px); }
.btn-round.action-start {
  background: var(--neon-green); color: #000; box-shadow: var(--shadow-neon-green);
  animation: pulseGreen 2s infinite;
}
@keyframes pulseGreen { 0%, 100% { box-shadow: 0 0 20px rgba(0, 255, 136, 0.5); } 50% { box-shadow: 0 0 35px rgba(0, 255, 136, 0.9); } }
.btn-round.action-stop {
  background: var(--neon-red); color: #fff; box-shadow: var(--shadow-neon-red);
}

.file-upload-label {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 10px; padding: 28px; border: 2px dashed var(--border-gold);
  border-radius: 20px; background: rgba(243, 156, 18, 0.06);
  cursor: pointer; text-align: center; transition: all 0.3s var(--ease);
}
.file-upload-label:hover { background: rgba(243, 156, 18, 0.16); border-color: #fff; transform: translateY(-2px); }
.file-upload-label svg { width: 34px; height: 34px; color: var(--neon-gold); }
.file-upload-label span { font-size: 12.5px; font-weight: 800; color: var(--txt-0); }

.form-group { margin-bottom: 14px; }
.form-group label { display: block; margin-bottom: 7px; font-size: 11px; font-weight: 800; color: var(--neon-gold); }
.form-group input:not([type="file"]):not([type="checkbox"]):not([type="radio"]), .form-group textarea, .form-group select {
  width: 100%; padding: 13px 16px; border: 1.5px solid rgba(255, 255, 255, 0.15); border-radius: 16px;
  font-size: 12.5px; background: rgba(6, 11, 20, 0.9); color: var(--txt-0); transition: all .25s;
}
.form-group input:focus, .form-group textarea:focus, .form-group select:focus {
  outline: none; border-color: var(--neon-gold); box-shadow: 0 0 15px rgba(243, 156, 18, 0.4);
}
.form-group textarea { min-height: 95px; font-family: 'JetBrains Mono', monospace; font-size: 12px; }

.chip-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.chip-item {
  padding: 9px 16px; background: rgba(255, 255, 255, 0.06); color: var(--txt-1); border-radius: 99px;
  font-size: 11px; font-weight: 800; cursor: pointer; border: 1.5px solid rgba(255, 255, 255, 0.15);
  transition: all .25s var(--ease);
}
.chip-item:hover { border-color: var(--neon-gold); color: #fff; transform: translateY(-2px); }
.chip-item.active { background: var(--grad-vip); color: #fff; border-color: transparent; box-shadow: var(--shadow-neon-red); }

.toggle-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 14px; }
.toggle-item {
  padding: 13px 12px; border: 1.5px solid rgba(255, 255, 255, 0.15); border-radius: 16px;
  cursor: pointer; text-align: center; font-weight: 800; font-size: 11px;
  background: rgba(255, 255, 255, 0.05); color: var(--txt-2); transition: all .25s;
}
.toggle-item:hover { transform: translateY(-2px); border-color: rgba(255, 255, 255, 0.4); }
.toggle-item.active { background: var(--grad-green); color: #000; font-weight: 900; border-color: transparent; box-shadow: var(--shadow-neon-green); }

.table-wrap { overflow-x: auto; border-radius: 18px; border: 1.5px solid rgba(255, 255, 255, 0.12); background: rgba(6, 11, 20, 0.95); }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { padding: 13px 15px; text-align: left; font-size: 11.5px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); white-space: nowrap; color: var(--txt-1); }
.table th { background: rgba(255, 255, 255, 0.06); font-weight: 800; color: var(--neon-gold); font-size: 10px; }

.box-list { max-height: 290px; overflow-y: auto; border: 1.5px solid rgba(255, 255, 255, 0.15); border-radius: 18px; padding: 10px; background: rgba(6, 11, 20, 0.9); }
.box-item {
  padding: 12px 16px; border: 1.5px solid rgba(255, 255, 255, 0.1); border-radius: 14px;
  margin-bottom: 7px; cursor: pointer; background: rgba(255, 255, 255, 0.03); display: flex; align-items: center; gap: 12px; transition: all .2s;
}
.box-item:hover { border-color: var(--neon-gold); background: rgba(243, 156, 18, 0.1); transform: translateX(3px); }
.box-item.selected { border-color: var(--neon-red); background: rgba(255, 51, 68, 0.25); box-shadow: 0 0 15px rgba(255, 51, 68, 0.3); }
.box-item .check-mark {
  width: 20px; height: 20px; border: 1.5px solid var(--txt-2); border-radius: 6px;
  display: flex; align-items: center; justify-content: center; font-size: 11px; color: transparent; font-weight: 900;
}
.box-item.selected .check-mark { background: var(--neon-red); border-color: var(--neon-red); color: #fff; }
.box-item .b-title { font-weight: 800; font-size: 12.5px; color: var(--txt-0); }
.box-item .b-sub { font-size: 10px; color: var(--txt-2); font-family: 'JetBrains Mono', monospace; }

.bottom-dock {
  position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
  width: calc(100% - 24px); max-width: 560px;
  background: rgba(13, 23, 42, 0.96); backdrop-filter: blur(35px);
  border: 1.5px solid var(--border-neon); border-radius: 99px;
  padding: 8px 12px; display: flex; justify-content: space-around;
  box-shadow: 0 16px 50px rgba(0, 0, 0, 0.7); z-index: 9999;
}
.bottom-dock .dock-btn {
  padding: 9px 14px; border-radius: 99px; cursor: pointer; font-size: 10px; font-weight: 800;
  text-align: center; color: var(--txt-2); display: flex; flex-direction: column; align-items: center;
  gap: 4px; background: transparent; border: none; transition: all .25s var(--ease);
}
.bottom-dock .dock-btn svg { width: 20px; height: 20px; }
.bottom-dock .dock-btn:hover { color: #fff; transform: scale(1.15) translateY(-3px); }
.bottom-dock .dock-btn.active { background: var(--grad-vip); color: #fff; box-shadow: var(--shadow-neon-red); transform: translateY(-3px); }

#toast-stack { position: fixed; top: 16px; right: 16px; z-index: 99999; max-width: 340px; width: calc(100% - 32px); pointer-events: none; }
.toast {
  background: rgba(13, 23, 42, 0.98); border: 2px solid var(--neon-gold);
  border-radius: 16px; padding: 14px 18px; margin-bottom: 10px;
  box-shadow: var(--shadow-neon-gold); pointer-events: auto;
  animation: slideIn .25s var(--ease) forwards;
}
@keyframes slideIn { from { opacity: 0; transform: translateY(-15px); } to { opacity: 1; transform: translateY(0); } }
.toast.hide { animation: slideOut .25s var(--ease) forwards; }
@keyframes slideOut { to { opacity: 0; transform: translateY(-40px); } }
.toast .t-head { font-size: 11.5px; font-weight: 900; color: var(--neon-gold); display:flex; align-items:center; gap:6px; }
.toast .t-body { font-size: 11px; font-weight: 600; color: var(--txt-0); margin-top: 3px; }
"""

HTML_GATE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>RICKI VIP — Cổng Bảo Mật ❄️</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_VIP + """
body { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
.gate-card {
  background: rgba(13, 23, 42, 0.98); border: 2px solid var(--border-neon);
  border-radius: 26px; padding: 38px 26px; max-width: 410px; width: 100%; text-align: center;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.7); position: relative; z-index: 10;
}
.radar-box { width: 95px; height: 95px; margin: 0 auto 22px; position: relative; display: flex; align-items: center; justify-content: center; }
.radar-box::before {
  content: ''; position: absolute; inset: 0; border-radius: 50%;
  border: 2px solid transparent; border-top-color: var(--neon-red);
  animation: spin 1.2s linear infinite;
}
@keyframes spin { 100% { transform: rotate(360deg); } }
.radar-icon { font-size: 42px; animation: pulse 1.5s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.15); } }
.progress-line { width: 100%; height: 7px; background: rgba(255, 255, 255, 0.1); border-radius: 99px; margin: 20px 0; overflow: hidden; display: none; }
.progress-fill { width: 0%; height: 100%; background: var(--grad-vip); transition: width 0.3s; }
</style>
</head>
<body>
<canvas id="snow-canvas"></canvas>
<div class="gate-card">
  <div class="radar-box"><div class="radar-icon">👑</div></div>
  <h1 style="font-family:'Orbitron',sans-serif; font-size:18px; margin-bottom:8px; color:var(--neon-gold);">RICKI VIP 2026</h1>
  <p id="scan-status" style="font-size:12.5px; color:var(--txt-1); min-height:36px;">Hệ thống phát tán tin nhắn đa nền tảng tối thượng.</p>
  <div class="progress-line" id="p-box"><div class="progress-fill" id="p-bar"></div></div>
  <button class="btn-pill primary full" id="verify-btn" onclick="startScan()">XÁC MINH DANH TÍNH VIP ❄️</button>
</div>

<script>
var canvas = document.getElementById('snow-canvas');
var ctx = canvas.getContext('2d');
var width = canvas.width = window.innerWidth;
var height = canvas.height = window.innerHeight;
var flakes = [];
for (var i = 0; i < 85; i++) {
  flakes.push({ x: Math.random() * width, y: Math.random() * height, r: Math.random() * 3.5 + 1, d: Math.random() * 1.5 });
}
function drawSnow() {
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
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
    f.x += Math.sin(f.d) * 0.8;
    if (f.x > width + 5 || f.x < -5 || f.y > height) {
      flakes[i] = { x: Math.random() * width, y: -10, r: f.r, d: f.d };
    }
  }
  requestAnimationFrame(drawSnow);
}
drawSnow();
window.onresize = function(){ width = canvas.width = window.innerWidth; height = canvas.height = window.innerHeight; };

function startScan(){
  var btn = document.getElementById('verify-btn');
  var status = document.getElementById('scan-status');
  var pbox = document.getElementById('p-box');
  var pbar = document.getElementById('p-bar');
  btn.style.display = 'none'; pbox.style.display = 'block';

  var steps = [
    { p: 35, t: 'Đang kiểm tra chứng chỉ Ricki Vip...' },
    { p: 75, t: 'Mở khóa module mã hóa Zalo & Discord...' },
    { p: 100, t: 'Hoàn tất xác thực. Đang chuyển hướng...' }
  ];
  var i = 0;
  var iv = setInterval(function(){
    if(i < steps.length){
      pbar.style.width = steps[i].p + '%';
      status.textContent = steps[i].t;
      i++;
    } else {
      clearInterval(iv);
      fetch('/api/gate/verify', { method: 'POST' }).then(() => {
        window.location.href = '/login';
      });
    }
  }, 350);
}
</script>
</body>
</html>"""

HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Đăng Nhập — RICKI VIP ❄️</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_VIP + """
body { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
.login-card {
  background: rgba(13, 23, 42, 0.98); border: 2px solid var(--border-neon);
  border-radius: 26px; padding: 36px 28px; max-width: 400px; width: 100%; text-align: center;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.7); position: relative; z-index: 10;
}
.brand-img { width: 75px; height: 75px; border-radius: 50%; border: 3px solid var(--neon-gold); margin: 0 auto 16px; object-fit: cover; box-shadow: var(--shadow-neon-gold); }
.err-msg { background: rgba(255, 51, 68, 0.25); border: 1.5px solid var(--neon-red); color: #ff6b6b; padding: 12px; border-radius: 14px; font-size: 12px; font-weight: 800; margin-bottom: 16px; text-align: left; }
</style>
</head>
<body>
<canvas id="snow-canvas"></canvas>
<div class="login-card">
  <div style="position:relative; display:inline-block;">
    <img src="/static/logo.png" class="brand-img" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 100 100\'><circle cx=\'50\' cy=\'50\' r=\'45\' fill=\'%23ff3344\'/><text x=\'50\' y=\'62\' font-size=\'40\' text-anchor=\'middle\' fill=\'white\'>👑</text></svg>'">
  </div>
  <h1 style="font-family:'Orbitron',sans-serif; font-size:19px; margin-bottom:6px; color:var(--neon-gold);">RICKI VIP ❄️</h1>
  <p style="font-size:11.5px; color:var(--txt-1); font-weight:700; margin-bottom:24px; display:flex; align-items:center; justify-content:center; gap:6px;">
    Bản quyền: <span class="v-badge"><svg viewBox="0 0 24 24" width="15" height="15" fill="#00d4ff"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></span> Ricki Vip
  </p>

  {% if error %}
  <div class="err-msg">⚠️ {{ error }}</div>
  {% endif %}

  <form method="POST" action="/login">
    <div class="form-group" style="text-align:left;">
      <label>MẬT KHẨU BẢO MẬT VIP</label>
      <input type="password" name="password" placeholder="Nhập mật khẩu (mặc định: rickivip)" required autocomplete="current-password">
    </div>
    <button type="submit" class="btn-pill primary full" style="margin-top:12px;">ĐĂNG NHẬP HỆ THỐNG VIP 👑</button>
  </form>
</div>

<script>
var canvas = document.getElementById('snow-canvas');
var ctx = canvas.getContext('2d');
var width = canvas.width = window.innerWidth;
var height = canvas.height = window.innerHeight;
var flakes = [];
for (var i = 0; i < 85; i++) {
  flakes.push({ x: Math.random() * width, y: Math.random() * height, r: Math.random() * 3.5 + 1, d: Math.random() * 1.5 });
}
function drawSnow() {
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
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
    f.x += Math.sin(f.d) * 0.8;
    if (f.x > width + 5 || f.x < -5 || f.y > height) {
      flakes[i] = { x: Math.random() * width, y: -10, r: f.r, d: f.d };
    }
  }
  requestAnimationFrame(drawSnow);
}
drawSnow();
</script>
</body>
</html>"""

HTML_MAIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>RICKI VIP — CHIẾN HẠM PRO (MAX COMBAT) ❄️</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=JetBrains+Mono:wght@500;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_VIP + """
</style>
</head>
<body>
<canvas id="snow-canvas"></canvas>

<div class="header">
  <div class="header-inner">
    <div class="logo-box">
      <img id="header-logo" src="/static/logo.png" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 100 100\'><circle cx=\'50\' cy=\'50\' r=\'45\' fill=\'%23ff3344\'/><text x=\'50\' y=\'62\' font-size=\'40\' text-anchor=\'middle\' fill=\'white\'>👑</text></svg>'">
      <div class="header-meta">
        <h1>RICKI VIP ❄️</h1>
        <p>
          Bản quyền: <span class="v-badge"><svg viewBox="0 0 24 24" width="14" height="14" fill="#00d4ff"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></span> <b>Ricki Vip</b> (Zalo & Discord Acc)
        </p>
      </div>
    </div>
    <div>
      <a href="/logout" class="btn-pill danger" style="padding:7px 14px; font-size:10.5px;">Đăng Xuất</a>
    </div>
  </div>
</div>

<div class="container">

<div class="top-nav-bar">
  <button class="top-nav-btn active" data-tab="accounts" onclick="showTab('accounts')">
    <span class="nav-ic">👑</span><span class="nav-txt">Tài Khoản</span>
  </button>
  <button class="top-nav-btn" data-tab="boxes" onclick="showTab('boxes')">
    <span class="nav-ic">💬</span><span class="nav-txt">Hội Thoại & Nhóm</span>
  </button>
  <button class="top-nav-btn" data-tab="files" onclick="showTab('files')">
    <span class="nav-ic">📁</span><span class="nav-txt">Tập Tin (5MB+)</span>
  </button>
  <button class="top-nav-btn" data-tab="spam" onclick="showTab('spam')">
    <span class="nav-ic">⚡</span><span class="nav-txt">Gửi Tin Tự Động</span>
  </button>
  <button class="top-nav-btn" data-tab="security" onclick="showTab('security')">
    <span class="nav-ic">🛡️</span><span class="nav-txt">Bảo Mật & Anti-Ban</span>
  </button>
  <button class="top-nav-btn" data-tab="docs" onclick="showTab('docs')">
    <span class="nav-ic">📖</span><span class="nav-txt">Hướng Dẫn</span>
  </button>
</div>

  <!-- TAB 1: ACCOUNTS (ZALO & DISCORD ACC TOKEN) -->
  <div class="panel active" id="panel-accounts">
    <div class="card">
      <h2>
        <span>Thêm Tài Khoản Đa Ứng Dụng (Zalo & Discord Acc)</span>
        <button class="btn-pill dark" onclick="checkAllAccounts()" style="font-size:10.5px; padding:7px 14px;">Kiểm Tra Toàn Bộ</button>
      </h2>
      
      <div class="chip-bar" style="margin-bottom:14px;">
        <div class="chip-item active" id="chip-plat-zalo" onclick="setPlatform('zalo')">🔷 Zalo Web (Cookie + IMEI)</div>
        <div class="chip-item" id="chip-plat-discord" onclick="setPlatform('discord')">🟣 Discord (Token Tài Khoản Acc)</div>
      </div>

      <div class="form-group">
        <label>TÊN GỢI NHỚ TÀI KHOẢN</label>
        <input type="text" id="acc-label" placeholder="VD: Nick Chính Khôi, Clone 1, Acc Discord...">
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
          <label>TOKEN TÀI KHOẢN DISCORD (USER TOKEN CÁ NHÂN)</label>
          <textarea id="acc-token" placeholder="Dán mã Token tài khoản Discord cá nhân vào đây (sử dụng trực tiếp trên acc, không qua bot)..."></textarea>
        </div>
      </div>

      <button class="btn-pill primary full" onclick="addAccount()">LƯU TÀI KHOẢN MỚI 👑</button>
    </div>

    <div class="card">
      <h2><span>Danh Sách Tài Khoản Đã Kết Nối</span></h2>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>ỨNG DỤNG</th>
              <th>NHÃN</th>
              <th>DANH TÍNH THẬT</th>
              <th>TRẠNG THÁI</th>
              <th>THAO TÁC</th>
            </tr>
          </thead>
          <tbody id="acc-table-body">
            <tr><td colspan="6" style="text-align:center; padding:18px;">Đang tải...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 2: BOXES / CHANNELS (TỰ ĐỘNG GỬI CÙNG LÚC 2 APP) -->
  <div class="panel" id="panel-boxes">
    <div class="card">
      <h2><span>Hội Thoại Zalo / Kênh Discord Mục Tiêu</span></h2>
      <div class="form-group">
        <label>CHỌN TÀI KHOẢN QUÉT DỮ LIỆU</label>
        <select id="load-acc-select"><option value="">-- Chọn tài khoản --</option></select>
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:14px;">
        <button class="btn-pill green" onclick="loadBoxes()">Nạp Danh Sách</button>
        <button class="btn-pill dark" onclick="selectAllBoxes()">Chọn Tất Cả</button>
        <button class="btn-pill danger" onclick="clearAllBoxes()">Bỏ Chọn</button>
      </div>
      <div>
        <div style="font-size:11.5px; font-weight:800; color:var(--neon-gold); margin-bottom:8px;">
          ĐÃ CHỌN: <span id="selected-count" style="color:var(--neon-red); font-size:14px; font-weight:900;">0</span> HỘI THOẠI / KÊNH (TỰ ĐỘNG GỬI CÙNG LÚC)
        </div>
        <div class="box-list" id="box-list"><div style="text-align:center; padding:20px; color:var(--txt-2); font-size:12px;">Chưa nạp dữ liệu hội thoại</div></div>
      </div>
    </div>
  </div>

  <!-- TAB 3: FILES (TỐI ƯU TỆP 5MB+ SIÊU TỐC KHÔNG LAG) -->
  <div class="panel" id="panel-files">
    <div class="card">
      <h2><span>Tập Tin Văn Bản & Ảnh Logo (Hỗ Trợ Tệp Lớn 5MB+ Siêu Mượt)</span></h2>
      <input type="file" id="file-input" style="display:none;" onchange="handleFileSelected(this)">
      <label class="file-upload-label" for="file-input">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        <span id="upload-txt">Bấm để chọn tệp Văn bản (.txt dung lượng đến 10MB+) hoặc Ảnh Logo</span>
      </label>
      <div style="display:flex; gap:8px; margin-top:14px;">
        <button class="btn-pill green full" onclick="uploadFile()">TẢI LÊN TẬP TIN ⚡</button>
      </div>
    </div>

    <div class="card">
      <h2><span>Danh Sách Tập Tin Đã Lưu</span></h2>
      <div id="files-list"><div style="text-align:center; padding:18px; color:var(--txt-2); font-size:12px;">Chưa có tập tin</div></div>
    </div>
  </div>

  <!-- TAB 4: COMBAT SPAM ENGINE (TAG ALL, TAG TÊN, ICON SÁT THƯƠNG, MÀU SẮC) -->
  <div class="panel" id="panel-spam">
    <div class="card">
      <h2><span>Trung Tâm Khởi Động Gửi Tin — VIP COMBAT EDITION ❄️</span></h2>

      <div class="form-group">
        <label>1. Chế độ gửi tin</label>
        <div class="chip-bar" id="spam-mode-bar">
          <div class="chip-item active" data-mode="fast">⚡ Siêu Nhanh (Gửi từng dòng)</div>
          <div class="chip-item" data-mode="treo_ngon">📜 Treo Ngôn (N Dòng / 1 Tin)</div>
          <div class="chip-item" data-mode="treo_nhay">🔥 Treo Nhây (Bắn câu liên tục)</div>
        </div>
        <input type="hidden" id="spam-mode" value="fast">
      </div>

      <div class="form-group">
        <label>2. Chọn nguồn nội dung tin nhắn</label>
        <select id="spam-file-select" style="margin-bottom:8px;"><option value="">-- Dán nội dung trực tiếp bên dưới --</option></select>
        <textarea id="spam-messages" placeholder="Nhập nội dung tin nhắn cần gửi... (Mỗi khối ngôn cách nhau bởi 1 dòng trống)"></textarea>
      </div>

      <!-- BỘ PHỐI ICON SÁT THƯƠNG CỰC CAO CHỌC TỨC -->
      <div class="form-group" style="background:rgba(255,51,68,0.06); border:1.5px solid rgba(255,51,68,0.3); border-radius:18px; padding:16px;">
        <label style="color:var(--neon-red); font-size:12px; font-weight:900;">
          💥 BỘ PHỐI ICON SÁT THƯƠNG CỰC CAO & CHỌC TỨC ĐỐI THỦ
        </label>
        <div class="chip-bar" id="combat-icon-bar">
          <div class="chip-item active" data-ic="mixed">👑 Combo Hỗn Hợp Đồ Sát (1 Sát Thương + 1 Chọc Tức + 1 Cười Đểu)</div>
          <div class="chip-item" data-ic="damage">💀 Icon Sát Thương Cao (💀💥🔥⚡🔨🩸⚰️)</div>
          <div class="chip-item" data-ic="troll">🤡 Icon Chọc Tức / Khinh Bỉ (🤡🤫🖕💩👎🥱🐷)</div>
          <div class="chip-item" data-ic="mock">🤣 Icon Cười Đểu / Cay Cú (🤣😏🤪🤭😹👀)</div>
          <div class="chip-item" data-ic="none">Tắt Ghép Icon</div>
        </div>
        <input type="hidden" id="combat-icon-mode" value="mixed">
        <div style="display:flex; align-items:center; gap:10px; margin-top:10px;">
          <span style="font-size:11px; font-weight:800; color:var(--txt-1);">Số lượng icon ghép mỗi tin:</span>
          <select id="combat-icon-count" style="width:90px; padding:6px 10px; font-size:11.5px;">
            <option value="2">2 Icon</option>
            <option value="3" selected>3 Icon</option>
            <option value="4">4 Icon</option>
            <option value="6">6 Icon</option>
          </select>
        </div>
      </div>

      <div class="form-group">
        <label>3. Các tính năng bảo vệ VIP (Anti-Ban Đa Tầng, Anti-Die, Tag @All Chuẩn)</label>
        <div class="toggle-grid">
          <div class="toggle-item active" id="tg-antiband" onclick="tgFlag('antiband')">🛡️ Bật Anti-Ban (Hash Đa Tầng)</div>
          <div class="toggle-item active" id="tg-antidieall" onclick="tgFlag('antidieall')">🔒 Anti-Die-All (Tự Cách Ly 429)</div>
          <div class="toggle-item active" id="tg-badge" onclick="tgFlag('badge')">🎨 Huy Hiệu Màu (Hiện Mọi Thiết Bị)</div>
          <div class="toggle-item" id="tg-all" onclick="tgFlag('all')">📢 Tag @All (Tất Cả Thành Viên)</div>
          <div class="toggle-item active" id="tg-heading" onclick="tgFlag('heading')">Chữ To Tiêu Đề (#)</div>
          <div class="toggle-item active" id="tg-multi" onclick="tgFlag('multi')">Gửi Cả 2 App (Zalo & Discord)</div>
        </div>
      </div>

      <!-- VỊ TRÍ TAG @ALL -->
      <div id="tag-all-options" style="display:none; margin-bottom:14px; background:rgba(0,212,255,0.06); border:1.5px solid rgba(0,212,255,0.3); border-radius:16px; padding:12px;">
        <label style="color:var(--neon-blue); font-size:11.5px; font-weight:900;">VỊ TRÍ GẮN THẺ @ALL</label>
        <div style="display:flex; gap:16px; margin-top:6px;">
          <label style="font-size:11.5px; cursor:pointer; color:var(--txt-0); display:flex; align-items:center; gap:6px;">
            <input type="radio" name="tag_pos" value="head" checked> 🚀 Đặt ở ĐẦU tin nhắn (Khuyên dùng - Nổ thông báo ngay lập tức, 100% ăn tag)
          </label>
          <label style="font-size:11.5px; cursor:pointer; color:var(--txt-0); display:flex; align-items:center; gap:6px;">
            <input type="radio" name="tag_pos" value="tail"> 🎯 Đặt ở CUỐI tin nhắn
          </label>
        </div>
      </div>

      <div class="form-group">
        <label>4. Màu sắc chữ (Đổi màu chuẩn Zalo Group, Huy Hiệu Màu & Discord ANSI)</label>
        <div class="chip-bar" id="color-mode-bar">
          <div class="chip-item active" data-cmode="rainbow">Trộn Màu Từng Dòng (Rainbow)</div>
          <div class="chip-item" data-cmode="random">Đổi Màu Ngẫu Nhiên</div>
          <div class="chip-item" data-cmode="fixed">Cố Định 1 Màu</div>
          <div class="chip-item" data-cmode="none">Tắt Màu</div>
        </div>
        <input type="hidden" id="color-mode" value="rainbow">
        <div id="fixed-colors-wrap" style="display:none; margin-top:8px;" class="chip-bar"></div>
      </div>

      <div class="form-group">
        <label>5. Khoảng cách thời gian (giây)</label>
        <div class="chip-bar" id="delay-bar">
          <div class="chip-item active" data-val="1">1 Giây</div>
          <div class="chip-item" data-val="2">2 Giây</div>
          <div class="chip-item" data-val="3">3 Giây</div>
          <div class="chip-item" data-val="5">5 Giây</div>
          <div class="chip-item" data-val="8">8 Giây (An Toàn)</div>
        </div>
        <input type="hidden" id="delay-val" value="1">
      </div>

      <!-- MỤC QUẢN LÝ TAG THÀNH VIÊN THEO TÊN (TAG TÊN XỊN XÒ) -->
      <div class="form-group" style="background:rgba(255,255,255,0.03); border:1.5px solid var(--border-gold); border-radius:18px; padding:16px;">
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer; font-size:12.5px; color:var(--neon-gold); font-weight:900;">
          <input type="checkbox" id="tg-tag" onchange="tgTag()" style="width:18px; height:18px;">
          🏷️ BẬT CHỌN THÀNH VIÊN ZALO ĐỂ TAG THEO TÊN THẬT
        </label>
        <div id="tag-wrap" style="display:none; margin-top:14px;">
          <div class="form-group">
            <label>CHỌN NHÓM ZALO ĐỂ QUÉT THÀNH VIÊN</label>
            <select id="member-group-select" onchange="loadMembers()"><option value="">-- Chọn nhóm Zalo mục tiêu --</option></select>
          </div>
          <div class="form-group">
            <label>CHẾ ĐỘ TAG TÊN</label>
            <div style="display:flex; flex-wrap:wrap; gap:14px; margin-top:4px;">
              <label style="font-size:11.5px; cursor:pointer; color:var(--txt-1); display:flex; align-items:center; gap:6px;">
                <input type="radio" name="tag_mode" value="rotate" checked> 🔄 Tag Luân Phiên (Mỗi tin tag 1 người xoay vòng - chuẩn Nhây Tag)
              </label>
              <label style="font-size:11.5px; cursor:pointer; color:var(--txt-1); display:flex; align-items:center; gap:6px;">
                <input type="radio" name="tag_mode" value="all_at_once"> 👥 Tag Cùng Lúc (Gắn tất cả người đã chọn vào mỗi tin)
              </label>
            </div>
          </div>
          <div class="form-group">
            <label>HOẶC NHẬP DANH SÁCH TÊN CẦN TAG TRỰC TIẾP (Mỗi tên 1 dòng hoặc cách nhau dấu phẩy)</label>
            <input type="text" id="manual-tags-inp" placeholder="VD: Long Phạm, Kiên, Admin...">
          </div>
          <div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px;">
            <button class="btn-pill dark" onclick="loadMembers()">Quét & Nạp Thành Viên Nhóm</button>
            <button class="btn-pill green" onclick="selectAllMembers()">Chọn Tất Cả</button>
            <button class="btn-pill danger" onclick="clearAllMembers()">Bỏ Chọn Tất Cả</button>
          </div>
          <div class="form-group" style="margin-bottom:10px;">
            <input type="text" id="search-member-inp" placeholder="Tìm kiếm tên thành viên..." oninput="filterMembers()" style="padding:10px 14px; font-size:12px;">
          </div>
          <div style="font-size:11.5px; font-weight:800; color:var(--neon-gold); margin-bottom:8px;">
            ĐÃ CHỌN: <span id="tag-count" style="color:var(--neon-red); font-weight:900; font-size:14px;">0</span> THÀNH VIÊN
          </div>
          <div class="box-list" id="tag-selector" style="margin-top:8px; max-height:240px; display:none;"></div>
        </div>
      </div>
    </div>

    <div class="action-control-banner">
      <div style="text-align:left;">
        <div style="font-size:13px; font-weight:900; color:var(--neon-gold); display:flex; align-items:center; gap:8px;">
          <span>⚡ BẢNG ĐIỀU KHIỂN CHIẾN HẠM RICKI VIP</span>
          <span class="sec-badge">🛡️ ANTI-BAN V3 KÍCH HOẠT</span>
        </div>
        <div style="font-size:11.5px; color:var(--txt-1); margin-top:4px;">
          Khởi chạy chiến dịch tự động trên Zalo & Discord hoặc Dừng khẩn cấp toàn bộ tiến trình
        </div>
      </div>
      <div style="display:flex; align-items:center; gap:14px; flex-wrap:wrap;">
        <button class="btn-pill green" onclick="startSpam()" style="padding:14px 28px; font-size:13px; font-weight:900; box-shadow:var(--shadow-neon-green); letter-spacing:0.8px;">
          🚀 BẮT ĐẦU GỬI NGAY
        </button>
        <button class="btn-pill danger" onclick="stopAll()" style="padding:14px 22px; font-size:12px; font-weight:900; box-shadow:var(--shadow-neon-red);">
          🛑 DỪNG TẤT CẢ
        </button>
      </div>
    </div>

    <div class="card">
      <h2><span>Tiến Trình Đang Chạy</span></h2>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>MÃ TIẾN TRÌNH</th>
              <th>CHẾ ĐỘ</th>
              <th>TRẠNG THÁI</th>
              <th>HÀNH ĐỘNG</th>
            </tr>
          </thead>
          <tbody id="task-table-body">
            <tr><td colspan="4" style="text-align:center; padding:14px;">Chưa có tiến trình nào</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 5: HƯỚNG DẪN TOKEN DISCORD USER & ANTI-DIE -->
  <div class="panel" id="panel-docs">
    <div class="card">
      <h2><span>Hướng Dẫn Lấy Token Discord Cá Nhân (Sài Lên Thẳng Acc - Không Dùng Bot)</span></h2>
      
      <div style="line-height:1.75; font-size:13px; color:var(--txt-1);">
        <h3 style="color:var(--neon-gold); font-size:15px; margin-top:8px; margin-bottom:8px;">Cách Lấy Token Tài Khoản Discord Cá Nhân (Self-Bot Token)</h3>
        <ol style="padding-left:20px; margin-bottom:16px;">
          <li>Mở Discord trên trình duyệt (Chrome, Cốc Cốc, Brave, Kiwi Browser) tại <a href="https://discord.com/app" target="_blank" style="color:var(--neon-blue); font-weight:bold;">discord.com/app</a> và đăng nhập tài khoản của bạn.</li>
          <li>Nhấn phím <b>F12</b> (hoặc chuột phải chọn <b>Kiểm tra / Inspect</b>) ➔ Chuyển sang tab <b>Network (Mạng)</b>.</li>
          <li>Tại ô tìm kiếm (Filter), nhập <code>/api</code>.</li>
          <li>Bấm vào một kênh chat bất kỳ hoặc gửi 1 tin nhắn ngắn bất kỳ.</li>
          <li>Nhấp vào một gói tin xuất hiện trong bảng mạng (ví dụ: <code>messages</code> hoặc <code>science</code>) ➔ Kéo xuống phần <b>Request Headers</b>.</li>
          <li>Tìm dòng có tên <b>Authorization</b> ➔ Sao chép toàn bộ chuỗi ký tự phía sau ➔ Đó chính là Token tài khoản Discord của bạn.</li>
          <li>Dán vào tab <b>Tài khoản</b> trên hệ thống VIP. Hệ thống sẽ tự động đăng nhập và gửi tin trực tiếp dưới danh nghĩa tài khoản của bạn.</li>
        </ol>

        <h3 style="color:var(--neon-red); font-size:15px; margin-top:14px; margin-bottom:8px;">⚠️ 5 Nguyên Tắc Giữ Token Discord An Toàn Tuyệt Đối (Anti-Die)</h3>
        <ul style="padding-left:20px;">
          <li><b>1. Luôn Bật Anti-Ban Đa Tầng:</b> Hệ thống tự động chèn zero-width hash làm thay đổi hoàn toàn mã checksum của từng gói tin gửi đi, tránh bị AutoMod của Discord phát hiện tin trùng.</li>
          <li><b>2. Luôn Bật Anti-Die-All:</b> Khi tài khoản chạm giới hạn tần suất (HTTP 429), hệ thống tự động cho tài khoản nghỉ xả hơi (Cool-down) đúng theo thời gian phạt của Discord rồi mới tiếp tục, không bao giờ spam dồn dập khiến Discord gắn cờ tài khoản.</li>
          <li><b>3. Độ trễ khuyến nghị:</b> Nên đặt delay từ 3 - 6 giây/tin để mô phỏng chính xác thao tác người dùng thật.</li>
          <li><b>4. Sử dụng Clone:</b> Nên chạy tài khoản phụ/clone khi war hoặc combat.</li>
          <li><b>5. Bảo mật mã Token:</b> Không gửi token cho người khác hoặc để lộ công khai.</li>
        </ul>
      </div>
    </div>
  </div>
</div>

<!-- DOCK NAVIGATION PHÁT QUANG NEON -->
<div class="bottom-dock">
  <button class="dock-btn active" data-tab="accounts" onclick="showTab('accounts')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
    <span>Tài khoản</span>
  </button>
  <button class="dock-btn" data-tab="boxes" onclick="showTab('boxes')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
    <span>Hội thoại</span>
  </button>
  <button class="dock-btn" data-tab="files" onclick="showTab('files')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
    <span>Tập tin</span>
  </button>
  <button class="dock-btn" data-tab="spam" onclick="showTab('spam')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
    <span>Gửi tin</span>
  </button>
  <button class="dock-btn" data-tab="docs" onclick="showTab('docs')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
    <span>HD Token</span>
  </button>
</div>

<div id="toast-stack"></div>

<script>
// ==================== TUYẾT RƠI VIP 60FPS ====================
var canvas = document.getElementById('snow-canvas');
var ctx = canvas.getContext('2d');
var width = canvas.width = window.innerWidth;
var height = canvas.height = window.innerHeight;
var flakes = [];
for (var i = 0; i < 95; i++) {
  flakes.push({
    x: Math.random() * width,
    y: Math.random() * height,
    r: Math.random() * 3.8 + 0.8,
    d: Math.random() * 1.5,
    speed: Math.random() * 1.2 + 0.6
  });
}
function drawSnow() {
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
  ctx.beginPath();
  for (var i = 0; i < flakes.length; i++) {
    var f = flakes[i];
    ctx.moveTo(f.x, f.y);
    ctx.arc(f.x, f.y, f.r, 0, Math.PI * 2, true);
  }
  ctx.fill();
  for (var i = 0; i < flakes.length; i++) {
    var f = flakes[i];
    f.y += Math.cos(f.d) + f.speed + f.r / 3;
    f.x += Math.sin(f.d) * 0.8;
    if (f.x > width + 5 || f.x < -5 || f.y > height) {
      flakes[i] = { x: Math.random() * width, y: -10, r: f.r, d: f.d, speed: f.speed };
    }
  }
  requestAnimationFrame(drawSnow);
}
drawSnow();
window.onresize = function(){ width = canvas.width = window.innerWidth; height = canvas.height = window.innerHeight; };

// ==================== BIẾN TRẠNG THÁI ====================
var flags = { antiband: true, antidieall: true, heading: true, multi: true, all: false, badge: true };
var selectedBoxes = [];
var selectedTags = [];
var _boxes = [];
var _members = [];
var currentMode = "fast";
var colorMode = "rainbow";
var fixedColor = "red";
var currentPlatform = "zalo";
var ZALO_PALETTE = [];

// TOAST THÔNG MINH
var Toast = (function(){
  var stack = null;
  function ensure(){ if(!stack) stack = document.getElementById('toast-stack'); }
  function show(title, msg, timeout){
    ensure();
    var t = document.createElement('div');
    t.className = 'toast';
    t.innerHTML = `<div class="t-head"><span>👑</span><span>${title}</span></div><div class="t-body">${msg}</div>`;
    stack.appendChild(t);
    setTimeout(() => {
      t.classList.add('hide');
      setTimeout(() => { if(t.parentNode) t.parentNode.removeChild(t); }, 300);
    }, timeout || 3200);
  }
  return {
    success: (m) => show('Thành Công', m, 3200),
    error: (m) => show('Thông Báo Lỗi', m, 4500),
    info: (m) => show('Thông Tin', m, 2800)
  };
})();

function showTab(name){
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.top-nav-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.dock-btn').forEach(b => b.classList.remove('active'));
  
  var p = document.getElementById('panel-' + name);
  if(p) p.classList.add('active');
  
  var tb = document.querySelector(`.top-nav-btn[data-tab="${name}"]`);
  if(tb) tb.classList.add('active');
  
  var db = document.querySelector(`.dock-btn[data-tab="${name}"]`);
  if(db) db.classList.add('active');

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// BẢO VỆ CHỐNG SOI MÃ F12 & CHUỘT PHẢI
var inspectDefenseActive = false;
function tgInspectDefense(){
  inspectDefenseActive = !inspectDefenseActive;
  var btn = document.getElementById('btn-inspect-def');
  if(inspectDefenseActive){
    if(btn){ btn.textContent = 'ĐANG BẬT BẢO VỆ 🔒'; btn.className = 'btn-pill green'; }
    document.addEventListener('contextmenu', blockContextMenu);
    document.addEventListener('keydown', blockDevKeys);
    Toast.success('Đã KÍCH HOẠT bảo vệ chống soi mã và chặn F12!');
  } else {
    if(btn){ btn.textContent = 'BẬT BẢO VỆ F12 🔒'; btn.className = 'btn-pill dark'; }
    document.removeEventListener('contextmenu', blockContextMenu);
    document.removeEventListener('keydown', blockDevKeys);
    Toast.info('Đã tắt chế độ chặn F12.');
  }
}
function blockContextMenu(e){ e.preventDefault(); Toast.info('Hệ thống Ricki Vip đã khóa chuột phải để bảo vệ bản quyền.'); }
function blockDevKeys(e){
  if(e.keyCode === 123 || (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 74)) || (e.ctrlKey && e.keyCode === 85)){
    e.preventDefault();
    Toast.error('Phím tắt nhà phát triển bị vô hiệu hóa bởi Ricki Vip Armor.');
  }
}

// TEST TRỰC TIẾP ANTI-BAN V3 TRÊN GIAO DIỆN
async function testAntibandLive(){
  var inp = document.getElementById('test-antiband-inp').value.trim();
  if(!inp) return Toast.error('Vui lòng nhập nội dung muốn kiểm tra');
  Toast.info('Đang phân tích mã băm Anti-Ban V3...');
  var res = await api('/api/security/test_antiband', { method: 'POST', body: JSON.stringify({ text: inp }) });
  if(res.error) return Toast.error(res.error);
  var box = document.getElementById('test-antiband-res');
  box.style.display = 'block';
  box.innerHTML = `
    <div style="color:var(--neon-green); font-weight:bold; margin-bottom:6px;">✅ PHÂN TÍCH ANTI-BAN V3 HOÀN TẤT:</div>
    <div><b>Văn bản gốc:</b> "${res.original}"</div>
    <div style="color:var(--txt-2); word-break:break-all;"><b>SHA256 gốc:</b> ${res.orig_sha256}</div>
    <div style="margin-top:6px; color:var(--neon-gold);"><b>Văn bản sau bảo vệ:</b> "${res.processed}" (Mắt thường đọc chuẩn 100%)</div>
    <div style="color:var(--neon-blue); word-break:break-all;"><b>SHA256 mới:</b> ${res.proc_sha256}</div>
    <div style="margin-top:6px; color:#00ff88;"><b>Trạng thái:</b> Mã băm thay đổi 100% | Phông chữ tiếng Việt nguyên vẹn không bị lỗi!</div>
  `;
}


function setPlatform(plat){
  currentPlatform = plat;
  document.getElementById('chip-plat-zalo').classList.toggle('active', plat === 'zalo');
  document.getElementById('chip-plat-discord').classList.toggle('active', plat === 'discord');
  document.getElementById('form-zalo').style.display = (plat === 'zalo') ? 'block' : 'none';
  document.getElementById('form-discord').style.display = (plat === 'discord') ? 'block' : 'none';
}

function tgFlag(name){
  flags[name] = !flags[name];
  var el = document.getElementById('tg-' + name);
  if(el) el.classList.toggle('active', flags[name]);
  if(name === 'all') {
    document.getElementById('tag-all-options').style.display = flags.all ? 'block' : 'none';
    if(flags.all) Toast.success('Đã BẬT Tag @All! Vị trí: ĐẦU tin nhắn (Nổ thông báo ngay)');
    else Toast.info('Đã TẮT Tag @All.');
  }
}

function tgTag(){
  var c = document.getElementById('tg-tag');
  document.getElementById('tag-wrap').style.display = c.checked ? 'block' : 'none';
  if(c.checked) updateMemberGroupSelect();
}

function updateMemberGroupSelect(){
  var s = document.getElementById('member-group-select');
  var groups = _boxes.filter(b => b.type === 'group');
  if(!groups.length) groups = selectedBoxes.filter(b => b.type === 'group');
  var html = '<option value="">-- Chọn nhóm Zalo mục tiêu --</option>';
  groups.forEach(g => {
    html += `<option value="${g.id}">${g.name} (${g.id})</option>`;
  });
  s.innerHTML = html;
  if(groups.length > 0) s.value = groups[0].id;
}

// BỘ CHỌN CHẾ ĐỘ
document.querySelectorAll('#spam-mode-bar .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#spam-mode-bar .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    currentMode = c.dataset.mode;
    document.getElementById('spam-mode').value = currentMode;
  });
});

document.querySelectorAll('#combat-icon-bar .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#combat-icon-bar .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    document.getElementById('combat-icon-mode').value = c.dataset.ic;
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
    document.getElementById('delay-val').value = c.dataset.val;
  });
});

function handleFileSelected(input){
  if(input.files && input.files.length > 0){
    document.getElementById('upload-txt').textContent = "Đã chọn: " + input.files[0].name + " (" + Math.round(input.files[0].size/1024) + " KB)";
    document.getElementById('upload-txt').style.color = "var(--neon-gold)";
  }
}

async function api(url, opts = {}){
  try {
    var r = await fetch(url, Object.assign({}, opts, {
      headers: Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {})
    }));
    return await r.json();
  } catch(e) {
    return { error: 'Không thể kết nối đến máy chủ' };
  }
}

// ==================== TÀI KHOẢN (ACCOUNTS) ====================
async function loadAccounts(){
  var accs = await api('/api/accounts');
  if(!Array.isArray(accs)) accs = [];
  var tb = document.getElementById('acc-table-body');
  tb.innerHTML = accs.map(a => {
    var platIcon = (a.platform === 'discord') ? '🟣 Discord Acc' : '🔷 Zalo Web';
    var realName = a.real_name || (a.platform === 'discord' ? 'Discord User' : 'Chưa quét danh tính');
    var isLive = (a.status === 'live');
    var badge = isLive ? '<span class="status-badge live" style="color:var(--neon-green); font-weight:900;">● HOẠT ĐỘNG</span>' : '<span class="status-badge dead" style="color:var(--neon-red); font-weight:900;">● NGẮT KẾT NỐI</span>';
    return `<tr>
      <td>${a.id}</td>
      <td><b>${platIcon}</b></td>
      <td><b>${a.label}</b></td>
      <td><span style="color:var(--neon-gold); font-weight:800;">${realName}</span></td>
      <td id="status-${a.id}">${badge}</td>
      <td>
        <button class="btn-pill light" onclick="checkAccount(${a.id})" style="padding:5px 12px; font-size:10px;">Kiểm Tra</button>
        <button class="btn-pill danger" onclick="deleteAccount(${a.id})" style="padding:5px 12px; font-size:10px;">Xóa</button>
      </td>
    </tr>`;
  }).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--txt-2); padding:18px;">Chưa có tài khoản nào</td></tr>';

  var s1 = document.getElementById('load-acc-select');
  var opts = '<option value="">-- Chọn tài khoản --</option>' + accs.map(a => `<option value="${a.id}">[${a.platform.toUpperCase()}] ${a.label}</option>`).join('');
  s1.innerHTML = opts;
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
  var r = await api(`/api/accounts/${aid}/check`, { method: 'POST' });
  var el = document.getElementById(`status-${aid}`);
  if(r.ok){
    if(el) el.innerHTML = '<span class="status-badge live" style="color:var(--neon-green); font-weight:900;">● HOẠT ĐỘNG</span>';
    Toast.success('Tài khoản hoạt động rất tốt!');
  } else {
    if(el) el.innerHTML = '<span class="status-badge dead" style="color:var(--neon-red); font-weight:900;">● NGẮT KẾT NỐI</span>';
    Toast.error('Kết nối thất bại: ' + (r.error || 'Token/Cookie hết hạn'));
  }
}

async function checkAllAccounts(){
  Toast.info('Đang kiểm tra toàn bộ...');
  var r = await api('/api/accounts/check_all', { method: 'POST' });
  Toast.success(`Hoàn tất: ${r.live || 0} hoạt động / ${r.total || 0} tài khoản`);
  loadAccounts();
}

async function deleteAccount(aid){
  if(!confirm('Xác nhận xóa tài khoản này?')) return;
  await api(`/api/accounts/${aid}`, { method: 'DELETE' });
  Toast.info('Đã xóa tài khoản');
  loadAccounts();
}

// ==================== HỘI THOẠI & KÊNH ====================
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
  `).join('') || '<div style="text-align:center; padding:16px;">Không tìm thấy hội thoại</div>';
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

// ==================== QUẢN LÝ THÀNH VIÊN & TAG TÊN ====================
function renderMemberItems(){
  var sel = document.getElementById('tag-selector');
  var query = (document.getElementById('search-member-inp').value || '').toLowerCase().trim();
  var filtered = _members.filter(m => !query || m.name.toLowerCase().includes(query) || m.id.includes(query));

  sel.innerHTML = filtered.map((m, i) => {
    var isSel = selectedTags.some(t => t.id === m.id);
    return `<div class="box-item ${isSel ? 'selected' : ''}" onclick="toggleMemberById('${m.id}')">
      <div class="check-mark">✓</div>
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
  var gid = document.getElementById('member-group-select').value;
  if(!gid){
    var box = selectedBoxes.find(b => b.type === 'group');
    if(box) gid = box.id;
  }
  if(!gid) return Toast.error('Vui lòng chọn 1 nhóm Zalo để quét thành viên');

  Toast.info('Đang nạp danh sách thành viên nhóm...');
  var r = await api('/api/members/' + gid, { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  _members = r.members || [];
  selectedTags = [];
  document.getElementById('tag-count').textContent = '0';
  document.getElementById('tag-selector').style.display = 'block';
  renderMemberItems();
  Toast.success('Đã nạp thành công ' + _members.length + ' thành viên!');
}

// ==================== TẬP TIN (XỬ LÝ TỆP LỚN 5MB+) ====================
async function uploadFile(){
  var inp = document.getElementById('file-input');
  if(!inp.files || !inp.files.length) return Toast.error('Vui lòng chọn tệp văn bản .txt');
  var fd = new FormData();
  fd.append('file', inp.files[0]);
  Toast.info('Đang tải lên và xử lý tệp tin...');
  var r = await fetch('/api/files/upload', { method: 'POST', body: fd }).then(x => x.json());
  if(r.error) return Toast.error(r.error);
  Toast.success('Đã lưu thành công: ' + r.lines + ' khối nội dung!');
  inp.value = '';
  document.getElementById('upload-txt').textContent = "Nhấn để chọn tệp Văn bản (.txt) hoặc Ảnh Logo";
  loadFiles();
}

async function loadFiles(){
  var files = await api('/api/files');
  if(!Array.isArray(files)) files = [];
  var list = document.getElementById('files-list');
  list.innerHTML = files.map(f => `
    <div class="box-item" style="justify-content:space-between;">
      <div><div class="b-title">${f.filename}</div><div class="b-sub">${f.lines} khối | ${Math.round(f.size/1024)} KB</div></div>
      <button class="btn-pill danger" onclick="deleteFile(${f.id})" style="padding:5px 12px; font-size:10px;">Xóa</button>
    </div>
  `).join('') || '<div style="text-align:center; padding:16px; color:var(--txt-2);">Chưa có tập tin nào</div>';
  var s = document.getElementById('spam-file-select');
  s.innerHTML = '<option value="">-- Dán nội dung trực tiếp bên dưới --</option>' + files.map(f => `<option value="${f.id}">${f.filename} (${f.lines} khối - ${Math.round(f.size/1024)}KB)</option>`).join('');
}

async function deleteFile(fid){
  await api('/api/files/' + fid, { method: 'DELETE' });
  Toast.info('Đã xóa tập tin');
  loadFiles();
}

// ==================== BẮT ĐẦU SPAM ENGINE ====================
async function startSpam(){
  if(!selectedBoxes.length) return Toast.error('Chưa chọn hội thoại hoặc kênh nhận tin! Hãy qua tab Hội thoại để chọn.');
  var fid = document.getElementById('spam-file-select').value;
  var direct = document.getElementById('spam-messages').value.trim();
  if(!fid && !direct) return Toast.error('Vui lòng nhập nội dung hoặc chọn tập tin');

  var delay = parseFloat(document.getElementById('delay-val').value) || 1.0;
  var combatIconMode = document.getElementById('combat-icon-mode').value;
  var combatIconCount = parseInt(document.getElementById('combat-icon-count').value) || 3;

  var tagUsers = document.getElementById('tg-tag').checked ? selectedTags.slice() : [];
  var manualTags = document.getElementById('manual-tags-inp').value.trim();
  if(manualTags){
    var rawNames = manualTags.split(/[,\n]/).map(x => x.trim()).filter(Boolean);
    rawNames.forEach((nm, idx) => {
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
  Toast.success('Khởi chạy tiến trình VIP thành công!');
  loadTasks();
}

async function loadTasks(){
  var tasks = await api('/api/tasks');
  if(!Array.isArray(tasks)) tasks = [];
  var tb = document.getElementById('task-table-body');
  tb.innerHTML = tasks.map(t => {
    var running = (t.status === 'running');
    return `<tr>
      <td><code>${t.id}</code></td>
      <td><b>${t.type}</b></td>
      <td>${running ? '<span class="status-badge live" style="color:var(--neon-green); font-weight:900;">Đang gửi</span>' : '<span class="status-badge dead" style="color:var(--neon-red); font-weight:900;">Đã dừng</span>'}</td>
      <td>${running ? `<button class="btn-pill danger" onclick="stopTask('${t.id}')" style="padding:5px 12px; font-size:10px;">Dừng</button>` : ''}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="4" style="text-align:center; padding:14px; color:var(--txt-2);">Không có tiến trình</td></tr>';
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

async function loadColors(){
  var cols = await api('/api/colors');
  if(Array.isArray(cols)){
    ZALO_PALETTE = cols;
    var wrap = document.getElementById('fixed-colors-wrap');
    wrap.innerHTML = cols.map(c => `<div class="chip-item ${c.id === fixedColor ? 'active' : ''}" id="fc-${c.id}" style="border-color:${c.hex}; color:${c.hex};" onclick="setFixedColor('${c.id}')">${c.badge} ${c.name}</div>`).join('');
  }
}

function setFixedColor(cid){
  fixedColor = cid;
  document.querySelectorAll('#fixed-colors-wrap .chip-item').forEach(x => x.classList.remove('active'));
  var el = document.getElementById('fc-' + cid);
  if(el) el.classList.add('active');
  var col = ZALO_PALETTE.find(c => c.id === cid);
  if(col) Toast.info('Đã chọn: ' + col.name);
}

// KHỞI ĐỘNG HỆ THỐNG
window.addEventListener('DOMContentLoaded', () => {
  loadAccounts();
  loadFiles();
  loadTasks();
  loadColors();
  setInterval(loadTasks, 4000);
});
</script>
</body>
</html>"""

# ============================================================
# CÁC ROUTE FLASK WEB SERVER
# ============================================================
@app.route("/")
def page_root():
    if session.get("logged_in"):
        return render_template_string(HTML_MAIN)
    return redirect(url_for("page_gate"))


@app.route("/gate")
def page_gate():
    return render_template_string(HTML_GATE)


@app.route("/api/gate/verify", methods=["POST"])
def api_gate_verify():
    session["gate_passed"] = True
    return jsonify({"ok": True})


@app.route("/login", methods=["GET", "POST"])
def page_login():
    error = None
    ip = get_client_ip()
    now = time.time()

    tracker = login_fail_tracker[ip]
    if now < tracker["locked_until"]:
        rem = int(tracker["locked_until"] - now)
        return render_template_string(HTML_LOGIN, error=f"Bạn đã nhập sai quá nhiều lần. Khóa {rem}s.")

    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == APP_PASSWORD:
            session["logged_in"] = True
            tracker["count"] = 0
            return redirect(url_for("page_root"))
        else:
            tracker["count"] += 1
            if tracker["count"] >= LOGIN_MAX_FAILS:
                tracker["locked_until"] = now + LOGIN_LOCKOUT_TIME
                error = "Sai mật khẩu 5 lần. Tạm khóa 15 phút."
            else:
                rem = LOGIN_MAX_FAILS - tracker["count"]
                error = f"Mật khẩu không đúng! Còn {rem} lần thử."

    return render_template_string(HTML_LOGIN, error=error)


@app.route("/logout")
def page_logout():
    session.clear()
    return redirect(url_for("page_login"))


@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.route("/api/upload_logo", methods=["POST"])
@login_required
def api_upload_logo():
    f = request.files.get("logo")
    if not f: return jsonify({"error": "Không có tệp"}), 400
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


@app.route("/api/accounts", methods=["POST"])
@login_required
def api_add_account():
    d = request.json or {}
    label = d.get("label", "").strip()
    plat = d.get("platform", "zalo")

    if not label: return jsonify({"error": "Thiếu nhãn tài khoản"}), 400

    real_name = None
    avatar = None
    status = "unknown"

    if plat == "zalo":
        imei = d.get("imei", "").strip()
        cookies_raw = d.get("cookies", "").strip()
        if not imei or not cookies_raw:
            return jsonify({"error": "Thiếu IMEI hoặc Cookie Zalo"}), 400
        try:
            cookies = json.loads(cookies_raw)
            if isinstance(cookies, list):
                cookies = {c["name"]: c["value"] for c in cookies if "name" in c and "value" in c}
        except Exception:
            try:
                cookies = dict(item.split("=", 1) for item in cookies_raw.split("; ") if "=" in item)
            except Exception:
                return jsonify({"error": "Định dạng Cookie Zalo không hợp lệ"}), 400

        try:
            z = Zalo(imei, cookies)
            real_name = z.display_name or z.zalo_name
            status = "live"
        except Exception as e:
            status = "dead"
            return jsonify({"error": f"Đăng nhập Zalo thất bại: {e}"}), 400

        conn = db()
        conn.execute(
            "INSERT INTO accounts (label, platform, imei, cookies, real_name, avatar, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (label, plat, imei, json.dumps(cookies), real_name, avatar, status, time.time())
        )
        conn.commit()
        conn.close()

    else:
        # DISCORD USER TOKEN
        token = d.get("token", "").strip()
        if not token: return jsonify({"error": "Thiếu Discord Token tài khoản"}), 400

        try:
            client = DiscordUserClient(token)
            if not client.check():
                return jsonify({"error": "Token Discord không hợp lệ hoặc đã hết hạn"}), 400
            real_name = client.user_info.get("global_name") or client.user_info.get("username")
            status = "live"
        except Exception as e:
            return jsonify({"error": f"Lỗi Discord: {e}"}), 400

        conn = db()
        conn.execute(
            "INSERT INTO accounts (label, platform, token, real_name, avatar, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (label, plat, token, real_name, avatar, status, time.time())
        )
        conn.commit()
        conn.close()

    return jsonify({"ok": True})


@app.route("/api/accounts/<int:aid>/check", methods=["POST"])
@login_required
def api_check_account(aid):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Không tìm thấy tài khoản"}), 404

    plat = row["platform"] or "zalo"
    ok = False
    err = None

    if plat == "zalo":
        try:
            cookies = json.loads(row["cookies"])
            z = Zalo(row["imei"], cookies)
            conn.execute("UPDATE accounts SET status = 'live', real_name = ? WHERE id = ?", (z.display_name, aid))
            ok = True
        except Exception as e:
            conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
            err = str(e)
    else:
        try:
            client = DiscordUserClient(row["token"])
            if client.check():
                name = client.user_info.get("global_name") or client.user_info.get("username")
                conn.execute("UPDATE accounts SET status = 'live', real_name = ? WHERE id = ?", (name, aid))
                ok = True
            else:
                conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
                err = "Token không hợp lệ"
        except Exception as e:
            conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
            err = str(e)

    conn.commit()
    conn.close()
    return jsonify({"ok": ok, "error": err})


@app.route("/api/accounts/check_all", methods=["POST"])
@login_required
def api_check_all_accounts():
    conn = db()
    rows = conn.execute("SELECT id FROM accounts").fetchall()
    conn.close()
    live_count = 0
    for r in rows:
        res = api_check_account(r["id"]).get_json()
        if res.get("ok"): live_count += 1
    return jsonify({"live": live_count, "total": len(rows)})


@app.route("/api/accounts/<int:aid>", methods=["DELETE"])
@login_required
def api_delete_account(aid):
    conn = db()
    conn.execute("DELETE FROM accounts WHERE id = ?", (aid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


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
            grps = z.groups()
            frs = z.friends()
            boxes = grps + frs
        else:
            client = DiscordUserClient(row["token"])
            # Lấy danh sách server
            guilds = client.get_guilds()
            for g in guilds:
                channels = client.get_channels(g["id"])
                for ch in channels:
                    boxes.append({
                        "id": str(ch["id"]),
                        "name": f"🏰 {g['name']} ➔ #{ch['name']}",
                        "type": "discord_channel"
                    })
            # Lấy danh sách DM
            dms = client.get_dm_channels()
            for dm in dms:
                dm_recips = dm.get("recipients", [])
                dm_name = ", ".join([r.get("global_name") or r.get("username") for r in dm_recips]) or "DM Discord"
                boxes.append({
                    "id": str(dm["id"]),
                    "name": f"💬 DM: {dm_name}",
                    "type": "discord_channel"
                })
        return jsonify({"ok": True, "boxes": boxes})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/members/<group_id>", methods=["GET", "POST"])
@login_required
def api_load_group_members(group_id):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE platform = 'zalo' AND enabled = 1 ORDER BY id ASC LIMIT 1").fetchone()
    conn.close()
    if not row: return jsonify({"error": "Không tìm thấy tài khoản Zalo khả dụng nào"}), 404
    try:
        z = Zalo(row["imei"], json.loads(row["cookies"]))
        members = z.get_members_full(group_id)
        return jsonify({"ok": True, "members": members})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ============================================================
# API XỬ LÝ TỆP TIN 5MB+ BẰNG BUFFER STREAMING SIÊU TỐC
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
        return jsonify({"error": "Vui lòng chọn tệp tin"}), 400

    fn = f.filename
    safe = str(int(time.time())) + "_" + fn
    fp = os.path.join(UPLOAD_DIR, safe)
    f.save(fp)

    # Đếm số dòng / khối theo luồng stream O(1) RAM (không làm lag máy)
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
    conn.execute("INSERT INTO files (filename, filepath, lines, size, uploaded_at) VALUES (?, ?, ?, ?, ?)",
                 (fn, fp, block_count, sz, time.time()))
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "filename": fn, "lines": block_count, "size": sz})


@app.route("/api/files/<int:fid>", methods=["DELETE"])
@login_required
def api_files_delete(fid):
    conn = db()
    r = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    if r and os.path.exists(r["filepath"]):
        try: os.remove(r["filepath"])
        except Exception: pass
    conn.execute("DELETE FROM files WHERE id = ?", (fid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ============================================================
# ENGINE KHỞI CHẠY TIẾN TRÌNH SPAM TỐI THƯỢNG (ZALO & DISCORD)
# ============================================================
ACTIVE_TASKS = {}


def new_tid(prefix="vip"):
    return f"{prefix}_{int(time.time())}_{random.randint(100, 999)}"


def single_acc_worker(acc_dict, targets, file_path, direct_blocks, delay,
                      combat_icon_mode, combat_icon_count,
                      tag_users, tag_all, is_heading, mode, color_mode, fixed_color,
                      stop_ev, counter, lock, antiband=True, antidieall=True,
                      use_badge=True, tag_mode="rotate", tag_pos="head"):
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
            client = DiscordUserClient(token)
            if not client.check():
                raise Exception("Token Discord hết hạn")
        except Exception as e:
            print(f"Lỗi đăng nhập Discord #{acc_id}: {e}")
            HEALTH_MGR.report_error(acc_id)
            return

    # Khởi tạo stream reader nếu có file_path (xử lý 5MB+ siêu mượt)
    stream_reader = FastFileBlockReader(file_path) if file_path and os.path.exists(file_path) else None

    t_idx = 0
    b_idx = 0
    color_counter = 0
    mention_counter = 0

    while not stop_ev.is_set():
        if not targets:
            break

        if antidieall and not HEALTH_MGR.is_usable(acc_id):
            time.sleep(2)
            continue

        target = targets[t_idx % len(targets)]
        t_idx += 1
        target_type = target.get("type", "group")
        target_id = target.get("id")

        is_discord_target = (target_type == "discord_channel")
        # Phân luồng: Zalo gửi đích Zalo, Discord gửi đích Discord
        if (plat == "zalo" and is_discord_target) or (plat == "discord" and not is_discord_target):
            continue

        is_group = (target_type == "group")

        # Lấy nội dung khối tiếp theo
        if stream_reader:
            raw = stream_reader.next_block()
            if not raw:
                break
        else:
            if not direct_blocks:
                break
            raw = direct_blocks[b_idx % len(direct_blocks)]
            b_idx += 1

        try:
            # Tạo icon sát thương cao chọc tức nếu được bật
            icon_str = ""
            if combat_icon_mode != "none":
                icon_str = " " + generate_combat_combo(combat_icon_mode, combat_icon_count)

            if mode == "treo_ngon":
                text = raw.replace("\r\n", "\n").replace("\r", "\n") + icon_str

                if plat == "zalo":
                    client.send_adv(text, target_id, color_mode=color_mode, fixed_color=fixed_color,
                                    is_group=is_group, mentions=(tag_users if is_group else None),
                                    tag_all=(tag_all if is_group else False), is_heading=is_heading,
                                    color_offset=color_counter, antiband=antiband,
                                    use_badge=use_badge, tag_mode=tag_mode,
                                    mention_index=mention_counter, tag_pos=tag_pos)
                else:
                    discord_text = text
                    if tag_all:
                        discord_text = "@everyone " + discord_text
                    if tag_users:
                        if tag_mode == "rotate":
                            u = tag_users[mention_counter % len(tag_users)]
                            discord_text = (f"<@{u['id']}> " if not u['id'].startswith('manual_') else f"@{u['name']} ") + discord_text
                        else:
                            tags_d = " ".join([(f"<@{u['id']}>" if not u['id'].startswith('manual_') else f"@{u['name']}") for u in tag_users])
                            discord_text = tags_d + " " + discord_text

                    client.send_message(target_id, discord_text, color_mode=color_mode,
                                        fixed_color=fixed_color, antiband=antiband)

                color_counter += 1
                mention_counter += 1
                with lock: counter["sent"] += 1
                HEALTH_MGR.report_success(acc_id)

            elif mode == "treo_nhay":
                lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
                for ln in lines:
                    if stop_ev.is_set(): break
                    msg_line = ln + icon_str

                    if plat == "zalo":
                        client.send_adv(msg_line, target_id, color_mode=color_mode, fixed_color=fixed_color,
                                        is_group=is_group, mentions=(tag_users if is_group else None),
                                        tag_all=(tag_all if is_group else False), is_heading=is_heading,
                                        color_offset=color_counter, antiband=antiband,
                                        use_badge=use_badge, tag_mode=tag_mode,
                                        mention_index=mention_counter, tag_pos=tag_pos)
                    else:
                        discord_text = msg_line
                        if tag_all:
                            discord_text = "@everyone " + discord_text
                        if tag_users:
                            if tag_mode == "rotate":
                                u = tag_users[mention_counter % len(tag_users)]
                                discord_text = (f"<@{u['id']}> " if not u['id'].startswith('manual_') else f"@{u['name']} ") + discord_text
                            else:
                                tags_d = " ".join([(f"<@{u['id']}>" if not u['id'].startswith('manual_') else f"@{u['name']}") for u in tag_users])
                                discord_text = tags_d + " " + discord_text

                        client.send_message(target_id, discord_text, color_mode=color_mode,
                                            fixed_color=fixed_color, antiband=antiband)

                    color_counter += 1
                    mention_counter += 1
                    with lock: counter["sent"] += 1
                    HEALTH_MGR.report_success(acc_id)
                    time.sleep(0.35)

            else: # fast
                text = raw + icon_str

                if plat == "zalo":
                    client.send_adv(text, target_id, color_mode=color_mode, fixed_color=fixed_color,
                                    is_group=is_group, mentions=(tag_users if is_group else None),
                                    tag_all=(tag_all if is_group else False), is_heading=is_heading,
                                    color_offset=color_counter, antiband=antiband,
                                    use_badge=use_badge, tag_mode=tag_mode,
                                    mention_index=mention_counter, tag_pos=tag_pos)
                else:
                    discord_text = text
                    if tag_all:
                        discord_text = "@everyone " + discord_text
                    if tag_users:
                        if tag_mode == "rotate":
                            u = tag_users[mention_counter % len(tag_users)]
                            discord_text = (f"<@{u['id']}> " if not u['id'].startswith('manual_') else f"@{u['name']} ") + discord_text
                        else:
                            tags_d = " ".join([(f"<@{u['id']}>" if not u['id'].startswith('manual_') else f"@{u['name']}") for u in tag_users])
                            discord_text = tags_d + " " + discord_text

                    client.send_message(target_id, discord_text, color_mode=color_mode,
                                        fixed_color=fixed_color, antiband=antiband)

                color_counter += 1
                mention_counter += 1
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

        # Áp dụng Jitter Delay ngẫu nhiên để mô phỏng người thật
        actual_delay = delay * random.uniform(0.85, 1.25)
        time.sleep(actual_delay)

    if stream_reader:
        stream_reader.close()


def task_supervisor(tid, targets, file_path, direct_blocks, delay,
                    combat_icon_mode, combat_icon_count,
                    tag_users, tag_all, is_heading, multi_acc, mode, color_mode, fixed_color,
                    stop_ev, antiband=True, antidieall=True, use_badge=True, tag_mode="rotate", tag_pos="head"):
    conn = db()
    accs = conn.execute("SELECT * FROM accounts WHERE enabled = 1").fetchall()
    if not accs:
        accs = conn.execute("SELECT * FROM accounts").fetchall()
    conn.close()

    accs = [dict(a) for a in accs]
    if not accs:
        print("[Supervisor] Không có tài khoản nào!")
        conn = db()
        conn.execute("UPDATE tasks SET status = 'stopped', ended_at = ? WHERE id = ?", (time.time(), tid))
        conn.commit()
        conn.close()
        return

    counter = {"sent": 0}
    lock = threading.Lock()
    threads = []

    if multi_acc:
        for acc in accs:
            t = threading.Thread(
                target=single_acc_worker,
                args=(acc, targets, file_path, direct_blocks, delay,
                      combat_icon_mode, combat_icon_count,
                      tag_users, tag_all, is_heading, mode, color_mode, fixed_color,
                      stop_ev, counter, lock, antiband, antidieall, use_badge, tag_mode, tag_pos),
                daemon=True
            )
            threads.append(t)
            t.start()
    else:
        t = threading.Thread(
            target=single_acc_worker,
            args=(accs[0], targets, file_path, direct_blocks, delay,
                  combat_icon_mode, combat_icon_count,
                  tag_users, tag_all, is_heading, mode, color_mode, fixed_color,
                  stop_ev, counter, lock, antiband, antidieall, use_badge, tag_mode, tag_pos),
            daemon=True
        )
        threads.append(t)
        t.start()

    while not stop_ev.is_set():
        alive = [t for t in threads if t.is_alive()]
        if not alive:
            break
        time.sleep(1)

    conn = db()
    conn.execute("UPDATE tasks SET status = 'stopped', ended_at = ?, stats = ? WHERE id = ?",
                 (time.time(), json.dumps(counter), tid))
    conn.commit()
    conn.close()


@app.route("/api/tasks/start", methods=["POST"])
@login_required
def api_start_task():
    d = request.json or {}
    targets = d.get("targets", [])
    file_id = d.get("file_id")
    direct_text = d.get("direct_text", "").strip()

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
        return jsonify({"error": "Vui lòng chọn hội thoại / kênh và nhập nội dung cần gửi"}), 400

    delay = float(d.get("delay", 1.0))
    combat_icon_mode = d.get("combat_icon_mode", "mixed")
    combat_icon_count = int(d.get("combat_icon_count", 3))
    tag_users = d.get("tag_users", [])
    tag_all = bool(d.get("tag_all", False))
    tag_mode = d.get("tag_mode", "rotate")
    tag_pos = d.get("tag_pos", "head")
    use_badge = bool(d.get("use_badge", True))
    is_heading = bool(d.get("is_heading", True))
    multi_acc = bool(d.get("multi_acc", True))
    antiband = bool(d.get("antiband", True))
    antidieall = bool(d.get("antidieall", True))
    mode = d.get("mode", "fast")
    color_mode = d.get("color_mode", "rainbow")
    fixed_color = d.get("fixed_color", "red")

    tid = new_tid("vip")
    stop_ev = threading.Event()

    th = threading.Thread(
        target=task_supervisor,
        args=(tid, targets, file_path, direct_blocks, delay,
              combat_icon_mode, combat_icon_count,
              tag_users, tag_all, is_heading, multi_acc, mode, color_mode, fixed_color,
              stop_ev, antiband, antidieall, use_badge, tag_mode, tag_pos),
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


@app.route("/api/tasks", methods=["GET"])
@login_required
def api_get_tasks():
    conn = db()
    rows = conn.execute("SELECT * FROM tasks ORDER BY started_at DESC LIMIT 15").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tasks/<tid>/stop", methods=["POST"])
@login_required
def api_stop_task(tid):
    if tid in ACTIVE_TASKS:
        ACTIVE_TASKS[tid]["stop"].set()
        del ACTIVE_TASKS[tid]
    conn = db()
    conn.execute("UPDATE tasks SET status = 'stopped', ended_at = ? WHERE id = ?", (time.time(), tid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/tasks/stop_all", methods=["POST"])
@login_required
def api_stop_all_tasks():
    for tid, obj in list(ACTIVE_TASKS.items()):
        obj["stop"].set()
    ACTIVE_TASKS.clear()
    conn = db()
    conn.execute("UPDATE tasks SET status = 'stopped', ended_at = ? WHERE status = 'running'", (time.time(),))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ============================================================
# KHỞI CHẠY FLASK SERVER
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"👑 [RICKI VIP — CHIẾN HẠM PRO] Đang chạy tại: http://0.0.0.0:{port}")
    print(f"🔑 Mật khẩu truy cập mặc định: {APP_PASSWORD}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
