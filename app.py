# ============================================================
# ALB FORGE v34.0 — I LOVE NGỌC HÂN (WHITE GLASS EDITION)
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
app.secret_key = os.environ.get("SECRET_KEY", "alb-ngoc-han-2026")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024


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
# ICON ZALO SÁT THƯƠNG TÂM LÝ
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
    "😹", "😈", "🔥", "😤", "🤮", "🤢", "🐒"
]


def get_icon_hard():
    if random.random() < 0.65:
        return random.choice(ZALO_ICON_HARD)
    return random.choice(ZALO_ICON_UNICODE)


# ============================================================
# BẢNG MÀU CHỮ ZALO
# ============================================================
ZALO_COLORS = [
    {"id": "red",    "name": "Đỏ",        "hex": "#e8453c"},
    {"id": "orange", "name": "Cam",       "hex": "#ff8c00"},
    {"id": "yellow", "name": "Vàng",      "hex": "#f5c500"},
    {"id": "green",  "name": "Lục",       "hex": "#00b14f"},
    {"id": "ocean",  "name": "Xanh biển", "hex": "#0091ff"},
    {"id": "blue",   "name": "Xanh dương", "hex": "#0068ff"},
    {"id": "purple", "name": "Tím",       "hex": "#a05eff"},
    {"id": "pink",   "name": "Hồng",      "hex": "#ff47a8"},
    {"id": "brown",  "name": "Nâu",       "hex": "#a87050"},
    {"id": "black",  "name": "Đen",       "hex": "#1a1a1a"},
    {"id": "gray",   "name": "Xám",       "hex": "#8a8a8a"},
    {"id": "white",  "name": "Trắng",     "hex": "#ffffff"},
]

COLOR_IDS = [c["id"] for c in ZALO_COLORS]


# ============================================================
# ANTI-BAN & LOGIC DELAY
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
        if fail > 20 and ok < 5: base = min(1.0, base + 0.18)
        if ok > 100 and base < 0.05: base = max(0.0, base - 0.02)
        return min(1.0, base)

    @staticmethod
    def compute_delay(user_delay, risk, is_warmup=False):
        d = max(AntiBan.MIN_DELAY, user_delay)
        if risk > 0.85: d = max(d, 18.0)
        elif risk > 0.7: d = max(d, 10.0)
        elif risk > 0.5: d = max(d, 5.0)
        elif risk > 0.3: d = max(d, 2.5)
        if is_warmup: d *= AntiBan.WARMUP_MULT
        d = d * random.uniform(0.88, 1.12)
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
    def typing_rate(speed):
        return {"fast": 0.014, "normal": 0.032,
                "slow": 0.055, "instant": 0.0}.get(speed, 0.014)


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
            raise Exception("Cookie hoặc IMEI không chính xác")
        self.uid = ud.get("send2me_id")
        self.secret_key = ud.get("zpw_enk")
        try:
            self.display_name = ud.get("displayName") or ud.get("zaloName")
            self.zalo_name = ud.get("zaloName")
            self.username = ud.get("username")
        except Exception:
            pass
        if not self.secret_key:
            raise Exception("Không trích xuất được secret key")
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
        return {"name": info.get("name", "?"),
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
                     "name": u.get("zaloName", "?"),
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
                final_name = dn or zn or un or ("User_" + uid[:8])
                members.append({
                    "id": uid, "name": final_name,
                    "display_name": dn, "zalo_name": zn, "username": un,
                })
        except Exception:
            for uid in uids:
                members.append({
                    "id": uid, "name": "User_" + uid[:8],
                    "display_name": "", "zalo_name": "", "username": "",
                })
        return members

    def build_mention_payload(self, text, mentions):
        if not mentions: return text, []
        final = text
        m_arr = []
        for m in mentions:
            name = str(m.get("name", "")).strip()
            uid = str(m.get("uid") or m.get("id") or "").strip()
            if not name or not uid: continue
            tag_str = "@" + name
            pos = len(final) + (1 if final else 0)
            if final: final = final + " " + tag_str
            else: final = tag_str
            m_arr.append({"uid": str(uid), "pos": pos,
                          "len": len(tag_str), "type": 0})
        return final, m_arr

    def send(self, msg, thread_id, color=None, is_group=True, mentions=None):
        url = ("https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
               if is_group
               else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms")

        final_msg = msg
        m_arr = []
        if mentions:
            final_msg, m_arr = self.build_mention_payload(msg, mentions)

        # Chuẩn hóa ngắt dòng, ngăn chặn chèn ký tự lạ
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

    def set_typing(self, thread_id, is_group=True):
        if is_group:
            url = "https://tt-group-wpa.chat.zalo.me/api/group/typing"
            pl = {"grid": str(thread_id), "imei": self.imei}
        else:
            url = "https://tt-chat1-wpa.chat.zalo.me/api/message/typing"
            pl = {"toid": str(thread_id), "destType": 3, "imei": self.imei}
        enc = self._enc(pl)
        try:
            self.s.post(url, params={"zpw_ver": 645, "zpw_type": 30},
                        data={"params": enc}, timeout=10)
        except Exception:
            pass

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
# PARSER TỆP TIN
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
        print("[FILE ERROR] " + str(e))
    return blocks


# ============================================================
# WORKER TIẾN TRÌNH
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


def pick_account(exclude_id=None):
    conn = db()
    q = "SELECT * FROM accounts WHERE enabled = 1 AND risk < 0.85"
    params = []
    if exclude_id:
        q += " AND id != ?"; params.append(exclude_id)
    q += " ORDER BY risk ASC, last_used ASC LIMIT 1"
    rows = conn.execute(q, params).fetchall()
    if not rows and exclude_id:
        rows = conn.execute(
            "SELECT * FROM accounts WHERE enabled = 1 AND risk < 0.85 "
            "ORDER BY risk ASC LIMIT 1"
        ).fetchall()
    conn.close()
    return rows[0] if rows else None


def humanize_typing(z, thread_id, is_group, msg_len, speed="fast"):
    r = AntiBan.typing_rate(speed)
    if r <= 0: return
    typing_time = min(msg_len * r, 2.5)
    try: z.set_typing(thread_id, is_group=is_group)
    except Exception: pass
    if typing_time > 0.05: time.sleep(typing_time)


def spam_worker(tid, targets, blocks, delay,
                use_emoji, icon_count, tag_users, stop_event,
                mode="fast", color_mode="random", fixed_color=None,
                typing_speed="fast", human_mode=True,
                real_mention=False, read_receipt=True):
    block_idx = 0
    target_idx = 0
    count = 0
    last_acc_id = None
    acc_warmup_counter = {}
    acc_session_counter = {}
    global_color_idx = 0

    while not stop_event.is_set():
        acc = pick_account(exclude_id=last_acc_id)
        if not acc:
            time.sleep(0.3); continue

        last_acc_id = acc["id"]
        aid_key = acc["id"]
        acc_warmup_counter.setdefault(aid_key, 0)
        acc_session_counter.setdefault(aid_key, 0)

        if acc_session_counter[aid_key] >= AntiBan.SESSION_MAX:
            rest = random.uniform(AntiBan.SESSION_REST_MIN, AntiBan.SESSION_REST_MAX)
            end = time.time() + rest
            while time.time() < end:
                if stop_event.is_set(): break
                time.sleep(0.05)
            acc_session_counter[aid_key] = 0
            last_acc_id = None
            continue

        is_warmup = acc_warmup_counter[aid_key] < AntiBan.WARMUP_MSGS
        target = targets[target_idx % len(targets)]
        target_idx += 1
        is_group = target.get("type") == "group"
        target_id = target.get("id")

        raw = blocks[block_idx % len(blocks)]
        block_idx += 1

        try:
            cookies = json.loads(acc["cookies"])
            z = Zalo(acc["imei"], cookies)

            if read_receipt:
                z.mark_read(target_id, is_group=is_group)
                time.sleep(random.uniform(0.05, 0.15))

            if mode == "treo_nhay":
                # N dòng -> N tin riêng biệt đánh số 1. 2. 3.
                lines = [ln for ln in raw.split("\n") if ln.strip()]
                numbered = [str(i) + ". " + ln for i, ln in enumerate(lines, 1)]

                if human_mode:
                    humanize_typing(z, target_id, is_group, len(raw), typing_speed)

                for mi, ln in enumerate(numbered):
                    if stop_event.is_set(): break
                    text = ln
                    if use_emoji and icon_count > 0:
                        text = AntiBan.append_icons(text, icon_count)
                    mentions = tag_users if (real_mention and tag_users and mi == 0) else None
                    color = AntiBan.pick_color(color_mode, fixed_color, global_color_idx)
                    global_color_idx += 1

                    r = z.send(text, target_id, color=color,
                               is_group=is_group, mentions=mentions)
                    ok = bool(r and r.status_code == 200)
                    update_stats(acc["id"], ok)
                    count += 1
                    acc_warmup_counter[aid_key] += 1
                    acc_session_counter[aid_key] += 1

                    if mi < len(numbered) - 1:
                        gap = random.uniform(0.3, 0.7) if human_mode else 0.15
                        end = time.time() + gap
                        while time.time() < end:
                            if stop_event.is_set(): break
                            time.sleep(0.01)

            elif mode == "treo_ngon":
                # Toàn bộ khối N dòng gửi trong 1 TIN DUY NHẤT, giữ trọn \n
                text_full = raw.replace("\r\n", "\n").replace("\r", "\n")
                if use_emoji and icon_count > 0:
                    text_full = AntiBan.append_icons(text_full, icon_count)

                if human_mode:
                    humanize_typing(z, target_id, is_group, len(text_full), typing_speed)

                mentions = tag_users if (real_mention and tag_users) else None
                color = AntiBan.pick_color(color_mode, fixed_color, global_color_idx)
                global_color_idx += 1

                r = z.send(text_full, target_id, color=color,
                           is_group=is_group, mentions=mentions)
                ok = bool(r and r.status_code == 200)
                update_stats(acc["id"], ok)
                count += 1
                acc_warmup_counter[aid_key] += 1
                acc_session_counter[aid_key] += 1

            else:
                # Fast xoay vòng
                text = raw
                if use_emoji and icon_count > 0:
                    text = AntiBan.append_icons(text, icon_count)

                if human_mode:
                    humanize_typing(z, target_id, is_group, len(text), typing_speed)

                color = AntiBan.pick_color(color_mode, fixed_color, global_color_idx)
                global_color_idx += 1
                mentions = tag_users if (real_mention and tag_users) else None

                r = z.send(text, target_id, color=color,
                           is_group=is_group, mentions=mentions)
                ok = bool(r and r.status_code == 200)
                update_stats(acc["id"], ok)
                count += 1
                acc_warmup_counter[aid_key] += 1
                acc_session_counter[aid_key] += 1

        except Exception as e:
            update_stats(acc["id"], False)
            print("[SPAM] Error " + acc["label"] + ": " + str(e))

        risk = acc["risk"] if acc["risk"] else 0.0
        base = AntiBan.compute_delay(delay, risk, is_warmup=is_warmup)
        actual = base * random.uniform(0.92, 1.18) if human_mode else base

        end = time.time() + actual
        while time.time() < end:
            if stop_event.is_set(): break
            time.sleep(0.03)

    conn = db()
    conn.execute("UPDATE tasks SET status = 'stopped', stats = ? WHERE id = ?",
                 (json.dumps({"sent": count}), tid))
    conn.commit(); conn.close()
    ACTIVE_TASKS.pop(tid, None)


# ============================================================
# AUTH FILTER
# ============================================================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


# ============================================================
# CSS GIAO DIỆN TRẮNG TINH TẾ & HIỆU ỨNG CHUYỂN ĐỘNG
# ============================================================
CSS_COMMON = """
:root {
  --bg-main: #ffffff;
  --bg-card: rgba(255, 255, 255, 0.94);
  --line-1: rgba(226, 232, 240, 0.85);
  --line-focus: #ff3366;
  --txt-0: #0f172a;
  --txt-1: #1e293b;
  --txt-2: #64748b;
  --txt-3: #94a3b8;
  --love-1: #ff007f;
  --love-2: #ff3366;
  --love-gold: #f59e0b;
  --grad-love: linear-gradient(135deg, #ff007f 0%, #ff3366 50%, #f43f5e 100%);
  --grad-gold: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
  --grad-rainbow: linear-gradient(90deg, #ff007f, #f59e0b, #00b14f, #0091ff, #7b2ff7);
  --shadow-soft: 0 10px 30px rgba(15, 23, 42, 0.06);
  --shadow-glow: 0 8px 25px rgba(255, 0, 127, 0.25);
  --r-sm: 10px; --r-md: 14px; --r-lg: 20px; --r-xl: 26px;
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
}
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html { touch-action: manipulation; -webkit-text-size-adjust: 100%; }
body {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background-color: #f8fafc;
  color: var(--txt-1);
  min-height: 100vh;
  padding-bottom: 110px;
  overflow-x: hidden;
  position: relative;
}
/* Ảnh nền chiếc váy phủ mờ thanh lịch */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  background-image: url('/static/bg.jpg');
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  opacity: 0.22;
  filter: blur(4px);
  pointer-events: none;
  z-index: -1;
}
button, input, textarea, select { font-family: inherit; }
::selection { background: rgba(255, 0, 127, 0.2); color: #000; }
*::-webkit-scrollbar { width: 5px; height: 5px; }
*::-webkit-scrollbar-track { background: transparent; }
*::-webkit-scrollbar-thumb { background: rgba(15, 23, 42, 0.15); border-radius: 99px; }

/* HEADER */
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
.header::after { content:''; position:absolute; left:0; right:0; bottom:0; height:2px; background:var(--grad-rainbow); }
.header-inner { max-width: 1050px; margin: 0 auto; display: flex; align-items: center; gap: 12px; }

/* LOGO NGỌC HÂN */
.logo-wrap {
  width: 46px; height: 46px; border-radius: 50%;
  position: relative; padding: 2px;
  background: var(--grad-love);
  box-shadow: var(--shadow-glow);
  flex-shrink: 0; display: flex; align-items: center; justify-content: center;
  animation: pulseLogo 3s ease-in-out infinite;
}
@keyframes pulseLogo {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.05); }
}
.logo-img {
  width: 100%; height: 100%; border-radius: 50%;
  object-fit: cover; background: #fff;
  border: 1.5px solid #fff;
}
.header-title-box { flex: 1; min-width: 0; }
.header-title-box h1 {
  font-family: 'Orbitron', sans-serif; font-size: 14.5px; font-weight: 900;
  background: var(--grad-love); -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; letter-spacing: 0.5px;
}
.header-title-box p {
  font-size: 9px; color: var(--txt-2); font-weight: 700;
  letter-spacing: 1px; text-transform: uppercase; margin-top: 2px;
}
.logout-btn {
  display: inline-flex; align-items: center; gap: 5px;
  background: #ffffff; color: var(--txt-1);
  border: 1px solid var(--line-1); padding: 7px 12px; border-radius: 12px;
  font-size: 11px; font-weight: 800; cursor: pointer; transition: all .25s var(--ease-spring);
}
.logout-btn:hover { background: #fef2f2; border-color: #ef4444; color: #dc2626; transform: translateY(-2px); }

/* MAIN CONTAINERS */
.container { max-width: 1050px; margin: 0 auto; padding: 14px; }
.panel { display: none; animation: fadeIn .3s ease both; }
.panel.active { display: block; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

/* CARDS */
.card {
  position: relative; background: var(--bg-card);
  backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
  padding: 18px; border-radius: var(--r-lg);
  border: 1px solid var(--line-1); box-shadow: var(--shadow-soft);
  margin-bottom: 14px; transition: all .3s var(--ease-spring);
}
.card:hover { border-color: rgba(255, 0, 127, 0.3); box-shadow: 0 12px 35px rgba(255, 0, 127, 0.08); }
.card h2 {
  font-size: 12px; font-weight: 900; letter-spacing: .5px; margin-bottom: 14px;
  display: flex; align-items: center; gap: 9px; color: var(--txt-0); text-transform: uppercase;
}
.card h2 .badge-icon {
  width: 26px; height: 26px; border-radius: 8px; background: var(--grad-love);
  display: flex; align-items: center; justify-content: center; font-size: 12px; color: #fff;
  box-shadow: 0 4px 12px rgba(255, 0, 127, 0.3);
}

/* FORMS */
.form-group { margin-bottom: 12px; }
.form-group label { display: block; margin-bottom: 5px; font-size: 9.5px; font-weight: 800; color: var(--txt-2); text-transform: uppercase; letter-spacing: .8px; }
.form-group input, .form-group textarea, .form-group select {
  width: 100%; padding: 12px 14px; border: 1.5px solid var(--line-1); border-radius: 12px;
  font-size: 13px; font-weight: 500; background: #ffffff; color: var(--txt-0);
  transition: all .25s var(--ease-spring);
}
.form-group input::placeholder, .form-group textarea::placeholder { color: var(--txt-3); }
.form-group input:focus, .form-group textarea:focus, .form-group select:focus {
  outline: none; border-color: var(--love-2); background: #ffffff;
  box-shadow: 0 0 0 4px rgba(255, 0, 127, 0.12);
}
.form-group textarea { min-height: 90px; resize: vertical; font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.5; }

/* BUTTONS WITH SPRING BOUNCE EFFECT */
.btn-rect {
  padding: 12px 18px; border: none; border-radius: 12px; cursor: pointer;
  font-size: 11.5px; font-weight: 900; letter-spacing: .6px; color: #fff; text-transform: uppercase;
  display: inline-flex; align-items: center; gap: 7px; transition: all .25s var(--ease-spring);
}
.btn-rect:hover { transform: translateY(-2px); filter: brightness(1.05); }
.btn-rect:active { transform: translateY(0) scale(0.96); }
.btn-rect.primary { background: var(--grad-love); box-shadow: 0 8px 24px rgba(255, 0, 127, 0.35); }
.btn-rect.full { width: 100%; justify-content: center; }

.btn-circle {
  width: 46px; height: 46px; border-radius: 50%; border: none; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center; color: #fff;
  transition: all .25s var(--ease-spring); margin: 3px;
}
.btn-circle svg { width: 19px; height: 19px; }
.btn-circle:hover { transform: translateY(-3px) scale(1.08); }
.btn-circle:active { transform: translateY(0) scale(0.94); }
.btn-circle.primary { background: var(--grad-love); box-shadow: 0 6px 18px rgba(255, 0, 127, 0.35); }
.btn-circle.danger { background: linear-gradient(135deg, #ef4444, #dc2626); box-shadow: 0 6px 18px rgba(239, 68, 68, 0.3); }
.btn-circle.success { background: linear-gradient(135deg, #10b981, #059669); box-shadow: 0 6px 18px rgba(16, 185, 129, 0.3); }
.btn-circle.warning { background: var(--grad-gold); box-shadow: 0 6px 18px rgba(245, 158, 11, 0.3); }
.btn-circle.small { width: 32px; height: 32px; }
.btn-circle.small svg { width: 14px; height: 14px; }
.btn-circle.big { width: 62px; height: 62px; }
.btn-circle.big svg { width: 25px; height: 25px; }

/* STATS */
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(90px, 1fr)); gap: 8px; margin-bottom: 12px; }
.stat { background: #ffffff; padding: 12px 10px; border-radius: var(--r-md); border: 1px solid var(--line-1); position: relative; overflow: hidden; }
.stat::before { content:''; position:absolute; top:0; left:0; right:0; height:2px; background:var(--grad-rainbow); }
.stat .label { font-size: 8.5px; color: var(--txt-2); margin-bottom: 4px; text-transform: uppercase; font-weight: 800; }
.stat .value { font-size: 19px; font-weight: 900; color: var(--txt-0); font-family: 'Orbitron', sans-serif; }

/* TABLES */
.table-wrap { overflow-x: auto; border-radius: var(--r-md); border: 1px solid var(--line-1); background: #ffffff; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { padding: 9px 8px; text-align: left; font-size: 11px; border-bottom: 1px solid rgba(226, 232, 240, 0.6); white-space: nowrap; }
.table th { background: #f8fafc; font-weight: 800; color: var(--txt-2); text-transform: uppercase; font-size: 9px; }
.table td code { background: #f1f5f9; padding: 2px 6px; border-radius: 5px; font-size: 9.5px; font-family: 'JetBrains Mono', monospace; color: var(--love-2); }

.badge { display: inline-flex; align-items: center; gap: 4px; padding: 3px 7px; border-radius: 20px; font-size: 9px; font-weight: 800; }
.badge::before { content:''; width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
.badge-ok { background: #d1fae5; color: #065f46; }
.badge-err { background: #fee2e2; color: #991b1b; }
.badge-warn { background: #fef3c7; color: #92400e; }

/* BOX & FILE LIST */
.box-list { max-height: 320px; overflow-y: auto; border: 1px solid var(--line-1); border-radius: var(--r-md); padding: 7px; background: #ffffff; }
.box-item { padding: 10px; border-radius: 10px; background: #f8fafc; margin-bottom: 5px; cursor: pointer; border: 1px solid var(--line-1); display: flex; align-items: center; gap: 9px; transition: all .2s var(--ease-spring); }
.box-item:hover { border-color: var(--love-2); transform: translateX(2px); background: #fff; }
.box-item.selected { border-color: var(--love-1); background: #fff0f5; }
.box-item .check { width: 18px; height: 18px; border: 2px solid var(--txt-3); border-radius: 5px; display: flex; align-items: center; justify-content: center; font-size: 10px; color: transparent; font-weight: 900; }
.box-item.selected .check { background: var(--love-1); border-color: var(--love-1); color: #fff; }
.box-item .info { flex: 1; min-width: 0; }
.box-item .name { font-weight: 700; font-size: 12px; color: var(--txt-0); text-overflow: ellipsis; white-space: nowrap; overflow: hidden; }
.box-item .meta { font-size: 9.5px; color: var(--txt-3); font-family: 'JetBrains Mono', monospace; margin-top: 2px; }

/* MODE CARDS */
.mode-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin-top: 6px; }
.mode-card { padding: 12px 6px; border-radius: 12px; cursor: pointer; background: #ffffff; border: 1.5px solid var(--line-1); text-align: center; transition: all .25s var(--ease-spring); }
.mode-card:hover { transform: translateY(-2px); border-color: var(--love-2); }
.mode-card.active { background: var(--grad-love); border-color: transparent; color: #fff; box-shadow: 0 6px 20px rgba(255, 0, 127, 0.35); transform: translateY(-2px); }
.mode-card .mc-icon { width: 28px; height: 28px; margin: 0 auto 5px; display: flex; align-items: center; justify-content: center; }
.mode-card .mc-icon svg { width: 22px; height: 22px; }
.mode-card .mc-title { font-size: 10.5px; font-weight: 900; letter-spacing: .4px; text-transform: uppercase; margin-bottom: 2px; }
.mode-card .mc-desc { font-size: 8.5px; opacity: 0.85; }

/* CHIPS & TOGGLES */
.chip-group { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px; }
.chip { padding: 7px 13px; background: #ffffff; color: var(--txt-2); border-radius: 20px; font-size: 10.5px; font-weight: 800; cursor: pointer; border: 1px solid var(--line-1); transition: all .2s var(--ease-spring); }
.chip:hover { border-color: var(--love-2); color: var(--love-2); }
.chip.active { background: var(--grad-love); color: #fff; border-color: transparent; box-shadow: 0 4px 14px rgba(255, 0, 127, 0.3); transform: translateY(-1px); }

.toggle-group { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; margin-bottom: 11px; }
.toggle { padding: 11px 9px; border: 1px solid var(--line-1); border-radius: var(--r-md); cursor: pointer; text-align: center; font-weight: 800; font-size: 10.5px; background: #ffffff; color: var(--txt-2); text-transform: uppercase; transition: all .25s var(--ease-spring); }
.toggle.active { background: var(--grad-love); color: #fff; border-color: transparent; box-shadow: 0 4px 14px rgba(255, 0, 127, 0.28); transform: translateY(-1px); }

/* FLOATING BOTTOM DOCK */
.bottom-dock {
  position: fixed; bottom: 14px; left: 50%; transform: translateX(-50%);
  width: calc(100% - 24px); max-width: 520px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(28px) saturate(200%);
  -webkit-backdrop-filter: blur(28px) saturate(200%);
  border: 1.5px solid rgba(255, 0, 127, 0.25);
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.12), 0 0 20px rgba(255, 0, 127, 0.15);
  border-radius: var(--r-xl); display: grid; grid-template-columns: repeat(4, 1fr);
  padding: 6px; gap: 5px; z-index: 999;
}
.bottom-dock .tab {
  padding: 9px 4px; border-radius: 16px; cursor: pointer; font-size: 9.5px; font-weight: 800;
  text-align: center; color: var(--txt-2); display: flex; flex-direction: column; align-items: center;
  gap: 3px; background: transparent; border: none; transition: all .3s var(--ease-spring); text-transform: uppercase;
}
.bottom-dock .tab svg { width: 19px; height: 19px; transition: transform .25s var(--ease-spring); }
.bottom-dock .tab:hover svg { transform: scale(1.15) translateY(-2px); }
.bottom-dock .tab.active { background: var(--grad-love); color: #fff; box-shadow: 0 5px 16px rgba(255, 0, 127, 0.35); transform: translateY(-2px); }

/* THÔNG BÁO TOAST: KHÔNG CHỒNG, VUỐT LÊN BIẾN MẤT, TẮT NHANH 1.4S */
#toast-stack {
  position: fixed; top: calc(14px + env(safe-area-inset-top, 0px)); right: 12px;
  z-index: 99999; max-width: 350px; width: calc(100% - 24px); pointer-events: none;
}
.toast {
  pointer-events: auto; position: relative; overflow: hidden;
  padding: 12px 14px 12px 50px; border-radius: 14px;
  background: rgba(255, 255, 255, 0.98); backdrop-filter: blur(20px);
  border: 1px solid var(--line-1); box-shadow: 0 12px 35px rgba(15, 23, 42, 0.12);
  display: flex; flex-direction: column; gap: 2px; touch-action: pan-y;
  animation: toastSlideDown .28s var(--ease-spring) both;
}
.toast.swipe-out {
  animation: toastSwipeUp .22s ease-out forwards;
}
@keyframes toastSlideDown {
  from { opacity: 0; transform: translateY(-25px) scale(0.95); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
@keyframes toastSwipeUp {
  to { opacity: 0; transform: translateY(-50px) scale(0.9); }
}
.toast::before { content:''; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--grad-love); }
.toast .t-icon {
  position: absolute; left: 11px; top: 50%; transform: translateY(-50%);
  width: 30px; height: 30px; border-radius: 9px; display: flex; align-items: center;
  justify-content: center; color: #fff; background: var(--grad-love); box-shadow: 0 4px 10px rgba(255, 0, 127, 0.3);
}
.toast .t-icon svg { width: 16px; height: 16px; }
.toast .t-title { font-size: 11px; font-weight: 900; color: var(--txt-0); text-transform: uppercase; }
.toast .t-msg { font-size: 10.5px; font-weight: 600; color: var(--txt-2); line-height: 1.4; }
.toast .t-close {
  position: absolute; top: 6px; right: 6px; width: 20px; height: 20px;
  border-radius: 5px; border: none; background: transparent; color: var(--txt-3);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
}

.hint {
  font-size: 10.5px; color: var(--txt-2); line-height: 1.5; padding: 10px 12px;
  background: #fff0f5; border-radius: 10px; border-left: 3px solid var(--love-2); margin-top: 9px;
}
.hint b { color: var(--love-2); font-weight: 800; }
"""


# ============================================================
# TEMPLATE LOGIN TRẮNG
# ============================================================
HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>I Love Ngọc Hân — Đăng Nhập</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_COMMON + """
body { display:flex; align-items:center; justify-content:center; min-height:100vh; padding:18px; }
.card-login {
  position: relative; background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(30px); -webkit-backdrop-filter: blur(30px);
  padding: 38px 26px; border-radius: var(--r-xl);
  border: 1px solid var(--line-1); box-shadow: 0 20px 60px rgba(15, 23, 42, 0.12);
  width: 100%; max-width: 390px; text-align: center; overflow: hidden;
}
.card-login::before { content:''; position:absolute; top:0; left:0; right:0; height:3px; background:var(--grad-rainbow); }
.logo-center {
  width: 86px; height: 86px; border-radius: 50%;
  margin: 0 auto 14px; position: relative; padding: 3px;
  background: var(--grad-love); box-shadow: 0 10px 30px rgba(255, 0, 127, 0.35);
}
.logo-center img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; border: 2px solid #fff; }
h1 {
  font-family: 'Orbitron', sans-serif; font-size: 20px; font-weight: 900;
  background: var(--grad-love); -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; margin-bottom: 4px;
}
p.sub { color: var(--txt-2); margin-bottom: 22px; font-size: 10.5px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; }
.input-wrap { position: relative; margin-bottom: 12px; }
input[type=password] {
  width: 100%; padding: 15px 44px 15px 16px; border: 1.5px solid var(--line-1);
  border-radius: var(--r-md); font-size: 14px; font-weight: 600; background: #fff;
  color: var(--txt-0); transition: all .25s var(--ease-spring);
}
input[type=password]:focus { outline: none; border-color: var(--love-2); box-shadow: 0 0 0 4px rgba(255, 0, 127, 0.12); }
.pw-toggle { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); width: 34px; height: 34px; border: none; background: transparent; color: var(--txt-2); cursor: pointer; font-size: 16px; }
.error { background: #fef2f2; color: #b91c1c; padding: 11px; border-radius: var(--r-md); margin-bottom: 14px; font-size: 11.5px; font-weight: 700; border-left: 3px solid #ef4444; text-align: left; }
.foot { margin-top: 18px; font-size: 9.5px; color: var(--txt-3); font-weight: 800; letter-spacing: 1.5px; text-transform: uppercase; }
.foot b { color: var(--love-2); }
</style>
</head>
<body>
<div class="card-login">
  <div class="logo-center">
    <img src="/static/logo.png" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 100 100\\'><circle cx=\\'50\\' cy=\\'50\\' r=\\'50\\' fill=\\'%23ff3366\\'/><text x=\\'50\\' y=\\'58\\' text-anchor=\\'middle\\' font-size=\\'36\\' fill=\\'white\\'>❤</text></svg>'" alt="Logo">
  </div>
  <h1>I LOVE NGỌC HÂN</h1>
  <p class="sub">White Aesthetic Edition • v34.0</p>
  {% if error %}<div class="error">⚠️ {{ error }}</div>{% endif %}
  <form method="POST" autocomplete="off">
    <div class="input-wrap">
      <input type="password" name="password" id="pw" placeholder="Nhập mật khẩu truy cập..." autofocus required>
      <button type="button" class="pw-toggle" onclick="tgPw()">👁️</button>
    </div>
    <button type="submit" class="btn-rect primary full" style="padding:15px;">💖 Đăng nhập hệ thống</button>
  </form>
  <div class="foot">Bản quyền thuộc về <b>NGỌC HÂN</b></div>
</div>
<script>
function tgPw(){var p=document.getElementById('pw');p.type=p.type==='password'?'text':'password';}
</script>
</body>
</html>
"""


# ============================================================
# TEMPLATE DASHBOARD CHÍNH TRẮNG & BOTTOM DOCK
# ============================================================
HTML_INDEX = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>I Love Ngọc Hân — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_COMMON + """
</style>
</head>
<body>

<!-- TOP HEADER TRẮNG -->
<div class="header">
  <div class="header-inner">
    <div class="logo-wrap">
      <img class="logo-img" src="/static/logo.png" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 100 100\\'><circle cx=\\'50\\' cy=\\'50\\' r=\\'50\\' fill=\\'%23ff3366\\'/><text x=\\'50\\' y=\\'58\\' text-anchor=\\'middle\\' font-size=\\'36\\' fill=\\'white\\'>❤</text></svg>'" alt="Logo">
    </div>
    <div class="header-title-box">
      <h1>I LOVE NGỌC HÂN 💖</h1>
      <p>Universal • v34.0 • Treo Ngôn Trọn Khối</p>
    </div>
    <button class="logout-btn" onclick="location.href='/logout'">
      <span>Thoát</span>
      <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
    </button>
  </div>
</div>

<!-- CONTAINER THÔNG BÁO TOAST THÔNG MINH -->
<div id="toast-stack"></div>

<!-- NỘI DUNG TỪNG PANEL -->
<div class="container">

  <!-- TAB 1: ACC -->
  <div class="panel active" id="panel-accounts">
    <div class="card">
      <h2><span class="badge-icon">+</span> Thêm tài khoản Zalo</h2>
      <div class="form-group"><label>Tên gợi nhớ</label><input id="add-label" placeholder="acc1"></div>
      <div class="form-group"><label>IMEI</label><input id="add-imei" placeholder="000000000000000"></div>
      <div class="form-group"><label>Cookie (JSON)</label><textarea id="add-cookies" placeholder='{"zpw_sek":"...","zpw_ver":"645","zpw_type":"30"}'></textarea></div>
      <button type="button" class="btn-rect primary full" onclick="addAccount()">💾 Lưu tài khoản</button>
    </div>

    <div class="card">
      <h2><span class="badge-icon">≡</span> Danh sách tài khoản</h2>
      <div class="stat-grid">
        <div class="stat"><div class="label">Tổng số</div><div class="value" id="stat-total">0</div></div>
        <div class="stat"><div class="label">Đang bật</div><div class="value" id="stat-active">0</div></div>
        <div class="stat"><div class="label">Đã gửi</div><div class="value" id="stat-sent">0</div></div>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>ID</th><th>Tên</th><th>Tên thật</th><th>UID</th><th>OK/Lỗi</th><th>Risk</th><th>Thao tác</th></tr></thead>
          <tbody id="accounts-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 2: BOX -->
  <div class="panel" id="panel-boxes">
    <div class="card">
      <h2><span class="badge-icon">▦</span> Quản lý hội thoại / Box Chat</h2>
      <div class="form-group"><label>Chọn tài khoản để tải hội thoại</label><select id="load-acc-select"><option value="">-- Chọn tài khoản --</option></select></div>
      <div style="text-align:center; margin: 10px 0;">
        <button type="button" class="btn-circle primary" onclick="loadBoxes()" title="Load danh sách"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg></button>
        <button type="button" class="btn-circle success" onclick="selectAllBoxes()" title="Chọn tất cả"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></button>
        <button type="button" class="btn-circle danger" onclick="clearAllBoxes()" title="Bỏ chọn tất cả"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
      </div>
      <div style="margin-top:10px;">
        <div style="display:flex; justify-content:space-between; margin-bottom:5px; font-size:10px;">
          <b style="color:var(--txt-2); text-transform:uppercase; letter-spacing:.8px;">Đã chọn: <span id="selected-count" style="color:var(--love-1); font-weight:900;">0</span></b>
        </div>
        <div class="box-list" id="box-list"><div style="text-align:center; padding:18px; color:var(--txt-3); font-size:11px;">Chưa tải danh sách box</div></div>
      </div>
    </div>
  </div>

  <!-- TAB 3: FILE -->
  <div class="panel" id="panel-files">
    <div class="card">
      <h2><span class="badge-icon">↑</span> Upload File Tin Nhắn</h2>
      <div class="form-group"><input type="file" id="file-input" accept=".txt" style="padding:7px;"></div>
      <button type="button" class="btn-rect primary full" onclick="uploadFile()">📤 Tải file lên</button>
      <div class="hint">
        💡 Mỗi khối cách nhau bởi <b>dòng trống</b> = 1 tin nhắn.<br>
        <b>Treo ngôn</b>: Dán bao nhiêu dòng cũng gửi trong <b>1 tin nhắn duy nhất</b> (giữ nguyên xuống dòng thật, không chia nhỏ).<br>
        <b>Treo nhây</b>: Tự động tách từng dòng thành tin nhắn riêng, đánh số 1. 2. 3.
      </div>
    </div>
    <div class="card">
      <h2><span class="badge-icon">▤</span> File đã upload</h2>
      <div id="files-list"><div style="text-align:center; padding:18px; color:var(--txt-3); font-size:11px;">Chưa có file nào</div></div>
    </div>
  </div>

  <!-- TAB 4: SPAM -->
  <div class="panel" id="panel-spam">
    <div class="card">
      <h2><span class="badge-icon">▶</span> Cấu hình gửi tin nhắn</h2>

      <div class="form-group">
        <label>⚙️ Chế độ gửi tin</label>
        <div class="mode-grid" id="mode-grid">
          <div class="mode-card active" data-mode="fast">
            <div class="mc-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg></div>
            <div class="mc-title">Siêu nhanh</div>
            <div class="mc-desc">Xoay vòng khối</div>
          </div>
          <div class="mode-card" data-mode="treo_ngon">
            <div class="mc-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/></svg></div>
            <div class="mc-title">Treo ngôn</div>
            <div class="mc-desc">N dòng / 1 tin duy nhất</div>
          </div>
          <div class="mode-card" data-mode="treo_nhay">
            <div class="mc-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg></div>
            <div class="mc-title">Treo nhây</div>
            <div class="mc-desc">N dòng / N tin đánh số</div>
          </div>
        </div>
        <input type="hidden" id="spam-mode" value="fast">
      </div>

      <div class="form-group">
        <label>Chọn file đã upload</label>
        <select id="spam-file-select"><option value="">-- Chọn file --</option></select>
      </div>

      <div class="form-group">
        <label>Hoặc dán trực tiếp nội dung tin nhắn</label>
        <textarea id="spam-messages" placeholder="Dán nội dung vào đây. Nếu chọn Treo Ngôn, 4 dòng hoặc 10 dòng đều sẽ được gửi cùng 1 lúc trong 1 tin nhắn duy nhất!"></textarea>
      </div>

      <div class="form-group">
        <label>🎨 Đổi màu chữ Zalo tự động</label>
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
        <label>⏱ Delay giữa các lần gửi (giây)</label>
        <div class="chip-group" id="delay-chips">
          <div class="chip" data-delay="0.3">0.3s</div>
          <div class="chip" data-delay="0.5">0.5s</div>
          <div class="chip active" data-delay="1">1s</div>
          <div class="chip" data-delay="2">2s</div>
          <div class="chip" data-delay="3">3s</div>
          <div class="chip" data-delay="5">5s</div>
          <div class="chip" data-delay="10">10s</div>
        </div>
        <input type="hidden" id="spam-delay" value="1">
      </div>

      <div class="form-group">
        <label>😈 Icon sát thương tâm lý cuối câu</label>
        <div class="chip-group" id="icon-chips">
          <div class="chip" data-icon="0">0</div>
          <div class="chip" data-icon="2">2</div>
          <div class="chip active" data-icon="3">3</div>
          <div class="chip" data-icon="5">5</div>
          <div class="chip" data-icon="8">8</div>
        </div>
        <input type="hidden" id="icon-count" value="3">
      </div>

      <div class="toggle-group">
        <div class="toggle active" id="tg-emoji" onclick="tgFlag('emoji')">😈 Icon</div>
        <div class="toggle active" id="tg-human" onclick="tgFlag('human')">🧑 Giả người</div>
        <div class="toggle active" id="tg-mention" onclick="tgFlag('mention')">📢 Tag thật</div>
        <div class="toggle active" id="tg-read" onclick="tgFlag('read')">👁️ Đã xem</div>
      </div>

      <div class="form-group">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;text-transform:none;letter-spacing:0;font-size:11.5px;color:var(--txt-0);">
          <input type="checkbox" id="tg-tag" onchange="tgTag()" style="width:auto;">
          Lấy UUID và Tên trong box để Tag
        </label>
        <div id="tag-wrap" style="display:none; margin-top:8px;">
          <div class="form-group"><select id="member-acc-select"><option value="">-- Chọn tài khoản load members --</option></select></div>
          <button type="button" class="btn-rect primary" onclick="loadMembers()">🔄 Tải danh sách thành viên</button>
          <div class="box-list" id="tag-selector" style="margin-top:8px; max-height:220px; display:none;"></div>
          <input type="hidden" id="tag-selected" value="">
        </div>
      </div>
    </div>

    <div style="text-align:center; margin-bottom:14px;">
      <button type="button" class="btn-circle success big" onclick="startSpam()" title="Bắt đầu"><svg viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3"/></svg></button>
      <button type="button" class="btn-circle danger big" onclick="stopAll()" title="Dừng"><svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg></button>
    </div>

    <div class="card">
      <h2><span class="badge-icon">≡</span> Danh sách tiến trình</h2>
      <button type="button" class="btn-circle danger small" onclick="stopAll()" title="Dừng tất cả"><svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg></button>
      <div class="table-wrap" style="margin-top:10px;">
        <table class="table"><thead><tr><th>ID</th><th>Chế độ</th><th>Màu</th><th>Delay</th><th>Trạng thái</th><th>Hành động</th></tr></thead><tbody id="tasks-tbody"></tbody></table>
      </div>
    </div>
  </div>

</div>

<!-- BOTTOM FLOATING DOCK -->
<div class="bottom-dock">
  <button type="button" class="tab active" data-tab="accounts">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
    <div>Acc</div>
  </button>
  <button type="button" class="tab" data-tab="boxes">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
    <div>Box</div>
  </button>
  <button type="button" class="tab" data-tab="files">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
    <div>File</div>
  </button>
  <button type="button" class="tab" data-tab="spam">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
    <div>Spam</div>
  </button>
</div>

<script>
var flags = { emoji: true, human: true, mention: true, read: true };
var selectedBoxes = [];
var selectedTags = [];
var _boxes = [];
var _members = [];
var currentMode = "fast";
var colorMode = "random";
var fixedColor = "red";
var ZALO_COLORS = [];

// ==========================================
// TOAST THÔNG MINH: VUỐT LÊN BIẾN MẤT + KHÔNG CHỒNG + TẮT NHANH (1.4s)
// ==========================================
var Toast = (function(){
  var stack = null;
  function ensure(){
    if(!stack) stack = document.getElementById('toast-stack');
    return stack;
  }
  var ICONS = {
    success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="8" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'
  };

  function show(msg, type, title, duration){
    type = type || 'success';
    duration = duration || 1400; // Tắt nhanh hơn (1.4s)
    var s = ensure();
    if(!s) return;

    // Không chồng chéo: Dọn sạch mọi thông báo cũ ngay lập tức
    var existing = s.querySelectorAll('.toast');
    existing.forEach(function(el){ el.remove(); });

    var toastEl = document.createElement('div');
    toastEl.className = 'toast ' + type;
    toastEl.innerHTML = '<div class="t-icon">' + (ICONS[type] || ICONS.info) + '</div>' +
      '<button type="button" class="t-close">✕</button>' +
      '<div class="t-title">' + (title || 'Thông báo') + '</div>' +
      '<div class="t-msg">' + msg + '</div>';

    s.appendChild(toastEl);

    var autoTimer = setTimeout(dismiss, duration);

    function dismiss(){
      clearTimeout(autoTimer);
      toastEl.classList.add('swipe-out');
      toastEl.addEventListener('animationend', function(){ toastEl.remove(); }, { once: true });
    }

    toastEl.querySelector('.t-close').addEventListener('click', dismiss);

    // Cử chỉ vuốt lên để biến mất ngay lập tức
    var startY = 0;
    toastEl.addEventListener('touchstart', function(e){
      startY = e.touches[0].clientY;
    }, { passive: true });

    toastEl.addEventListener('touchmove', function(e){
      var diff = e.touches[0].clientY - startY;
      if(diff < 0){
        toastEl.style.transform = 'translateY(' + diff + 'px) scale(' + Math.max(0.7, 1 + diff/250) + ')';
        toastEl.style.opacity = Math.max(0, 1 + diff/100);
      }
    }, { passive: true });

    toastEl.addEventListener('touchend', function(e){
      var diff = e.changedTouches[0].clientY - startY;
      if(diff < -25){
        dismiss();
      } else {
        toastEl.style.transform = '';
        toastEl.style.opacity = '';
      }
    });
  }

  return {
    success: function(m, t, d){ show(m, 'success', t, d); },
    error: function(m, t, d){ show(m, 'error', t, d || 1800); },
    warning: function(m, t, d){ show(m, 'warning', t, d); },
    info: function(m, t, d){ show(m, 'info', t, d); }
  };
})();

// TAB SWITCHING
document.querySelectorAll('.bottom-dock .tab').forEach(function(t){
  t.addEventListener('click', function(){
    document.querySelectorAll('.bottom-dock .tab').forEach(function(x){ x.classList.remove('active'); });
    document.querySelectorAll('.panel').forEach(function(x){ x.classList.remove('active'); });
    t.classList.add('active');
    var p = document.getElementById('panel-' + t.dataset.tab);
    if(p) p.classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    refreshAll();
  });
});

// CHẾ ĐỘ SPAM
document.querySelectorAll('.mode-card').forEach(function(c){
  c.addEventListener('click', function(){
    document.querySelectorAll('.mode-card').forEach(function(x){ x.classList.remove('active'); });
    c.classList.add('active');
    currentMode = c.dataset.mode;
    document.getElementById('spam-mode').value = currentMode;
  });
});

// ĐỔI MÀU CHỮ
document.querySelectorAll('#color-mode-group .chip').forEach(function(c){
  c.addEventListener('click', function(){
    document.querySelectorAll('#color-mode-group .chip').forEach(function(x){ x.classList.remove('active'); });
    c.classList.add('active');
    colorMode = c.dataset.cmode;
    document.getElementById('color-mode').value = colorMode;
    var pw = document.getElementById('palette-wrap');
    if(colorMode === 'fixed') pw.style.display = 'flex'; else pw.style.display = 'none';
  });
});

document.querySelectorAll('#delay-chips .chip').forEach(function(c){
  c.addEventListener('click', function(){
    document.querySelectorAll('#delay-chips .chip').forEach(function(x){ x.classList.remove('active'); });
    c.classList.add('active');
    document.getElementById('spam-delay').value = c.dataset.delay;
  });
});

document.querySelectorAll('#icon-chips .chip').forEach(function(c){
  c.addEventListener('click', function(){
    document.querySelectorAll('#icon-chips .chip').forEach(function(x){ x.classList.remove('active'); });
    c.classList.add('active');
    document.getElementById('icon-count').value = c.dataset.icon;
  });
});

function tgFlag(name){
  flags[name] = !flags[name];
  var map = { emoji:'tg-emoji', human:'tg-human', mention:'tg-mention', read:'tg-read' };
  var el = document.getElementById(map[name]);
  if(el) el.classList.toggle('active', flags[name]);
}

function tgTag(){
  var c = document.getElementById('tg-tag');
  var wrap = document.getElementById('tag-wrap');
  if(wrap) wrap.style.display = c.checked ? 'block' : 'none';
}

async function api(url, opts){
  opts = opts || {};
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
    tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--txt-3);padding:18px;">Chưa có tài khoản nào</td></tr>';
  } else {
    tb.innerHTML = accs.map(function(a){
      var risk = (a.risk || 0).toFixed(2);
      var rc = risk > 0.5 ? 'badge-err' : risk > 0.2 ? 'badge-warn' : 'badge-ok';
      var uidShort = a.uid ? String(a.uid).slice(-7) : '?';
      var realName = a.display_name || a.zalo_name || a.username || '—';
      return '<tr><td>' + a.id + '</td>' +
        '<td><b>' + a.label + '</b></td>' +
        '<td><span style="color:var(--love-2);font-weight:700;">' + realName + '</span></td>' +
        '<td><code>…' + uidShort + '</code></td>' +
        '<td><span class="badge badge-ok">' + a.ok_count + '</span> <span class="badge badge-err">' + a.fail_count + '</span></td>' +
        '<td><span class="badge ' + rc + '">' + risk + '</span></td>' +
        '<td>' +
          '<button type="button" class="btn-circle primary small" onclick="checkAcc(' + a.id + ')" title="Check"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg></button>' +
          '<button type="button" class="btn-circle warning small" onclick="resetAcc(' + a.id + ')" title="Reset"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg></button>' +
          '<button type="button" class="btn-circle danger small" onclick="delAcc(' + a.id + ')" title="Xoá"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg></button>' +
        '</td></tr>';
    }).join('');
  }
  document.getElementById('stat-total').textContent = accs.length;
  document.getElementById('stat-active').textContent = accs.filter(function(a){return a.enabled;}).length;
  document.getElementById('stat-sent').textContent = accs.reduce(function(s,a){return s+(a.total_sent||0);},0);

  var s1 = document.getElementById('load-acc-select');
  var s2 = document.getElementById('member-acc-select');
  var opts = '<option value="">-- Chọn tài khoản --</option>' + accs.map(function(a){return '<option value="'+a.id+'">'+a.label+'</option>';}).join('');
  var v1 = s1.value, v2 = s2.value;
  s1.innerHTML = opts; s1.value = v1;
  s2.innerHTML = opts; s2.value = v2;
}

async function addAccount(){
  var label = document.getElementById('add-label').value.trim();
  var imei = document.getElementById('add-imei').value.trim();
  var cookies = document.getElementById('add-cookies').value.trim();
  if(!imei || !cookies){ return Toast.error('Vui lòng điền IMEI và Cookie'); }
  Toast.info('Đang kiểm tra Cookie...');
  var r = await api('/api/accounts/add', { method:'POST', body: JSON.stringify({ label:label, imei:imei, cookies:cookies }) });
  if(r.error){ return Toast.error(r.error, 'Thất bại'); }
  var nameInfo = r.display_name || r.zalo_name || r.username || '?';
  Toast.success('Đã thêm: ' + r.label + ' (' + nameInfo + ')');
  document.getElementById('add-label').value = '';
  document.getElementById('add-imei').value = '';
  document.getElementById('add-cookies').value = '';
  refreshAll();
}

async function delAcc(id){
  if(!confirm('Xác nhận xóa tài khoản #' + id + '?')) return;
  await api('/api/accounts/' + id, { method:'DELETE' });
  Toast.success('Đã xóa #' + id);
  refreshAll();
}

async function resetAcc(id){
  await api('/api/accounts/' + id + '/reset', { method:'POST' });
  Toast.info('Reset risk #' + id);
  refreshAll();
}

async function checkAcc(id){
  Toast.info('Đang kiểm tra #' + id + '...');
  var r = await api('/api/accounts/' + id + '/check', { method:'POST' });
  if(r.error){ return Toast.error(r.error, 'Lỗi'); }
  var nameInfo = r.display_name || r.zalo_name || r.username || '?';
  Toast.success('Live • ' + nameInfo);
}

async function loadBoxes(){
  var aid = document.getElementById('load-acc-select').value;
  if(!aid) return Toast.error('Hãy chọn tài khoản trước');
  Toast.info('Đang tải danh sách Box...');
  var r = await api('/api/accounts/' + aid + '/load_boxes', { method:'POST' });
  if(r.error) return Toast.error(r.error, 'Lỗi');
  var all = (r.groups||[]).concat(r.friends||[]);
  var bl = document.getElementById('box-list');
  if(!all.length){
    bl.innerHTML = '<div style="text-align:center;padding:18px;color:var(--txt-3);">Không có box nào</div>';
    return;
  }
  bl.innerHTML = all.map(function(b,i){
    return '<div class="box-item" data-idx="'+i+'" onclick="tgBox(this, '+i+')"><div class="check">✓</div><div class="info"><div class="name">' + b.name + '</div><div class="meta">' + b.id + ' | ' + b.type + (b.members?(' | '+b.members+' mem'):'') + '</div></div></div>';
  }).join('');
  _boxes = all; selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
  Toast.success('Đã tải ' + all.length + ' box chat');
}

function tgBox(el, idx){
  var b = _boxes[idx]; if(!b) return;
  if(el.classList.contains('selected')){
    el.classList.remove('selected');
    selectedBoxes = selectedBoxes.filter(function(x){return x.id !== b.id;});
  } else {
    el.classList.add('selected');
    selectedBoxes.push(b);
  }
  document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function selectAllBoxes(){
  document.querySelectorAll('.box-item').forEach(function(el){el.classList.add('selected');});
  selectedBoxes = _boxes.slice();
  document.getElementById('selected-count').textContent = selectedBoxes.length;
  Toast.info('Đã chọn ' + selectedBoxes.length + ' box');
}

function clearAllBoxes(){
  document.querySelectorAll('.box-item').forEach(function(el){el.classList.remove('selected');});
  selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
  Toast.info('Đã bỏ chọn tất cả');
}

async function uploadFile(){
  var input = document.getElementById('file-input');
  if(!input.files.length) return Toast.error('Chưa chọn file');
  var fd = new FormData();
  fd.append('file', input.files[0]);
  Toast.info('Đang tải file lên...');
  try {
    var r = await fetch('/api/files/upload', { method:'POST', body: fd }).then(function(x){return x.json();});
    if(r.error) return Toast.error(r.error);
    Toast.success('Upload thành công ' + r.lines + ' khối');
    input.value = ''; loadFiles();
  } catch(e){ Toast.error('Lỗi: ' + e.message); }
}

async function loadFiles(){
  var files = await api('/api/files');
  if(!Array.isArray(files)) files = [];
  var list = document.getElementById('files-list');
  if(!files.length){
    list.innerHTML = '<div style="text-align:center;padding:18px;color:var(--txt-3);font-size:11px;">Chưa có file nào</div>';
  } else {
    list.innerHTML = files.map(function(f){
      var kb = (f.size/1024).toFixed(1);
      return '<div class="box-item"><div class="info"><div class="name">📄 ' + f.filename + '</div><div class="meta">' + f.lines + ' khối • ' + kb + ' KB</div></div>' +
        '<button type="button" class="btn-circle danger small" onclick="delFile('+f.id+')" title="Xoá"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg></button></div>';
    }).join('');
  }
  var s = document.getElementById('spam-file-select');
  var cur = s.value;
  s.innerHTML = '<option value="">-- Chọn file --</option>' + files.map(function(f){return '<option value="'+f.id+'">'+f.filename+' ('+f.lines+' khối)</option>';}).join('');
  s.value = cur;
}

async function delFile(fid){
  if(!confirm('Xác nhận xóa file này?')) return;
  await api('/api/files/' + fid, { method:'DELETE' });
  Toast.success('Đã xóa file'); loadFiles();
}

async function loadMembers(){
  var aid = document.getElementById('member-acc-select').value;
  if(!aid) return Toast.error('Hãy chọn tài khoản');
  var box = selectedBoxes.find(function(b){return b.type === 'group';});
  if(!box) return Toast.error('Cần chọn ít nhất 1 nhóm ở Tab Box');
  Toast.info('Đang tải danh sách thành viên...');
  var r = await api('/api/accounts/' + aid + '/members/' + box.id, { method:'POST' });
  if(r.error) return Toast.error(r.error);
  var mem = r.members || [];
  var sel = document.getElementById('tag-selector');
  sel.style.display = 'block';
  if(!mem.length){
    sel.innerHTML = '<div style="padding:14px;text-align:center;color:var(--txt-3);font-size:11px;">Không có member nào</div>'; return;
  }
  sel.innerHTML = mem.map(function(m,i){
    var sub = [];
    if(m.username) sub.push('@'+m.username);
    if(m.zalo_name && m.zalo_name !== m.name) sub.push(m.zalo_name);
    sub.push(m.id);
    return '<div class="box-item" data-idx="'+i+'" onclick="tgMember(this, '+i+')"><div class="check">✓</div><div class="info"><div class="name">' + m.name + '</div><div class="meta">' + sub.join(' • ') + '</div></div></div>';
  }).join('');
  _members = mem; selectedTags = [];
  Toast.success('Đã tải ' + mem.length + ' thành viên');
}

function tgMember(el, idx){
  var m = _members[idx]; if(!m) return;
  if(el.classList.contains('selected')){
    el.classList.remove('selected');
    selectedTags = selectedTags.filter(function(t){return t.id !== m.id;});
  } else {
    el.classList.add('selected');
    selectedTags.push({ id:m.id, name:m.name });
  }
  document.getElementById('tag-selected').value = JSON.stringify(selectedTags);
}

// BẮT ĐẦU SPAM — HỖ TRỢ TREO NGÔN TRỌN KHỐI
async function startSpam(){
  if(!selectedBoxes.length) return Toast.error('Chưa chọn Box chat mục tiêu');
  var fid = document.getElementById('spam-file-select').value;
  var direct = document.getElementById('spam-messages').value.trim();
  var blocks = [];

  if(fid){
    var r = await api('/api/files/' + fid + '/preview');
    if(r.error) return Toast.error('Lỗi file: ' + r.error);
    blocks = r.all || [];
  } else if(direct){
    if(currentMode === "treo_ngon"){
      // Treo ngôn: Dù 4 hay 10 dòng đều giữ nguyên gửi 1 tin duy nhất!
      blocks = [direct];
    } else {
      if(direct.indexOf(';') !== -1){
        blocks = direct.split(';').map(function(m){return m.trim();}).filter(function(m){return m;});
      } else {
        blocks = [direct];
      }
    }
  }

  if(!blocks.length) return Toast.error('Chưa có nội dung tin nhắn');
  var delay = parseFloat(document.getElementById('spam-delay').value) || 1;
  var iconCount = parseInt(document.getElementById('icon-count').value) || 3;
  if(!flags.emoji) iconCount = 0;
  var tagUsers = document.getElementById('tg-tag').checked ? selectedTags : [];

  var payload = {
    targets: selectedBoxes, blocks: blocks, delay: delay,
    use_emoji: flags.emoji, icon_count: iconCount, tag_users: tagUsers,
    mode: currentMode, color_mode: colorMode, fixed_color: fixedColor,
    typing_speed: "fast", human_mode: flags.human,
    real_mention: flags.mention, read_receipt: flags.read
  };

  var r = await api('/api/tasks/start', { method:'POST', body: JSON.stringify(payload) });
  if(r.error) return Toast.error(r.error);
  Toast.success('Đã kích hoạt: ' + currentMode);
  loadTasks();
}

async function stopAll(){
  await api('/api/tasks/stop_all', { method:'POST' });
  Toast.warning('Đã dừng tất cả tác vụ');
  loadTasks();
}

async function loadTasks(){
  var tasks = await api('/api/tasks');
  if(!Array.isArray(tasks)) tasks = [];
  var tb = document.getElementById('tasks-tbody');
  if(!tasks.length){
    tb.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--txt-3);padding:14px;">Chưa có tiến trình nào</td></tr>'; return;
  }
  tb.innerHTML = tasks.map(function(t){
    var running = t.status === 'running';
    var b = running ? 'badge-ok' : 'badge-err';
    var txt = running ? 'Chạy' : 'Dừng';
    var meta = {};
    try { meta = JSON.parse(t.meta || '{}'); } catch(e){}
    var mode = meta.mode || 'fast';
    var modeLabels = { 'fast':'⚡ Nhanh', 'treo_ngon':'❄️ Ngôn', 'treo_nhay':'🌀 Nhây' };
    var cm = meta.color_mode || 'random';
    var d = meta.delay ? (meta.delay + 's') : '—';
    return '<tr><td><code>' + t.id.split('_').pop() + '</code></td>' +
      '<td><b>' + (modeLabels[mode] || mode) + '</b></td>' +
      '<td><span style="color:var(--love-2); font-weight:700;">' + cm + '</span></td>' +
      '<td><b>' + d + '</b></td>' +
      '<td><span class="badge ' + b + '">' + txt + '</span></td>' +
      '<td>' + (running ? '<button type="button" class="btn-circle danger small" onclick="stopTask(\\'' + t.id + '\\')" title="Dừng"><svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg></button>' : '') + '</td></tr>';
  }).join('');
}

async function stopTask(tid){
  await api('/api/tasks/' + tid + '/stop', { method:'POST' });
  Toast.warning('Đã dừng #' + tid);
  loadTasks();
}

async function loadColors(){
  var cols = await api('/api/colors');
  if(Array.isArray(cols)){
    ZALO_COLORS = cols;
    var pw = document.getElementById('palette-wrap');
    pw.innerHTML = cols.map(function(c){
      return '<div class="chip" data-color="'+c.id+'" style="border-color:'+c.hex+'; color:'+c.hex+'" onclick="pickFixedColor(\\''+c.id+'\\')">'+c.name+'</div>';
    }).join('');
  }
}

function pickFixedColor(cid){
  fixedColor = cid;
  Toast.info('Chọn màu: ' + cid);
}

function refreshAll(){ loadAccounts(); loadFiles(); loadTasks(); }
loadColors();
setInterval(loadTasks, 5000);
refreshAll();
</script>
</body>
</html>
"""


# ============================================================
# TẤT CẢ ROUTE WEB VÀ API FLASK
# ============================================================
@app.route("/")
@login_required
def index():
    return render_template_string(HTML_INDEX)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        return render_template_string(HTML_LOGIN, error="Mật khẩu không chính xác")
    return render_template_string(HTML_LOGIN)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/colors", methods=["GET"])
@login_required
def api_colors():
    return jsonify(ZALO_COLORS)


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
    label = d.get("label", "").strip() or "acc" + str(int(time.time()))
    imei = d.get("imei", "").strip()
    ck = d.get("cookies", "").strip()
    if not imei or not ck:
        return jsonify({"error": "Thiếu IMEI hoặc Cookie"}), 400
    try:
        ck_obj = json.loads(ck)
    except Exception:
        return jsonify({"error": "Cookie phải là định dạng JSON hợp lệ"}), 400
    try:
        z = Zalo(imei, ck_obj)
        uid = z.uid
        dn = z.display_name or ""
        zn = z.zalo_name or ""
        un = z.username or ""
    except Exception as e:
        return jsonify({"error": "Cookie hỏng hoặc hết hạn: " + str(e)}), 400
    conn = db()
    conn.execute("""
        INSERT INTO accounts (label, imei, cookies, added_at,
                             uid, display_name, zalo_name, username)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (label, imei, json.dumps(ck_obj), time.time(),
          uid, dn, zn, un))
    conn.commit(); conn.close()
    return jsonify({"ok": True, "label": label, "uid": uid,
                    "display_name": dn, "zalo_name": zn, "username": un})


@app.route("/api/accounts/<int:aid>", methods=["DELETE"])
@login_required
def api_accounts_delete(aid):
    conn = db()
    conn.execute("DELETE FROM accounts WHERE id = ?", (aid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/accounts/<int:aid>/reset", methods=["POST"])
@login_required
def api_accounts_reset(aid):
    conn = db()
    conn.execute("UPDATE accounts SET risk = 0, enabled = 1 WHERE id = ?", (aid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/accounts/<int:aid>/check", methods=["POST"])
@login_required
def api_accounts_check(aid):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Không tìm thấy tài khoản"}), 404
    try:
        z = Zalo(row["imei"], json.loads(row["cookies"]))
        return jsonify({"ok": True, "uid": z.uid,
                        "display_name": z.display_name or "",
                        "zalo_name": z.zalo_name or "",
                        "username": z.username or ""})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


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
        gs = z.groups()
        fs = z.friends()
        return jsonify({"ok": True, "groups": gs, "friends": fs,
                        "total": len(gs) + len(fs)})
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
        return jsonify({"ok": True, "members": members, "count": len(members)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/files", methods=["GET"])
@login_required
def api_files_list():
    conn = db()
    rows = conn.execute("""
        SELECT id, filename, lines, size, uploaded_at
        FROM files ORDER BY id DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/files/upload", methods=["POST"])
@login_required
def api_files_upload():
    if "file" not in request.files:
        return jsonify({"error": "Không có tệp tải lên"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Tên tệp rỗng"}), 400
    safe = str(int(time.time())) + "_" + f.filename
    fp = os.path.join(UPLOAD_DIR, safe)
    f.save(fp)
    blocks = parse_blocks(fp, max_blocks=5000)
    size = os.path.getsize(fp)
    conn = db()
    conn.execute("""
        INSERT INTO files (filename, filepath, lines, size, uploaded_at)
        VALUES (?, ?, ?, ?, ?)
    """, (f.filename, fp, len(blocks), size, time.time()))
    conn.commit(); conn.close()
    return jsonify({"ok": True, "filename": f.filename,
                    "lines": len(blocks), "preview": blocks[:3]})


@app.route("/api/files/<int:fid>", methods=["DELETE"])
@login_required
def api_files_delete(fid):
    conn = db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    if not row:
        conn.close(); return jsonify({"error": "Không tìm thấy tệp"}), 404
    try:
        if os.path.exists(row["filepath"]): os.remove(row["filepath"])
    except Exception: pass
    conn.execute("DELETE FROM files WHERE id = ?", (fid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/files/<int:fid>/preview", methods=["GET"])
@login_required
def api_files_preview(fid):
    conn = db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Không tìm thấy tệp"}), 404
    blocks = parse_blocks(row["filepath"], max_blocks=5000)
    return jsonify({"filename": row["filename"], "total": len(blocks),
                    "preview": blocks[:5], "all": blocks})


@app.route("/api/tasks", methods=["GET"])
@login_required
def api_tasks():
    conn = db()
    rows = conn.execute(
        "SELECT * FROM tasks ORDER BY started_at DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tasks/start", methods=["POST"])
@login_required
def api_tasks_start():
    d = request.json
    targets = d.get("targets", [])
    blocks = d.get("blocks", [])
    try:
        delay = float(d.get("delay", 1))
    except Exception:
        return jsonify({"error": "Delay không hợp lệ"}), 400

    use_emoji = bool(d.get("use_emoji", True))
    icon_count = int(d.get("icon_count", 3))
    if not use_emoji: icon_count = 0

    tag_users = d.get("tag_users", [])
    mode = d.get("mode", "fast")
    color_mode = d.get("color_mode", "random")
    fixed_color = d.get("fixed_color", None)
    typing_speed = d.get("typing_speed", "fast")
    human_mode = bool(d.get("human_mode", True))
    real_mention = bool(d.get("real_mention", True))
    read_receipt = bool(d.get("read_receipt", True))

    if not targets:
        return jsonify({"error": "Chưa chọn Box chat mục tiêu"}), 400
    if not blocks:
        return jsonify({"error": "Chưa có nội dung tin nhắn"}), 400
    if delay < AntiBan.MIN_DELAY:
        return jsonify({"error": "Delay tối thiểu " + str(AntiBan.MIN_DELAY) + "s"}), 400
    if delay > AntiBan.MAX_DELAY:
        return jsonify({"error": "Delay tối đa " + str(AntiBan.MAX_DELAY) + "s"}), 400
    if icon_count < 0: icon_count = 0
    if icon_count > 20: icon_count = 20
    if mode not in ("fast", "treo_ngon", "treo_nhay"): mode = "fast"
    if color_mode not in ("none", "random", "fixed", "cycle"): color_mode = "random"
    if color_mode == "fixed" and fixed_color not in COLOR_IDS:
        return jsonify({"error": "Màu cố định không hợp lệ"}), 400

    conn = db()
    cnt = conn.execute(
        "SELECT COUNT(*) as c FROM accounts WHERE enabled = 1"
    ).fetchone()["c"]
    conn.close()
    if cnt == 0:
        return jsonify({"error": "Kho tài khoản trống hoặc chưa có tài khoản nào được bật"}), 400

    tid = new_tid("spam")
    stop_ev = threading.Event()
    th = threading.Thread(
        target=spam_worker,
        args=(tid, targets, blocks, delay,
              use_emoji, icon_count, tag_users, stop_ev,
              mode, color_mode, fixed_color,
              typing_speed, human_mode, real_mention, read_receipt),
        daemon=True,
    )

    conn = db()
    conn.execute("""
        INSERT INTO tasks (id, type, meta, status, started_at, stats)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tid, "spam",
          json.dumps({"targets": len(targets), "blocks": len(blocks),
                      "delay": delay, "tags": len(tag_users),
                      "mode": mode, "color_mode": color_mode,
                      "fixed_color": fixed_color,
                      "typing_speed": typing_speed, "human_mode": human_mode,
                      "real_mention": real_mention}),
          "running", time.time(), "{}"))
    conn.commit(); conn.close()

    ACTIVE_TASKS[tid] = {"stop": stop_ev, "thread": th}
    th.start()

    return jsonify({"ok": True, "task_id": tid, "mode": mode,
                    "delay": delay, "color_mode": color_mode})


@app.route("/api/tasks/<tid>/stop", methods=["POST"])
@login_required
def api_tasks_stop(tid):
    if tid in ACTIVE_TASKS:
        ACTIVE_TASKS[tid]["stop"].set()
        return jsonify({"ok": True})
    return jsonify({"error": "Không tìm thấy tác vụ"}), 404


@app.route("/api/tasks/stop_all", methods=["POST"])
@login_required
def api_tasks_stop_all():
    for tid, t in list(ACTIVE_TASKS.items()):
        t["stop"].set()
    return jsonify({"ok": True, "count": len(ACTIVE_TASKS)})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "alb-forge", "version": "34.0"})


# ============================================================
# RUN SERVER
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
