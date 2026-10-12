# ============================================================
# Copyright © 2026 Pham Anh Khoi • All Rights Reserved ⚡
# System: ALB Forge — I Love Ngọc Hân Luxury Edition
# ============================================================
import os
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
app.secret_key = os.environ.get("SECRET_KEY", "pak-ngoc-han-verified-2026")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

DDOS_LIMIT_PER_MINUTE = 100
DDOS_BURST_PER_SEC = 20
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
                    "error": "IP bị chặn do gửi yêu cầu quá nhanh. Vui lòng thử lại sau.",
                    "retry_after": int(ip_blocked_until[ip] - now)
                }), 429
            else:
                del ip_blocked_until[ip]

        history = [t for t in ip_request_history[ip] if now - t < 60]
        ip_request_history[ip] = history

        burst = sum(1 for t in history if now - t <= 1.0)
        if burst > DDOS_BURST_PER_SEC or len(history) > DDOS_LIMIT_PER_MINUTE:
            ip_blocked_until[ip] = now + 300
            return jsonify({"error": "Phát hiện lưu lượng bất thường. IP đã bị khóa trong 5 phút."}), 429

        ip_request_history[ip].append(now)

    if not session.get("human_verified") and request.endpoint not in ("verify_gate", "api_verify_human"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Chưa hoàn tất kiểm tra an toàn"}), 403
        return redirect(url_for("verify_gate"))


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


ZALO_PALETTE = [
    {"id": "red",    "name": "Đỏ Rực",       "hex": "#e8453c"},
    {"id": "yellow", "name": "Vàng Chói",     "hex": "#f5c500"},
    {"id": "green",  "name": "Xanh Lá",      "hex": "#00b14f"},
    {"id": "orange", "name": "Cam Lửa",      "hex": "#ff8c00"},
    {"id": "ocean",  "name": "Xanh Biển",    "hex": "#0091ff"},
    {"id": "blue",   "name": "Xanh Dương",   "hex": "#0068ff"},
    {"id": "purple", "name": "Tím Pha Lê",   "hex": "#a05eff"},
    {"id": "pink",   "name": "Hồng Ngọc Hân","hex": "#ff47a8"},
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
    "😹", "😈", "🔥", "😤", "🤮", "🤢", "🐒", "✌️", "☝️", "😁"
]


def get_icon_hard():
    if random.random() < 0.65:
        return random.choice(ZALO_ICON_HARD)
    return random.choice(ZALO_ICON_UNICODE)


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
            raise Exception("Phiên đăng nhập hết hạn hoặc Cookie/IMEI không hợp lệ")
        self.uid = ud.get("send2me_id")
        self.secret_key = ud.get("zpw_enk")
        self.display_name = ud.get("displayName") or ud.get("zaloName")
        self.zalo_name = ud.get("zaloName")
        self.username = ud.get("username")
        if not self.secret_key:
            raise Exception("Không thể lấy khóa xác thực")

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

        friends = self.friends()
        for f in friends:
            fid = str(f.get("id"))
            if fid in uids and fid not in members_dict:
                members_dict[fid] = f.get("name")

        out = []
        for uid in uids:
            real_name = members_dict.get(uid) or f"Thành viên {uid[-6:]}"
            out.append({
                "id": str(uid),
                "name": real_name
            })
        return out

    def build_mentions(self, text, mentions, tag_all=False):
        final = text
        m_arr = []
        if tag_all:
            tag_str = "@All"
            pos = utf16_len(final) + (1 if final else 0)
            final = (final + " " + tag_str) if final else tag_str
            m_arr.append({"uid": "0", "pos": pos, "len": utf16_len(tag_str), "type": 1})
            return final, m_arr

        if not mentions:
            return text, []

        for m in mentions:
            raw_name = str(m.get("name", "")).strip()
            name = raw_name.split(" (")[0] if " (" in raw_name else raw_name
            uid = str(m.get("uid") or m.get("id") or "").strip()
            if not name or not uid: continue
            tag_str = "@" + name
            pos = utf16_len(final) + (1 if final else 0)
            final = (final + " " + tag_str) if final else tag_str
            m_arr.append({"uid": str(uid), "pos": pos, "len": utf16_len(tag_str), "type": 0})
        return final, m_arr

    def send(self, msg, thread_id, color_item=None, is_group=True, mentions=None, tag_all=False, is_heading=True):
        url = ("https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
               if is_group
               else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms")

        final_msg = msg.replace("\r\n", "\n").replace("\r", "\n")

        if is_heading:
            lines = final_msg.split("\n")
            h_lines = []
            for ln in lines:
                ln_s = ln.strip()
                if ln_s and not ln_s.startswith("#"):
                    h_lines.append(f"# {ln_s}")
                else:
                    h_lines.append(ln)
            final_msg = "\n".join(h_lines)

        m_arr = []
        if mentions or tag_all:
            final_msg, m_arr = self.build_mentions(final_msg, mentions, tag_all=tag_all)

        pl = {
            "message": final_msg,
            "clientId": str(int(time.time() * 1000)) + str(random.randint(100, 999)),
            "imei": self.imei,
        }
        if m_arr:
            pl["mentions"] = json.dumps(m_arr, ensure_ascii=False)

        if color_item and isinstance(color_item, dict):
            c_id = color_item.get("id", "red")
            c_hex = color_item.get("hex", "#e8453c")
            pl["msgColor"] = c_id
            pl["color"] = c_hex
            u16_length = utf16_len(final_msg)
            styles = [
                {"offset": 0, "len": u16_length, "type": "color", "value": c_hex},
                {"offset": 0, "len": u16_length, "type": "color", "value": c_id},
                {"start": 0, "len": u16_length, "st": f"c_{c_hex}"}
            ]
            pl["styles"] = json.dumps(styles)

        if is_group:
            pl["visibility"] = 0
            pl["grid"] = str(thread_id)
        else:
            pl["toid"] = str(thread_id)

        enc = self._enc(pl)
        return self.s.post(url, params={"zpw_ver": 645, "zpw_type": 30},
                           data={"params": enc}, timeout=15)


CSS_STYLE = """
:root {
  --bg-page: #fbfbfd;
  --bg-card: rgba(255, 255, 255, 0.94);
  --border-color: rgba(226, 232, 240, 0.85);
  --txt-0: #0f172a;
  --txt-1: #334155;
  --txt-2: #64748b;
  --accent: #e11d48;
  --grad-primary: linear-gradient(135deg, #f43f5e 0%, #e11d48 100%);
  --grad-dark: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  --shadow-soft: 0 10px 30px rgba(15, 23, 42, 0.05);
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
}
#particles-canvas {
  position: fixed; inset: 0; pointer-events: none; z-index: 90; width: 100%; height: 100%;
}
body::before {
  content: ''; position: fixed; inset: 0;
  background-image: url('/static/bg.jpg');
  background-size: cover; background-position: center; background-repeat: no-repeat;
  opacity: 0.16; filter: blur(3px); pointer-events: none; z-index: -1;
}

.header {
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(25px);
  padding: 10px 18px;
  border-bottom: 1px solid var(--border-color);
  position: sticky; top:0; z-index: 100;
  box-shadow: 0 2px 12px rgba(15, 23, 42, 0.03);
}
.header-inner { max-width: 1050px; margin: 0 auto; display: flex; align-items: center; gap: 12px; }
.logo-box {
  width: 44px; height: 44px; border-radius: 50%;
  overflow: hidden; border: 2px solid #fff;
  box-shadow: 0 4px 16px rgba(225, 29, 72, 0.3);
  background: #fff; flex-shrink: 0;
  animation: pulseLogo 3s ease-in-out infinite;
}
@keyframes pulseLogo { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.05); } }
.logo-box img { width: 100%; height: 100%; object-fit: cover; }
.header-meta { flex: 1; min-width: 0; }
.header-meta h1 { font-family: 'Orbitron', sans-serif; font-size: 14px; font-weight: 900; color: var(--txt-0); }
.header-meta p { font-size: 9.5px; color: var(--txt-2); font-weight: 700; margin-top: 2px; display: flex; align-items: center; gap: 4px; }

.v-badge {
  display: inline-flex; align-items: center; justify-content: center;
  color: #0084ff; font-weight: 900; filter: drop-shadow(0 2px 4px rgba(0,132,255,0.3));
}

.container { max-width: 1050px; margin: 0 auto; padding: 14px; position: relative; z-index: 10; }
.panel { display: none; animation: fadeIn .28s var(--ease) both; }
.panel.active { display: block; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

.card {
  background: var(--bg-card); backdrop-filter: blur(20px);
  padding: 16px; border-radius: 18px; border: 1px solid var(--border-color);
  box-shadow: var(--shadow-soft); margin-bottom: 12px;
}
.card h2 {
  font-size: 11.5px; font-weight: 900; letter-spacing: .5px; margin-bottom: 12px;
  display: flex; align-items: center; justify-content: space-between; color: var(--txt-0);
}

.btn-pill {
  padding: 8px 14px; border-radius: 99px; border: none; cursor: pointer;
  font-size: 10.5px; font-weight: 800; letter-spacing: .4px;
  display: inline-flex; align-items: center; gap: 6px; transition: all .25s var(--ease);
  position: relative; overflow: hidden;
}
.btn-pill::after {
  content: ''; position: absolute; top: -50%; left: -60%; width: 40%; height: 200%;
  background: linear-gradient(60deg, transparent, rgba(255,255,255,0.4), transparent);
  transform: rotate(25deg); transition: all 0.6s;
}
.btn-pill:hover::after { left: 130%; }
.btn-pill:hover { transform: translateY(-2px); filter: brightness(1.05); }
.btn-pill:active { transform: translateY(0) scale(0.96); }
.btn-pill.primary { background: var(--grad-primary); color: #fff; box-shadow: 0 4px 14px rgba(225, 29, 72, 0.28); }
.btn-pill.dark { background: var(--grad-dark); color: #fff; }
.btn-pill.light { background: #f1f5f9; color: var(--txt-1); border: 1px solid var(--border-color); }
.btn-pill.danger { background: #fee2e2; color: #b91c1c; }
.btn-pill.full { width: 100%; justify-content: center; padding: 11px; }

.btn-round {
  width: 44px; height: 44px; border-radius: 50%; border: none; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  transition: all .25s var(--ease); margin: 3px;
}
.btn-round svg { width: 18px; height: 18px; }
.btn-round:hover { transform: scale(1.08); }
.btn-round.action-start { background: #10b981; color: #fff; box-shadow: 0 4px 14px rgba(16, 185, 129, 0.3); }
.btn-round.action-stop { background: #ef4444; color: #fff; box-shadow: 0 4px 14px rgba(239, 68, 68, 0.3); }

.form-group { margin-bottom: 11px; }
.form-group label { display: block; margin-bottom: 5px; font-size: 9.5px; font-weight: 800; color: var(--txt-2); }
.form-group input, .form-group textarea, .form-group select {
  width: 100%; padding: 11px 13px; border: 1.5px solid var(--border-color); border-radius: 12px;
  font-size: 12px; background: #fff; color: var(--txt-0); transition: border-color .2s;
}
.form-group input:focus, .form-group textarea:focus, .form-group select:focus {
  outline: none; border-color: var(--accent);
}
.form-group textarea { min-height: 85px; font-family: 'JetBrains Mono', monospace; font-size: 11.5px; }

.chip-bar { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 4px; }
.chip-item {
  padding: 6px 12px; background: #fff; color: var(--txt-2); border-radius: 99px;
  font-size: 10px; font-weight: 800; cursor: pointer; border: 1px solid var(--border-color);
  transition: all .2s;
}
.chip-item:hover { border-color: var(--accent); color: var(--accent); }
.chip-item.active { background: var(--grad-primary); color: #fff; border-color: transparent; }

.toggle-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 6px; margin-bottom: 11px; }
.toggle-item {
  padding: 9px; border: 1px solid var(--border-color); border-radius: 12px;
  cursor: pointer; text-align: center; font-weight: 800; font-size: 10px;
  background: #fff; color: var(--txt-2); transition: all .2s;
}
.toggle-item.active { background: var(--grad-primary); color: #fff; border-color: transparent; box-shadow: 0 4px 10px rgba(225, 29, 72, 0.2); }

.table-wrap { overflow-x: auto; border-radius: 12px; border: 1px solid var(--border-color); background: #fff; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { padding: 9px 8px; text-align: left; font-size: 10.5px; border-bottom: 1px solid #f1f5f9; white-space: nowrap; }
.table th { background: #f8fafc; font-weight: 800; color: var(--txt-2); font-size: 8.5px; }

.status-badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 99px; font-size: 9px; font-weight: 800; }
.status-badge.live { background: #dcfce7; color: #15803d; }
.status-badge.dead { background: #fee2e2; color: #b91c1c; }

.box-list { max-height: 280px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 12px; padding: 6px; background: #fff; }
.box-item {
  padding: 8px 10px; border-radius: 9px; background: #f8fafc; margin-bottom: 4px;
  cursor: pointer; border: 1px solid var(--border-color); display: flex; align-items: center; gap: 8px;
  transition: all .15s;
}
.box-item:hover { border-color: var(--accent); background: #fff; }
.box-item.selected { border-color: var(--accent); background: #fff1f2; }
.box-item .check-mark {
  width: 16px; height: 16px; border: 1.5px solid var(--txt-2); border-radius: 4px;
  display: flex; align-items: center; justify-content: center; font-size: 9px; color: transparent; font-weight: 900;
}
.box-item.selected .check-mark { background: var(--accent); border-color: var(--accent); color: #fff; }
.box-item .b-title { font-weight: 700; font-size: 11.5px; color: var(--txt-0); }
.box-item .b-sub { font-size: 9px; color: var(--txt-2); font-family: 'JetBrains Mono', monospace; }

.bottom-dock {
  position: fixed; bottom: 12px; left: 50%; transform: translateX(-50%);
  width: calc(100% - 24px); max-width: 480px;
  background: rgba(255, 255, 255, 0.94); backdrop-filter: blur(24px);
  border: 1px solid rgba(226, 232, 240, 0.95);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.1);
  border-radius: 99px; display: grid; grid-template-columns: repeat(4, 1fr);
  padding: 5px; gap: 4px; z-index: 999;
}
.bottom-dock .dock-btn {
  padding: 8px 2px; border-radius: 99px; cursor: pointer; font-size: 9.5px; font-weight: 800;
  text-align: center; color: var(--txt-2); display: flex; flex-direction: column; align-items: center;
  gap: 2px; background: transparent; border: none; transition: all .2s;
}
.bottom-dock .dock-btn svg { width: 17px; height: 17px; }
.bottom-dock .dock-btn.active { background: var(--grad-primary); color: #fff; }

#toast-stack { position: fixed; top: 12px; right: 12px; z-index: 99999; max-width: 320px; width: calc(100% - 24px); pointer-events: none; }
.toast {
  pointer-events: auto; padding: 11px 14px; border-radius: 12px;
  background: rgba(255, 255, 255, 0.98); border: 1px solid var(--border-color);
  box-shadow: 0 10px 25px rgba(15, 23, 42, 0.1); display: flex; flex-direction: column; gap: 2px;
  animation: toastIn .2s var(--ease) both;
}
.toast.swipe-up { animation: toastUp .18s ease-out forwards; }
@keyframes toastIn { from { opacity: 0; transform: translateY(-15px); } to { opacity: 1; transform: translateY(0); } }
@keyframes toastUp { to { opacity: 0; transform: translateY(-30px); } }
.toast .t-head { font-size: 10.5px; font-weight: 900; color: var(--txt-0); }
.toast .t-body { font-size: 10px; font-weight: 600; color: var(--txt-2); }
"""

HTML_GATE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Bảo Mật ALB Shield — Cổng Xác Thực</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_STYLE + """
body { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
.gate-card {
  background: rgba(255, 255, 255, 0.98); border: 1px solid var(--border-color);
  border-radius: 24px; padding: 36px 26px; max-width: 390px; width: 100%; text-align: center;
  box-shadow: 0 25px 60px rgba(15, 23, 42, 0.08); position: relative; overflow: hidden;
}
.radar-scanner {
  width: 90px; height: 90px; margin: 0 auto 18px; border-radius: 50%;
  position: relative; display: flex; align-items: center; justify-content: center;
  background: radial-gradient(circle, rgba(225,29,72,0.1) 0%, transparent 70%);
  border: 2px dashed rgba(225,29,72,0.4);
}
.radar-scanner::before {
  content: ''; position: absolute; inset: 0; border-radius: 50%;
  border: 2px solid transparent; border-top-color: var(--accent);
  animation: spin 1.2s linear infinite;
}
@keyframes spin { 100% { transform: rotate(360deg); } }
.radar-icon { font-size: 32px; }
.progress-line {
  height: 4px; width: 100%; background: #f1f5f9; border-radius: 99px;
  overflow: hidden; margin: 16px 0; display: none;
}
.progress-fill {
  height: 100%; width: 0%; background: var(--grad-primary);
  border-radius: 99px; transition: width 0.35s ease;
}
.copyright-tag { margin-top: 18px; font-size: 9.5px; color: var(--txt-2); font-weight: 800; }
</style>
</head>
<body>
<div class="gate-card">
  <div class="radar-scanner">
    <div class="radar-icon">🛡️</div>
  </div>
  <h1 style="font-family:'Orbitron',sans-serif; font-size:16px; margin-bottom:6px;">CỔNG BẢO MẬT ANTI-DDOS</h1>
  <p id="scan-status" style="font-size:11px; color:var(--txt-2); min-height:30px;">Hệ thống yêu cầu xác thực danh tính để ngăn chặn các lượt truy vấn ảo.</p>
  <div class="progress-line" id="p-box"><div class="progress-fill" id="p-bar"></div></div>
  <button class="btn-pill primary full" id="start-btn" onclick="startVerification()">Bắt đầu quét bảo mật & Xác thực</button>
  <div class="copyright-tag">Copyright © 2026 Pham Anh Khoi • All Rights Reserved ⚡</div>
</div>
<script>
var pBox = document.getElementById('p-box');
var pBar = document.getElementById('p-bar');
var statusTxt = document.getElementById('scan-status');
var startBtn = document.getElementById('start-btn');

var steps = [
  { p: 25, txt: 'Đang kiểm tra địa chỉ IP và tần suất truy vấn...' },
  { p: 60, txt: 'Đang phân tích chứng chỉ trình duyệt bảo mật...' },
  { p: 85, txt: 'Xác thực hoàn tất! Cấp quyền truy cập hệ thống...' },
  { p: 100, txt: 'Đang chuyển hướng vào bảng điều khiển...' }
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
</script>
</body>
</html>
"""

HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Đăng Nhập Hệ Thống</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_STYLE + """
body { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
.login-card {
  background: rgba(255, 255, 255, 0.98); border: 1px solid var(--border-color);
  border-radius: 24px; padding: 36px 26px; max-width: 380px; width: 100%; text-align: center;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.08);
}
.login-logo { width: 78px; height: 78px; border-radius: 50%; overflow: hidden; margin: 0 auto 14px; border: 2px solid var(--accent); }
.login-logo img { width: 100%; height: 100%; object-fit: cover; }
.err-msg { background: #fee2e2; color: #b91c1c; padding: 9px; border-radius: 10px; font-size: 11px; font-weight: 700; margin-bottom: 14px; text-align: left; }
</style>
</head>
<body>
<div class="login-card">
  <div class="login-logo">
    <img src="/static/logo.png" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 100 100\\'><circle cx=\\'50\\' cy=\\'50\\' r=\\'50\\' fill=\\'%23e11d48\\'/><text x=\\'50\\' y=\\'58\\' text-anchor=\\'middle\\' font-size=\\'36\\' fill=\\'white\\'>❤</text></svg>'">
  </div>
  <h1 style="font-family:'Orbitron',sans-serif; font-size:18px; margin-bottom:4px;">I LOVE NGỌC HÂN</h1>
  <p style="font-size:10px; color:var(--txt-2); font-weight:700; margin-bottom:20px; display:flex; align-items:center; justify-content:center; gap:4px;">
    Bản quyền thiết kế: <span class="v-badge"><svg viewBox="0 0 24 24" width="14" height="14" fill="#0084ff"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></span> Phạm Anh Khôi
  </p>
  {% if error %}<div class="err-msg">⚠️ {{ error }}</div>{% endif %}
  <form method="POST">
    <div class="form-group" style="text-align:left;">
      <input type="password" name="password" placeholder="Nhập mật khẩu truy cập..." required autofocus>
    </div>
    <button type="submit" class="btn-pill primary full">💖 Đăng nhập hệ thống</button>
  </form>
  <div style="margin-top:18px; font-size:9.5px; color:var(--txt-2); font-weight:800;">Copyright © 2026 Pham Anh Khoi • All Rights Reserved ⚡</div>
</div>
</body>
</html>
"""

HTML_INDEX = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Bảng Điều Khiển — I Love Ngọc Hân</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_STYLE + """
</style>
</head>
<body>
<canvas id="particles-canvas"></canvas>

<div class="header">
  <div class="header-inner">
    <div class="logo-box">
      <img id="header-logo" src="/static/logo.png" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 100 100\\'><circle cx=\\'50\\' cy=\\'50\\' r=\\'50\\' fill=\\'%23e11d48\\'/><text x=\\'50\\' y=\\'58\\' text-anchor=\\'middle\\' font-size=\\'36\\' fill=\\'white\\'>❤</text></svg>'">
    </div>
    <div class="header-meta">
      <h1>I LOVE NGỌC HÂN 💖</h1>
      <p>
        Bản quyền thiết kế: <span class="v-badge"><svg viewBox="0 0 24 24" width="13" height="13" fill="#0084ff"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></span> <b>Phạm Anh Khôi</b>
      </p>
    </div>
    <button class="btn-pill light" onclick="location.href='/logout'">Thoát</button>
  </div>
</div>

<div id="toast-stack"></div>

<div class="container">

  <div class="panel active" id="panel-accounts">
    <div class="card">
      <h2>
        <span>Tài Khoản Zalo</span>
        <button class="btn-pill dark" onclick="checkAllAccounts()">Kiểm Tra Tất Cả</button>
      </h2>
      <div class="form-group"><label>Tên gợi nhớ</label><input id="add-label" placeholder="acc_1"></div>
      <div class="form-group"><label>IMEI thiết bị</label><input id="add-imei" placeholder="000000000000000"></div>
      <div class="form-group"><label>Cookie JSON</label><textarea id="add-cookies" placeholder='{"zpw_sek":"...","zpw_ver":"645","zpw_type":"30"}'></textarea></div>
      <button class="btn-pill primary full" onclick="addAccount()">Lưu Tài Khoản</button>
    </div>

    <div class="card">
      <h2><span>Tải Lên Logo Website</span></h2>
      <div style="display:flex; gap:8px; align-items:center;">
        <input type="file" id="logo-file-input" accept="image/*" style="font-size:11px; padding:6px;">
        <button class="btn-pill dark" onclick="uploadLogo()">Cập Nhật Logo</button>
      </div>
    </div>

    <div class="card">
      <h2><span>Danh Sách Tài Khoản</span></h2>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>ID</th><th>Gợi nhớ</th><th>Họ Tên Thật Zalo</th><th>UID</th><th>Trạng thái</th><th>Thao tác</th></tr></thead>
          <tbody id="accounts-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="panel" id="panel-boxes">
    <div class="card">
      <h2><span>Quản Lý Cuộc Trò Chuyện</span></h2>
      <div class="form-group"><label>Chọn tài khoản để nạp cuộc trò chuyện</label><select id="load-acc-select"><option value="">-- Chọn tài khoản --</option></select></div>
      <div style="display:flex; gap:6px; margin-bottom:10px;">
        <button class="btn-pill dark" onclick="loadBoxes()">Nạp Danh Sách</button>
        <button class="btn-pill light" onclick="selectAllBoxes()">Chọn Tất Cả</button>
        <button class="btn-pill danger" onclick="clearAllBoxes()">Bỏ Chọn</button>
      </div>
      <div>
        <div style="font-size:9.5px; font-weight:800; color:var(--txt-2); margin-bottom:4px;">
          ĐÃ CHỌN: <span id="selected-count" style="color:var(--accent);">0</span>
        </div>
        <div class="box-list" id="box-list"><div style="text-align:center; padding:18px; color:var(--txt-2); font-size:11px;">Chưa nạp dữ liệu</div></div>
      </div>
    </div>
  </div>

  <div class="panel" id="panel-files">
    <div class="card">
      <h2><span>Tải Lên Văn Bản</span></h2>
      <div class="form-group"><input type="file" id="file-input" accept=".txt" style="padding:6px;"></div>
      <button class="btn-pill primary full" onclick="uploadFile()">Lưu Tập Tin</button>
    </div>
    <div class="card">
      <h2><span>Tập Tin Đã Lưu</span></h2>
      <div id="files-list"><div style="text-align:center; padding:18px; color:var(--txt-2); font-size:11px;">Chưa có tập tin</div></div>
    </div>
  </div>

  <div class="panel" id="panel-spam">
    <div class="card">
      <h2><span>Thiết Lập Gửi Tin Nâng Cao</span></h2>

      <div class="form-group">
        <label>Chế độ gửi</label>
        <div class="chip-bar" id="mode-selector">
          <div class="chip-item active" data-mode="fast">Siêu Nhanh</div>
          <div class="chip-item" data-mode="treo_ngon">Treo Ngôn (N Dòng / 1 Tin)</div>
          <div class="chip-item" data-mode="treo_nhay">Treo Nhây (Từng Dòng Không Số)</div>
        </div>
        <input type="hidden" id="spam-mode" value="fast">
      </div>

      <div class="form-group">
        <label>Chọn tập tin có sẵn</label>
        <select id="spam-file-select"><option value="">-- Chọn tập tin --</option></select>
      </div>

      <div class="form-group">
        <label>Hoặc dán trực tiếp văn bản</label>
        <textarea id="spam-messages" placeholder="Dán văn bản nhiều dòng vào đây... Nếu chọn Treo Ngôn, toàn bộ văn bản sẽ được gửi trong 1 tin duy nhất. Nếu chọn Treo Nhây, mỗi dòng sẽ được gửi riêng biệt (không đánh số)."></textarea>
      </div>

      <div class="form-group">
        <label>Đổi màu chữ Zalo tự động</label>
        <div class="chip-bar" id="color-mode-bar">
          <div class="chip-item active" data-cmode="random">Đổi màu ngẫu nhiên</div>
          <div class="chip-item" data-cmode="cycle">Đổi màu xoay vòng</div>
          <div class="chip-item" data-cmode="fixed">Cố định một màu</div>
          <div class="chip-item" data-cmode="none">Tắt màu</div>
        </div>
        <input type="hidden" id="color-mode" value="random">
        <div id="fixed-colors-wrap" style="display:none; margin-top:6px;" class="chip-bar"></div>
      </div>

      <div class="form-group">
        <label>Khoảng cách gửi (giây)</label>
        <div class="chip-bar" id="delay-bar">
          <div class="chip-item" data-delay="0.3">0.3s</div>
          <div class="chip-item" data-delay="0.5">0.5s</div>
          <div class="chip-item active" data-delay="1">1s</div>
          <div class="chip-item" data-delay="2">2s</div>
          <div class="chip-item" data-delay="3">3s</div>
        </div>
        <input type="hidden" id="spam-delay" value="1">
      </div>

      <div class="form-group">
        <label>Số biểu tượng cảm xúc cuối câu</label>
        <div class="chip-bar" id="icon-bar">
          <div class="chip-item" data-icon="0">0</div>
          <div class="chip-item" data-icon="2">2</div>
          <div class="chip-item active" data-icon="3">3</div>
          <div class="chip-item" data-icon="5">5</div>
        </div>
        <input type="hidden" id="icon-count" value="3">
      </div>

      <div class="toggle-grid">
        <div class="toggle-item active" id="tg-heading" onclick="tgFlag('heading')">Chữ To Tiêu Đề (#)</div>
        <div class="toggle-item active" id="tg-multi" onclick="tgFlag('multi')">Chạy Tất Cả Acc Song Song</div>
        <div class="toggle-item" id="tg-all" onclick="tgFlag('all')">Nhắc Cả Nhóm (@All)</div>
        <div class="toggle-item active" id="tg-emoji" onclick="tgFlag('emoji')">Biểu Tượng Cảm Xúc</div>
      </div>

      <div class="form-group">
        <label style="display:flex; align-items:center; gap:6px; cursor:pointer; font-size:11px;">
          <input type="checkbox" id="tg-tag" onchange="tgTag()" style="width:auto;">
          Chọn từng thành viên theo họ tên thật
        </label>
        <div id="tag-wrap" style="display:none; margin-top:8px;">
          <div class="form-group"><select id="member-acc-select"><option value="">-- Chọn tài khoản quét --</option></select></div>
          <button class="btn-pill dark" onclick="loadMembers()">Nạp Danh Sách Thành Viên</button>
          <div class="box-list" id="tag-selector" style="margin-top:6px; max-height:220px; display:none;"></div>
          <input type="hidden" id="tag-selected" value="">
        </div>
      </div>
    </div>

    <div style="text-align:center; margin-bottom:14px;">
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

</div>

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
</div>

<script>
var flags = { heading: true, multi: true, all: false, emoji: true };
var selectedBoxes = [];
var selectedTags = [];
var _boxes = [];
var _members = [];
var currentMode = "fast";
var colorMode = "random";
var fixedColor = "red";
var ZALO_PALETTE = [];

var Toast = (function(){
  var stack = null;
  function ensure(){ if(!stack) stack = document.getElementById('toast-stack'); return stack; }
  function show(msg, title, duration){
    duration = duration || 1400;
    var s = ensure();
    if(!s) return;
    s.querySelectorAll('.toast').forEach(el => el.remove());

    var el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = '<div class="t-head">' + (title || 'Thông báo') + '</div>' +
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
    error: (m, t, d) => show(m, t || 'Lỗi', d || 1800),
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
  var inp = document.getElementById('logo-file-input');
  if(!inp.files.length) return Toast.error('Vui lòng chọn hình ảnh logo');
  var fd = new FormData();
  fd.append('logo', inp.files[0]);
  Toast.info('Đang cập nhật logo...');
  var r = await fetch('/api/upload_logo', { method: 'POST', body: fd }).then(x => x.json());
  if(r.ok){
    Toast.success('Cập nhật logo thành công!');
    document.getElementById('header-logo').src = '/static/logo.png?t=' + Date.now();
  } else {
    Toast.error(r.error || 'Lỗi tải ảnh');
  }
}

async function loadAccounts(){
  var accs = await api('/api/accounts');
  if(!Array.isArray(accs)) accs = [];
  var tb = document.getElementById('accounts-tbody');
  tb.innerHTML = accs.map(a => {
    var realName = a.display_name || a.zalo_name || a.username || 'Chưa cập nhật';
    var isLive = (a.status === 'live');
    var badge = isLive ? '<span class="status-badge live">● HOẠT ĐỘNG</span>' : '<span class="status-badge dead">● NGẮT KẾT NỐI</span>';
    return `<tr>
      <td>${a.id}</td>
      <td><b>${a.label}</b></td>
      <td><span style="color:var(--accent); font-weight:800;">${realName}</span></td>
      <td><code>…${String(a.uid||'').slice(-6)}</code></td>
      <td id="status-${a.id}">${badge}</td>
      <td>
        <button class="btn-pill light" onclick="checkAccount(${a.id})" style="padding:4px 8px; font-size:9.5px;">Kiểm tra</button>
        <button class="btn-pill danger" onclick="delAcc(${a.id})" style="padding:4px 8px; font-size:9.5px;">Xóa</button>
      </td>
    </tr>`;
  }).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--txt-2); padding:16px;">Chưa có tài khoản</td></tr>';

  var s1 = document.getElementById('load-acc-select');
  var s2 = document.getElementById('member-acc-select');
  var opts = '<option value="">-- Chọn tài khoản --</option>' + accs.map(a => `<option value="${a.id}">${a.label} (${a.display_name||'Zalo'})</option>`).join('');
  s1.innerHTML = opts; s2.innerHTML = opts;
}

async function checkAccount(aid){
  Toast.info('Đang kiểm tra kết nối...');
  var r = await api(`/api/accounts/${aid}/check`, { method: 'POST' });
  var el = document.getElementById(`status-${aid}`);
  if(r.ok){
    if(el) el.innerHTML = '<span class="status-badge live">● HOẠT ĐỘNG</span>';
    Toast.success('Tài khoản đang hoạt động tốt!');
  } else {
    if(el) el.innerHTML = '<span class="status-badge dead">● NGẮT KẾT NỐI</span>';
    Toast.error('Phiên đăng nhập đã hết hạn');
  }
}

async function checkAllAccounts(){
  Toast.info('Đang kiểm tra toàn bộ...');
  var r = await api('/api/accounts/check_all', { method: 'POST' });
  Toast.success(`Hoàn tất: ${r.live}/${r.total} tài khoản hoạt động`);
  loadAccounts();
}

async function addAccount(){
  var label = document.getElementById('add-label').value.trim();
  var imei = document.getElementById('add-imei').value.trim();
  var cookies = document.getElementById('add-cookies').value.trim();
  if(!imei || !cookies) return Toast.error('Vui lòng điền đủ IMEI và Cookie');
  Toast.info('Đang xác thực thông tin...');
  var r = await api('/api/accounts/add', { method: 'POST', body: JSON.stringify({ label, imei, cookies }) });
  if(r.error) return Toast.error(r.error);
  Toast.success('Thêm tài khoản thành công!');
  document.getElementById('add-label').value = '';
  document.getElementById('add-imei').value = '';
  document.getElementById('add-cookies').value = '';
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
  Toast.info('Đang nạp danh sách cuộc trò chuyện...');
  var r = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  var all = (r.groups||[]).concat(r.friends||[]);
  var bl = document.getElementById('box-list');
  bl.innerHTML = all.map((b,i) => `
    <div class="box-item" onclick="tgBox(this, ${i})">
      <div class="check-mark">✓</div>
      <div><div class="b-title">${b.name}</div><div class="b-sub">${b.id} | ${b.type}</div></div>
    </div>
  `).join('') || '<div style="text-align:center; padding:14px;">Không tìm thấy cuộc trò chuyện</div>';
  _boxes = all; selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
  Toast.success('Đã nạp ' + all.length + ' cuộc trò chuyện');
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
  document.querySelectorAll('.box-item').forEach(el => el.classList.add('selected'));
  selectedBoxes = _boxes.slice();
  document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function clearAllBoxes(){
  document.querySelectorAll('.box-item').forEach(el => el.classList.remove('selected'));
  selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
}

async function loadMembers(){
  var aid = document.getElementById('member-acc-select').value;
  if(!aid) return Toast.error('Vui lòng chọn tài khoản');
  var box = selectedBoxes.find(b => b.type === 'group');
  if(!box) return Toast.error('Cần chọn ít nhất 1 nhóm ở mục Hội Thoại');
  Toast.info('Đang nạp danh sách họ tên thành viên...');
  var r = await api('/api/accounts/' + aid + '/members/' + box.id, { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  var mem = r.members || [];
  var sel = document.getElementById('tag-selector');
  sel.style.display = 'block';
  sel.innerHTML = mem.map((m, i) => `
    <div class="box-item" onclick="tgMember(this, ${i})">
      <div class="check-mark">✓</div>
      <div><div class="b-title">${m.name}</div><div class="b-sub">ID: ${m.id}</div></div>
    </div>
  `).join('') || '<div style="padding:14px; text-align:center;">Không có thành viên</div>';
  _members = mem; selectedTags = [];
  Toast.success('Đã nạp ' + mem.length + ' thành viên đầy đủ họ tên');
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

async function uploadFile(){
  var inp = document.getElementById('file-input');
  if(!inp.files.length) return Toast.error('Vui lòng chọn tập tin');
  var fd = new FormData();
  fd.append('file', inp.files[0]);
  Toast.info('Đang tải lên tập tin...');
  var r = await fetch('/api/files/upload', { method: 'POST', body: fd }).then(x => x.json());
  if(r.error) return Toast.error(r.error);
  Toast.success('Đã lưu ' + r.lines + ' khối văn bản');
  inp.value = ''; loadFiles();
}

async function loadFiles(){
  var files = await api('/api/files');
  if(!Array.isArray(files)) files = [];
  var list = document.getElementById('files-list');
  list.innerHTML = files.map(f => `
    <div class="box-item">
      <div><div class="b-title">📄 ${f.filename}</div><div class="b-sub">${f.lines} khối</div></div>
    </div>
  `).join('') || '<div style="text-align:center; padding:14px; color:var(--txt-2);">Chưa có tập tin</div>';
  var s = document.getElementById('spam-file-select');
  s.innerHTML = '<option value="">-- Chọn tập tin --</option>' + files.map(f => `<option value="${f.id}">${f.filename} (${f.lines} khối)</option>`).join('');
}

async function startSpam(){
  if(!selectedBoxes.length) return Toast.error('Chưa chọn cuộc trò chuyện nhận tin');
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
      blocks = direct.split('\n').map(m => m.trim()).filter(Boolean);
    } else {
      blocks = direct.includes(';') ? direct.split(';').map(m => m.trim()).filter(Boolean) : [direct];
    }
  }

  if(!blocks.length) return Toast.error('Vui lòng nhập hoặc chọn văn bản cần gửi');
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
    mode: currentMode,
    color_mode: colorMode,
    fixed_color: fixedColor
  };

  var res = await api('/api/tasks/start', { method: 'POST', body: JSON.stringify(payload) });
  if(res.error) return Toast.error(res.error);
  Toast.success('Đã khởi chạy tiến trình thành công!');
  loadTasks();
}

async function stopAll(){
  await api('/api/tasks/stop_all', { method: 'POST' });
  Toast.info('Đã dừng toàn bộ tiến trình');
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
      <td>${running ? '<span class="status-badge live">Đang chạy</span>' : '<span class="status-badge dead">Đã dừng</span>'}</td>
      <td>${running ? `<button class="btn-pill danger" onclick="stopTask('${t.id}')" style="padding:2px 8px;">Dừng</button>` : ''}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="4" style="text-align:center; padding:12px; color:var(--txt-2);">Không có tiến trình</td></tr>';
}

async function stopTask(tid){
  await api('/api/tasks/' + tid + '/stop', { method: 'POST' });
  Toast.info('Đã dừng tiến trình ' + tid);
  loadTasks();
}

async function loadColors(){
  var cols = await api('/api/colors');
  if(Array.isArray(cols)){
    ZALO_PALETTE = cols;
    var wrap = document.getElementById('fixed-colors-wrap');
    wrap.innerHTML = cols.map(c => `<div class="chip-item" style="border-color:${c.hex}; color:${c.hex};" onclick="setFixedColor('${c.id}')">${c.name}</div>`).join('');
  }
}

function setFixedColor(cid){
  fixedColor = cid;
  Toast.info('Đã chọn màu: ' + cid);
}

function refreshAll(){ loadAccounts(); loadFiles(); loadTasks(); }

var canvas = document.getElementById('particles-canvas');
var ctx = canvas.getContext('2d');
var width = window.innerWidth;
var height = window.innerHeight;
canvas.width = width; canvas.height = height;

var particles = Array.from({ length: 42 }, () => ({
  x: Math.random() * width,
  y: Math.random() * height,
  r: Math.random() * 2.8 + 1,
  speedY: Math.random() * 0.9 + 0.4,
  speedX: (Math.random() - 0.5) * 0.5
}));

function animateParticles(){
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = 'rgba(225, 29, 72, 0.25)';
  particles.forEach(p => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    ctx.fill();
    p.y += p.speedY;
    p.x += p.speedX;
    if(p.y > height){ p.y = 0; p.x = Math.random() * width; }
    if(p.x > width){ p.x = 0; }
    if(p.x < 0){ p.x = width; }
  });
  requestAnimationFrame(animateParticles);
}
animateParticles();

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


@app.route("/api/accounts/add", methods=["POST"])
@login_required
def api_accounts_add():
    d = request.json
    label = d.get("label", "").strip() or "acc_" + str(int(time.time()))
    imei = d.get("imei", "").strip()
    ck = d.get("cookies", "").strip()
    if not imei or not ck:
        return jsonify({"error": "Vui lòng nhập đủ IMEI và Cookie"}), 400
    try:
        ck_obj = json.loads(ck)
        z = Zalo(imei, ck_obj)
        st = "live"
    except Exception as e:
        return jsonify({"error": "Không thể đăng nhập: " + str(e)}), 400

    conn = db()
    conn.execute("""
        INSERT INTO accounts (label, imei, cookies, added_at,
                             uid, display_name, zalo_name, username, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (label, imei, json.dumps(ck_obj), time.time(),
          z.uid, z.display_name or "", z.zalo_name or "", z.username or "", st))
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
    try:
        z = Zalo(row["imei"], json.loads(row["cookies"]))
        conn.execute("UPDATE accounts SET status = 'live' WHERE id = ?", (aid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "status": "live", "name": z.display_name})
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
        try:
            z = Zalo(r["imei"], json.loads(r["cookies"]))
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
    try:
        z = Zalo(row["imei"], json.loads(row["cookies"]))
        return jsonify({"ok": True, "groups": z.groups(), "friends": z.friends()})
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


def parse_blocks(filepath, max_blocks=5000):
    blocks = []
    current = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        for line in content.split("\n"):
            if len(blocks) >= max_blocks: break
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
    return blocks


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
    safe = str(int(time.time())) + "_" + f.filename
    fp = os.path.join(UPLOAD_DIR, safe)
    f.save(fp)
    blocks = parse_blocks(fp)
    conn = db()
    conn.execute("INSERT INTO files (filename, filepath, lines, size, uploaded_at) VALUES (?, ?, ?, ?, ?)",
                 (f.filename, fp, len(blocks), os.path.getsize(fp), time.time()))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "filename": f.filename, "lines": len(blocks)})


@app.route("/api/files/<int:fid>/preview", methods=["GET"])
@login_required
def api_files_preview(fid):
    conn = db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    conn.close()
    if not row: return jsonify({"error": "Không tìm thấy tập tin"}), 404
    return jsonify({"filename": row["filename"], "all": parse_blocks(row["filepath"])})


@app.route("/api/tasks", methods=["GET"])
@login_required
def api_tasks():
    conn = db()
    rows = conn.execute("SELECT * FROM tasks ORDER BY started_at DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


def pick_color_item(color_mode, fixed_color, index):
    if color_mode == "none":
        return None
    if color_mode == "fixed":
        for c in ZALO_PALETTE:
            if c["id"] == fixed_color:
                return c
        return ZALO_PALETTE[0]
    if color_mode == "cycle":
        return ZALO_PALETTE[index % len(ZALO_PALETTE)]
    return random.choice(ZALO_PALETTE)


def single_acc_worker(acc_dict, targets, blocks, delay, use_emoji, icon_count,
                      tag_users, tag_all, is_heading, mode, color_mode, fixed_color,
                      stop_ev, counter, lock):
    imei = acc_dict["imei"]
    cookies = json.loads(acc_dict["cookies"])
    try:
        z = Zalo(imei, cookies)
    except Exception:
        return

    b_idx, t_idx = 0, 0
    c_idx = random.randint(0, len(ZALO_PALETTE) - 1)

    while not stop_ev.is_set():
        target = targets[t_idx % len(targets)]
        t_idx += 1
        is_group = (target.get("type") == "group")
        target_id = target.get("id")

        raw = blocks[b_idx % len(blocks)]
        b_idx += 1

        color_item = pick_color_item(color_mode, fixed_color, c_idx)
        c_idx += 1

        try:
            if mode == "treo_ngon":
                text = raw.replace("\r\n", "\n").replace("\r", "\n")
                if use_emoji and icon_count > 0:
                    text = text + " " + " ".join([get_icon_hard() for _ in range(icon_count)])
                z.send(text, target_id, color_item=color_item, is_group=is_group,
                       mentions=tag_users, tag_all=tag_all, is_heading=is_heading)
                with lock: counter["sent"] += 1

            elif mode == "treo_nhay":
                lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
                for ln in lines:
                    if stop_ev.is_set(): break
                    msg_line = ln
                    if use_emoji and icon_count > 0:
                        msg_line += " " + " ".join([get_icon_hard() for _ in range(icon_count)])
                    sub_color = pick_color_item(color_mode, fixed_color, c_idx)
                    c_idx += 1
                    z.send(msg_line, target_id, color_item=sub_color, is_group=is_group,
                           mentions=tag_users, tag_all=tag_all, is_heading=is_heading)
                    with lock: counter["sent"] += 1
                    time.sleep(0.2)
            else:
                text = raw
                if use_emoji and icon_count > 0:
                    text = text + " " + " ".join([get_icon_hard() for _ in range(icon_count)])
                z.send(text, target_id, color_item=color_item, is_group=is_group,
                       mentions=tag_users, tag_all=tag_all, is_heading=is_heading)
                with lock: counter["sent"] += 1

        except Exception:
            pass

        time.sleep(max(0.3, delay))


def task_supervisor(tid, targets, blocks, delay, use_emoji, icon_count,
                    tag_users, tag_all, is_heading, multi_acc, mode, color_mode, fixed_color, stop_ev):
    conn = db()
    accs = conn.execute("SELECT * FROM accounts WHERE status = 'live' OR status = 'unknown'").fetchall()
    conn.close()
    if not accs:
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
                      stop_ev, counter, lock),
                daemon=True
            )
            threads.append(t)
            t.start()
    else:
        t = threading.Thread(
            target=single_acc_worker,
            args=(dict(accs[0]), targets, blocks, delay, use_emoji, icon_count,
                  tag_users, tag_all, is_heading, mode, color_mode, fixed_color,
                  stop_ev, counter, lock),
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
    mode = d.get("mode", "fast")
    color_mode = d.get("color_mode", "random")
    fixed_color = d.get("fixed_color", "red")

    if not targets or not blocks:
        return jsonify({"error": "Vui lòng chọn cuộc trò chuyện và nội dung"}), 400

    tid = new_tid("task")
    stop_ev = threading.Event()

    th = threading.Thread(
        target=task_supervisor,
        args=(tid, targets, blocks, delay, use_emoji, icon_count,
              tag_users, tag_all, is_heading, multi_acc, mode, color_mode, fixed_color, stop_ev),
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
