# ============================================================
# ALB FORGE v27.0 — Universal Forge
# Bot by Anh Khôi • Anti-Ban Pro • Real Mention • Humanized Engine
# ============================================================
import os
import io
import json
import time
import uuid
import sqlite3
import threading
import random
import base64
import re
import hashlib
from functools import wraps
from collections import deque

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
            warmup INTEGER DEFAULT 0,
            uid TEXT
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
# ANTI-BAN PRO ENGINE
# ============================================================
class AntiBanPro:
    """
    Engine giả lập hành vi người thật tầng protocol.
    Không hứa 'không ban' — mà giảm risk signal ở mọi layer.
    """
    MIN_DELAY = 0.3
    MAX_DELAY = 120.0
    ZALO_COLORS = ["red", "orange", "yellow", "green", "ocean",
                   "blue", "purple", "pink", "brown", "black",
                   "gray", "white"]

    # Session pattern: mỗi session gửi 1 batch rồi nghỉ
    SESSION_MIN_MSGS = 8
    SESSION_MAX_MSGS = 25
    SESSION_REST_MIN = 3.0
    SESSION_REST_MAX = 12.0

    @staticmethod
    def compute_risk(ok, fail):
        total = ok + fail
        if total == 0:
            return 0.0
        base = fail / total
        # Phạt nặng nếu fail liên tiếp cao
        if fail > 20 and ok < 5:
            base = min(1.0, base + 0.15)
        return min(1.0, base)

    @staticmethod
    def compute_delay(user_delay, risk):
        d = max(AntiBanPro.MIN_DELAY, user_delay)
        if risk > 0.85:
            d = max(d, 20.0)
        elif risk > 0.7:
            d = max(d, 12.0)
        elif risk > 0.5:
            d = max(d, 6.0)
        elif risk > 0.3:
            d = max(d, 3.0)
        d = d * random.uniform(0.8, 1.3)
        return max(AntiBanPro.MIN_DELAY, min(AntiBanPro.MAX_DELAY, d))

    @staticmethod
    def random_color():
        return random.choice(AntiBanPro.ZALO_COLORS)

    @staticmethod
    def append_icons(text, count):
        if count <= 0:
            return text
        icons = [get_icon_hard() for _ in range(count)]
        return text + " " + " ".join(icons)

    @staticmethod
    def human_typing_rate(speed):
        """Trả về ms/ký tự theo speed."""
        return {"fast": 0.014, "normal": 0.032, "slow": 0.055,
                "instant": 0.0}.get(speed, 0.014)

    @staticmethod
    def session_size():
        return random.randint(AntiBanPro.SESSION_MIN_MSGS,
                              AntiBanPro.SESSION_MAX_MSGS)

    @staticmethod
    def session_rest():
        return random.uniform(AntiBanPro.SESSION_REST_MIN,
                              AntiBanPro.SESSION_REST_MAX)

    @staticmethod
    def should_micro_pause():
        """5% xác suất nghỉ tay như người thật."""
        return random.random() < 0.05

    @staticmethod
    def micro_pause_duration():
        return random.uniform(1.5, 5.0)

    @staticmethod
    def should_typo_recover():
        """3% xác suất: gõ nhầm rồi xoá (giả typing 2 lần)."""
        return random.random() < 0.03


# ============================================================
# ZALO API v27 — Real Mention
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
        if not self.secret_key:
            raise Exception("Không lấy được key")

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

    def get_members(self, gid):
        """Lấy members với TÊN THẬT đầy đủ."""
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
        # Zalo cho phép query batch
        try:
            payload = {"friendId": uids}
            enc2 = self._enc(payload)
            r2 = self.s.post(
                "https://tt-group-wpa.chat.zalo.me/api/group/getuserinfo",
                params={"zpw_ver": 645, "zpw_type": 30},
                data={"params": enc2}, timeout=20,
            )
            dec2 = self._dec(r2.json()["data"])
            profiles = json.loads(dec2).get("data", {}).get("profiles", {})
            for uid in uids:
                p = profiles.get(uid, {})
                # Ưu tiên displayName > zaloName > "User_xxx"
                name = (p.get("displayName") or p.get("zaloName")
                        or p.get("username") or "User_" + uid[:8])
                members.append({"id": uid, "name": name})
        except Exception as e:
            print("[MEMBERS] batch fail: " + str(e))
            # Fallback gọi từng người
            for uid in uids:
                try:
                    enc3 = self._enc({"friendId": uid})
                    r3 = self.s.post(
                        "https://tt-group-wpa.chat.zalo.me/api/group/getuserinfo",
                        params={"zpw_ver": 645, "zpw_type": 30},
                        data={"params": enc3}, timeout=10,
                    )
                    dec3 = self._dec(r3.json()["data"])
                    p = json.loads(dec3).get("data", {}).get("profiles", {}).get(uid, {})
                    name = (p.get("displayName") or p.get("zaloName")
                            or "User_" + uid[:8])
                    members.append({"id": uid, "name": name})
                except Exception:
                    members.append({"id": uid, "name": "User_" + uid[:8]})
        return members

    def build_mention_payload(self, text, mentions):
        """
        Build text + mentions array đúng chuẩn Zalo.
        mentions = [{"uid": ..., "name": ...}, ...]
        Trả về (final_text, mentions_array)
        """
        if not mentions:
            return text, []

        final = text
        m_arr = []
        # Mỗi mention chèn @Name vào đầu text, tính pos/len
        for m in mentions:
            name = m.get("name", "")
            uid = m.get("uid") or m.get("id")
            if not name or not uid:
                continue
            tag_str = "@" + name
            # Luôn chèn vào đầu (đơn giản, an toàn offset)
            pos = len(final) if final else 0
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
        # Đảo ngược để tag đúng thứ tự user chọn
        return final, m_arr

    def send(self, msg, thread_id, color=None, is_group=True, mentions=None):
        url = ("https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
               if is_group
               else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms")

        final_msg = msg
        m_arr = []
        if mentions:
            final_msg, m_arr = self.build_mention_payload(msg, mentions)

        pl = {
            "message": final_msg,
            "clientId": str(int(time.time() * 1000)),
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
        """Đánh dấu đã đọc — giả người thật online."""
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
            for line in f:
                if len(blocks) >= max_blocks:
                    break
                stripped = line.rstrip("\n").rstrip("\r")
                if stripped.strip() == "":
                    if current:
                        blocks.append("\n".join(current))
                        current = []
                else:
                    current.append(stripped)
            if current:
                blocks.append("\n".join(current))
    except Exception as e:
        print("[FILE] error: " + str(e))
    return blocks


# ============================================================
# WORKER v27
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
    risk = AntiBanPro.compute_risk(ok_c, fail_c)
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
    """Giả lập gõ phím."""
    r = AntiBanPro.human_typing_rate(speed)
    if r <= 0:
        return
    typing_time = min(msg_len * r, 3.0)
    try:
        z.set_typing(thread_id, is_group=is_group)
    except Exception:
        pass
    if typing_time > 0.05:
        time.sleep(typing_time)


def spam_worker(tid, targets, blocks, delay, use_color, use_emoji,
                icon_count, tag_users, stop_event,
                mode="fast", multi_color=False,
                typing_speed="fast", human_mode=True,
                real_mention=False, read_receipt=True,
                session_mode=True):
    """
    mode:
      fast        — gửi xoay vòng block nhanh
      treo_ngon   — NGUYÊN KHỐI, không cắt dòng
      treo_nhay   — tách từng DÒNG, mỗi dòng 1 message, đa màu
    real_mention  — tag tên thật qua mentions array
    session_mode  — batch + nghỉ giữa session (giả người thật)
    """
    block_idx = 0
    target_idx = 0
    count = 0
    last_acc_id = None
    session_remaining = AntiBanPro.session_size() if session_mode else 10**9

    print("[SPAM v27] Start: " + tid)
    print("  Mode: " + mode + " | Multi: " + str(multi_color))
    print("  Real mention: " + str(real_mention))
    print("  Human: " + str(human_mode) + " | Speed: " + typing_speed)
    print("  Session: " + str(session_mode))

    while not stop_event.is_set():
        # Session break
        if session_mode and session_remaining <= 0:
            rest = AntiBanPro.session_rest()
            print("[SESSION] Nghỉ " + str(round(rest, 1)) + "s")
            end = time.time() + rest
            while time.time() < end:
                if stop_event.is_set():
                    break
                time.sleep(0.1)
            session_remaining = AntiBanPro.session_size()
            continue

        acc = pick_account(exclude_id=last_acc_id)
        if not acc:
            time.sleep(0.3)
            continue

        last_acc_id = acc["id"]

        target = targets[target_idx % len(targets)]
        target_idx += 1
        is_group = target.get("type") == "group"
        target_id = target.get("id")

        raw = blocks[block_idx % len(blocks)]
        block_idx += 1

        # Build messages theo mode
        if mode == "treo_nhay":
            lines = [ln for ln in raw.split("\n") if ln.strip()]
            messages = []
            for ln in lines:
                messages.append({
                    "text": ln,
                    "color": AntiBanPro.random_color() if use_color else None,
                    "raw": ln,
                })
        else:
            messages = [{
                "text": raw,
                "color": AntiBanPro.random_color() if use_color else None,
                "raw": raw,
            }]

        try:
            cookies = json.loads(acc["cookies"])
            z = Zalo(acc["imei"], cookies)

            # Read receipt giả người online
            if read_receipt and human_mode:
                z.mark_read(target_id, is_group=is_group)
                time.sleep(random.uniform(0.1, 0.4))

            for mi, item in enumerate(messages):
                if stop_event.is_set():
                    break

                text = item["text"]

                # Icons (chỉ thêm sau khi đã split dòng — không phá multiline)
                if use_emoji and icon_count > 0:
                    text = AntiBanPro.append_icons(text, icon_count)

                # Mentions
                mentions = None
                if real_mention and tag_users:
                    mentions = tag_users

                # Human typing
                if human_mode:
                    humanize_typing(z, target_id, is_group,
                                    len(text), typing_speed)
                    # Typo-recover: 3% gõ thêm 1 nhịp typing nữa
                    if AntiBanPro.should_typo_recover():
                        time.sleep(random.uniform(0.3, 0.8))
                        try:
                            z.set_typing(target_id, is_group=is_group)
                        except Exception:
                            pass
                        time.sleep(random.uniform(0.2, 0.5))

                r = z.send(text, target_id, color=item["color"],
                           is_group=is_group, mentions=mentions)
                ok = bool(r and r.status_code == 200)
                update_stats(acc["id"], ok)
                count += 1
                session_remaining -= 1

                cs = "[" + item["color"] + "]" if item["color"] else ""
                preview = text.replace("\n", " ⏎ ")[:60]
                print("[#" + str(count) + "] " + acc["label"] + " → " +
                      str(target_id) + cs + " [" + ("OK" if ok else "ERR") +
                      "] " + preview)

                # Gap giữa các message trong batch (treo nhây)
                if mode == "treo_nhay" and mi < len(messages) - 1:
                    gap = random.uniform(0.2, 0.55) if human_mode else 0.05
                    end = time.time() + gap
                    while time.time() < end:
                        if stop_event.is_set():
                            break
                        time.sleep(0.02)

        except Exception as e:
            update_stats(acc["id"], False)
            print("[SPAM] Error " + acc["label"] + ": " + str(e))

        # Delay giữa batch
        risk = acc["risk"] if acc["risk"] else 0.0
        base = AntiBanPro.compute_delay(delay, risk)

        if human_mode:
            actual = base * random.uniform(0.85, 1.4)
            if AntiBanPro.should_micro_pause():
                actual += AntiBanPro.micro_pause_duration()
        else:
            actual = base

        end = time.time() + actual
        while time.time() < end:
            if stop_event.is_set():
                break
            time.sleep(0.03)

    conn = db()
    conn.execute(
        "UPDATE tasks SET status = 'stopped', stats = ? WHERE id = ?",
        (json.dumps({"sent": count}), tid)
    )
    conn.commit()
    conn.close()
    ACTIVE_TASKS.pop(tid, None)
    print("[SPAM v27] " + tid + " stop - total: " + str(count))


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
# ROUTES
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
        return render_template_string(HTML_LOGIN, error="Sai mật khẩu")
    return render_template_string(HTML_LOGIN)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---- ACCOUNTS ----
@app.route("/api/accounts", methods=["GET"])
@login_required
def api_accounts():
    conn = db()
    rows = conn.execute("""
        SELECT id, label, imei, ok_count, fail_count, risk,
               total_sent, enabled, uid
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
        return jsonify({"error": "Thiếu IMEI hoặc cookie"}), 400
    try:
        ck_obj = json.loads(ck)
    except Exception:
        return jsonify({"error": "Cookie không phải JSON"}), 400

    # Verify cookie sống
    try:
        z = Zalo(imei, ck_obj)
        uid = z.uid
    except Exception as e:
        return jsonify({"error": "Cookie chết: " + str(e)}), 400

    conn = db()
    conn.execute("""
        INSERT INTO accounts (label, imei, cookies, added_at, uid)
        VALUES (?, ?, ?, ?, ?)
    """, (label, imei, json.dumps(ck_obj), time.time(), uid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "label": label, "uid": uid})


@app.route("/api/accounts/<int:aid>", methods=["DELETE"])
@login_required
def api_accounts_delete(aid):
    conn = db()
    conn.execute("DELETE FROM accounts WHERE id = ?", (aid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/accounts/<int:aid>/reset", methods=["POST"])
@login_required
def api_accounts_reset(aid):
    conn = db()
    conn.execute("UPDATE accounts SET risk = 0, enabled = 1 WHERE id = ?", (aid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/accounts/<int:aid>/check", methods=["POST"])
@login_required
def api_accounts_check(aid):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Không tìm thấy"}), 404
    try:
        z = Zalo(row["imei"], json.loads(row["cookies"]))
        return jsonify({"ok": True, "uid": z.uid})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/accounts/<int:aid>/load_boxes", methods=["POST"])
@login_required
def api_load_boxes(aid):
    conn = db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Không tìm thấy"}), 404
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
        return jsonify({"error": "Không tìm thấy"}), 404
    try:
        z = Zalo(row["imei"], json.loads(row["cookies"]))
        members = z.get_members(group_id)
        return jsonify({"ok": True, "members": members,
                        "count": len(members)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ---- FILES ----
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
        return jsonify({"error": "Không có file"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Tên trống"}), 400
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
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "filename": f.filename,
                    "lines": len(blocks), "preview": blocks[:3]})


@app.route("/api/files/<int:fid>", methods=["DELETE"])
@login_required
def api_files_delete(fid):
    conn = db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Không tìm thấy"}), 404
    try:
        if os.path.exists(row["filepath"]):
            os.remove(row["filepath"])
    except Exception:
        pass
    conn.execute("DELETE FROM files WHERE id = ?", (fid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/files/<int:fid>/preview", methods=["GET"])
@login_required
def api_files_preview(fid):
    conn = db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Không tìm thấy"}), 404
    blocks = parse_blocks(row["filepath"], max_blocks=5000)
    return jsonify({"filename": row["filename"],
                    "total": len(blocks),
                    "preview": blocks[:5],
                    "all": blocks})


# ---- TASKS ----
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
    # Delay BẮT BUỘC từ server: validate chặt
    try:
        delay = float(d.get("delay", 1))
    except Exception:
        return jsonify({"error": "Delay không hợp lệ"}), 400

    use_color = bool(d.get("use_color", True))
    use_emoji = bool(d.get("use_emoji", True))
    icon_count = int(d.get("icon_count", 3))
    tag_users = d.get("tag_users", [])

    mode = d.get("mode", "fast")
    multi_color = bool(d.get("multi_color", True))
    typing_speed = d.get("typing_speed", "fast")
    human_mode = bool(d.get("human_mode", True))
    real_mention = bool(d.get("real_mention", True))
    read_receipt = bool(d.get("read_receipt", True))
    session_mode = bool(d.get("session_mode", True))

    if not targets:
        return jsonify({"error": "Chưa chọn target"}), 400
    if not blocks:
        return jsonify({"error": "Chưa có tin nhắn"}), 400
    if delay < AntiBanPro.MIN_DELAY:
        return jsonify({"error": "Delay tối thiểu " + str(AntiBanPro.MIN_DELAY) + "s"}), 400
    if delay > AntiBanPro.MAX_DELAY:
        return jsonify({"error": "Delay tối đa " + str(AntiBanPro.MAX_DELAY) + "s"}), 400
    if icon_count < 0: icon_count = 0
    if icon_count > 20: icon_count = 20
    if mode not in ("fast", "treo_ngon", "treo_nhay"):
        mode = "fast"
    if typing_speed not in ("instant", "fast", "normal", "slow"):
        typing_speed = "fast"

    conn = db()
    cnt = conn.execute(
        "SELECT COUNT(*) as c FROM accounts WHERE enabled = 1"
    ).fetchone()["c"]
    conn.close()
    if cnt == 0:
        return jsonify({"error": "Kho tài khoản trống"}), 400

    tid = new_tid("spam")
    stop_ev = threading.Event()
    th = threading.Thread(
        target=spam_worker,
        args=(tid, targets, blocks, delay, use_color, use_emoji,
              icon_count, tag_users, stop_ev,
              mode, multi_color, typing_speed, human_mode,
              real_mention, read_receipt, session_mode),
        daemon=True,
    )

    conn = db()
    conn.execute("""
        INSERT INTO tasks (id, type, meta, status, started_at, stats)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tid, "spam",
          json.dumps({"targets": len(targets), "blocks": len(blocks),
                      "delay": delay, "tags": len(tag_users),
                      "mode": mode, "multi_color": multi_color,
                      "typing_speed": typing_speed, "human_mode": human_mode,
                      "real_mention": real_mention,
                      "session_mode": session_mode}),
          "running", time.time(), "{}"))
    conn.commit()
    conn.close()

    ACTIVE_TASKS[tid] = {"stop": stop_ev, "thread": th}
    th.start()

    return jsonify({"ok": True, "task_id": tid, "mode": mode,
                    "delay": delay})


@app.route("/api/tasks/<tid>/stop", methods=["POST"])
@login_required
def api_tasks_stop(tid):
    if tid in ACTIVE_TASKS:
        ACTIVE_TASKS[tid]["stop"].set()
        return jsonify({"ok": True})
    return jsonify({"error": "Không tồn tại"}), 404


@app.route("/api/tasks/stop_all", methods=["POST"])
@login_required
def api_tasks_stop_all():
    for tid, t in list(ACTIVE_TASKS.items()):
        t["stop"].set()
    return jsonify({"ok": True, "count": len(ACTIVE_TASKS)})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "alb-forge", "version": "27.0"})


# ============================================================
# LOGO SVG v27 — ALB hex-forge
# ============================================================
LOGO_SVG = """<svg viewBox="0 0 140 140" xmlns="http://www.w3.org/2000/svg" fill="none">
<defs>
<linearGradient id="lg1" x1="0" y1="0" x2="1" y2="1">
<stop offset="0%" stop-color="#00d4ff"/>
<stop offset="50%" stop-color="#7b2ff7"/>
<stop offset="100%" stop-color="#f107a3"/>
</linearGradient>
<linearGradient id="lg2" x1="0" y1="1" x2="1" y2="0">
<stop offset="0%" stop-color="#ffd700"/>
<stop offset="50%" stop-color="#ff6b35"/>
<stop offset="100%" stop-color="#f107a3"/>
</linearGradient>
<linearGradient id="lg3" x1="0" y1="0" x2="0" y2="1">
<stop offset="0%" stop-color="#ffffff" stop-opacity="0.9"/>
<stop offset="100%" stop-color="#ffffff" stop-opacity="0.1"/>
</linearGradient>
<radialGradient id="core" cx="0.5" cy="0.5" r="0.5">
<stop offset="0%" stop-color="#ffffff"/>
<stop offset="40%" stop-color="#00d4ff"/>
<stop offset="100%" stop-color="#7b2ff7" stop-opacity="0"/>
</radialGradient>
<filter id="glow1" x="-50%" y="-50%" width="200%" height="200%">
<feGaussianBlur stdDeviation="3"/>
</filter>
<filter id="glow2" x="-50%" y="-50%" width="200%" height="200%">
<feGaussianBlur stdDeviation="6"/>
</filter>
</defs>

<!-- Outer glow -->
<circle cx="70" cy="70" r="62" fill="url(#core)" opacity="0.35" filter="url(#glow2)"/>

<!-- Rotating hex ring -->
<g transform="translate(70,70)">
<g>
<animateTransform attributeName="transform" type="rotate"
 from="0" to="360" dur="24s" repeatCount="indefinite"/>
<polygon points="0,-56 48.5,-28 48.5,28 0,56 -48.5,28 -48.5,-28"
 fill="none" stroke="url(#lg1)" stroke-width="1.4"
 stroke-dasharray="4 7" opacity="0.7"/>
</g>
<g>
<animateTransform attributeName="transform" type="rotate"
 from="360" to="0" dur="16s" repeatCount="indefinite"/>
<polygon points="0,-46 40,-23 40,23 0,46 -40,23 -40,-23"
 fill="none" stroke="url(#lg2)" stroke-width="1" opacity="0.55"
 stroke-dasharray="2 5"/>
</g>
</g>

<!-- Core hex -->
<g transform="translate(70,70)">
<polygon points="0,-38 33,-19 33,19 0,38 -33,19 -33,-19"
 fill="url(#lg1)" filter="url(#glow1)"/>
<polygon points="0,-38 33,-19 33,19 0,38 -33,19 -33,-19"
 fill="none" stroke="url(#lg3)" stroke-width="1.4"/>
<!-- Inner hex cut -->
<polygon points="0,-22 19,-11 19,11 0,22 -19,11 -19,-11"
 fill="#0a0a1a" opacity="0.9"/>
<!-- Lightning bolt A -->
<path d="M-6,-16 L2,-6 L-2,-6 L6,6 L0,-2 L4,-2 Z"
 fill="url(#lg2)" filter="url(#glow1)"/>
</g>

<!-- Orbiting particles -->
<g transform="translate(70,70)">
<circle r="62" fill="none"/>
<circle cx="62" cy="0" r="2.4" fill="#00d4ff" filter="url(#glow1)">
<animateTransform attributeName="transform" type="rotate"
 from="0" to="360" dur="8s" repeatCount="indefinite"/>
</circle>
<circle cx="0" cy="-62" r="2" fill="#f107a3" filter="url(#glow1)">
<animateTransform attributeName="transform" type="rotate"
 from="0" to="360" dur="11s" repeatCount="indefinite"/>
</circle>
<circle cx="-62" cy="0" r="1.8" fill="#ffd700" filter="url(#glow1)">
<animateTransform attributeName="transform" type="rotate"
 from="360" to="0" dur="14s" repeatCount="indefinite"/>
</circle>
</g>

<!-- Corner sparks -->
<path d="M116 22 L119 30 L127 33 L119 36 L116 44 L113 36 L105 33 L113 30 Z"
 fill="url(#lg2)" filter="url(#glow1)">
<animateTransform attributeName="transform" type="scale"
 values="1;1.3;1" dur="2.6s" repeatCount="indefinite" additive="sum"/>
</path>
<path d="M24 116 L26 121 L31 123 L26 125 L24 130 L22 125 L17 123 L22 121 Z"
 fill="url(#lg1)" filter="url(#glow1)" opacity="0.85"/>
</svg>"""


# ============================================================
# CSS ROOT
# ============================================================
CSS_ROOT = """
:root{
  --bg-0:#0a0a1a; --bg-1:#12122a; --bg-2:#1a1a35;
  --bg-3:#232346; --bg-glass:rgba(18,18,42,.72);
  --line:rgba(255,255,255,.08); --line-2:rgba(255,255,255,.14);
  --line-3:rgba(255,255,255,.22);
  --txt-0:#ffffff; --txt-1:#e8eaf6; --txt-2:#a0a4c0; --txt-3:#6b6f8c;
  --brand-a:#00d4ff; --brand-b:#7b2ff7; --brand-c:#f107a3; --brand-d:#ffd700;
  --ok:#10b981; --err:#ef4444; --warn:#f59e0b; --info:#3b82f6;
  --purple:#8b5cf6; --pink:#ec4899; --teal:#14b8a6;
  --grad-brand:linear-gradient(135deg,#00d4ff 0%,#7b2ff7 60%,#f107a3 100%);
  --grad-hot:linear-gradient(135deg,#ffd700 0%,#ff6b35 50%,#f107a3 100%);
  --grad-ok:linear-gradient(135deg,#10b981,#059669);
  --grad-err:linear-gradient(135deg,#ef4444,#dc2626);
  --grad-warn:linear-gradient(135deg,#f59e0b,#d97706);
  --grad-info:linear-gradient(135deg,#3b82f6,#2563eb);
  --grad-purple:linear-gradient(135deg,#8b5cf6,#7c3aed);
  --grad-pink:linear-gradient(135deg,#ec4899,#db2777);
  --grad-teal:linear-gradient(135deg,#14b8a6,#0d9488);
  --r-xs:8px; --r-sm:10px; --r-md:14px; --r-lg:18px; --r-xl:22px; --r-2xl:28px;
  --ease:cubic-bezier(.16,1,.3,1);
  --ease-2:cubic-bezier(.34,1.56,.64,1);
}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{touch-action:manipulation;-webkit-text-size-adjust:100%}
body{
  font-family:'Inter',system-ui,-apple-system,sans-serif;
  background:var(--bg-0); color:var(--txt-1);
  min-height:100vh;
  -webkit-font-smoothing:antialiased;
  overflow-x:hidden;
  background-image:
    radial-gradient(900px 500px at 0% 0%,rgba(0,212,255,.08),transparent 60%),
    radial-gradient(900px 500px at 100% 100%,rgba(241,7,163,.08),transparent 60%);
  background-attachment:fixed;
}
button,input,textarea,select{font-family:inherit;font-feature-settings:'ss01','cv11'}
::selection{background:rgba(0,212,255,.3)}
*::-webkit-scrollbar{width:8px;height:8px}
*::-webkit-scrollbar-track{background:transparent}
*::-webkit-scrollbar-thumb{background:rgba(0,212,255,.25);border-radius:99px}
*::-webkit-scrollbar-thumb:hover{background:rgba(0,212,255,.5)}
:focus-visible{outline:2px solid var(--brand-a);outline-offset:2px;border-radius:6px}
"""


# ============================================================
# HTML — LOGIN v27
# ============================================================
HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="theme-color" content="#0a0a1a">
<title>Đăng nhập — ALB Forge v27</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_ROOT + """
body{
  display:flex;align-items:center;justify-content:center;
  min-height:100vh;min-height:100dvh;
  padding:20px;
  position:relative;overflow:hidden;
}
body::before{
  content:'';position:absolute;inset:0;
  background-image:
    linear-gradient(rgba(0,212,255,.06) 1px,transparent 1px),
    linear-gradient(90deg,rgba(0,212,255,.06) 1px,transparent 1px);
  background-size:44px 44px;
  animation:gridMove 30s linear infinite;
  pointer-events:none;
}
@keyframes gridMove{from{background-position:0 0}to{background-position:44px 44px}}
.card{
  position:relative;
  background:linear-gradient(180deg,rgba(18,18,42,.92),rgba(10,10,26,.96));
  backdrop-filter:blur(24px) saturate(160%);
  -webkit-backdrop-filter:blur(24px) saturate(160%);
  padding:44px 34px 36px;
  border-radius:var(--r-2xl);
  border:1px solid var(--line-2);
  box-shadow:
    0 30px 80px rgba(0,0,0,.6),
    0 0 60px rgba(0,212,255,.15),
    inset 0 1px 0 rgba(255,255,255,.1);
  width:100%;max-width:420px;text-align:center;
  animation:cardIn .9s var(--ease) both;
  overflow:hidden;
}
.card::before{
  content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:var(--grad-brand);
  box-shadow:0 0 20px rgba(0,212,255,.8);
}
@keyframes cardIn{
  from{opacity:0;transform:translateY(40px) scale(.95)}
  to{opacity:1;transform:translateY(0) scale(1)}
}
.logo-box{
  width:130px;height:130px;margin:0 auto 18px;position:relative;
  filter:drop-shadow(0 0 30px rgba(123,47,247,.5));
  animation:logoFloat 4s ease-in-out infinite;
}
@keyframes logoFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
.logo-box svg{width:100%;height:100%}
h1{
  font-family:'Orbitron',sans-serif;
  font-size:28px;font-weight:900;letter-spacing:2px;
  background:linear-gradient(135deg,#00d4ff,#7b2ff7 50%,#f107a3);
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
  margin-bottom:6px;
  text-transform:uppercase;
}
p.sub{color:var(--txt-2);margin-bottom:26px;font-size:11.5px;font-weight:600;letter-spacing:1.2px;text-transform:uppercase}
.input-wrap{position:relative;margin-bottom:6px}
input[type=password]{
  width:100%;padding:16px 48px 16px 18px;
  border:2px solid var(--line-2);border-radius:var(--r-md);
  font-size:15px;font-weight:600;
  background:rgba(255,255,255,.03);color:var(--txt-0);
  letter-spacing:2px;text-align:left;
  transition:all .25s var(--ease);
}
input[type=password]::placeholder{color:var(--txt-3);letter-spacing:normal;font-weight:500}
input[type=password]:focus{
  outline:none;border-color:var(--brand-a);background:rgba(0,212,255,.04);
  box-shadow:0 0 0 4px rgba(0,212,255,.15),0 0 30px rgba(0,212,255,.15);
}
.pw-toggle{
  position:absolute;right:6px;top:50%;transform:translateY(-50%);
  width:38px;height:38px;border-radius:10px;border:none;background:transparent;
  color:var(--txt-2);cursor:pointer;font-size:16px;
  display:flex;align-items:center;justify-content:center;
  transition:all .2s var(--ease);
}
.pw-toggle:hover{background:rgba(255,255,255,.08);color:var(--brand-a)}
button.submit{
  width:100%;padding:16px;margin-top:16px;
  background:var(--grad-brand);color:#fff;border:none;border-radius:var(--r-md);
  font-size:14px;font-weight:900;letter-spacing:1.5px;cursor:pointer;
  text-transform:uppercase;
  box-shadow:0 14px 34px rgba(123,47,247,.5),0 0 40px rgba(0,212,255,.3);
  transition:all .3s var(--ease);
  position:relative;overflow:hidden;
  display:flex;align-items:center;justify-content:center;gap:8px;
}
button.submit::before{
  content:'';position:absolute;inset:0;
  background:linear-gradient(120deg,transparent 30%,rgba(255,255,255,.5) 50%,transparent 70%);
  transform:translateX(-100%);transition:transform .8s var(--ease);
}
button.submit:hover::before{transform:translateX(100%)}
button.submit:hover{transform:translateY(-2px);box-shadow:0 20px 50px rgba(123,47,247,.6),0 0 60px rgba(0,212,255,.5)}
button.submit:active{transform:translateY(0) scale(.99)}
.error{
  background:rgba(239,68,68,.12);color:#fca5a5;
  padding:12px 16px;border-radius:var(--r-md);margin-bottom:16px;
  font-size:12px;font-weight:700;letter-spacing:.5px;
  border-left:4px solid var(--err);
  animation:shake .5s var(--ease);text-align:left;
}
@keyframes shake{
  0%,100%{transform:translateX(0)}
  20%,60%{transform:translateX(-6px)}
  40%,80%{transform:translateX(6px)}
}
.foot{margin-top:22px;font-size:10px;color:var(--txt-3);font-weight:700;letter-spacing:2px;text-transform:uppercase}
.foot b{background:var(--grad-brand);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;font-weight:900}
</style>
</head>
<body>
<div class="card">
<div class="logo-box">""" + LOGO_SVG + """</div>
<h1>ALB FORGE</h1>
<p class="sub">Universal • v27.0 • Anti-Pro</p>
{% if error %}<div class="error">⚠️ {{ error }}</div>{% endif %}
<form method="POST" autocomplete="off">
<div class="input-wrap">
<input type="password" name="password" id="pw" placeholder="Nhập mật khẩu..." autofocus required>
<button type="button" class="pw-toggle" onclick="tgPw()" aria-label="Hiện mật khẩu">👁️</button>
</div>
<button type="submit" class="submit">🚀 Đăng nhập</button>
</form>
<div class="foot">Secured by <b>ALB FORGE</b></div>
</div>
<script>
function tgPw(){
  var p=document.getElementById('pw');
  p.type = p.type==='password' ? 'text' : 'password';
}
</script>
</body>
</html>
"""


# ============================================================
# HTML — INDEX v27 (FULL)
# ============================================================
HTML_INDEX = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="theme-color" content="#0a0a1a">
<title>ALB Forge v27.0</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
""" + CSS_ROOT + """

/* ---------- BACKGROUND GRID ---------- */
body::before{
  content:'';position:fixed;inset:0;z-index:-1;
  background-image:
    linear-gradient(rgba(0,212,255,.04) 1px,transparent 1px),
    linear-gradient(90deg,rgba(0,212,255,.04) 1px,transparent 1px);
  background-size:48px 48px;
  animation:gridMove 40s linear infinite;
  pointer-events:none;
}
@keyframes gridMove{from{background-position:0 0}to{background-position:48px 48px}}

/* ---------- HEADER ---------- */
.header{
  background:linear-gradient(180deg,rgba(18,18,42,.94),rgba(10,10,26,.88));
  backdrop-filter:blur(24px) saturate(160%);
  -webkit-backdrop-filter:blur(24px) saturate(160%);
  color:#fff;padding:14px 18px;
  padding-top:calc(14px + env(safe-area-inset-top,0px));
  border-bottom:1px solid var(--line-2);
  box-shadow:0 6px 30px rgba(0,0,0,.5),0 0 40px rgba(0,212,255,.08);
  position:sticky;top:0;z-index:100;
}
.header::after{
  content:'';position:absolute;left:0;right:0;bottom:0;height:2px;
  background:var(--grad-brand);opacity:.9;
  box-shadow:0 0 20px rgba(0,212,255,.6);
}
.header-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;gap:12px}
.logo-mini{
  width:44px;height:44px;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  background:rgba(0,212,255,.08);border-radius:12px;
  border:1px solid rgba(0,212,255,.25);
  padding:5px;
  box-shadow:0 0 20px rgba(0,212,255,.3),inset 0 1px 0 rgba(255,255,255,.15);
  animation:logoFl 4s ease-in-out infinite;
}
@keyframes logoFl{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
.logo-mini svg{width:100%;height:100%}
.header-info{flex:1;min-width:0}
.header-info h1{
  font-family:'Orbitron',sans-serif;
  font-size:15px;font-weight:900;letter-spacing:1.5px;
  background:linear-gradient(135deg,#00d4ff,#7b2ff7 60%,#f107a3);
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
}
.header-info p{font-size:9px;color:var(--txt-2);font-weight:700;margin-top:3px;letter-spacing:1.5px;text-transform:uppercase}
.logout-btn{
  display:inline-flex;align-items:center;gap:6px;
  background:rgba(255,255,255,.05);color:var(--txt-1);
  border:1px solid var(--line-2);
  padding:8px 12px;border-radius:11px;
  font-size:11px;font-weight:800;cursor:pointer;letter-spacing:.5px;
  transition:all .25s var(--ease);
}
.logout-btn:hover{background:rgba(241,7,163,.15);border-color:rgba(241,7,163,.5);color:#fff;transform:translateY(-1px)}

/* ---------- CONTAINER / TABS ---------- */
.container{max-width:1200px;margin:0 auto;padding:14px}
.tabs{
  display:grid;grid-template-columns:repeat(4,1fr);gap:6px;
  margin-bottom:14px;padding:6px;
  background:var(--bg-glass);
  backdrop-filter:blur(20px);
  border-radius:var(--r-lg);
  border:1px solid var(--line-2);
  box-shadow:0 8px 30px rgba(0,0,0,.4),inset 0 1px 0 rgba(255,255,255,.05);
}
.tab{
  position:relative;padding:11px 4px;border-radius:12px;cursor:pointer;
  font-size:10px;font-weight:800;letter-spacing:.6px;
  text-align:center;color:var(--txt-2);
  display:flex;flex-direction:column;align-items:center;gap:4px;
  user-select:none;background:transparent;border:none;
  transition:all .3s var(--ease);
  isolation:isolate;text-transform:uppercase;
}
.tab::before{
  content:'';position:absolute;inset:0;border-radius:inherit;
  background:var(--grad-brand);opacity:0;transform:scale(.92);
  transition:all .3s var(--ease);
  z-index:-1;
  box-shadow:0 10px 24px rgba(123,47,247,.5),0 0 30px rgba(0,212,255,.3);
}
.tab.active{color:#fff;transform:translateY(-2px)}
.tab.active::before{opacity:1;transform:scale(1)}
.tab .tab-icon{font-size:18px;line-height:1;transition:transform .3s var(--ease-2)}
.tab:hover .tab-icon{transform:scale(1.18) rotate(-4deg)}

.panel{display:none;animation:fadeUp .35s var(--ease)}
.panel.active{display:block}
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}

/* ---------- CARD ---------- */
.card{
  position:relative;
  background:linear-gradient(180deg,rgba(18,18,42,.85),rgba(10,10,26,.92));
  backdrop-filter:blur(20px);
  -webkit-backdrop-filter:blur(20px);
  padding:18px;border-radius:var(--r-xl);
  border:1px solid var(--line-2);
  box-shadow:
    0 8px 30px rgba(0,0,0,.4),
    inset 0 1px 0 rgba(255,255,255,.05);
  margin-bottom:14px;
  transition:all .35s var(--ease);
}
.card:hover{border-color:var(--line-3);box-shadow:0 12px 40px rgba(0,0,0,.5),0 0 40px rgba(0,212,255,.08),inset 0 1px 0 rgba(255,255,255,.08)}
.card h2{
  font-size:12.5px;font-weight:900;letter-spacing:.5px;
  margin-bottom:14px;display:flex;align-items:center;gap:9px;
  color:var(--txt-0);text-transform:uppercase;
}
.card h2 .bi{
  width:30px;height:30px;border-radius:10px;
  background:var(--grad-brand);
  display:flex;align-items:center;justify-content:center;
  font-size:13px;color:#fff;
  box-shadow:0 6px 16px rgba(123,47,247,.5),inset 0 1px 0 rgba(255,255,255,.3);
}

/* ---------- FORM ---------- */
.form-group{margin-bottom:13px}
.form-group label{
  display:block;margin-bottom:6px;
  font-size:10px;font-weight:800;color:var(--txt-2);
  text-transform:uppercase;letter-spacing:1px;
}
.form-group input,
.form-group textarea,
.form-group select{
  width:100%;padding:12px 14px;
  border:2px solid var(--line-2);border-radius:12px;
  font-size:13px;font-weight:500;
  background:rgba(255,255,255,.03);color:var(--txt-0);
  transition:all .25s var(--ease);
}
.form-group input::placeholder,
.form-group textarea::placeholder{color:var(--txt-3)}
.form-group input:focus,
.form-group textarea:focus,
.form-group select:focus{
  outline:none;border-color:var(--brand-a);background:rgba(0,212,255,.04);
  box-shadow:0 0 0 4px rgba(0,212,255,.12),0 0 25px rgba(0,212,255,.15);
}
.form-group textarea{
  min-height:96px;resize:vertical;
  font-family:'JetBrains Mono',ui-monospace,monospace;
  font-size:12px;line-height:1.55;
}
.form-group select{
  appearance:none;-webkit-appearance:none;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2300d4ff' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat:no-repeat;background-position:right 14px center;
  padding-right:38px;cursor:pointer;
}
.form-group select option{background:#12122a;color:var(--txt-0)}

/* ---------- BUTTONS ---------- */
.btn-circle{
  width:52px;height:52px;border-radius:50%;border:none;cursor:pointer;
  display:inline-flex;align-items:center;justify-content:center;
  font-size:20px;color:#fff;
  transition:all .3s var(--ease-2);
  position:relative;overflow:hidden;margin:3px;
  isolation:isolate;
}
.btn-circle::before{
  content:'';position:absolute;inset:0;border-radius:inherit;
  background:linear-gradient(120deg,transparent 30%,rgba(255,255,255,.5) 50%,transparent 70%);
  transform:translateX(-120%);
  transition:transform .7s var(--ease);
}
.btn-circle:hover{transform:translateY(-4px) scale(1.06);filter:brightness(1.1)}
.btn-circle:hover::before{transform:translateX(120%)}
.btn-circle:active{transform:translateY(-1px) scale(.98)}
.btn-circle:disabled{opacity:.4;cursor:not-allowed;filter:grayscale(.6)}
.btn-circle.primary{background:var(--grad-brand);box-shadow:0 10px 28px rgba(123,47,247,.5),0 0 30px rgba(0,212,255,.3),inset 0 1px 0 rgba(255,255,255,.3)}
.btn-circle.danger{background:var(--grad-err);box-shadow:0 10px 28px rgba(239,68,68,.5),inset 0 1px 0 rgba(255,255,255,.3)}
.btn-circle.success{background:var(--grad-ok);box-shadow:0 10px 28px rgba(16,185,129,.5),inset 0 1px 0 rgba(255,255,255,.3)}
.btn-circle.warning{background:var(--grad-warn);box-shadow:0 10px 28px rgba(245,158,11,.5),inset 0 1px 0 rgba(255,255,255,.3)}
.btn-circle.info{background:var(--grad-info);box-shadow:0 10px 28px rgba(59,130,246,.5),inset 0 1px 0 rgba(255,255,255,.3)}
.btn-circle.purple{background:var(--grad-purple);box-shadow:0 10px 28px rgba(139,92,246,.5),inset 0 1px 0 rgba(255,255,255,.3)}
.btn-circle.pink{background:var(--grad-pink);box-shadow:0 10px 28px rgba(236,72,153,.5),inset 0 1px 0 rgba(255,255,255,.3)}
.btn-circle.teal{background:var(--grad-teal);box-shadow:0 10px 28px rgba(20,184,166,.5),inset 0 1px 0 rgba(255,255,255,.3)}
.btn-circle.small{width:38px;height:38px;font-size:15px}
.btn-circle.big{width:74px;height:74px;font-size:28px}

.btn-rect{
  padding:12px 20px;border:none;border-radius:12px;cursor:pointer;
  font-size:11.5px;font-weight:900;letter-spacing:.6px;color:#fff;
  text-transform:uppercase;
  display:inline-flex;align-items:center;gap:7px;
  box-shadow:0 10px 22px rgba(0,0,0,.4),inset 0 1px 0 rgba(255,255,255,.25);
  transition:all .3s var(--ease-2);
}
.btn-rect:hover{transform:translateY(-3px);filter:brightness(1.1)}
.btn-rect:active{transform:translateY(-1px) scale(.98)}
.btn-rect.primary{background:var(--grad-brand)}
.btn-rect.danger{background:var(--grad-err)}
.btn-rect.success{background:var(--grad-ok)}
.btn-rect.info{background:var(--grad-info)}
.btn-rect.purple{background:var(--grad-purple)}
.btn-rect.full{width:100%;justify-content:center}

/* ---------- STAT ---------- */
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:8px;margin-bottom:14px}
.stat{
  position:relative;overflow:hidden;
  background:linear-gradient(180deg,rgba(35,35,70,.6),rgba(18,18,42,.8));
  padding:13px 12px;border-radius:var(--r-md);
  border:1px solid var(--line-2);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.05);
}
.stat::before{
  content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:var(--grad-brand);
  box-shadow:0 0 15px rgba(0,212,255,.6);
}
.stat::after{
  content:'';position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(120deg,transparent 40%,rgba(0,212,255,.15) 50%,transparent 60%);
  transform:translateX(-100%);
  animation:statShimmer 4s ease-in-out infinite;
}
@keyframes statShimmer{0%,60%{transform:translateX(-100%)}80%,100%{transform:translateX(100%)}}
.stat .label{font-size:9px;color:var(--txt-2);margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;font-weight:800}
.stat .value{font-size:22px;font-weight:900;color:var(--txt-0);line-height:1;font-variant-numeric:tabular-nums;font-family:'Orbitron',sans-serif}

/* ---------- TABLE ---------- */
.table-wrap{
  overflow-x:auto;border-radius:var(--r-md);
  border:1px solid var(--line-2);
  background:rgba(10,10,26,.5);
}
.table{width:100%;border-collapse:collapse}
.table th,.table td{
  padding:10px 8px;text-align:left;font-size:11px;
  border-bottom:1px solid var(--line);white-space:nowrap;
}
.table th{
  background:rgba(35,35,70,.7);font-weight:800;color:var(--brand-a);
  text-transform:uppercase;font-size:9px;letter-spacing:1px;
  position:sticky;top:0;z-index:1;
}
.table tbody tr{transition:background .2s var(--ease)}
.table tbody tr:hover{background:rgba(0,212,255,.05)}
.table tbody tr:last-child td{border-bottom:none}
.table td code{
  background:rgba(0,212,255,.08);padding:2px 7px;border-radius:6px;
  font-size:10px;font-family:'JetBrains Mono',monospace;
  color:var(--brand-a);font-weight:700;
  border:1px solid rgba(0,212,255,.15);
}

/* ---------- BADGE ---------- */
.badge{
  display:inline-flex;align-items:center;gap:4px;
  padding:3px 8px;border-radius:20px;
  font-size:9.5px;font-weight:800;letter-spacing:.4px;
}
.badge::before{content:'';width:5px;height:5px;border-radius:50%;background:currentColor;box-shadow:0 0 8px currentColor}
.badge-ok{background:rgba(16,185,129,.15);color:#34d399;border:1px solid rgba(16,185,129,.3)}
.badge-err{background:rgba(239,68,68,.15);color:#f87171;border:1px solid rgba(239,68,68,.3)}
.badge-warn{background:rgba(245,158,11,.15);color:#fbbf24;border:1px solid rgba(245,158,11,.3)}
.badge-info{background:rgba(59,130,246,.15);color:#60a5fa;border:1px solid rgba(59,130,246,.3)}
.badge-mode-fast{background:rgba(255,215,0,.12);color:#ffd700;border:1px solid rgba(255,215,0,.3)}
.badge-mode-ngon{background:rgba(0,212,255,.12);color:#00d4ff;border:1px solid rgba(0,212,255,.3)}
.badge-mode-nhay{background:rgba(241,7,163,.12);color:#f472b6;border:1px solid rgba(241,7,163,.3)}

/* ---------- BOX LIST ---------- */
.box-list{
  max-height:340px;overflow-y:auto;
  border:1px solid var(--line-2);border-radius:var(--r-md);
  padding:8px;background:rgba(10,10,26,.5);
}
.box-item{
  padding:11px;border-radius:11px;
  background:rgba(35,35,70,.5);
  margin-bottom:6px;cursor:pointer;
  border:1px solid var(--line-2);
  display:flex;align-items:center;gap:10px;font-size:12px;
  transition:all .25s var(--ease);
}
.box-item:hover{border-color:var(--brand-a);background:rgba(0,212,255,.05);transform:translateX(2px)}
.box-item.selected{
  border-color:var(--ok);background:rgba(16,185,129,.1);
  box-shadow:0 0 20px rgba(16,185,129,.2);
}
.box-item .check{
  width:19px;height:19px;border:2px solid var(--line-3);border-radius:6px;
  display:flex;align-items:center;justify-content:center;
  font-size:10px;color:transparent;font-weight:900;flex-shrink:0;
  transition:all .25s var(--ease);
}
.box-item.selected .check{background:var(--ok);border-color:var(--ok);color:#fff;box-shadow:0 0 12px var(--ok)}
.box-item .info{flex:1;min-width:0}
.box-item .name{font-weight:700;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--txt-0)}
.box-item .meta{font-size:10px;color:var(--txt-3);font-family:'JetBrains Mono',monospace;margin-top:2px}

/* ---------- FILE ---------- */
.file-item{
  display:flex;align-items:center;gap:10px;
  padding:11px;border-radius:12px;
  background:rgba(35,35,70,.5);margin-bottom:8px;
  border:1px solid var(--line-2);
  transition:all .25s var(--ease);
}
.file-item:hover{border-color:var(--brand-a);transform:translateY(-2px);box-shadow:0 10px 24px rgba(0,212,255,.1)}
.file-item .info{flex:1;min-width:0}
.file-item .name{font-weight:700;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--txt-0)}
.file-item .meta{font-size:10px;color:var(--txt-3);margin-top:2px}

/* ---------- CHIP ---------- */
.chip-group{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px}
.chip{
  position:relative;
  padding:8px 14px;background:rgba(35,35,70,.6);color:var(--txt-2);
  border-radius:20px;font-size:11px;font-weight:800;letter-spacing:.4px;
  cursor:pointer;user-select:none;
  border:1px solid var(--line-2);
  transition:all .25s var(--ease-2);
}
.chip:hover{background:rgba(0,212,255,.1);color:var(--brand-a);transform:translateY(-1px)}
.chip.active{
  background:var(--grad-brand);color:#fff;border-color:transparent;
  box-shadow:0 8px 22px rgba(123,47,247,.5),0 0 20px rgba(0,212,255,.3);
  transform:translateY(-2px);
}

/* ---------- TOGGLE ---------- */
.toggle-group{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}
.toggle{
  position:relative;padding:12px 10px;
  border:1px solid var(--line-2);border-radius:var(--r-md);
  cursor:pointer;text-align:center;
  font-weight:800;font-size:10.5px;letter-spacing:.5px;
  background:rgba(35,35,70,.4);color:var(--txt-2);
  user-select:none;isolation:isolate;text-transform:uppercase;
  transition:all .3s var(--ease-2);
}
.toggle::before{
  content:'';position:absolute;inset:-1px;border-radius:inherit;
  background:var(--grad-brand);opacity:0;transform:scale(.94);
  transition:all .3s var(--ease);
  z-index:-1;
  box-shadow:0 10px 24px rgba(123,47,247,.5),0 0 30px rgba(0,212,255,.3);
}
.toggle.active{color:#fff;border-color:transparent;transform:translateY(-2px)}
.toggle.active::before{opacity:1;transform:scale(1)}

/* ---------- MODE GRID ---------- */
.mode-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:6px}
.mode-card{
  position:relative;padding:14px 8px;border-radius:14px;cursor:pointer;
  background:rgba(35,35,70,.4);
  border:1px solid var(--line-2);
  text-align:center;
  transition:all .3s var(--ease-2);
  isolation:isolate;overflow:hidden;
}
.mode-card::before{
  content:'';position:absolute;inset:0;border-radius:inherit;
  background:var(--grad-brand);opacity:0;
  transition:opacity .3s var(--ease);
  z-index:-1;
}
.mode-card:hover{transform:translateY(-3px);border-color:var(--brand-a)}
.mode-card.active{
  border-color:transparent;color:#fff;
  box-shadow:0 12px 30px rgba(123,47,247,.5),0 0 30px rgba(0,212,255,.3);
  transform:translateY(-3px);
}
.mode-card.active::before{opacity:1}
.mode-card .mc-icon{font-size:24px;margin-bottom:6px;line-height:1}
.mode-card .mc-title{font-size:11px;font-weight:900;letter-spacing:.6px;color:var(--txt-0);margin-bottom:3px;text-transform:uppercase}
.mode-card .mc-desc{font-size:9px;font-weight:600;color:var(--txt-3);line-height:1.4}
.mode-card.active .mc-title{color:#fff}
.mode-card.active .mc-desc{color:rgba(255,255,255,.9)}

/* ---------- TAG SELECTOR ---------- */
.tag-selector{
  max-height:240px;overflow-y:auto;
  border:1px solid var(--line-2);border-radius:12px;
  padding:8px;background:rgba(10,10,26,.5);display:none;margin-top:8px;
}
.tag-selector.show{display:block}
.tag-member{
  padding:8px;border-radius:8px;background:rgba(35,35,70,.5);margin-bottom:4px;cursor:pointer;
  border:1px solid var(--line-2);font-size:12px;
  display:flex;align-items:center;gap:8px;
  transition:all .2s var(--ease);
}
.tag-member:hover{border-color:var(--purple);background:rgba(139,92,246,.08)}
.tag-member.selected{border-color:var(--purple);background:rgba(139,92,246,.15)}
.tag-member .check{
  width:16px;height:16px;border:2px solid var(--line-3);border-radius:4px;
  display:flex;align-items:center;justify-content:center;
  font-size:9px;color:transparent;font-weight:900;flex-shrink:0;
  transition:all .2s var(--ease);
}
.tag-member.selected .check{background:var(--purple);border-color:var(--purple);color:#fff}
.tag-member .tm-name{color:var(--txt-0);font-weight:700}
.tag-member .tm-uid{color:var(--txt-3);font-size:10px;font-family:'JetBrains Mono',monospace}

/* ---------- NOTIFICATION STACK ---------- */
#toast-stack{
  position:fixed;top:calc(20px + env(safe-area-inset-top,0px));right:16px;
  z-index:9999;display:flex;flex-direction:column;gap:10px;
  max-width:380px;width:calc(100% - 32px);pointer-events:none;
}
.toast{
  pointer-events:auto;position:relative;overflow:hidden;
  padding:14px 16px 14px 58px;
  border-radius:16px;
  background:linear-gradient(180deg,rgba(18,18,42,.97),rgba(10,10,26,.99));
  backdrop-filter:blur(20px) saturate(180%);
  -webkit-backdrop-filter:blur(20px) saturate(180%);
  box-shadow:
    0 20px 50px rgba(0,0,0,.6),
    0 0 40px rgba(0,212,255,.15),
    inset 0 1px 0 rgba(255,255,255,.1);
  border:1px solid var(--line-2);
  display:flex;flex-direction:column;gap:3px;
  animation:toastIn .5s var(--ease-2) both;
}
.toast.removing{animation:toastOut .35s var(--ease) both}
@keyframes toastIn{
  from{opacity:0;transform:translateX(120%) scale(.9)}
  to{opacity:1;transform:translateX(0) scale(1)}
}
@keyframes toastOut{
  from{opacity:1;transform:translateX(0) scale(1)}
  to{opacity:0;transform:translateX(120%) scale(.9)}
}
.toast::before{
  content:'';position:absolute;left:0;top:0;bottom:0;width:4px;
  background:var(--grad-brand);
}
.toast.success::before{background:var(--grad-ok)}
.toast.error::before{background:var(--grad-err)}
.toast.warning::before{background:var(--grad-warn)}
.toast.info::before{background:var(--grad-info)}
.toast .t-icon{
  position:absolute;left:14px;top:50%;transform:translateY(-50%);
  width:32px;height:32px;border-radius:10px;
  display:flex;align-items:center;justify-content:center;
  font-size:15px;color:#fff;font-weight:900;
  box-shadow:0 6px 16px rgba(0,0,0,.4),inset 0 1px 0 rgba(255,255,255,.3);
}
.toast.success .t-icon{background:var(--grad-ok)}
.toast.error .t-icon{background:var(--grad-err)}
.toast.warning .t-icon{background:var(--grad-warn)}
.toast.info .t-icon{background:var(--grad-info)}
.toast .t-title{font-size:12px;font-weight:900;color:var(--txt-0);letter-spacing:.4px;text-transform:uppercase}
.toast .t-msg{font-size:11.5px;font-weight:600;color:var(--txt-2);line-height:1.5}
.toast .t-msg code{background:rgba(0,212,255,.12);color:var(--brand-a);padding:1px 6px;border-radius:5px;font-size:10.5px;font-family:'JetBrains Mono',monospace}
.toast .t-progress{
  position:absolute;left:0;right:0;bottom:0;height:2px;
  background:rgba(255,255,255,.05);overflow:hidden;
}
.toast .t-progress::after{
  content:'';display:block;height:100%;width:100%;
  background:currentColor;opacity:.8;
  transform-origin:left;
  animation:toastBar linear forwards;
}
.toast.success .t-progress::after{color:var(--ok)}
.toast.error .t-progress::after{color:var(--err)}
.toast.warning .t-progress::after{color:var(--warn)}
.toast.info .t-progress::after{color:var(--info)}
@keyframes toastBar{from{transform:scaleX(1)}to{transform:scaleX(0)}}
.toast .t-close{
  position:absolute;top:8px;right:8px;
  width:22px;height:22px;border-radius:6px;border:none;
  background:transparent;color:var(--txt-3);cursor:pointer;
  font-size:12px;display:flex;align-items:center;justify-content:center;
  transition:all .2s var(--ease);
}
.toast .t-close:hover{background:rgba(255,255,255,.08);color:var(--txt-0)}

/* ---------- HUMAN PULSE ---------- */
.human-pulse{
  display:inline-flex;align-items:center;gap:5px;
  font-size:10px;font-weight:800;color:var(--ok);
  padding:3px 8px;border-radius:20px;
  background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.3);
  margin-left:6px;letter-spacing:.4px;
}
.human-pulse::before{
  content:'';width:6px;height:6px;border-radius:50%;
  background:var(--ok);
  animation:humanPulse 1.6s ease-in-out infinite;
  box-shadow:0 0 10px var(--ok);
}
@keyframes humanPulse{
  0%,100%{transform:scale(1);opacity:1}
  50%{transform:scale(1.4);opacity:.6}
}

/* ---------- HINT BOX ---------- */
.hint{
  font-size:10.5px;color:var(--txt-2);line-height:1.6;
  padding:10px 12px;background:rgba(0,212,255,.05);
  border-radius:10px;border-left:3px solid var(--brand-a);
  margin-top:10px;
}
.hint b{color:var(--brand-a);font-weight:800}

/* ---------- RESPONSIVE ---------- */
@media (max-width:640px){
  .container{padding:10px}
  .card{padding:14px;border-radius:var(--r-lg)}
  .header{padding:10px 12px;padding-top:calc(10px + env(safe-area-inset-top,0px))}
  .header-info h1{font-size:13px}
  .header-info p{font-size:8px}
  .logo-mini{width:38px;height:38px}
  .logout-btn{padding:7px 10px;font-size:10px}
  .logout-btn span{display:none}
  .tab{padding:9px 3px;font-size:8.5px}
  .tab .tab-icon{font-size:16px}
  .stat .value{font-size:18px}
  .btn-circle{width:46px;height:46px;font-size:18px}
  .btn-circle.small{width:34px;height:34px;font-size:13px}
  .btn-circle.big{width:62px;height:62px;font-size:22px}
  #toast-stack{left:12px;right:12px;max-width:none;width:auto}
  .mode-card .mc-desc{font-size:8px}
}

@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{
    animation-duration:.001ms !important;
    animation-iteration-count:1 !important;
    transition-duration:.001ms !important;
  }
}
</style>
</head>
<body>

<div class="header">
  <div class="header-inner">
    <div class="logo-mini">""" + LOGO_SVG + """</div>
    <div class="header-info">
      <h1>ALB FORGE</h1>
      <p>Universal • v27.0 • Anti-Pro</p>
    </div>
    <button class="logout-btn" onclick="location.href='/logout'">
      <span>Thoát</span>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="2.4"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
        <polyline points="16 17 21 12 16 7"/>
        <line x1="21" y1="12" x2="9" y2="12"/>
      </svg>
    </button>
  </div>
</div>

<div id="toast-stack"></div>

<div class="container">

<div class="tabs">
  <button type="button" class="tab active" data-tab="accounts"><div class="tab-icon">🔐</div><div>Acc</div></button>
  <button type="button" class="tab" data-tab="boxes"><div class="tab-icon">📦</div><div>Box</div></button>
  <button type="button" class="tab" data-tab="files"><div class="tab-icon">📁</div><div>File</div></button>
  <button type="button" class="tab" data-tab="spam"><div class="tab-icon">🎯</div><div>Spam</div></button>
</div>

<!-- ACCOUNTS -->
<div class="panel active" id="panel-accounts">
  <div class="card">
    <h2><span class="bi">➕</span> Thêm tài khoản</h2>
    <div class="form-group"><label>Tên gợi nhớ</label><input id="add-label" placeholder="acc1"></div>
    <div class="form-group"><label>IMEI</label><input id="add-imei" placeholder="000000000000000"></div>
    <div class="form-group"><label>Cookie (JSON)</label>
      <textarea id="add-cookies" placeholder='{"zpw_sek":"...","zpw_ver":"645","zpw_type":"30"}'></textarea>
    </div>
    <button type="button" class="btn-rect primary full" onclick="addAccount()">💾 Thêm tài khoản</button>
  </div>
  <div class="card">
    <h2><span class="bi">📋</span> Danh sách</h2>
    <div class="stat-grid">
      <div class="stat"><div class="label">Tổng</div><div class="value" id="stat-total">0</div></div>
      <div class="stat"><div class="label">Active</div><div class="value" id="stat-active">0</div></div>
      <div class="stat"><div class="label">Sent</div><div class="value" id="stat-sent">0</div></div>
    </div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr>
          <th>ID</th><th>Tên</th><th>UID</th><th>OK/Lỗi</th><th>Risk</th><th>Sent</th><th></th>
        </tr></thead>
        <tbody id="accounts-tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- BOXES -->
<div class="panel" id="panel-boxes">
  <div class="card">
    <h2><span class="bi">📦</span> Load Box</h2>
    <div class="form-group">
      <label>Chọn tài khoản</label>
      <select id="load-acc-select"><option value="">-- Chọn --</option></select>
    </div>
    <div style="text-align:center;">
      <button type="button" class="btn-circle primary" onclick="loadBoxes()" title="Load">🔄</button>
      <button type="button" class="btn-circle success" onclick="selectAllBoxes()" title="Chọn tất cả">✅</button>
      <button type="button" class="btn-circle danger" onclick="clearAllBoxes()" title="Bỏ chọn">❌</button>
    </div>
    <div style="margin-top:12px;">
      <div style="display:flex;justify-content:space-between;margin-bottom:6px;font-size:11px;">
        <b style="color:var(--txt-2);text-transform:uppercase;letter-spacing:1px;font-size:10px;">Đã chọn: <span id="selected-count" style="color:var(--brand-a);font-weight:900;">0</span></b>
      </div>
      <div class="box-list" id="box-list">
        <div style="text-align:center;padding:20px;color:var(--txt-3);font-size:11px;">Chưa load</div>
      </div>
    </div>
  </div>
</div>

<!-- FILES -->
<div class="panel" id="panel-files">
  <div class="card">
    <h2><span class="bi">📤</span> Upload file</h2>
    <div class="form-group"><input type="file" id="file-input" accept=".txt" style="padding:6px;"></div>
    <button type="button" class="btn-rect primary full" onclick="uploadFile()">📤 Upload</button>
    <div class="hint">
      💡 Mỗi khối ngăn bởi <b>dòng trống</b> = 1 tin nhắn.<br>
      Mode <b>Treo ngôn</b> gửi nguyên khối.<br>
      Mode <b>Treo nhây</b> tách từng dòng thành 1 tin riêng.
    </div>
  </div>
  <div class="card">
    <h2><span class="bi">📁</span> File đã upload</h2>
    <div id="files-list"><div style="text-align:center;padding:20px;color:var(--txt-3);font-size:11px;">Chưa có</div></div>
  </div>
</div>

<!-- SPAM -->
<div class="panel" id="panel-spam">
  <div class="card">
    <h2><span class="bi">🎯</span> Cấu hình spam</h2>

    <div class="form-group">
      <label>⚙️ Chế độ gửi</label>
      <div class="mode-grid" id="mode-grid">
        <div class="mode-card active" data-mode="fast">
          <div class="mc-icon">⚡</div>
          <div class="mc-title">Siêu nhanh</div>
          <div class="mc-desc">Xoay vòng block, tốc độ tối đa</div>
        </div>
        <div class="mode-card" data-mode="treo_ngon">
          <div class="mc-icon">❄️</div>
          <div class="mc-title">Treo ngôn</div>
          <div class="mc-desc">Nguyên khối 1 lần, không cắt</div>
        </div>
        <div class="mode-card" data-mode="treo_nhay">
          <div class="mc-icon">🌀</div>
          <div class="mc-title">Treo nhây</div>
          <div class="mc-desc">Tách từng dòng, đa màu</div>
        </div>
      </div>
      <input type="hidden" id="spam-mode" value="fast">
    </div>

    <div class="form-group">
      <label>Chọn file tin nhắn</label>
      <select id="spam-file-select"><option value="">-- Chọn file --</option></select>
    </div>

    <div class="form-group">
      <label>Hoặc nhập tin (mỗi khối cách nhau dấu ;)</label>
      <textarea id="spam-messages" placeholder="Tin 1 dòng 1&#10;Tin 1 dòng 2;Tin 2"></textarea>
    </div>

    <div class="form-group">
      <label>⏱ Delay (giây) — BẮT BUỘC gửi lên server</label>
      <div class="chip-group" id="delay-chips">
        <div class="chip" data-delay="0.3">0.3s</div>
        <div class="chip" data-delay="0.5">0.5s</div>
        <div class="chip active" data-delay="1">1s</div>
        <div class="chip" data-delay="2">2s</div>
        <div class="chip" data-delay="3">3s</div>
        <div class="chip" data-delay="5">5s</div>
        <div class="chip" data-delay="10">10s</div>
        <div class="chip" data-delay="30">30s</div>
      </div>
      <input type="hidden" id="spam-delay" value="1">
    </div>

    <div class="form-group">
      <label>😈 Số icon cuối câu</label>
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
      <div class="toggle active" id="tg-color" onclick="tgFlag('color')">🎨 Đổi màu</div>
      <div class="toggle active" id="tg-emoji" onclick="tgFlag('emoji')">😈 Thêm icon</div>
      <div class="toggle active" id="tg-multi" onclick="tgFlag('multi')">🌈 Đa màu dòng</div>
      <div class="toggle active" id="tg-human" onclick="tgFlag('human')">🧑 Giả người</div>
      <div class="toggle active" id="tg-mention" onclick="tgFlag('mention')">📢 Tag tên thật</div>
      <div class="toggle active" id="tg-session" onclick="tgFlag('session')">💤 Nghỉ session</div>
    </div>

    <div class="form-group" id="speed-wrap">
      <label>⌨️ Tốc độ gõ (giả người)</label>
      <div class="chip-group" id="speed-chips">
        <div class="chip" data-speed="instant">Tức thì</div>
        <div class="chip active" data-speed="fast">Nhanh</div>
        <div class="chip" data-speed="normal">Vừa</div>
        <div class="chip" data-speed="slow">Chậm</div>
      </div>
      <input type="hidden" id="typing-speed" value="fast">
    </div>

    <div class="form-group">
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;text-transform:none;letter-spacing:0;font-size:11px;color:var(--txt-1);">
        <input type="checkbox" id="tg-tag" onchange="tgTag()" style="width:auto;">
        Bật chọn members để tag
      </label>
      <div id="tag-wrap" style="display:none;margin-top:8px;">
        <div class="form-group">
          <select id="member-acc-select"><option value="">-- Chọn acc để load members --</option></select>
        </div>
        <button type="button" class="btn-rect info" onclick="loadMembers()">🔄 Load members</button>
        <div class="tag-selector" id="tag-selector"></div>
        <input type="hidden" id="tag-selected" value="">
        <div class="hint" style="margin-top:8px;">
          📢 <b>Tag tên thật</b>: Bot gửi kèm mentions array đúng chuẩn Zalo.<br>
          Tên phải khớp UID. Nhóm tắt mention → không tag được.
        </div>
      </div>
    </div>
  </div>

  <div style="text-align:center;margin-bottom:14px;">
    <button type="button" class="btn-circle success big" onclick="startSpam()" title="Bắt đầu">▶️</button>
    <button type="button" class="btn-circle danger big" onclick="stopAll()" title="Dừng">⏸️</button>
  </div>

  <div class="card">
    <h2><span class="bi">📋</span> Tác vụ</h2>
    <button type="button" class="btn-circle danger small" onclick="stopAll()" title="Dừng hết">⏸️</button>
    <div class="table-wrap" style="margin-top:10px;">
      <table class="table"><thead><tr>
        <th>ID</th><th>Mode</th><th>Delay</th><th>Trạng thái</th><th></th>
      </tr></thead><tbody id="tasks-tbody"></tbody></table>
    </div>
  </div>
</div>

</div>

<script>
/* ============================================================
   STATE
============================================================ */
var flags = {
  color: true, emoji: true, multi: true,
  human: true, mention: true, session: true
};
var selectedBoxes = [];
var selectedTags = [];
var _boxes = [];
var _members = [];
var currentMode = "fast";


/* ============================================================
   TOAST
============================================================ */
var Toast = (function(){
  var stack = null;
  function ensure(){ if(!stack) stack = document.getElementById('toast-stack'); return stack; }
  var ICONS = { success:'✓', error:'✕', warning:'!', info:'i' };
  var TITLES = { success:'Thành công', error:'Lỗi', warning:'Cảnh báo', info:'Thông tin' };

  function show(msg, type, title, duration){
    type = type || 'success'; duration = duration || 3500;
    var s = ensure(); if(!s) return;
    var el = document.createElement('div');
    el.className = 'toast ' + type;
    el.innerHTML =
      '<div class="t-icon">' + (ICONS[type] || '•') + '</div>' +
      '<button type="button" class="t-close" aria-label="Đóng">✕</button>' +
      '<div class="t-title">' + (title || TITLES[type] || '') + '</div>' +
      '<div class="t-msg">' + msg + '</div>' +
      '<div class="t-progress" style="animation-duration:' + duration + 'ms;"></div>';
    s.appendChild(el);
    var timer = setTimeout(remove, duration);
    function remove(){
      clearTimeout(timer);
      el.classList.add('removing');
      el.addEventListener('animationend', function(){ el.remove(); }, { once:true });
    }
    el.querySelector('.t-close').addEventListener('click', remove);
    return el;
  }
  return {
    success:function(m,t,d){return show(m,'success',t,d);},
    error:function(m,t,d){return show(m,'error',t,d);},
    warning:function(m,t,d){return show(m,'warning',t,d);},
    info:function(m,t,d){return show(m,'info',t,d);},
    show:show
  };
})();
function showAlert(m,t){ Toast.show(m, t==='error'?'error':'success'); }


/* ============================================================
   TABS
============================================================ */
document.querySelectorAll('.tab').forEach(function(t){
  t.addEventListener('click', function(){
    document.querySelectorAll('.tab').forEach(function(x){ x.classList.remove('active'); });
    document.querySelectorAll('.panel').forEach(function(x){ x.classList.remove('active'); });
    t.classList.add('active');
    var p = document.getElementById('panel-' + t.dataset.tab);
    if(p) p.classList.add('active');
    refreshAll();
  });
});


/* ============================================================
   MODE SELECTOR
============================================================ */
document.querySelectorAll('.mode-card').forEach(function(c){
  c.addEventListener('click', function(){
    document.querySelectorAll('.mode-card').forEach(function(x){ x.classList.remove('active'); });
    c.classList.add('active');
    currentMode = c.dataset.mode;
    document.getElementById('spam-mode').value = currentMode;
    var multiToggle = document.getElementById('tg-multi');
    if(currentMode === 'treo_nhay'){
      multiToggle.style.opacity = '1';
      multiToggle.style.pointerEvents = 'auto';
    } else if(currentMode === 'treo_ngon'){
      multiToggle.style.opacity = '.4';
      multiToggle.style.pointerEvents = 'none';
    } else {
      multiToggle.style.opacity = '1';
      multiToggle.style.pointerEvents = 'auto';
    }
  });
});


/* ============================================================
   CHIPS
============================================================ */
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


/* ============================================================
   TOGGLES
============================================================ */
function tgFlag(name){
  flags[name] = !flags[name];
  var map = {
    'color':'tg-color','emoji':'tg-emoji','multi':'tg-multi',
    'human':'tg-human','mention':'tg-mention','session':'tg-session'
  };
  var el = document.getElementById(map[name] || ('tg-'+name));
  if(el) el.classList.toggle('active', flags[name]);

  if(name === 'human'){
    var sw = document.getElementById('speed-wrap');
    if(sw){
      sw.style.opacity = flags.human ? '1' : '.4';
      sw.style.pointerEvents = flags.human ? 'auto' : 'none';
    }
  }
  if(name === 'mention'){
    var tw = document.getElementById('tag-wrap');
    if(tw && !flags.mention){
      // không tắt UI tag, chỉ disable gửi mentions
    }
  }
}
function tgTag(){
  var c = document.getElementById('tg-tag');
  var wrap = document.getElementById('tag-wrap');
  if(wrap) wrap.style.display = c.checked ? 'block' : 'none';
}


/* ============================================================
   API
============================================================ */
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
    return { error: 'Kết nối lỗi: ' + e.message };
  }
}


/* ============================================================
   ACCOUNTS
============================================================ */
async function loadAccounts(){
  var accs = await api('/api/accounts');
  if(!Array.isArray(accs)) accs = [];
  var tb = document.getElementById('accounts-tbody');
  if(!accs.length){
    tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--txt-3);padding:20px;">Chưa có</td></tr>';
  } else {
    tb.innerHTML = accs.map(function(a){
      var risk = (a.risk || 0).toFixed(2);
      var rc = risk > 0.5 ? 'badge-err' : risk > 0.2 ? 'badge-warn' : 'badge-ok';
      var uidShort = a.uid ? String(a.uid).slice(-6) : '?';
      return '<tr>' +
        '<td>' + a.id + '</td>' +
        '<td><b style="color:var(--txt-0)">' + a.label + '</b></td>' +
        '<td><code>…' + uidShort + '</code></td>' +
        '<td><span class="badge badge-ok">' + a.ok_count + '</span> <span class="badge badge-err">' + a.fail_count + '</span></td>' +
        '<td><span class="badge ' + rc + '">' + risk + '</span></td>' +
        '<td><span class="badge badge-info">' + (a.total_sent || 0) + '</span></td>' +
        '<td>' +
          '<button type="button" class="btn-circle primary small" onclick="checkAcc(' + a.id + ')" title="Check">🔍</button>' +
          '<button type="button" class="btn-circle warning small" onclick="resetAcc(' + a.id + ')" title="Reset">🔄</button>' +
          '<button type="button" class="btn-circle danger small" onclick="delAcc(' + a.id + ')" title="Xoá">🗑️</button>' +
        '</td>' +
      '</tr>';
    }).join('');
  }
  document.getElementById('stat-total').textContent = accs.length;
  document.getElementById('stat-active').textContent = accs.filter(function(a){return a.enabled;}).length;
  document.getElementById('stat-sent').textContent = accs.reduce(function(s,a){return s+(a.total_sent||0);},0);

  var s1 = document.getElementById('load-acc-select');
  var s2 = document.getElementById('member-acc-select');
  var opts = '<option value="">-- Chọn --</option>' +
    accs.map(function(a){return '<option value="'+a.id+'">'+a.label+'</option>';}).join('');
  var v1 = s1.value, v2 = s2.value;
  s1.innerHTML = opts; s1.value = v1;
  s2.innerHTML = opts; s2.value = v2;
}

async function addAccount(){
  var label = document.getElementById('add-label').value.trim();
  var imei = document.getElementById('add-imei').value.trim();
  var cookies = document.getElementById('add-cookies').value.trim();
  if(!imei || !cookies){ return Toast.error('Điền IMEI và cookie'); }
  var t = Toast.info('Đang verify cookie...', 'Vui lòng đợi', 30000);
  var r = await api('/api/accounts/add', {
    method:'POST',
    body: JSON.stringify({ label:label, imei:imei, cookies:cookies })
  });
  if(r.error){ return Toast.error(r.error, 'Thêm thất bại'); }
  Toast.success('Đã thêm <b>' + r.label + '</b><br>UID: <code>' + r.uid + '</code>', 'Cookie sống');
  document.getElementById('add-label').value = '';
  document.getElementById('add-imei').value = '';
  document.getElementById('add-cookies').value = '';
  refreshAll();
}

async function delAcc(id){
  if(!confirm('Xóa tài khoản #' + id + '?')) return;
  await api('/api/accounts/' + id, { method:'DELETE' });
  Toast.success('Đã xóa #' + id); refreshAll();
}
async function resetAcc(id){
  await api('/api/accounts/' + id + '/reset', { method:'POST' });
  Toast.info('Đã reset risk #' + id); refreshAll();
}
async function checkAcc(id){
  Toast.info('Đang check cookie #' + id + '...', 'Kiểm tra', 20000);
  var r = await api('/api/accounts/' + id + '/check', { method:'POST' });
  if(r.error){ return Toast.error(r.error, 'Check thất bại'); }
  Toast.success('Cookie sống<br>UID: <code>' + r.uid + '</code>', 'Check OK');
}


/* ============================================================
   BOXES
============================================================ */
async function loadBoxes(){
  var aid = document.getElementById('load-acc-select').value;
  if(!aid) return Toast.error('Chọn tài khoản trước');
  Toast.info('Đang load box...', 'Vui lòng đợi', 90000);
  var r = await api('/api/accounts/' + aid + '/load_boxes', { method:'POST' });
  if(r.error) return Toast.error(r.error, 'Load thất bại');
  var all = (r.groups||[]).concat(r.friends||[]);
  var bl = document.getElementById('box-list');
  if(!all.length){
    bl.innerHTML = '<div style="text-align:center;padding:20px;color:var(--txt-3);">Không có box nào</div>';
    return;
  }
  bl.innerHTML = all.map(function(b,i){
    return '<div class="box-item" data-idx="'+i+'" onclick="tgBox(this, '+i+')">' +
      '<div class="check">✓</div>' +
      '<div class="info">' +
        '<div class="name">' + b.name + '</div>' +
        '<div class="meta">' + b.id + ' | ' + b.type + (b.members?(' | '+b.members+' mem'):'') + '</div>' +
      '</div>' +
    '</div>';
  }).join('');
  _boxes = all;
  selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
  Toast.success('Đã load <b>' + all.length + '</b> box', 'Load OK');
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


/* ============================================================
   FILES
============================================================ */
async function uploadFile(){
  var input = document.getElementById('file-input');
  if(!input.files.length) return Toast.error('Chưa chọn file');
  var fd = new FormData();
  fd.append('file', input.files[0]);
  Toast.info('Đang upload...', 'Vui lòng đợi', 60000);
  try {
    var r = await fetch('/api/files/upload', { method:'POST', body: fd }).then(function(x){return x.json();});
    if(r.error) return Toast.error(r.error);
    Toast.success('Đã upload <b>' + r.filename + '</b><br>' + r.lines + ' khối', 'Upload OK');
    input.value = '';
    loadFiles();
  } catch(e){ Toast.error('Upload lỗi: ' + e.message); }
}
async function loadFiles(){
  var files = await api('/api/files');
  if(!Array.isArray(files)) files = [];
  var list = document.getElementById('files-list');
  if(!files.length){
    list.innerHTML = '<div style="text-align:center;padding:20px;color:var(--txt-3);font-size:11px;">Chưa có</div>';
  } else {
    list.innerHTML = files.map(function(f){
      var kb = (f.size/1024).toFixed(1);
      return '<div class="file-item">' +
        '<div class="info">' +
          '<div class="name">📄 ' + f.filename + '</div>' +
          '<div class="meta">' + f.lines + ' khối • ' + kb + ' KB</div>' +
        '</div>' +
        '<button type="button" class="btn-circle info small" onclick="previewFile('+f.id+')" title="Xem">👁️</button>' +
        '<button type="button" class="btn-circle danger small" onclick="delFile('+f.id+')" title="Xoá">🗑️</button>' +
      '</div>';
    }).join('');
  }
  var s = document.getElementById('spam-file-select');
  var cur = s.value;
  s.innerHTML = '<option value="">-- Chọn file --</option>' +
    files.map(function(f){return '<option value="'+f.id+'">'+f.filename+' ('+f.lines+')</option>';}).join('');
  s.value = cur;
}
async function previewFile(fid){
  var r = await api('/api/files/' + fid + '/preview');
  if(r.error) return Toast.error(r.error);
  var pv = (r.preview||[]).map(function(m,i){return '--- Khối '+(i+1)+' ---\\n'+m;}).join('\\n\\n');
  alert('File: '+r.filename+'\\nTổng: '+r.total+' khối\\n\\n'+pv);
}
async function delFile(fid){
  if(!confirm('Xóa file?')) return;
  await api('/api/files/' + fid, { method:'DELETE' });
  Toast.success('Đã xóa file'); loadFiles();
}


/* ============================================================
   MEMBERS
============================================================ */
async function loadMembers(){
  var aid = document.getElementById('member-acc-select').value;
  if(!aid) return Toast.error('Chọn acc để load members');
  var box = selectedBoxes.find(function(b){return b.type === 'group';});
  if(!box) return Toast.error('Cần chọn 1 NHÓM trong tab Box trước');
  Toast.info('Đang load members...', 'Vui lòng đợi', 90000);
  var r = await api('/api/accounts/' + aid + '/members/' + box.id, { method:'POST' });
  if(r.error) return Toast.error(r.error);
  var mem = r.members || [];
  var sel = document.getElementById('tag-selector');
  sel.classList.add('show');
  if(!mem.length){
    sel.innerHTML = '<div style="padding:14px;text-align:center;color:var(--txt-3);font-size:11px;">Không có members</div>';
    return;
  }
  sel.innerHTML = mem.map(function(m,i){
    return '<div class="tag-member" data-idx="'+i+'" onclick="tgMember(this, '+i+')">' +
      '<div class="check">✓</div>' +
      '<div><span class="tm-name">' + m.name + '</span> <span class="tm-uid">' + m.id + '</span></div>' +
    '</div>';
  }).join('');
  _members = mem;
  selectedTags = [];
  Toast.success('Đã load <b>' + mem.length + '</b> members — bấm chọn', 'Load OK');
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


/* ============================================================
   SPAM
============================================================ */
async function startSpam(){
  if(!selectedBoxes.length) return Toast.error('Chưa chọn box — vào tab Box chọn target trước');
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
  if(!blocks.length) return Toast.error('Chưa có tin nhắn — chọn file hoặc nhập tay');
  var delay = parseFloat(document.getElementById('spam-delay').value) || 1;
  if(delay < 0.3) return Toast.error('Delay tối thiểu 0.3s');
  var iconCount = parseInt(document.getElementById('icon-count').value) || 3;
  var typingSpeed = document.getElementById('typing-speed').value || 'fast';
  var tagUsers = [];
  if(document.getElementById('tg-tag').checked) tagUsers = selectedTags;

  var payload = {
    targets: selectedBoxes,
    blocks: blocks,
    delay: delay,
    use_color: flags.color,
    use_emoji: flags.emoji,
    icon_count: iconCount,
    tag_users: tagUsers,
    mode: currentMode,
    multi_color: flags.multi,
    typing_speed: typingSpeed,
    human_mode: flags.human,
    real_mention: flags.mention,
    read_receipt: flags.human,
    session_mode: flags.session
  };
  var r = await api('/api/tasks/start', { method:'POST', body: JSON.stringify(payload) });
  if(r.error) return Toast.error(r.error);
  var modeName = {'fast':'⚡ Siêu nhanh','treo_ngon':'❄️ Treo ngôn','treo_nhay':'🌀 Treo nhây'}[currentMode] || currentMode;
  var extras = [];
  if(flags.multi) extras.push('🌈 đa màu');
  if(flags.human) extras.push('🧑 giả người');
  if(flags.mention && tagUsers.length) extras.push('📢 tag thật');
  if(flags.session) extras.push('💤 session');
  var suffix = extras.length ? '<br><small style="color:var(--txt-3)">' + extras.join(' • ') + '</small>' : '';
  Toast.success('🚀 ' + modeName + ': <code>' + r.task_id + '</code><br>Delay <b>' + delay + 's</b>' + suffix, 'Task running', 5000);
  loadTasks();
}
async function stopAll(){
  await api('/api/tasks/stop_all', { method:'POST' });
  Toast.warning('Đã ra lệnh dừng tất cả task'); loadTasks();
}
async function loadTasks(){
  var tasks = await api('/api/tasks');
  if(!Array.isArray(tasks)) tasks = [];
  var tb = document.getElementById('tasks-tbody');
  if(!tasks.length){
    tb.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--txt-3);padding:16px;">Chưa có</td></tr>';
    return;
  }
  tb.innerHTML = tasks.map(function(t){
    var running = t.status === 'running';
    var b = running ? 'badge-ok' : 'badge-err';
    var txt = running ? 'Đang chạy' : 'Đã dừng';
    var meta = {};
    try { meta = JSON.parse(t.meta || '{}'); } catch(e){}
    var mode = meta.mode || 'fast';
    var modeLabels = {
      'fast':['⚡ Nhanh','badge-mode-fast'],
      'treo_ngon':['❄️ Ngôn','badge-mode-ngon'],
      'treo_nhay':['🌀 Nhây','badge-mode-nhay']
    };
    var ml = modeLabels[mode] || modeLabels['fast'];
    var d = meta.delay ? (meta.delay + 's') : '—';
    return '<tr>' +
      '<td><code>' + t.id + '</code></td>' +
      '<td><span class="badge ' + ml[1] + '">' + ml[0] + '</span></td>' +
      '<td><b style="color:var(--brand-a)">' + d + '</b></td>' +
      '<td><span class="badge ' + b + '">' + txt + '</span></td>' +
      '<td>' + (running ? '<button type="button" class="btn-circle danger small" onclick="stopTask(\\'' + t.id + '\\')" title="Dừng">⏸️</button>' : '') + '</td>' +
    '</tr>';
  }).join('');
}
async function stopTask(tid){
  await api('/api/tasks/' + tid + '/stop', { method:'POST' });
  Toast.warning('Đã dừng task <code>' + tid + '</code>'); loadTasks();
}


/* ============================================================
   BOOT
============================================================ */
function refreshAll(){ loadAccounts(); loadFiles(); loadTasks(); }
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
