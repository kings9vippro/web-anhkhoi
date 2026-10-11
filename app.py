# ============================================================
# ALB FORGE v32.0 — Universal Forge • Multi-line Master
# Bot by Anh Khôi • True multiline • Per-line color • Ghost anti
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
    "🤣", "😂", "😹", "😏", "😜", "😝", "🤪", "🤬",
    "😈", "👊", "🖕", "💩", "🤡", "👎", "🖕", "😤",
    "🤮", "🤢", "💀", "☠️", "🔥", "💢", "🗿", "🖕",
    "😆", "🙄", "😒", "😑", "🤦", "🖕", "😺", "🐒",
]


def get_icon_hard():
    if random.random() < 0.6:
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
# ANTI-BAN GHOST v32
# ============================================================
class AntiBanGhost:
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
        if total == 0:
            return 0.0
        base = fail / total
        if fail > 20 and ok < 5:
            base = min(1.0, base + 0.18)
        if ok > 100 and base < 0.05:
            base = max(0.0, base - 0.02)
        return min(1.0, base)

    @staticmethod
    def compute_delay(user_delay, risk, is_warmup=False):
        d = max(AntiBanGhost.MIN_DELAY, user_delay)
        if risk > 0.85:
            d = max(d, 18.0)
        elif risk > 0.7:
            d = max(d, 10.0)
        elif risk > 0.5:
            d = max(d, 5.0)
        elif risk > 0.3:
            d = max(d, 2.5)
        if is_warmup:
            d *= AntiBanGhost.WARMUP_MULT
        d = d * random.uniform(0.88, 1.12)
        return max(AntiBanGhost.MIN_DELAY, min(AntiBanGhost.MAX_DELAY, d))

    @staticmethod
    def pick_color(color_mode, fixed_color, idx=0):
        if color_mode == 'none':
            return None
        if color_mode == 'random':
            return random.choice(COLOR_IDS)
        if color_mode == 'fixed':
            return fixed_color if fixed_color in COLOR_IDS else random.choice(COLOR_IDS)
        if color_mode == 'cycle':
            return COLOR_IDS[idx % len(COLOR_IDS)]
        return None

    @staticmethod
    def append_icons(text, count):
        if count <= 0:
            return text
        icons = [get_icon_hard() for _ in range(count)]
        return text + " " + " ".join(icons)

    @staticmethod
    def human_typing_rate(speed):
        return {"fast": 0.014, "normal": 0.032,
                "slow": 0.055, "instant": 0.0}.get(speed, 0.014)


# ============================================================
# ZALO API v32
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
            raise Exception("Cookie/IMEI không đúng")
        self.uid = ud.get("send2me_id")
        self.secret_key = ud.get("zpw_enk")
        try:
            self.display_name = ud.get("displayName") or ud.get("zaloName")
            self.zalo_name = ud.get("zaloName")
            self.username = ud.get("username")
        except Exception:
            pass
        if not self.secret_key:
            raise Exception("Không lấy được key")
        try:
            self._fetch_own_profile()
        except Exception:
            pass

    def _fetch_own_profile(self):
        if not self.uid:
            return
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
        pt = json.dumps(params).encode()
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
        if not uids:
            return []

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
                    "id": uid,
                    "name": final_name,
                    "display_name": dn,
                    "zalo_name": zn,
                    "username": un,
                })
        except Exception as e:
            print("[MEMBERS] batch fail: " + str(e))
            for uid in uids:
                members.append({
                    "id": uid,
                    "name": "User_" + uid[:8],
                    "display_name": "", "zalo_name": "", "username": "",
                })
        return members

    def build_mention_payload(self, text, mentions):
        if not mentions:
            return text, []
        final = text
        m_arr = []
        for m in mentions:
            name = m.get("name", "")
            uid = m.get("uid") or m.get("id")
            if not name or not uid:
                continue
            tag_str = "@" + name
            if final:
                final = final + " " + tag_str
            else:
                final = tag_str
            pos = final.rfind(tag_str)
            m_arr.append({
                "uid": str(uid),
                "pos": pos,
                "len": len(tag_str),
                "type": 0,
            })
        return final, m_arr

    def send(self, msg, thread_id, color=None, is_group=True, mentions=None):
        """
        Gửi 1 message.
        - Giữ nguyên \n trong message → Zalo client render xuống dòng.
        """
        url = ("https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
               if is_group
               else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms")

        final_msg = msg
        m_arr = []
        if mentions:
            final_msg, m_arr = self.build_mention_payload(msg, mentions)

        # Giữ \n nguyên — Zalo render được xuống dòng trong 1 bubble
        # Normalize CRLF → LF (Zalo protocol chuẩn dùng LF)
        final_msg = final_msg.replace("\r\n", "\n").replace("\r", "\n")

        pl = {
            "message": final_msg,
            "clientId": str(int(time.time() * 1000)) + str(random.randint(100, 999)),
            "imei": self.imei,
        }
        if m_arr:
            pl["mentions"] = json.dumps(m_arr)
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

    def send_multiline(self, lines, thread_id, color=None, is_group=True,
                       mentions=None, per_line_color=False,
                       color_mode='random', fixed_color=None):
        """
        Gửi NHIỀU dòng trong 1 tin nhắn duy nhất.

        per_line_color=False:
            → 1 request với text chứa \n → Zalo render 4 dòng cùng 1 màu
        per_line_color=True:
            → 4 request gap 0.08s, mỗi request 1 dòng + 1 màu riêng
            → Zalo client gộp lại thành 1 block hiển thị 4 màu
            → NHƯNG vẫn là 4 message Zalo (không phải 1)

        Lưu ý: Zalo KHÔNG có khả năng render 4 dòng 4 màu trong 1 message duy nhất.
        Chỉ có 2 cách: 1 màu cả block, hoặc 4 message gộp.
        """
        if not lines:
            return None

        if not per_line_color:
            # CÁCH A: 1 request duy nhất, 4 dòng cùng màu
            text = "\n".join(lines)
            return self.send(text, thread_id, color=color,
                             is_group=is_group, mentions=mentions)

        # CÁCH B: N request gap siêu ngắn, gộp hiển thị thành 1 block nhiều màu
        results = []
        base_cid = str(int(time.time() * 1000))
        for idx, ln in enumerate(lines):
            c = None
            if color_mode == 'random':
                c = random.choice(COLOR_IDS)
            elif color_mode == 'fixed':
                c = fixed_color if fixed_color in COLOR_IDS else None
            elif color_mode == 'cycle':
                c = COLOR_IDS[idx % len(COLOR_IDS)]
            m = mentions if idx == 0 else None
            r = self.send(ln, thread_id, color=c,
                          is_group=is_group, mentions=m)
            results.append(r)
            # Gap siêu ngắn giữa các dòng → Zalo gộp thành 1 block
            if idx < len(lines) - 1:
                time.sleep(0.08)
        return results[-1] if results else None

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
            if len(blocks) >= max_blocks:
                break
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
# WORKER v32
# ============================================================
def update_stats(aid, ok):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    if not row:
        conn.close()
        return
    ok_c = row["ok_count"] + (1 if ok else 0)
    fail_c = row["fail_count"] + (0 if ok else 1)
    sent = row["total_sent"] + (1 if ok else 0)
    risk = AntiBanGhost.compute_risk(ok_c, fail_c)
    enabled = row["enabled"]
    if fail_c >= 50 and ok_c / max(fail_c, 1) < 0.05:
        enabled = 0
    conn.execute("""
        UPDATE accounts SET
            ok_count = ?, fail_count = ?, risk = ?,
            total_sent = ?, enabled = ?, last_used = ?
        WHERE id = ?
    """, (ok_c, fail_c, risk, sent, enabled, time.time(), aid))
    conn.commit()
    conn.close()


def pick_account(exclude_id=None):
    conn = db()
    q = "SELECT * FROM accounts WHERE enabled = 1 AND risk < 0.85"
    params = []
    if exclude_id:
        q += " AND id != ?"
        params.append(exclude_id)
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
    r = AntiBanGhost.human_typing_rate(speed)
    if r <= 0:
        return
    typing_time = min(msg_len * r, 2.5)
    try:
        z.set_typing(thread_id, is_group=is_group)
    except Exception:
        pass
    if typing_time > 0.05:
        time.sleep(typing_time)


def spam_worker(tid, targets, blocks, delay,
                use_emoji, icon_count, tag_users, stop_event,
                mode="fast", color_mode="random", fixed_color=None,
                typing_speed="fast", human_mode=True,
                real_mention=False, read_receipt=True):
    """
    Mode:
      - fast: xoay vòng block, mỗi block 1 tin
      - treo_ngon: dán N dòng → gửi N dòng TRONG 1 TIN (per_line_color quyết định màu)
      - treo_nhay: dán N dòng → gửi N tin riêng, đánh số, gap vừa
    """
    block_idx = 0
    target_idx = 0
    count = 0
    last_acc_id = None
    acc_warmup_counter = {}
    acc_session_counter = {}
    global_color_idx = 0

    print("[SPAM v32] Start: " + tid)
    print("  Mode: " + mode + " | Color: " + color_mode + " | Emoji: " + str(use_emoji))

    while not stop_event.is_set():
        acc = pick_account(exclude_id=last_acc_id)
        if not acc:
            time.sleep(0.3)
            continue

        last_acc_id = acc["id"]
        aid_key = acc["id"]
        acc_warmup_counter.setdefault(aid_key, 0)
        acc_session_counter.setdefault(aid_key, 0)

        if acc_session_counter[aid_key] >= AntiBanGhost.SESSION_MAX:
            rest = random.uniform(AntiBanGhost.SESSION_REST_MIN,
                                  AntiBanGhost.SESSION_REST_MAX)
            print("[ROTATE] " + acc["label"] + " nghỉ " + str(round(rest,1)) + "s")
            end = time.time() + rest
            while time.time() < end:
                if stop_event.is_set(): break
                time.sleep(0.05)
            acc_session_counter[aid_key] = 0
            last_acc_id = None
            continue

        is_warmup = acc_warmup_counter[aid_key] < AntiBanGhost.WARMUP_MSGS

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

            # ============================================
            # BUILD + SEND
            # ============================================
            if mode == "treo_nhay":
                # Tách dòng, đánh số, mỗi dòng 1 tin riêng
                lines = [ln for ln in raw.split("\n") if ln.strip()]
                numbered = [str(i) + ". " + ln for i, ln in enumerate(lines, 1)]

                # Typing 1 lần cho cả block
                if human_mode:
                    humanize_typing(z, target_id, is_group,
                                    len(raw), typing_speed)

                for mi, ln in enumerate(numbered):
                    if stop_event.is_set(): break
                    text = ln
                    if use_emoji and icon_count > 0:
                        text = AntiBanGhost.append_icons(text, icon_count)
                    mentions = tag_users if (real_mention and tag_users and mi == 0) else None
                    color = AntiBanGhost.pick_color(color_mode, fixed_color, global_color_idx)
                    global_color_idx += 1

                    r = z.send(text, target_id, color=color,
                               is_group=is_group, mentions=mentions)
                    ok = bool(r and r.status_code == 200)
                    update_stats(acc["id"], ok)
                    count += 1
                    acc_warmup_counter[aid_key] += 1
                    acc_session_counter[aid_key] += 1

                    cs = "[" + color + "]" if color else ""
                    print("[#" + str(count) + "] " + acc["label"] + " → " +
                          str(target_id) + cs + " [" + ("OK" if ok else "ERR") +
                          "]" + (" [W]" if is_warmup else "") + " " + text[:50])

                    if mi < len(numbered) - 1:
                        gap = random.uniform(0.3, 0.7) if human_mode else 0.15
                        end = time.time() + gap
                        while time.time() < end:
                            if stop_event.is_set(): break
                            time.sleep(0.01)

            elif mode == "treo_ngon":
                # Dán N dòng → gửi N dòng TRONG 1 TIN
                # Nếu color_mode = none → 1 request với \n
                # Nếu color_mode != none → N request gap 0.08s, gộp thành 1 block hiển thị
                lines = [ln for ln in raw.split("\n") if ln.strip()]

                # Thêm icon vào dòng cuối cùng (nếu bật)
                if use_emoji and icon_count > 0 and lines:
                    lines[-1] = AntiBanGhost.append_icons(lines[-1], icon_count)

                # Typing
                if human_mode:
                    humanize_typing(z, target_id, is_group,
                                    len(raw), typing_speed)

                if color_mode == 'none':
                    # CÁCH A: 1 request duy nhất, 4 dòng cùng 1 bubble 0 màu
                    text_full = "\n".join(lines)
                    mentions = tag_users if (real_mention and tag_users) else None
                    r = z.send(text_full, target_id, color=None,
                               is_group=is_group, mentions=mentions)
                    ok = bool(r and r.status_code == 200)
                    update_stats(acc["id"], ok)
                    count += 1
                    acc_warmup_counter[aid_key] += 1
                    acc_session_counter[aid_key] += 1
                    print("[#" + str(count) + "] " + acc["label"] + " → " +
                          str(target_id) + " [1req-" + str(len(lines)) + "dòng]" +
                          " [" + ("OK" if ok else "ERR") + "] " +
                          text_full.replace("\n", " ⏎ ")[:60])
                else:
                    # CÁCH B: N request gap 0.08s → Zalo gộp thành 1 block nhiều màu
                    results = []
                    for idx, ln in enumerate(lines):
                        if stop_event.is_set(): break
                        c = AntiBanGhost.pick_color(color_mode, fixed_color, global_color_idx)
                        global_color_idx += 1
                        m = tag_users if (real_mention and tag_users and idx == 0) else None
                        r = z.send(ln, target_id, color=c,
                                   is_group=is_group, mentions=m)
                        ok = bool(r and r.status_code == 200)
                        update_stats(acc["id"], ok)
                        count += 1
                        acc_warmup_counter[aid_key] += 1
                        acc_session_counter[aid_key] += 1
                        results.append(ok)
                        cs = "[" + c + "]" if c else ""
                        print("[#" + str(count) + "] " + acc["label"] + " → " +
                              str(target_id) + cs + " [" + ("OK" if ok else "ERR") +
                              "]" + (" [W]" if is_warmup else "") + " " + ln[:50])

                        # Gap siêu ngắn → Zalo gộp bubble
                        if idx < len(lines) - 1:
                            end = time.time() + 0.08
                            while time.time() < end:
                                if stop_event.is_set(): break
                                time.sleep(0.01)

            else:
                # FAST — block như 1 tin
                text = raw
                if use_emoji and icon_count >
