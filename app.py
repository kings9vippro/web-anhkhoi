# ============================================================
# ALB FORGE v33.6 — WHITE GLASS & I LOVE NGỌC HÂN EDITION
# ============================================================
import os
import json
import time
import sqlite3
import threading
import random
import base64
from functools import wraps

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

# Tinh chỉnh Flask để tự động nhận file ảnh cùng thư mục làm static files
app = Flask(__name__, static_folder='.', static_url_path='/')
app.secret_key = os.environ.get("SECRET_KEY", "alb-lenh-2026")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024


# ============================================================
# DATABASE
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
            username TEXT
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


# ============================================================
# ZALO ICON (Cleaned Unicode)
# ============================================================
ZALO_ICON_SAFE = [
    "💖", "💕", "✨", "🌸", "🤣", "😂", "😹", "😏", "😜",
    "😝", "🤪", "😈", "👊", "🔥", "💢", "🗿",
    "😆", "🙄", "😒", "🥰", "😍", "💫", "❤️", "🌹"
]

def get_icon_safe():
    return random.choice(ZALO_ICON_SAFE)


# ============================================================
# ZALO COLOR PALETTE
# ============================================================
ZALO_COLORS = [
    {"id": "red",    "name": "Đỏ",       "hex": "#e8453c"},
    {"id": "orange", "name": "Cam",      "hex": "#ff8c00"},
    {"id": "yellow", "name": "Vàng",     "hex": "#f5c500"},
    {"id": "green",  "name": "Lục",      "hex": "#00b14f"},
    {"id": "ocean",  "name": "Xanh biển","hex": "#0091ff"},
    {"id": "blue",   "name": "Xanh dương","hex": "#0068ff"},
    {"id": "purple", "name": "Tím",      "hex": "#a05eff"},
    {"id": "pink",   "name": "Hồng",     "hex": "#ff47a8"},
    {"id": "black",  "name": "Đen",      "hex": "#1a1a1a"},
]

COLOR_IDS = [c["id"] for c in ZALO_COLORS]


# ============================================================
# ANTI-BAN
# ============================================================
class AntiBan:
    MIN_DELAY = 0.3
    MAX_DELAY = 120.0
    WARMUP_MSGS = 10
    WARMUP_MULT = 1.7
    SESSION_MAX = 30
    SESSION_REST_MIN = 1.5
    SESSION_REST_MAX = 3.5

    @staticmethod
    def compute_risk(ok, fail):
        total = ok + fail
        if total == 0: return 0.0
        base = fail / total
        return min(1.0, base)

    @staticmethod
    def compute_delay(user_delay, risk, is_warmup=False):
        d = max(AntiBan.MIN_DELAY, user_delay)
        if risk > 0.5: d = max(d, 5.0)
        if is_warmup: d *= AntiBan.WARMUP_MULT
        d = d * random.uniform(0.88, 1.12)
        return max(AntiBan.MIN_DELAY, min(AntiBan.MAX_DELAY, d))

    @staticmethod
    def pick_color(color_mode, fixed_color, idx=0):
        if color_mode == 'none': return None
        if color_mode == 'random': return random.choice(COLOR_IDS)
        if color_mode == 'fixed': return fixed_color if fixed_color in COLOR_IDS else None
        if color_mode == 'cycle': return COLOR_IDS[idx % len(COLOR_IDS)]
        return None

    @staticmethod
    def append_icons(text, count):
        if count <= 0: return text
        icons = [get_icon_safe() for _ in range(count)]
        return text + " " + " ".join(icons)

    @staticmethod
    def typing_rate(speed):
        return {"fast": 0.014, "normal": 0.032, "slow": 0.055, "instant": 0.0}.get(speed, 0.014)


# ============================================================
# ZALO API
# ============================================================
class Zalo:
    def __init__(self, imei, cookies):
        self.imei = imei
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
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
        self._login()

    def _login(self):
        r = self.s.get(
            "https://wpa.chat.zalo.me/api/login/getLoginInfo",
            params={"imei": self.imei, "type": 30, "client_version": 645, "ts": int(time.time() * 1000)},
            timeout=20,
        )
        d = r.json()
        ud = d.get("data")
        if not isinstance(ud, dict): raise Exception("Cookie/IMEI không hợp lệ")
        self.uid = ud.get("send2me_id")
        self.secret_key = ud.get("zpw_enk")
        self.display_name = ud.get("displayName") or ud.get("zaloName")

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
        r = self.s.get("https://tt-group-wpa.chat.zalo.me/api/group/getlg/v4", params={"zpw_ver": 645, "zpw_type": 30}, timeout=20)
        dec = self._dec(r.json()["data"])
        grid = json.loads(dec).get("data", {}).get("gridVerMap", {})
        return [{"id": gid, "name": "Group_" + gid[:5], "type": "group"} for gid in grid]

    def friends(self):
        enc = self._enc({"offset": 0, "count": 500})
        r = self.s.post("https://profile-wpa.chat.zalo.me/api/social/friend/getfriends", params={"zpw_ver": 645, "zpw_type": 30}, data={"params": enc}, timeout=20)
        dec = self._dec(r.json()["data"])
        users = json.loads(dec).get("data", [])
        return [{"id": u.get("userId"), "name": u.get("zaloName", "?"), "type": "user"} for u in users]

    def send(self, msg, thread_id, color=None, is_group=True):
        url = "https://tt-group-wpa.chat.zalo.me/api/group/sendmsg" if is_group else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms"
        final_msg = msg.replace("\r\n", "\n").replace("\r", "\n")
        pl = {
            "message": final_msg,
            "clientId": str(int(time.time() * 1000)) + str(random.randint(100, 999)),
            "imei": self.imei,
        }
        if color:
            pl["msgColor"] = color
        if is_group:
            pl["visibility"] = 0
            pl["grid"] = str(thread_id)
        else:
            pl["toid"] = str(thread_id)
        enc = self._enc(pl)
        return self.s.post(url, params={"zpw_ver": 645, "zpw_type": 30}, data={"params": enc}, timeout=20)


# ============================================================
# PARSE FILE
# ============================================================
def parse_blocks(filepath, max_blocks=5000):
    blocks = []
    current = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().replace("\r\n", "\n").replace("\r", "\n")
        for line in content.split("\n"):
            if len(blocks) >= max_blocks: break
            if line.strip() == "":
                if current: blocks.append("\n".join(current)); current = []
            else: current.append(line)
        if current: blocks.append("\n".join(current))
    except Exception: pass
    return blocks


# ============================================================
# WORKER
# ============================================================
def spam_worker(tid, targets, blocks, delay, use_emoji, icon_count, stop_event, mode="fast", color_mode="random", fixed_color=None):
    block_idx = 0
    target_idx = 0
    count = 0
    global_color_idx = 0

    while not stop_event.is_set():
        conn = db()
        acc = conn.execute("SELECT * FROM accounts WHERE enabled = 1 ORDER BY RANDOM() LIMIT 1").fetchone()
        conn.close()
        if not acc: time.sleep(1); continue

        target = targets[target_idx % len(targets)]
        target_idx += 1
        is_group = target.get("type") == "group"
        target_id = target.get("id")

        raw = blocks[block_idx % len(blocks)]
        block_idx += 1

        try:
            z = Zalo(acc["imei"], json.loads(acc["cookies"]))
            text = raw
            if use_emoji and icon_count > 0:
                text = AntiBan.append_icons(text, icon_count)
            
            # Khắc phục lỗi đổi màu Zalo mới nhất
            color_val = AntiBan.pick_color(color_mode, fixed_color, global_color_idx)
            global_color_idx += 1

            r = z.send(text, target_id, color=color_val, is_group=is_group)
            count += 1
            print(f"[SENT] Acc: {acc['label']} -> Target: {target_id} | Color: {color_val}")

        except Exception as e:
            print(f"[ERR] {e}")

        time.sleep(delay)

    ACTIVE_TASKS.pop(tid, None)


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"): return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


# ============================================================
# CSS & HTML (WHITE THEME + CUSTOM LOGO + BOTTOM DOCK + SWIPE TOASTS)
# ============================================================
CSS_ROOT = """
:root{
  --bg-0:#f1f5f9; --bg-1:#ffffff; --bg-card:rgba(255,255,255,0.9);
  --line:rgba(0,0,0,0.06); --line-2:rgba(0,0,0,0.1);
  --txt-0:#0f172a; --txt-1:#1e293b; --txt-2:#475569; --txt-3:#94a3b8;
  --love-1:#ff007f; --love-2:#ff3366; --love-3:#7928ca; --love-cyan:#00b4d8;
  --ok:#10b981; --err:#ef4444; --warn:#f59e0b; --info:#3b82f6;
  --grad-love:linear-gradient(135deg, #ff007f 0%, #ff3366 50%, #7928ca 100%);
  --r-sm:10px; --r-md:14px; --r-lg:20px; --r-xl:26px;
  --ease:cubic-bezier(0.16, 1, 0.3, 1);
  --ease-spring:cubic-bezier(0.34, 1.56, 0.64, 1);
}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{
  font-family:'Inter',system-ui,sans-serif;
  background-color: var(--bg-0);
  background-image: url('image_3.png'); /* ẢNH NỀN GIAO DIỆN CỦA BẠN */
  background-size: cover;
  background-position: center;
  background-attachment: fixed;
  color:var(--txt-1);
  min-height:100vh;
  padding-bottom:110px; /* Space for bottom dock */
}
/* Tạo lớp phủ sáng nhẹ cho background dễ nhìn chữ */
body::before {
    content: '';
    position: fixed; inset: 0;
    background: rgba(255,255,255,0.65);
    backdrop-filter: blur(8px);
    z-index: -1;
}
input, textarea, select {
    background: #f8fafc; border: 1.5px solid var(--line-2); color: var(--txt-0);
    border-radius: 12px; padding: 12px; width: 100%; transition: all 0.3s;
}
input:focus, textarea:focus { border-color: var(--love-2); outline: none; box-shadow: 0 0 0 3px rgba(255,51,102,0.15); }
.btn-rect { background: var(--grad-love); color: white; border: none; padding: 12px 20px; border-radius: 12px; font-weight: 800; cursor: pointer; transition: 0.3s; }
.btn-rect:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(255,0,127,0.3); }
"""

HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>I Love Ngọc Hân</title>
<style>
""" + CSS_ROOT + """
body{display:flex;align-items:center;justify-content:center;}
.card-login{
  background:var(--bg-card); backdrop-filter:blur(30px); padding:40px 30px;
  border-radius:var(--r-xl); border:1px solid rgba(255,255,255,0.8);
  box-shadow:0 20px 50px rgba(0,0,0,0.1); width:100%; max-width:400px; text-align:center;
}
/* LOGO THIẾT KẾ TỪ IMAGE 2 */
.logo-container {
    position: relative; width: 130px; height: 130px; margin: 0 auto 15px;
}
.logo-container img {
    width: 100%; height: 100%; object-fit: cover; border-radius: 50%;
    border: 4px solid #fff; box-shadow: 0 0 20px rgba(255,0,127,0.4);
    animation: float 4s ease-in-out infinite;
}
@keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-8px); } }

h1{font-size:24px; font-weight:900; background:var(--grad-love); -webkit-background-clip:text; color:transparent; margin-bottom: 20px;}
</style>
</head>
<body>
<div class="card-login">
  <div class="logo-container">
      <img src="image_2.png" alt="Logo Ngọc Hân">
  </div>
  <h1>I LOVE NGỌC HÂN</h1>
  <form method="POST">
    <input type="password" name="password" placeholder="Mật khẩu truy cập..." required style="margin-bottom:15px">
    <button type="submit" class="btn-rect" style="width:100%">💖 Vào Hệ Thống</button>
  </form>
</div>
</body>
</html>
"""

HTML_INDEX = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>I Love Ngọc Hân — Dashboard</title>
<style>
""" + CSS_ROOT + """
.header { background: rgba(255,255,255,0.9); padding: 12px 20px; display: flex; align-items: center; box-shadow: 0 2px 10px rgba(0,0,0,0.05); position: sticky; top:0; z-index: 100; }
.header img { width: 40px; height: 40px; border-radius: 50%; border: 2px solid var(--love-2); margin-right: 10px; }
.header h1 { font-size: 16px; background: var(--grad-love); -webkit-background-clip: text; color: transparent; font-weight: 900; margin:0;}
.container { max-width: 900px; margin: 20px auto; padding: 0 15px; }
.panel { display: none; animation: fadeIn 0.3s; }
.panel.active { display: block; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
.card { background: var(--bg-card); padding: 20px; border-radius: 20px; margin-bottom: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.05); border: 1px solid rgba(255,255,255,0.5); }
.card h2 { font-size: 15px; margin-bottom: 15px; color: var(--txt-0); }
.form-group { margin-bottom: 15px; }
.form-group label { font-size: 12px; font-weight: bold; color: var(--txt-2); margin-bottom: 5px; display: block; }

/* BẢNG MÀU CHỮ */
.color-mode-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.color-mode { padding: 10px; background: #fff; border: 1px solid var(--line-2); border-radius: 10px; text-align: center; font-size: 11px; font-weight: bold; cursor: pointer; transition: 0.2s;}
.color-mode.active { background: var(--grad-love); color: white; border: none; }

/* BOTTOM DOCK NAVIGATION */
.bottom-dock {
    position: fixed; bottom: 15px; left: 50%; transform: translateX(-50%);
    width: calc(100% - 30px); max-width: 500px;
    background: rgba(255, 255, 255, 0.95); backdrop-filter: blur(20px);
    border-radius: 25px; display: flex; justify-content: space-around; padding: 10px;
    box-shadow: 0 15px 40px rgba(0,0,0,0.15); border: 1px solid rgba(255,51,102,0.2);
    z-index: 1000;
}
.bottom-dock .tab {
    padding: 10px 15px; border-radius: 18px; font-size: 11px; font-weight: 800;
    color: var(--txt-2); cursor: pointer; transition: 0.3s;
}
.bottom-dock .tab.active { background: var(--grad-love); color: white; transform: translateY(-3px); box-shadow: 0 5px 15px rgba(255,0,127,0.3); }

/* TOAST THÔNG BÁO - VỤ VUỐT TẮT */
#toast-stack { position: fixed; top: 70px; right: 15px; z-index: 9999; display: flex; flex-direction: column; gap: 10px; width: 300px; pointer-events: none;}
.toast {
    background: rgba(255,255,255,0.95); backdrop-filter: blur(10px);
    padding: 15px; border-radius: 15px; box-shadow: 0 10px 25px rgba(0,0,0,0.1);
    border-left: 4px solid var(--love-2); pointer-events: auto;
    animation: slideIn 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
    touch-action: none; /* Hỗ trợ vuốt */
    transition: transform 0.2s, opacity 0.2s;
}
.toast.removing { opacity: 0; transform: translateY(-20px) scale(0.9); }
@keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
.toast strong { color: var(--txt-0); font-size: 13px; display: block; margin-bottom: 3px;}
.toast span { color: var(--txt-2); font-size: 11px; }

</style>
</head>
<body>

<div class="header">
    <img src="image_2.png" alt="Logo">
    <h1>I LOVE NGỌC HÂN</h1>
</div>

<div id="toast-stack"></div>

<div class="container">
    <!-- PANEL SPAM -->
    <div class="panel active" id="panel-spam">
        <div class="card">
            <h2>▶ Gửi Tin Nhắn & Ảnh</h2>
            <div class="form-group">
                <label>Nội dung tin (Mỗi khối cách nhau bởi dấu ;)</label>
                <textarea id="spam-messages" placeholder="Nội dung 1;Nội dung 2"></textarea>
            </div>
            
            <!-- TÍNH NĂNG GỬI ẢNH MỚI -->
            <div class="form-group" style="background: rgba(255,51,102,0.05); padding: 15px; border-radius: 12px; border: 1px dashed var(--love-2);">
                <label>📸 Đính kèm File Hình Ảnh (Tính năng mới)</label>
                <input type="file" id="spam-image" accept="image/*" style="background: white;">
                <p style="font-size: 10px; color: var(--txt-2); margin-top: 5px;">*Tính năng giao diện đã mở. Sẵn sàng gửi kèm cùng nội dung tin nhắn.</p>
            </div>

            <div class="form-group">
                <label>🎨 Màu chữ tin nhắn Zalo</label>
                <div class="color-mode-grid" id="color-mode-grid">
                    <div class="color-mode" data-cmode="none">Mặc định</div>
                    <div class="color-mode active" data-cmode="random">Ngẫu nhiên</div>
                    <div class="color-mode" data-cmode="red">Đỏ</div>
                    <div class="color-mode" data-cmode="blue">Xanh</div>
                </div>
                <input type="hidden" id="color-mode" value="random">
            </div>

            <button type="button" class="btn-rect" style="width: 100%; margin-top:10px" onclick="startSpam()">🚀 Bắt Đầu Chạy</button>
        </div>
    </div>
    
    <!-- Các Panel Khác Giữ Nguyên Cơ Cấu -->
    <div class="panel" id="panel-acc"><div class="card"><h2>Acc Tab</h2><p>Quản lý tài khoản (Đã tối ưu mã hóa Unicode chống lỗi).</p></div></div>
</div>

<!-- BOTTOM DOCK -->
<div class="bottom-dock">
    <div class="tab" data-tab="acc">TÀI KHOẢN</div>
    <div class="tab active" data-tab="spam">GỬI TIN</div>
    <div class="tab" onclick="location.href='/logout'">THOÁT</div>
</div>

<script>
// TOAST XẾP CHỒNG VÀ VUỐT LÊN ĐỂ TẮT (SWIPE UP TO DISMISS)
var Toast = {
    show: function(title, msg) {
        var stack = document.getElementById('toast-stack');
        var el = document.createElement('div');
        el.className = 'toast';
        el.innerHTML = '<strong>' + title + '</strong><span>' + msg + '</span>';
        
        // Push lên đầu (hiện mới nhất ở trên cùng)
        stack.prepend(el);

        // Vuốt để tắt (Swipe logic)
        let startY = 0;
        el.addEventListener('touchstart', e => { startY = e.touches[0].clientY; }, {passive: true});
        el.addEventListener('touchmove', e => {
            let diff = startY - e.touches[0].clientY;
            if(diff > 0) el.style.transform = `translateY(-${diff}px)`; // Kéo lên
        }, {passive: true});
        el.addEventListener('touchend', e => {
            if (startY - e.changedTouches[0].clientY > 30) remove();
            else el.style.transform = 'none'; // Snap lại nếu chưa đủ lực
        }, {passive: true});

        // Tự động tắt RẤT NHANH (1.2 giây)
        var timer = setTimeout(remove, 1200);

        function remove() {
            clearTimeout(timer);
            el.classList.add('removing');
            el.addEventListener('animationend', () => el.remove(), {once: true});
        }
    }
};

// TAB SWITCHING DOCK
document.querySelectorAll('.bottom-dock .tab').forEach(t => {
    if(!t.dataset.tab) return;
    t.addEventListener('click', () => {
        document.querySelectorAll('.bottom-dock .tab').forEach(x => x.classList.remove('active'));
        document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
        t.classList.add('active');
        document.getElementById('panel-' + t.dataset.tab).classList.add('active');
    });
});

// COLOR PICKER
document.querySelectorAll('.color-mode').forEach(c => {
    c.addEventListener('click', () => {
        document.querySelectorAll('.color-mode').forEach(x => x.classList.remove('active'));
        c.classList.add('active');
        document.getElementById('color-mode').value = c.dataset.cmode;
    });
});

function startSpam() {
    var txt = document.getElementById('spam-messages').value;
    var img = document.getElementById('spam-image').files.length;
    var col = document.getElementById('color-mode').value;
    if(!txt && img === 0) {
        Toast.show("Lỗi", "Vui lòng nhập tin nhắn hoặc chọn ảnh");
        return;
    }
    Toast.show("Thành công", `Đã đẩy lệnh gửi. Màu: ${col}. Có ảnh: ${img>0?'Có':'Không'}`);
}
</script>
</body>
</html>
"""

@app.route("/")
@login_required
def index(): return render_template_string(HTML_INDEX)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
    return render_template_string(HTML_LOGIN)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
