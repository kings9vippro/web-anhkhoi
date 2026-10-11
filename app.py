# ============================================================
# ALB FORGE v35.0 — NOEL & CHRISTMAS ROYAL EDITION ($800 SPEC)
# I LOVE NGỌC HÂN • ANTI-DDOS • MULTI-THREAD CONCURRENCY • TAG ALL
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
    session, redirect, url_for, abort
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
app.secret_key = os.environ.get("SECRET_KEY", "alb-noel-ngoc-han-2026-vip")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024


# ============================================================
# ANTI-DDOS & RATE LIMITER & BRUTE-FORCE SHIELD
# ============================================================
DDOS_LIMIT_PER_MINUTE = 120
DDOS_BURST_PER_SEC = 25
LOGIN_MAX_FAILS = 5
LOGIN_LOCKOUT_TIME = 900  # 15 phút

ip_request_history = defaultdict(list)
ip_blocked_until = {}
login_fail_tracker = defaultdict(lambda: {"count": 0, "locked_until": 0})
traffic_lock = threading.Lock()


def get_client_ip():
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


@app.before_request
def anti_ddos_middleware():
    # Bỏ qua các endpoint tĩnh nếu có
    if request.endpoint in ("static",):
        return

    ip = get_client_ip()
    now = time.time()

    with traffic_lock:
        # Kiểm tra IP có đang bị tạm khóa do DDoS không
        if ip in ip_blocked_until:
            if now < ip_blocked_until[ip]:
                return jsonify({
                    "error": "Phát hiện lưu lượng bất thường. IP tạm thời bị hạn chế bởi Khiên Bảo Vệ ALB Anti-DDoS.",
                    "retry_after": int(ip_blocked_until[ip] - now)
                }), 429
            else:
                del ip_blocked_until[ip]

        # Lọc danh sách request trong vòng 60 giây
        history = [t for t in ip_request_history[ip] if now - t < 60]
        ip_request_history[ip] = history

        # Kiểm tra ngưỡng burst (trong 1 giây) và ngưỡng phút
        burst_count = sum(1 for t in history if now - t <= 1.0)
        if burst_count > DDOS_BURST_PER_SEC or len(history) > DDOS_LIMIT_PER_MINUTE:
            ip_blocked_until[ip] = now + 180  # Khóa 3 phút
            return jsonify({
                "error": "Lưu lượng truy cập quá tải. Chế độ Anti-DDoS đã kích hoạt bảo vệ.",
                "status": 429
            }), 429

        ip_request_history[ip].append(now)

    # Cổng Xác Thực Danh Tính Anti-Bot trước khi vào Web
    if not session.get("bot_verified") and request.endpoint not in ("verify_gate", "api_verify_challenge"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Vui lòng xác thực danh tính tại cổng bảo mật"}), 403
        return redirect(url_for("verify_gate"))


# ============================================================
# DATABASE SETUP
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
# ZALO PSYCHOLOGICAL ICONS
# ============================================================
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
    "😹", "😈", "🔥", "😤", "🤮", "🤢", "🐒", "🎄", "❄️", "🎁"
]


def get_icon_hard():
    if random.random() < 0.65:
        return random.choice(ZALO_ICON_HARD)
    return random.choice(ZALO_ICON_UNICODE)


# ============================================================
# BẢNG MÀU CHỮ ZALO CHÍNH THỨC
# ============================================================
ZALO_COLORS = [
    {"id": "red",    "name": "Đỏ Noel",      "hex": "#e8453c"},
    {"id": "green",  "name": "Lục Thông",    "hex": "#00b14f"},
    {"id": "yellow", "name": "Vàng Hoàng Gia","hex": "#f5c500"},
    {"id": "orange", "name": "Cam Rực Rỡ",   "hex": "#ff8c00"},
    {"id": "ocean",  "name": "Xanh Biển",    "hex": "#0091ff"},
    {"id": "blue",   "name": "Xanh Dương",   "hex": "#0068ff"},
    {"id": "purple", "name": "Tím Pha Lê",   "hex": "#a05eff"},
    {"id": "pink",   "name": "Hồng Ngọc Hân","hex": "#ff47a8"},
    {"id": "brown",  "name": "Nâu Gỗ",       "hex": "#a87050"},
    {"id": "black",  "name": "Đen Tối Giản", "hex": "#1a1a1a"},
    {"id": "gray",   "name": "Xám Bạc",      "hex": "#8a8a8a"},
    {"id": "white",  "name": "Trắng Tuyết",  "hex": "#ffffff"},
]

COLOR_IDS = [c["id"] for c in ZALO_COLORS]


# ============================================================
# ANTI-BAN & LOGIC DELAY
# ============================================================
class AntiBan:
    MIN_DELAY = 0.3
    MAX_DELAY = 120.0
    WARMUP_MSGS = 10
    WARMUP_MULT = 1.6
    SESSION_MAX = 35
    SESSION_REST_MIN = 1.2
    SESSION_REST_MAX = 3.0

    @staticmethod
    def compute_risk(ok, fail):
        total = ok + fail
        if total == 0: return 0.0
        base = fail / total
        if fail > 20 and ok < 5: base = min(1.0, base + 0.18)
        if ok > 100 and base < 0.05: base = max(0.0, base - 0.02)
        return min(1.0, base)

    @staticmethod
    def compute_delay(user_delay, risk, is_warmup=False):
        d = max(AntiBan.MIN_DELAY, user_delay)
        if risk > 0.85: d = max(d, 16.0)
        elif risk > 0.7: d = max(d, 9.0)
        elif risk > 0.5: d = max(d, 4.5)
        elif risk > 0.3: d = max(d, 2.0)
        if is_warmup: d *= AntiBan.WARMUP_MULT
        d = d * random.uniform(0.9, 1.1)
        return max(AntiBan.MIN_DELAY, min(AntiBan.MAX_DELAY, d))

    @staticmethod
    def pick_color(color_mode, fixed_color, idx=0):
        if color_mode == 'none': return None
        if color_mode == 'random': return random.choice(COLOR_IDS)
        if color_mode == 'fixed':
            return fixed_color if fixed_color in COLOR_IDS else random.choice(COLOR_IDS)
        if color_mode == 'cycle': return COLOR_IDS[idx % len(COLOR_IDS)]
        return None

    @staticmethod
    def append_icons(text, count):
        if count <= 0: return text
        icons = [get_icon_hard() for _ in range(count)]
        return text + " " + " ".join(icons)

    @staticmethod
    def apply_formatting(text, make_bold=True):
        if not text: return text
        if make_bold:
            # Bọc dòng bằng markdown in đậm của Zalo nếu chưa có
            lines = text.split("\n")
            styled = []
            for ln in lines:
                ln_s = ln.strip()
                if ln_s and not (ln_s.startswith("**") and ln_s.endswith("**")):
                    styled.append(f"**{ln_s}**")
                else:
                    styled.append(ln)
            return "\n".join(styled)
        return text


# ============================================================
# ZALO PROTOCOL CLIENT
# ============================================================
class Zalo:
    def __init__(self, imei, cookies):
        self.imei = imei
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/122.0.0.0 Safari/537.36"),
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
            timeout=20,
        )
        d = r.json()
        ud = d.get("data")
        if not isinstance(ud, dict):
            raise Exception("Cookie/IMEI không hợp lệ")
        self.uid = ud.get("send2me_id")
        self.secret_key = ud.get("zpw_enk")
        try:
            self.display_name = ud.get("displayName") or ud.get("zaloName")
            self.zalo_name = ud.get("zaloName")
            self.username = ud.get("username")
        except Exception:
            pass
        if not self.secret_key:
            raise Exception("Không thể trích xuất secret key")
        try:
            self._fetch_own_profile()
        except Exception:
            pass

    def _fetch_own_profile(self):
        if not self.uid: return
        try:
            enc = self._enc({"friendId": self.uid})
            r = self.s.post(
                "https://tt-profile-wpa.chat.zalo.me/api/social/profile/header",
                params={"zpw_ver": 645, "zpw_type": 30},
                data={"params": enc}, timeout=12,
            )
            j = r.json()
            if j.get("data"):
                dec = self._dec(j["data"])
                p = json.loads(dec).get("data", {})
                self.display_name = p.get("displayName") or self.display_name
                self.zalo_name = p.get("zaloName") or self.zalo_name
                self.username = p.get("username") or self.username
        except Exception:
            pass

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
            params={"zpw_ver": 645, "zpw_type": 30}, timeout=20,
        )
        dec = self._dec(r.json()["data"])
        grid = json.loads(dec).get("data", {}).get("gridVerMap", {})
        out = []
        for gid in grid:
            try:
                info = self.group_info(gid)
                out.append({"id": gid, "name": info["name"],
                            "type": "group",
                            "members": info["totalMember"]})
            except Exception:
                continue
        return out

    def group_info(self, gid):
        enc = self._enc({"gridVerMap": json.dumps({str(gid): 0})})
        r = self.s.post(
            "https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2",
            params={"zpw_ver": 645, "zpw_type": 30},
            data={"params": enc}, timeout=20,
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
                data={"params": enc}, timeout=20,
            )
            dec = self._dec(r.json()["data"])
            d = json.loads(dec).get("data", [])
            users = d if isinstance(d, list) else d.get("users", [])
            return [{"id": u.get("userId"),
                     "name": u.get("displayName") or u.get("zaloName") or f"Bạn_{u.get('userId')[-6:]}",
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
        mem_list = info.get("memVerList", [])

        uids = [m.split("_")[0] for m in mem_list]
        if not uids: return []

        members = []
        try:
            payload = {"friendId": uids}
            enc2 = self._enc(payload)
            r2 = self.s.post(
                "https://tt-group-wpa.chat.zalo.me/api/group/getuserinfo",
                params={"zpw_ver": 645, "zpw_type": 30},
                data={"params": enc2}, timeout=25,
            )
            dec2 = self._dec(r2.json()["data"])
            profiles = json.loads(dec2).get("data", {}).get("profiles", {})
            for uid in uids:
                p = profiles.get(uid, {})
                dn = p.get("displayName") or ""
                zn = p.get("zaloName") or ""
                un = p.get("username") or ""
                final_name = dn or zn or un or f"Thành viên ({uid[-6:]})"
                members.append({
                    "id": uid, "name": final_name,
                    "display_name": dn, "zalo_name": zn, "username": un,
                })
        except Exception:
            for uid in uids:
                members.append({
                    "id": uid, "name": f"Thành viên ({uid[-6:]})",
                    "display_name": "", "zalo_name": "", "username": "",
                })
        return members

    def build_mention_payload(self, text, mentions, tag_all=False):
        final = text
        m_arr = []
        if tag_all:
            tag_str = "@All"
            pos = len(final) + (1 if final else 0)
            final = (final + " " + tag_str) if final else tag_str
            m_arr.append({"uid": "0", "pos": pos, "len": len(tag_str), "type": 1})
            return final, m_arr

        if not mentions:
            return text, []

        for m in mentions:
            name = str(m.get("name", "")).strip()
            uid = str(m.get("uid") or m.get("id") or "").strip()
            if not name or not uid: continue
            tag_str = "@" + name
            pos = len(final) + (1 if final else 0)
            final = (final + " " + tag_str) if final else tag_str
            m_arr.append({"uid": str(uid), "pos": pos,
                          "len": len(tag_str), "type": 0})
        return final, m_arr

    def send(self, msg, thread_id, color=None, is_group=True, mentions=None, tag_all=False):
        url = ("https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
               if is_group
               else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms")

        final_msg = msg
        m_arr = []
        if mentions or tag_all:
            final_msg, m_arr = self.build_mention_payload(msg, mentions, tag_all=tag_all)

        final_msg = final_msg.replace("\r\n", "\n").replace("\r", "\n")

        pl = {
            "message": final_msg,
            "clientId": str(int(time.time() * 1000)) + str(random.randint(100, 999)),
            "imei": self.imei,
        }
        if m_arr:
            pl["mentions"] = json.dumps(m_arr, ensure_ascii=False)
        if color:
            pl["msgColor"] = color
        if is_group:
            pl["visibility"] = 0
            pl["grid"] = str(thread_id)
        else:
            pl["toid"] = str(thread_id)
        enc = self._enc(pl)
        return self.s.post(url, params={"zpw_ver": 645, "zpw_type": 30},
                           data={"params": enc}, timeout=20)

    def mark_read(self, thread_id, is_group=True):
        try:
            if is_group:
                url = "https://tt-group-wpa.chat.zalo.me/api/group/seentmsg"
                pl = {"grid": str(thread_id), "imei": self.imei}
            else:
                url = "https://tt-chat1-wpa.chat.zalo.me/api/message/seentmsg"
                pl = {"toid": str(thread_id), "imei": self.imei}
            enc = self._enc(pl)
            self.s.post(url, params={"zpw_ver": 645, "zpw_type": 30},
                        data={"params": enc}, timeout=8)
        except Exception:
            pass


# ============================================================
# PARSE FILE
# ============================================================
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
    except Exception as e:
        print("[FILE ERR] " + str(e))
    return blocks


# ============================================================
# MULTI-ACCOUNT CONCURRENCY WORKER
# ============================================================
def update_stats(aid, ok):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    if not row:
        conn.close(); return
    ok_c = row["ok_count"] + (1 if ok else 0)
    fail_c = row["fail_count"] + (0 if ok else 1)
    sent = row["total_sent"] + (1 if ok else 0)
    risk = AntiBan.compute_risk(ok_c, fail_c)
    enabled = row["enabled"]
    if fail_c >= 50 and ok_c / max(fail_c, 1) < 0.05:
        enabled = 0
    conn.execute("""
        UPDATE accounts SET ok_count = ?, fail_count = ?, risk = ?,
            total_sent = ?, enabled = ?, last_used = ?
        WHERE id = ?
    """, (ok_c, fail_c, risk, sent, enabled, time.time(), aid))
    conn.commit(); conn.close()


def single_acc_runner(acc_data, targets, blocks, delay, use_emoji, icon_count,
                      tag_users, tag_all, make_bold, mode, color_mode, fixed_color,
                      human_mode, stop_event, global_counter, task_lock):
    aid = acc_data["id"]
    imei = acc_data["imei"]
    cookies = json.loads(acc_data["cookies"])

    block_idx = 0
    target_idx = 0
    sent_in_session = 0
    color_idx = random.randint(0, 11)

    try:
        z = Zalo(imei, cookies)
    except Exception:
        update_stats(aid, False)
        return

    while not stop_event.is_set():
        if sent_in_session >= AntiBan.SESSION_MAX:
            rest = random.uniform(AntiBan.SESSION_REST_MIN, AntiBan.SESSION_REST_MAX)
            time.sleep(rest)
            sent_in_session = 0

        target = targets[target_idx % len(targets)]
        target_idx += 1
        is_group = (target.get("type") == "group")
        target_id = target.get("id")

        raw_block = blocks[block_idx % len(blocks)]
        block_idx += 1

        color = AntiBan.pick_color(color_mode, fixed_color, color_idx)
        color_idx += 1

        try:
            if human_mode:
                z.mark_read(target_id, is_group=is_group)

            if mode == "treo_ngon":
                # N dòng trong 1 tin duy nhất, giữ nguyên \n
                full_text = raw_block.replace("\r\n", "\n").replace("\r", "\n")
                if make_bold:
                    full_text = AntiBan.apply_formatting(full_text, make_bold=True)
                if use_emoji and icon_count > 0:
                    full_text = AntiBan.append_icons(full_text, icon_count)

                r = z.send(full_text, target_id, color=color, is_group=is_group,
                           mentions=tag_users, tag_all=tag_all)
                ok = bool(r and r.status_code == 200)
                update_stats(aid, ok)
                with task_lock:
                    global_counter["sent"] += 1
                sent_in_session += 1

            elif mode == "treo_nhay":
                # N dòng -> N tin riêng đánh số
                lines = [ln for ln in raw_block.split("\n") if ln.strip()]
                for mi, ln in enumerate(lines, 1):
                    if stop_event.is_set(): break
                    t_msg = f"{mi}. {ln}"
                    if make_bold:
                        t_msg = AntiBan.apply_formatting(t_msg, make_bold=True)
                    if use_emoji and icon_count > 0:
                        t_msg = AntiBan.append_icons(t_msg, icon_count)

                    cur_color = AntiBan.pick_color(color_mode, fixed_color, color_idx)
                    color_idx += 1

                    r = z.send(t_msg, target_id, color=cur_color, is_group=is_group,
                               mentions=(tag_users if mi == 1 else None),
                               tag_all=(tag_all if mi == 1 else False))
                    ok = bool(r and r.status_code == 200)
                    update_stats(aid, ok)
                    with task_lock:
                        global_counter["sent"] += 1
                    sent_in_session += 1
                    time.sleep(0.18 if not human_mode else random.uniform(0.3, 0.6))
            else:
                # Siêu nhanh
                text = raw_block
                if make_bold:
                    text = AntiBan.apply_formatting(text, make_bold=True)
                if use_emoji and icon_count > 0:
                    text = AntiBan.append_icons(text, icon_count)

                r = z.send(text, target_id, color=color, is_group=is_group,
                           mentions=tag_users, tag_all=tag_all)
                ok = bool(r and r.status_code == 200)
                update_stats(aid, ok)
                with task_lock:
                    global_counter["sent"] += 1
                sent_in_session += 1

        except Exception:
            update_stats(aid, False)

        risk = acc_data.get("risk", 0.0) or 0.0
        actual_delay = AntiBan.compute_delay(delay, risk)
        time.sleep(actual_delay)


def master_task_controller(tid, targets, blocks, delay, use_emoji, icon_count,
                           tag_users, tag_all, make_bold, mode, color_mode, fixed_color,
                           human_mode, multi_acc, stop_event):
    conn = db()
    accounts = conn.execute("SELECT * FROM accounts WHERE enabled = 1 AND risk < 0.85").fetchall()
    conn.close()

    if not accounts:
        return

    global_counter = {"sent": 0}
    task_lock = threading.Lock()
    sub_threads = []

    if multi_acc:
        # Chạy đồng thời tất cả các tài khoản song song!
        for acc in accounts:
            t = threading.Thread(
                target=single_acc_runner,
                args=(dict(acc), targets, blocks, delay, use_emoji, icon_count,
                      tag_users, tag_all, make_bold, mode, color_mode, fixed_color,
                      human_mode, stop_event, global_counter, task_lock),
                daemon=True
            )
            sub_threads.append(t)
            t.start()
    else:
        # Chế độ xoay vòng 1 thread
        t = threading.Thread(
            target=single_acc_runner,
            args=(dict(accounts[0]), targets, blocks, delay, use_emoji, icon_count,
                  tag_users, tag_all, make_bold, mode, color_mode, fixed_color,
                  human_mode, stop_event, global_counter, task_lock),
            daemon=True
        )
        sub_threads.append(t)
        t.start()

    while not stop_event.is_set():
        time.sleep(1)

    for st in sub_threads:
        st.join(timeout=0.2)

    conn = db()
    conn.execute("UPDATE tasks SET status = 'stopped', stats = ? WHERE id = ?",
                 (json.dumps({"sent": global_counter["sent"]}), tid))
    conn.commit()
    conn.close()
    ACTIVE_TASKS.pop(tid, None)


# ============================================================
# CỔNG BẢO MẬT: VERIFY GATE & LOGIN
# ============================================================
HTML_VERIFY_GATE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Bảo Mật ALB Shield — Cổng Xác Thực Anti-DDoS</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: 'Inter', sans-serif;
  background: #fdfbfb;
  color: #0f172a;
  display: flex; align-items: center; justify-content: center;
  min-height: 100vh; padding: 20px;
}
.gate-card {
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(226, 232, 240, 0.9);
  box-shadow: 0 25px 60px rgba(15, 23, 42, 0.08);
  border-radius: 24px; padding: 36px 28px;
  max-width: 420px; width: 100%; text-align: center;
}
.gate-icon {
  width: 76px; height: 76px; margin: 0 auto 16px;
  background: linear-gradient(135deg, #ff007f, #ff3366);
  border-radius: 50%; display: flex; align-items: center; justify-content: center;
  box-shadow: 0 10px 25px rgba(255, 0, 127, 0.3); color: #fff;
}
.gate-icon svg { width: 38px; height: 38px; }
h1 { font-family: 'Orbitron', sans-serif; font-size: 19px; font-weight: 900; color: #0f172a; margin-bottom: 6px; }
p { font-size: 12px; color: #64748b; margin-bottom: 24px; line-height: 1.5; }
.btn-verify {
  width: 100%; padding: 15px; background: linear-gradient(135deg, #ff007f, #ff3366);
  color: #fff; font-weight: 800; font-size: 13px; text-transform: uppercase;
  letter-spacing: 0.8px; border: none; border-radius: 14px; cursor: pointer;
  box-shadow: 0 8px 24px rgba(255, 0, 127, 0.35); transition: all .25s ease;
}
.btn-verify:hover { transform: translateY(-2px); filter: brightness(1.05); }
.shield-info { margin-top: 20px; font-size: 10px; color: #94a3b8; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; }
</style>
</head>
<body>
<div class="gate-card">
  <div class="gate-icon">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
  </div>
  <h1>ALB ANTI-DDOS SHIELD</h1>
  <p>Hệ thống tự động phát hiện và ngăn chặn truy vấn ảo. Vui lòng bấm xác thực danh tính để vào trang làm việc.</p>
  <button type="button" class="btn-verify" onclick="doVerify()">🛡️ Tôi không phải là Robot (Tiếp tục)</button>
  <div class="shield-info">Protected by <b>I Love Ngọc Hân Security Engine</b></div>
</div>
<script>
async function doVerify(){
  var r = await fetch('/api/verify_challenge', { method: 'POST' }).then(x => x.json());
  if(r.ok){
    window.location.href = '/login';
  }
}
</script>
</body>
</html>
"""

# ============================================================
# LOGO NOEL HOÀNG GIA: I LOVE NGỌC HÂN (LUXURY NOEL SVG)
# ============================================================
LOGO_NOEL_SVG = """<svg viewBox="0 0 160 160" xmlns="http://www.w3.org/2000/svg">
<defs>
  <linearGradient id="noelHeart" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#ff0055"/>
    <stop offset="50%" stop-color="#e8453c"/>
    <stop offset="100%" stop-color="#00b14f"/>
  </linearGradient>
  <linearGradient id="noelGold" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#ffe259"/>
    <stop offset="100%" stop-color="#ffa751"/>
  </linearGradient>
  <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
    <feGaussianBlur stdDeviation="3" result="blur"/>
    <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>
<circle cx="80" cy="80" r="74" fill="none" stroke="url(#noelGold)" stroke-width="1.8" stroke-dasharray="4 6" opacity="0.8"/>
<!-- Trái tim Pha Lê -->
<g filter="url(#glow)">
  <path d="M80 118 C80 118 40 94 40 64 C40 46 54 36 68 44 C75 48 80 54 80 54 C80 54 85 48 92 44 C106 36 120 46 120 64 C120 94 80 118 80 118 Z" fill="url(#noelHeart)"/>
</g>
<!-- Nón Noel Nhỏ Xinh Trên Tim -->
<g transform="translate(68, 22) scale(0.65)">
  <polygon points="20,0 0,40 40,40" fill="#e8453c"/>
  <rect x="-4" y="38" width="48" height="12" rx="6" fill="#ffffff"/>
  <circle cx="20" cy="-2" r="7" fill="#ffffff"/>
</g>
<!-- Hoa Tuyết Pha Lê -->
<circle cx="50" cy="55" r="2" fill="#fff"><animate attributeName="opacity" values="0.3;1;0.3" dur="2s" repeatCount="indefinite"/></circle>
<circle cx="110" cy="55" r="2" fill="#fff"><animate attributeName="opacity" values="1;0.3;1" dur="2s" repeatCount="indefinite"/></circle>
<circle cx="80" cy="78" r="2.5" fill="#ffe259"><animate attributeName="opacity" values="0.4;1;0.4" dur="1.5s" repeatCount="indefinite"/></circle>
<!-- Dải Ribbon Hoàng Gia -->
<rect x="18" y="124" width="124" height="26" rx="13" fill="#ffffff" stroke="url(#noelGold)" stroke-width="2"/>
<text x="80" y="141" text-anchor="middle" font-family="'Orbitron', sans-serif" font-weight="900" font-size="9.5" fill="#e8453c" letter-spacing="1">
  I ❤ NGỌC HÂN
</text>
</svg>"""

# ============================================================
# CSS GIAO DIỆN NOEL TRẮNG TINH TẾ & TUYẾT RƠI
# ============================================================
CSS_NOEL = """
:root {
  --bg-main: #f8fafc;
  --bg-card: rgba(255, 255, 255, 0.94);
  --line-1: rgba(226, 232, 240, 0.85);
  --txt-0: #0f172a;
  --txt-1: #1e293b;
  --txt-2: #64748b;
  --txt-3: #94a3b8;
  --noel-red: #e8453c;
  --noel-green: #00b14f;
  --noel-gold: #f59e0b;
  --love-1: #ff007f;
  --grad-noel: linear-gradient(135deg, #e8453c 0%, #ff007f 60%, #00b14f 100%);
  --grad-bar: linear-gradient(90deg, #e8453c, #f59e0b, #00b14f, #0091ff, #ff007f);
  --r-sm: 10px; --r-md: 14px; --r-lg: 20px; --r-xl: 26px;
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
}
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html { touch-action: manipulation; -webkit-text-size-adjust: 100%; }
body {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background-color: var(--bg-main);
  color: var(--txt-1);
  min-height: 100vh;
  padding-bottom: 110px;
  overflow-x: hidden;
  position: relative;
}
/* Canvas Tuyết Rơi 60FPS Tuyệt Đẹp */
#snow-canvas {
  position: fixed; inset: 0; pointer-events: none; z-index: 99; width: 100%; height: 100%;
}
/* Hình Nền Mờ Chiếc Váy Sang Trọng */
body::before {
  content: ''; position: fixed; inset: 0;
  background-image: url('/static/bg.jpg');
  background-size: cover; background-position: center;
  opacity: 0.18; filter: blur(3px); pointer-events: none; z-index: -1;
}

/* HEADER TRẮNG NOEL */
.header {
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(25px) saturate(180%);
  -webkit-backdrop-filter: blur(25px) saturate(180%);
  padding: 10px 16px;
  padding-top: calc(10px + env(safe-area-inset-top, 0px));
  border-bottom: 1px solid var(--line-1);
  position: sticky; top:0; z-index: 100;
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.04);
}
.header::after { content:''; position:absolute; left:0; right:0; bottom:0; height:2px; background:var(--grad-bar); }
.header-inner { max-width: 1050px; margin: 0 auto; display: flex; align-items: center; gap: 12px; }

.logo-wrap {
  width: 48px; height: 48px; border-radius: 50%;
  position: relative; padding: 2px;
  background: var(--grad-noel);
  box-shadow: 0 8px 25px rgba(232, 69, 60, 0.3);
  flex-shrink: 0; display: flex; align-items: center; justify-content: center;
}
.logo-wrap svg { width: 100%; height: 100%; }
.header-info { flex: 1; min-width: 0; }
.header-info h1 {
  font-family: 'Orbitron', sans-serif; font-size: 14.5px; font-weight: 900;
  background: var(--grad-noel); -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; letter-spacing: 0.5px;
}
.header-info p { font-size: 9px; color: var(--txt-2); font-weight: 700; text-transform: uppercase; margin-top: 2px; }
.logout-btn {
  background: #ffffff; color: var(--txt-1); border: 1px solid var(--line-1);
  padding: 7px 12px; border-radius: 12px; font-size: 11px; font-weight: 800; cursor: pointer;
  transition: all .25s var(--ease-spring); display: inline-flex; align-items: center; gap: 5px;
}
.logout-btn:hover { background: #fef2f2; border-color: #ef4444; color: #dc2626; transform: translateY(-2px); }

/* CONTAINERS */
.container { max-width: 1050px; margin: 0 auto; padding: 14px; position: relative; z-index: 10; }
.panel { display: none; animation: panelFadeIn .3s ease both; }
.panel.active { display: block; }
@keyframes panelFadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

/* CARDS */
.card {
  position: relative; background: var(--bg-card);
  backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
  padding: 18px; border-radius: var(--r-lg);
  border: 1px solid var(--line-1); box-shadow: 0 10px 30px rgba(15, 23, 42, 0.05);
  margin-bottom: 14px; transition: all .3s var(--ease-spring);
}
.card:hover { border-color: rgba(232, 69, 60, 0.35); box-shadow: 0 12px 35px rgba(232, 69, 60, 0.08); }
.card h2 {
  font-size: 12px; font-weight: 900; letter-spacing: .5px; margin-bottom: 14px;
  display: flex; align-items: center; gap: 9px; color: var(--txt-0); text-transform: uppercase;
}
.card h2 .badge-icon {
  width: 26px; height: 26px; border-radius: 8px; background: var(--grad-noel);
  display: flex; align-items: center; justify-content: center; font-size: 12px; color: #fff;
}

/* FORMS */
.form-group { margin-bottom: 12px; }
.form-group label { display: block; margin-bottom: 5px; font-size: 9.5px; font-weight: 800; color: var(--txt-2); text-transform: uppercase; letter-spacing: .8px; }
.form-group input, .form-group textarea, .form-group select {
  width: 100%; padding: 12px 14px; border: 1.5px solid var(--line-1); border-radius: 12px;
  font-size: 13px; font-weight: 500; background: #ffffff; color: var(--txt-0);
  transition: all .25s var(--ease-spring);
}
.form-group input:focus, .form-group textarea:focus, .form-group select:focus {
  outline: none; border-color: var(--noel-red); box-shadow: 0 0 0 4px rgba(232, 69, 60, 0.12);
}
.form-group textarea { min-height: 90px; resize: vertical; font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.5; }

/* NÚT BẤM SPRING BOUNCE */
.btn-rect {
  padding: 12px 18px; border: none; border-radius: 12px; cursor: pointer;
  font-size: 11.5px; font-weight: 900; letter-spacing: .6px; color: #fff; text-transform: uppercase;
  display: inline-flex; align-items: center; gap: 7px; transition: all .25s var(--ease-spring);
}
.btn-rect:hover { transform: translateY(-2px); filter: brightness(1.05); }
.btn-rect:active { transform: translateY(0) scale(0.96); }
.btn-rect.primary { background: var(--grad-noel); box-shadow: 0 8px 24px rgba(232, 69, 60, 0.3); }
.btn-rect.full { width: 100%; justify-content: center; }

.btn-circle {
  width: 46px; height: 46px; border-radius: 50%; border: none; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center; color: #fff;
  transition: all .25s var(--ease-spring); margin: 3px;
}
.btn-circle svg { width: 19px; height: 19px; }
.btn-circle:hover { transform: translateY(-3px) scale(1.08); }
.btn-circle:active { transform: translateY(0) scale(0.94); }
.btn-circle.primary { background: var(--grad-noel); box-shadow: 0 6px 18px rgba(232, 69, 60, 0.35); }
.btn-circle.danger { background: linear-gradient(135deg, #ef4444, #dc2626); box-shadow: 0 6px 18px rgba(239, 68, 68, 0.3); }
.btn-circle.success { background: linear-gradient(135deg, #00b14f, #059669); box-shadow: 0 6px 18px rgba(0, 177, 79, 0.3); }
.btn-circle.small { width: 32px; height: 32px; }
.btn-circle.small svg { width: 14px; height: 14px; }
.btn-circle.big { width: 62px; height: 62px; }
.btn-circle.big svg { width: 25px; height: 25px; }

/* CHIPS & TOGGLES */
.chip-group { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px; }
.chip {
  padding: 7px 13px; background: #ffffff; color: var(--txt-2); border-radius: 20px;
  font-size: 10.5px; font-weight: 800; cursor: pointer; border: 1px solid var(--line-1);
  transition: all .2s var(--ease-spring);
}
.chip:hover { border-color: var(--noel-red); color: var(--noel-red); }
.chip.active { background: var(--grad-noel); color: #fff; border-color: transparent; box-shadow: 0 4px 14px rgba(232, 69, 60, 0.3); transform: translateY(-1px); }

.toggle-group { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 7px; margin-bottom: 11px; }
.toggle {
  padding: 11px 9px; border: 1px solid var(--line-1); border-radius: var(--r-md);
  cursor: pointer; text-align: center; font-weight: 800; font-size: 10.5px;
  background: #ffffff; color: var(--txt-2); text-transform: uppercase;
  transition: all .25s var(--ease-spring);
}
.toggle.active { background: var(--grad-noel); color: #fff; border-color: transparent; box-shadow: 0 4px 14px rgba(232, 69, 60, 0.28); transform: translateY(-1px); }

.mode-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin-top: 6px; }
.mode-card {
  padding: 12px 6px; border-radius: 12px; cursor: pointer; background: #ffffff;
  border: 1.5px solid var(--line-1); text-align: center; transition: all .25s var(--ease-spring);
}
.mode-card.active { background: var(--grad-noel); border-color: transparent; color: #fff; box-shadow: 0 6px 20px rgba(232, 69, 60, 0.3); transform: translateY(-2px); }
.mode-card .mc-title { font-size: 10.5px; font-weight: 900; text-transform: uppercase; margin-bottom: 2px; }
.mode-card .mc-desc { font-size: 8.5px; opacity: 0.85; }

/* LIST ITEMS */
.box-list { max-height: 320px; overflow-y: auto; border: 1px solid var(--line-1); border-radius: var(--r-md); padding: 7px; background: #ffffff; }
.box-item {
  padding: 10px; border-radius: 10px; background: #f8fafc; margin-bottom: 5px;
  cursor: pointer; border: 1px solid var(--line-1); display: flex; align-items: center; gap: 9px;
  transition: all .2s var(--ease-spring);
}
.box-item:hover { border-color: var(--noel-red); transform: translateX(2px); background: #fff; }
.box-item.selected { border-color: var(--noel-red); background: #fff5f5; }
.box-item .check {
  width: 18px; height: 18px; border: 2px solid var(--txt-3); border-radius: 5px;
  display: flex; align-items: center; justify-content: center; font-size: 10px; color: transparent; font-weight: 900;
}
.box-item.selected .check { background: var(--noel-red); border-color: var(--noel-red); color: #fff; }
.box-item .info { flex: 1; min-width: 0; }
.box-item .name { font-weight: 700; font-size: 12px; color: var(--txt-0); text-overflow: ellipsis; white-space: nowrap; overflow: hidden; }
.box-item .meta { font-size: 9.5px; color: var(--txt-3); font-family: 'JetBrains Mono', monospace; margin-top: 2px; }

/* STATS */
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(90px, 1fr)); gap: 8px; margin-bottom: 12px; }
.stat { background: #ffffff; padding: 12px 10px; border-radius: var(--r-md); border: 1px solid var(--line-1); position: relative; overflow: hidden; }
.stat::before { content:''; position:absolute; top:0; left:0; right:0; height:2px; background:var(--grad-bar); }
.stat .label { font-size: 8.5px; color: var(--txt-2); margin-bottom: 4px; text-transform: uppercase; font-weight: 800; }
.stat .value { font-size: 19px; font-weight: 900; color: var(--txt-0); font-family: 'Orbitron', sans-serif; }

/* TABLE */
.table-wrap { overflow-x: auto; border-radius: var(--r-md); border: 1px solid var(--line-1); background: #ffffff; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { padding: 9px 8px; text-align: left; font-size: 11px; border-bottom: 1px solid rgba(226, 232, 240, 0.6); white-space: nowrap; }
.table th { background: #f8fafc; font-weight: 800; color: var(--txt-2); text-transform: uppercase; font-size: 9px; }
.badge { display: inline-flex; align-items: center; gap: 4px; padding: 3px 7px; border-radius: 20px; font-size: 9px; font-weight: 800; }
.badge-ok { background: #d1fae5; color: #065f46; }
.badge-err { background: #fee2e2; color: #991b1b; }

/* BOTTOM FLOATING DOCK */
.bottom-dock {
  position: fixed; bottom: 14px; left: 50%; transform: translateX(-50%);
  width: calc(100% - 24px); max-width: 520px;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(28px) saturate(200%);
  border: 1.5px solid rgba(232, 69, 60, 0.25);
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.12), 0 0 20px rgba(232, 69, 60, 0.15);
  border-radius: var(--r-xl); display: grid; grid-template-columns: repeat(4, 1fr);
  padding: 6px; gap: 5px; z-index: 999;
}
.bottom-dock .tab {
  padding: 9px 4px; border-radius: 16px; cursor: pointer; font-size: 9.5px; font-weight: 800;
  text-align: center; color: var(--txt-2); display: flex; flex-direction: column; align-items: center;
  gap: 3px; background: transparent; border: none; transition: all .3s var(--ease-spring); text-transform: uppercase;
}
.bottom-dock .tab.active { background: var(--grad-noel); color: #fff; box-shadow: 0 5px 16px rgba(232, 69, 60, 0.35); transform: translateY(-2px); }

/* TOAST THÔNG MINH */
#toast-stack {
  position: fixed; top: calc(14px + env(safe-area-inset-top, 0px)); right: 12px;
  z-index: 99999; max-width: 350px; width: calc(100% - 24px); pointer-events: none;
}
.toast {
  pointer-events: auto; position: relative; overflow: hidden;
  padding: 12px 14px 12px 50px; border-radius: 14px;
  background: rgba(255, 255, 255, 0.98); backdrop-filter: blur(20px);
  border: 1px solid var(--line-1); box-shadow: 0 12px 35px rgba(15, 23, 42, 0.12);
  display: flex; flex-direction: column; gap: 2px;
  animation: toastIn .28s var(--ease-spring) both;
}
.toast.swipe-out { animation: toastOut .22s ease-out forwards; }
@keyframes toastIn { from { opacity: 0; transform: translateY(-25px); } to { opacity: 1; transform: translateY(0); } }
@keyframes toastOut { to { opacity: 0; transform: translateY(-50px); } }
.toast::before { content:''; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--grad-noel); }
.toast .t-icon {
  position: absolute; left: 11px; top: 50%; transform: translateY(-50%);
  width: 30px; height: 30px; border-radius: 9px; display: flex; align-items: center;
  justify-content: center; color: #fff; background: var(--grad-noel);
}
.toast .t-title { font-size: 11px; font-weight: 900; color: var(--txt-0); text-transform: uppercase; }
.toast .t-msg { font-size: 10.5px; font-weight: 600; color: var(--txt-2); }
"""


# ============================================================
# TEMPLATE LOGIN CHỐNG BRUTE FORCE
# ============================================================
HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>I Love Ngọc Hân — Noel Login</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_NOEL + """
body { display:flex; align-items:center; justify-content:center; min-height:100vh; padding:18px; }
.login-card {
  position: relative; background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(30px); padding: 38px 26px; border-radius: var(--r-xl);
  border: 1px solid var(--line-1); box-shadow: 0 20px 60px rgba(15, 23, 42, 0.1);
  width: 100%; max-width: 390px; text-align: center;
}
.logo-box { width: 90px; height: 90px; margin: 0 auto 14px; }
h1 { font-family: 'Orbitron', sans-serif; font-size: 19px; font-weight: 900; background: var(--grad-noel); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
p.sub { font-size: 10.5px; color: var(--txt-2); font-weight: 700; margin-bottom: 22px; text-transform: uppercase; }
.error { background: #fef2f2; color: #b91c1c; padding: 11px; border-radius: 12px; margin-bottom: 14px; font-size: 11.5px; font-weight: 700; border-left: 3px solid #ef4444; text-align: left; }
</style>
</head>
<body>
<canvas id="snow-canvas"></canvas>
<div class="login-card">
  <div class="logo-box">""" + LOGO_NOEL_SVG + """</div>
  <h1>I LOVE NGỌC HÂN</h1>
  <p class="sub">Noel White-Glass Edition • v35.0</p>
  {% if error %}<div class="error">⚠️ {{ error }}</div>{% endif %}
  <form method="POST">
    <div class="form-group" style="text-align:left;">
      <input type="password" name="password" placeholder="Nhập mã bí mật..." required autofocus>
    </div>
    <button type="submit" class="btn-rect primary full" style="padding:15px;">🎄 Đăng nhập hệ thống</button>
  </form>
</div>
<script>
// Tuyết Rơi Noel 60FPS
var c = document.getElementById("snow-canvas");
var ctx = c.getContext("2d");
var W = window.innerWidth, H = window.innerHeight;
c.width = W; c.height = H;
var flakes = Array.from({length: 45}, () => ({
  x: Math.random()*W, y: Math.random()*H, r: Math.random()*3 + 1, d: Math.random()*1 + 0.5
}));
function drawSnow(){
  ctx.clearRect(0,0,W,H);
  ctx.fillStyle = "rgba(232, 69, 60, 0.4)";
  flakes.forEach(f => {
    ctx.beginPath(); ctx.arc(f.x, f.y, f.r, 0, Math.PI*2); ctx.fill();
    f.y += f.d; f.x += Math.sin(f.y/20);
    if(f.y > H){ f.y = 0; f.x = Math.random()*W; }
  });
  requestAnimationFrame(drawSnow);
}
drawSnow();
</script>
</body>
</html>
"""


# ============================================================
# TEMPLATE DASHBOARD NOEL CHÍNH
# ============================================================
HTML_INDEX = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>I Love Ngọc Hân — Noel Royal Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_NOEL + """
</style>
</head>
<body>
<canvas id="snow-canvas"></canvas>

<!-- TOP HEADER -->
<div class="header">
  <div class="header-inner">
    <div class="logo-wrap">""" + LOGO_NOEL_SVG + """</div>
    <div class="header-info">
      <h1>I LOVE NGỌC HÂN ❄️</h1>
      <p>Noel Edition • Multi-Thread Concurrency Active</p>
    </div>
    <button class="logout-btn" onclick="location.href='/logout'">
      <span>Thoát</span>
      <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
    </button>
  </div>
</div>

<div id="toast-stack"></div>

<!-- NỘI DUNG CHÍNH -->
<div class="container">

  <!-- TAB 1: ACCOUNTS -->
  <div class="panel active" id="panel-accounts">
    <div class="card">
      <h2><span class="badge-icon">🎅</span> Thêm tài khoản Zalo</h2>
      <div class="form-group"><label>Tên gợi nhớ</label><input id="add-label" placeholder="acc_noel_1"></div>
      <div class="form-group"><label>IMEI thiết bị</label><input id="add-imei" placeholder="000000000000000"></div>
      <div class="form-group"><label>Cookie JSON</label><textarea id="add-cookies" placeholder='{"zpw_sek":"...","zpw_ver":"645","zpw_type":"30"}'></textarea></div>
      <button type="button" class="btn-rect primary full" onclick="addAccount()">💾 Lưu tài khoản Zalo</button>
    </div>

    <div class="card">
      <h2><span class="badge-icon">≡</span> Danh sách tài khoản</h2>
      <div class="stat-grid">
        <div class="stat"><div class="label">Tổng Acc</div><div class="value" id="stat-total">0</div></div>
        <div class="stat"><div class="label">Hoạt động</div><div class="value" id="stat-active">0</div></div>
        <div class="stat"><div class="label">Đã gửi</div><div class="value" id="stat-sent">0</div></div>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>ID</th><th>Gợi nhớ</th><th>Tên Thật Zalo</th><th>UID</th><th>OK/Lỗi</th><th>Risk</th><th>Thao tác</th></tr></thead>
          <tbody id="accounts-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 2: BOX CHAT -->
  <div class="panel" id="panel-boxes">
    <div class="card">
      <h2><span class="badge-icon">🎁</span> Quản lý Box & Hội Thoại</h2>
      <div class="form-group"><label>Chọn tài khoản để nạp Box</label><select id="load-acc-select"><option value="">-- Chọn tài khoản --</option></select></div>
      <div style="text-align:center; margin: 10px 0;">
        <button type="button" class="btn-circle primary" onclick="loadBoxes()" title="Tải Box"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg></button>
        <button type="button" class="btn-circle success" onclick="selectAllBoxes()" title="Chọn hết"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><polyline points="20 6 9 17 4 12"/></svg></button>
        <button type="button" class="btn-circle danger" onclick="clearAllBoxes()" title="Bỏ chọn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
      </div>
      <div style="margin-top:10px;">
        <div style="display:flex; justify-content:space-between; margin-bottom:5px; font-size:10px;">
          <b style="color:var(--txt-2); text-transform:uppercase;">Đã chọn: <span id="selected-count" style="color:var(--noel-red); font-weight:900;">0</span></b>
        </div>
        <div class="box-list" id="box-list"><div style="text-align:center; padding:18px; color:var(--txt-3); font-size:11px;">Chưa nạp box</div></div>
      </div>
    </div>
  </div>

  <!-- TAB 3: FILE -->
  <div class="panel" id="panel-files">
    <div class="card">
      <h2><span class="badge-icon">📄</span> Upload File Văn Bản</h2>
      <div class="form-group"><input type="file" id="file-input" accept=".txt" style="padding:7px;"></div>
      <button type="button" class="btn-rect primary full" onclick="uploadFile()">📤 Tải tệp tin lên</button>
      <div class="hint">
        💡 <b>Treo ngôn</b>: Bạn có thể dán 4, 10 hoặc 20 dòng — Hệ thống sẽ gửi trọn vẹn trong <b>1 tin nhắn duy nhất</b> (xuống dòng đầy đủ, không cắt nhỏ).
      </div>
    </div>
    <div class="card">
      <h2><span class="badge-icon">▤</span> Danh sách File lưu trữ</h2>
      <div id="files-list"><div style="text-align:center; padding:18px; color:var(--txt-3); font-size:11px;">Chưa có tệp nào</div></div>
    </div>
  </div>

  <!-- TAB 4: SPAM / ENGINE -->
  <div class="panel" id="panel-spam">
    <div class="card">
      <h2><span class="badge-icon">⚡</span> Cấu hình Bắn Tin Nhắn Siêu Cấp</h2>

      <div class="form-group">
        <label>⚙️ Chế độ gửi tin</label>
        <div class="mode-grid">
          <div class="mode-card active" data-mode="fast">
            <div class="mc-title">⚡ Siêu Nhanh</div>
            <div class="mc-desc">Xoay vòng khối</div>
          </div>
          <div class="mode-card" data-mode="treo_ngon">
            <div class="mc-title">❄️ Treo Ngôn</div>
            <div class="mc-desc">N Dòng / 1 Tin</div>
          </div>
          <div class="mode-card" data-mode="treo_nhay">
            <div class="mc-title">🌀 Treo Nhây</div>
            <div class="mc-desc">Đánh số từng dòng</div>
          </div>
        </div>
        <input type="hidden" id="spam-mode" value="fast">
      </div>

      <div class="form-group">
        <label>Chọn tệp tin nhắn có sẵn</label>
        <select id="spam-file-select"><option value="">-- Chọn file đã tải --</option></select>
      </div>

      <div class="form-group">
        <label>Hoặc Dán trực tiếp nội dung</label>
        <textarea id="spam-messages" placeholder="Dán văn bản nhiều dòng vào đây... Nếu chọn Treo Ngôn, toàn bộ văn bản sẽ được gửi trong đúng 1 tin nhắn duy nhất!"></textarea>
      </div>

      <div class="form-group">
        <label>🎨 Đổi màu chữ Zalo tự động & Nổi bật</label>
        <div class="chip-group" id="color-mode-group">
          <div class="chip" data-cmode="none">Tắt màu</div>
          <div class="chip active" data-cmode="random">Ngẫu nhiên</div>
          <div class="chip" data-cmode="cycle">Xoay vòng</div>
          <div class="chip" data-cmode="fixed">Cố định</div>
        </div>
        <input type="hidden" id="color-mode" value="random">
        <div id="palette-wrap" style="display:none; margin-top:8px;" class="chip-group"></div>
      </div>

      <div class="form-group">
        <label>⏱ Tốc độ Delay (giây)</label>
        <div class="chip-group" id="delay-chips">
          <div class="chip" data-delay="0.3">0.3s</div>
          <div class="chip" data-delay="0.5">0.5s</div>
          <div class="chip active" data-delay="1">1s</div>
          <div class="chip" data-delay="2">2s</div>
          <div class="chip" data-delay="3">3s</div>
          <div class="chip" data-delay="5">5s</div>
        </div>
        <input type="hidden" id="spam-delay" value="1">
      </div>

      <div class="form-group">
        <label>😈 Icon Sát Thương Cuối Câu</label>
        <div class="chip-group" id="icon-chips">
          <div class="chip" data-icon="0">0</div>
          <div class="chip" data-icon="2">2</div>
          <div class="chip active" data-icon="3">3</div>
          <div class="chip" data-icon="5">5</div>
          <div class="chip" data-icon="8">8</div>
        </div>
        <input type="hidden" id="icon-count" value="3">
      </div>

      <!-- TÙY CHỌN NÂNG CAO VIP -->
      <div class="toggle-group">
        <div class="toggle active" id="tg-bold" onclick="tgFlag('bold')">✨ Chữ In Đậm</div>
        <div class="toggle active" id="tg-multi" onclick="tgFlag('multi')">🚀 Đa Acc Cùng Lúc</div>
        <div class="toggle" id="tg-all" onclick="tgFlag('all')">📢 Tag All Box</div>
        <div class="toggle active" id="tg-emoji" onclick="tgFlag('emoji')">😈 Icon</div>
        <div class="toggle active" id="tg-human" onclick="tgFlag('human')">🧑 Giả Người</div>
      </div>

      <div class="form-group">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:11.5px;">
          <input type="checkbox" id="tg-tag" onchange="tgTag()" style="width:auto;">
          Lọc & Tag từng người theo Tên thật Zalo (Không bị tên User)
        </label>
        <div id="tag-wrap" style="display:none; margin-top:8px;">
          <div class="form-group"><select id="member-acc-select"><option value="">-- Chọn Acc quét thành viên --</option></select></div>
          <button type="button" class="btn-rect primary" onclick="loadMembers()">🔄 Quét tên thành viên trong nhóm</button>
          <div class="box-list" id="tag-selector" style="margin-top:8px; max-height:220px; display:none;"></div>
          <input type="hidden" id="tag-selected" value="">
        </div>
      </div>
    </div>

    <div style="text-align:center; margin-bottom:14px;">
      <button type="button" class="btn-circle success big" onclick="startSpam()" title="Kích hoạt"><svg viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3"/></svg></button>
      <button type="button" class="btn-circle danger big" onclick="stopAll()" title="Dừng hết"><svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg></button>
    </div>

    <div class="card">
      <h2><span class="badge-icon">≡</span> Tiến Trình Đang Chạy</h2>
      <div class="table-wrap">
        <table class="table"><thead><tr><th>ID</th><th>Chế độ</th><th>Màu</th><th>Delay</th><th>Trạng thái</th><th>Thao tác</th></tr></thead><tbody id="tasks-tbody"></tbody></table>
      </div>
    </div>
  </div>

</div>

<!-- BOTTOM FLOATING DOCK -->
<div class="bottom-dock">
  <button type="button" class="tab active" data-tab="accounts">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
    <div>Acc</div>
  </button>
  <button type="button" class="tab" data-tab="boxes">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
    <div>Box</div>
  </button>
  <button type="button" class="tab" data-tab="files">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
    <div>File</div>
  </button>
  <button type="button" class="tab" data-tab="spam">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
    <div>Spam</div>
  </button>
</div>

<script>
var flags = { bold: true, multi: true, all: false, emoji: true, human: true };
var selectedBoxes = [];
var selectedTags = [];
var _boxes = [];
var _members = [];
var currentMode = "fast";
var colorMode = "random";
var fixedColor = "red";
var ZALO_COLORS = [];

// ==========================================
// TOAST THÔNG MINH (VUỐT LÊN BIẾN MẤT, KHÔNG CHỒNG, 1.4S)
// ==========================================
var Toast = (function(){
  var stack = null;
  function ensure(){ if(!stack) stack = document.getElementById('toast-stack'); return stack; }
  function show(msg, type, title, duration){
    type = type || 'success';
    duration = duration || 1400;
    var s = ensure();
    if(!s) return;
    s.querySelectorAll('.toast').forEach(el => el.remove());

    var el = document.createElement('div');
    el.className = 'toast ' + type;
    el.innerHTML = '<div class="t-icon">❄️</div>' +
      '<div class="t-title">' + (title || 'Thông báo') + '</div>' +
      '<div class="t-msg">' + msg + '</div>';
    s.appendChild(el);

    var t = setTimeout(dismiss, duration);
    function dismiss(){
      clearTimeout(t);
      el.classList.add('swipe-out');
      el.addEventListener('animationend', () => el.remove(), { once: true });
    }

    var startY = 0;
    el.addEventListener('touchstart', e => { startY = e.touches[0].clientY; }, { passive: true });
    el.addEventListener('touchend', e => {
      if(e.changedTouches[0].clientY - startY < -20) dismiss();
    });
  }
  return {
    success: (m,t,d) => show(m, 'success', t, d),
    error: (m,t,d) => show(m, 'error', t, d || 1800),
    info: (m,t,d) => show(m, 'info', t, d),
    warning: (m,t,d) => show(m, 'warning', t, d)
  };
})();

// TAB DOCK CHUYỂN TRANG
document.querySelectorAll('.bottom-dock .tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.bottom-dock .tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    var p = document.getElementById('panel-' + t.dataset.tab);
    if(p) p.classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    refreshAll();
  });
});

document.querySelectorAll('.mode-card').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('.mode-card').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    currentMode = c.dataset.mode;
    document.getElementById('spam-mode').value = currentMode;
  });
});

document.querySelectorAll('#color-mode-group .chip').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#color-mode-group .chip').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    colorMode = c.dataset.cmode;
    document.getElementById('color-mode').value = colorMode;
    document.getElementById('palette-wrap').style.display = (colorMode === 'fixed') ? 'flex' : 'none';
  });
});

document.querySelectorAll('#delay-chips .chip').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#delay-chips .chip').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    document.getElementById('spam-delay').value = c.dataset.delay;
  });
});

document.querySelectorAll('#icon-chips .chip').forEach(c => {
  c.addEventListener('click', () => {
    document.querySelectorAll('#icon-chips .chip').forEach(x => x.classList.remove('active'));
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
    return { error: 'Lỗi mạng: ' + e.message };
  }
}

async function loadAccounts(){
  var accs = await api('/api/accounts');
  if(!Array.isArray(accs)) accs = [];
  var tb = document.getElementById('accounts-tbody');
  if(!accs.length){
    tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--txt-3);padding:18px;">Chưa có tài khoản</td></tr>';
  } else {
    tb.innerHTML = accs.map(a => {
      var realName = a.display_name || a.zalo_name || a.username || '—';
      return `<tr><td>${a.id}</td><td><b>${a.label}</b></td>
        <td><span style="color:var(--noel-red);font-weight:700;">${realName}</span></td>
        <td><code>…${String(a.uid||'').slice(-6)}</code></td>
        <td><span class="badge badge-ok">${a.ok_count}</span> <span class="badge badge-err">${a.fail_count}</span></td>
        <td>${(a.risk||0).toFixed(2)}</td>
        <td>
          <button class="btn-circle danger small" onclick="delAcc(${a.id})"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg></button>
        </td></tr>`;
    }).join('');
  }
  document.getElementById('stat-total').textContent = accs.length;
  document.getElementById('stat-active').textContent = accs.filter(a => a.enabled).length;
  document.getElementById('stat-sent').textContent = accs.reduce((s,a) => s + (a.total_sent||0), 0);

  var s1 = document.getElementById('load-acc-select');
  var s2 = document.getElementById('member-acc-select');
  var opts = '<option value="">-- Chọn tài khoản --</option>' + accs.map(a => `<option value="${a.id}">${a.label}</option>`).join('');
  s1.innerHTML = opts; s2.innerHTML = opts;
}

async function addAccount(){
  var label = document.getElementById('add-label').value.trim();
  var imei = document.getElementById('add-imei').value.trim();
  var cookies = document.getElementById('add-cookies').value.trim();
  if(!imei || !cookies) return Toast.error('Thiếu IMEI hoặc Cookie');
  Toast.info('Đang kiểm tra danh tính Cookie...');
  var r = await api('/api/accounts/add', { method: 'POST', body: JSON.stringify({ label, imei, cookies }) });
  if(r.error) return Toast.error(r.error);
  Toast.success('Thêm thành công: ' + r.label);
  refreshAll();
}

async function delAcc(id){
  if(!confirm('Xác nhận xóa tài khoản #' + id + '?')) return;
  await api('/api/accounts/' + id, { method: 'DELETE' });
  Toast.success('Đã xóa #' + id);
  refreshAll();
}

async function loadBoxes(){
  var aid = document.getElementById('load-acc-select').value;
  if(!aid) return Toast.error('Chọn tài khoản trước');
  Toast.info('Đang nạp hội thoại Zalo...');
  var r = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  var all = (r.groups||[]).concat(r.friends||[]);
  var bl = document.getElementById('box-list');
  bl.innerHTML = all.map((b,i) => `
    <div class="box-item" onclick="tgBox(this, ${i})">
      <div class="check">✓</div>
      <div class="info"><div class="name">${b.name}</div><div class="meta">${b.id} | ${b.type}</div></div>
    </div>
  `).join('');
  _boxes = all; selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
  Toast.success('Đã nạp ' + all.length + ' box');
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

async function uploadFile(){
  var input = document.getElementById('file-input');
  if(!input.files.length) return Toast.error('Chưa chọn tệp tin');
  var fd = new FormData();
  fd.append('file', input.files[0]);
  Toast.info('Đang tải tệp...');
  var r = await fetch('/api/files/upload', { method: 'POST', body: fd }).then(x => x.json());
  if(r.error) return Toast.error(r.error);
  Toast.success('Đã tải lên ' + r.lines + ' khối tin');
  input.value = ''; loadFiles();
}

async function loadFiles(){
  var files = await api('/api/files');
  if(!Array.isArray(files)) files = [];
  var list = document.getElementById('files-list');
  list.innerHTML = files.map(f => `
    <div class="box-item">
      <div class="info"><div class="name">📄 ${f.filename}</div><div class="meta">${f.lines} khối</div></div>
    </div>
  `).join('') || '<div style="text-align:center;padding:14px;color:var(--txt-3);">Chưa có tệp</div>';
  var s = document.getElementById('spam-file-select');
  s.innerHTML = '<option value="">-- Chọn file --</option>' + files.map(f => `<option value="${f.id}">${f.filename} (${f.lines} khối)</option>`).join('');
}

// LỌC TÊN THẬT 100% (KHÔNG USER)
async function loadMembers(){
  var aid = document.getElementById('member-acc-select').value;
  if(!aid) return Toast.error('Chọn tài khoản trước');
  var box = selectedBoxes.find(b => b.type === 'group');
  if(!box) return Toast.error('Hãy chọn 1 nhóm ở Tab Box trước');
  Toast.info('Đang quét tên thật thành viên...');
  var r = await api('/api/accounts/' + aid + '/members/' + box.id, { method: 'POST' });
  if(r.error) return Toast.error(r.error);
  var mem = r.members || [];
  var sel = document.getElementById('tag-selector');
  sel.style.display = 'block';
  sel.innerHTML = mem.map((m, i) => `
    <div class="box-item" onclick="tgMember(this, ${i})">
      <div class="check">✓</div>
      <div class="info"><div class="name">${m.name}</div><div class="meta">${m.id}</div></div>
    </div>
  `).join('') || '<div style="padding:14px;text-align:center;">Không có thành viên</div>';
  _members = mem; selectedTags = [];
  Toast.success('Quét xong ' + mem.length + ' thành viên tên thật');
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

// BẮT ĐẦU BẮN TIN NHẮN
async function startSpam(){
  if(!selectedBoxes.length) return Toast.error('Chưa chọn Box chat mục tiêu');
  var fid = document.getElementById('spam-file-select').value;
  var direct = document.getElementById('spam-messages').value.trim();
  var blocks = [];

  if(fid){
    var r = await api('/api/files/' + fid + '/preview');
    blocks = r.all || [];
  } else if(direct){
    if(currentMode === "treo_ngon"){
      blocks = [direct]; // Treo ngôn: Giữ nguyên toàn bộ dòng trong 1 tin duy nhất
    } else {
      blocks = direct.includes(';') ? direct.split(';').map(m => m.trim()).filter(Boolean) : [direct];
    }
  }

  if(!blocks.length) return Toast.error('Chưa có nội dung tin nhắn');
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
    make_bold: flags.bold,
    multi_acc: flags.multi,
    mode: currentMode,
    color_mode: colorMode,
    fixed_color: fixedColor,
    human_mode: flags.human
  };

  var res = await api('/api/tasks/start', { method: 'POST', body: JSON.stringify(payload) });
  if(res.error) return Toast.error(res.error);
  Toast.success('Đã kích hoạt: ' + currentMode + ' (Multi-Thread)');
  loadTasks();
}

async function stopAll(){
  await api('/api/tasks/stop_all', { method: 'POST' });
  Toast.warning('Đã dừng tất cả tiến trình');
  loadTasks();
}

async function loadTasks(){
  var tasks = await api('/api/tasks');
  if(!Array.isArray(tasks)) tasks = [];
  var tb = document.getElementById('tasks-tbody');
  tb.innerHTML = tasks.map(t => {
    var running = (t.status === 'running');
    return `<tr><td><code>${t.id.slice(-6)}</code></td>
      <td>${t.type}</td>
      <td>${t.status}</td>
      <td>${running ? '<span class="badge badge-ok">Đang chạy</span>' : '<span class="badge badge-err">Đã dừng</span>'}</td>
      <td>${running ? `<button class="btn-circle danger small" onclick="stopTask('${t.id}')">⏹</button>` : ''}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="6" style="text-align:center;padding:14px;color:var(--txt-3);">Không có tiến trình</td></tr>';
}

async function stopTask(tid){
  await api('/api/tasks/' + tid + '/stop', { method: 'POST' });
  Toast.warning('Đã dừng ' + tid);
  loadTasks();
}

function refreshAll(){ loadAccounts(); loadFiles(); loadTasks(); }

// HIỆU ỨNG TUYẾT RƠI 60FPS
var snowCanvas = document.getElementById("snow-canvas");
var sCtx = snowCanvas.getContext("2d");
var sW = window.innerWidth, sH = window.innerHeight;
snowCanvas.width = sW; snowCanvas.height = sH;
var flakes = Array.from({length: 40}, () => ({
  x: Math.random()*sW, y: Math.random()*sH, r: Math.random()*3 + 1, d: Math.random()*1 + 0.4
}));
function runSnow(){
  sCtx.clearRect(0,0,sW,sH);
  sCtx.fillStyle = "rgba(232, 69, 60, 0.35)";
  flakes.forEach(f => {
    sCtx.beginPath(); sCtx.arc(f.x, f.y, f.r, 0, Math.PI*2); sCtx.fill();
    f.y += f.d; f.x += Math.sin(f.y/15);
    if(f.y > sH){ f.y = 0; f.x = Math.random()*sW; }
  });
  requestAnimationFrame(runSnow);
}
runSnow();

refreshAll();
setInterval(loadTasks, 5000);
</script>
</body>
</html>
"""


# ============================================================
# TẤT CẢ ROUTE VÀ API
# ============================================================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/verify_gate")
def verify_gate():
    return render_template_string(HTML_VERIFY_GATE)


@app.route("/api/verify_challenge", methods=["POST"])
def api_verify_challenge():
    session["bot_verified"] = True
    return jsonify({"ok": True})


@app.route("/")
@login_required
def index():
    return render_template_string(HTML_INDEX)


@app.route("/login", methods=["GET", "POST"])
def login():
    ip = get_client_ip()
    now = time.time()

    # Kiểm tra khóa Brute Force
    tracker = login_fail_tracker[ip]
    if tracker["locked_until"] > now:
        rem = int(tracker["locked_until"] - now)
        return render_template_string(
            HTML_LOGIN,
            error=f"IP bị khóa do nhập sai mật khẩu quá 5 lần. Vui lòng thử lại sau {rem} giây."
        )

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
                return render_template_string(
                    HTML_LOGIN,
                    error="Cảnh báo: Nhập sai 5 lần! IP của bạn đã bị khóa trong 15 phút."
                )
            rem_tries = LOGIN_MAX_FAILS - tracker["count"]
            return render_template_string(
                HTML_LOGIN,
                error=f"Sai mật khẩu truy cập! Còn {rem_tries} lần thử trước khi bị khóa."
            )

    return render_template_string(HTML_LOGIN)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/accounts", methods=["GET"])
@login_required
def api_accounts():
    conn = db()
    rows = conn.execute("""
        SELECT id, label, imei, ok_count, fail_count, risk,
               total_sent, enabled, uid, display_name, zalo_name, username
        FROM accounts ORDER BY id DESC
    """).fetchall()
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
        return jsonify({"error": "Thiếu IMEI hoặc Cookie"}), 400
    try:
        ck_obj = json.loads(ck)
        z = Zalo(imei, ck_obj)
    except Exception as e:
        return jsonify({"error": "Cookie hỏng hoặc sai định dạng: " + str(e)}), 400

    conn = db()
    conn.execute("""
        INSERT INTO accounts (label, imei, cookies, added_at,
                             uid, display_name, zalo_name, username)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (label, imei, json.dumps(ck_obj), time.time(),
          z.uid, z.display_name or "", z.zalo_name or "", z.username or ""))
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


@app.route("/api/accounts/<int:aid>/load_boxes", methods=["POST"])
@login_required
def api_load_boxes(aid):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    conn.close()
    if not row: return jsonify({"error": "Không tìm thấy acc"}), 404
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
    if not row: return jsonify({"error": "Không tìm thấy acc"}), 404
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
    rows = conn.execute("SELECT id, filename, lines, size, uploaded_at FROM files ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/files/upload", methods=["POST"])
@login_required
def api_files_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Không có tệp"}), 400
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
    if not row: return jsonify({"error": "Không tìm thấy file"}), 404
    return jsonify({"filename": row["filename"], "all": parse_blocks(row["filepath"])})


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
    d = request.json
    targets = d.get("targets", [])
    blocks = d.get("blocks", [])
    delay = float(d.get("delay", 1.0))
    use_emoji = bool(d.get("use_emoji", True))
    icon_count = int(d.get("icon_count", 3))
    tag_users = d.get("tag_users", [])
    tag_all = bool(d.get("tag_all", False))
    make_bold = bool(d.get("make_bold", True))
    multi_acc = bool(d.get("multi_acc", True))
    mode = d.get("mode", "fast")
    color_mode = d.get("color_mode", "random")
    fixed_color = d.get("fixed_color", "red")
    human_mode = bool(d.get("human_mode", True))

    if not targets or not blocks:
        return jsonify({"error": "Chưa chọn Box hoặc chưa có nội dung"}), 400

    tid = new_tid("spam_noel")
    stop_ev = threading.Event()

    th = threading.Thread(
        target=master_task_controller,
        args=(tid, targets, blocks, delay, use_emoji, icon_count,
              tag_users, tag_all, make_bold, mode, color_mode, fixed_color,
              human_mode, multi_acc, stop_ev),
        daemon=True
    )

    conn = db()
    conn.execute("INSERT INTO tasks (id, type, meta, status, started_at, stats) VALUES (?, ?, ?, ?, ?, ?)",
                 (tid, mode, json.dumps({"multi_acc": multi_acc, "tag_all": tag_all}), "running", time.time(), "{}"))
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
    return jsonify({"error": "Không tìm thấy task"}), 404


@app.route("/api/tasks/stop_all", methods=["POST"])
@login_required
def api_tasks_stop_all():
    for tid, t in list(ACTIVE_TASKS.items()):
        t["stop"].set()
    return jsonify({"ok": True, "count": len(ACTIVE_TASKS)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
