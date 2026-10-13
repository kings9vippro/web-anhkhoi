# -*- coding: utf-8 -*-
# ==============================================================================
# Bản quyền © Phạm Anh Khôi (Verified ✔) — Ricki Vip
# Tác giả: Phạm Anh Khôi ✔
# Hệ Thống Lưu Cookie/IMEI, Đẩy File Server & Điều Khiển Lệnh Trực Tiếp Zalo / Discord
# ==============================================================================

import os
import re
import sys
import time
import json
import uuid
import base64
import random
import sqlite3
import threading
from datetime import timedelta
from functools import wraps

import requests
from Crypto.Cipher import AES
from flask import (
    Flask, request, jsonify, render_template_string,
    session, send_from_directory
)

# ---------------------------------------------------------
# KHỞI TẠO FLASK APP (TƯƠNG THÍCH 100% GUNICORN RENDER: app:app)
# ---------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ricki_vip_stable_khoi_key_2026_xyz987")
app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024  # Hỗ trợ tải tệp lớn lên tới 150MB
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=365)

DATA_DIR = os.environ.get("DATA_DIR", "/tmp/ricki_web")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "ricki_vip.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------------------------------------------------------
# BIỂU TƯỢNG TICK XANH CHÍNH CHỦ (VERIFIED BADGE SVG)
# ---------------------------------------------------------
SVG_VERIFIED_TICK = r'''<svg class="verified-tick" viewBox="0 0 24 24" aria-label="Verified" role="img"><g><path d="M22.25 12c0-1.43-.88-2.67-2.19-3.34.46-1.39.2-2.9-.81-3.91s-2.52-1.27-3.91-.81c-.66-1.31-1.91-2.19-3.34-2.19s-2.67.88-3.33 2.19c-1.4-.46-2.91-.2-3.92.81s-1.26 2.52-.8 3.91c-1.31.67-2.2 1.91-2.2 3.34s.89 2.67 2.2 3.34c-.46 1.39-.21 2.9.8 3.91s2.52 1.26 3.91.81c.67 1.31 1.91 2.19 3.34 2.19s2.68-.88 3.34-2.19c1.39.45 2.9.2 3.91-.81s1.27-2.52.81-3.91c1.31-.67 2.19-1.91 2.19-3.34zm-11.71 4.2L6.8 12.46l1.41-1.42 2.26 2.26 4.8-5.23 1.47 1.36-6.2 6.77z" fill="#1d9bf0"></path></g></svg>'''

# ---------------------------------------------------------
# CƠ SỞ DỮ LIỆU SQLITE
# ---------------------------------------------------------
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT,
        platform TEXT DEFAULT 'zalo',
        imei TEXT,
        cookies TEXT,
        token TEXT,
        real_name TEXT DEFAULT '',
        status TEXT DEFAULT 'live',
        enabled INTEGER DEFAULT 1,
        created_at REAL
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT,
        filepath TEXT,
        size INTEGER,
        lines INTEGER DEFAULT 0,
        blocks INTEGER,
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
    {"id": "cyan",    "name": "Xanh Ngọc",     "hex": "00b4d8", "badge": "🔵"}
]

COMBAT_ICONS = {
    "fire":      ["🔥", "💥", "⚡", "🌋", "☄️", "🧨"],
    "crown":     ["👑", "💎", "🏆", "⚜️", "🔱", "🌟"],
    "sword":     ["⚔️", "🗡️", "🛡️", "🏹", "💣", "🪓"],
    "skull":     ["💀", "☠️", "👻", "👽", "👾", "😈"],
    "lightning": ["⚡", "🌩️", "🌀", "🌪️", "❄️", "🌊"]
}

def generate_combat_combo(combo_type="mixed", count=3):
    if combo_type == "none" or count <= 0:
        return ""
    if combo_type == "mixed":
        pool = [ic for sub in COMBAT_ICONS.values() for ic in sub]
    else:
        pool = COMBAT_ICONS.get(combo_type, COMBAT_ICONS["fire"])
    chosen = [random.choice(pool) for _ in range(count)]
    return "".join(chosen)

def utf16_len(s):
    if not s:
        return 0
    return len(s.encode("utf-16-le")) // 2

# ---------------------------------------------------------
# THUẬT TOÁN ANTI-BAN ZALO V5 (BẢO TOÀN 100% DẤU TIẾNG VIỆT)
# ---------------------------------------------------------
ZERO_WIDTH_POOL = ["\u200b", "\u200c", "\u200d", "\ufeff"]
SAFE_SPACES = [" ", "  ", " \u200b "]

def apply_antiband_zalo_v5(text):
    if not text:
        return text
    lines = text.split("\n")
    out_lines = []
    for line in lines:
        words = line.split(" ")
        if len(words) > 1:
            new_line = ""
            for i, w in enumerate(words):
                new_line += w
                if w.endswith((",", ".", "!", "?", ":", ";")):
                    new_line += random.choice(ZERO_WIDTH_POOL)
                if i < len(words) - 1:
                    new_line += random.choice(SAFE_SPACES) if random.random() < 0.35 else " "
        else:
            new_line = line
        tail_zw = "".join(random.choice(ZERO_WIDTH_POOL) for _ in range(random.randint(1, 3)))
        out_lines.append(new_line + tail_zw)
    return "\n".join(out_lines)

# ---------------------------------------------------------
# TRÌNH ĐỌC TỆP LỚN 5MB - 100MB+ (O(1) RAM STREAMING)
# ---------------------------------------------------------
class FastFileBlockReader:
    def __init__(self, filepath):
        self.filepath = filepath
        self.fp = open(filepath, "r", encoding="utf-8", errors="ignore")

    def next_block(self):
        lines = []
        while True:
            line = self.fp.readline()
            if not line:
                if lines:
                    return "\n".join(lines)
                self.fp.seek(0)
                line = self.fp.readline()
                if not line:
                    return "Ricki Vip — Phạm Anh Khôi ✔"
            s = line.strip()
            if s:
                lines.append(s)
            else:
                if lines:
                    return "\n".join(lines)

    def close(self):
        try:
            self.fp.close()
        except Exception:
            pass

# ---------------------------------------------------------
# LỚP ZALO ENGINE CHUYÊN SÂU
# ---------------------------------------------------------
class Zalo:
    def __init__(self, imei, cookies):
        self.imei = str(imei).strip().strip('"').strip("'")
        self.cookies_str = str(cookies).strip()
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
        if not raw:
            return
        # 1. Định dạng mảng JSON: [{"name": "...", "value": "..."}, ...]
        if raw.startswith("["):
            try:
                arr = json.loads(raw)
                if isinstance(arr, list):
                    for item in arr:
                        if isinstance(item, dict):
                            n = item.get("name") or item.get("key")
                            v = item.get("value")
                            if n and v is not None:
                                self.session.cookies.set(str(n).strip(), str(v).strip(), domain=".zalo.me")
                    return
            except Exception:
                pass
        # 2. Định dạng đối tượng JSON: {"zpw_sek": "...", "cookies": ...}
        if raw.startswith("{"):
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    if "cookies" in obj and isinstance(obj["cookies"], list):
                        for item in obj["cookies"]:
                            if isinstance(item, dict):
                                n = item.get("name") or item.get("key")
                                v = item.get("value")
                                if n and v is not None:
                                    self.session.cookies.set(str(n).strip(), str(v).strip(), domain=".zalo.me")
                        return
                    for k, v in obj.items():
                        if k and v is not None and not isinstance(v, (dict, list)):
                            self.session.cookies.set(str(k).strip(), str(v).strip(), domain=".zalo.me")
                    return
            except Exception:
                pass
        # 3. Định dạng chuỗi Cookie tiêu chuẩn: k1=v1; k2=v2
        if "=" in raw:
            pairs = re.split(r"[;\n\r]+", raw)
            for p in pairs:
                p = p.strip()
                if "=" in p:
                    k, v = p.split("=", 1)
                    if k.strip():
                        self.session.cookies.set(k.strip(), v.strip(), domain=".zalo.me")
            return
        # 4. Định dạng chỉ truyền mã zpw_sek trần
        self.session.cookies.set("zpw_sek", raw, domain=".zalo.me")

    def _login(self):
        # Ưu tiên lấy khóa có sẵn trong cookie nếu có
        self.secret_key = self.session.cookies.get("zpw_enk") or self.session.cookies.get("zpw_sek")
        try:
            url = f"https://chat.zalo.me/api/login/getServerInfo?imei={self.imei}&type=30&client_version=645&computer_name=Web"
            r = self.session.get(url, timeout=8)
            data = r.json()
            if data.get("error_code") == 0:
                info = data.get("data") or data
                if isinstance(info, dict) and info.get("zpw_enk"):
                    self.secret_key = info.get("zpw_enk")
        except Exception:
            pass
        if not self.secret_key:
            zpw = self.session.cookies.get("zpw_sek")
            if zpw:
                self.secret_key = zpw
        if not self.secret_key:
            raise Exception("Không tìm thấy khóa zpw_sek / zpw_enk trong Cookie Zalo")

    def check_status(self):
        t0 = time.time()
        try:
            prof = self.get_user_profile()
            ping_ms = int((time.time() - t0) * 1000)
            if prof and (prof.get("name") or prof.get("displayName") or prof.get("userId") or prof.get("uid")):
                uname = prof.get("name") or prof.get("displayName") or "Zalo User"
                uid = str(prof.get("userId") or prof.get("uid") or "")
                return {"live": True, "name": uname, "uid": uid, "ping_ms": ping_ms}
            # Thử kiểm tra qua danh sách nhóm nếu profile/get không trả về
            convs = self.get_conversations()
            ping_ms = int((time.time() - t0) * 1000)
            if convs:
                return {"live": True, "name": f"Zalo ({len(convs)} box)", "uid": self.imei[:10], "ping_ms": ping_ms}
            return {"live": False, "error": "Cookie hết hạn hoặc không đọc được hồ sơ", "ping_ms": ping_ms}
        except Exception as e:
            ping_ms = int((time.time() - t0) * 1000)
            return {"live": False, "error": str(e), "ping_ms": ping_ms}

    def _pad(self, s):
        bs = AES.block_size
        return s + (bs - len(s) % bs) * chr(bs - len(s) % bs).encode()

    def _unpad(self, s):
        return s[:-ord(s[len(s)-1:])]

    def encrypt(self, data_str):
        raw_key = self.secret_key or "0" * 32
        try:
            # Nếu secret_key là chuỗi base64 chuẩn 24/32 ký tự của Zalo
            dec_key = base64.b64decode(raw_key)
            if len(dec_key) in (16, 24, 32):
                key = dec_key
            else:
                key = raw_key.ljust(32, "0").encode("utf-8")[:32]
        except Exception:
            key = raw_key.ljust(32, "0").encode("utf-8")[:32]
        iv = bytes([0] * 16)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded = self._pad(data_str.encode("utf-8"))
        enc = cipher.encrypt(padded)
        return base64.b64encode(enc).decode("utf-8")

    def decrypt(self, enc_str):
        raw_key = self.secret_key or "0" * 32
        try:
            dec_key = base64.b64decode(raw_key)
            if len(dec_key) in (16, 24, 32):
                key = dec_key
            else:
                key = raw_key.ljust(32, "0").encode("utf-8")[:32]
        except Exception:
            key = raw_key.ljust(32, "0").encode("utf-8")[:32]
        iv = bytes([0] * 16)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        dec = cipher.decrypt(base64.b64decode(enc_str))
        return self._unpad(dec).decode("utf-8")

    def get_user_profile(self):
        try:
            url = "https://chat.zalo.me/api/profile/get"
            params = {"params": self.encrypt("{}"), "imei": self.imei}
            r = self.session.post(url, data=params, timeout=8)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                return info.get("data", info) if isinstance(info, dict) else {}
        except Exception:
            pass
        return {}

    def get_friend_map(self):
        fmap = {}
        try:
            url = "https://chat.zalo.me/api/friend/getfriends"
            params = {"params": self.encrypt("{}"), "imei": self.imei}
            r = self.session.post(url, data=params, timeout=8)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                data_list = info.get("data", []) if isinstance(info, dict) else []
                for item in data_list:
                    if isinstance(item, dict):
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
            r = self.session.post(url, data=params, timeout=8)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                gmap = info.get("data", {}).get("gridInfoMap", {}) if isinstance(info, dict) else {}
                for grid_key, g in gmap.items():
                    gid = str(g.get("grid") or grid_key)
                    gname = g.get("name", f"Nhóm {gid}")
                    boxes.append({
                        "id": gid,
                        "name": "[Zalo Nhóm] " + gname,
                        "type": "group",
                        "platform": "zalo"
                    })
        except Exception:
            pass
        try:
            url = "https://chat.zalo.me/api/friend/getfriends"
            params = {"params": self.encrypt("{}"), "imei": self.imei}
            r = self.session.post(url, data=params, timeout=8)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                data_list = info.get("data", []) if isinstance(info, dict) else []
                for f in data_list:
                    if isinstance(f, dict):
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
            r = self.session.post("https://chat.zalo.me/api/group/getgridinfo", data=params, timeout=8)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                gdata = info.get("data", {}) if isinstance(info, dict) else {}
                mem_list = gdata.get("memList", []) or gdata.get("members", []) or gdata.get("memberIds", [])
                mem_info_map = gdata.get("memInfoMap", {})

                for m in mem_list:
                    if isinstance(m, dict):
                        uid = str(m.get("uid") or m.get("id") or m.get("userId") or "")
                        info_item = mem_info_map.get(uid, {}) if isinstance(mem_info_map, dict) else {}
                        raw_name = m.get("dName") or m.get("displayName") or m.get("name") or info_item.get("dName") or info_item.get("displayName")
                    else:
                        uid = str(m).split("_")[0]
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
                styles.append({
                    "start": current_u16_pos,
                    "len": line_len,
                    "st": f"c_{clean_hex}"
                })
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
        r = self.session.post(url, data=params, timeout=10)
        res = r.json()
        if res.get("error_code") == 0:
            return True, res
        return False, res

# ---------------------------------------------------------
# DISCORD USER CLIENT
# ---------------------------------------------------------
class DiscordUserClient:
    def __init__(self, token):
        self.token = str(token).strip().strip('"').strip("'")
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
            "client_build_number": 325892,
            "client_event_source": None
        }
        b64_props = base64.b64encode(json.dumps(super_props).encode("utf-8")).decode("utf-8")
        self.session.headers.update({
            "Authorization": self.token,
            "User-Agent": super_props["browser_user_agent"],
            "X-Super-Properties": b64_props,
            "X-Discord-Locale": "vi",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": "https://discord.com",
            "Referer": "https://discord.com/channels/@me"
        })

    def check_status(self):
        t0 = time.time()
        try:
            r = self.session.get("https://discord.com/api/v9/users/@me", timeout=8)
            ping_ms = int((time.time() - t0) * 1000)
            if r.status_code == 200:
                d = r.json()
                uname = d.get("global_name") or d.get("username", "Discord User")
                uid = str(d.get("id", ""))
                return {"live": True, "username": uname, "id": uid, "ping_ms": ping_ms}
            return {"live": False, "error": f"HTTP {r.status_code} - Token hết hạn", "ping_ms": ping_ms}
        except Exception as e:
            ping_ms = int((time.time() - t0) * 1000)
            return {"live": False, "error": str(e), "ping_ms": ping_ms}

    def get_self(self):
        try:
            r = self.session.get("https://discord.com/api/v9/users/@me", timeout=8)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def get_all_chat_boxes(self):
        boxes = []
        try:
            r = self.session.get("https://discord.com/api/v9/users/@me/channels", timeout=8)
            if r.status_code == 200:
                for ch in r.json():
                    ctype = ch.get("type")
                    cid = str(ch.get("id"))
                    if ctype == 1:
                        recips = ch.get("recipients", [])
                        rname = recips[0].get("global_name") or recips[0].get("username", "User") if recips else "DM"
                        boxes.append({"id": cid, "name": f"[Discord DM] {rname}", "type": "user", "platform": "discord"})
                    elif ctype == 3:
                        gname = ch.get("name")
                        if not gname:
                            recips = ch.get("recipients", [])
                            gname = ", ".join([(u.get("global_name") or u.get("username", "")) for u in recips[:3]])
                        boxes.append({"id": cid, "name": f"[Discord Nhóm] {gname or 'Group DM'}", "type": "group", "platform": "discord"})
        except Exception:
            pass

        try:
            rg = self.session.get("https://discord.com/api/v9/users/@me/guilds", timeout=8)
            if rg.status_code == 200:
                for g in rg.json()[:15]:
                    gid = g.get("id")
                    gname = g.get("name", "Server")
                    rc = self.session.get(f"https://discord.com/api/v9/guilds/{gid}/channels", timeout=6)
                    if rc.status_code == 200:
                        for c in rc.json():
                            if c.get("type") in (0, 5):
                                cname = c.get("name", "channel")
                                boxes.append({
                                    "id": str(c.get("id")),
                                    "name": f"[Discord Server] {gname} # {cname}",
                                    "type": "group",
                                    "platform": "discord"
                                })
        except Exception:
            pass
        return boxes

    def send_message(self, channel_id, raw_text, tag_all=False, mentions=None,
                     tag_mode="rotate", mention_index=0, is_heading=False,
                     antiband=True, tag_pos="head"):
        text = apply_antiband_zalo_v5(raw_text) if antiband else raw_text
        if is_heading:
            lines = [f"# {line.strip()}" if line.strip() else "" for line in text.split("\n")]
            text = "\n".join(lines)

        tag_str = ""
        if tag_all:
            tag_str += "@everyone "
        if mentions and len(mentions) > 0:
            if tag_mode == "all":
                tag_str += " ".join([f"<@{m.get('id')}>" for m in mentions])
            else:
                target_u = mentions[mention_index % len(mentions)]
                tag_str += f"<@{target_u.get('id')}>"

        if tag_str:
            if tag_pos == "tail":
                text = f"{text}\n{tag_str.strip()}"
            else:
                text = f"{tag_str.strip()}\n{text}"

        nonce = str(int(time.time() * 1000) + random.randint(100, 999))
        payload = {"content": text[:1990], "tts": False, "nonce": nonce}
        r = self.session.post(
            f"https://discord.com/api/v9/channels/{channel_id}/messages",
            json=payload,
            timeout=10
        )
        if r.status_code in (200, 201):
            return True, r.json()
        elif r.status_code == 429:
            retry_after = 2.0
            try:
                retry_after = float(r.json().get("retry_after", 2.0))
            except Exception:
                pass
            time.sleep(min(retry_after + 0.3, 8.0))
            return False, {"error": "Rate Limited"}
        return False, {"error": f"HTTP {r.status_code}"}

# ---------------------------------------------------------
# QUẢN LÝ TIẾN TRÌNH & CACHE KẾT NỐI
# ---------------------------------------------------------
RUNNING_TASKS = {}
TASKS_LOCK = threading.Lock()
ZALO_CLIENT_CACHE = {}
DISCORD_CLIENT_CACHE = {}
COMMAND_HISTORY = []

BOT_STATE = {
    "active_file": None,
    "active_text": None,
    "delay": 1.2,
    "mode": "fast",
    "color_mode": "rainbow",
    "fixed_color": "red",
    "tag_all": False,
    "tag_rotate_tail": True,
    "is_heading": False,
    "antiband": True,
    "combat_icon_mode": "mixed",
    "combat_icon_count": 2,
    "target_mode": "here",
    "custom_targets": []
}

def get_active_clients():
    conn = db()
    zalo_rows = conn.execute("SELECT * FROM accounts WHERE platform = 'zalo' AND enabled = 1").fetchall()
    discord_rows = conn.execute("SELECT * FROM accounts WHERE platform = 'discord' AND enabled = 1").fetchall()
    conn.close()

    z_clients = []
    d_clients = []

    for r in zalo_rows:
        aid = r["id"]
        ckey = f"{aid}_{r['imei']}_{r['cookies']}"
        zc = ZALO_CLIENT_CACHE.get(ckey)
        if not zc:
            try:
                zc = Zalo(r["imei"], r["cookies"])
                ZALO_CLIENT_CACHE[ckey] = zc
            except Exception:
                zc = None
        if zc:
            z_clients.append((aid, r["label"], zc))

    for r in discord_rows:
        aid = r["id"]
        ckey = f"{aid}_{r['token']}"
        dc = DISCORD_CLIENT_CACHE.get(ckey)
        if not dc:
            try:
                dc = DiscordUserClient(r["token"])
                DISCORD_CLIENT_CACHE[ckey] = dc
            except Exception:
                dc = None
        if dc:
            d_clients.append((aid, r["label"], dc))

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
    combat_icon_count = int(payload.get("combat_icon_count", 2))

    reader = None
    if file_path and os.path.exists(file_path):
        reader = FastFileBlockReader(file_path)

    z_clients, d_clients = get_active_clients()
    group_members_cache = {}
    step_idx = 0
    color_offset = 0

    try:
        while not stop_ev.is_set():
            if reader:
                block_text = reader.next_block()
            elif direct_blocks:
                block_text = direct_blocks[step_idx % len(direct_blocks)]
            else:
                block_text = "Ricki Vip — Phạm Anh Khôi ✔"

            if mode == "treo_nhay":
                lines = [ln.strip() for ln in block_text.split("\n") if ln.strip()]
                sub_items = lines if lines else [block_text]
            else:
                sub_items = [block_text]

            for item_text in sub_items:
                if stop_ev.is_set():
                    break

                icons = generate_combat_combo(combat_icon_mode, combat_icon_count)
                final_raw = f"{icons} {item_text} {icons}".strip() if icons else item_text

                for t in targets:
                    if stop_ev.is_set():
                        break

                    tid = str(t.get("id"))
                    is_grp = (t.get("type", "group") == "group")
                    plat = t.get("platform", "zalo")
                    t_pos = "tail" if tag_rotate_tail else "head"

                    if plat == "zalo":
                        if not z_clients:
                            continue
                        _, _, zc = z_clients[step_idx % len(z_clients)]
                        mems = []
                        if is_grp and tag_rotate_tail:
                            if tid not in group_members_cache:
                                group_members_cache[tid] = zc.get_group_members(tid)
                            mems = group_members_cache.get(tid, [])

                        try:
                            zc.send_adv(
                                final_raw, tid,
                                color_mode=color_mode,
                                fixed_color=fixed_color,
                                is_group=is_grp,
                                mentions=mems,
                                tag_all=tag_all,
                                tag_mode="rotate",
                                mention_index=step_idx,
                                is_heading=is_heading,
                                color_offset=color_offset,
                                use_badge=True,
                                antiband=antiband,
                                tag_pos=t_pos
                            )
                            with TASKS_LOCK:
                                if task_id in RUNNING_TASKS:
                                    RUNNING_TASKS[task_id]["sent_count"] = RUNNING_TASKS[task_id].get("sent_count", 0) + 1
                        except Exception:
                            pass

                    elif plat == "discord":
                        if not d_clients:
                            continue
                        _, _, dc = d_clients[step_idx % len(d_clients)]
                        try:
                            dc.send_message(
                                tid, final_raw,
                                tag_all=tag_all,
                                is_heading=is_heading,
                                antiband=antiband,
                                tag_pos=t_pos
                            )
                            with TASKS_LOCK:
                                if task_id in RUNNING_TASKS:
                                    RUNNING_TASKS[task_id]["sent_count"] = RUNNING_TASKS[task_id].get("sent_count", 0) + 1
                        except Exception:
                            pass

                step_idx += 1
                color_offset = (color_offset + 1) % len(ZALO_PALETTE)
                if stop_ev.wait(max(0.3, delay + random.uniform(0.02, 0.15))):
                    break
    finally:
        if reader:
            reader.close()
        with TASKS_LOCK:
            if task_id in RUNNING_TASKS:
                RUNNING_TASKS[task_id]["status"] = "stopped"

# ---------------------------------------------------------
# HỆ THỐNG MENU & XỬ LÝ LỆNH TRỰC TIẾP (ZALO, DISCORD & CONSOLE)
# ---------------------------------------------------------
MENU_TEXT = """👑 HỆ THỐNG LỆNH RICKI VIP 👑
👤 Bản quyền © Phạm Anh Khôi (Verified ✔)
────────────────────────────
1️⃣ KIỂM TRA TÀI KHOẢN & HỘI THOẠI:
• .check (hoặc .checkacc) : Kiểm tra Token / Cookie & IMEI còn sống (LIVE) hay đã chết (DIE) kèm độ trễ Ping (ms)
• .boxes : Quét toàn bộ danh sách Nhóm Zalo & Kênh Discord kèm ID
• .target <ID | here | all> : Chọn nhóm mục tiêu để gửi tin
• .status : Xem trạng thái hệ thống, tệp đang chọn & số tin đã gửi

2️⃣ QUẢN LÝ & KIỂM TRA FILE NGÔN TRÊN SERVER:
• .listfiles (hoặc .files) : Xem danh sách tệp .txt đã đẩy lên server
• .setupfile <tên_file> : Kiểm tra cấu trúc dòng/khối & chọn làm tệp chạy chính
• .checkfile <tên_file> : Xem trước nội dung và kiểm tra cấu trúc tệp
• .addfile <tên.txt> <nội dung> : Tạo nhanh tệp ngôn mới trên server
• .settext <nội dung> : Đặt văn bản gửi trực tiếp không cần tệp

3️⃣ CHẠY GỬI TIN, ĐỔI MÀU & XOAY VÒNG @TAG CUỐI CÂU:
• .spam [nhanh|ngon|nhay] [delay] [màu] [tag]
  Ví dụ: .spam nhanh 1.2 rainbow tag (Gửi kèm @tag xoay vòng thành viên ở cuối câu liên tục đến khi dừng)
• .tagloop [delay] [màu] [nội dung] : Tự động lấy thành viên nhóm & xoay vòng @tag ở cuối câu liên tục
• .tagall [nội dung] : Rung chuông @All cả nhóm Zalo / @everyone Discord
• .color <rainbow|random|red|gold|green|orange|blue|purple|pink|cyan> : Đổi màu chữ Zalo rực rỡ
• .stop (hoặc .stopall) : Dừng khẩn cấp toàn bộ tiến trình đang chạy!"""

def execute_command(cmd_text, platform="zalo", target_id="here", is_group=True, client=None):
    cmd_text = (cmd_text or "").strip()
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
        # Nếu nhập trên console không có dấu chấm ở đầu, tự động nhận diện lệnh
        parts = cmd_text.split(" ", 1)
        if parts[0].lower() in [
            "menu", "help", "check", "checkacc", "kiemtra", "setupfile", "setfile",
            "checkfile", "tagloop", "spam", "stop", "stopall", "tagall", "status",
            "listfiles", "files", "addfile", "settext", "color", "target", "boxes"
        ]:
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
        conn = db()
        rows = conn.execute("SELECT * FROM accounts ORDER BY id DESC").fetchall()
        conn.close()

        if not rows:
            return "⚠️ Chưa có tài khoản nào được lưu trên server! Hãy dán Cookie + IMEI Zalo hoặc Token Discord vào mục Lưu Tài Khoản ở trên."

        for r in rows:
            aid = r["id"]
            plat = r["platform"]
            label = r["label"]
            if plat == "zalo":
                try:
                    zc = Zalo(r["imei"], r["cookies"])
                    stat = zc.check_status()
                    if stat["live"]:
                        rep.append(f"🟢 [ZALO #{aid}] LIVE: {stat['name']} (UID: {stat['uid']}) • Ping: {stat['ping_ms']}ms")
                    else:
                        rep.append(f"🔴 [ZALO #{aid}] DIE: {label} ({stat.get('error', 'Hết hạn')}) • Ping: {stat['ping_ms']}ms")
                except Exception as e:
                    rep.append(f"🔴 [ZALO #{aid}] DIE: {label} (Lỗi: {str(e)[:45]})")
            else:
                try:
                    dc = DiscordUserClient(r["token"])
                    stat = dc.check_status()
                    if stat["live"]:
                        rep.append(f"🟢 [DISCORD #{aid}] LIVE: {stat['username']} (ID: {stat['id']}) • Ping: {stat['ping_ms']}ms")
                    else:
                        rep.append(f"🔴 [DISCORD #{aid}] DIE: {label} ({stat.get('error', 'Hết hạn')}) • Ping: {stat['ping_ms']}ms")
                except Exception as e:
                    rep.append(f"🔴 [DISCORD #{aid}] DIE: {label} (Lỗi: {str(e)[:45]})")

        rep.append("────────────────────────────")
        rep.append("⚡ Hệ thống Ricki Vip sẵn sàng thực thi lệnh!")
        return "\n".join(rep)

    # 3. SETUP FILE
    elif cmd_name in ["setupfile", "setfile"]:
        conn = db()
        all_files = conn.execute("SELECT * FROM files ORDER BY id DESC").fetchall()
        conn.close()

        if not cmd_args:
            if not all_files:
                return "⚠️ Server chưa có tệp nào! Hãy đẩy tệp .txt lên ở khung Đẩy File Lên Server hoặc dùng .addfile <tên.txt> <nội dung>."
            # Nếu không truyền tên, tự động lấy file mới nhất
            chosen_row = all_files[0]
            fp = chosen_row["filepath"]
            target_file = chosen_row["filename"]
        else:
            target_q = cmd_args.strip()
            chosen_row = None
            for r in all_files:
                if str(r["id"]) == target_q or target_q.lower() in r["filename"].lower() or target_q.lower() in os.path.basename(r["filepath"]).lower():
                    chosen_row = r
                    break
            if chosen_row and os.path.exists(chosen_row["filepath"]):
                fp = chosen_row["filepath"]
                target_file = chosen_row["filename"]
            else:
                cands = [f for f in os.listdir(UPLOAD_DIR) if target_q.lower() in f.lower() and f.endswith(".txt")]
                if cands:
                    fp = os.path.join(UPLOAD_DIR, cands[0])
                    target_file = cands[0]
                else:
                    return f"❌ Không tìm thấy tệp '{target_q}'! Gõ .listfiles để xem danh sách tệp trên server."

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

        sz_kb = round(os.path.getsize(fp) / 1024, 2)
        est_min = round((max(1, total_blocks) * BOT_STATE["delay"]) / 60, 1)

        BOT_STATE["active_file"] = fp
        BOT_STATE["active_text"] = None

        rep = [
            f"📋 SETUP FILE THÀNH CÔNG: {target_file}",
            "────────────────────────────",
            f"📁 Dung lượng: {sz_kb} KB ({round(sz_kb/1024, 2)} MB)",
            f"📑 Tổng số dòng: {total_lines} dòng",
            f"📦 Tổng số khối ngôn: {max(1, total_blocks)} khối",
            "🔍 Kiểm tra cấu trúc: Hợp lệ 100% (Chuẩn UTF-8 Streaming)",
            f"⏳ Thời gian chạy ước tính: ~{est_min} phút (delay {BOT_STATE['delay']}s)",
            "────────────────────────────",
            "✔️ ĐÃ ĐẶT LÀM TỆP CHẠY CHÍNH (ACTIVE FILE)!",
            "👉 Gõ: .spam nhanh 1.2 rainbow tag để bắn tin kèm @tag cuối câu!"
        ]
        return "\n".join(rep)

    # 4. CHECKFILE
    elif cmd_name == "checkfile":
        conn = db()
        all_files = conn.execute("SELECT * FROM files ORDER BY id DESC").fetchall()
        conn.close()

        fp = None
        target_file = ""
        if not cmd_args:
            if BOT_STATE["active_file"] and os.path.exists(BOT_STATE["active_file"]):
                fp = BOT_STATE["active_file"]
                target_file = os.path.basename(fp)
            elif all_files and os.path.exists(all_files[0]["filepath"]):
                fp = all_files[0]["filepath"]
                target_file = all_files[0]["filename"]
            else:
                return "📁 Chưa có tệp nào được chọn! Hãy đẩy tệp .txt lên server trước."
        else:
            q = cmd_args.strip()
            for r in all_files:
                if str(r["id"]) == q or q.lower() in r["filename"].lower():
                    fp = r["filepath"]
                    target_file = r["filename"]
                    break
            if not fp:
                cands = [f for f in os.listdir(UPLOAD_DIR) if q.lower() in f.lower() and f.endswith(".txt")]
                if cands:
                    fp = os.path.join(UPLOAD_DIR, cands[0])
                    target_file = cands[0]

        if not fp or not os.path.exists(fp):
            return f"❌ Không tìm thấy tệp '{cmd_args}' trên server!"

        sz_kb = round(os.path.getsize(fp) / 1024, 2)
        preview_lines = []
        total_lines = 0
        total_blocks = 0
        in_block = False
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                total_lines += 1
                s = line.strip()
                if s:
                    if len(preview_lines) < 5:
                        preview_lines.append(s[:120])
                    if not in_block:
                        total_blocks += 1
                        in_block = True
                else:
                    in_block = False

        rep = [
            f"🔍 KIỂM TRA CHI TIẾT FILE: {target_file}",
            "────────────────────────────",
            f"• Kích thước: {sz_kb} KB | Số dòng: {total_lines} | Số khối: {max(1, total_blocks)}",
            "📄 Xem trước 5 dòng đầu tiên:",
            "\n".join([f"  [{i+1}] {ln}" for i, ln in enumerate(preview_lines)]) or "  (Tệp trống)",
            "────────────────────────────",
            f"👉 Gõ .setupfile {target_file} để kích hoạt chạy tệp này!"
        ]
        return "\n".join(rep)

    # 5. LISTFILES
    elif cmd_name in ["listfiles", "files"]:
        conn = db()
        rows = conn.execute("SELECT * FROM files ORDER BY id DESC").fetchall()
        conn.close()
        if not rows:
            return "📁 Trên server hiện chưa có tệp .txt nào!\n👉 Hãy chọn tệp ở mục 'Đẩy File Ngôn Lên Server' hoặc gõ: .addfile <tên.txt> <nội dung>"
        rep = ["📁 DANH SÁCH FILE NGÔN TRÊN SERVER:"]
        active_fp = BOT_STATE.get("active_file")
        for r in rows:
            sz_kb = round((r["size"] or 0) / 1024, 1)
            is_act = " ⭐ [ĐANG CHỌN]" if (active_fp and active_fp == r["filepath"]) else ""
            rep.append(f"• ID #{r['id']}: {r['filename']} ({sz_kb} KB • {r['lines']} dòng • {r['blocks']} khối){is_act}")
        rep.append("────────────────────────────")
        rep.append("👉 Gõ: .setupfile <ID hoặc tên_file> để kiểm tra & chọn chạy!")
        return "\n".join(rep)

    # 6. ADDFILE
    elif cmd_name == "addfile":
        if " " not in cmd_args:
            return "⚠️ Cú pháp: .addfile <tên_file.txt> <nội dung văn bản>"
        fname, content = cmd_args.split(" ", 1)
        if not fname.endswith(".txt"):
            fname += ".txt"
        safe_name = str(int(time.time())) + "_" + re.sub(r"[^a-zA-Z0-9_.-]", "_", fname)
        fp = os.path.join(UPLOAD_DIR, safe_name)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)

        lines = len(content.splitlines())
        blocks = len([b for b in content.split("\n\n") if b.strip()]) or 1
        sz = os.path.getsize(fp)
        conn = db()
        conn.execute("INSERT INTO files (filename, filepath, size, lines, blocks, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (fname, fp, sz, lines, blocks, time.time()))
        conn.commit()
        conn.close()

        BOT_STATE["active_file"] = fp
        BOT_STATE["active_text"] = None
        return f"✔️ ĐÃ TẠO & SETUP FILE: {fname} ({lines} dòng, {blocks} khối)!\n👉 Gõ .spam nhanh 1.2 rainbow tag để chạy ngay!"

    # 7. SETTEXT
    elif cmd_name == "settext":
        if not cmd_args:
            return "⚠️ Cú pháp: .settext <nội dung văn bản cần gửi>"
        BOT_STATE["active_text"] = cmd_args
        BOT_STATE["active_file"] = None
        return f"✔️ ĐÃ LƯU NỘI DUNG TRỰC TIẾP ({len(cmd_args)} ký tự)!\n👉 Gõ .spam nhanh 1.2 rainbow tag để gửi ngay!"

    # 8. COLOR
    elif cmd_name == "color":
        valid_colors = ["rainbow", "random", "red", "gold", "green", "orange", "blue", "purple", "pink", "cyan"]
        chosen = cmd_args.lower().strip()
        if chosen not in valid_colors:
            return f"⚠️ Màu không hợp lệ. Chọn 1 trong các màu: {', '.join(valid_colors)}"
        if chosen in ["rainbow", "random"]:
            BOT_STATE["color_mode"] = chosen
        else:
            BOT_STATE["color_mode"] = "fixed"
            BOT_STATE["fixed_color"] = chosen
        return f"🎨 ĐÃ ĐẶT CHẾ ĐỘ MÀU CHỮ ZALO: {chosen.upper()} (Hiển thị màu rực rỡ chuẩn UTF-16 trên Zalo Mobile & PC)!"

    # 9. BOXES & TARGET
    elif cmd_name == "boxes":
        z_clients, d_clients = get_active_clients()
        all_boxes = []
        for _, label, zc in z_clients:
            try:
                all_boxes.extend(zc.get_conversations())
            except Exception:
                pass
        for _, label, dc in d_clients:
            try:
                all_boxes.extend(dc.get_all_chat_boxes())
            except Exception:
                pass
        if not all_boxes:
            return "💬 Không tìm thấy hội thoại nào hoặc chưa lưu tài khoản Live!"
        rep = [f"💬 DANH SÁCH HỘI THOẠI / NHÓM ({len(all_boxes)} box):"]
        for b in all_boxes[:20]:
            rep.append(f"• {b['name']} ➔ ID: {b['id']}")
        rep.append("────────────────────────────")
        rep.append("👉 Gõ: .target <ID> để chọn nhóm nhận tin (hoặc chọn trên thanh chọn Nhóm của Web).")
        return "\n".join(rep)

    elif cmd_name == "target":
        if not cmd_args or cmd_args.lower() == "here":
            BOT_STATE["target_mode"] = "here"
            BOT_STATE["custom_targets"] = []
            return f"🎯 ĐÃ ĐẶT MỤC TIÊU: Nhóm hiện tại (ID: {target_id})."
        elif cmd_args.lower() == "all":
            BOT_STATE["target_mode"] = "all"
            BOT_STATE["custom_targets"] = []
            return "🎯 ĐÃ ĐẶT MỤC TIÊU: TẤT CẢ các nhóm & hội thoại trên tài khoản!"
        else:
            ids = [i.strip() for i in cmd_args.split(",") if i.strip()]
            BOT_STATE["target_mode"] = "custom"
            BOT_STATE["custom_targets"] = [{"id": i, "type": "group", "platform": platform} for i in ids]
            return f"🎯 ĐÃ KHOÁ MỤC TIÊU: {len(ids)} nhóm ({', '.join(ids)})."

    # 10. TAGLOOP (XOAY VÒNG @TAG Ở CUỐI TIN NHẮN LIÊN TỤC ĐẾN KHI DỪNG)
    elif cmd_name == "tagloop":
        args = cmd_args.split()
        delay = BOT_STATE["delay"]
        color = BOT_STATE["fixed_color"]
        color_mode = BOT_STATE["color_mode"]
        direct_text = ""

        if len(args) >= 1 and args[0].replace(".", "", 1).isdigit():
            delay = float(args[0])
            if len(args) >= 2 and args[1].lower() in [c["id"] for c in ZALO_PALETTE] + ["rainbow", "random"]:
                c_arg = args[1].lower()
                if c_arg in ["rainbow", "random"]:
                    color_mode = c_arg
                else:
                    color_mode = "fixed"
                    color = c_arg
                direct_text = " ".join(args[2:])
            else:
                direct_text = " ".join(args[1:])
        else:
            direct_text = cmd_args

        if not direct_text and not BOT_STATE["active_file"] and not BOT_STATE["active_text"]:
            direct_text = "Điểm danh anh em trong nhóm"

        file_path = BOT_STATE["active_file"] if not direct_text else None
        direct_blocks = [direct_text] if direct_text else ([b.strip() for b in BOT_STATE["active_text"].split("\n\n") if b.strip()] if BOT_STATE["active_text"] else [])

        targets = []
        if BOT_STATE["custom_targets"]:
            targets = BOT_STATE["custom_targets"]
        elif target_id and target_id not in ("here", "web_console", ""):
            targets = [{"id": str(target_id), "type": "group" if is_group else "user", "platform": platform}]
        else:
            return "⚠️ Chưa xác định nhóm mục tiêu! Hãy chọn Nhóm ở ô 'Nhóm Mục Tiêu' hoặc gõ lệnh: .target <ID_Nhóm> trước."

        task_id = "TAGLOOP_" + str(int(time.time()))[-4:]
        stop_ev = threading.Event()
        payload = {
            "targets": targets,
            "file_path": file_path,
            "direct_blocks": direct_blocks,
            "delay": delay,
            "mode": "fast",
            "color_mode": color_mode,
            "fixed_color": color,
            "tag_all": False,
            "tag_rotate_tail": True,
            "is_heading": False,
            "antiband": BOT_STATE["antiband"],
            "combat_icon_mode": BOT_STATE["combat_icon_mode"],
            "combat_icon_count": BOT_STATE["combat_icon_count"]
        }

        t = threading.Thread(target=run_spam_task, args=(task_id, payload, stop_ev), daemon=True)
        t.start()
        with TASKS_LOCK:
            RUNNING_TASKS[task_id] = {
                "id": task_id,
                "type": "TAGLOOP_CUỐI_CÂU",
                "status": "running",
                "thread": t,
                "stop_ev": stop_ev,
                "created_at": time.time(),
                "sent_count": 0
            }
        return f"🔥 ĐÃ CHẠY CHẾ ĐỘ XOAY VÒNG @TAG Ở CUỐI TIN NHẮN!\n🔹 Mã tiến trình: {task_id}\n🔹 Delay: {delay}s | Màu: {color_mode.upper()}\n🔹 Mục tiêu: {len(targets)} nhóm\n👉 Tự động duyệt thành viên và gắn @tag ở cuối mỗi câu liên tục đến khi gõ .stop!"

    # 11. SPAM
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
            elif a_lower in ["notags", "notag"]:
                tag_tail_flag = False
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
        if not file_path or not os.path.exists(file_path):
            # Tự động lấy file mới nhất trên server nếu có
            conn = db()
            latest_f = conn.execute("SELECT filepath FROM files ORDER BY id DESC LIMIT 1").fetchone()
            conn.close()
            if latest_f and os.path.exists(latest_f["filepath"]):
                file_path = latest_f["filepath"]
                BOT_STATE["active_file"] = file_path
            elif BOT_STATE["active_text"]:
                direct_blocks = [b.strip() for b in BOT_STATE["active_text"].split("\n\n") if b.strip()]
            else:
                return "❌ Chưa có tệp ngôn hoặc văn bản! Hãy đẩy tệp .txt lên Server hoặc gõ .settext <nội dung> trước."

        targets = []
        if BOT_STATE["target_mode"] == "all":
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
        elif target_id and target_id not in ("here", "web_console", ""):
            targets = [{"id": str(target_id), "type": "group" if is_group else "user", "platform": platform}]
        else:
            return "⚠️ Chưa chọn Nhóm nhận tin! Hãy chọn Nhóm ở thanh 'Nhóm Mục Tiêu' hoặc gõ lệnh .boxes rồi .target <ID_Nhóm>."

        task_id = "SPAM_" + str(int(time.time()))[-5:]
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
            "is_heading": False,
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

        fname_disp = os.path.basename(file_path) if file_path else "Văn bản trực tiếp"
        tag_disp = "BẬT (@tag xoay vòng ở cuối câu)" if tag_tail_flag else "TẮT"
        return (
            f"🚀 ĐÃ KHỞI CHẠY CHIẾN DỊCH #{task_id}!\n"
            f"🔹 Tệp nguồn: {fname_disp}\n"
            f"🔹 Chế độ: {mode.upper()} | Delay: {delay}s | Màu: {color_mode.upper()}\n"
            f"🔹 Tag cuối câu: {tag_disp}\n"
            f"🔹 Mục tiêu: {len(targets)} nhóm\n"
            f"👉 Gõ .stop để dừng bất kỳ lúc nào!"
        )

    # 12. STOP
    elif cmd_name in ["stop", "stopall"]:
        stopped = 0
        with TASKS_LOCK:
            for tid, tinfo in RUNNING_TASKS.items():
                if tinfo.get("status") == "running":
                    tinfo["stop_ev"].set()
                    tinfo["status"] = "stopped"
                    stopped += 1
        return f"🛑 ĐÃ DỪNG KHẨN CẤP TOÀN BỘ TIẾN TRÌNH ({stopped} tiến trình đã dừng)!"

    # 13. TAGALL
    elif cmd_name == "tagall":
        text = cmd_args if cmd_args else "Thông báo khẩn đến toàn thể anh em trong nhóm!"
        t_id = target_id
        if (not t_id or t_id in ("here", "web_console")) and BOT_STATE["custom_targets"]:
            t_id = BOT_STATE["custom_targets"][0]["id"]
            platform = BOT_STATE["custom_targets"][0].get("platform", "zalo")

        if not t_id or t_id in ("here", "web_console"):
            return "⚠️ Hãy chọn Nhóm Mục Tiêu hoặc gõ .target <ID_Nhóm> trước khi dùng .tagall!"

        if platform == "zalo":
            z_clients, _ = get_active_clients()
            if not z_clients:
                return "❌ Chưa có tài khoản Zalo hoạt động!"
            zc = client or z_clients[0][2]
            zc.send_adv(text, t_id, is_group=True, tag_all=True, is_heading=False)
            return f"📢 Đã bắn bản tin @All vào nhóm Zalo ({t_id}): {text}"
        else:
            _, d_clients = get_active_clients()
            if not d_clients:
                return "❌ Chưa có tài khoản Discord hoạt động!"
            dc = client or d_clients[0][2]
            dc.send_message(t_id, text, tag_all=True)
            return f"📢 Đã bắn bản tin @everyone vào kênh Discord ({t_id}): {text}"

    # 14. STATUS
    elif cmd_name == "status":
        z_clients, d_clients = get_active_clients()
        with TASKS_LOCK:
            running_tasks = [t for t in RUNNING_TASKS.values() if t.get("status") == "running"]
            total_sent = sum(t.get("sent_count", 0) for t in RUNNING_TASKS.values())

        file_name = os.path.basename(BOT_STATE["active_file"]) if BOT_STATE["active_file"] else "Chưa chọn (Dùng .setupfile)"
        if BOT_STATE["active_text"]:
            file_name = f"Văn bản trực tiếp ({len(BOT_STATE['active_text'])} ký tự)"

        rep = [
            "⚡ TRẠNG THÁI HỆ THỐNG RICKI VIP ⚡",
            "👤 Bản quyền: Phạm Anh Khôi (Verified ✔)",
            "────────────────────────────",
            f"🔷 Tài khoản Zalo đang bật: {len(z_clients)}",
            f"🟣 Tài khoản Discord đang bật: {len(d_clients)}",
            f"📁 Nguồn ngôn: {file_name}",
            f"🎨 Màu chữ Zalo: {BOT_STATE['color_mode'].upper()} ({BOT_STATE['fixed_color']})",
            f"🏷️ Xoay vòng @tag ở cuối: {'BẬT' if BOT_STATE['tag_rotate_tail'] else 'TẮT'}",
            f"🛡️ Anti-ban V5: {'BẬT' if BOT_STATE['antiband'] else 'TẮT'}",
            f"🚀 Tiến trình đang chạy: {len(running_tasks)}",
            f"📊 Tổng số tin đã bắn: {total_sent} tin",
            "────────────────────────────",
            "👉 Gõ .menu để xem bảng lệnh đầy đủ."
        ]
        return "\n".join(rep)

    return f"⚠️ Lệnh không hợp lệ: '{cmd_text}'. Gõ .menu để xem danh sách lệnh!"

# ---------------------------------------------------------
# LUỒNG TỰ ĐỘNG BẮT LỆNH TRỰC TIẾP TRÊN ZALO & DISCORD
# ---------------------------------------------------------
SEEN_MESSAGES = set()
SEEN_LOCK = threading.Lock()

def extract_zalo_msg_text(raw_val):
    if not raw_val:
        return ""
    if isinstance(raw_val, dict):
        return str(raw_val.get("content") or raw_val.get("message") or raw_val.get("title") or "").strip()
    if isinstance(raw_val, str):
        val = raw_val.strip()
        if val.startswith("{"):
            try:
                d = json.loads(val)
                if isinstance(d, dict):
                    return str(d.get("content") or d.get("message") or d.get("title") or val).strip()
            except Exception:
                pass
        return val
    return str(raw_val).strip()

def handle_incoming_command(text, platform, target_id, is_group, client):
    try:
        reply = execute_command(text, platform, target_id, is_group=is_group, client=client)
        if reply:
            COMMAND_HISTORY.append({
                "time": time.strftime("%H:%M:%S"),
                "source": f"{platform.upper()} ({target_id})",
                "cmd": text,
                "reply": reply
            })
            if len(COMMAND_HISTORY) > 50:
                COMMAND_HISTORY.pop(0)

            if platform == "zalo" and client:
                client.send_adv(reply, target_id, is_group=is_group, is_heading=False)
            elif platform == "discord" and client:
                client.send_message(target_id, reply)
    except Exception as e:
        print(f"Lỗi thực thi lệnh: {e}")

def zalo_listener_loop():
    print("🔷 [Zalo Listener] Đang chạy luồng quét lệnh trực tiếp trên Zalo...")
    first_poll_accounts = set()
    while True:
        try:
            z_clients, _ = get_active_clients()
            for acc_id, label, zc in z_clients:
                is_first = (acc_id not in first_poll_accounts)
                try:
                    url = "https://chat.zalo.me/api/group/getlg"
                    params = {"params": zc.encrypt("{}"), "imei": zc.imei}
                    r = zc.session.post(url, data=params, timeout=5)
                    res = r.json()
                    if res.get("data"):
                        plain = zc.decrypt(res["data"])
                        info = json.loads(plain)
                        grid_map = info.get("data", {}).get("gridInfoMap", {}) or {}
                        for grid_key, g in list(grid_map.items())[:15]:
                            grid = str(g.get("grid") or grid_key)
                            last_msg_val = g.get("lastMsg") or g.get("lastMsgInfo")
                            # Nếu getlg không đính kèm lastMsg, thử lấy từ getgridinfo
                            if not last_msg_val:
                                try:
                                    pl_g = json.dumps({"grid": grid})
                                    pr_g = {"params": zc.encrypt(pl_g), "imei": zc.imei}
                                    rg = zc.session.post("https://chat.zalo.me/api/group/getgridinfo", data=pr_g, timeout=4)
                                    res_g = rg.json()
                                    if res_g.get("data"):
                                        plain_g = zc.decrypt(res_g["data"])
                                        info_g = json.loads(plain_g).get("data", {})
                                        last_msg_val = info_g.get("lastMsg") or info_g.get("lastMsgInfo") or info_g.get("latestMsg")
                                except Exception:
                                    pass

                            text = extract_zalo_msg_text(last_msg_val)
                            if not text:
                                continue
                            last_msg_id = str(g.get("lastMsgId") or g.get("cliMsgId") or g.get("lastMsgTime") or "")
                            msg_key = f"{grid}_{last_msg_id}_{text}"

                            with SEEN_LOCK:
                                if msg_key in SEEN_MESSAGES:
                                    continue
                                SEEN_MESSAGES.add(msg_key)
                                if len(SEEN_MESSAGES) > 5000:
                                    SEEN_MESSAGES.clear()

                            if is_first:
                                continue

                            if text.startswith((".", "!", "/")) or text.lower() in ["menu", "help"]:
                                threading.Thread(
                                    target=handle_incoming_command,
                                    args=(text, "zalo", grid, True, zc),
                                    daemon=True
                                ).start()
                    if is_first:
                        first_poll_accounts.add(acc_id)
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(1.2)

CACHED_DISCORD_BOXES = []
LAST_DISCORD_BOX_POLL = 0

def discord_listener_loop():
    global CACHED_DISCORD_BOXES, LAST_DISCORD_BOX_POLL
    print("🟣 [Discord Listener] Đang chạy luồng quét lệnh trực tiếp trên Discord...")
    first_poll_channels = set()
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

                for b in CACHED_DISCORD_BOXES[:10]:
                    cid = b["id"]
                    is_first = (cid not in first_poll_channels)
                    try:
                        r = dc.session.get(f"https://discord.com/api/v9/channels/{cid}/messages?limit=2", timeout=4)
                        if r.status_code == 200:
                            arr = r.json()
                            for m in arr:
                                mid = str(m.get("id"))
                                with SEEN_LOCK:
                                    if mid in SEEN_MESSAGES:
                                        continue
                                    SEEN_MESSAGES.add(mid)
                                    if len(SEEN_MESSAGES) > 5000:
                                        SEEN_MESSAGES.clear()

                                if is_first:
                                    continue

                                text = (m.get("content") or "").strip()
                                if text.startswith((".", "!", "/")) or text.lower() in ["menu", "help"]:
                                    threading.Thread(
                                        target=handle_incoming_command,
                                        args=(text, "discord", cid, (b["type"] == "group"), dc),
                                        daemon=True
                                    ).start()
                        if is_first:
                            first_poll_channels.add(cid)
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

start_background_listeners()

# ---------------------------------------------------------
# GIAO DIỆN TRUNG TÂM LƯU COOKIE/IMEI, ĐẨY FILE & GÕ LỆNH (CHUẨN RAW STRING r"""...""")
# ---------------------------------------------------------
HTML_MAIN = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Ricki Vip — Phạm Anh Khôi ✔</title>
<style>
:root {
  --bg-main: #090d16;
  --bg-card: rgba(17, 24, 39, 0.88);
  --border-clr: rgba(255, 255, 255, 0.1);
  --accent-blue: #3b82f6;
  --accent-indigo: #6366f1;
  --accent-green: #10b981;
  --accent-red: #ef4444;
  --accent-gold: #f59e0b;
  --txt-1: #f8fafc;
  --txt-2: #94a3b8;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: radial-gradient(circle at top right, #1e1b4b, #090d16 60%);
  color: var(--txt-1);
  min-height: 100vh;
  padding: 16px;
  line-height: 1.5;
}
.container {
  max-width: 1080px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.header-card {
  background: var(--bg-card);
  border: 1px solid var(--border-clr);
  border-radius: 18px;
  padding: 18px 22px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  box-shadow: 0 12px 32px rgba(0,0,0,0.45);
}
.brand-left {
  display: flex;
  align-items: center;
  gap: 14px;
}
.logo-box {
  width: 58px;
  height: 58px;
  border-radius: 15px;
  overflow: hidden;
  border: 2px solid rgba(99, 102, 241, 0.6);
  background: #1e293b;
  flex-shrink: 0;
}
.logo-box img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.brand-title {
  font-size: 22px;
  font-weight: 800;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #fff;
}
.verified-tick {
  width: 20px;
  height: 20px;
  display: inline-block;
  vertical-align: middle;
}
.copyright-line {
  font-size: 13px;
  color: var(--txt-2);
  margin-top: 3px;
  display: flex;
  align-items: center;
  gap: 5px;
}
.copyright-line b { color: #e2e8f0; }
.logo-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}
@media (max-width: 820px) {
  .grid-2 { grid-template-columns: 1fr; }
}
.card {
  background: var(--bg-card);
  border: 1px solid var(--border-clr);
  border-radius: 18px;
  padding: 20px;
  box-shadow: 0 10px 28px rgba(0,0,0,0.35);
}
.card-title {
  font-size: 16px;
  font-weight: 800;
  color: #fff;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  padding-bottom: 10px;
}
.form-group { margin-bottom: 12px; }
.form-group label {
  display: block;
  font-size: 12px;
  font-weight: 700;
  color: var(--txt-2);
  margin-bottom: 5px;
  text-transform: uppercase;
}
input[type="text"], textarea, select {
  width: 100%;
  background: rgba(15, 23, 42, 0.9);
  border: 1px solid rgba(255,255,255,0.14);
  border-radius: 11px;
  padding: 10px 13px;
  color: #fff;
  font-size: 13.5px;
  outline: none;
  transition: border 0.2s;
}
input[type="text"]:focus, textarea:focus, select:focus {
  border-color: var(--accent-blue);
}
textarea { min-height: 78px; resize: vertical; font-family: monospace; }
.btn {
  border: none;
  border-radius: 10px;
  padding: 9px 15px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.18s;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: #fff;
}
.btn:active { transform: scale(0.97); }
.btn-primary { background: linear-gradient(135deg, #6366f1, #3b82f6); }
.btn-green { background: linear-gradient(135deg, #10b981, #059669); }
.btn-red { background: rgba(239, 68, 68, 0.2); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.4); }
.btn-dark { background: rgba(255,255,255,0.08); color: #e2e8f0; border: 1px solid rgba(255,255,255,0.12); }
.btn-full { width: 100%; padding: 11px; font-size: 14px; }
.plat-switch {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.plat-switch .btn { flex: 1; }
.item-list {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 230px;
  overflow-y: auto;
}
.list-row {
  background: rgba(15, 23, 42, 0.75);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 11px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.badge-live {
  color: #10b981;
  font-weight: 700;
  font-size: 12px;
}
.badge-dead {
  color: #ef4444;
  font-weight: 700;
  font-size: 12px;
}
.upload-zone {
  border: 2px dashed rgba(99, 102, 241, 0.5);
  background: rgba(99, 102, 241, 0.06);
  border-radius: 13px;
  padding: 16px;
  text-align: center;
  cursor: pointer;
  margin-bottom: 10px;
  transition: all 0.2s;
}
.upload-zone:hover { border-color: #3b82f6; background: rgba(59, 130, 246, 0.12); }
.progress-wrap {
  display: none;
  background: rgba(255,255,255,0.08);
  border-radius: 8px;
  height: 10px;
  overflow: hidden;
  margin: 8px 0;
}
.progress-bar {
  height: 100%;
  width: 0%;
  background: linear-gradient(90deg, #10b981, #3b82f6);
  transition: width 0.15s;
}
.cmd-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-bottom: 12px;
}
.cmd-chip {
  background: rgba(59, 130, 246, 0.14);
  border: 1px solid rgba(59, 130, 246, 0.35);
  color: #93c5fd;
  padding: 6px 11px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  font-family: monospace;
}
.cmd-chip:hover { background: rgba(59, 130, 246, 0.28); color: #fff; }
.cmd-input-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.cmd-input-row input {
  flex: 1;
  font-family: monospace;
  font-size: 14px;
  border-color: rgba(99, 102, 241, 0.5);
}
.terminal-box {
  background: #050811;
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 12px;
  padding: 14px;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 13px;
  color: #a7f3d0;
  white-space: pre-wrap;
  max-height: 340px;
  overflow-y: auto;
  line-height: 1.55;
}
#toast-stack {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.toast {
  background: rgba(15, 23, 42, 0.96);
  border: 1px solid rgba(255,255,255,0.18);
  border-radius: 11px;
  padding: 11px 15px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.5);
  min-width: 250px;
}
</style>
</head>
<body>

<div id="toast-stack"></div>

<div class="container">
  <!-- HEADER THƯƠNG HIỆU & ĐỔI LOGO TRỰC TIẾP -->
  <div class="header-card">
    <div class="brand-left">
      <div class="logo-box">
        <img id="site-logo-img" src="/logo" alt="Ricki Vip">
      </div>
      <div>
        <div class="brand-title">
          <span>Ricki Vip</span>
          """ + SVG_VERIFIED_TICK + r"""
        </div>
        <div class="copyright-line">
          <span>Bản quyền © <b>Phạm Anh Khôi</b></span>
          """ + SVG_VERIFIED_TICK + r"""
        </div>
      </div>
    </div>

    <div class="logo-actions">
      <input type="file" id="logo-file-input" accept="image/*" style="display:none;" onchange="onLogoChosen(this)">
      <button type="button" class="btn btn-dark" onclick="document.getElementById('logo-file-input').click()">🖼️ Chọn Ảnh Logo</button>
      <button type="button" class="btn btn-primary" id="btn-save-logo" onclick="uploadLogo()" style="display:none;">⬆️ Lưu Logo Lên Web</button>
      <button type="button" class="btn btn-red" onclick="resetLogo()">Khôi Phục Mặc Định</button>
    </div>
  </div>

  <!-- KHỐI 1 & KHỐI 2: LƯU COOKIE/IMEI & ĐẨY FILE LÊN SERVER -->
  <div class="grid-2">
    <!-- KHỐI 1: LƯU COOKIE & IMEI ZALO / TOKEN DISCORD -->
    <div class="card">
      <div class="card-title">
        <span>1. Lưu Cookie & IMEI / Token (Kích Hoạt Bot)</span>
        <button type="button" class="btn btn-dark" style="padding:5px 10px; font-size:11.5px;" onclick="checkAllAccounts()">🔍 Check Live Tất Cả</button>
      </div>

      <div class="plat-switch">
        <button type="button" id="btn-plat-zalo" class="btn btn-primary" onclick="switchPlatform('zalo')">🔷 Zalo (IMEI + Cookie)</button>
        <button type="button" id="btn-plat-discord" class="btn btn-dark" onclick="switchPlatform('discord')">🟣 Discord (User Token)</button>
      </div>

      <div class="form-group">
        <label>Tên Gợi Nhớ (Không bắt buộc)</label>
        <input type="text" id="acc-label" placeholder="Để trống hệ thống tự đặt tên...">
      </div>

      <div id="form-zalo">
        <div class="form-group">
          <label>Zalo IMEI</label>
          <input type="text" id="acc-imei" placeholder="Dán mã IMEI Zalo Web vào đây...">
        </div>
        <div class="form-group">
          <label>Zalo Cookie (JSON, Chuỗi Cookie hoặc zpw_sek)</label>
          <textarea id="acc-cookies" placeholder="Dán toàn bộ Cookie Zalo vào đây..."></textarea>
        </div>
      </div>

      <div id="form-discord" style="display:none;">
        <div class="form-group">
          <label>Discord User Token</label>
          <textarea id="acc-token" placeholder="Dán mã Authorization Token Discord vào đây..."></textarea>
        </div>
      </div>

      <button type="button" class="btn btn-green btn-full" id="btn-save-acc" onclick="addAccount()">💾 LƯU TÀI KHOẢN & KÍCH HOẠT LỆNH</button>

      <div class="item-list" id="acc-list-wrap"></div>
    </div>

    <!-- KHỐI 2: ĐẨY FILE NGÔN LÊN SERVER (HỖ TRỢ 5MB - 100MB+) -->
    <div class="card">
      <div class="card-title">
        <span>2. Đẩy File Ngôn Lên Server (5MB - 100MB+)</span>
        <span id="active-file-badge" style="font-size:11.5px; color:#10b981; font-weight:700;"></span>
      </div>

      <input type="file" id="file-input" accept=".txt,text/plain" style="display:none;" onchange="onTxtFileChosen(this)">
      <div class="upload-zone" onclick="document.getElementById('file-input').click()">
        <div style="font-size:24px; margin-bottom:4px;">📁</div>
        <div id="upload-zone-title" style="font-weight:700; color:#fff; font-size:13.5px;">Nhấn vào đây để chọn tệp .TXT cần đẩy lên Server</div>
        <div id="upload-zone-sub" style="font-size:12px; color:var(--txt-2); margin-top:3px;">Hỗ trợ tệp 5MB - 100MB+ • Tự động kiểm tra dòng & khối ngôn</div>
      </div>

      <div class="progress-wrap" id="upload-progress-wrap">
        <div class="progress-bar" id="upload-progress-bar"></div>
      </div>

      <button type="button" class="btn btn-primary btn-full" id="btn-upload-file" onclick="uploadTxtFile()">⬆️ ĐẨY FILE LÊN SERVER & KIỂM TRA SETUP</button>

      <div class="item-list" id="files-list-wrap"></div>
    </div>
  </div>

  <!-- KHỐI 3: TRUNG TÂM GÕ LỆNH TRỰC TIẾP (ZALO / DISCORD / SERVER CONSOLE) -->
  <div class="card">
    <div class="card-title">
      <span>3. Trung Tâm Gõ Lệnh Trực Tiếp (Chạy Trên Zalo, Discord & Console)</span>
      <div style="display:flex; gap:8px; align-items:center;">
        <button type="button" class="btn btn-dark" style="padding:5px 10px; font-size:11.5px;" onclick="scanBoxesToSelect()">🔄 Quét Nhóm Zalo/Discord</button>
        <button type="button" class="btn btn-red" style="padding:5px 10px; font-size:11.5px;" onclick="quickCmd('.stop')">🛑 Dừng Tất Cả (.stop)</button>
      </div>
    </div>

    <div class="grid-2" style="margin-bottom:12px; gap:12px;">
      <div class="form-group" style="margin-bottom:0;">
        <label>Chọn Nhóm / Box Mục Tiêu (Để bắn tin hoặc gửi phản hồi lệnh vào nhóm)</label>
        <select id="target-box-select" onchange="onTargetBoxChanged()">
          <option value="">-- Tự động nhận diện hoặc bấm 'Quét Nhóm Zalo/Discord' --</option>
        </select>
      </div>
      <div class="form-group" style="margin-bottom:0; display:flex; align-items:flex-end;">
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer; text-transform:none; font-size:13px; color:#e2e8f0; background:rgba(15,23,42,0.8); padding:10px 13px; border-radius:11px; border:1px solid rgba(255,255,255,0.12); width:100%;">
          <input type="checkbox" id="chk-send-to-chat" checked style="width:16px; height:16px;">
          <span>Đồng thời gửi bảng phản hồi lệnh (`.menu`, `.check`...) vào thẳng Nhóm đang chọn</span>
        </label>
      </div>
    </div>

    <!-- CÁC NÚT LỆNH 1 CHẠM -->
    <div class="cmd-chips">
      <span class="cmd-chip" onclick="quickCmd('.menu')">.menu (Hiện Menu)</span>
      <span class="cmd-chip" onclick="quickCmd('.check')">.check (Check Live/Die)</span>
      <span class="cmd-chip" onclick="quickCmd('.listfiles')">.listfiles (DS File)</span>
      <span class="cmd-chip" onclick="quickCmd('.setupfile')">.setupfile (Setup File Mới Nhất)</span>
      <span class="cmd-chip" onclick="quickCmd('.checkfile')">.checkfile (Kiểm Tra File)</span>
      <span class="cmd-chip" onclick="quickCmd('.boxes')">.boxes (Quét DS Nhóm)</span>
      <span class="cmd-chip" onclick="quickCmd('.spam nhanh 1.2 rainbow tag')">.spam nhanh 1.2 rainbow tag (Bắn + @Tag Cuối)</span>
      <span class="cmd-chip" onclick="quickCmd('.tagloop 1.2 rainbow')">.tagloop 1.2 rainbow (Xoay Vòng @Tag Cuối)</span>
      <span class="cmd-chip" onclick="quickCmd('.tagall Thông báo anh em!')">.tagall (Tag @All Cả Nhóm)</span>
      <span class="cmd-chip" onclick="quickCmd('.color rainbow')">.color rainbow (Đổi Màu Chữ)</span>
      <span class="cmd-chip" onclick="quickCmd('.status')">.status (Trạng Thái)</span>
      <span class="cmd-chip" style="border-color:#ef4444; color:#fca5a5;" onclick="quickCmd('.stop')">.stop (Dừng Ngay)</span>
    </div>

    <div class="cmd-input-row">
      <input type="text" id="cmd-input" placeholder="Nhập lệnh trực tiếp (VD: .menu, .check, .setupfile, .spam nhanh 1.2 rainbow tag, .stop)..." onkeydown="if(event.key==='Enter') sendCmdNow()">
      <button type="button" class="btn btn-primary" onclick="sendCmdNow()">⚡ GỬI LỆNH CHẠY NGAY</button>
    </div>

    <div class="terminal-box" id="terminal-output">👑 RICKI VIP COMMAND CONSOLE — Bản quyền © Phạm Anh Khôi (Verified ✔)
👉 Bước 1: Dán Cookie + IMEI Zalo (hoặc Token Discord) và bấm 'LƯU TÀI KHOẢN'.
👉 Bước 2: Chọn tệp .txt (hỗ trợ 5MB - 100MB+) và bấm 'ĐẨY FILE LÊN SERVER'.
👉 Bước 3: Gõ lệnh trực tiếp tại đây HOẶC gõ trong nhóm Zalo / kênh Discord (.menu, .check, .setupfile, .spam nhanh 1.2 rainbow tag, .stop)!</div>
  </div>
</div>

<script>
var currentPlatform = 'zalo';
var cachedBoxes = [];

var Toast = (function(){
  function show(title, msg, type){
    var stack = document.getElementById('toast-stack');
    if(!stack) return;
    var t = document.createElement('div');
    t.className = 'toast';
    var color = (type === 'success') ? '#10b981' : (type === 'error' ? '#ef4444' : '#3b82f6');
    var icon = (type === 'success') ? '✔️' : (type === 'error' ? '❌' : 'ℹ️');
    t.innerHTML = '<div style="font-weight:800; font-size:12.5px; color:' + color + '; margin-bottom:2px;">' + icon + ' ' + title + '</div>' +
                  '<div style="font-size:12.5px; color:#fff;">' + msg + '</div>';
    stack.appendChild(t);
    setTimeout(function(){
      if(t.parentNode) t.parentNode.removeChild(t);
    }, 3500);
  }
  return {
    success: function(m){ show('Thành Công', m, 'success'); },
    error: function(m){ show('Thông Báo Lỗi', m, 'error'); },
    info: function(m){ show('Thông Tin', m, 'info'); }
  };
})();

function logTerminal(text){
  var box = document.getElementById('terminal-output');
  if(!box) return;
  var now = new Date().toLocaleTimeString('vi-VN');
  box.textContent = '[' + now + ']\n' + text + '\n────────────────────────────────────────\n' + box.textContent;
}

async function apiJson(url, opts){
  opts = opts || {};
  try {
    var r = await fetch(url, Object.assign({}, opts, {
      credentials: 'same-origin',
      headers: Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {})
    }));
    return await r.json();
  } catch(e) {
    return { error: 'Lỗi kết nối máy chủ: ' + (e.message || '') };
  }
}

function switchPlatform(plat){
  currentPlatform = plat;
  var bz = document.getElementById('btn-plat-zalo');
  var bd = document.getElementById('btn-plat-discord');
  if(plat === 'zalo'){
    bz.className = 'btn btn-primary';
    bd.className = 'btn btn-dark';
    document.getElementById('form-zalo').style.display = 'block';
    document.getElementById('form-discord').style.display = 'none';
  } else {
    bz.className = 'btn btn-dark';
    bd.className = 'btn btn-primary';
    document.getElementById('form-zalo').style.display = 'none';
    document.getElementById('form-discord').style.display = 'block';
  }
}

/* 1. XỬ LÝ ĐỔI LOGO WEB */
function onLogoChosen(input){
  if(input.files && input.files.length > 0){
    var file = input.files[0];
    var reader = new FileReader();
    reader.onload = function(e){
      document.getElementById('site-logo-img').src = e.target.result;
    };
    reader.readAsDataURL(file);
    document.getElementById('btn-save-logo').style.display = 'inline-flex';
    Toast.info('Đã chọn ảnh: ' + file.name + '. Bấm "Lưu Logo Lên Web" để hoàn tất!');
  }
}

async function uploadLogo(){
  var inp = document.getElementById('logo-file-input');
  if(!inp.files || !inp.files.length) return Toast.error('Vui lòng chọn ảnh logo trước!');
  var fd = new FormData();
  fd.append('logo', inp.files[0]);
  Toast.info('Đang tải ảnh logo lên server...');
  try {
    var resp = await fetch('/api/upload_logo', { method: 'POST', body: fd, credentials: 'same-origin' });
    var res = await resp.json();
    if(res.ok){
      document.getElementById('site-logo-img').src = res.logo_url || ('/logo?t=' + Date.now());
      document.getElementById('btn-save-logo').style.display = 'none';
      Toast.success('Đã cập nhật Logo Website thành công!');
    } else {
      Toast.error(res.error || 'Không thể lưu logo');
    }
  } catch(e) {
    Toast.error('Lỗi tải logo: ' + e.message);
  }
}

async function resetLogo(){
  await fetch('/api/reset_logo', { method: 'POST', credentials: 'same-origin' });
  document.getElementById('site-logo-img').src = '/logo?t=' + Date.now();
  document.getElementById('btn-save-logo').style.display = 'none';
  Toast.info('Đã khôi phục Logo mặc định');
}

/* 2. XỬ LÝ LƯU COOKIE & IMEI / TOKEN */
async function addAccount(){
  var label = document.getElementById('acc-label').value.trim();
  if(!label){
    label = (currentPlatform === 'zalo' ? 'Nick Zalo ' : 'Nick Discord ') + (Math.floor(Date.now() / 1000) % 1000);
  }
  var payload = { label: label, platform: currentPlatform };
  if(currentPlatform === 'zalo'){
    payload.imei = document.getElementById('acc-imei').value.trim();
    payload.cookies = document.getElementById('acc-cookies').value.trim();
    if(!payload.imei || !payload.cookies){
      return Toast.error('Vui lòng dán đầy đủ IMEI và Cookie Zalo!');
    }
  } else {
    payload.token = document.getElementById('acc-token').value.trim();
    if(!payload.token){
      return Toast.error('Vui lòng dán Token Discord!');
    }
  }

  var btn = document.getElementById('btn-save-acc');
  btn.disabled = true;
  btn.textContent = '⏳ ĐANG LƯU & KIỂM TRA KẾT NỐI...';

  var res = await apiJson('/api/accounts', { method: 'POST', body: JSON.stringify(payload) });
  btn.disabled = false;
  btn.textContent = '💾 LƯU TÀI KHOẢN & KÍCH HOẠT LỆNH';

  if(res.error){
    return Toast.error(res.error);
  }
  Toast.success('Đã lưu tài khoản: ' + (res.real_name || label) + '!');
  logTerminal('✔️ ĐÃ LƯU TÀI KHOẢN: ' + (res.real_name || label) + ' (' + res.status.toUpperCase() + ')\n' + (res.detail || 'Đã kích hoạt luồng nhận lệnh trực tiếp!'));

  document.getElementById('acc-label').value = '';
  document.getElementById('acc-imei').value = '';
  document.getElementById('acc-cookies').value = '';
  document.getElementById('acc-token').value = '';

  await loadAccounts();
  await scanBoxesToSelect();
}

async function loadAccounts(){
  var accs = await apiJson('/api/accounts');
  if(!Array.isArray(accs)) accs = [];
  var wrap = document.getElementById('acc-list-wrap');
  if(!accs.length){
    wrap.innerHTML = '<div style="text-align:center; color:var(--txt-2); font-size:12.5px; padding:10px;">Chưa có tài khoản nào trên server. Hãy dán Cookie & IMEI ở trên để lưu.</div>';
    return;
  }
  wrap.innerHTML = accs.map(function(a){
    var pBadge = (a.platform === 'discord') ? '🟣 Discord' : '🔷 Zalo';
    var stHtml = (a.status === 'live')
      ? '<span class="badge-live">● LIVE</span>'
      : '<span class="badge-dead">● DIE / HẾT HẠN</span>';
    return '<div class="list-row">' +
      '<div>' +
        '<div style="font-weight:700; font-size:13px; color:#fff;">' + pBadge + ' — ' + a.label + ' <span style="color:#93c5fd;">(' + (a.real_name || 'User') + ')</span></div>' +
        '<div id="acc-st-' + a.id + '" style="margin-top:2px;">' + stHtml + '</div>' +
      '</div>' +
      '<div style="display:flex; gap:6px;">' +
        '<button type="button" class="btn btn-dark" style="padding:5px 10px; font-size:11.5px;" onclick="checkAccount(' + a.id + ')">Check</button>' +
        '<button type="button" class="btn btn-red" style="padding:5px 10px; font-size:11.5px;" onclick="deleteAccount(' + a.id + ')">Xóa</button>' +
      '</div>' +
    '</div>';
  }).join('');
}

async function checkAccount(aid){
  Toast.info('Đang kiểm tra trạng thái Live/Die...');
  var r = await apiJson('/api/accounts/' + aid + '/check', { method: 'POST' });
  var el = document.getElementById('acc-st-' + aid);
  if(r.ok){
    if(el) el.innerHTML = '<span class="badge-live">● LIVE (' + (r.ping_ms || 0) + 'ms) — ' + (r.name || '') + '</span>';
    Toast.success('Tài khoản LIVE! Ping: ' + (r.ping_ms || 0) + 'ms');
    logTerminal('🟢 TÀI KHOẢN #' + aid + ' LIVE: ' + (r.name || '') + ' • Ping: ' + (r.ping_ms || 0) + 'ms');
  } else {
    if(el) el.innerHTML = '<span class="badge-dead">● DIE (' + (r.error || 'Hết hạn') + ')</span>';
    Toast.error('Tài khoản DIE: ' + (r.error || 'Cookie/Token hết hạn'));
    logTerminal('🔴 TÀI KHOẢN #' + aid + ' DIE: ' + (r.error || 'Hết hạn'));
  }
}

async function checkAllAccounts(){
  quickCmd('.check');
}

async function deleteAccount(aid){
  await apiJson('/api/accounts/' + aid, { method: 'DELETE' });
  Toast.info('Đã xóa tài khoản #' + aid);
  loadAccounts();
}

/* 3. XỬ LÝ ĐẨY FILE LÊN SERVER (5MB - 100MB+) */
function onTxtFileChosen(input){
  if(input.files && input.files.length > 0){
    var f = input.files[0];
    var mb = (f.size / (1024 * 1024)).toFixed(2);
    document.getElementById('upload-zone-title').textContent = 'Đã chọn: ' + f.name + ' (' + mb + ' MB)';
    document.getElementById('upload-zone-title').style.color = '#10b981';
  }
}

function uploadTxtFile(){
  var inp = document.getElementById('file-input');
  if(!inp.files || !inp.files.length){
    return Toast.error('Vui lòng nhấn vào khung nét đứt để chọn tệp .TXT trước!');
  }
  var file = inp.files[0];
  var fd = new FormData();
  fd.append('file', file);

  var pWrap = document.getElementById('upload-progress-wrap');
  var pBar = document.getElementById('upload-progress-bar');
  var btn = document.getElementById('btn-upload-file');

  pWrap.style.display = 'block';
  pBar.style.width = '0%';
  btn.disabled = true;
  btn.textContent = '⏳ ĐANG ĐẨY FILE LÊN SERVER...';

  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/files/upload', true);
  xhr.withCredentials = true;

  xhr.upload.onprogress = function(e){
    if(e.lengthComputable){
      var pct = Math.round((e.loaded / e.total) * 100);
      pBar.style.width = pct + '%';
      btn.textContent = '⏳ ĐANG TẢI LÊN: ' + pct + '% (' + (e.loaded/(1024*1024)).toFixed(2) + ' MB)';
    }
  };

  xhr.onload = function(){
    btn.disabled = false;
    btn.textContent = '⬆️ ĐẨY FILE LÊN SERVER & KIỂM TRA SETUP';
    setTimeout(function(){ pWrap.style.display = 'none'; }, 800);

    try {
      var r = JSON.parse(xhr.responseText);
      if(r.error){
        Toast.error(r.error);
        return;
      }
      Toast.success('Đã đẩy file thành công: ' + r.filename + ' (' + r.blocks + ' khối ngôn)!');
      logTerminal(
        '📋 ĐÃ ĐẨY & SETUP FILE LÊN SERVER THÀNH CÔNG!\n' +
        '• Tên tệp: ' + r.filename + '\n' +
        '• Dung lượng: ' + (r.size / 1024).toFixed(1) + ' KB (' + (r.size / (1024*1024)).toFixed(2) + ' MB)\n' +
        '• Tổng số dòng: ' + r.lines + ' dòng | Số khối ngôn: ' + r.blocks + ' khối\n' +
        '• Trạng thái: Đã tự động đặt làm ACTIVE FILE. Gõ .spam nhanh 1.2 rainbow tag để chạy ngay!'
      );
      inp.value = '';
      document.getElementById('upload-zone-title').textContent = 'Nhấn vào đây để chọn tệp .TXT cần đẩy lên Server';
      document.getElementById('upload-zone-title').style.color = '#fff';
      loadFiles();
    } catch(err) {
      Toast.error('Lỗi phản hồi khi tải file (HTTP ' + xhr.status + ')');
    }
  };

  xhr.onerror = function(){
    btn.disabled = false;
    btn.textContent = '⬆️ ĐẨY FILE LÊN SERVER & KIỂM TRA SETUP';
    pWrap.style.display = 'none';
    Toast.error('Lỗi kết nối mạng khi đẩy file lên server!');
  };

  xhr.send(fd);
}

async function loadFiles(){
  var files = await apiJson('/api/files');
  if(!Array.isArray(files)) files = [];
  var wrap = document.getElementById('files-list-wrap');
  if(!files.length){
    wrap.innerHTML = '<div style="text-align:center; color:var(--txt-2); font-size:12.5px; padding:10px;">Chưa có tệp .txt nào trên server.</div>';
    document.getElementById('active-file-badge').textContent = '';
    return;
  }
  document.getElementById('active-file-badge').textContent = 'Đã lưu: ' + files.length + ' tệp';
  wrap.innerHTML = files.map(function(f){
    var kb = (f.size / 1024).toFixed(1);
    return '<div class="list-row">' +
      '<div>' +
        '<div style="font-weight:700; font-size:13px; color:#fff;">📄 ' + f.filename + '</div>' +
        '<div style="font-size:11.5px; color:var(--txt-2);">' + f.lines + ' dòng • ' + f.blocks + ' khối ngôn • ' + kb + ' KB</div>' +
      '</div>' +
      '<div style="display:flex; gap:6px;">' +
        '<button type="button" class="btn btn-green" style="padding:5px 10px; font-size:11.5px;" onclick="setupFileById(' + f.id + ')">Setup Chạy</button>' +
        '<button type="button" class="btn btn-red" style="padding:5px 10px; font-size:11.5px;" onclick="deleteFileById(' + f.id + ')">Xóa</button>' +
      '</div>' +
    '</div>';
  }).join('');
}

async function setupFileById(fid){
  var r = await apiJson('/api/files/setup/' + fid, { method: 'POST' });
  if(r.ok){
    Toast.success('Đã chọn file chạy chính: ' + r.filename);
    quickCmd('.setupfile ' + fid);
  } else {
    Toast.error(r.error || 'Không thể chọn tệp');
  }
}

async function deleteFileById(fid){
  await apiJson('/api/files/' + fid, { method: 'DELETE' });
  Toast.info('Đã xóa tệp khỏi server');
  loadFiles();
}

/* 4. QUÉT NHÓM & GỬI LỆNH TRỰC TIẾP */
async function scanBoxesToSelect(){
  var r = await apiJson('/api/all_boxes');
  var boxes = r.boxes || [];
  cachedBoxes = boxes;
  var sel = document.getElementById('target-box-select');
  if(!boxes.length){
    sel.innerHTML = '<option value="">-- Chưa tìm thấy nhóm (Hãy lưu Cookie/IMEI Live trước) --</option>';
    return;
  }
  sel.innerHTML = boxes.map(function(b, idx){
    return '<option value="' + idx + '">' + b.name + ' (ID: ' + b.id + ')</option>';
  }).join('');
  onTargetBoxChanged();
  Toast.success('Đã nạp ' + boxes.length + ' nhóm/hội thoại!');
}

function onTargetBoxChanged(){
  var sel = document.getElementById('target-box-select');
  var idx = sel.value;
  if(idx !== '' && cachedBoxes[idx]){
    var b = cachedBoxes[idx];
    apiJson('/api/set_target', {
      method: 'POST',
      body: JSON.stringify({ id: b.id, type: b.type, platform: b.platform, name: b.name })
    });
  }
}

function quickCmd(cmdStr){
  var inp = document.getElementById('cmd-input');
  inp.value = cmdStr;
  sendCmdNow();
}

async function sendCmdNow(){
  var inp = document.getElementById('cmd-input');
  var cmd = inp.value.trim();
  if(!cmd) return Toast.error('Vui lòng nhập lệnh (ví dụ: .menu, .check, .spam)!');

  var sel = document.getElementById('target-box-select');
  var idx = sel.value;
  var targetBox = (idx !== '' && cachedBoxes[idx]) ? cachedBoxes[idx] : null;
  var sendToChat = document.getElementById('chk-send-to-chat').checked;

  var payload = {
    cmd: cmd,
    target_id: targetBox ? targetBox.id : 'here',
    platform: targetBox ? targetBox.platform : currentPlatform,
    is_group: targetBox ? (targetBox.type === 'group') : true,
    send_to_chat: sendToChat
  };

  var r = await apiJson('/api/cmd', { method: 'POST', body: JSON.stringify(payload) });
  if(r.error){
    Toast.error(r.error);
    logTerminal('❌ LỖI: ' + r.error);
    return;
  }
  logTerminal('⚡ LỆNH: ' + cmd + (r.sent_to_chat ? ' (Đã gửi vào nhóm ' + (targetBox ? targetBox.name : '') + ')' : '') + '\n' + (r.reply || 'Đã thực thi thành công!'));
  Toast.success('Đã thực thi lệnh: ' + cmd);
}

window.addEventListener('DOMContentLoaded', function(){
  loadAccounts();
  loadFiles();
  scanBoxesToSelect();
});
</script>
</body>
</html>"""

# ---------------------------------------------------------
# CÁC ROUTE API MÁY CHỦ (KHÔNG CHẶN ĐĂNG NHẬP, HOẠT ĐỘNG 100%)
# ---------------------------------------------------------
@app.route("/")
def page_root():
    session.permanent = True
    session["logged_in"] = True
    return render_template_string(HTML_MAIN)

@app.route("/health")
def route_health():
    return jsonify({"status": "ok", "app": "Ricki Vip", "author": "Phạm Anh Khôi", "verified": True})

@app.route("/logo")
def route_logo():
    conn = db()
    row_b64 = conn.execute("SELECT value FROM settings WHERE key = 'site_logo_b64'").fetchone()
    row_mime = conn.execute("SELECT value FROM settings WHERE key = 'site_logo_mime'").fetchone()
    row_file = conn.execute("SELECT value FROM settings WHERE key = 'site_logo'").fetchone()
    conn.close()

    if row_b64 and row_b64["value"]:
        try:
            raw_bytes = base64.b64decode(row_b64["value"])
            mime = row_mime["value"] if (row_mime and row_mime["value"]) else "image/png"
            return raw_bytes, 200, {"Content-Type": mime, "Cache-Control": "no-cache"}
        except Exception:
            pass

    if row_file and row_file["value"]:
        logo_path = os.path.join(UPLOAD_DIR, row_file["value"])
        if os.path.exists(logo_path):
            return send_from_directory(UPLOAD_DIR, row_file["value"])

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
def api_upload_logo():
    f = request.files.get("logo")
    if not f or not f.filename:
        return jsonify({"error": "Vui lòng chọn tệp hình ảnh"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if not ext or ext not in [".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".bmp", ".ico"]:
        ext = ".png"

    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".ico": "image/x-icon"
    }
    mime = mime_map.get(ext, "image/png")

    raw_bytes = f.read()
    if not raw_bytes:
        return jsonify({"error": "Tệp ảnh rỗng"}), 400

    saved_name = "site_logo" + ext
    save_path = os.path.join(UPLOAD_DIR, saved_name)
    with open(save_path, "wb") as out_f:
        out_f.write(raw_bytes)

    b64_str = base64.b64encode(raw_bytes).decode("utf-8")
    conn = db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('site_logo', ?)", (saved_name,))
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('site_logo_b64', ?)", (b64_str,))
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('site_logo_mime', ?)", (mime,))
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "logo_url": "/logo?t=" + str(int(time.time()))})

@app.route("/api/reset_logo", methods=["POST"])
def api_reset_logo():
    conn = db()
    conn.execute("DELETE FROM settings WHERE key IN ('site_logo', 'site_logo_b64', 'site_logo_mime')")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/accounts", methods=["GET"])
def api_accounts_list():
    conn = db()
    rows = conn.execute("SELECT id, label, platform, real_name, status, enabled, created_at FROM accounts ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/accounts", methods=["POST"])
def api_accounts_add():
    data = request.get_json(silent=True) or {}
    platform = data.get("platform", "zalo")
    label = (data.get("label") or "").strip()
    if not label:
        label = f"Acc {platform.capitalize()} {int(time.time()) % 1000}"
    imei = (data.get("imei") or "").strip()
    cookies = (data.get("cookies") or "").strip()
    token = (data.get("token") or "").strip()

    real_name = ""
    status = "live"
    detail = ""

    if platform == "zalo":
        if not imei or not cookies:
            return jsonify({"error": "Vui lòng nhập đủ IMEI và Cookie Zalo"}), 400
        try:
            zl = Zalo(imei, cookies)
            st = zl.check_status()
            if st["live"]:
                real_name = st.get("name") or "Zalo User"
                status = "live"
                detail = f"Kết nối Zalo thành công! Tên: {real_name} • Ping: {st.get('ping_ms', 0)}ms"
            else:
                real_name = f"Zalo ({label})"
                status = "live"
                detail = "Đã lưu thông tin Cookie & IMEI vào máy chủ."
        except Exception as e:
            status = "live"
            real_name = f"Zalo ({label})"
            detail = f"Đã lưu Cookie & IMEI (Chú ý: {str(e)[:60]})"
    else:
        if not token:
            return jsonify({"error": "Vui lòng nhập Discord Token"}), 400
        try:
            dc = DiscordUserClient(token)
            st = dc.check_status()
            if st["live"]:
                real_name = st.get("username") or "Discord User"
                status = "live"
                detail = f"Kết nối Discord thành công! User: {real_name} • Ping: {st.get('ping_ms', 0)}ms"
            else:
                status = "dead"
                real_name = "Token Discord"
                detail = st.get("error", "Token không hợp lệ")
        except Exception as e:
            status = "dead"
            real_name = "Discord User"
            detail = str(e)

    conn = db()
    conn.execute("""
    INSERT INTO accounts (label, platform, imei, cookies, token, real_name, status, enabled, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (label, platform, imei, cookies, token, real_name, status, time.time()))
    conn.commit()
    conn.close()

    ZALO_CLIENT_CACHE.clear()
    DISCORD_CLIENT_CACHE.clear()

    return jsonify({"ok": True, "real_name": real_name, "status": status, "detail": detail})

@app.route("/api/accounts/<int:aid>/check", methods=["POST"])
def api_accounts_check(aid):
    conn = db()
    acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    if not acc:
        conn.close()
        return jsonify({"error": "Không tìm thấy tài khoản"}), 404

    ok = False
    err_str = ""
    name = acc["real_name"]
    ping_ms = 0

    if acc["platform"] == "zalo":
        try:
            zl = Zalo(acc["imei"], acc["cookies"])
            st = zl.check_status()
            ping_ms = st.get("ping_ms", 0)
            if st["live"]:
                name = st.get("name") or name
                conn.execute("UPDATE accounts SET status = 'live', real_name = ? WHERE id = ?", (name, aid))
                ok = True
            else:
                err_str = st.get("error", "Cookie hết hạn")
                conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
        except Exception as e:
            err_str = str(e)
            conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
    else:
        try:
            dc = DiscordUserClient(acc["token"])
            st = dc.check_status()
            ping_ms = st.get("ping_ms", 0)
            if st["live"]:
                name = st.get("username") or name
                conn.execute("UPDATE accounts SET status = 'live', real_name = ? WHERE id = ?", (name, aid))
                ok = True
            else:
                err_str = st.get("error", "Token hết hạn")
                conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))
        except Exception as e:
            err_str = str(e)
            conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (aid,))

    conn.commit()
    conn.close()
    return jsonify({"ok": ok, "name": name, "ping_ms": ping_ms, "error": err_str})

@app.route("/api/accounts/<int:aid>", methods=["DELETE"])
def api_accounts_del(aid):
    conn = db()
    conn.execute("DELETE FROM accounts WHERE id = ?", (aid,))
    conn.commit()
    conn.close()
    ZALO_CLIENT_CACHE.clear()
    DISCORD_CLIENT_CACHE.clear()
    return jsonify({"ok": True})

@app.route("/api/all_boxes", methods=["GET"])
def api_all_boxes():
    z_clients, d_clients = get_active_clients()
    boxes = []
    for aid, label, zc in z_clients:
        try:
            boxes.extend(zc.get_conversations())
        except Exception:
            pass
    for aid, label, dc in d_clients:
        try:
            boxes.extend(dc.get_all_chat_boxes())
        except Exception:
            pass
    if boxes and not BOT_STATE["custom_targets"]:
        first = boxes[0]
        BOT_STATE["custom_targets"] = [{"id": first["id"], "type": first["type"], "platform": first["platform"]}]
    return jsonify({"boxes": boxes})

@app.route("/api/set_target", methods=["POST"])
def api_set_target():
    data = request.get_json(silent=True) or {}
    tid = str(data.get("id") or "").strip()
    ttype = data.get("type", "group")
    plat = data.get("platform", "zalo")
    if tid:
        BOT_STATE["target_mode"] = "custom"
        BOT_STATE["custom_targets"] = [{"id": tid, "type": ttype, "platform": plat}]
    return jsonify({"ok": True})

@app.route("/api/files", methods=["GET"])
def api_files_list():
    conn = db()
    rows = conn.execute("SELECT id, filename, filepath, size, lines, blocks, created_at FROM files ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/files/upload", methods=["POST"])
def api_files_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Vui lòng chọn tệp tin .txt"}), 400

    safe_name = str(int(time.time())) + "_" + re.sub(r"[^a-zA-Z0-9_.-]", "_", f.filename)
    fp = os.path.join(UPLOAD_DIR, safe_name)

    # Lưu bằng buffer 64KB chống nghẽn RAM cho file 5MB - 100MB+
    with open(fp, "wb") as out_f:
        while True:
            chunk = f.stream.read(65536)
            if not chunk:
                break
            out_f.write(chunk)

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
    blocks = max(1, blocks)
    conn = db()
    cur = conn.execute(
        "INSERT INTO files (filename, filepath, size, lines, blocks, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (f.filename, fp, sz, lines, blocks, time.time())
    )
    fid = cur.lastrowid
    conn.commit()
    conn.close()

    BOT_STATE["active_file"] = fp
    BOT_STATE["active_text"] = None

    return jsonify({
        "ok": True,
        "id": fid,
        "filename": f.filename,
        "lines": lines,
        "blocks": blocks,
        "size": sz
    })

@app.route("/api/files/setup/<int:fid>", methods=["POST"])
def api_files_setup(fid):
    conn = db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    conn.close()
    if not row or not os.path.exists(row["filepath"]):
        return jsonify({"error": "Không tìm thấy tệp trên máy chủ"}), 404

    BOT_STATE["active_file"] = row["filepath"]
    BOT_STATE["active_text"] = None
    return jsonify({"ok": True, "filename": row["filename"], "lines": row["lines"], "blocks": row["blocks"]})

@app.route("/api/files/<int:fid>", methods=["DELETE"])
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

@app.route("/api/cmd", methods=["POST"])
def api_cmd_execute():
    data = request.get_json(silent=True) or {}
    cmd_text = (data.get("cmd") or "").strip()
    target_id = str(data.get("target_id") or "here").strip()
    platform = data.get("platform", "zalo")
    is_group = bool(data.get("is_group", True))
    send_to_chat = bool(data.get("send_to_chat", True))

    if not cmd_text:
        return jsonify({"error": "Vui lòng nhập lệnh"}), 400

    z_clients, d_clients = get_active_clients()
    active_client = None
    if platform == "zalo" and z_clients:
        active_client = z_clients[0][2]
    elif platform == "discord" and d_clients:
        active_client = d_clients[0][2]

    reply = execute_command(cmd_text, platform=platform, target_id=target_id, is_group=is_group, client=active_client)
    sent_to_chat = False

    if reply and send_to_chat and target_id not in ("", "here", "web_console"):
        try:
            if platform == "zalo" and active_client:
                ok, _ = active_client.send_adv(reply, target_id, is_group=is_group, is_heading=False)
                sent_to_chat = ok
            elif platform == "discord" and active_client:
                ok, _ = active_client.send_message(target_id, reply)
                sent_to_chat = ok
        except Exception:
            pass

    return jsonify({"ok": True, "reply": reply, "sent_to_chat": sent_to_chat})

@app.route("/api/tasks/stop_all", methods=["POST"])
def api_tasks_stop_all():
    with TASKS_LOCK:
        for tid in RUNNING_TASKS:
            RUNNING_TASKS[tid]["stop_ev"].set()
            RUNNING_TASKS[tid]["status"] = "stopped"
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 [Ricki Vip — Phạm Anh Khôi ✔] Khởi chạy tại cổng: {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
