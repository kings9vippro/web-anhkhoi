# ============================================================
# BẢN QUYỀN THIẾT KẾ VÀ ĐIỀU HÀNH: PHẠM ANH KHÔI
# HỆ THỐNG: ALB FORGE — SAKURA 3D LUXURY EDITION
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
    session, redirect, url_for
)
from Crypto.Cipher import AES
import requests

APP_PASSWORD = os.environ.get("APP_PASSWORD", "anhkhoidz")
DATA_DIR = os.environ.get("DATA_DIR", "/tmp/alb_web")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "alb.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "pham-anh-khoi-sakura-vip")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # Hỗ trợ file siêu lớn 500MB

# ============================================================
# KHIÊN BẢO VỆ CHỐNG DDOS VÀ BOT TỰ ĐỘNG
# ============================================================
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
            return jsonify({"error": "Yêu cầu xác thực danh tính"}), 403
        return redirect(url_for("verify_gate"))


# ============================================================
# CƠ SỞ DỮ LIỆU
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT, imei TEXT, cookies TEXT,
            ok_count INTEGER DEFAULT 0, fail_count INTEGER DEFAULT 0,
            risk REAL DEFAULT 0.0, enabled INTEGER DEFAULT 1,
            added_at REAL, last_used REAL DEFAULT 0, total_sent INTEGER DEFAULT 0,
            uid TEXT, display_name TEXT, zalo_name TEXT, username TEXT,
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

# Bảng màu sắc nét hiển thị chuẩn Zalo
ZALO_PALETTE = [
    {"id": "red",    "name": "Đỏ Rực",       "hex": "e8453c"},
    {"id": "yellow", "name": "Vàng Chói",     "hex": "f5c500"},
    {"id": "green",  "name": "Xanh Lá",      "hex": "00b14f"},
    {"id": "orange", "name": "Cam Lửa",      "hex": "ff8c00"},
    {"id": "ocean",  "name": "Xanh Biển",    "hex": "0091ff"},
    {"id": "blue",   "name": "Xanh Dương",   "hex": "0068ff"},
    {"id": "purple", "name": "Tím Pha Lê",   "hex": "a05eff"},
    {"id": "pink",   "name": "Hồng Đào",     "hex": "ff47a8"},
]

ZALO_ICON_HARD = [
    ";-A", ":-bd", "/-punch", "/-shit", "/-weak", ":-DIG", "8-|", ";-!", ":-t", "=d>", ":q",
    ";f", ":d", "=))", "b-)", ":-R", ":-L", ":-F", "x-)", ":v", ":3", ":>", ":$", ";)p", ";;)",
    ":p", ":-p", ":-d", "8-)", ":-*", ":-h", ":-?", ":-s", ":-x", ":x", ":-o", ":o", ":-|", ":|",
    "/-no", "/-bad", "/-li", "/-strong", "/-fade", "/-bome", "/-bd", "/-break", ">-)", "p-(", ":--|"
]
ZALO_ICON_UNICODE = [ "😏", "🤡", "💩", "🖕", "👊", "💀", "🤣", "🤪", "🤦", "💢", "☠️", "🗿", "😆", "🙄", "😒", "😑", "😹", "😈", "🔥", "😤", "🤮", "🤢", "🐒", "✌️", "☝️", "😁" ]

def get_icon_hard():
    if random.random() < 0.65:
        return random.choice(ZALO_ICON_HARD)
    return random.choice(ZALO_ICON_UNICODE)


# ============================================================
# CỐT LÕI XỬ LÝ ZALO CAO CẤP
# ============================================================
class Zalo:
    def __init__(self, imei, cookies):
        self.imei = str(imei).strip()
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://chat.zalo.me",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        })
        self.s.cookies.update(cookies)
        self._login()

    def _login(self):
        r = self.s.get(
            "https://wpa.chat.zalo.me/api/login/getLoginInfo",
            params={"imei": self.imei, "type": 30, "client_version": 645, "ts": int(time.time() * 1000)},
            timeout=15,
        )
        d = r.json()
        ud = d.get("data")
        if not isinstance(ud, dict): raise Exception("Phiên đăng nhập hết hạn")
        self.uid = ud.get("send2me_id")
        self.secret_key = ud.get("zpw_enk")
        self.display_name = ud.get("displayName") or ud.get("zaloName")
        if not self.secret_key: raise Exception("Lỗi lấy khóa mã hóa")

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
        r = self.s.get("https://tt-group-wpa.chat.zalo.me/api/group/getlg/v4", params={"zpw_ver": 645, "zpw_type": 30}, timeout=15)
        grid = json.loads(self._dec(r.json()["data"])).get("data", {}).get("gridVerMap", {})
        out = []
        for gid in grid:
            try:
                enc = self._enc({"gridVerMap": json.dumps({str(gid): 0})})
                r_info = self.s.post("https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2", params={"zpw_ver": 645, "zpw_type": 30}, data={"params": enc}, timeout=15)
                info = json.loads(self._dec(r_info.json()["data"])).get("data", {}).get("gridInfoMap", {}).get(str(gid), {})
                out.append({"id": str(gid), "name": info.get("name", "Nhóm Zalo"), "type": "group", "members": info.get("totalMember", "?")})
            except Exception: continue
        return out

    def friends(self):
        try:
            enc = self._enc({"offset": 0, "count": 500})
            r = self.s.post("https://profile-wpa.chat.zalo.me/api/social/friend/getfriends", params={"zpw_ver": 645, "zpw_type": 30}, data={"params": enc}, timeout=15)
            users = json.loads(self._dec(r.json()["data"])).get("data", [])
            if isinstance(users, dict): users = users.get("users", [])
            return [{"id": str(u.get("userId")), "name": u.get("displayName") or u.get("zaloName") or f"Bạn_{str(u.get('userId'))[-6:]}", "type": "user"} for u in users]
        except Exception: return []

    def get_members_full(self, gid):
        enc = self._enc({"gridVerMap": json.dumps({str(gid): 0})})
        r = self.s.post("https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2", params={"zpw_ver": 645, "zpw_type": 30}, data={"params": enc}, timeout=20)
        info = json.loads(self._dec(r.json()["data"])).get("data", {}).get("gridInfoMap", {}).get(str(gid), {})
        
        members_dict = {}
        mem_info_list = info.get("memInfoList", [])
        if isinstance(mem_info_list, list):
            for m in mem_info_list:
                uid = str(m.get("userId") or m.get("id") or "")
                name = (m.get("dName") or m.get("displayName") or m.get("zaloName") or "").strip()
                if uid and name: members_dict[uid] = name

        mem_ver_list = info.get("memVerList", [])
        uids = [m.split("_")[0] for m in mem_ver_list if m]
        missing_uids = [u for u in uids if u not in members_dict]

        if missing_uids:
            try:
                enc2 = self._enc({"grid": str(gid), "userIds": missing_uids, "friendId": missing_uids})
                r2 = self.s.post("https://tt-group-wpa.chat.zalo.me/api/group/getuserinfo", params={"zpw_ver": 645, "zpw_type": 30}, data={"params": enc2}, timeout=18)
                profiles = json.loads(self._dec(r2.json()["data"])).get("data", {}).get("profiles", {})
                for uid in missing_uids:
                    p = profiles.get(uid, {})
                    pname = (p.get("displayName") or p.get("zaloName") or p.get("username") or "").strip()
                    if pname: members_dict[uid] = pname
            except Exception: pass

        out = []
        for uid in uids:
            real_name = members_dict.get(uid) or f"Thành viên {uid[-6:]}"
            out.append({"id": str(uid), "name": real_name})
        return out

    def build_payload(self, text, mentions, tag_all, color_mode, fixed_color, is_heading, c_idx):
        final = text.replace("\r\n", "\n").replace("\r", "\n")
        
        # 1. Gắn H1 Zalo (Heading # )
        if is_heading:
            h_lines = [f"# {ln}" if not ln.startswith("#") else ln for ln in final.split("\n") if ln.strip()]
            final = "\n".join(h_lines)

        # 2. Xử lý Tag (All hoặc Tên)
        m_arr = []
        if tag_all:
            tag_token = "@All"
            pos = utf16_len(final) + (1 if final else 0)
            final = (final + " " + tag_token) if final else tag_token
            m_arr.append({"uid": "0", "pos": pos, "len": 4, "type": 1})
        elif mentions:
            for m in mentions:
                name = str(m.get("name", "")).split(" (")[0].strip()
                uid = str(m.get("uid") or m.get("id") or "").strip()
                if not name or not uid: continue
                tag_token = f"@{name}"
                pos = utf16_len(final) + (1 if final else 0)
                final = (final + " " + tag_token) if final else tag_token
                m_arr.append({"uid": uid, "pos": pos, "len": utf16_len(tag_token), "type": 0})

        # 3. Phủ Màu Chính Xác Chữ Zalo
        styles = []
        first_color = "red"
        
        if color_mode != "none":
            if color_mode == "fixed":
                c = next((x for x in ZALO_PALETTE if x["id"] == fixed_color), ZALO_PALETTE[0])
            elif color_mode == "cycle":
                c = ZALO_PALETTE[c_idx % len(ZALO_PALETTE)]
            else:
                c = random.choice(ZALO_PALETTE)
                
            first_color = c["id"]
            u16_len = utf16_len(final)
            styles = [
                {"start": 0, "len": u16_len, "st": f"c_{c['hex']}"}
            ]

        return final, m_arr, styles, first_color

    def send_msg(self, text, thread_id, color_mode="random", fixed_color="red", c_idx=0, is_group=True, mentions=None, tag_all=False, is_heading=True):
        url = "https://tt-group-wpa.chat.zalo.me/api/group/sendmsg" if is_group else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms"
        
        final_msg, m_arr, styles, first_color = self.build_payload(text, mentions, tag_all, color_mode, fixed_color, is_heading, c_idx)
        
        pl = {
            "message": final_msg,
            "clientId": str(int(time.time() * 1000)) + str(random.randint(100, 999)),
            "imei": self.imei,
        }
        if m_arr: pl["mentions"] = json.dumps(m_arr, ensure_ascii=False)
        if styles: 
            pl["msgColor"] = first_color
            pl["styles"] = json.dumps(styles, ensure_ascii=False)
            
        if is_group:
            pl["visibility"] = 0
            pl["grid"] = str(thread_id)
        else:
            pl["toid"] = str(thread_id)

        enc = self._enc(pl)
        return self.s.post(url, params={"zpw_ver": 645, "zpw_type": 30}, data={"params": enc}, timeout=15)


# ============================================================
# XỬ LÝ FILE DUNG LƯỢNG LỚN (Stream Generator)
# ============================================================
def process_large_file(filepath):
    blocks, current = [], []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if len(blocks) >= 15000: break
                ln = line.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
                if ln.strip() == "":
                    if current:
                        blocks.append("\n".join(current))
                        current = []
                else:
                    current.append(ln)
            if current:
                blocks.append("\n".join(current))
    except Exception: pass
    return blocks


# ============================================================
# MULTI-THREAD CONCURRENCY WORKER
# ============================================================
def single_acc_worker(acc_dict, targets, blocks, delay, use_emoji, icon_count,
                      tag_users, tag_all, is_heading, mode, color_mode, fixed_color,
                      stop_ev, counter, lock):
    try: z = Zalo(acc_dict["imei"], json.loads(acc_dict["cookies"]))
    except Exception: return

    b_idx, t_idx = 0, 0
    c_idx = random.randint(0, 100)

    while not stop_ev.is_set():
        target = targets[t_idx % len(targets)]
        t_idx += 1
        is_group = (target.get("type") == "group")
        target_id = target.get("id")
        
        raw = blocks[b_idx % len(blocks)]
        b_idx += 1
        c_idx += 1

        try:
            if mode == "treo_ngon":
                # Gửi nguyên vẹn N dòng trong 1 tin duy nhất
                text = raw
                if use_emoji and icon_count > 0:
                    text += " " + " ".join([get_icon_hard() for _ in range(icon_count)])
                z.send_msg(text, target_id, color_mode, fixed_color, c_idx, is_group, tag_users, tag_all, is_heading)
                with lock: counter["sent"] += 1

            elif mode == "treo_nhay":
                # Tách dòng, KHÔNG đánh số, gửi từng tin
                lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
                for mi, ln in enumerate(lines):
                    if stop_ev.is_set(): break
                    msg_line = ln
                    if use_emoji and icon_count > 0:
                        msg_line += " " + " ".join([get_icon_hard() for _ in range(icon_count)])
                    z.send_msg(msg_line, target_id, color_mode, fixed_color, c_idx + mi, is_group,
                               tag_users if mi == 0 else None, tag_all if mi == 0 else False, is_heading)
                    with lock: counter["sent"] += 1
                    time.sleep(0.35)
            else:
                text = raw
                if use_emoji and icon_count > 0:
                    text += " " + " ".join([get_icon_hard() for _ in range(icon_count)])
                z.send_msg(text, target_id, color_mode, fixed_color, c_idx, is_group, tag_users, tag_all, is_heading)
                with lock: counter["sent"] += 1

        except Exception: pass
        time.sleep(max(0.3, delay))


def task_supervisor(tid, targets, blocks, delay, use_emoji, icon_count,
                    tag_users, tag_all, is_heading, multi_acc, mode, color_mode, fixed_color, stop_ev):
    conn = db()
    accs = conn.execute("SELECT * FROM accounts WHERE enabled = 1").fetchall()
    conn.close()
    if not accs: return

    counter = {"sent": 0}
    lock = threading.Lock()
    threads = []

    active_accs = accs if multi_acc else [accs[0]]
    for a in active_accs:
        t = threading.Thread(target=single_acc_worker, args=(dict(a), targets, blocks, delay, use_emoji, icon_count, tag_users, tag_all, is_heading, mode, color_mode, fixed_color, stop_ev, counter, lock), daemon=True)
        threads.append(t)
        t.start()

    while not stop_ev.is_set(): time.sleep(1)
    for th in threads: th.join(timeout=0.2)

    conn = db()
    conn.execute("UPDATE tasks SET status = 'stopped', stats = ? WHERE id = ?", (json.dumps({"sent": counter["sent"]}), tid))
    conn.commit(); conn.close()
    ACTIVE_TASKS.pop(tid, None)


# ============================================================
# CSS GIAO DIỆN HOA ANH ĐÀO CAO CẤP MENGTO STYLE
# ============================================================
CSS_SAKURA = """
:root {
  --bg-page: #fdfafc;
  --bg-card: rgba(255, 255, 255, 0.85);
  --border-color: rgba(255, 183, 197, 0.4);
  --txt-0: #1a1a24; --txt-1: #334155; --txt-2: #64748b;
  --sakura: #ff69b4; --sakura-deep: #e11d48;
  --grad-sakura: linear-gradient(135deg, #ff758c 0%, #ff7eb3 100%);
  --shadow-soft: 0 16px 40px rgba(255, 117, 140, 0.1);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html { touch-action: manipulation; }
body {
  font-family: 'Inter', system-ui, sans-serif;
  background-color: var(--bg-page); color: var(--txt-1);
  min-height: 100vh; padding-bottom: 120px; overflow-x: hidden;
}
/* HOA ANH ĐÀO VÀ NỀN KHÔNG CHẶN CLICK */
#sakura-canvas { position: fixed; inset: 0; pointer-events: none !important; z-index: 9999; }
.cherry-branch { position: fixed; top: -15px; right: -15px; width: 220px; height: 180px; pointer-events: none !important; z-index: 9998; opacity: 0.95; filter: drop-shadow(0 10px 20px rgba(255,105,180,0.3)); }
.bg-blur { position: fixed; inset: 0; background: url('/static/bg.jpg') cover center no-repeat; opacity: 0.12; filter: blur(6px); pointer-events: none !important; z-index: -1; }

/* HEADER SANG TRỌNG */
.header { background: rgba(255,255,255,0.8); backdrop-filter: blur(30px); padding: 12px 20px; border-bottom: 1px solid var(--border-color); position: sticky; top:0; z-index: 100; box-shadow: 0 4px 20px rgba(255,117,140,0.05); }
.header-inner { max-width: 1000px; margin: 0 auto; display: flex; align-items: center; gap: 14px; }
.logo-box { width: 48px; height: 48px; border-radius: 50%; border: 2.5px solid #fff; box-shadow: 0 6px 20px rgba(255,105,180,0.4); overflow: hidden; background: #fff; flex-shrink: 0; }
.logo-box img { width: 100%; height: 100%; object-fit: cover; }
.header-meta { flex: 1; min-width: 0; }
.header-meta h1 { font-family: 'Orbitron', sans-serif; font-size: 16px; font-weight: 900; color: var(--txt-0); }
.v-badge { display: inline-flex; align-items: center; justify-content: center; color: #0084ff; filter: drop-shadow(0 2px 4px rgba(0,132,255,0.3)); margin-right: 4px; }

/* CONTAINER & CARD 3D GLASSMORPHISM */
.container { max-width: 1000px; margin: 0 auto; padding: 20px; position: relative; z-index: 10; }
.panel { display: none; animation: slideUp .4s var(--ease) both; }
.panel.active { display: block; }
@keyframes slideUp { from { opacity: 0; transform: translateY(15px); } to { opacity: 1; transform: translateY(0); } }

.card { background: var(--bg-card); backdrop-filter: blur(30px); padding: 22px; border-radius: 24px; border: 1px solid rgba(255,255,255,0.6); box-shadow: var(--shadow-soft); margin-bottom: 18px; }
.card h2 { font-size: 13px; font-weight: 900; color: var(--txt-0); margin-bottom: 16px; display: flex; align-items: center; justify-content: space-between; }

/* NÚT BẤM PILL-SHAPED MENGTO */
.btn-pill {
  padding: 10px 18px; border-radius: 99px; border: none; cursor: pointer; font-size: 11.5px; font-weight: 800;
  display: inline-flex; align-items: center; justify-content: center; gap: 8px; transition: all .3s var(--ease);
  position: relative; overflow: hidden;
}
.btn-pill::after {
  content: ''; position: absolute; top: -50%; left: -60%; width: 30%; height: 200%;
  background: linear-gradient(60deg, transparent, rgba(255,255,255,0.5), transparent);
  transform: rotate(25deg); transition: all 0.6s ease;
}
.btn-pill:hover::after { left: 130%; }
.btn-pill:hover { transform: translateY(-3px); filter: brightness(1.08); box-shadow: 0 8px 25px rgba(255,105,180,0.4); }
.btn-pill:active { transform: translateY(0) scale(0.95); }
.btn-pill.primary { background: var(--grad-sakura); color: #fff; box-shadow: 0 6px 20px rgba(255,117,140,0.3); }
.btn-pill.dark { background: #1e293b; color: #fff; }
.btn-pill.light { background: #fff0f3; color: var(--sakura-deep); border: 1px solid var(--border-color); }
.btn-pill.full { width: 100%; padding: 14px; font-size: 12.5px; }

/* FILE UPLOAD DRAG DROP */
.file-drop-area {
  position: relative; width: 100%; padding: 25px; border: 2.5px dashed var(--sakura);
  border-radius: 20px; background: rgba(255,183,197,0.1); text-align: center;
  transition: all 0.3s; cursor: pointer; margin-bottom: 15px;
}
.file-drop-area:hover { background: rgba(255,183,197,0.25); border-color: var(--sakura-deep); transform: translateY(-2px); }
.file-drop-area input { position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%; }
.file-drop-area svg { width: 32px; height: 32px; color: var(--sakura); margin-bottom: 8px; }
.file-drop-area span { display: block; font-size: 12px; font-weight: 800; color: var(--txt-1); }

/* FORMS & INPUTS */
.form-group { margin-bottom: 14px; }
.form-group label { display: block; margin-bottom: 6px; font-size: 10.5px; font-weight: 800; color: var(--txt-2); }
.form-group input:not([type="file"]), .form-group textarea, .form-group select {
  width: 100%; padding: 14px 16px; border: 1.5px solid var(--border-color); border-radius: 16px;
  font-size: 13px; background: #fff; color: var(--txt-0); transition: all .3s;
}
.form-group input:focus, .form-group textarea:focus, .form-group select:focus { outline: none; border-color: var(--sakura); box-shadow: 0 0 0 4px rgba(255,105,180,0.15); }
.form-group textarea { min-height: 100px; font-family: 'JetBrains Mono', monospace; font-size: 12px; }

/* CHIPS */
.chip-bar { display: flex; flex-wrap: wrap; gap: 8px; }
.chip-item { padding: 8px 16px; background: #fff; color: var(--txt-2); border-radius: 99px; font-size: 11px; font-weight: 800; cursor: pointer; border: 1px solid var(--border-color); transition: all .25s; }
.chip-item:hover { border-color: var(--sakura); color: var(--sakura); transform: translateY(-2px); }
.chip-item.active { background: var(--grad-sakura); color: #fff; border-color: transparent; box-shadow: 0 6px 15px rgba(255,117,140,0.3); transform: translateY(-2px); }

/* TOGGLES */
.toggle-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 15px; }
.toggle-item { padding: 12px; border: 1px solid var(--border-color); border-radius: 16px; cursor: pointer; text-align: center; font-weight: 800; font-size: 11px; background: #fff; color: var(--txt-2); transition: all .3s; }
.toggle-item.active { background: var(--grad-sakura); color: #fff; border-color: transparent; box-shadow: 0 6px 18px rgba(255,117,140,0.3); transform: translateY(-2px); }

/* LISTS & TABLES */
.table-wrap { overflow-x: auto; border-radius: 16px; border: 1px solid var(--border-color); background: #fff; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { padding: 12px 14px; text-align: left; font-size: 11.5px; border-bottom: 1px solid #fdf2f4; white-space: nowrap; }
.table th { background: #fdf6f7; font-weight: 900; color: var(--txt-2); font-size: 10px; text-transform: uppercase; }

.box-list { max-height: 300px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 16px; padding: 10px; background: #fff; }
.box-item { padding: 12px; border-radius: 14px; background: #fdfafb; margin-bottom: 8px; cursor: pointer; border: 1px solid var(--border-color); display: flex; align-items: center; gap: 12px; transition: all .2s; }
.box-item:hover { border-color: var(--sakura); background: #fff; transform: translateX(3px); }
.box-item.selected { border-color: var(--sakura); background: #fff0f3; }
.box-item .check-mark { width: 20px; height: 20px; border: 2px solid var(--txt-2); border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 12px; color: transparent; font-weight: 900; }
.box-item.selected .check-mark { background: var(--sakura); border-color: var(--sakura); color: #fff; }

/* BOTTOM DOCK */
.bottom-dock {
  position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); width: calc(100% - 40px); max-width: 500px;
  background: rgba(255,255,255,0.9); backdrop-filter: blur(30px); border: 1px solid rgba(255,183,197,0.8);
  box-shadow: 0 15px 45px rgba(255,117,140,0.15); border-radius: 99px; display: grid; grid-template-columns: repeat(4, 1fr);
  padding: 8px; gap: 6px; z-index: 999;
}
.bottom-dock .dock-btn { padding: 10px 4px; border-radius: 99px; cursor: pointer; font-size: 10px; font-weight: 900; text-align: center; color: var(--txt-2); display: flex; flex-direction: column; align-items: center; gap: 4px; background: transparent; border: none; transition: all .3s; text-transform: uppercase; }
.bottom-dock .dock-btn svg { width: 22px; height: 22px; transition: transform 0.3s; }
.bottom-dock .dock-btn:hover svg { transform: scale(1.15) translateY(-3px); color: var(--sakura); }
.bottom-dock .dock-btn.active { background: var(--grad-sakura); color: #fff; box-shadow: 0 6px 18px rgba(255,105,180,0.35); transform: translateY(-3px); }

/* TOAST */
#toast-stack { position: fixed; top: 16px; right: 16px; z-index: 99999; max-width: 340px; width: calc(100% - 32px); pointer-events: none; }
.toast { pointer-events: auto; padding: 14px 18px; border-radius: 16px; background: rgba(255,255,255,0.98); border: 1px solid var(--border-color); box-shadow: 0 15px 40px rgba(255,117,140,0.2); display: flex; flex-direction: column; gap: 4px; animation: toastIn .3s var(--ease) both; cursor: pointer; }
.toast.swipe-up { animation: toastUp .25s ease-out forwards; }
@keyframes toastIn { from { opacity: 0; transform: translateY(-25px) scale(0.9); } to { opacity: 1; transform: translateY(0) scale(1); } }
@keyframes toastUp { to { opacity: 0; transform: translateY(-40px) scale(0.9); } }
.toast .t-head { font-size: 12px; font-weight: 900; color: var(--txt-0); display:flex; align-items:center; gap:6px; }
.toast .t-body { font-size: 11px; font-weight: 600; color: var(--txt-2); }
"""

# ============================================================
# GIAO DIỆN WEB: CỔNG BẢO MẬT & ĐĂNG NHẬP
# ============================================================
HTML_GATE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Hệ Thống An Toàn</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_SAKURA + """
body { display: flex; align-items: center; justify-content: center; }
.gate-card { background: rgba(255,255,255,0.98); border: 1px solid var(--border-color); border-radius: 28px; padding: 45px 30px; max-width: 420px; width: 100%; text-align: center; box-shadow: 0 30px 60px rgba(255,117,140,0.15); z-index: 10; }
.radar-scanner { width: 100px; height: 100px; margin: 0 auto 24px; border-radius: 50%; position: relative; display: flex; align-items: center; justify-content: center; background: radial-gradient(circle, rgba(255,105,180,0.15) 0%, transparent 70%); border: 2px dashed rgba(255,105,180,0.5); }
.radar-scanner::before { content: ''; position: absolute; inset: 0; border-radius: 50%; border: 3px solid transparent; border-top-color: var(--sakura); animation: spin 1.2s linear infinite; }
@keyframes spin { 100% { transform: rotate(360deg); } }
.radar-icon { font-size: 38px; animation: pulse 1.5s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.15); } }
.progress-line { height: 6px; width: 100%; background: #fdf2f4; border-radius: 99px; overflow: hidden; margin: 24px 0; display: none; }
.progress-fill { height: 100%; width: 0%; background: var(--grad-sakura); border-radius: 99px; transition: width 0.4s ease; }
</style>
</head>
<body>
<div class="bg-blur"></div>
<canvas id="sakura-canvas"></canvas>
<div class="gate-card">
  <div class="radar-scanner"><div class="radar-icon">🛡️</div></div>
  <h1 style="font-family:'Orbitron',sans-serif; font-size:18px; margin-bottom:10px;">BẢO MẬT HỆ THỐNG</h1>
  <p id="scan-status" style="font-size:12px; color:var(--txt-2); font-weight:600;">Hệ thống phát hiện luồng truy cập mới. Vui lòng xác thực danh tính để đảm bảo an toàn.</p>
  <div class="progress-line" id="p-box"><div class="progress-fill" id="p-bar"></div></div>
  <button class="btn-pill primary full" id="start-btn" onclick="startVerification()" style="margin-top:20px; font-size:14px; padding:16px;">BẮT ĐẦU XÁC THỰC</button>
  <div style="margin-top:20px; font-size:10px; font-weight:800; color:var(--txt-2);">Bản quyền thiết kế: <span class="v-badge"><svg viewBox="0 0 24 24" width="14" height="14" fill="#0084ff"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></span> Phạm Anh Khôi</div>
</div>
<script>
var pBox = document.getElementById('p-box');
var pBar = document.getElementById('p-bar');
var statusTxt = document.getElementById('scan-status');
var startBtn = document.getElementById('start-btn');
var steps = [
  { p: 25, txt: 'Đang kiểm tra tần suất kết nối...' },
  { p: 60, txt: 'Đang phân tích chứng chỉ mã hóa...' },
  { p: 85, txt: 'Xác thực hoàn tất, đang cấp quyền...' },
  { p: 100, txt: 'Chuyển hướng thành công!' }
];
var idx = 0;
function startVerification(){
  startBtn.style.display = 'none'; pBox.style.display = 'block'; runStep();
}
function runStep(){
  if(idx < steps.length){
    pBar.style.width = steps[idx].p + '%';
    statusTxt.textContent = steps[idx].txt;
    idx++; setTimeout(runStep, 500);
  } else { finishScan(); }
}
async function finishScan(){
  var r = await fetch('/api/verify_human', { method: 'POST' }).then(x => x.json());
  if(r.ok) window.location.href = '/login';
}
var sC = document.getElementById('sakura-canvas'), ctx = sC.getContext('2d'), w = window.innerWidth, h = window.innerHeight;
sC.width = w; sC.height = h;
var pts = Array.from({length: 40}, () => ({x: Math.random()*w, y: Math.random()*h, s: Math.random()*7+5, sy: Math.random()*1.5+0.5, sx: Math.random()*2-1, a: Math.random()*360, av: (Math.random()-0.5)*2}));
function draw(){
  ctx.clearRect(0,0,w,h);
  pts.forEach(p => {
    ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a * Math.PI/180); ctx.fillStyle='rgba(255,183,197,0.7)';
    ctx.beginPath(); ctx.moveTo(0,0); ctx.bezierCurveTo(p.s/2, -p.s/2, p.s, 0, 0, p.s); ctx.bezierCurveTo(-p.s, 0, -p.s/2, -p.s/2, 0, 0); ctx.fill(); ctx.restore();
    p.y += p.sy; p.x += p.sx; p.a += p.av;
    if(p.y > h+20){ p.y = -20; p.x = Math.random()*w; }
  });
  requestAnimationFrame(draw);
}
draw();
</script>
</body>
</html>
"""

HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Đăng Nhập Quản Trị</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_SAKURA + """
body { display: flex; align-items: center; justify-content: center; }
.login-card { background: rgba(255,255,255,0.98); border: 1px solid var(--border-color); border-radius: 28px; padding: 45px 30px; max-width: 420px; width: 100%; text-align: center; box-shadow: 0 30px 60px rgba(255,117,140,0.15); z-index: 10; }
.login-logo { width: 90px; height: 90px; border-radius: 50%; overflow: hidden; margin: 0 auto 20px; border: 3px solid var(--sakura); box-shadow: 0 10px 25px rgba(255,105,180,0.3); }
.login-logo img { width: 100%; height: 100%; object-fit: cover; }
.err-msg { background: #fee2e2; color: #b91c1c; padding: 12px; border-radius: 14px; font-size: 12px; font-weight: 800; margin-bottom: 20px; text-align: left; }
</style>
</head>
<body>
<div class="bg-blur"></div>
<canvas id="sakura-canvas"></canvas>
<div class="login-card">
  <div class="login-logo"><img src="/static/logo.png" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 100 100\\'><circle cx=\\'50\\' cy=\\'50\\' r=\\'50\\' fill=\\'%23ff69b4\\'/><text x=\\'50\\' y=\\'58\\' text-anchor=\\'middle\\' font-size=\\'36\\' fill=\\'white\\'>❤</text></svg>'"></div>
  <h1 style="font-family:'Orbitron',sans-serif; font-size:20px; margin-bottom:8px; color:var(--txt-0);">I LOVE NGỌC HÂN</h1>
  <p style="font-size:11px; color:var(--txt-2); font-weight:800; margin-bottom:24px; display:flex; align-items:center; justify-content:center; gap:5px;">
    Bản quyền thiết kế: <span class="v-badge"><svg viewBox="0 0 24 24" width="15" height="15" fill="#0084ff"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></span> Phạm Anh Khôi
  </p>
  {% if error %}<div class="err-msg">⚠️ {{ error }}</div>{% endif %}
  <form method="POST">
    <div class="form-group" style="text-align:left;">
      <input type="password" name="password" placeholder="Nhập mật mã truy cập..." required autofocus>
    </div>
    <button type="submit" class="btn-pill primary full" style="font-size:14px; padding:16px; margin-top:10px;">💖 Truy Cập Hệ Thống</button>
  </form>
</div>
<script>
var sC = document.getElementById('sakura-canvas'), ctx = sC.getContext('2d'), w = window.innerWidth, h = window.innerHeight;
sC.width = w; sC.height = h;
var pts = Array.from({length: 40}, () => ({x: Math.random()*w, y: Math.random()*h, s: Math.random()*7+5, sy: Math.random()*1.5+0.5, sx: Math.random()*2-1, a: Math.random()*360, av: (Math.random()-0.5)*2}));
function draw(){
  ctx.clearRect(0,0,w,h);
  pts.forEach(p => {
    ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a * Math.PI/180); ctx.fillStyle='rgba(255,183,197,0.7)';
    ctx.beginPath(); ctx.moveTo(0,0); ctx.bezierCurveTo(p.s/2, -p.s/2, p.s, 0, 0, p.s); ctx.bezierCurveTo(-p.s, 0, -p.s/2, -p.s/2, 0, 0); ctx.fill(); ctx.restore();
    p.y += p.sy; p.x += p.sx; p.a += p.av;
    if(p.y > h+20){ p.y = -20; p.x = Math.random()*w; }
  });
  requestAnimationFrame(draw);
}
draw();
</script>
</body>
</html>
"""

HTML_INDEX = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Hệ Thống — I Love Ngọc Hân</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_SAKURA + """
</style>
</head>
<body>
<div class="bg-blur"></div>
<canvas id="sakura-canvas"></canvas>
<svg class="cherry-branch" viewBox="0 0 200 160" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M200 10 C160 20 130 50 100 55 C70 60 40 40 10 45" stroke="#8b4513" stroke-width="4.5" stroke-linecap="round"/>
  <path d="M130 50 C110 75 90 85 60 95" stroke="#8b4513" stroke-width="3" stroke-linecap="round"/>
  <circle cx="100" cy="55" r="8" fill="#ffb7c5"/><circle cx="100" cy="55" r="4" fill="#ff1493"/>
  <circle cx="130" cy="48" r="9" fill="#ffb7c5"/><circle cx="130" cy="48" r="4.5" fill="#ff1493"/>
  <circle cx="65" cy="90" r="8.5" fill="#ffb7c5"/><circle cx="65" cy="90" r="4" fill="#ff1493"/>
  <circle cx="160" cy="20" r="9" fill="#ffc0cb"/><circle cx="160" cy="20" r="4.5" fill="#ff1493"/>
</svg>

<div class="header">
  <div class="header-inner">
    <div class="logo-box">
      <img id="header-logo" src="/static/logo.png" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 100 100\\'><circle cx=\\'50\\' cy=\\'50\\' r=\\'50\\' fill=\\'%23ff69b4\\'/><text x=\\'50\\' y=\\'58\\' text-anchor=\\'middle\\' font-size=\\'36\\' fill=\\'white\\'>❤</text></svg>'">
    </div>
    <div class="header-meta">
      <h1>I LOVE NGỌC HÂN 🌸</h1>
      <p>
        Bản quyền thiết kế: <span class="v-badge"><svg viewBox="0 0 24 24" width="14" height="14" fill="#0084ff"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></span> <b style="font-size:11px; color:#1a1a24;">Phạm Anh Khôi</b>
      </p>
    </div>
    <button class="btn-pill light" onclick="location.href='/logout'">Đăng xuất</button>
  </div>
</div>

<div id="toast-stack"></div>

<div class="container">

  <!-- TAB 1: ACCOUNTS -->
  <div class="panel active" id="panel-accounts">
    <div class="card">
      <h2><span>Tài Khoản Zalo</span></h2>
      <div class="form-group"><label>Tên gợi nhớ</label><input id="add-label" placeholder="Ví dụ: acc_1"></div>
      <div class="form-group"><label>IMEI thiết bị</label><input id="add-imei" placeholder="000000000000000"></div>
      <div class="form-group"><label>Cookie JSON</label><textarea id="add-cookies" placeholder='{"zpw_sek":"...","zpw_ver":"645","zpw_type":"30"}'></textarea></div>
      <button class="btn-pill primary full" onclick="addAccount()">Lưu Tài Khoản Này</button>
    </div>

    <div class="card">
      <h2><span>Tùy Biến Hình Ảnh Website</span></h2>
      <div class="file-drop-area" onclick="document.getElementById('logo-file-input').click()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        <span id="logo-upload-txt">Nhấn để chọn Ảnh Logo mới</span>
        <input type="file" id="logo-file-input" accept="image/*" onchange="uploadLogo()">
      </div>
    </div>

    <div class="card">
      <h2><span>Danh Sách Đã Lưu</span></h2>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>ID</th><th>Gợi nhớ</th><th>Họ Tên Thật Zalo</th><th>UID</th><th>Trạng thái</th><th>Thao tác</th></tr></thead>
          <tbody id="accounts-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 2: BOXES -->
  <div class="panel" id="panel-boxes">
    <div class="card">
      <h2><span>Quản Lý Hội Thoại Nhận Tin</span></h2>
      <div class="form-group"><label>Chọn tài khoản để nạp hội thoại</label><select id="load-acc-select"><option value="">-- Chọn tài khoản --</option></select></div>
      <div style="display:flex; gap:8px; margin-bottom:14px;">
        <button class="btn-pill dark" onclick="loadBoxes()">Nạp Danh Sách Hội Thoại</button>
        <button class="btn-pill light" onclick="selectAllBoxes()">Chọn Tất Cả</button>
        <button class="btn-pill light" onclick="clearAllBoxes()">Bỏ Chọn</button>
      </div>
      <div>
        <div style="font-size:11px; font-weight:900; color:var(--txt-2); margin-bottom:8px;">ĐÃ CHỌN: <span id="selected-count" style="color:var(--sakura-deep); font-size:13px;">0</span></div>
        <div class="box-list" id="box-list"><div style="text-align:center; padding:20px; color:var(--txt-2); font-size:12px;">Chưa nạp dữ liệu</div></div>
      </div>
    </div>
  </div>

  <!-- TAB 3: FILES -->
  <div class="panel" id="panel-files">
    <div class="card">
      <h2><span>Tải Lên Văn Bản (Hỗ trợ file lớn)</span></h2>
      <div class="file-drop-area" onclick="document.getElementById('file-input').click()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>
        <span id="file-upload-txt">Nhấn để chọn tệp Văn bản (.txt)</span>
        <input type="file" id="file-input" accept=".txt" onchange="uploadFile()">
      </div>
    </div>
    <div class="card">
      <h2><span>Tập Tin Đã Lưu</span></h2>
      <div id="files-list"><div style="text-align:center; padding:20px; color:var(--txt-2); font-size:12px;">Chưa có tập tin</div></div>
    </div>
  </div>

  <!-- TAB 4: SPAM ENGINE -->
  <div class="panel" id="panel-spam">
    <div class="card">
      <h2><span>Trung Tâm Gửi Tin Nâng Cao</span></h2>

      <div class="form-group">
        <label>Chế độ gửi</label>
        <div class="chip-bar" id="mode-selector">
          <div class="chip-item active" data-mode="fast">Siêu Nhanh</div>
          <div class="chip-item" data-mode="treo_ngon">Treo Ngôn (N Dòng / 1 Tin Duy Nhất)</div>
          <div class="chip-item" data-mode="treo_nhay">Treo Nhây (Từng Dòng Không Số)</div>
        </div>
        <input type="hidden" id="spam-mode" value="fast">
      </div>

      <div class="form-group">
        <label>Chọn tập tin văn bản</label>
        <select id="spam-file-select"><option value="">-- Chọn tập tin --</option></select>
      </div>

      <div class="form-group">
        <label>Hoặc dán trực tiếp văn bản vào đây</label>
        <textarea id="spam-messages" placeholder="Nếu chọn Treo Ngôn, toàn bộ văn bản có khoảng cách dòng sẽ được gửi trọn vẹn trong 1 tin duy nhất."></textarea>
      </div>

      <div class="form-group">
        <label>Đổi màu chữ Zalo rực rỡ</label>
        <div class="chip-bar" id="color-mode-bar">
          <div class="chip-item active" data-cmode="rainbow">Trộn Màu Từng Dòng</div>
          <div class="chip-item" data-cmode="random">Ngẫu Nhiên</div>
          <div class="chip-item" data-cmode="cycle">Xoay Vòng Đều</div>
          <div class="chip-item" data-cmode="fixed">Cố Định Một Màu</div>
          <div class="chip-item" data-cmode="none">Tắt Đổi Màu</div>
        </div>
        <input type="hidden" id="color-mode" value="rainbow">
        <div id="fixed-colors-wrap" style="display:none; margin-top:8px;" class="chip-bar"></div>
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
        <label>Số Icon sát thương tâm lý cuối câu</label>
        <div class="chip-bar" id="icon-bar">
          <div class="chip-item" data-icon="0">0</div>
          <div class="chip-item" data-icon="2">2</div>
          <div class="chip-item active" data-icon="3">3</div>
          <div class="chip-item" data-icon="5">5</div>
        </div>
        <input type="hidden" id="icon-count" value="3">
      </div>

      <div class="toggle-grid">
        <div class="toggle-item active" id="tg-heading" onclick="tgFlag('heading')">Chữ To Tiêu Đề Zalo (#)</div>
        <div class="toggle-item active" id="tg-multi" onclick="tgFlag('multi')">Chạy Đa Luồng Tất Cả Acc</div>
        <div class="toggle-item" id="tg-all" onclick="tgFlag('all')">Nhắc Cả Nhóm (@All)</div>
        <div class="toggle-item active" id="tg-emoji" onclick="tgFlag('emoji')">Sử Dụng Icon Gây Ức Chế</div>
      </div>

      <div class="form-group">
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer; font-size:12px; color:var(--txt-0);">
          <input type="checkbox" id="tg-tag" onchange="tgTag()" style="width:18px; height:18px;">
          Bật tùy chọn Tag từng người theo Tên Thật
        </label>
        <div id="tag-wrap" style="display:none; margin-top:12px;">
          <div class="form-group"><select id="member-acc-select"><option value="">-- Chọn tài khoản quét --</option></select></div>
          <button class="btn-pill dark" onclick="loadMembers()">Nạp Danh Sách Tên Thật 100%</button>
          <div class="box-list" id="tag-selector" style="margin-top:10px; max-height:220px; display:none;"></div>
        </div>
      </div>
    </div>

    <div style="text-align:center; margin-bottom:20px; margin-top:15px;">
      <button class="btn-pill primary" onclick="startSpam()" style="padding:15px 40px; font-size:14px; box-shadow: 0 10px 30px rgba(255,105,180,0.5);">🚀 KHỞI ĐỘNG HỆ THỐNG</button>
      <button class="btn-pill danger" onclick="stopAll()" style="padding:15px 40px; font-size:14px; margin-left:10px;">⏹ DỪNG LẠI</button>
    </div>

    <div class="card">
      <h2><span>Tiến Trình Đang Chạy</span></h2>
      <div class="table-wrap">
        <table class="table"><thead><tr><th>Mã</th><th>Chế độ</th><th>Trạng thái</th><th>Thao tác</th></tr></thead><tbody id="tasks-tbody"></tbody></table>
      </div>
    </div>
  </div>

</div>

<!-- BOTTOM DOCK KHÔNG CHẶN TƯƠNG TÁC -->
<div class="bottom-dock">
  <button class="dock-btn active" data-tab="accounts"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg><span>Tài khoản</span></button>
  <button class="dock-btn" data-tab="boxes"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg><span>Hội thoại</span></button>
  <button class="dock-btn" data-tab="files"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg><span>Tập tin</span></button>
  <button class="dock-btn" data-tab="spam"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg><span>Gửi tin</span></button>
</div>

<script>
var flags = { heading: true, multi: true, all: false, emoji: true };
var selectedBoxes = [], selectedTags = [], _boxes = [], _members = [];
var currentMode = "fast", colorMode = "rainbow", fixedColor = "red", ZALO_PALETTE = [];

// ==========================================
// TOAST THÔNG MINH (VUỐT TẮT, KHÔNG CHỒNG LÊN NHAU)
// ==========================================
var Toast = (function(){
  var stack = null;
  function ensure(){ if(!stack) stack = document.getElementById('toast-stack'); return stack; }
  function show(msg, title, duration){
    duration = duration || 1400; var s = ensure(); if(!s) return;
    s.querySelectorAll('.toast').forEach(el => el.remove());

    var el = document.createElement('div'); el.className = 'toast';
    el.innerHTML = '<div class="t-head">🌸 ' + (title || 'Hệ Thống') + '</div><div class="t-body">' + msg + '</div>';
    s.appendChild(el);

    var timer = setTimeout(dismiss, duration);
    function dismiss(){ clearTimeout(timer); el.classList.add('swipe-up'); el.addEventListener('animationend', () => el.remove(), { once: true }); }
    var startY = 0;
    el.addEventListener('touchstart', e => { startY = e.touches[0].clientY; }, { passive: true });
    el.addEventListener('touchend', e => { if(e.changedTouches[0].clientY - startY < -15) dismiss(); });
  }
  return {
    success: (m, t, d) => show(m, t || 'Thành công', d),
    error: (m, t, d) => show(m, t || 'Lỗi hệ thống', d || 2000),
    info: (m, t, d) => show(m, t || 'Thông báo', d)
  };
})();

// XỬ LÝ CHUYỂN TAB VÀ SELECTORS
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
    c.classList.add('active'); currentMode = c.dataset.mode; document.getElementById('spam-mode').value = currentMode;
  });
});

document.querySelectorAll('#color-mode-bar .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#color-mode-bar .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active'); colorMode = c.dataset.cmode; document.getElementById('color-mode').value = colorMode;
    document.getElementById('fixed-colors-wrap').style.display = (colorMode === 'fixed') ? 'flex' : 'none';
  });
});

document.querySelectorAll('#delay-bar .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#delay-bar .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active'); document.getElementById('spam-delay').value = c.dataset.delay;
  });
});

document.querySelectorAll('#icon-bar .chip-item').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#icon-bar .chip-item').forEach(x => x.classList.remove('active'));
    c.classList.add('active'); document.getElementById('icon-count').value = c.dataset.icon;
  });
});

function tgFlag(name){ flags[name] = !flags[name]; document.getElementById('tg-' + name).classList.toggle('active', flags[name]); }
function tgTag(){ document.getElementById('tag-wrap').style.display = document.getElementById('tg-tag').checked ? 'block' : 'none'; }

async function api(url, opts = {}){
  try { return await fetch(url, Object.assign({}, opts, { headers: Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {}) })).then(r => r.json()); }
  catch(e){ return { error: 'Lỗi kết nối mạng: ' + e.message }; }
}

async function uploadLogo(){
  var inp = document.getElementById('logo-file-input');
  if(!inp.files.length) return Toast.error('Vui lòng chọn hình ảnh để tải lên');
  var fd = new FormData(); fd.append('logo', inp.files[0]);
  Toast.info('Đang xử lý logo...');
  var r = await fetch('/api/upload_logo', { method: 'POST', body: fd }).then(x => x.json());
  if(r.ok){
    Toast.success('Cập nhật logo thành công!');
    document.getElementById('header-logo').src = '/static/logo.png?t=' + Date.now();
    inp.value = ''; document.getElementById('logo-upload-txt').textContent = "Nhấn để chọn Ảnh Logo mới";
  } else { Toast.error(r.error || 'Lỗi tải ảnh'); }
}

async function loadAccounts(){
  var accs = await api('/api/accounts'); if(!Array.isArray(accs)) accs = [];
  var tb = document.getElementById('accounts-tbody');
  tb.innerHTML = accs.map(a => `<tr>
      <td>${a.id}</td><td><b>${a.label}</b></td><td><span style="color:var(--sakura-deep); font-weight:800;">${a.display_name || a.zalo_name || a.username || 'Chưa cập nhật'}</span></td>
      <td><code>…${String(a.uid||'').slice(-6)}</code></td>
      <td id="status-${a.id}">${a.status === 'live' ? '<span class="status-badge live">● HOẠT ĐỘNG</span>' : '<span class="status-badge dead">● NGẮT KẾT NỐI</span>'}</td>
      <td><button class="btn-pill light" onclick="delAcc(${a.id})" style="padding:6px 12px;">Xóa</button></td>
    </tr>`).join('') || '<tr><td colspan="6" style="text-align:center; padding:18px;">Chưa có dữ liệu</td></tr>';
  var opts = '<option value="">-- Chọn tài khoản --</option>' + accs.map(a => `<option value="${a.id}">${a.label} (${a.display_name||'Zalo'})</option>`).join('');
  document.getElementById('load-acc-select').innerHTML = opts; document.getElementById('member-acc-select').innerHTML = opts;
}

async function checkAllAccounts(){
  Toast.info('Đang kiểm tra bảo mật token...');
  var r = await api('/api/accounts/check_all', { method: 'POST' });
  if(r.ok) Toast.success(`Hoàn tất: ${r.live}/${r.total} tài khoản sống`);
  loadAccounts();
}

async function addAccount(){
  var label = document.getElementById('add-label').value.trim(), imei = document.getElementById('add-imei').value.trim(), cookies = document.getElementById('add-cookies').value.trim();
  if(!imei || !cookies) return Toast.error('Thiếu IMEI hoặc Cookie');
  Toast.info('Đang xác minh thông tin...');
  var r = await api('/api/accounts/add', { method: 'POST', body: JSON.stringify({ label, imei, cookies }) });
  if(r.error) return Toast.error(r.error);
  Toast.success('Tài khoản đã được thêm vào hệ thống'); refreshAll();
}

async function delAcc(id){
  if(!confirm('Xác nhận xóa tài khoản #' + id + '?')) return;
  await api('/api/accounts/' + id, { method: 'DELETE' }); Toast.success('Đã xóa'); refreshAll();
}

async function loadBoxes(){
  var aid = document.getElementById('load-acc-select').value; if(!aid) return Toast.error('Hãy chọn một tài khoản');
  Toast.info('Hệ thống đang nạp hội thoại...');
  var r = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  var all = (r.groups||[]).concat(r.friends||[]);
  document.getElementById('box-list').innerHTML = all.map((b,i) => `
    <div class="box-item" onclick="tgBox(this, ${i})"><div class="check-mark">✓</div><div><div class="b-title">${b.name}</div><div class="b-sub">${b.id}</div></div></div>
  `).join('') || '<div style="text-align:center; padding:18px;">Không tìm thấy hội thoại</div>';
  _boxes = all; selectedBoxes = []; document.getElementById('selected-count').textContent = '0';
  Toast.success('Đã nạp ' + all.length + ' hội thoại');
}

function tgBox(el, idx){
  var b = _boxes[idx]; if(!b) return;
  if(el.classList.contains('selected')){ el.classList.remove('selected'); selectedBoxes = selectedBoxes.filter(x => x.id !== b.id); }
  else { el.classList.add('selected'); selectedBoxes.push(b); }
  document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function selectAllBoxes(){ document.querySelectorAll('#box-list .box-item').forEach(el => el.classList.add('selected')); selectedBoxes = _boxes.slice(); document.getElementById('selected-count').textContent = selectedBoxes.length; }
function clearAllBoxes(){ document.querySelectorAll('#box-list .box-item').forEach(el => el.classList.remove('selected')); selectedBoxes = []; document.getElementById('selected-count').textContent = '0'; }

async function loadMembers(){
  var aid = document.getElementById('member-acc-select').value; if(!aid) return Toast.error('Vui lòng chọn tài khoản quét');
  var box = selectedBoxes.find(b => b.type === 'group'); if(!box) return Toast.error('Hãy chọn 1 nhóm bên tab Hội Thoại');
  Toast.info('Đang định danh tên thật thành viên...');
  var r = await api('/api/accounts/' + aid + '/members/' + box.id, { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  var mem = r.members || [];
  document.getElementById('tag-selector').style.display = 'block';
  document.getElementById('tag-selector').innerHTML = mem.map((m, i) => `
    <div class="box-item" onclick="tgMember(this, ${i})"><div class="check-mark">✓</div><div><div class="b-title">${m.name}</div><div class="b-sub">ID: ${m.id}</div></div></div>
  `).join('') || '<div style="padding:18px; text-align:center;">Không có thành viên</div>';
  _members = mem; selectedTags = []; Toast.success('Quét xong ' + mem.length + ' tên thật');
}

function tgMember(el, idx){
  var m = _members[idx]; if(!m) return;
  if(el.classList.contains('selected')){ el.classList.remove('selected'); selectedTags = selectedTags.filter(t => t.id !== m.id); }
  else { el.classList.add('selected'); selectedTags.push({ id: m.id, name: m.name }); }
}

async function uploadFile(){
  var inp = document.getElementById('file-input'); if(!inp.files.length) return Toast.error('Chưa chọn tệp tin văn bản');
  var fd = new FormData(); fd.append('file', inp.files[0]);
  Toast.info('Đang nạp và phân tích file siêu tốc...');
  var r = await fetch('/api/files/upload', { method: 'POST', body: fd }).then(x => x.json());
  if(r.error) return Toast.error(r.error);
  Toast.success('Lưu thành công ' + r.lines + ' khối văn bản'); inp.value = ''; document.getElementById('file-upload-txt').textContent = "Nhấn để chọn tệp Văn bản (.txt)"; loadFiles();
}

async function loadFiles(){
  var files = await api('/api/files'); if(!Array.isArray(files)) files = [];
  document.getElementById('files-list').innerHTML = files.map(f => `
    <div class="box-item" style="cursor:default;"><div style="flex:1;"><div class="b-title">📄 ${f.filename}</div><div class="b-sub">${f.lines} khối</div></div>
    <button class="btn-pill danger" onclick="delFile(${f.id})" style="padding:6px 12px;">Xóa</button></div>
  `).join('') || '<div style="text-align:center; padding:18px;">Chưa có tập tin</div>';
  document.getElementById('spam-file-select').innerHTML = '<option value="">-- Chọn tập tin --</option>' + files.map(f => `<option value="${f.id}">${f.filename} (${f.lines} khối)</option>`).join('');
}
async function delFile(id){ if(!confirm('Xác nhận xóa tệp?')) return; await api('/api/files/' + id, { method: 'DELETE' }); Toast.success('Đã xóa tệp'); loadFiles(); }

async function startSpam(){
  if(!selectedBoxes.length) return Toast.error('Lỗi: Chưa chọn hội thoại nhận tin');
  var fid = document.getElementById('spam-file-select').value, direct = document.getElementById('spam-messages').value.trim(), blocks = [];
  if(fid) blocks = (await api('/api/files/' + fid + '/preview')).all || [];
  else if(direct) blocks = (currentMode === "treo_ngon" || currentMode === "treo_nhay") ? [direct] : (direct.includes(';') ? direct.split(';').map(m => m.trim()).filter(Boolean) : [direct]);
  if(!blocks.length) return Toast.error('Lỗi: Chưa có dữ liệu văn bản để gửi');

  var payload = {
    targets: selectedBoxes, blocks: blocks, delay: parseFloat(document.getElementById('spam-delay').value) || 1,
    use_emoji: flags.emoji, icon_count: flags.emoji ? (parseInt(document.getElementById('icon-count').value) || 3) : 0,
    tag_users: document.getElementById('tg-tag').checked ? selectedTags : [], tag_all: flags.all,
    is_heading: flags.heading, multi_acc: flags.multi, mode: currentMode, color_mode: colorMode, fixed_color: fixedColor
  };
  var res = await api('/api/tasks/start', { method: 'POST', body: JSON.stringify(payload) });
  if(res.error) return Toast.error(res.error);
  Toast.success('Khởi động động cơ thành công!'); loadTasks();
}

async function stopAll(){ await api('/api/tasks/stop_all', { method: 'POST' }); Toast.info('Đã phát lệnh dừng khẩn cấp'); loadTasks(); }

async function loadTasks(){
  var tasks = await api('/api/tasks'); if(!Array.isArray(tasks)) tasks = [];
  document.getElementById('tasks-tbody').innerHTML = tasks.map(t => `<tr>
      <td><code>${t.id.slice(-6)}</code></td><td><b>${t.type}</b></td>
      <td>${t.status === 'running' ? '<span class="status-badge live">Đang gửi</span>' : '<span class="status-badge dead">Đã dừng</span>'}</td>
      <td>${t.status === 'running' ? `<button class="btn-pill danger" onclick="stopTask('${t.id}')" style="padding:4px 12px;">Dừng</button>` : ''}</td>
    </tr>`).join('') || '<tr><td colspan="4" style="text-align:center; padding:18px;">Chưa có tiến trình</td></tr>';
}
async function stopTask(tid){ await api('/api/tasks/' + tid + '/stop', { method: 'POST' }); Toast.info('Đã dừng tiến trình'); loadTasks(); }

async function loadColors(){
  var cols = await api('/api/colors');
  if(Array.isArray(cols)){ ZALO_PALETTE = cols; document.getElementById('fixed-colors-wrap').innerHTML = cols.map(c => `<div class="chip-item" style="border-color:#${c.hex}; color:#${c.hex};" onclick="setFixedColor('${c.id}')">${c.name}</div>`).join(''); }
}
function setFixedColor(cid){ fixedColor = cid; Toast.info('Đã chọn màu tĩnh: ' + cid); }

function refreshAll(){ loadAccounts(); loadFiles(); loadTasks(); }

// ==========================================
// CÔNG CỤ TẠO CÁNH HOA ANH ĐÀO (SIÊU NHẸ)
// ==========================================
var sC = document.getElementById('sakura-canvas'), ctx = sC.getContext('2d'), w = window.innerWidth, h = window.innerHeight;
sC.width = w; sC.height = h;
var pts = Array.from({length: 45}, () => ({x: Math.random()*w, y: Math.random()*h, s: Math.random()*8+6, sy: Math.random()*1.5+0.8, sx: Math.random()*2-1, a: Math.random()*360, av: (Math.random()-0.5)*2}));
function draw(){
  ctx.clearRect(0,0,w,h);
  pts.forEach(p => {
    ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a * Math.PI/180); ctx.fillStyle='rgba(255,183,197,0.85)'; ctx.shadowBlur=5; ctx.shadowColor='rgba(255,105,180,0.4)';
    ctx.beginPath(); ctx.moveTo(0,0); ctx.bezierCurveTo(p.s/2, -p.s/2, p.s, 0, 0, p.s); ctx.bezierCurveTo(-p.s, 0, -p.s/2, -p.s/2, 0, 0); ctx.fill(); ctx.restore();
    p.y += p.sy; p.x += p.sx; p.a += p.av;
    if(p.y > h+20){ p.y = -20; p.x = Math.random()*w; } if(p.x > w+20) p.x = -20; if(p.x < -20) p.x = w+20;
  }); requestAnimationFrame(draw);
}
draw();
window.addEventListener('resize', () => { w = window.innerWidth; h = window.innerHeight; sC.width = w; sC.height = h; });

document.getElementById('file-input').addEventListener('change', function(){ if(this.files.length>0) { document.getElementById('file-upload-txt').textContent = "Đã chọn: " + this.files[0].name; document.getElementById('file-upload-txt').style.color = "var(--sakura-deep)"; } });
document.getElementById('logo-file-input').addEventListener('change', function(){ if(this.files.length>0) { document.getElementById('logo-upload-txt').textContent = "Đã chọn Logo: " + this.files[0].name; document.getElementById('logo-upload-txt').style.color = "var(--sakura-deep)"; } });

loadColors(); refreshAll(); setInterval(loadTasks, 5000);
</script>
</body>
</html>
"""

# ============================================================
# ĐỊNH TUYẾN MÁY CHỦ
# ============================================================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"): return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

@app.route("/static/<path:filename>")
def static_files(filename): return send_from_directory(STATIC_DIR, filename)

@app.route("/verify_gate")
def verify_gate(): return render_template_string(HTML_GATE)

@app.route("/api/verify_human", methods=["POST"])
def api_verify_human(): session["human_verified"] = True; return jsonify({"ok": True})

@app.route("/")
@login_required
def index(): return render_template_string(HTML_INDEX)

@app.route("/login", methods=["GET", "POST"])
def login():
    ip = get_client_ip(); now = time.time(); tracker = login_fail_tracker[ip]
    if tracker["locked_until"] > now: return render_template_string(HTML_LOGIN, error=f"Hệ thống khóa tạm thời. Thử lại sau {int(tracker['locked_until'] - now)}s.")
    if request.method == "POST":
        if request.form.get("password", "") == APP_PASSWORD:
            session["logged_in"] = True; login_fail_tracker[ip] = {"count": 0, "locked_until": 0}
            return redirect(url_for("index"))
        else:
            tracker["count"] += 1
            if tracker["count"] >= LOGIN_MAX_FAILS: tracker["locked_until"] = now + LOGIN_LOCKOUT_TIME; return render_template_string(HTML_LOGIN, error="Khóa IP 15 phút do nhập sai 5 lần.")
            return render_template_string(HTML_LOGIN, error=f"Mã truy cập sai! Còn {LOGIN_MAX_FAILS - tracker['count']} lần thử.")
    return render_template_string(HTML_LOGIN)

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/api/upload_logo", methods=["POST"])
@login_required
def api_upload_logo():
    if "logo" not in request.files: return jsonify({"error": "Không có tệp"})
    f = request.files["logo"]
    if not f.filename: return jsonify({"error": "Tên rỗng"})
    f.save(os.path.join(STATIC_DIR, "logo.png"))
    return jsonify({"ok": True})

@app.route("/api/colors", methods=["GET"])
@login_required
def api_colors(): return jsonify(ZALO_PALETTE)

@app.route("/api/accounts", methods=["GET"])
@login_required
def api_accounts(): return jsonify([dict(r) for r in db().execute("SELECT * FROM accounts ORDER BY id DESC").fetchall()])

@app.route("/api/accounts/add", methods=["POST"])
@login_required
def api_accounts_add():
    d = request.json
    label = d.get("label", "").strip() or "acc_" + str(int(time.time()))
    imei = d.get("imei", "").strip()
    ck = d.get("cookies", "").strip()
    if not imei or not ck: return jsonify({"error": "Vui lòng nhập đủ IMEI và Cookie"}), 400
    try: ck_obj = json.loads(ck); z = Zalo(imei, ck_obj)
    except Exception as e: return jsonify({"error": f"Lỗi đăng nhập: {str(e)}"}), 400
    conn = db(); conn.execute("INSERT INTO accounts (label, imei, cookies, added_at, uid, display_name, zalo_name, username, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (label, imei, json.dumps(ck_obj), time.time(), z.uid, z.display_name or "", z.zalo_name or "", z.username or "", "live")); conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/accounts/<int:aid>", methods=["DELETE"])
@login_required
def api_accounts_delete(aid): conn = db(); conn.execute("DELETE FROM accounts WHERE id = ?", (aid,)); conn.commit(); conn.close(); return jsonify({"ok": True})

@app.route("/api/accounts/check_all", methods=["POST"])
@login_required
def api_accounts_check_all():
    conn = db(); rows = conn.execute("SELECT * FROM accounts").fetchall(); live_count = 0
    for r in rows:
        try: Zalo(r["imei"], json.loads(r["cookies"])); conn.execute("UPDATE accounts SET status = 'live' WHERE id = ?", (r["id"],)); live_count += 1
        except Exception: conn.execute("UPDATE accounts SET status = 'dead' WHERE id = ?", (r["id"],))
    conn.commit(); conn.close()
    return jsonify({"ok": True, "total": len(rows), "live": live_count})

@app.route("/api/accounts/<int:aid>/load_boxes", methods=["POST"])
@login_required
def api_load_boxes(aid):
    row = db().execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    if not row: return jsonify({"error": "Không tìm thấy tài khoản"}), 404
    try: z = Zalo(row["imei"], json.loads(row["cookies"])); return jsonify({"ok": True, "groups": z.groups(), "friends": z.friends()})
    except Exception as e: return jsonify({"error": str(e)}), 400

@app.route("/api/accounts/<int:aid>/members/<group_id>", methods=["POST"])
@login_required
def api_load_members(aid, group_id):
    row = db().execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    if not row: return jsonify({"error": "Không tìm thấy tài khoản"}), 404
    try: z = Zalo(row["imei"], json.loads(row["cookies"])); return jsonify({"ok": True, "members": z.get_members_full(group_id)})
    except Exception as e: return jsonify({"error": str(e)}), 400

@app.route("/api/files", methods=["GET"])
@login_required
def api_files_list(): return jsonify([dict(r) for r in db().execute("SELECT * FROM files ORDER BY id DESC").fetchall()])

@app.route("/api/files/upload", methods=["POST"])
@login_required
def api_files_upload():
    f = request.files.get("file")
    if not f or not f.filename: return jsonify({"error": "Tập tin rỗng"}), 400
    fp = os.path.join(UPLOAD_DIR, str(int(time.time())) + "_" + f.filename); f.save(fp)
    blocks = process_large_file(fp)
    conn = db(); conn.execute("INSERT INTO files (filename, filepath, lines, size, uploaded_at) VALUES (?, ?, ?, ?, ?)", (f.filename, fp, len(blocks), os.path.getsize(fp), time.time())); conn.commit(); conn.close()
    return jsonify({"ok": True, "filename": f.filename, "lines": len(blocks)})

@app.route("/api/files/<int:fid>/preview", methods=["GET"])
@login_required
def api_files_preview(fid):
    row = db().execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    if not row: return jsonify({"error": "Không tìm thấy tập tin"}), 404
    return jsonify({"filename": row["filename"], "all": process_large_file(row["filepath"])})

@app.route("/api/files/<int:fid>", methods=["DELETE"])
@login_required
def api_files_delete(fid): conn = db(); conn.execute("DELETE FROM files WHERE id = ?", (fid,)); conn.commit(); conn.close(); return jsonify({"ok": True})

@app.route("/api/tasks", methods=["GET"])
@login_required
def api_tasks(): return jsonify([dict(r) for r in db().execute("SELECT * FROM tasks ORDER BY started_at DESC LIMIT 50").fetchall()])

@app.route("/api/tasks/start", methods=["POST"])
@login_required
def api_tasks_start():
    d = request.json
    targets = d.get("targets", [])
    blocks = d.get("blocks", [])
    if not targets or not blocks: return jsonify({"error": "Vui lòng chỉ định hội thoại và văn bản"}), 400
    
    tid = new_tid("task")
    stop_ev = threading.Event()
    th = threading.Thread(
        target=task_supervisor,
        args=(tid, targets, blocks, float(d.get("delay", 1.0)), bool(d.get("use_emoji", True)), int(d.get("icon_count", 3)),
              d.get("tag_users", []), bool(d.get("tag_all", False)), bool(d.get("is_heading", True)),
              bool(d.get("multi_acc", True)), d.get("mode", "fast"), d.get("color_mode", "rainbow"), d.get("fixed_color", "red"), stop_ev),
        daemon=True
    )
    conn = db(); conn.execute("INSERT INTO tasks (id, type, status, started_at, stats) VALUES (?, ?, ?, ?, ?)", (tid, d.get("mode", "fast"), "running", time.time(), "{}")); conn.commit(); conn.close()
    ACTIVE_TASKS[tid] = {"stop": stop_ev, "thread": th}; th.start()
    return jsonify({"ok": True, "task_id": tid})

@app.route("/api/tasks/<tid>/stop", methods=["POST"])
@login_required
def api_tasks_stop(tid):
    if tid in ACTIVE_TASKS: ACTIVE_TASKS[tid]["stop"].set(); return jsonify({"ok": True})
    return jsonify({"error": "Không tìm thấy tiến trình"}), 404

@app.route("/api/tasks/stop_all", methods=["POST"])
@login_required
def api_tasks_stop_all():
    for tid, t in list(ACTIVE_TASKS.items()): t["stop"].set()
    return jsonify({"ok": True, "count": len(ACTIVE_TASKS)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
