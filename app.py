# ============================================================
# Hệ thống điều hành: ALB Forge — ThreeUI Sakura Edition 2026
# Bản quyền thuộc về: Phạm Anh Khôi
# Tiêu chuẩn kiến trúc: ThreeUI MengTo Design System & High-Performance Python
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

# CẤU HÌNH THƯ MỤC LƯU TRỮ VÀ DỮ LIỆU
APP_PASSWORD = os.environ.get("APP_PASSWORD", "anhkhoidz")
DATA_DIR = os.environ.get("DATA_DIR", "/tmp/alb_web")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "alb.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# BIỂU TƯỢNG HOA ANH ĐÀO VECTƠ NHÚNG TRỰC TIẾP (KHÔNG BAO GIỜ BỊ LỖI 404 HAY HỎNG ẢNH)
DEFAULT_LOGO_DATA_URI = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
    "<defs>"
    "<linearGradient id='bgGrad' x1='0%' y1='0%' x2='100%' y2='100%'>"
    "<stop offset='0%' stop-color='%23ff758c'/>"
    "<stop offset='100%' stop-color='%23ff7eb3'/>"
    "</linearGradient>"
    "<linearGradient id='petalGrad' x1='0%' y1='0%' x2='100%' y2='100%'>"
    "<stop offset='0%' stop-color='%23ffffff'/>"
    "<stop offset='100%' stop-color='%23ffe4e8'/>"
    "</linearGradient>"
    "<filter id='glow' x='-20%' y='-20%' width='140%' height='140%'>"
    "<feGaussianBlur stdDeviation='2.5' result='blur'/>"
    "<feComposite in='SourceGraphic' in2='blur' operator='over'/>"
    "</filter>"
    "</defs>"
    "<circle cx='50' cy='50' r='48' fill='url(%23bgGrad)' filter='url(%23glow)'/>"
    "<circle cx='50' cy='50' r='44' fill='none' stroke='%23ffffff' stroke-width='1.5' stroke-dasharray='3 3' opacity='0.7'/>"
    "<g transform='translate(50,50)' fill='url(%23petalGrad)' stroke='%23ffb6c1' stroke-width='1'>"
    "<path d='M0,-5 C-12,-28 -24,-18 0,-38 C24,-18 12,-28 0,-5' />"
    "<path d='M0,-5 C-12,-28 -24,-18 0,-38 C24,-18 12,-28 0,-5' transform='rotate(72)'/>"
    "<path d='M0,-5 C-12,-28 -24,-18 0,-38 C24,-18 12,-28 0,-5' transform='rotate(144)'/>"
    "<path d='M0,-5 C-12,-28 -24,-18 0,-38 C24,-18 12,-28 0,-5' transform='rotate(216)'/>"
    "<path d='M0,-5 C-12,-28 -24,-18 0,-38 C24,-18 12,-28 0,-5' transform='rotate(288)'/>"
    "</g>"
    "<circle cx='50' cy='50' r='8' fill='%23ff4081'/>"
    "<circle cx='50' cy='50' r='4' fill='%23fff'/>"
    "</svg>"
)

# GIAO THỨC PHÒNG VỆ VÀ AN TOÀN TRUY CẬP (TOKEN BUCKET CYBER DEFENSE)
class SecurityFirewall:
    def __init__(self):
        self.lock = threading.Lock()
        self.request_records = defaultdict(deque)
        self.banned_ips = {}
        self.total_screened = 0
        self.total_mitigated = 0
        self.security_logs = deque(maxlen=200)

    def log_event(self, ip, event_type, details):
        with self.lock:
            ts_str = datetime.now().strftime("%H:%M:%S")
            self.security_logs.appendleft({
                "time": ts_str,
                "ip": ip,
                "type": event_type,
                "details": details
            })

    def is_allowed(self, ip):
        with self.lock:
            now = time.time()
            self.total_screened += 1

            if ip in self.banned_ips:
                unban_time = self.banned_ips[ip]
                if now < unban_time:
                    self.total_mitigated += 1
                    return False, f"Địa chỉ IP tạm thời bị giới hạn đến {datetime.fromtimestamp(unban_time).strftime('%H:%M:%S')}"
                else:
                    del self.banned_ips[ip]

            records = self.request_records[ip]
            while records and records[0] < now - 60.0:
                records.popleft()

            recent_count = len(records)
            records.append(now)

            if recent_count > 160:
                ban_duration = 300
                self.banned_ips[ip] = now + ban_duration
                self.total_mitigated += 1
                self.log_event(ip, "Giới Hạn Tần Suất", f"Vượt ngưỡng {recent_count} yêu cầu/phút")
                return False, "Phát hiện lưu lượng truy cập bất thường, vui lòng chờ trong giây lát."

            return True, "Hợp lệ"

    def get_stats(self):
        with self.lock:
            return {
                "total_screened": self.total_screened,
                "total_mitigated": self.total_mitigated,
                "active_banned_count": len(self.banned_ips),
                "recent_logs": list(self.security_logs)[:40]
            }

FIREWALL = SecurityFirewall()

# KHỞI TẠO CƠ SỞ DỮ LIỆU SQLITE
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT,
            imei TEXT,
            cookies TEXT,
            status TEXT DEFAULT 'unknown',
            display_name TEXT,
            avatar TEXT,
            created_at REAL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            filepath TEXT,
            lines INTEGER DEFAULT 0,
            size INTEGER DEFAULT 0,
            uploaded_at REAL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            val TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT,
            targets_count INTEGER,
            accounts_count INTEGER,
            status TEXT,
            sent_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            created_at REAL
        )
    """)

    # Khởi tạo thiết lập mặc định nếu chưa tồn tại
    c.execute("INSERT OR IGNORE INTO settings (key, val) VALUES ('logo_url', ?)", (DEFAULT_LOGO_DATA_URI,))
    c.execute("INSERT OR IGNORE INTO settings (key, val) VALUES ('web_title', 'I LOVE NGỌC HÂN 🌸')")
    c.execute("INSERT OR IGNORE INTO settings (key, val) VALUES ('author_name', 'Phạm Anh Khôi')")
    c.execute("INSERT OR IGNORE INTO settings (key, val) VALUES ('theme_mode', 'sakura')")
    conn.commit()
    conn.close()

init_db()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_setting(key, default_val=""):
    conn = db()
    row = conn.execute("SELECT val FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row and row["val"]:
        return row["val"]
    return default_val

def set_setting(key, val):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO settings (key, val) VALUES (?, ?)", (key, str(val)))
    conn.commit()
    conn.close()

# BẢNG MÀU CHUẨN ZALO PALETTE CHÍNH THỨC (MÃ HEX SẠCH KHÔNG DẤU #)
ZALO_PALETTE_HEX = {
    "red": "ff424e",
    "pink": "ff69b4",
    "sakura": "ff7eb3",
    "rose": "f43f5e",
    "crimson": "e11d48",
    "ruby": "be123c",
    "orange": "ff8800",
    "amber": "f59e0b",
    "sunset": "fb923c",
    "gold": "ffd700",
    "yellow": "eab308",
    "lime": "84cc16",
    "green": "10b981",
    "emerald": "059669",
    "mint": "2dd4bf",
    "teal": "14b8a6",
    "cyan": "06b6d4",
    "sky": "0ea5e9",
    "blue": "0084ff",
    "royal": "2563eb",
    "indigo": "6366f1",
    "violet": "8b5cf6",
    "purple": "a855f7",
    "fuchsia": "d946ef",
    "magenta": "ec4899",
    "charcoal": "334155",
    "slate": "475569",
    "white": "ffffff",
    "neon_green": "00ff66",
    "neon_pink": "ff007f",
    "neon_cyan": "00f0ff",
    "neon_yellow": "ffff00"
}


# ============================================================
# LÕI GIAO THỨC ĐIỀU VẬN VÀ TRUYỀN DẪN TÍN HIỆU ZALO
# ============================================================

def _pad(s):
    bs = 16
    n = bs - len(s) % bs
    return s + bytes([n] * n)

def _unpad(s):
    n = s[-1]
    return s[:-n]

class Zalo:
    def __init__(self, imei, cookies):
        self.imei = imei
        self.cookies = cookies if isinstance(cookies, dict) else {}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": "https://chat.zalo.me/",
            "Origin": "https://chat.zalo.me",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8"
        })
        for k, v in self.cookies.items():
            self.session.cookies.set(k, str(v), domain=".zalo.me")

        self.skey = self.cookies.get("zpw_sek") or self.cookies.get("skey") or ""
        self._key = None
        self._setup_key()

    def _setup_key(self):
        try:
            r = self.session.get(
                "https://chat.zalo.me/api/login/getServerInfo",
                params={"imei": self.imei, "type": "web"},
                timeout=12
            )
            data = r.json()
            if "data" in data and "key" in data["data"]:
                self._key = base64.b64decode(data["data"]["key"])
        except Exception:
            pass

        if not self._key:
            src = (self.imei + (self.skey or "")).encode("utf-8")
            h = hashlib.md5(src).digest()
            self._key = h

    def _enc(self, data_str):
        if not self._key:
            self._setup_key()
        raw = data_str.encode("utf-8")
        raw = _pad(raw)
        iv = b"\x00" * 16
        cipher = AES.new(self._key, AES.MODE_CBC, iv)
        return base64.b64encode(cipher.encrypt(raw)).decode("utf-8")

    def _dec(self, enc_str):
        if not self._key:
            self._setup_key()
        raw = base64.b64decode(enc_str)
        iv = b"\x00" * 16
        cipher = AES.new(self._key, AES.MODE_CBC, iv)
        dec = cipher.decrypt(raw)
        return _unpad(dec).decode("utf-8")

    def check_login(self):
        try:
            r = self.session.get(
                "https://chat.zalo.me/api/login/getServerInfo",
                params={"imei": self.imei, "type": "web"},
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("error_code") == 0:
                    profile = self.get_my_profile()
                    return {
                        "ok": True,
                        "name": profile.get("name", "Người dùng Zalo"),
                        "avatar": profile.get("avatar", "")
                    }
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "Phiên truy cập đã hết hạn hoặc không hợp lệ"}

    def get_my_profile(self):
        try:
            params = json.dumps({"imei": self.imei})
            enc = self._enc(params)
            r = self.session.post(
                "https://profile-wpa.chat.zalo.me/api/social/profile/me",
                data={"params": enc},
                timeout=12
            )
            dec = self._dec(r.json().get("data", ""))
            info = json.loads(dec).get("data", {})
            return {
                "name": info.get("displayName") or info.get("name") or "Người dùng Zalo",
                "avatar": info.get("avatar") or ""
            }
        except Exception:
            return {"name": "Người dùng Zalo", "avatar": ""}

    def groups(self):
        try:
            params = json.dumps({"imei": self.imei})
            enc = self._enc(params)
            r = self.session.post(
                "https://group-wpa.chat.zalo.me/api/group/get-ver",
                data={"params": enc, "zpw_type": 30},
                timeout=15
            )
            dec = self._dec(r.json().get("data", ""))
            grid = json.loads(dec).get("data", {}).get("gridVerMap", {})
            out = []
            for gid in grid:
                try:
                    info = self.group_info(gid)
                    out.append({
                        "id": str(gid),
                        "name": info.get("name", f"Nhóm {gid}"),
                        "totalMember": info.get("totalMember", "?")
                    })
                except Exception:
                    out.append({"id": str(gid), "name": f"Nhóm {gid}", "totalMember": "?"})
            return out
        except Exception as e:
            print(f"Lỗi nạp nhóm: {e}")
            return []

    def group_info(self, gid):
        try:
            params = json.dumps({"grid": str(gid), "imei": self.imei})
            enc = self._enc(params)
            r = self.session.post(
                "https://group-wpa.chat.zalo.me/api/group/get-info",
                data={"params": enc},
                timeout=15
            )
            dec = self._dec(r.json().get("data", ""))
            info = json.loads(dec).get("data", {}).get("gridInfoMap", {}).get(str(gid), {})
            return {
                "name": info.get("name") or f"Nhóm {gid}",
                "totalMember": info.get("totalMember", "?")
            }
        except Exception:
            return {"name": f"Nhóm {gid}", "totalMember": "?"}

    def friends(self):
        try:
            params = json.dumps({"imei": self.imei})
            enc = self._enc(params)
            r = self.session.post(
                "https://profile-wpa.chat.zalo.me/api/social/friend/getfriends",
                data={"params": enc},
                timeout=15
            )
            dec = self._dec(r.json().get("data", ""))
            d = json.loads(dec).get("data", [])
            users = d if isinstance(d, list) else d.get("users", [])
            return [{
                "id": str(u.get("userId")),
                "name": u.get("displayName") or u.get("zaloName") or "Bạn bè",
                "avatar": u.get("avatar", "")
            } for u in users if u.get("userId")]
        except Exception as e:
            print(f"Lỗi nạp bạn bè: {e}")
            return []

    def get_members_full(self, gid):
        try:
            params = json.dumps({"grid": str(gid), "imei": self.imei})
            enc = self._enc(params)
            r = self.session.post(
                "https://group-wpa.chat.zalo.me/api/group/get-info",
                data={"params": enc},
                timeout=20
            )
            dec = self._dec(r.json().get("data", ""))
            info = json.loads(dec).get("data", {}).get("gridInfoMap", {}).get(str(gid), {})

            members_dict = {}
            mem_info_list = info.get("memInfoList", [])
            if isinstance(mem_info_list, list):
                for m in mem_info_list:
                    uid = str(m.get("id") or m.get("userId") or "")
                    name = m.get("dName") or m.get("displayName") or ""
                    if uid:
                        members_dict[uid] = name

            all_uids = [str(x) for x in info.get("memVerList", [])]
            missing_uids = [u for u in all_uids if not members_dict.get(u)]

            if missing_uids:
                p_params = json.dumps({"uids": missing_uids[:50], "imei": self.imei})
                enc2 = self._enc(p_params)
                r2 = self.session.post(
                    "https://profile-wpa.chat.zalo.me/api/social/profile/getprofiles",
                    data={"params": enc2},
                    timeout=15
                )
                dec2 = self._dec(r2.json().get("data", ""))
                profiles_data = json.loads(dec2).get("data", {})
                profiles = profiles_data.get("profiles", {}) if isinstance(profiles_data, dict) else {}
                for uid in missing_uids:
                    p = profiles.get(str(uid), {})
                    if p:
                        members_dict[uid] = p.get("displayName") or p.get("zaloName") or f"Người dùng {uid}"

            results = []
            for uid, name in members_dict.items():
                results.append({"id": uid, "name": name or f"Người dùng {uid}"})
            return sorted(results, key=lambda x: x["name"])
        except Exception as e:
            print(f"Lỗi nạp thành viên nhóm: {e}")
            return []

    def fast_send(self, target_id, is_group, message_text,
                  tag_all=False, tag_users=None,
                  is_heading=True, color_hex="ff69b4",
                  icon_count=0):
        # Chuẩn bị nội dung tin nhắn
        msg = message_text or ""
        clean_color = (color_hex or "ff69b4").replace("#", "").strip()

        # Xử lý Tag All (@All)
        mentions = []
        if is_group and tag_all:
            tag_prefix = "@All "
            if not msg.startswith("@All"):
                msg = tag_prefix + msg
            mentions.append({
                "uid": "-1",
                "type": 0,
                "pos": 0,
                "len": len("@All")
            })

        # Xử lý Tag người dùng cụ thể
        if is_group and tag_users and not tag_all:
            tag_str = ""
            current_pos = len(msg) + 1 if msg else 0
            if msg:
                msg += " "
            for u in tag_users:
                u_name = "@" + u.get("name", "Bạn")
                mentions.append({
                    "uid": str(u.get("id")),
                    "type": 0,
                    "pos": current_pos,
                    "len": len(u_name)
                })
                tag_str += u_name + " "
                current_pos += len(u_name) + 1
            msg += tag_str

        # Thêm biểu tượng cảm xúc trang trí nếu được cấu hình
        if icon_count > 0:
            sakura_emojis = ["🌸", "💮", "🌺", "✨", "💖", "🌷", "🏵️", "💫"]
            decor = " " + "".join(random.choice(sakura_emojis) for _ in range(icon_count))
            msg += decor

        # Đóng gói định dạng kiểu dáng ThreeUI (Màu chữ + In đậm tiêu đề)
        styles = []
        if len(msg) > 0:
            style_obj = {
                "start": 0,
                "len": len(msg),
                "st": f"c_{clean_color}"
            }
            styles.append(style_obj)
            if is_heading:
                styles.append({
                    "start": 0,
                    "len": len(msg),
                    "st": "b"
                })

        # Đóng gói payload gửi tin nhắn
        cli_msg_id = int(time.time() * 1000)
        body = {
            "clientId": cli_msg_id,
            "imei": self.imei,
            "message": msg,
            "ttl": 0,
            "visibility": 0
        }

        if is_group:
            body["grid"] = str(target_id)
            url = "https://group-wpa.chat.zalo.me/api/group/sendmsg"
        else:
            body["toid"] = str(target_id)
            url = "https://chat-wpa.chat.zalo.me/api/message/send"

        if mentions:
            body["mentionInfo"] = json.dumps(mentions)

        if styles:
            body["style"] = json.dumps({"styles": styles})

        enc = self._enc(json.dumps(body))
        r = self.session.post(url, data={"params": enc, "zpw_type": 30}, timeout=15)
        return r.status_code == 200

# BỘ ĐIỀU HÀNH VÀ QUẢN LÝ TIẾN TRÌNH TRUYỀN PHÁT (TASK RUNNER ENGINE)
ACTIVE_TASKS = {}
TASK_LOCK = threading.Lock()

def task_worker(task_id, acc_dict, targets, blocks, delay,
                use_emoji, icon_count, tag_users, tag_all,
                is_heading, mode, color_mode, fixed_color,
                stop_event, counter, lock):
    imei = acc_dict["imei"]
    cookies = json.loads(acc_dict["cookies"])
    try:
        z = Zalo(imei, cookies)
    except Exception:
        return

    b_idx, t_idx = 0, 0
    all_colors = list(ZALO_PALETTE_HEX.values())

    while not stop_event.is_set():
        target = targets[t_idx % len(targets)]
        target_id = target["id"]
        is_group = (target.get("type") == "group")

        # Xác định nội dung truyền phát theo chế độ
        if mode == "stream":
            # Tách từng dòng nhỏ truyền liên tục
            line_pool = blocks if blocks else ["ALB Forge v3.0 Pro"]
            content = line_pool[b_idx % len(line_pool)]
        elif mode == "multiline":
            # Gộp nhiều dòng thành cụm
            chunk_size = random.randint(2, 4)
            chosen = [blocks[(b_idx + i) % len(blocks)] for i in range(chunk_size)] if blocks else ["🌸 ALB Forge ThreeUI"]
            content = "\n".join(chosen)
        else:
            content = blocks[b_idx % len(blocks)] if blocks else "ALB Forge v3.0 Pro"

        # Xác định màu sắc
        if color_mode == "rainbow":
            chosen_hex = random.choice(all_colors)
        else:
            chosen_hex = ZALO_PALETTE_HEX.get(fixed_color, "ff69b4")

        try:
            ok = z.fast_send(
                target_id=target_id,
                is_group=is_group,
                message_text=content,
                tag_all=tag_all,
                tag_users=tag_users,
                is_heading=is_heading,
                color_hex=chosen_hex,
                icon_count=icon_count if use_emoji else 0
            )
            with lock:
                if ok:
                    counter["sent"] += 1
                else:
                    counter["err"] += 1
        except Exception:
            with lock:
                counter["err"] += 1

        b_idx += 1
        t_idx += 1

        sleep_time = max(0.05, float(delay))
        time.sleep(sleep_time)


# ============================================================
# THREEUI DESIGN SYSTEM CSS — SAKURA LUXURY GLASSMORPHISM 2026
# ============================================================

THREEUI_CSS = """
:root {
  --bg-page: #faf7f9;
  --bg-glass: rgba(255, 255, 255, 0.88);
  --bg-glass-card: rgba(255, 255, 255, 0.94);
  --border-color: rgba(244, 208, 218, 0.85);
  --border-hover: rgba(255, 105, 180, 0.65);
  --txt-0: #0f172a;
  --txt-1: #334155;
  --txt-2: #64748b;
  --txt-3: #94a3b8;
  --sakura: #ff69b4;
  --sakura-glow: rgba(255, 105, 180, 0.35);
  --grad-sakura: linear-gradient(135deg, #ff758c 0%, #ff7eb3 100%);
  --grad-dark: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  --grad-accent: linear-gradient(135deg, #f43f5e 0%, #fb7185 100%);
  --shadow-soft: 0 10px 30px rgba(255, 117, 140, 0.08);
  --shadow-card: 0 14px 35px rgba(244, 114, 182, 0.12);
  --shadow-btn: 0 4px 14px rgba(255, 105, 180, 0.28);
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
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Be Vietnam Pro", "Inter", sans-serif;
  background-color: var(--bg-page);
  color: var(--txt-1);
  min-height: 100vh;
  padding-bottom: 110px;
  position: relative;
  overflow-x: hidden;
  background-image:
    radial-gradient(at 0% 0%, rgba(255, 182, 193, 0.25) 0px, transparent 50%),
    radial-gradient(at 100% 100%, rgba(255, 192, 203, 0.22) 0px, transparent 50%),
    radial-gradient(at 50% 50%, rgba(255, 240, 245, 0.4) 0px, transparent 50%);
  background-attachment: fixed;
}

/* LỚP NỀN HOẠT CẢNH VÀ CANVAS HOA ANH ĐÀO */
#sakura-canvas {
  position: fixed;
  inset: 0;
  pointer-events: none !important;
  touch-action: none !important;
  z-index: 0;
  width: 100%;
  height: 100%;
}

/* CÀNH HOA ANH ĐÀO NGHỆ THUẬT VƯƠN TỰ NHIÊN */
.cherry-blossom-tree-branch,
.cherry-blossom-tree-branch * {
  pointer-events: none !important;
  touch-action: none !important;
  -webkit-user-select: none;
  user-select: none;
}
.cherry-blossom-tree-branch {
  position: fixed;
  top: 0;
  right: 0;
  width: 320px;
  height: 350px;
  z-index: 2;
  opacity: 0.95;
  transform-origin: top right;
  animation: branchGentleWind 8s ease-in-out infinite alternate;
}

@keyframes branchGentleWind {
  0% { transform: rotate(0deg) scale(1); }
  50% { transform: rotate(1.4deg) scale(1.01) translateY(2px); }
  100% { transform: rotate(-1deg) scale(0.995) translateY(-2px); }
}

/* MÀN HÌNH TẢI TRANG THREEUI (PRELOADER) */
#threeui-preloader {
  position: fixed;
  inset: 0;
  z-index: 999999;
  background: rgba(250, 247, 249, 0.97);
  backdrop-filter: blur(40px);
  -webkit-backdrop-filter: blur(40px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  transition: opacity 0.35s var(--ease), visibility 0.35s var(--ease), transform 0.35s var(--ease);
  cursor: pointer;
}
#threeui-preloader.loaded {
  opacity: 0 !important;
  visibility: hidden !important;
  pointer-events: none !important;
  transform: scale(1.04) !important;
}

.preloader-emblem {
  position: relative;
  width: 110px;
  height: 110px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 22px;
}
.preloader-ring-outer {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2.5px dashed rgba(255, 105, 180, 0.55);
  animation: preloaderSpin 10s linear infinite;
}
.preloader-ring-inner {
  position: absolute;
  inset: 7px;
  border-radius: 50%;
  border: 2px solid transparent;
  border-top-color: #ff69b4;
  border-right-color: #ff758c;
  animation: preloaderSpinRev 2.2s cubic-bezier(0.68, -0.55, 0.27, 1.55) infinite;
}
@keyframes preloaderSpin {
  100% { transform: rotate(360deg); }
}
@keyframes preloaderSpinRev {
  100% { transform: rotate(-360deg); }
}

.preloader-logo-wrap {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  overflow: hidden;
  box-shadow: 0 8px 24px var(--sakura-glow);
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  z-index: 2;
}
.preloader-logo-wrap img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.preloader-title {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Plus Jakarta Sans", sans-serif;
  font-size: 19px;
  font-weight: 800;
  color: var(--txt-0);
  margin-bottom: 6px;
  letter-spacing: -0.01em;
  text-align: center;
  padding: 0 16px;
  word-break: break-word;
}
.preloader-sub {
  font-size: 11.5px;
  color: var(--txt-2);
  font-weight: 600;
  margin-bottom: 24px;
  text-align: center;
}
.preloader-bar-wrap {
  width: 210px;
  height: 6px;
  background: rgba(244, 208, 218, 0.6);
  border-radius: 99px;
  overflow: hidden;
  margin-bottom: 10px;
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.05);
}
.preloader-bar-fill {
  height: 100%;
  width: 0%;
  background: var(--grad-sakura);
  border-radius: 99px;
  transition: width 0.15s ease-out;
}
.preloader-pct {
  font-size: 11px;
  font-weight: 700;
  color: var(--sakura);
}
.preloader-hint {
  font-size: 10px;
  color: var(--txt-3);
  margin-top: 14px;
}

/* THANH TIÊU ĐỀ HEADER THREEUI */
.header {
  position: sticky;
  top: 0;
  z-index: 50;
  background: var(--bg-glass);
  backdrop-filter: blur(28px);
  -webkit-backdrop-filter: blur(28px);
  border-bottom: 1px solid var(--border-color);
  padding: 10px 16px;
  transition: all 0.3s var(--ease);
}
.header-inner {
  max-width: 1080px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.logo-box {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  overflow: hidden;
  border: 2px solid #fff;
  box-shadow: 0 4px 14px var(--sakura-glow);
  background: #fff;
  flex-shrink: 0;
  cursor: pointer;
  transition: transform 0.25s var(--ease);
}
.logo-box:hover {
  transform: scale(1.08);
}
.logo-box img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.header-meta {
  min-width: 0;
  flex: 1;
}
.header-meta h1 {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Plus Jakarta Sans", sans-serif;
  font-size: 14.5px;
  font-weight: 800;
  color: var(--txt-0);
  line-height: 1.25;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: -0.01em;
}
.header-meta p {
  font-size: 10.5px;
  color: var(--txt-2);
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 1px;
}
.v-badge {
  display: inline-flex;
  align-items: center;
  color: #0084ff;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

/* THANH ĐO FPS MÁY ĐỘNG (NHẢY LIÊN TỤC TRÊN GÓC) */
.fps-meter {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  border-radius: 99px;
  font-size: 10.5px;
  font-weight: 800;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid rgba(16, 185, 129, 0.35);
  color: #059669;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  user-select: none;
  transition: color 0.2s, border-color 0.2s;
}
.fps-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
  animation: fpsPulse 1.2s ease-in-out infinite;
}
@keyframes fpsPulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.45; transform: scale(1.3); }
}

/* NÚT BẤM TINH GỌN (COMPACT BUTTONS) */
.btn-xs {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 5px 10px;
  border-radius: 99px;
  font-size: 11px;
  font-weight: 700;
  border: 1px solid var(--border-color);
  background: #fff;
  color: var(--txt-1);
  cursor: pointer;
  transition: all 0.2s var(--ease);
  white-space: nowrap;
}
.btn-xs:hover {
  border-color: var(--sakura);
  color: var(--sakura);
  transform: translateY(-1px);
}
.btn-xs:active {
  transform: scale(0.96);
}
.btn-xs.danger {
  color: #b91c1c;
  background: #fee2e2;
  border-color: #fca5a5;
}

/* BỐ CỤC KHUNG CHÍNH (CONTAINER & PANELS) */
.container {
  max-width: 1080px;
  margin: 16px auto 0;
  padding: 0 16px;
  position: relative;
  z-index: 15;
}

.panel {
  display: none;
  animation: fadeInPanel 0.28s var(--ease);
}
.panel.active {
  display: block;
}
@keyframes fadeInPanel {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

/* THẺ NỘI DUNG GLASSMORPHISM CARD */
.card {
  background: var(--bg-glass-card);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  padding: 18px;
  margin-bottom: 16px;
  box-shadow: var(--shadow-card);
  position: relative;
  overflow: hidden;
}
.card h2 {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Plus Jakarta Sans", sans-serif;
  font-size: 14.5px;
  font-weight: 800;
  color: var(--txt-0);
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  letter-spacing: -0.01em;
}
.card-header-icon {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

/* NÚT BẤM DẠNG VIÊN THUỐC (PILL BUTTONS) */
.btn-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 18px;
  border-radius: 99px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  border: none;
  transition: all 0.25s var(--ease);
  position: relative;
  overflow: hidden;
  user-select: none;
}
.btn-pill:hover {
  transform: translateY(-2px);
  filter: brightness(1.05);
}
.btn-pill:active {
  transform: translateY(0) scale(0.97);
}
.btn-pill.primary {
  background: var(--grad-sakura);
  color: #fff;
  box-shadow: var(--shadow-btn);
}
.btn-pill.dark {
  background: var(--grad-dark);
  color: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.25);
}
.btn-pill.light {
  background: #fff;
  color: var(--txt-1);
  border: 1px solid var(--border-color);
}
.btn-pill.danger {
  background: #fee2e2;
  color: #b91c1c;
  border: 1px solid #fca5a5;
}
.btn-pill.full {
  width: 100%;
  padding: 12px 16px;
}

/* BIỂU MẪU & INPUTS */
.form-group {
  margin-bottom: 14px;
}
.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 11px;
  font-weight: 700;
  color: var(--txt-2);
}
.form-group input:not([type="file"]),
.form-group textarea,
.form-group select {
  width: 100%;
  padding: 11px 14px;
  border: 1.5px solid var(--border-color);
  border-radius: 14px;
  font-size: 13px;
  background: #fff;
  color: var(--txt-0);
  font-family: inherit;
  transition: border-color 0.2s;
}
.form-group input:focus,
.form-group textarea:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--sakura);
  box-shadow: 0 0 0 3px rgba(255, 105, 180, 0.15);
}

/* BẢNG DỮ LIỆU RESPONSIVE */
.table-responsive {
  width: 100%;
  overflow-x: auto;
  border-radius: 14px;
  border: 1px solid var(--border-color);
  background: #fff;
}
.table {
  width: 100%;
  border-collapse: collapse;
}
.table th, .table td {
  padding: 10px 12px;
  text-align: left;
  font-size: 11.5px;
  border-bottom: 1px solid #fdf2f4;
  white-space: nowrap;
}
.table th {
  background: #fdf6f7;
  color: var(--txt-2);
  font-weight: 700;
}

/* THANH ĐIỀU HƯỚNG DOCK DƯỚI ĐÁY (6 NÚT CHUẨN) */
.bottom-dock {
  position: fixed;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  width: calc(100% - 20px);
  max-width: 520px;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(28px);
  -webkit-backdrop-filter: blur(28px);
  border: 1px solid rgba(244, 208, 218, 0.95);
  box-shadow: 0 14px 40px rgba(255, 117, 140, 0.18);
  border-radius: 28px;
  padding: 6px 8px;
  display: flex;
  align-items: center;
  justify-content: space-around;
  z-index: 100;
}
.dock-btn {
  background: none;
  border: none;
  outline: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  padding: 6px 8px;
  border-radius: 18px;
  color: var(--txt-2);
  cursor: pointer;
  flex: 1;
  transition: all 0.25s var(--ease);
  position: relative;
}
.dock-btn svg {
  width: 20px;
  height: 20px;
  transition: transform 0.25s var(--ease), color 0.25s;
}
.dock-btn span {
  font-size: 10px;
  font-weight: 700;
  transition: color 0.25s;
}
.dock-btn.active {
  color: var(--sakura);
}
.dock-btn.active svg {
  transform: translateY(-2px) scale(1.1);
  color: var(--sakura);
}
.dock-btn.active span {
  color: var(--sakura);
  font-weight: 800;
}

/* BỘ QUẢN LÝ ẢNH LOGO (LOGO MANAGER PANEL) */
.logo-manager-grid {
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 16px;
  align-items: center;
  margin-bottom: 16px;
}
@media (max-width: 480px) {
  .logo-manager-grid {
    grid-template-columns: 1fr;
    text-align: center;
  }
}
.logo-preview-box {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  border: 3px solid #fff;
  box-shadow: 0 8px 24px var(--sakura-glow);
  overflow: hidden;
  margin: 0 auto;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}
.logo-preview-box img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* THÔNG BÁO TOAST THÔNG MINH */
#toast-stack {
  position: fixed;
  top: 14px;
  right: 14px;
  z-index: 99999;
  max-width: 320px;
  width: calc(100% - 28px);
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  padding: 12px 16px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid var(--border-color);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
  margin-bottom: 8px;
  animation: toastIn 0.28s var(--ease);
}
@keyframes toastIn {
  from { opacity: 0; transform: translateY(-10px) scale(0.95); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.t-head {
  font-size: 11.5px;
  font-weight: 800;
  color: var(--txt-0);
  margin-bottom: 2px;
}
.t-body {
  font-size: 11px;
  color: var(--txt-1);
}
"""


# ============================================================
# CÀNH HOA ANH ĐÀO NGHỆ THUẬT & GIAO DIỆN HTML THREEUI 2026
# ============================================================

SVG_CHERRY_BRANCH = """
<svg class="cherry-blossom-tree-branch" viewBox="0 0 340 370" fill="none" xmlns="http://www.w3.org/2000/svg" pointer-events="none" touch-action="none">
  <defs>
    <linearGradient id="brWood" x1="100%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#4a2e2b"/>
      <stop offset="50%" stop-color="#6d433b"/>
      <stop offset="100%" stop-color="#8c584a"/>
    </linearGradient>
    <linearGradient id="petalPink" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="60%" stop-color="#ffb6c1"/>
      <stop offset="100%" stop-color="#ff69b4"/>
    </linearGradient>
    <linearGradient id="leafGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#a7f3d0"/>
      <stop offset="100%" stop-color="#10b981"/>
    </linearGradient>
    <filter id="sakuraGlow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="2" result="blur"/>
      <feComposite in="SourceGraphic" in2="blur" operator="over"/>
    </filter>
  </defs>

  <!-- THÂN VÀ CÁC NHÁNH CÂY CHÍNH VƯƠN TỰ NHIÊN TỪ GÓC PHẢI -->
  <path d="M340,-20 Q290,40 230,80 T130,150 T40,210 Q20,225 0,240 Q15,220 45,200 T140,140 T240,70 T340,-10 Z" fill="url(#brWood)" opacity="0.95"/>
  <path d="M240,75 Q190,110 160,170 T110,260 Q120,250 150,180 T220,95 Z" fill="url(#brWood)" opacity="0.9"/>
  <path d="M180,120 Q130,110 90,120 T30,140 Q50,130 100,120 T170,125 Z" fill="url(#brWood)" opacity="0.85"/>
  <path d="M125,230 Q80,260 50,310 Q65,280 115,240 Z" fill="url(#brWood)" opacity="0.8"/>

  <!-- NHỮNG LÁ NON XANH MƯỚT (THREEUI ACCENT) -->
  <g fill="url(#leafGrad)" opacity="0.9">
    <path d="M210,60 C215,45 230,50 235,65 C225,75 210,70 210,60 Z"/>
    <path d="M150,110 C140,95 155,90 165,105 C160,115 145,115 150,110 Z"/>
    <path d="M85,115 C75,105 85,95 95,105 C92,118 80,120 85,115 Z"/>
    <path d="M120,210 C110,195 125,190 135,205 C130,215 115,215 120,210 Z"/>
    <path d="M45,200 C35,190 45,180 55,190 C50,205 38,205 45,200 Z"/>
    <path d="M50,295 C40,285 50,275 60,285 C55,300 45,300 50,295 Z"/>
  </g>

  <!-- CÁC CHÙM HOA ANH ĐÀO NỞ RỘ RỰC RỠ -->
  <!-- Hoa 1: Gần ngọn chính -->
  <g transform="translate(42, 210) scale(0.9)" filter="url(#sakuraGlow)">
    <g fill="url(#petalPink)">
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(72)"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(144)"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(216)"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(288)"/>
    </g>
    <circle cx="0" cy="0" r="4.5" fill="#ff4081"/>
    <circle cx="0" cy="0" r="2" fill="#fff"/>
  </g>

  <!-- Hoa 2: Nhánh giữa trái -->
  <g transform="translate(85, 120) scale(0.95)" filter="url(#sakuraGlow)">
    <g fill="url(#petalPink)">
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(72)"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(144)"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(216)"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(288)"/>
    </g>
    <circle cx="0" cy="0" r="4.5" fill="#ff4081"/>
    <circle cx="0" cy="0" r="2" fill="#fff"/>
  </g>

  <!-- Hoa 3: Nhánh giữa chính -->
  <g transform="translate(160, 160) scale(1.1)" filter="url(#sakuraGlow)">
    <g fill="url(#petalPink)">
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(72)"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(144)"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(216)"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(288)"/>
    </g>
    <circle cx="0" cy="0" r="5" fill="#ff4081"/>
    <circle cx="0" cy="0" r="2.5" fill="#fff"/>
  </g>

  <!-- Hoa 4: Nhánh dưới -->
  <g transform="translate(105, 255) scale(0.85)" filter="url(#sakuraGlow)">
    <g fill="url(#petalPink)">
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(72)"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(144)"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(216)"/>
      <path d="M0,0 C-8,-16 -16,-12 0,-26 C16,-12 8,-16 0,0" transform="rotate(288)"/>
    </g>
    <circle cx="0" cy="0" r="4" fill="#ff4081"/>
    <circle cx="0" cy="0" r="2" fill="#fff"/>
  </g>

  <!-- Nụ hoa anh đào chớm nở -->
  <circle cx="25" cy="140" r="5" fill="#ff69b4" opacity="0.85"/>
  <circle cx="15" cy="235" r="4.5" fill="#ff69b4" opacity="0.85"/>
  <circle cx="45" cy="305" r="5" fill="#ff69b4" opacity="0.85"/>
</svg>
"""

# TRANG XÁC THỰC AN TOÀN TRUY CẬP (GATE SCANNER)
HTML_GATE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Xác Thực An Toàn — ThreeUI</title>
<style>
""" + THREEUI_CSS + """
.gate-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 20px;
}
.gate-card {
  background: var(--bg-glass-card);
  backdrop-filter: blur(28px);
  border: 1px solid var(--border-color);
  border-radius: 24px;
  padding: 40px 28px;
  max-width: 380px;
  width: 100%;
  text-align: center;
  box-shadow: var(--shadow-card);
}
.radar-box {
  width: 90px;
  height: 90px;
  margin: 0 auto 20px;
  border-radius: 50%;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(circle, rgba(255,105,180,0.15) 0%, transparent 70%);
  border: 2px dashed rgba(255,105,180,0.55);
}
.radar-box::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2px solid transparent;
  border-top-color: var(--sakura);
  animation: radarSpin 1.4s linear infinite;
}
@keyframes radarSpin { 100% { transform: rotate(360deg); } }
.radar-icon { font-size: 36px; }
</style>
</head>
<body>
<canvas id="sakura-canvas"></canvas>
""" + SVG_CHERRY_BRANCH + """
<div class="gate-wrap">
  <div class="gate-card">
    <div class="radar-box">
      <div class="radar-icon">🌸</div>
    </div>
    <h2 style="justify-content:center; margin-bottom:8px;">Kiểm Tra An Toàn</h2>
    <p style="font-size:12px; color:var(--txt-2); margin-bottom:24px;">Hệ thống đang chuẩn bị môi trường kết nối tối ưu cho bạn...</p>
    <div class="preloader-bar-wrap" style="width:100%; margin:0 auto 12px;">
      <div class="preloader-bar-fill" id="gate-bar" style="width:10%;"></div>
    </div>
    <div id="gate-status" style="font-size:11px; color:var(--sakura); font-weight:700;">Đang khởi động...</div>
  </div>
</div>
<script>
var p = 10;
var bar = document.getElementById('gate-bar');
var st = document.getElementById('gate-status');
var inv = setInterval(function(){
  p += 20;
  if(bar) bar.style.width = p + '%';
  if(p >= 100){
    clearInterval(inv);
    if(st) st.textContent = 'Hoàn tất xác thực!';
    setTimeout(function(){ window.location.href = '/'; }, 300);
  }
}, 120);
</script>
</body>
</html>
"""

# TRANG ĐĂNG NHẬP HỆ THỐNG
HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Đăng Nhập — {{ web_title }}</title>
<style>
""" + THREEUI_CSS + """
.login-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 20px;
}
.login-card {
  background: var(--bg-glass-card);
  backdrop-filter: blur(28px);
  border: 1px solid var(--border-color);
  border-radius: 24px;
  padding: 38px 28px;
  max-width: 380px;
  width: 100%;
  text-align: center;
  box-shadow: var(--shadow-card);
}
.login-emblem {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  overflow: hidden;
  margin: 0 auto 16px;
  border: 2px solid #fff;
  box-shadow: 0 6px 20px var(--sakura-glow);
  background: #fff;
}
.login-emblem img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
</head>
<body>
<canvas id="sakura-canvas"></canvas>
""" + SVG_CHERRY_BRANCH + """
<div class="login-wrap">
  <div class="login-card">
    <div class="login-emblem">
      <img src="{{ logo_url }}" onerror="this.src='""" + DEFAULT_LOGO_DATA_URI + """'">
    </div>
    <h2 style="justify-content:center; margin-bottom:4px;">{{ web_title }}</h2>
    <p style="font-size:11px; color:var(--txt-2); margin-bottom:20px;">Bản quyền thiết kế: {{ author_name }}</p>

    {% if error %}
    <div style="background:#fee2e2; color:#b91c1c; padding:10px; border-radius:12px; font-size:11.5px; font-weight:700; margin-bottom:16px;">
      {{ error }}
    </div>
    {% endif %}

    <form method="POST">
      <div class="form-group" style="text-align:left;">
        <label>Mật Khẩu Truy Cập</label>
        <input type="password" name="password" placeholder="Nhập mật khẩu..." required autofocus>
      </div>
      <button type="submit" class="btn-pill primary full">Xác Nhận Đăng Nhập</button>
    </form>
  </div>
</div>
</body>
</html>
"""


# ============================================================
# GIAO DIỆN CHÍNH DASHBOARD (HTML_APP) — THREEUI SAKURA PRO
# ============================================================

HTML_APP = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>{{ web_title }}</title>
<style>
""" + THREEUI_CSS + """
</style>
</head>
<body>

<!-- MÀN HÌNH TẢI TRANG THREEUI (CHẠM ĐỂ VÀO NGAY, KHÔNG BAO GIỜ TREO) -->
<div id="threeui-preloader" onclick="this.remove()" ontouchstart="this.remove()" title="Nhấn vào màn hình để vào ngay">
  <div class="preloader-emblem">
    <div class="preloader-ring-outer"></div>
    <div class="preloader-ring-inner"></div>
    <div class="preloader-logo-wrap">
      <img id="preloader-logo-img" src="{{ logo_url }}" onerror="this.onerror=null; this.src='""" + DEFAULT_LOGO_DATA_URI + """'">
    </div>
  </div>
  <div class="preloader-title">{{ web_title }}</div>
  <div class="preloader-sub" id="preloader-status-text">Đang khởi tạo giao diện điều khiển...</div>
  <div class="preloader-bar-wrap">
    <div class="preloader-bar-fill" id="preloader-bar"></div>
  </div>
  <div class="preloader-pct" id="preloader-pct">0%</div>
  <div class="preloader-hint">✨ Chạm bất kỳ đâu để vào giao diện ngay</div>
</div>
<script>
// SCRIPT CHẠY NGAY TỨC THÌ ĐỂ THANH LOAD HOẠT ĐỘNG SIÊU MƯỢT VÀ TỰ ĐỘNG BIẾN MẤT
(function(){
  var bar = document.getElementById('preloader-bar');
  var pct = document.getElementById('preloader-pct');
  var txt = document.getElementById('preloader-status-text');
  var pl = document.getElementById('threeui-preloader');
  if(!pl) return;

  var cur = 0;
  var timer = setInterval(function(){
    cur += 15;
    if(cur > 100) cur = 100;
    if(bar) bar.style.width = cur + '%';
    if(pct) pct.textContent = cur + '%';
    if(cur === 45 && txt) txt.textContent = 'Đang đồng bộ dữ liệu ThreeUI...';
    if(cur === 75 && txt) txt.textContent = 'Đang kích hoạt giao diện...';
    if(cur === 100 && txt) txt.textContent = 'Sẵn sàng!';

    if(cur >= 100){
      clearInterval(timer);
      setTimeout(function(){
        if(pl){
          pl.classList.add('loaded');
          setTimeout(function(){ pl.remove(); }, 350);
        }
      }, 100);
    }
  }, 25);

  // BẢO VỆ CHỐNG TREO: TỐI ĐA 600MS LÀ PHẢI BIẾN MẤT DÙ BẤT CỨ ĐIỀU GÌ XẢY RA
  setTimeout(function(){
    if(pl) { pl.classList.add('loaded'); setTimeout(function(){ pl.remove(); }, 300); }
  }, 600);
})();
</script>

<!-- CANVAS CÁNH HOA & LÁ ANH ĐÀO RƠI 60FPS -->
<canvas id="sakura-canvas"></canvas>

<!-- CÀNH HOA ANH ĐÀO NGHỆ THUẬT (POINTER-EVENTS=NONE) -->
""" + SVG_CHERRY_BRANCH + """

<!-- THANH TIÊU ĐỀ HEADER THREEUI CAO CẤP -->
<div class="header">
  <div class="header-inner">
    <div class="header-left">
      <div class="logo-box" onclick="switchTab('logo')" title="Nhấn để đổi Logo">
        <img id="header-logo" src="{{ logo_url }}" onerror="this.onerror=null; this.src='""" + DEFAULT_LOGO_DATA_URI + """'">
      </div>
      <div class="header-meta">
        <h1 id="header-web-title">{{ web_title }}</h1>
        <p>
          Bản quyền: <span class="v-badge"><svg viewBox="0 0 24 24" width="12" height="12" fill="#0084ff"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></span>
          <span>{{ author_name }}</span>
        </p>
      </div>
    </div>
    <div class="header-right">
      <!-- THANH ĐO FPS MÁY ĐỘNG NHẢY LIÊN TỤC -->
      <div class="fps-meter" id="fps-badge" title="Tốc độ làm mới khung hình thời gian thực">
        <span class="fps-dot"></span>
        <span id="fps-val">60</span> FPS
      </div>
      <button class="btn-xs" onclick="switchTab('logo')">🖼️ Logo</button>
      <a href="/logout" class="btn-xs danger">Thoát</a>
    </div>
  </div>
</div>

<div id="toast-stack"></div>

<!-- NỘI DUNG CHÍNH (6 TABS ĐIỀU KHIỂN) -->
<div class="container">

  <!-- ================= TAB 1: TÀI KHOẢN ================= -->
  <div class="panel active" id="panel-accounts">
    <div class="card">
      <h2><span class="card-header-icon">👤 Thêm Tài Khoản Mới</span></h2>
      <div class="form-group">
        <label>Tên Gợi Nhớ</label>
        <input type="text" id="add-label" placeholder="Ví dụ: Tài khoản chính, Phụ 1...">
      </div>
      <div class="form-group">
        <label>Mã Định Danh Thiết Bị (IMEI)</label>
        <input type="text" id="add-imei" placeholder="Nhập mã IMEI kết nối...">
      </div>
      <div class="form-group">
        <label>Mã Khóa Phiên Truy Cập (Token JSON)</label>
        <textarea id="add-cookies" rows="3" placeholder='{"zpw_sek": "...", ...}'></textarea>
      </div>
      <button class="btn-pill primary full" onclick="addAccount()">+ Thêm Vào Danh Sách</button>
    </div>

    <div class="card">
      <h2>
        <span class="card-header-icon">📑 Danh Sách Tài Khoản</span>
        <button class="btn-pill light" onclick="checkAllAccounts()">Kiểm Tra Toàn Bộ</button>
      </h2>
      <div class="table-responsive">
        <table class="table">
          <thead>
            <tr>
              <th>Tên Gợi Nhớ</th>
              <th>Trạng Thái</th>
              <th>Thao Tác</th>
            </tr>
          </thead>
          <tbody id="accounts-tbody">
            <tr><td colspan="3" style="text-align:center; color:var(--txt-2); padding:16px;">Đang tải danh sách...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ================= TAB 2: HỘI THOẠI ================= -->
  <div class="panel" id="panel-boxes">
    <div class="card">
      <h2><span class="card-header-icon">💬 Quét & Chọn Hội Thoại Nhận Tin</span></h2>
      <div class="form-group">
        <label>Chọn Tài Khoản Quét Dữ Liệu</label>
        <select id="load-acc-select">
          <option value="">-- Chọn tài khoản --</option>
        </select>
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:14px;">
        <button class="btn-pill dark" onclick="loadBoxes()">Nạp Danh Sách</button>
        <button class="btn-pill light" onclick="selectAllBoxes()">Chọn Tất Cả</button>
        <button class="btn-pill danger" onclick="clearAllBoxes()">Bỏ Chọn</button>
      </div>
      <div style="font-size:11.5px; font-weight:700; color:var(--txt-1); margin-bottom:8px;">
        Đã chọn: <span id="selected-count" style="color:var(--sakura); font-weight:900;">0</span> hội thoại
      </div>
      <div id="box-list" style="max-height:360px; overflow-y:auto; display:flex; flex-direction:column; gap:6px;">
        <div style="text-align:center; padding:24px; color:var(--txt-2); font-size:11.5px;">Chưa nạp hội thoại. Vui lòng chọn tài khoản và nhấn "Nạp Danh Sách".</div>
      </div>
    </div>
  </div>

  <!-- ================= TAB 3: TẬP TIN ================= -->
  <div class="panel" id="panel-files">
    <div class="card">
      <h2><span class="card-header-icon">📂 Tải Lên Tập Tin Văn Bản (.txt)</span></h2>
      <div class="form-group">
        <label>Chọn Tệp Văn Bản Chứa Dòng/Khối Nội Dung</label>
        <input type="file" id="file-input" accept=".txt" onchange="handleFileSelect(this)">
      </div>
      <button class="btn-pill primary full" onclick="uploadFile()">Lưu Vào Hệ Thống</button>
    </div>

    <div class="card">
      <h2><span class="card-header-icon">📄 Tập Tin Đã Lưu</span></h2>
      <div id="files-list">
        <div style="text-align:center; padding:20px; color:var(--txt-2); font-size:11.5px;">Chưa có tập tin nào.</div>
      </div>
    </div>
  </div>

  <!-- ================= TAB 4: PHÁT TIN ================= -->
  <div class="panel" id="panel-spam">
    <div class="card">
      <h2><span class="card-header-icon">🚀 Cấu Hình & Chế Độ Truyền Phát</span></h2>
      
      <div class="form-group">
        <label>Chọn Nguồn Văn Bản</label>
        <select id="spam-file-select">
          <option value="">-- Nhập nội dung trực tiếp bên dưới --</option>
        </select>
      </div>

      <div class="form-group">
        <label>Nội Dung Trực Tiếp (Mỗi dòng một khối)</label>
        <textarea id="spam-direct-text" rows="3" placeholder="Nhập nội dung truyền phát..."></textarea>
      </div>

      <div class="form-group">
        <label>Chế Độ Vận Hành (ThreeUI Protocol)</label>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:6px;">
          <button class="btn-pill light mode-btn active" data-mode="fast" onclick="setMode('fast', this)">⚡ Siêu Tốc</button>
          <button class="btn-pill light mode-btn" data-mode="block" onclick="setMode('block', this)">📦 Khối Ngôn Từ</button>
          <button class="btn-pill light mode-btn" data-mode="stream" onclick="setMode('stream', this)">🌊 Tách Dòng</button>
          <button class="btn-pill light mode-btn" data-mode="multi" onclick="setMode('multi', this)">🌪️ Bão Đa Điểm</button>
          <button class="btn-pill light mode-btn" data-mode="tagall" onclick="setMode('tagall', this)">📢 Báo Danh Toàn Nhóm</button>
          <button class="btn-pill light mode-btn" data-mode="rainbow" onclick="setMode('rainbow', this)">🌈 Quang Phổ</button>
        </div>
      </div>

      <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
        <div class="form-group">
          <label>Độ Trễ Giữa Mỗi Lần Gửi (Giây)</label>
          <input type="number" id="spam-delay" value="0.2" step="0.05" min="0.05">
        </div>
        <div class="form-group">
          <label>Biểu Tượng Cảm Xúc Kèm Theo</label>
          <input type="number" id="spam-icon-count" value="1" min="0" max="6">
        </div>
      </div>

      <div class="form-group">
        <label>Tùy Chọn Bổ Sung</label>
        <div style="display:flex; flex-wrap:wrap; gap:14px; font-size:12px; font-weight:700; color:var(--txt-1); margin-top:4px;">
          <label style="display:inline-flex; align-items:center; gap:6px; cursor:pointer;">
            <input type="checkbox" id="tg-all" checked> <span>Nhắc tên toàn nhóm (@All)</span>
          </label>
          <label style="display:inline-flex; align-items:center; gap:6px; cursor:pointer;">
            <input type="checkbox" id="tg-heading" checked> <span>Chữ in đậm nổi bật</span>
          </label>
          <label style="display:inline-flex; align-items:center; gap:6px; cursor:pointer;">
            <input type="checkbox" id="tg-emoji" checked> <span>Thêm biểu tượng cảm xúc</span>
          </label>
        </div>
      </div>

      <div class="form-group">
        <label>Chọn Bảng Màu Zalo Palette</label>
        <div id="fixed-colors-wrap" style="display:flex; flex-wrap:wrap; gap:6px; max-height:100px; overflow-y:auto; padding:4px;"></div>
      </div>

      <div style="display:flex; gap:10px; margin-top:14px;">
        <button class="btn-pill primary full" onclick="startSpam()">▶ Khởi Chạy Tiến Trình</button>
        <button class="btn-pill danger full" onclick="stopAll()">⏹ Dừng Tất Cả</button>
      </div>
    </div>

    <div class="card">
      <h2><span class="card-header-icon">📊 Bảng Giám Sát Tiến Trình</span></h2>
      <div class="table-responsive">
        <table class="table">
          <thead>
            <tr>
              <th>Mã Nhiệm Vụ</th>
              <th>Loại</th>
              <th>Mục Tiêu</th>
              <th>Thành Công</th>
              <th>Lỗi</th>
              <th>Trạng Thái</th>
              <th>Thao Tác</th>
            </tr>
          </thead>
          <tbody id="tasks-tbody">
            <tr><td colspan="7" style="text-align:center; color:var(--txt-2); padding:16px;">Chưa có nhiệm vụ đang chạy.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ================= TAB 5: ĐỔI LOGO & THƯƠNG HIỆU (DEDICATED TAB) ================= -->
  <div class="panel" id="panel-logo">
    <div class="card">
      <h2><span class="card-header-icon">🌸 Tùy Biến Ảnh Logo & Thương Hiệu</span></h2>
      <p style="font-size:11.5px; color:var(--txt-2); margin-bottom:18px;">
        Thêm hoặc đổi ảnh Logo trang web theo sở thích của bạn. Ảnh Logo sẽ được lưu vĩnh viễn trên máy chủ và cập nhật tức thì trên toàn bộ giao diện!
      </p>

      <div class="logo-manager-grid">
        <div class="logo-preview-box">
          <img id="theme-logo-preview" src="{{ logo_url }}" onerror="this.onerror=null; this.src='""" + DEFAULT_LOGO_DATA_URI + """'">
        </div>
        <div>
          <div style="font-size:13px; font-weight:800; color:var(--txt-0); margin-bottom:4px;">Logo Hiện Tại Của Trang Web</div>
          <p style="font-size:11px; color:var(--txt-2); margin-bottom:12px;">Hỗ trợ ảnh PNG, JPG, JPEG, SVG, WebP, GIF. Nhấn nút bên dưới để chọn ảnh từ máy:</p>
          <div style="display:flex; flex-wrap:wrap; gap:8px;">
            <input type="file" id="logo-file-picker" accept="image/*" style="display:none;" onchange="uploadLogoFile(this)">
            <button class="btn-pill primary" onclick="document.getElementById('logo-file-picker').click()">📁 Chọn Ảnh Từ Máy (Tự Động Lưu)</button>
            <button class="btn-pill danger" onclick="resetDefaultLogo()">↺ Đặt Lại Mặc Định</button>
          </div>
        </div>
      </div>

      <div class="form-group" style="margin-top:20px;">
        <label>Hoặc Dán Đường Dẫn Ảnh Trực Tuyến (URL)</label>
        <div style="display:flex; gap:8px;">
          <input type="text" id="logo-url-input" placeholder="https://example.com/logo.png">
          <button class="btn-pill dark" style="white-space:nowrap;" onclick="saveLogoUrl()">💾 Lưu URL</button>
        </div>
      </div>

      <div class="form-group" style="margin-top:16px;">
        <label>Tùy Biến Tên Tiêu Đề Trang Web</label>
        <div style="display:flex; gap:8px;">
          <input type="text" id="web-title-input" value="{{ web_title }}" placeholder="Nhập tên tiêu đề web...">
          <button class="btn-pill primary" style="white-space:nowrap;" onclick="saveWebTitle()">🌸 Cập Nhật</button>
        </div>
      </div>
    </div>
  </div>

  <!-- ================= TAB 6: CÀI ĐẶT & HỆ THỐNG ================= -->
  <div class="panel" id="panel-settings">
    <div class="card">
      <h2><span class="card-header-icon">🛡️ Trạng Thái Phòng Vệ & Giám Sát</span></h2>
      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:10px; margin-bottom:16px;">
        <div style="background:#fdf2f4; border:1px solid #fecdd3; border-radius:14px; padding:12px; text-align:center;">
          <div style="font-size:10px; color:var(--txt-2); font-weight:700;">LƯỢT QUÉT</div>
          <div id="stat-screened" style="font-size:20px; font-weight:900; color:var(--txt-0);">0</div>
        </div>
        <div style="background:#fdf2f4; border:1px solid #fecdd3; border-radius:14px; padding:12px; text-align:center;">
          <div style="font-size:10px; color:var(--txt-2); font-weight:700;">ĐÃ NGĂN CHẶN</div>
          <div id="stat-mitigated" style="font-size:20px; font-weight:900; color:#e11d48;">0</div>
        </div>
        <div style="background:#fdf2f4; border:1px solid #fecdd3; border-radius:14px; padding:12px; text-align:center;">
          <div style="font-size:10px; color:var(--txt-2); font-weight:700;">IP ĐANG KHÓA</div>
          <div id="stat-banned" style="font-size:20px; font-weight:900; color:#b91c1c;">0</div>
        </div>
      </div>
      <button class="btn-pill light" onclick="loadSecurityStats()">Làm Mới Số Liệu</button>
    </div>

    <div class="card">
      <h2><span class="card-header-icon">📜 Nhật Ký Hoạt Động Hệ Thống</span></h2>
      <div id="security-logs-list" style="max-height:220px; overflow-y:auto; font-family:monospace; font-size:11px; background:#fff; border:1px solid var(--border-color); border-radius:12px; padding:10px;">
        Đang nạp nhật ký...
      </div>
    </div>
  </div>

</div>

<!-- THANH ĐIỀU HƯỚNG DOCK 6 NÚT CHUẨN ĐẸP -->
<div class="bottom-dock">
  <button class="dock-btn active" data-tab="accounts" onclick="switchTab('accounts')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
    <span>Tài khoản</span>
  </button>
  <button class="dock-btn" data-tab="boxes" onclick="switchTab('boxes')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
    <span>Hội thoại</span>
  </button>
  <button class="dock-btn" data-tab="files" onclick="switchTab('files')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
    <span>Tập tin</span>
  </button>
  <button class="dock-btn" data-tab="spam" onclick="switchTab('spam')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
    <span>Phát tin</span>
  </button>
  <button class="dock-btn" data-tab="logo" onclick="switchTab('logo')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
    <span>Đổi Logo</span>
  </button>
  <button class="dock-btn" data-tab="settings" onclick="switchTab('settings')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
    <span>Cài đặt</span>
  </button>
</div>
"""


# ============================================================
# LOGIC JAVASCRIPT ĐIỀU HÀNH PHÍA TRÌNH DUYỆT (THREEUI CLIENT)
# ============================================================

CLIENT_JS = """
<script>
// ==========================================
// TOAST THÔNG BÁO THÔNG MINH
// ==========================================
var Toast = (function(){
  var stack = null;
  function ensure(){
    if(!stack) stack = document.getElementById('toast-stack');
    return stack;
  }
  function show(msg, title, duration){
    duration = duration || 1600;
    var s = ensure();
    if(!s) return;
    s.querySelectorAll('.toast').forEach(el => el.remove());

    var el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = '<div class="t-head">🌸 ' + (title || 'Thông Báo') + '</div>' +
                   '<div class="t-body">' + msg + '</div>';
    s.appendChild(el);

    var timer = setTimeout(function(){
      el.remove();
    }, duration);
    el.addEventListener('click', function(){
      clearTimeout(timer);
      el.remove();
    });
  }
  return {
    success: (m, t, d) => show(m, t || 'Thành công', d),
    error: (m, t, d) => show(m, t || 'Lỗi xử lý', d || 2000),
    info: (m, t, d) => show(m, t || 'Thông báo', d)
  };
})();

// ==========================================
// THANH ĐO FPS THỜI GIAN THỰC NHẢY LIÊN TỤC
// ==========================================
(function initLiveFpsMeter(){
  var fpsVal = document.getElementById('fps-val');
  var fpsBadge = document.getElementById('fps-badge');
  if(!fpsVal) return;

  var lastFrameTime = performance.now();
  var deltaTimes = [];
  var lastUpdate = performance.now();

  function renderFps(now){
    var delta = now - lastFrameTime;
    lastFrameTime = now;
    if(delta > 0 && delta < 200){
      deltaTimes.push(delta);
      if(deltaTimes.length > 25) deltaTimes.shift();
    }

    // Cập nhật số liệu FPS mỗi 220ms để số nhảy sinh động, mượt mà và thực tế
    if(now - lastUpdate >= 220 && deltaTimes.length > 0){
      var sum = 0;
      for(var i = 0; i < deltaTimes.length; i++) sum += deltaTimes[i];
      var avgDelta = sum / deltaTimes.length;
      var rawFps = 1000 / avgDelta;

      // Tạo dao động khung hình tự nhiên micro-jitter xung quanh tốc độ máy
      var jitter = (Math.random() - 0.5) * 1.4;
      var currentFps = Math.min(120, Math.max(15, Math.round(rawFps + jitter)));

      fpsVal.textContent = currentFps;

      if(fpsBadge){
        if(currentFps >= 50){
          fpsBadge.style.color = '#059669';
          fpsBadge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
        } else if(currentFps >= 28){
          fpsBadge.style.color = '#d97706';
          fpsBadge.style.borderColor = 'rgba(245, 158, 11, 0.4)';
        } else {
          fpsBadge.style.color = '#dc2626';
          fpsBadge.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        }
      }
      lastUpdate = now;
    }

    requestAnimationFrame(renderFps);
  }
  requestAnimationFrame(renderFps);
})();

// ==========================================
// ĐIỀU HƯỚNG 6 TABS CHUẨN
// ==========================================
function switchTab(tabName){
  document.querySelectorAll('.bottom-dock .dock-btn').forEach(function(b){
    b.classList.toggle('active', b.getAttribute('data-tab') === tabName);
  });
  document.querySelectorAll('.panel').forEach(function(p){
    p.classList.toggle('active', p.id === 'panel-' + tabName);
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });

  if(tabName === 'accounts') loadAccounts();
  if(tabName === 'files') loadFiles();
  if(tabName === 'spam') { loadTasks(); loadColors(); }
  if(tabName === 'settings') loadSecurityStats();
}

// ==========================================
// GỌI API BACKEND CHUNG
// ==========================================
async function api(url, opts = {}){
  try {
    var r = await fetch(url, Object.assign({}, opts, {
      headers: Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {})
    }));
    return await r.json();
  } catch(e){
    return { error: 'Lỗi kết nối máy chủ: ' + e.message };
  }
}

// ==========================================
// BỘ QUẢN LÝ LOGO VÀ THƯƠNG HIỆU WEB
// ==========================================
async function uploadLogoFile(input){
  if(!input.files || !input.files.length) return;
  var file = input.files[0];
  var fd = new FormData();
  fd.append('logo', file);

  Toast.info('Đang lưu ảnh Logo lên máy chủ...');
  try {
    var res = await fetch('/api/upload_logo', { method: 'POST', body: fd }).then(x => x.json());
    if(res.ok){
      Toast.success('Đã cập nhật và lưu Logo mới thành công!');
      var newUrl = res.logo_url + '?t=' + Date.now();
      updateLogoImagesInDom(newUrl);
      input.value = '';
    } else {
      Toast.error(res.error || 'Lỗi khi tải ảnh logo');
    }
  } catch(err){
    Toast.error('Lỗi tải ảnh: ' + err.message);
  }
}

async function saveLogoUrl(){
  var inp = document.getElementById('logo-url-input');
  var val = inp.value.trim();
  if(!val) return Toast.error('Vui lòng nhập đường dẫn ảnh hợp lệ');

  Toast.info('Đang lưu liên kết Logo...');
  var res = await api('/api/update_logo_url', {
    method: 'POST',
    body: JSON.stringify({ url: val })
  });

  if(res.ok){
    Toast.success('Đã lưu Logo từ liên kết thành công!');
    updateLogoImagesInDom(res.logo_url);
    inp.value = '';
  } else {
    Toast.error(res.error || 'Không thể lưu logo');
  }
}

async function resetDefaultLogo(){
  if(!confirm('Bạn có chắc chắn muốn đặt lại Logo mặc định?')) return;
  Toast.info('Đang khôi phục logo...');
  var res = await api('/api/reset_logo', { method: 'POST' });
  if(res.ok){
    Toast.success('Đã đặt lại Logo mặc định thành công!');
    updateLogoImagesInDom(res.logo_url);
  } else {
    Toast.error(res.error || 'Lỗi khôi phục logo');
  }
}

async function saveWebTitle(){
  var inp = document.getElementById('web-title-input');
  var val = inp.value.trim();
  if(!val) return Toast.error('Vui lòng nhập tên tiêu đề web');

  var res = await api('/api/update_title', {
    method: 'POST',
    body: JSON.stringify({ title: val })
  });

  if(res.ok){
    Toast.success('Cập nhật tên web thành công!');
    document.getElementById('header-web-title').textContent = res.title;
    document.title = res.title;
  } else {
    Toast.error(res.error || 'Không thể cập nhật tiêu đề');
  }
}

function updateLogoImagesInDom(url){
  var hl = document.getElementById('header-logo');
  if(hl) hl.src = url;
  var tp = document.getElementById('theme-logo-preview');
  if(tp) tp.src = url;
  var pl = document.getElementById('preloader-logo-img');
  if(pl) pl.src = url;
}

// ==========================================
// QUẢN LÝ TÀI KHOẢN
// ==========================================
async function loadAccounts(){
  var accs = await api('/api/accounts');
  if(!Array.isArray(accs)) accs = [];
  var tb = document.getElementById('accounts-tbody');
  if(!accs.length){
    tb.innerHTML = '<tr><td colspan="3" style="text-align:center; color:var(--txt-2); padding:16px;">Chưa có tài khoản nào.</td></tr>';
  } else {
    tb.innerHTML = accs.map(a => `
      <tr>
        <td style="font-weight:700;">${a.label} (${a.display_name || 'Chưa định danh'})</td>
        <td>
          <span style="font-size:11px; font-weight:800; color:${a.status === 'live' ? '#059669' : '#dc2626'}; background:${a.status === 'live' ? '#ecfdf5' : '#fee2e2'}; padding:3px 8px; border-radius:99px;">
            ${a.status === 'live' ? 'Hoạt động' : 'Hết hạn'}
          </span>
        </td>
        <td>
          <button class="btn-xs" onclick="checkAccount(${a.id})">Kiểm tra</button>
          <button class="btn-xs danger" onclick="deleteAccount(${a.id})">Xóa</button>
        </td>
      </tr>
    `).join('');
  }

  var s1 = document.getElementById('load-acc-select');
  if(s1){
    s1.innerHTML = '<option value="">-- Chọn tài khoản --</option>' + accs.map(a => `
      <option value="${a.id}">${a.label} (${a.display_name || 'Zalo'})</option>
    `).join('');
  }
}

async function addAccount(){
  var label = document.getElementById('add-label').value.trim();
  var imei = document.getElementById('add-imei').value.trim();
  var cookies = document.getElementById('add-cookies').value.trim();
  if(!imei || !cookies) return Toast.error('Vui lòng nhập đầy đủ IMEI và Token');

  Toast.info('Đang kiểm tra và thêm tài khoản...');
  var res = await api('/api/accounts/add', {
    method: 'POST',
    body: JSON.stringify({ label: label || 'Tài khoản', imei: imei, cookies: cookies })
  });

  if(res.ok){
    Toast.success('Thêm tài khoản thành công!');
    document.getElementById('add-label').value = '';
    document.getElementById('add-imei').value = '';
    document.getElementById('add-cookies').value = '';
    loadAccounts();
  } else {
    Toast.error(res.error || 'Lỗi thêm tài khoản');
  }
}

async function checkAccount(id){
  Toast.info('Đang kiểm tra trạng thái...');
  var res = await api('/api/accounts/' + id + '/check', { method: 'POST' });
  if(res.ok){
    Toast.success('Tài khoản hoạt động tốt (' + res.status + ')');
  } else {
    Toast.error('Tài khoản lỗi: ' + (res.error || ''));
  }
  loadAccounts();
}

async function checkAllAccounts(){
  Toast.info('Đang kiểm tra toàn bộ danh sách...');
  var res = await api('/api/accounts/check_all', { method: 'POST' });
  Toast.success('Hoàn tất: ' + res.live + '/' + res.total + ' tài khoản hoạt động');
  loadAccounts();
}

async function deleteAccount(id){
  if(!confirm('Xác nhận xóa tài khoản này?')) return;
  await api('/api/accounts/' + id, { method: 'DELETE' });
  Toast.success('Đã xóa tài khoản');
  loadAccounts();
}

// ==========================================
// QUẢN LÝ HỘI THOẠI & NHÓM
// ==========================================
var loadedBoxes = [];
var selectedBoxes = [];

async function loadBoxes(){
  var sel = document.getElementById('load-acc-select');
  var aid = sel ? sel.value : '';
  if(!aid) return Toast.error('Vui lòng chọn tài khoản quét trước');

  Toast.info('Đang nạp danh sách hội thoại từ Zalo...');
  var res = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
  if(res.error) return Toast.error(res.error);

  var groups = (res.groups || []).map(g => ({ id: g.id, name: g.name, type: 'group', members: g.totalMember }));
  var friends = (res.friends || []).map(f => ({ id: f.id, name: f.name, type: 'friend', avatar: f.avatar }));
  loadedBoxes = groups.concat(friends);

  var bl = document.getElementById('box-list');
  if(!loadedBoxes.length){
    bl.innerHTML = '<div style="text-align:center; padding:20px; color:var(--txt-2);">Không tìm thấy hội thoại nào.</div>';
    return;
  }

  bl.innerHTML = loadedBoxes.map(b => `
    <div class="box-item" id="box-item-${b.id}" onclick="toggleBox('${b.id}', '${b.type}', '${encodeURIComponent(b.name)}')" style="display:flex; align-items:center; justify-content:space-between; padding:10px 14px; background:#fff; border:1px solid var(--border-color); border-radius:14px; cursor:pointer; transition:all 0.2s;">
      <div style="display:flex; align-items:center; gap:8px;">
        <span>${b.type === 'group' ? '👥' : '👤'}</span>
        <div style="font-size:12px; font-weight:700; color:var(--txt-0);">${b.name}</div>
      </div>
      <span style="font-size:11px; color:var(--txt-2);">${b.type === 'group' ? (b.members + ' thành viên') : 'Cá nhân'}</span>
    </div>
  `).join('');
}

function toggleBox(id, type, encName){
  var name = decodeURIComponent(encName);
  var el = document.getElementById('box-item-' + id);
  var idx = selectedBoxes.findIndex(x => x.id === id);

  if(idx >= 0){
    selectedBoxes.splice(idx, 1);
    if(el){ el.style.borderColor = 'var(--border-color)'; el.style.background = '#fff'; }
  } else {
    selectedBoxes.push({ id: id, type: type, name: name });
    if(el){ el.style.borderColor = 'var(--sakura)'; el.style.background = '#fff0f5'; }
  }
  document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function selectAllBoxes(){
  selectedBoxes = loadedBoxes.map(b => ({ id: b.id, type: b.type, name: b.name }));
  document.querySelectorAll('.box-item').forEach(el => {
    el.style.borderColor = 'var(--sakura)';
    el.style.background = '#fff0f5';
  });
  document.getElementById('selected-count').textContent = selectedBoxes.length;
  Toast.info('Đã chọn tất cả ' + selectedBoxes.length + ' hội thoại');
}

function clearAllBoxes(){
  selectedBoxes = [];
  document.querySelectorAll('.box-item').forEach(el => {
    el.style.borderColor = 'var(--border-color)';
    el.style.background = '#fff';
  });
  document.getElementById('selected-count').textContent = '0';
  Toast.info('Đã bỏ chọn toàn bộ');
}

// ==========================================
// QUẢN LÝ TẬP TIN VĂN BẢN
// ==========================================
function handleFileSelect(input){
  if(input.files && input.files.length){
    Toast.info('Đã chọn tệp: ' + input.files[0].name);
  }
}

async function uploadFile(){
  var inp = document.getElementById('file-input');
  if(!inp.files || !inp.files.length) return Toast.error('Vui lòng chọn tệp tin .txt trước');

  var fd = new FormData();
  fd.append('file', inp.files[0]);
  Toast.info('Đang nạp tập tin vào hệ thống...');

  try {
    var res = await fetch('/api/files/upload', { method: 'POST', body: fd }).then(x => x.json());
    if(res.ok){
      Toast.success('Đã lưu tập tin thành công (' + res.lines + ' dòng)!');
      inp.value = '';
      loadFiles();
    } else {
      Toast.error(res.error || 'Lỗi tải tệp');
    }
  } catch(e){
    Toast.error('Lỗi kết nối: ' + e.message);
  }
}

async function loadFiles(){
  var files = await api('/api/files');
  if(!Array.isArray(files)) files = [];

  var fl = document.getElementById('files-list');
  if(!files.length){
    fl.innerHTML = '<div style="text-align:center; padding:20px; color:var(--txt-2);">Chưa có tập tin nào.</div>';
  } else {
    fl.innerHTML = files.map(f => `
      <div style="display:flex; align-items:center; justify-content:space-between; padding:10px 14px; background:#fff; border:1px solid var(--border-color); border-radius:14px; margin-bottom:6px;">
        <div>
          <div style="font-size:12.5px; font-weight:700; color:var(--txt-0);">📄 ${f.filename}</div>
          <div style="font-size:10.5px; color:var(--txt-2);">${f.lines} dòng • ${(f.size / 1024).toFixed(1)} KB</div>
        </div>
        <button class="btn-xs danger" onclick="deleteFile(${f.id})">Xóa</button>
      </div>
    `).join('');
  }

  var sfs = document.getElementById('spam-file-select');
  if(sfs){
    sfs.innerHTML = '<option value="">-- Nhập nội dung trực tiếp bên dưới --</option>' + files.map(f => `
      <option value="${f.id}">${f.filename} (${f.lines} dòng)</option>
    `).join('');
  }
}

async function deleteFile(id){
  if(!confirm('Xác nhận xóa tệp tin này?')) return;
  await api('/api/files/' + id, { method: 'DELETE' });
  Toast.success('Đã xóa tệp tin');
  loadFiles();
}

// ==========================================
// CẤU HÌNH & KHỞI CHẠY TIẾN TRÌNH TRUYỀN TIN
// ==========================================
var currentMode = 'fast';
var selectedFixedColor = 'pink';

function setMode(m, btn){
  currentMode = m;
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  if(btn) btn.classList.add('active');
  Toast.info('Đã chọn chế độ: ' + btn.textContent.trim());
}

async function loadColors(){
  var cols = await api('/api/colors');
  var wrap = document.getElementById('fixed-colors-wrap');
  if(!wrap) return;

  if(cols && typeof cols === 'object'){
    wrap.innerHTML = Object.keys(cols).map(c => `
      <button type="button" class="color-btn ${c === selectedFixedColor ? 'active' : ''}" onclick="selectFixedColor('${c}')" style="display:inline-flex; align-items:center; gap:4px; padding:4px 8px; border-radius:99px; font-size:10.5px; font-weight:700; border:1px solid ${c === selectedFixedColor ? 'var(--sakura)' : 'var(--border-color)'}; background:#fff; cursor:pointer;">
        <span style="width:10px; height:10px; border-radius:50%; background:#${cols[c]}; display:inline-block;"></span>
        <span>${c}</span>
      </button>
    `).join('');
  }
}

function selectFixedColor(c){
  selectedFixedColor = c;
  loadColors();
  Toast.info('Đã chọn màu sắc: ' + c);
}

async function startSpam(){
  if(!selectedBoxes.length) return Toast.error('Vui lòng chọn ít nhất 1 hội thoại ở Tab "Hội thoại"');

  var fid = document.getElementById('spam-file-select').value;
  var directText = document.getElementById('spam-direct-text').value.trim();
  var delay = parseFloat(document.getElementById('spam-delay').value) || 0.2;
  var iconCount = parseInt(document.getElementById('spam-icon-count').value) || 0;
  var tagAll = document.getElementById('tg-all').checked;
  var isHeading = document.getElementById('tg-heading').checked;
  var useEmoji = document.getElementById('tg-emoji').checked;

  var blocks = [];
  if(directText){
    blocks = directText.split('\\n').map(x => x.trim()).filter(Boolean);
  }

  var payload = {
    targets: selectedBoxes,
    file_id: fid ? parseInt(fid) : null,
    blocks: blocks,
    delay: delay,
    use_emoji: useEmoji,
    icon_count: iconCount,
    tag_all: tagAll,
    is_heading: isHeading,
    mode: currentMode,
    color_mode: currentMode === 'rainbow' ? 'rainbow' : 'fixed',
    fixed_color: selectedFixedColor
  };

  Toast.info('Đang gửi lệnh khởi chạy...');
  var res = await api('/api/tasks/start', {
    method: 'POST',
    body: JSON.stringify(payload)
  });

  if(res.ok){
    Toast.success('Khởi chạy tiến trình thành công!');
    loadTasks();
  } else {
    Toast.error(res.error || 'Lỗi khởi chạy');
  }
}

async function stopAll(){
  await api('/api/tasks/stop_all', { method: 'POST' });
  Toast.info('Đã gửi lệnh dừng toàn bộ tiến trình');
  loadTasks();
}

async function loadTasks(){
  var tasks = await api('/api/tasks');
  if(!Array.isArray(tasks)) tasks = [];
  var tb = document.getElementById('tasks-tbody');
  if(!tasks.length){
    tb.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--txt-2); padding:16px;">Chưa có nhiệm vụ đang chạy.</td></tr>';
  } else {
    tb.innerHTML = tasks.map(t => `
      <tr>
        <td style="font-weight:700;">#${t.id}</td>
        <td>${t.task_type}</td>
        <td>${t.targets_count}</td>
        <td style="color:#059669; font-weight:800;">${t.sent_count}</td>
        <td style="color:#dc2626; font-weight:800;">${t.error_count}</td>
        <td>
          <span style="font-size:10.5px; font-weight:800; color:${t.status === 'running' ? '#059669' : '#64748b'};">
            ${t.status === 'running' ? 'Đang chạy' : 'Đã dừng'}
          </span>
        </td>
        <td>
          ${t.status === 'running' ? `<button class="btn-xs danger" onclick="stopTask(${t.id})">Dừng</button>` : '-'}
        </td>
      </tr>
    `).join('');
  }
}

async function stopTask(tid){
  await api('/api/tasks/' + tid + '/stop', { method: 'POST' });
  Toast.info('Đã dừng nhiệm vụ #' + tid);
  loadTasks();
}

// ==========================================
// GIÁM SÁT PHÒNG VỆ HỆ THỐNG
// ==========================================
async function loadSecurityStats(){
  var stats = await api('/api/security_stats');
  if(!stats || stats.error) return;

  var s1 = document.getElementById('stat-screened');
  var s2 = document.getElementById('stat-mitigated');
  var s3 = document.getElementById('stat-banned');
  if(s1) s1.textContent = stats.total_screened || 0;
  if(s2) s2.textContent = stats.total_mitigated || 0;
  if(s3) s3.textContent = stats.active_banned_count || 0;

  var sl = document.getElementById('security-logs-list');
  if(sl && Array.isArray(stats.recent_logs)){
    if(!stats.recent_logs.length){
      sl.innerHTML = 'Hệ thống an toàn. Chưa có cảnh báo nào.';
    } else {
      sl.innerHTML = stats.recent_logs.map(l => `
        <div style="padding:4px 0; border-bottom:1px solid #fdf2f4;">
          <span style="color:#64748b;">[${l.time}]</span>
          <span style="color:#e11d48; font-weight:700;">${l.type}:</span>
          <span>${l.details}</span>
          <span style="color:#94a3b8;">(${l.ip})</span>
        </div>
      `).join('');
    }
  }
}

// ==========================================
// CANVAS CÁNH HOA & LÁ ANH ĐÀO RƠI 60FPS
// ==========================================
(function(){
  var canvas = document.getElementById('sakura-canvas');
  if(!canvas) return;
  var ctx = canvas.getContext('2d');
  var width = window.innerWidth;
  var height = window.innerHeight;
  canvas.width = width;
  canvas.height = height;

  window.addEventListener('resize', function(){
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = width;
    canvas.height = height;
  });

  var items = [];
  var itemCount = 40;
  for(var i = 0; i < itemCount; i++){
    items.push({
      x: Math.random() * width,
      y: Math.random() * height,
      size: Math.random() * 9 + 6,
      speedX: Math.random() * 1.5 - 0.5,
      speedY: Math.random() * 1.4 + 0.8,
      rotation: Math.random() * Math.PI * 2,
      rotationSpeed: (Math.random() - 0.5) * 0.03,
      isLeaf: (i % 5 === 0), // 20% là lá cây xanh non, 80% là cánh hoa anh đào
      opacity: Math.random() * 0.5 + 0.45
    });
  }

  function animate(){
    ctx.clearRect(0, 0, width, height);

    for(var j = 0; j < items.length; j++){
      var p = items[j];
      p.x += p.speedX;
      p.y += p.speedY;
      p.rotation += p.rotationSpeed;

      if(p.y > height + 20){ p.y = -20; p.x = Math.random() * width; }
      if(p.x > width + 20) p.x = -20;
      if(p.x < -20) p.x = width + 20;

      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rotation);
      ctx.globalAlpha = p.opacity;

      if(p.isLeaf){
        // Vẽ lá cây xanh non nghệ thuật
        ctx.fillStyle = '#10b981';
        ctx.beginPath();
        ctx.ellipse(0, 0, p.size * 0.8, p.size * 0.4, 0, 0, Math.PI * 2);
        ctx.fill();
      } else {
        // Vẽ cánh hoa anh đào mềm mại
        ctx.fillStyle = '#ffb6c1';
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.quadraticCurveTo(p.size * 0.8, -p.size * 0.6, 0, -p.size);
        ctx.quadraticCurveTo(-p.size * 0.8, -p.size * 0.6, 0, 0);
        ctx.fill();

        ctx.fillStyle = '#ff69b4';
        ctx.beginPath();
        ctx.arc(0, -p.size * 0.2, p.size * 0.15, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.restore();
    }

    requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);
})();

// KHỞI ĐỘNG HỆ THỐNG
loadAccounts();
loadFiles();
loadTasks();
loadColors();
setInterval(loadTasks, 4000);
</script>
</body>
</html>
"""


# ============================================================
# CÁC ĐƯỜNG DẪN ROUTE VÀ API ĐIỀU HÀNH HỆ THỐNG
# ============================================================

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "alb_threeui_sakura_2026_super_key")

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

@app.before_request
def security_check():
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1").split(",")[0].strip()
    if request.path.startswith("/static") or request.path in ["/health", "/healthz"]:
        return None
    allowed, msg = FIREWALL.is_allowed(client_ip)
    if not allowed:
        return Response(f"<h3 style='color:#e11d48; text-align:center; margin-top:50px;'>Phát hiện lưu lượng truy cập bất thường</h3><p style='text-align:center;'>{msg}</p>", status=429, mimetype="text/html")
    return None

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)

@app.route("/health")
@app.route("/healthz")
def health_check():
    return jsonify({"status": "ok", "time": time.time()})

@app.route("/verify_gate")
def verify_gate():
    return render_template_string(HTML_GATE)

@app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    logo_url = get_setting("logo_url", DEFAULT_LOGO_DATA_URI)
    web_title = get_setting("web_title", "I LOVE NGỌC HÂN 🌸")
    author_name = get_setting("author_name", "Phạm Anh Khôi")

    full_template = HTML_APP + CLIENT_JS
    return render_template_string(
        full_template,
        logo_url=logo_url,
        web_title=web_title,
        author_name=author_name
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    logo_url = get_setting("logo_url", DEFAULT_LOGO_DATA_URI)
    web_title = get_setting("web_title", "I LOVE NGỌC HÂN 🌸")
    author_name = get_setting("author_name", "Phạm Anh Khôi")

    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        return render_template_string(
            HTML_LOGIN,
            error="Mật khẩu truy cập không chính xác!",
            logo_url=logo_url,
            web_title=web_title,
            author_name=author_name
        )

    return render_template_string(
        HTML_LOGIN,
        logo_url=logo_url,
        web_title=web_title,
        author_name=author_name
    )

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# API QUẢN LÝ LOGO VÀ THƯƠNG HIỆU
@app.route("/api/upload_logo", methods=["POST"])
@login_required
def api_upload_logo():
    if "logo" not in request.files:
        return jsonify({"error": "Không tìm thấy tệp ảnh logo tải lên"}), 400
    f = request.files["logo"]
    if not f.filename:
        return jsonify({"error": "Tên tệp không hợp lệ"}), 400

    target_path = os.path.join(STATIC_DIR, "logo.png")
    f.save(target_path)
    new_logo_url = "/static/logo.png"
    set_setting("logo_url", new_logo_url)

    client_ip = request.remote_addr or "127.0.0.1"
    FIREWALL.log_event(client_ip, "Cập Nhật Logo", "Đã tải lên và lưu logo tệp mới")
    return jsonify({"ok": True, "logo_url": new_logo_url})

@app.route("/api/update_logo_url", methods=["POST"])
@login_required
def api_update_logo_url():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Vui lòng nhập đường dẫn ảnh"}), 400

    set_setting("logo_url", url)
    client_ip = request.remote_addr or "127.0.0.1"
    FIREWALL.log_event(client_ip, "Cập Nhật Logo URL", f"Đã lưu logo từ liên kết trực tuyến")
    return jsonify({"ok": True, "logo_url": url})

@app.route("/api/reset_logo", methods=["POST"])
@login_required
def api_reset_logo():
    set_setting("logo_url", DEFAULT_LOGO_DATA_URI)
    return jsonify({"ok": True, "logo_url": DEFAULT_LOGO_DATA_URI})

@app.route("/api/update_title", methods=["POST"])
@login_required
def api_update_title():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Tiêu đề không được để trống"}), 400

    set_setting("web_title", title)
    return jsonify({"ok": True, "title": title})

# API QUẢN LÝ TÀI KHOẢN
@app.route("/api/accounts", methods=["GET"])
@login_required
def api_get_accounts():
    conn = db()
    rows = conn.execute("SELECT id, label, imei, status, display_name, avatar, created_at FROM accounts ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/accounts/add", methods=["POST"])
@login_required
def api_add_account():
    data = request.get_json(silent=True) or {}
    label = (data.get("label") or "Tài khoản").strip()
    imei = (data.get("imei") or "").strip()
    cookies = (data.get("cookies") or "").strip()

    if not imei or not cookies:
        return jsonify({"error": "Vui lòng nhập đủ IMEI và Khóa phiên"}), 400

    try:
        ck_dict = json.loads(cookies) if cookies.startswith("{") else {"zpw_sek": cookies}
        z = Zalo(imei, ck_dict)
        chk = z.check_login()
        st = "live" if chk.get("ok") else "dead"
        display_name = chk.get("name", "Người dùng Zalo")
        avatar = chk.get("avatar", "")
    except Exception as e:
        return jsonify({"error": f"Lỗi khởi tạo tài khoản: {e}"}), 400

    conn = db()
    conn.execute(
        "INSERT INTO accounts (label, imei, cookies, status, display_name, avatar, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (label, imei, json.dumps(ck_dict), st, display_name, avatar, time.time())
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "status": st, "name": display_name})

@app.route("/api/accounts/<int:aid>/check", methods=["POST"])
@login_required
def api_check_account(aid):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Không tìm thấy tài khoản"}), 404

    try:
        z = Zalo(row["imei"], json.loads(row["cookies"]))
        chk = z.check_login()
        st = "live" if chk.get("ok") else "dead"
        name = chk.get("name") or row["display_name"]
        conn.execute("UPDATE accounts SET status = ?, display_name = ? WHERE id = ?", (st, name, aid))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "status": st, "name": name})
    except Exception as e:
        conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": False, "status": "dead", "error": str(e)})

@app.route("/api/accounts/check_all", methods=["POST"])
@login_required
def api_check_all_accounts():
    conn = db()
    rows = conn.execute("SELECT * FROM accounts").fetchall()
    live_count = 0
    for r in rows:
        try:
            z = Zalo(r["imei"], json.loads(r["cookies"]))
            chk = z.check_login()
            st = "live" if chk.get("ok") else "dead"
            if st == "live":
                live_count += 1
            conn.execute("UPDATE accounts SET status = ? WHERE id = ?", (st, r["id"]))
        except Exception:
            conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (r["id"],))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "total": len(rows), "live": live_count})

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
    if not row:
        return jsonify({"error": "Không tìm thấy tài khoản"}), 404

    try:
        z = Zalo(row["imei"], json.loads(row["cookies"]))
        groups = z.groups()
        friends = z.friends()
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
        return jsonify({"ok": True, "members": members})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# API QUẢN LÝ TẬP TIN VĂN BẢN
@app.route("/api/files", methods=["GET"])
@login_required
def api_get_files():
    conn = db()
    rows = conn.execute("SELECT id, filename, lines, size, uploaded_at FROM files ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/files/upload", methods=["POST"])
@login_required
def api_upload_file():
    if "file" not in request.files:
        return jsonify({"error": "Không tìm thấy tập tin"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Tập tin rỗng"}), 400

    safe_name = f"{int(time.time())}_{f.filename}"
    fp = os.path.join(UPLOAD_DIR, safe_name)
    f.save(fp)

    lines_count = 0
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as fl:
            lines = [x.strip() for x in fl if x.strip()]
            lines_count = len(lines)
    except Exception:
        pass

    conn = db()
    cur = conn.execute(
        "INSERT INTO files (filename, filepath, lines, size, uploaded_at) VALUES (?, ?, ?, ?, ?)",
        (f.filename, fp, lines_count, os.path.getsize(fp), time.time())
    )
    fid = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": fid, "filename": f.filename, "lines": lines_count})

@app.route("/api/files/<int:fid>", methods=["DELETE"])
@login_required
def api_delete_file(fid):
    conn = db()
    row = conn.execute("SELECT filepath FROM files WHERE id = ?", (fid,)).fetchone()
    if row and os.path.exists(row["filepath"]):
        try:
            os.remove(row["filepath"])
        except Exception:
            pass
    conn.execute("DELETE FROM files WHERE id = ?", (fid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# API QUẢN LÝ TIẾN TRÌNH TRUYỀN TIN
@app.route("/api/tasks", methods=["GET"])
@login_required
def api_get_tasks():
    with TASK_LOCK:
        res = []
        for tid, tinfo in ACTIVE_TASKS.items():
            res.append({
                "id": tid,
                "task_type": tinfo.get("mode", "fast"),
                "targets_count": len(tinfo.get("targets", [])),
                "sent_count": tinfo["counter"]["sent"],
                "error_count": tinfo["counter"]["err"],
                "status": "stopped" if tinfo["stop_event"].is_set() else "running"
            })
        return jsonify(res)

@app.route("/api/tasks/start", methods=["POST"])
@login_required
def api_start_task():
    data = request.get_json(silent=True) or {}
    targets = data.get("targets") or []
    if not targets:
        return jsonify({"error": "Vui lòng chọn ít nhất 1 hội thoại nhận tin"}), 400

    conn = db()
    accounts = conn.execute("SELECT * FROM accounts WHERE status = 'live'").fetchall()
    if not accounts:
        accounts = conn.execute("SELECT * FROM accounts").fetchall()
    if not accounts:
        conn.close()
        return jsonify({"error": "Không có tài khoản Zalo nào trong hệ thống"}), 400

    # Lấy nội dung từ file hoặc nội dung trực tiếp
    blocks = data.get("blocks") or []
    file_id = data.get("file_id")
    if file_id and not blocks:
        frow = conn.execute("SELECT filepath FROM files WHERE id = ?", (file_id,)).fetchone()
        if frow and os.path.exists(frow["filepath"]):
            try:
                with open(frow["filepath"], "r", encoding="utf-8", errors="ignore") as fl:
                    blocks = [line.strip() for line in fl if line.strip()]
            except Exception:
                pass
    conn.close()

    if not blocks:
        blocks = ["🌸 ALB Forge — ThreeUI Edition 2026"]

    delay = float(data.get("delay", 0.2))
    use_emoji = bool(data.get("use_emoji", True))
    icon_count = int(data.get("icon_count", 1))
    tag_all = bool(data.get("tag_all", True))
    is_heading = bool(data.get("is_heading", True))
    mode = data.get("mode", "fast")
    color_mode = data.get("color_mode", "fixed")
    fixed_color = data.get("fixed_color", "pink")
    tag_users = data.get("tag_users") or []

    task_id = int(time.time() * 1000) % 1000000
    stop_event = threading.Event()
    counter = {"sent": 0, "err": 0}
    lock = threading.Lock()

    workers = []
    for acc in accounts:
        t = threading.Thread(
            target=task_worker,
            args=(
                task_id, dict(acc), targets, blocks, delay,
                use_emoji, icon_count, tag_users, tag_all,
                is_heading, mode, color_mode, fixed_color,
                stop_event, counter, lock
            ),
            daemon=True
        )
        t.start()
        workers.append(t)

    with TASK_LOCK:
        ACTIVE_TASKS[task_id] = {
            "mode": mode,
            "targets": targets,
            "stop_event": stop_event,
            "counter": counter,
            "workers": workers
        }

    return jsonify({"ok": True, "task_id": task_id})

@app.route("/api/tasks/<int:tid>/stop", methods=["POST"])
@login_required
def api_stop_task(tid):
    with TASK_LOCK:
        if tid in ACTIVE_TASKS:
            ACTIVE_TASKS[tid]["stop_event"].set()
    return jsonify({"ok": True})

@app.route("/api/tasks/stop_all", methods=["POST"])
@login_required
def api_stop_all_tasks():
    with TASK_LOCK:
        for tinfo in ACTIVE_TASKS.values():
            tinfo["stop_event"].set()
    return jsonify({"ok": True})

@app.route("/api/colors", methods=["GET"])
@login_required
def api_get_colors():
    return jsonify(ZALO_PALETTE_HEX)

@app.route("/api/security_stats", methods=["GET"])
@login_required
def api_get_security_stats():
    return jsonify(FIREWALL.get_stats())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"ALB Forge ThreeUI Sakura khởi động trên cổng {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
