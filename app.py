# ============================================================
# ALB FORGE v33.5 — I LOVE NGỌC HÂN EDITION (BOTTOM DOCK UI)
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
# ZALO ICON
# ============================================================
ZALO_ICON_HARD = [
    ";f", ":d", "=))", "b-)", ";-A", ":-bd",
    ":-R", ":-L", ":-F", "x-)", ":v", ":3",
    ":>", ":$", ";)p", ";;)", ":p", ":-p",
    ":-d", "8-)", ":-*", ":-h", ":-?", ":-s",
    ":-x", ":x", ":-o", ":o", ":-|", ":|",
    "/-no", "/-ok", "/-v", "/-punch", "/-bad",
    "/-shit", "/-li", "/-strong", "/-weak",
    "/-fade", "/-bome", "/-bd", "/-thanks",
    "/-share", "/-loveu", "/-rose", "/-coffee",
    "/-beer", "/-cake", "/-heart", "/-break",
    "/-flag", "/-showlove", ":-bye", ">-)",
    "p-(", ":--|", ":-DIG", ":-bye", "8-|",
    "/-cake", ";-!", ":-t", "=d>", ":q",
]

ZALO_ICON_UNICODE = [
    "💖", "💕", "✨", "🌸", "🤣", "😂", "😹", "😏", "😜",
    "😝", "🤪", "😈", "👊", "💩", "🔥", "💢", "🗿",
    "😆", "🙄", "😒", "🥰", "😍", "💫", "❤️", "🌹"
]


def get_icon_hard():
    if random.random() < 0.5:
        return random.choice(ZALO_ICON_HARD)
    return random.choice(ZALO_ICON_UNICODE)


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
    {"id": "brown",  "name": "Nâu",      "hex": "#a87050"},
    {"id": "black",  "name": "Đen",      "hex": "#1a1a1a"},
    {"id": "gray",   "name": "Xám",      "hex": "#8a8a8a"},
    {"id": "white",  "name": "Trắng",    "hex": "#ffffff"},
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
# ZALO API
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
            raise Exception("Không lấy được encryption key")
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
        except Exception as e:
            print("[MEMBERS] batch fail: " + str(e))
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
            name = m.get("name", "")
            uid = m.get("uid") or m.get("id")
            if not name or not uid: continue
            tag_str = "@" + name
            if final: final = final + " " + tag_str
            else: final = tag_str
            pos = final.rfind(tag_str)
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
        print("[FILE] error: " + str(e))
    return blocks


# ============================================================
# WORKER
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

    print("[SPAM] Start: " + tid)

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
                lines = [ln for ln in raw.split("\n") if ln.strip()]
                if use_emoji and icon_count > 0 and lines:
                    lines[-1] = AntiBan.append_icons(lines[-1], icon_count)

                if human_mode:
                    humanize_typing(z, target_id, is_group, len(raw), typing_speed)

                text_full = "\n".join(lines)
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

        if human_mode:
            actual = base * random.uniform(0.92, 1.18)
        else:
            actual = base

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
# AUTH
# ============================================================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


# ============================================================
# LOGO SVG: I LOVE NGỌC HÂN (GLOWING HEART & WINGS EMBLEM)
# ============================================================
LOGO_SVG = """<svg viewBox="0 0 160 160" xmlns="http://www.w3.org/2000/svg" fill="none">
<defs>
  <linearGradient id="heartGrad" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#ff007f"/>
    <stop offset="50%" stop-color="#ff3366"/>
    <stop offset="100%" stop-color="#7928ca"/>
  </linearGradient>
  <linearGradient id="goldGrad" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#ffe259"/>
    <stop offset="100%" stop-color="#ffa751"/>
  </linearGradient>
  <linearGradient id="wingGrad" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#00f2fe"/>
    <stop offset="100%" stop-color="#4facfe"/>
  </linearGradient>
  <filter id="neonGlow" x="-30%" y="-30%" width="160%" height="160%">
    <feGaussianBlur stdDeviation="3.5" result="blur"/>
    <feMerge>
      <feMergeNode in="blur"/>
      <feMergeNode in="SourceGraphic"/>
    </feMerge>
  </filter>
</defs>
<circle cx="80" cy="80" r="74" stroke="url(#heartGrad)" stroke-width="1.8" stroke-dasharray="4 8" opacity="0.6">
  <animateTransform attributeName="transform" type="rotate" from="0 80 80" to="360 80 80" dur="20s" repeatCount="indefinite"/>
</circle>
<!-- Wings -->
<g opacity="0.9" filter="url(#neonGlow)">
  <path d="M40 70 C20 62 12 45 28 32 C38 42 48 55 58 68 Z" fill="url(#wingGrad)" opacity="0.8"/>
  <path d="M120 70 C140 62 148 45 132 32 C122 42 112 55 102 68 Z" fill="url(#wingGrad)" opacity="0.8"/>
  <path d="M48 82 C30 80 18 68 28 54 C40 62 50 72 58 80 Z" fill="url(#wingGrad)" opacity="0.6"/>
  <path d="M112 82 C130 80 142 68 132 54 C120 62 110 72 102 80 Z" fill="url(#wingGrad)" opacity="0.6"/>
</g>
<!-- Heart -->
<g filter="url(#neonGlow)">
  <path d="M80 118 C80 118 42 94 42 66 C42 48 56 38 70 46 C76 50 80 56 80 56 C80 56 84 50 90 46 C104 38 118 48 118 66 C118 94 80 118 80 118 Z"
        fill="url(#heartGrad)"/>
  <path d="M78 60 C78 60 52 75 52 90" stroke="#ffffff" stroke-width="2.5" stroke-linecap="round" opacity="0.5"/>
</g>
<!-- Little Crown on Top -->
<polygon points="68,36 74,44 80,32 86,44 92,36 90,48 70,48" fill="url(#goldGrad)" filter="url(#neonGlow)"/>
<circle cx="80" cy="28" r="2.8" fill="#ffd700" filter="url(#neonGlow)"/>
<!-- Sparkles -->
<circle cx="34" cy="40" r="2" fill="#fff">
  <animate attributeName="opacity" values="0.2;1;0.2" dur="2s" repeatCount="indefinite"/>
</circle>
<circle cx="126" cy="40" r="2" fill="#fff">
  <animate attributeName="opacity" values="1;0.2;1" dur="2s" repeatCount="indefinite"/>
</circle>
<!-- Text Ribbon -->
<rect x="20" y="124" width="120" height="26" rx="13" fill="#111827" stroke="url(#goldGrad)" stroke-width="1.6"/>
<text x="80" y="141" text-anchor="middle" font-family="'Orbitron', sans-serif" font-weight="900" font-size="9" fill="#ffffff" letter-spacing="1">
  I ❤ NGỌC HÂN
</text>
</svg>"""


# ============================================================
# CSS ROOT & ENHANCED EFFECTS
# ============================================================
CSS_ROOT = """
:root{
  --bg-0:#0f172a; --bg-1:#1e293b; --bg-2:#283548; --bg-card:rgba(30,41,59,0.85);
  --bg-glass:rgba(255,255,255,0.06);
  --line:rgba(255,255,255,0.08); --line-2:rgba(255,255,255,0.14);
  --txt-0:#ffffff; --txt-1:#f1f5f9; --txt-2:#94a3b8; --txt-3:#64748b;
  --love-1:#ff007f; --love-2:#ff3366; --love-3:#7928ca; --love-cyan:#00f2fe;
  --ok:#10b981; --err:#ef4444; --warn:#f59e0b; --info:#3b82f6;
  --grad-love:linear-gradient(135deg, #ff007f 0%, #ff3366 50%, #7928ca 100%);
  --grad-glow:radial-gradient(circle, rgba(255,0,127,0.3) 0%, transparent 70%);
  --grad-bar:linear-gradient(90deg, #ff007f, #00f2fe, #ff3366, #7928ca);
  --r-sm:10px; --r-md:14px; --r-lg:20px; --r-xl:26px;
  --ease:cubic-bezier(0.16, 1, 0.3, 1);
  --ease-spring:cubic-bezier(0.34, 1.56, 0.64, 1);
}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{touch-action:manipulation;-webkit-text-size-adjust:100%}
body{
  font-family:'Inter',system-ui,-apple-system,sans-serif;
  background:#090d16;
  color:var(--txt-1);
  min-height:100vh;
  padding-bottom:100px; /* Space for the bottom floating dock */
  overflow-x:hidden;
  background-image:
    radial-gradient(1000px 600px at 15% 10%, rgba(255,0,127,0.12), transparent 70%),
    radial-gradient(900px 500px at 85% 90%, rgba(0,242,254,0.08), transparent 70%),
    radial-gradient(600px 400px at 50% 50%, rgba(121,40,202,0.08), transparent 70%);
  background-attachment:fixed;
}
button,input,textarea,select{font-family:inherit}
::selection{background:rgba(255,0,127,0.4);color:#fff}
*::-webkit-scrollbar{width:6px;height:6px}
*::-webkit-scrollbar-track{background:transparent}
*::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.18);border-radius:99px}
:focus-visible{outline:2px solid var(--love-2);outline-offset:2px;border-radius:6px}
"""


# ============================================================
# HTML LOGIN
# ============================================================
HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>I Love Ngọc Hân — Login</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_ROOT + """
body{display:flex;align-items:center;justify-content:center;min-height:100vh;min-height:100dvh;padding:20px;padding-bottom:20px}
.card-login{
  position:relative;background:rgba(20,27,45,0.78);
  backdrop-filter:blur(30px) saturate(190%);
  -webkit-backdrop-filter:blur(30px) saturate(190%);
  padding:42px 30px;border-radius:var(--r-xl);
  border:1px solid rgba(255,0,127,0.25);
  box-shadow:0 25px 70px rgba(0,0,0,0.6), 0 0 40px rgba(255,0,127,0.15);
  width:100%;max-width:420px;text-align:center;animation:cardIn .8s var(--ease) both;
  overflow:hidden;
}
.card-login::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--grad-bar)}
@keyframes cardIn{from{opacity:0;transform:translateY(30px) scale(.95)}to{opacity:1;transform:translateY(0) scale(1)}}
.logo-box{width:125px;height:125px;margin:0 auto 16px;filter:drop-shadow(0 10px 25px rgba(255,0,127,0.45));animation:pulse 3.5s ease-in-out infinite}
@keyframes pulse{0%,100%{transform:scale(1) translateY(0)}50%{transform:scale(1.04) translateY(-5px)}}
.logo-box svg{width:100%;height:100%}
h1{font-family:'Orbitron',sans-serif;font-size:22px;font-weight:900;letter-spacing:1.5px;background:var(--grad-love);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:6px}
p.sub{color:var(--txt-2);margin-bottom:24px;font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase}
.input-wrap{position:relative;margin-bottom:12px}
input[type=password]{width:100%;padding:16px 48px 16px 18px;border:1.5px solid var(--line-2);border-radius:var(--r-md);font-size:15px;font-weight:600;background:rgba(15,23,42,0.7);color:#fff;transition:all .3s var(--ease)}
input[type=password]:focus{outline:none;border-color:var(--love-1);background:#0f172a;box-shadow:0 0 0 4px rgba(255,0,127,0.2)}
.pw-toggle{position:absolute;right:8px;top:50%;transform:translateY(-50%);width:36px;height:36px;border:none;background:transparent;color:var(--txt-2);cursor:pointer;font-size:17px}
button.submit{width:100%;padding:16px;margin-top:14px;background:var(--grad-love);color:#fff;border:none;border-radius:var(--r-md);font-size:14px;font-weight:900;letter-spacing:1.5px;cursor:pointer;text-transform:uppercase;box-shadow:0 12px 35px rgba(255,0,127,0.4);transition:all .3s var(--ease-spring)}
button.submit:hover{transform:translateY(-2px) scale(1.02);box-shadow:0 18px 45px rgba(255,0,127,0.55)}
.error{background:rgba(239,68,68,0.2);color:#fca5a5;padding:12px;border-radius:var(--r-md);margin-bottom:16px;font-size:12px;font-weight:700;border:1px solid rgba(239,68,68,0.4)}
.foot{margin-top:22px;font-size:10px;color:var(--txt-3);font-weight:700;letter-spacing:2px;text-transform:uppercase}
.foot b{color:var(--love-2)}
</style>
</head>
<body>
<div class="card-login">
  <div class="logo-box">""" + LOGO_SVG + """</div>
  <h1>I LOVE NGỌC HÂN</h1>
  <p class="sub">Special Edition • v33.5</p>
  {% if error %}<div class="error">⚠️ {{ error }}</div>{% endif %}
  <form method="POST" autocomplete="off">
    <div class="input-wrap">
      <input type="password" name="password" id="pw" placeholder="Nhập mật khẩu truy cập..." autofocus required>
      <button type="button" class="pw-toggle" onclick="tgPw()">👁️</button>
    </div>
    <button type="submit" class="submit">💖 Vào hệ thống</button>
  </form>
  <div class="foot">Designed with Love for <b>NGỌC HÂN</b></div>
</div>
<script>
function tgPw(){var p=document.getElementById('pw');p.type=p.type==='password'?'text':'password';}
</script>
</body>
</html>
"""


# ============================================================
# HTML INDEX: BOTTOM DOCK TABS + MODERN NEON GLASS UI
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
""" + CSS_ROOT + """

/* HEADER */
.header{
  background:rgba(15,23,42,0.85);
  backdrop-filter:blur(25px) saturate(180%);
  -webkit-backdrop-filter:blur(25px) saturate(180%);
  padding:12px 18px;
  padding-top:calc(12px + env(safe-area-inset-top,0px));
  border-bottom:1px solid var(--line);
  position:sticky;top:0;z-index:100;
  box-shadow:0 4px 20px rgba(0,0,0,0.3);
}
.header::after{content:'';position:absolute;left:0;right:0;bottom:0;height:2px;background:var(--grad-bar)}
.header-inner{max-width:1100px;margin:0 auto;display:flex;align-items:center;gap:12px}
.logo-mini{
  width:44px;height:44px;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  background:rgba(255,255,255,0.04);border-radius:14px;
  border:1px solid rgba(255,0,127,0.3);padding:3px;
  box-shadow:0 0 15px rgba(255,0,127,0.25);
}
.logo-mini svg{width:100%;height:100%}
.header-info{flex:1;min-width:0}
.header-info h1{
  font-family:'Orbitron',sans-serif;font-size:15px;font-weight:900;letter-spacing:1px;
  background:var(--grad-love);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
  display:flex;align-items:center;gap:6px;
}
.header-info p{font-size:9.5px;color:var(--txt-2);font-weight:700;margin-top:2px;letter-spacing:1px;text-transform:uppercase}
.logout-btn{
  display:inline-flex;align-items:center;gap:6px;
  background:rgba(255,255,255,0.05);color:var(--txt-1);
  border:1px solid var(--line-2);padding:8px 14px;border-radius:12px;
  font-size:11px;font-weight:800;cursor:pointer;transition:all .3s var(--ease);
}
.logout-btn:hover{background:rgba(239,68,68,0.2);border-color:var(--err);color:#fca5a5}
.logout-btn svg{width:14px;height:14px}

/* MAIN CONTAINER */
.container{max-width:1050px;margin:0 auto;padding:16px 14px}

/* PANELS */
.panel{display:none;animation:fadePanel .35s var(--ease)}
.panel.active{display:block}
@keyframes fadePanel{from{opacity:0;transform:translateY(12px) scale(.99)}to{opacity:1;transform:translateY(0) scale(1)}}

/* CARDS */
.card{
  position:relative;background:var(--bg-card);
  backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
  padding:18px;border-radius:var(--r-lg);
  border:1px solid var(--line-2);
  box-shadow:0 8px 30px rgba(0,0,0,0.35);margin-bottom:16px;
  transition:all .3s var(--ease);
}
.card:hover{border-color:rgba(255,0,127,0.35);box-shadow:0 10px 35px rgba(255,0,127,0.1)}
.card h2{
  font-size:12.5px;font-weight:900;letter-spacing:.8px;margin-bottom:14px;
  display:flex;align-items:center;gap:10px;color:#fff;text-transform:uppercase;
}
.card h2 .bi{
  width:28px;height:28px;border-radius:9px;background:var(--grad-love);
  display:flex;align-items:center;justify-content:center;font-size:13px;color:#fff;
  box-shadow:0 4px 14px rgba(255,0,127,0.35);
}

/* FORMS */
.form-group{margin-bottom:13px}
.form-group label{display:block;margin-bottom:6px;font-size:10px;font-weight:800;color:var(--txt-2);text-transform:uppercase;letter-spacing:.9px}
.form-group input,.form-group textarea,.form-group select{
  width:100%;padding:12px 14px;border:1.5px solid var(--line-2);border-radius:12px;
  font-size:13px;font-weight:500;background:rgba(15,23,42,0.85);color:#fff;
  transition:all .25s var(--ease);
}
.form-group input::placeholder,.form-group textarea::placeholder{color:var(--txt-3)}
.form-group input:focus,.form-group textarea:focus,.form-group select:focus{
  outline:none;border-color:var(--love-1);background:#090d16;
  box-shadow:0 0 0 4px rgba(255,0,127,0.18);
}
.form-group textarea{min-height:92px;resize:vertical;font-family:'JetBrains Mono',monospace;font-size:12px;line-height:1.55}
.form-group select{
  appearance:none;-webkit-appearance:none;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23ff3366' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat:no-repeat;background-position:right 14px center;padding-right:36px;cursor:pointer;
}

/* BUTTONS */
.btn-circle{
  width:46px;height:46px;border-radius:50%;border:none;cursor:pointer;
  display:inline-flex;align-items:center;justify-content:center;color:#fff;
  transition:all .3s var(--ease-spring);position:relative;overflow:hidden;margin:4px;
}
.btn-circle svg{width:20px;height:20px}
.btn-circle:hover{transform:translateY(-3px) scale(1.08);filter:brightness(1.15)}
.btn-circle:active{transform:translateY(0) scale(.96)}
.btn-circle.primary{background:var(--grad-love);box-shadow:0 6px 20px rgba(255,0,127,0.4)}
.btn-circle.danger{background:linear-gradient(135deg,#ef4444,#dc2626);box-shadow:0 6px 20px rgba(239,68,68,0.4)}
.btn-circle.success{background:linear-gradient(135deg,#10b981,#059669);box-shadow:0 6px 20px rgba(16,185,129,0.4)}
.btn-circle.warning{background:linear-gradient(135deg,#f59e0b,#d97706);box-shadow:0 6px 20px rgba(245,158,11,0.4)}
.btn-circle.info{background:linear-gradient(135deg,#3b82f6,#2563eb);box-shadow:0 6px 20px rgba(59,130,246,0.4)}
.btn-circle.small{width:32px;height:32px}
.btn-circle.small svg{width:14px;height:14px}
.btn-circle.big{width:64px;height:64px}
.btn-circle.big svg{width:26px;height:26px}

.btn-rect{
  padding:12px 18px;border:none;border-radius:12px;cursor:pointer;font-size:11.5px;
  font-weight:900;letter-spacing:.6px;color:#fff;text-transform:uppercase;
  display:inline-flex;align-items:center;gap:7px;transition:all .3s var(--ease-spring);
}
.btn-rect:hover{transform:translateY(-2px);filter:brightness(1.1)}
.btn-rect:active{transform:translateY(0) scale(.98)}
.btn-rect.primary{background:var(--grad-love);box-shadow:0 8px 25px rgba(255,0,127,0.35)}
.btn-rect.danger{background:linear-gradient(135deg,#ef4444,#dc2626);box-shadow:0 6px 20px rgba(239,68,68,0.35)}
.btn-rect.info{background:linear-gradient(135deg,#00f2fe,#4facfe);color:#051329}
.btn-rect.full{width:100%;justify-content:center}

/* STATS */
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(95px,1fr));gap:8px;margin-bottom:14px}
.stat{
  position:relative;background:rgba(15,23,42,0.7);padding:13px 12px;
  border-radius:var(--r-md);border:1px solid var(--line-2);overflow:hidden;
}
.stat::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--grad-bar)}
.stat .label{font-size:9px;color:var(--txt-2);margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;font-weight:800}
.stat .value{font-size:20px;font-weight:900;color:#fff;line-height:1;font-family:'Orbitron',sans-serif}

/* TABLE */
.table-wrap{overflow-x:auto;border-radius:var(--r-md);border:1px solid var(--line-2);background:rgba(15,23,42,0.7)}
.table{width:100%;border-collapse:collapse}
.table th,.table td{padding:10px 9px;text-align:left;font-size:11px;border-bottom:1px solid var(--line);white-space:nowrap}
.table th{background:rgba(255,255,255,0.03);font-weight:800;color:var(--txt-2);text-transform:uppercase;font-size:9px;letter-spacing:1px}
.table tbody tr:hover{background:rgba(255,255,255,0.025)}
.table td code{background:rgba(255,255,255,0.08);padding:3px 7px;border-radius:6px;font-size:10px;font-family:'JetBrains Mono',monospace;color:var(--love-cyan)}

.badge{display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:20px;font-size:9.5px;font-weight:800}
.badge::before{content:'';width:5px;height:5px;border-radius:50%;background:currentColor}
.badge-ok{background:rgba(16,185,129,0.2);color:#34d399}
.badge-err{background:rgba(239,68,68,0.2);color:#f87171}
.badge-warn{background:rgba(245,158,11,0.2);color:#fbbf24}
.badge-info{background:rgba(59,130,246,0.2);color:#60a5fa}

/* LIST ITEMS */
.box-list{max-height:320px;overflow-y:auto;border:1px solid var(--line-2);border-radius:var(--r-md);padding:8px;background:rgba(15,23,42,0.7)}
.box-item{
  padding:11px;border-radius:11px;background:rgba(30,41,59,0.7);margin-bottom:6px;
  cursor:pointer;border:1px solid var(--line);display:flex;align-items:center;gap:10px;
  transition:all .25s var(--ease);
}
.box-item:hover{border-color:var(--love-2);transform:translateX(3px);background:rgba(30,41,59,0.9)}
.box-item.selected{border-color:var(--love-1);background:rgba(255,0,127,0.12)}
.box-item .check{
  width:20px;height:20px;border:2px solid var(--txt-3);border-radius:6px;
  display:flex;align-items:center;justify-content:center;font-size:11px;color:transparent;
  font-weight:900;flex-shrink:0;transition:all .25s var(--ease);
}
.box-item.selected .check{background:var(--love-1);border-color:var(--love-1);color:#fff}
.box-item .info{flex:1;min-width:0}
.box-item .name{font-weight:700;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#fff}
.box-item .meta{font-size:10px;color:var(--txt-2);font-family:'JetBrains Mono',monospace;margin-top:2px}

.file-item{
  display:flex;align-items:center;gap:10px;padding:12px;border-radius:12px;
  background:rgba(15,23,42,0.7);margin-bottom:8px;border:1px solid var(--line-2);
  transition:all .25s var(--ease);
}
.file-item:hover{border-color:var(--love-cyan);box-shadow:0 3px 12px rgba(0,242,254,0.15)}
.file-item .info{flex:1;min-width:0}
.file-item .name{font-weight:700;font-size:12px;color:#fff}
.file-item .meta{font-size:10px;color:var(--txt-2);margin-top:3px}

/* CHIPS & TOGGLES */
.chip-group{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.chip{
  padding:7px 14px;background:rgba(15,23,42,0.8);color:var(--txt-2);border-radius:20px;
  font-size:11px;font-weight:800;cursor:pointer;border:1px solid var(--line-2);transition:all .25s var(--ease-spring);
}
.chip:hover{border-color:var(--love-2);color:#fff;transform:translateY(-2px)}
.chip.active{background:var(--grad-love);color:#fff;border-color:transparent;box-shadow:0 4px 15px rgba(255,0,127,0.4);transform:translateY(-2px)}

.toggle-group{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}
.toggle{
  padding:12px 10px;border:1px solid var(--line-2);border-radius:var(--r-md);
  cursor:pointer;text-align:center;font-weight:800;font-size:11px;
  background:rgba(15,23,42,0.8);color:var(--txt-2);text-transform:uppercase;transition:all .3s var(--ease-spring);
}
.toggle.active{background:var(--grad-love);color:#fff;border-color:transparent;box-shadow:0 4px 15px rgba(255,0,127,0.35);transform:translateY(-2px)}

.mode-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:7px}
.mode-card{
  padding:14px 8px;border-radius:14px;cursor:pointer;background:rgba(15,23,42,0.8);
  border:1.5px solid var(--line-2);text-align:center;transition:all .3s var(--ease-spring);
}
.mode-card:hover{transform:translateY(-3px);border-color:var(--love-1)}
.mode-card.active{background:var(--grad-love);border-color:transparent;color:#fff;box-shadow:0 8px 25px rgba(255,0,127,0.45);transform:translateY(-3px)}
.mode-card .mc-icon{width:32px;height:32px;margin:0 auto 6px;display:flex;align-items:center;justify-content:center}
.mode-card .mc-icon svg{width:24px;height:24px}
.mode-card .mc-title{font-size:11px;font-weight:900;letter-spacing:.5px;margin-bottom:3px;text-transform:uppercase}
.mode-card .mc-desc{font-size:9px;opacity:0.8}

.color-mode-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:6px}
.color-mode{
  padding:10px 6px;border-radius:11px;cursor:pointer;background:rgba(15,23,42,0.8);
  border:1px solid var(--line-2);text-align:center;font-size:10px;font-weight:800;color:var(--txt-2);
  text-transform:uppercase;transition:all .25s var(--ease);
}
.color-mode.active{background:var(--grad-love);color:#fff;border-color:transparent;box-shadow:0 4px 14px rgba(255,0,127,0.35)}
.color-palette{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin-top:8px;display:none}
.color-palette.show{display:grid}
.color-swatch{position:relative;aspect-ratio:1;border-radius:9px;cursor:pointer;border:2px solid transparent;transition:all .25s var(--ease-spring)}
.color-swatch:hover{transform:scale(1.1)}
.color-swatch.active{border-color:#fff;box-shadow:0 0 0 3px rgba(255,0,127,0.6);transform:scale(1.12)}
.color-preview{margin-top:8px;padding:10px 14px;border-radius:10px;background:rgba(15,23,42,0.8);border:1px dashed var(--line-2);font-size:12px;font-weight:700;font-family:'JetBrains Mono',monospace;text-align:center}

.tag-selector{max-height:220px;overflow-y:auto;border:1px solid var(--line-2);border-radius:12px;padding:8px;background:rgba(15,23,42,0.8);display:none;margin-top:8px}
.tag-selector.show{display:block}
.tag-member{padding:9px;border-radius:9px;background:rgba(30,41,59,0.7);margin-bottom:5px;cursor:pointer;border:1px solid var(--line);font-size:12px;display:flex;align-items:center;gap:9px;transition:all .2s var(--ease)}
.tag-member.selected{border-color:var(--love-1);background:rgba(255,0,127,0.15)}
.tag-member .check{width:16px;height:16px;border:2px solid var(--txt-3);border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:10px;color:transparent;font-weight:900}
.tag-member.selected .check{background:var(--love-1);border-color:var(--love-1);color:#fff}
.tag-member .tm-body{flex:1;min-width:0}
.tag-member .tm-name{color:#fff;font-weight:700;font-size:12px}
.tag-member .tm-sub{color:var(--txt-2);font-size:9.5px;font-family:'JetBrains Mono',monospace}

/* ============================================================ */
/* FLOATING BOTTOM DOCK NAVIGATION (DÃY TAB XUỐNG DƯỚI) */
/* ============================================================ */
.bottom-dock{
  position:fixed;
  bottom:14px;left:50%;transform:translateX(-50%);
  width:calc(100% - 24px);max-width:540px;
  background:rgba(15,23,42,0.88);
  backdrop-filter:blur(30px) saturate(200%);
  -webkit-backdrop-filter:blur(30px) saturate(200%);
  border:1.5px solid rgba(255,0,127,0.3);
  box-shadow:0 14px 45px rgba(0,0,0,0.65), 0 0 25px rgba(255,0,127,0.2);
  border-radius:var(--r-xl);
  display:grid;grid-template-columns:repeat(4,1fr);
  padding:7px;gap:6px;z-index:999;
}
.bottom-dock .tab{
  position:relative;padding:9px 4px;border-radius:18px;
  cursor:pointer;font-size:10px;font-weight:800;letter-spacing:.6px;
  text-align:center;color:var(--txt-2);display:flex;flex-direction:column;
  align-items:center;gap:4px;user-select:none;background:transparent;
  border:none;transition:all .35s var(--ease-spring);text-transform:uppercase;
}
.bottom-dock .tab svg{width:20px;height:20px;transition:transform .3s var(--ease-spring)}
.bottom-dock .tab:hover svg{transform:scale(1.15) translateY(-2px)}
.bottom-dock .tab::before{
  content:'';position:absolute;inset:0;border-radius:inherit;
  background:var(--grad-love);opacity:0;transform:scale(.85);
  transition:all .35s var(--ease-spring);z-index:-1;
  box-shadow:0 6px 20px rgba(255,0,127,0.45);
}
.bottom-dock .tab.active{color:#fff;transform:translateY(-2px)}
.bottom-dock .tab.active::before{opacity:1;transform:scale(1)}

/* TOAST STACK */
#toast-stack{position:fixed;top:calc(16px + env(safe-area-inset-top,0px));right:14px;z-index:9999;display:flex;flex-direction:column;gap:9px;max-width:360px;width:calc(100% - 28px);pointer-events:none}
.toast{
  pointer-events:auto;position:relative;overflow:hidden;padding:12px 14px 12px 52px;
  border-radius:15px;background:rgba(20,27,45,0.92);backdrop-filter:blur(20px);
  border:1px solid var(--line-2);box-shadow:0 14px 35px rgba(0,0,0,0.6);
  display:flex;flex-direction:column;gap:3px;animation:toastIn .4s var(--ease-spring) both;
}
.toast.removing{animation:toastOut .3s var(--ease) both}
@keyframes toastIn{from{opacity:0;transform:translateX(110%) scale(.9)}to{opacity:1;transform:translateX(0) scale(1)}}
@keyframes toastOut{from{opacity:1;transform:translateX(0) scale(1)}to{opacity:0;transform:translateX(110%) scale(.9)}}
.toast::before{content:'';position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--grad-love)}
.toast .t-icon{position:absolute;left:12px;top:50%;transform:translateY(-50%);width:32px;height:32px;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#fff;background:var(--grad-love);box-shadow:0 4px 12px rgba(255,0,127,0.4)}
.toast .t-icon svg{width:16px;height:16px}
.toast .t-title{font-size:11.5px;font-weight:900;color:#fff;letter-spacing:.4px;text-transform:uppercase}
.toast .t-msg{font-size:11px;font-weight:600;color:var(--txt-2);line-height:1.45}
.toast .t-close{position:absolute;top:6px;right:6px;width:22px;height:22px;border-radius:6px;border:none;background:transparent;color:var(--txt-3);cursor:pointer;display:flex;align-items:center;justify-content:center}

.hint{font-size:10.5px;color:var(--txt-2);line-height:1.55;padding:11px 13px;background:rgba(255,0,127,0.08);border-radius:11px;border-left:3px solid var(--love-2);margin-top:10px}
.hint b{color:var(--love-2);font-weight:800}

@media (max-width:640px){
  .container{padding:10px}
  .card{padding:14px;border-radius:var(--r-md)}
  .header-info h1{font-size:13.5px}
  .bottom-dock{bottom:10px;width:calc(100% - 18px);padding:5px}
  .bottom-dock .tab{font-size:9px;padding:8px 2px}
  .bottom-dock .tab svg{width:18px;height:18px}
  .mode-grid{grid-template-columns:repeat(3,1fr)}
}
</style>
</head>
<body>

<!-- TOP HEADER -->
<div class="header">
  <div class="header-inner">
    <div class="logo-mini">""" + LOGO_SVG + """</div>
    <div class="header-info">
      <h1>I LOVE NGỌC HÂN 💖</h1>
      <p>Special Edition • v33.5</p>
    </div>
    <button class="logout-btn" onclick="location.href='/logout'">
      <span>Thoát</span>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
    </button>
  </div>
</div>

<div id="toast-stack"></div>

<!-- CONTENT CONTAINER -->
<div class="container">

  <!-- TAB 1: ACCOUNTS -->
  <div class="panel active" id="panel-accounts">
    <div class="card">
      <h2><span class="bi">+</span> Thêm tài khoản</h2>
      <div class="form-group"><label>Tên gợi nhớ</label><input id="add-label" placeholder="acc1"></div>
      <div class="form-group"><label>IMEI</label><input id="add-imei" placeholder="000000000000000"></div>
      <div class="form-group"><label>Cookie (JSON)</label><textarea id="add-cookies" placeholder='{"zpw_sek":"...","zpw_ver":"645","zpw_type":"30"}'></textarea></div>
      <button type="button" class="btn-rect primary full" onclick="addAccount()">💖 Thêm tài khoản</button>
    </div>
    <div class="card">
      <h2><span class="bi">≡</span> Danh sách tài khoản</h2>
      <div class="stat-grid">
        <div class="stat"><div class="label">Tổng Acc</div><div class="value" id="stat-total">0</div></div>
        <div class="stat"><div class="label">Đang bật</div><div class="value" id="stat-active">0</div></div>
        <div class="stat"><div class="label">Đã gửi</div><div class="value" id="stat-sent">0</div></div>
      </div>
      <div class="table-wrap"><table class="table"><thead><tr><th>ID</th><th>Tên</th><th>Tên thật</th><th>UID</th><th>OK/Lỗi</th><th>Risk</th><th>Thao tác</th></tr></thead><tbody id="accounts-tbody"></tbody></table></div>
    </div>
  </div>

  <!-- TAB 2: BOXES -->
  <div class="panel" id="panel-boxes">
    <div class="card">
      <h2><span class="bi">▦</span> Quản lý Box chat</h2>
      <div class="form-group"><label>Chọn tài khoản để load</label><select id="load-acc-select"><option value="">-- Chọn tài khoản --</option></select></div>
      <div style="text-align:center;margin:12px 0;">
        <button type="button" class="btn-circle primary" onclick="loadBoxes()" title="Load"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg></button>
        <button type="button" class="btn-circle success" onclick="selectAllBoxes()" title="Chọn tất cả"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></button>
        <button type="button" class="btn-circle danger" onclick="clearAllBoxes()" title="Bỏ chọn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
      </div>
      <div style="margin-top:12px;">
        <div style="display:flex;justify-content:space-between;margin-bottom:6px;font-size:11px;">
          <b style="color:var(--txt-2);text-transform:uppercase;letter-spacing:1px;">Đã chọn: <span id="selected-count" style="color:var(--love-1);font-weight:900;">0</span></b>
        </div>
        <div class="box-list" id="box-list"><div style="text-align:center;padding:20px;color:var(--txt-3);font-size:12px;">Chưa tải danh sách box</div></div>
      </div>
    </div>
  </div>

  <!-- TAB 3: FILES -->
  <div class="panel" id="panel-files">
    <div class="card">
      <h2><span class="bi">↑</span> Tải lên File tin nhắn</h2>
      <div class="form-group"><input type="file" id="file-input" accept=".txt" style="padding:8px;"></div>
      <button type="button" class="btn-rect primary full" onclick="uploadFile()">📤 Upload File</button>
      <div class="hint">
        💡 Mỗi khối cách nhau bởi <b>dòng trống</b> = 1 tin nhắn.<br>
        <b>Treo ngôn</b>: N dòng → gửi trong <b>1 tin duy nhất</b> (giữ nguyên xuống dòng thật).<br>
        <b>Treo nhây</b>: N dòng → N tin nhắn riêng biệt, tự động đánh số 1. 2. 3.
      </div>
    </div>
    <div class="card">
      <h2><span class="bi">▤</span> File tin nhắn hiện có</h2>
      <div id="files-list"><div style="text-align:center;padding:20px;color:var(--txt-3);font-size:12px;">Chưa có file nào</div></div>
    </div>
  </div>

  <!-- TAB 4: SPAM CONTROL -->
  <div class="panel" id="panel-spam">
    <div class="card">
      <h2><span class="bi">▶</span> Cấu hình gửi tin</h2>

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
            <div class="mc-desc">N dòng / 1 tin</div>
          </div>
          <div class="mode-card" data-mode="treo_nhay">
            <div class="mc-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg></div>
            <div class="mc-title">Treo nhây</div>
            <div class="mc-desc">N dòng / N tin</div>
          </div>
        </div>
        <input type="hidden" id="spam-mode" value="fast">
      </div>

      <div class="form-group">
        <label>Chọn file tin nhắn</label>
        <select id="spam-file-select"><option value="">-- Chọn file đã upload --</option></select>
      </div>

      <div class="form-group">
        <label>Hoặc nhập tin trực tiếp (mỗi khối cách nhau bởi dấu ;)</label>
        <textarea id="spam-messages" placeholder="Dòng 1&#10;Dòng 2&#10;Dòng 3&#10;Dòng 4;Tin khác"></textarea>
      </div>

      <div class="form-group">
        <label>🎨 Màu chữ Zalo</label>
        <div class="color-mode-grid" id="color-mode-grid">
          <div class="color-mode" data-cmode="none">Tắt</div>
          <div class="color-mode active" data-cmode="random">Ngẫu nhiên</div>
          <div class="color-mode" data-cmode="fixed">Cố định</div>
          <div class="color-mode" data-cmode="cycle">Xoay vòng</div>
        </div>
        <input type="hidden" id="color-mode" value="random">
        <div class="color-palette" id="color-palette"></div>
        <div class="color-preview" id="color-preview">Xem trước màu chữ</div>
      </div>

      <div class="form-group">
        <label>⏱ Delay (giây)</label>
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
        <label>😈 Số Icon cuối câu</label>
        <div class="chip-group" id="icon-chips">
          <div class="chip" data-icon="0">0</div>
          <div class="chip" data-icon="2">2</div>
          <div class="chip active" data-icon="3">3</div>
          <div class="chip" data-icon="5">5</div>
          <div class="chip" data-icon="10">10</div>
        </div>
        <input type="hidden" id="icon-count" value="3">
      </div>

      <div class="toggle-group">
        <div class="toggle active" id="tg-emoji" onclick="tgFlag('emoji')">😈 Icon</div>
        <div class="toggle active" id="tg-human" onclick="tgFlag('human')">🧑 Giả người</div>
        <div class="toggle active" id="tg-mention" onclick="tgFlag('mention')">📢 Tag thật</div>
        <div class="toggle active" id="tg-read" onclick="tgFlag('read')">👁️ Đã xem</div>
      </div>

      <div class="form-group" id="speed-wrap">
        <label>⌨️ Tốc độ gõ phím</label>
        <div class="chip-group" id="speed-chips">
          <div class="chip" data-speed="instant">Tức thì</div>
          <div class="chip active" data-speed="fast">Nhanh</div>
          <div class="chip" data-speed="normal">Vừa</div>
          <div class="chip" data-speed="slow">Chậm</div>
        </div>
        <input type="hidden" id="typing-speed" value="fast">
      </div>

      <div class="form-group">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;text-transform:none;letter-spacing:0;font-size:12px;color:#fff;">
          <input type="checkbox" id="tg-tag" onchange="tgTag()" style="width:auto;">
          Bật chọn members trong nhóm để Tag
        </label>
        <div id="tag-wrap" style="display:none;margin-top:8px;">
          <div class="form-group"><select id="member-acc-select"><option value="">-- Chọn tài khoản --</option></select></div>
          <button type="button" class="btn-rect info" onclick="loadMembers()">🔄 Load members nhóm</button>
          <div class="tag-selector" id="tag-selector"></div>
          <input type="hidden" id="tag-selected" value="">
        </div>
      </div>
    </div>

    <div style="text-align:center;margin-bottom:16px;">
      <button type="button" class="btn-circle success big" onclick="startSpam()" title="Bắt đầu"><svg viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3"/></svg></button>
      <button type="button" class="btn-circle danger big" onclick="stopAll()" title="Dừng"><svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg></button>
    </div>

    <div class="card">
      <h2><span class="bi">≡</span> Tiến trình đang chạy</h2>
      <button type="button" class="btn-circle danger small" onclick="stopAll()" title="Dừng tất cả"><svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg></button>
      <div class="table-wrap" style="margin-top:10px;">
        <table class="table"><thead><tr><th>ID</th><th>Chế độ</th><th>Màu</th><th>Delay</th><th>Trạng thái</th><th>Hành động</th></tr></thead><tbody id="tasks-tbody"></tbody></table>
      </div>
    </div>
  </div>

</div>

<!-- ============================================================ -->
<!-- FLOATING BOTTOM DOCK: DÃY TAB CHỌN Ở DƯỚI ĐÁY MÀN HÌNH -->
<!-- ============================================================ -->
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
var fixedColor = null;
var ZALO_COLORS = [];

var Toast = (function(){
  var stack = null;
  function ensure(){ if(!stack) stack = document.getElementById('toast-stack'); return stack; }
  var ICONS = {
    success:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    error:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    warning:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="8" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    info:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
  };
  function show(msg, type, title, duration){
    type = type || 'success'; duration = duration || 2000;
    var s = ensure(); if(!s) return;
    var el = document.createElement('div');
    el.className = 'toast ' + type;
    el.innerHTML = '<div class="t-icon">' + (ICONS[type] || ICONS.info) + '</div>' +
      '<button type="button" class="t-close">✕</button>' +
      '<div class="t-title">' + (title || 'Thông báo') + '</div>' +
      '<div class="t-msg">' + msg + '</div>';
    s.appendChild(el);
    var timer = setTimeout(remove, duration);
    function remove(){ clearTimeout(timer); el.classList.add('removing'); el.addEventListener('animationend', function(){ el.remove(); }, { once:true }); }
    el.querySelector('.t-close').addEventListener('click', remove);
  }
  return {
    success:function(m,t,d){return show(m,'success',t,d);},
    error:function(m,t,d){return show(m,'error',t,d || 2600);},
    warning:function(m,t,d){return show(m,'warning',t,d);},
    info:function(m,t,d){return show(m,'info',t,d);}
  };
})();

// TAB SWITCHING (Bottom Navigation)
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

document.querySelectorAll('.mode-card').forEach(function(c){
  c.addEventListener('click', function(){
    document.querySelectorAll('.mode-card').forEach(function(x){ x.classList.remove('active'); });
    c.classList.add('active');
    currentMode = c.dataset.mode;
    document.getElementById('spam-mode').value = currentMode;
  });
});

function renderPalette(){
  var pal = document.getElementById('color-palette');
  pal.innerHTML = ZALO_COLORS.map(function(c){
    var act = (fixedColor === c.id) ? ' active' : '';
    return '<div class="color-swatch' + act + '" data-color="' + c.id + '" style="background:' + c.hex + ';" title="' + c.name + '"></div>';
  }).join('');
  pal.querySelectorAll('.color-swatch').forEach(function(sw){
    sw.addEventListener('click', function(){
      fixedColor = sw.dataset.color;
      colorMode = 'fixed';
      document.querySelectorAll('.color-mode').forEach(function(x){ x.classList.toggle('active', x.dataset.cmode === 'fixed'); });
      document.getElementById('color-mode').value = 'fixed';
      pal.querySelectorAll('.color-swatch').forEach(function(s){ s.classList.toggle('active', s.dataset.color === fixedColor); });
      updateColorPreview();
    });
  });
}
function updateColorPreview(){
  var prev = document.getElementById('color-preview');
  var col = null;
  if(colorMode === 'random') col = randomHex();
  else if(colorMode === 'cycle') col = ZALO_COLORS[Math.floor(Math.random() * ZALO_COLORS.length)].hex;
  else if(colorMode === 'fixed' && fixedColor){
    var found = ZALO_COLORS.find(function(x){ return x.id === fixedColor; });
    col = found ? found.hex : '#00f2fe';
  } else {
    prev.style.color = 'var(--txt-2)'; prev.textContent = 'Mặc định (không màu)'; return;
  }
  prev.style.color = col; prev.textContent = 'Aa Xem trước màu chữ Zalo Aa';
}
function randomHex(){ return ZALO_COLORS[Math.floor(Math.random() * ZALO_COLORS.length)].hex; }

document.querySelectorAll('.color-mode').forEach(function(cm){
  cm.addEventListener('click', function(){
    document.querySelectorAll('.color-mode').forEach(function(x){ x.classList.remove('active'); });
    cm.classList.add('active');
    colorMode = cm.dataset.cmode;
    document.getElementById('color-mode').value = colorMode;
    var pal = document.getElementById('color-palette');
    if(colorMode === 'fixed') pal.classList.add('show'); else pal.classList.remove('show');
    updateColorPreview();
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
document.querySelectorAll('#speed-chips .chip').forEach(function(c){
  c.addEventListener('click', function(){
    document.querySelectorAll('#speed-chips .chip').forEach(function(x){ x.classList.remove('active'); });
    c.classList.add('active');
    document.getElementById('typing-speed').value = c.dataset.speed;
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
  var ctrl = new AbortController();
  var to = setTimeout(function(){ ctrl.abort(); }, 90000);
  try {
    var r = await fetch(url, Object.assign({ signal: ctrl.signal }, opts, {
      headers: Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {})
    }));
    clearTimeout(to);
    return await r.json();
  } catch(e){
    clearTimeout(to);
    return { error: 'Kết nối máy chủ lỗi: ' + e.message };
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
        '<td><b style="color:#fff">' + a.label + '</b></td>' +
        '<td><span style="color:var(--love-cyan);font-weight:700;">' + realName + '</span></td>' +
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
  Toast.info('Đang xác thực Cookie...', 'Chờ xíu', 30000);
  var r = await api('/api/accounts/add', { method:'POST', body: JSON.stringify({ label:label, imei:imei, cookies:cookies }) });
  if(r.error){ return Toast.error(r.error, 'Thất bại'); }
  var nameInfo = r.display_name || r.zalo_name || r.username || '?';
  Toast.success('Đã thêm: ' + r.label + ' (' + nameInfo + ')', 'Thành công');
  document.getElementById('add-label').value = '';
  document.getElementById('add-imei').value = '';
  document.getElementById('add-cookies').value = '';
  refreshAll();
}
async function delAcc(id){
  if(!confirm('Xác nhận xóa tài khoản #' + id + '?')) return;
  await api('/api/accounts/' + id, { method:'DELETE' });
  Toast.success('Đã xóa #' + id); refreshAll();
}
async function resetAcc(id){
  await api('/api/accounts/' + id + '/reset', { method:'POST' });
  Toast.info('Đã reset risk #' + id); refreshAll();
}
async function checkAcc(id){
  Toast.info('Đang kiểm tra #' + id + '...', 'Đợi chút', 20000);
  var r = await api('/api/accounts/' + id + '/check', { method:'POST' });
  if(r.error){ return Toast.error(r.error, 'Lỗi'); }
  var nameInfo = r.display_name || r.zalo_name || r.username || '?';
  Toast.success('Hoạt động tốt • ' + nameInfo, 'Live');
}

async function loadBoxes(){
  var aid = document.getElementById('load-acc-select').value;
  if(!aid) return Toast.error('Hãy chọn tài khoản trước');
  Toast.info('Đang tải danh sách Box...', 'Đợi chút', 90000);
  var r = await api('/api/accounts/' + aid + '/load_boxes', { method:'POST' });
  if(r.error) return Toast.error(r.error, 'Lỗi');
  var all = (r.groups||[]).concat(r.friends||[]);
  var bl = document.getElementById('box-list');
  if(!all.length){
    bl.innerHTML = '<div style="text-align:center;padding:18px;color:var(--txt-3);">Không có box nào</div>'; return;
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
  Toast.info('Đã hủy chọn tất cả');
}

async function uploadFile(){
  var input = document.getElementById('file-input');
  if(!input.files.length) return Toast.error('Chưa chọn file');
  var fd = new FormData();
  fd.append('file', input.files[0]);
  Toast.info('Đang tải file lên...', 'Đang gửi');
  try {
    var r = await fetch('/api/files/upload', { method:'POST', body: fd }).then(function(x){return x.json();});
    if(r.error) return Toast.error(r.error);
    Toast.success('Upload thành công: ' + r.lines + ' khối tin');
    input.value = ''; loadFiles();
  } catch(e){ Toast.error('Lỗi: ' + e.message); }
}
async function loadFiles(){
  var files = await api('/api/files');
  if(!Array.isArray(files)) files = [];
  var list = document.getElementById('files-list');
  if(!files.length){
    list.innerHTML = '<div style="text-align:center;padding:18px;color:var(--txt-3);font-size:12px;">Chưa có file nào</div>';
  } else {
    list.innerHTML = files.map(function(f){
      var kb = (f.size/1024).toFixed(1);
      return '<div class="file-item"><div class="info"><div class="name">📄 ' + f.filename + '</div><div class="meta">' + f.lines + ' khối • ' + kb + ' KB</div></div>' +
        '<button type="button" class="btn-circle info small" onclick="previewFile('+f.id+')" title="Xem"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg></button>' +
        '<button type="button" class="btn-circle danger small" onclick="delFile('+f.id+')" title="Xoá"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg></button></div>';
    }).join('');
  }
  var s = document.getElementById('spam-file-select');
  var cur = s.value;
  s.innerHTML = '<option value="">-- Chọn file đã upload --</option>' + files.map(function(f){return '<option value="'+f.id+'">'+f.filename+' ('+f.lines+' khối)</option>';}).join('');
  s.value = cur;
}
async function previewFile(fid){
  var r = await api('/api/files/' + fid + '/preview');
  if(r.error) return Toast.error(r.error);
  var pv = (r.preview||[]).map(function(m,i){
    var lines = m.split('\\n').length;
    return '--- Khối '+(i+1)+' ('+lines+' dòng) ---\\n'+m;
  }).join('\\n\\n');
  alert('File: '+r.filename+'\\nTổng cộng: '+r.total+' khối tin\\n\\n'+pv);
}
async function delFile(fid){
  if(!confirm('Xác nhận xóa file này?')) return;
  await api('/api/files/' + fid, { method:'DELETE' });
  Toast.success('Đã xóa file'); loadFiles();
}

async function loadMembers(){
  var aid = document.getElementById('member-acc-select').value;
  if(!aid) return Toast.error('Chọn tài khoản trước');
  var box = selectedBoxes.find(function(b){return b.type === 'group';});
  if(!box) return Toast.error('Bạn cần chọn ít nhất 1 nhóm ở Tab Box');
  Toast.info('Đang tải danh sách thành viên...', 'Chờ xíu');
  var r = await api('/api/accounts/' + aid + '/members/' + box.id, { method:'POST' });
  if(r.error) return Toast.error(r.error);
  var mem = r.members || [];
  var sel = document.getElementById('tag-selector');
  sel.classList.add('show');
  if(!mem.length){
    sel.innerHTML = '<div style="padding:14px;text-align:center;color:var(--txt-3);font-size:11px;">Không có member nào</div>'; return;
  }
  sel.innerHTML = mem.map(function(m,i){
    var sub = [];
    if(m.username) sub.push('@'+m.username);
    if(m.zalo_name && m.zalo_name !== m.name) sub.push(m.zalo_name);
    sub.push(m.id);
    return '<div class="tag-member" data-idx="'+i+'" onclick="tgMember(this, '+i+')"><div class="check">✓</div><div class="tm-body"><div class="tm-name">' + m.name + '</div><div class="tm-sub">' + sub.join(' • ') + '</div></div></div>';
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
    blocks = direct.split(';').map(function(m){return m.trim();}).filter(function(m){return m;});
  }
  if(!blocks.length) return Toast.error('Chưa có nội dung tin nhắn');
  var delay = parseFloat(document.getElementById('spam-delay').value) || 1;
  var iconCount = parseInt(document.getElementById('icon-count').value) || 3;
  if(!flags.emoji) iconCount = 0;
  var typingSpeed = document.getElementById('typing-speed').value || 'fast';
  var tagUsers = [];
  if(document.getElementById('tg-tag').checked) tagUsers = selectedTags;

  var payload = {
    targets: selectedBoxes, blocks: blocks, delay: delay,
    use_emoji: flags.emoji, icon_count: iconCount, tag_users: tagUsers,
    mode: currentMode, color_mode: colorMode, fixed_color: fixedColor,
    typing_speed: typingSpeed, human_mode: flags.human,
    real_mention: flags.mention, read_receipt: flags.read
  };
  var r = await api('/api/tasks/start', { method:'POST', body: JSON.stringify(payload) });
  if(r.error) return Toast.error(r.error);
  Toast.success('Đã kích hoạt tiến trình', 'Bắt đầu gửi');
  loadTasks();
}
async function stopAll(){
  await api('/api/tasks/stop_all', { method:'POST' });
  Toast.warning('Đã dừng tất cả tác vụ'); loadTasks();
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
      '<td><span style="color:var(--love-cyan);">' + cm + '</span></td>' +
      '<td><b>' + d + '</b></td>' +
      '<td><span class="badge ' + b + '">' + txt + '</span></td>' +
      '<td>' + (running ? '<button type="button" class="btn-circle danger small" onclick="stopTask(\\'' + t.id + '\\')" title="Dừng"><svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg></button>' : '') + '</td></tr>';
  }).join('');
}
async function stopTask(tid){
  await api('/api/tasks/' + tid + '/stop', { method:'POST' });
  Toast.warning('Đã dừng #' + tid); loadTasks();
}
async function loadColors(){
  var cols = await api('/api/colors');
  if(Array.isArray(cols)){
    ZALO_COLORS = cols;
    renderPalette();
    updateColorPreview();
  }
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
# MAIN
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
