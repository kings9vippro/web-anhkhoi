# ============================================================
# WEB-LENH v26.1 — Bot by Anh Khôi
# Universal Forge UI • 2-mode freeze • Notification Stack
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
            total_sent INTEGER DEFAULT 0
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
# ICON ZALO
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
# ANTI-BAN VIP v26.1
# ============================================================
class AntiBanVIP:
    MIN_DELAY = 0.3
    MAX_DELAY = 30.0

    @staticmethod
    def compute_delay(user_delay, risk):
        d = max(AntiBanVIP.MIN_DELAY, user_delay)
        if risk > 0.85:
            d = max(d, 15.0)
        elif risk > 0.7:
            d = max(d, 8.0)
        elif risk > 0.5:
            d = max(d, 4.0)
        d = d * random.uniform(0.75, 1.25)
        return max(AntiBanVIP.MIN_DELAY, min(AntiBanVIP.MAX_DELAY, d))

    @staticmethod
    def compute_risk(ok, fail):
        total = ok + fail
        if total == 0:
            return 0.0
        return min(1.0, fail / total)

    ZALO_COLORS = ["red", "orange", "yellow", "green", "ocean",
                   "blue", "purple", "pink", "brown", "black",
                   "gray", "white"]

    @staticmethod
    def random_color():
        return random.choice(AntiBanVIP.ZALO_COLORS)

    @staticmethod
    def append_icons(text, count):
        icons = [get_icon_hard() for _ in range(count)]
        return text + " " + " ".join(icons)


# ============================================================
# ZALO API
# ============================================================
class Zalo:
    def __init__(self, imei, cookies):
        self.imei = imei
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
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
        enc = self._enc({"gridVerMap": json.dumps({str(gid): 0})})
        r = self.s.post(
            "https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2",
            params={"zpw_ver": 645, "zpw_type": 30},
            data={"params": enc}, timeout=20,
        )
        dec = self._dec(r.json()["data"])
        info = json.loads(dec).get("data", {}).get("gridInfoMap", {}).get(str(gid), {})
        mem_list = info.get("memVerList", [])

        members = []
        uids = [m.split("_")[0] for m in mem_list]
        if not uids:
            return []

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
                members.append({
                    "id": uid,
                    "name": p.get("displayName") or p.get("zaloName") or "User_" + uid[:6],
                })
        except Exception:
            for uid in uids:
                members.append({"id": uid, "name": "User_" + uid[:6]})
        return members

    def send(self, msg, thread_id, color=None, is_group=True):
        url = ("https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
               if is_group
               else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms")
        pl = {
            "message": msg,
            "clientId": str(int(time.time() * 1000)),
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


# ============================================================
# PARSE FILE
# ============================================================
def parse_blocks(filepath, max_blocks=2000):
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


def count_blocks(filepath):
    return len(parse_blocks(filepath))


# ============================================================
# WORKER — 2-mode freeze: TREO NGÔN + TREO NHÂY
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
    risk = AntiBanVIP.compute_risk(ok_c, fail_c)
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


def pick_account():
    conn = db()
    rows = conn.execute("""
        SELECT * FROM accounts
        WHERE enabled = 1 AND risk < 0.85
        ORDER BY risk ASC, last_used ASC
        LIMIT 1
    """).fetchall()
    conn.close()
    return rows[0] if rows else None


def spam_worker(tid, targets, blocks, delay, use_color, use_emoji,
                icon_count, tag_uids_names, stop_event,
                freeze_text=False, freeze_delay=False,
                freeze_text_after=0, freeze_delay_after=0):
    """
    freeze_text: TREO NGÔN — sau N tin thì gửi đúng 1 tin cố định lặp mãi
    freeze_delay: TREO NHÂY — sau N tin thì delay giữ nguyên 1 giá trị (không jitter)
    """
    block_idx = 0
    target_idx = 0
    count = 0
    last_acc_id = None
    frozen_text = None
    frozen_delay = None

    print("[SPAM] Bắt đầu: " + tid)
    print("  Targets: " + str(len(targets)))
    print("  Blocks: " + str(len(blocks)))
    print("  Delay: " + str(delay) + "s")
    print("  Tags: " + str(len(tag_uids_names)))
    print("  FreezeText: " + str(freeze_text) + " after " + str(freeze_text_after))
    print("  FreezeDelay: " + str(freeze_delay) + " after " + str(freeze_delay_after))

    while not stop_event.is_set():
        acc = pick_account()
        if not acc:
            time.sleep(0.5)
            continue

        if acc["id"] == last_acc_id:
            conn = db()
            cnt = conn.execute(
                "SELECT COUNT(*) as c FROM accounts WHERE enabled = 1"
            ).fetchone()["c"]
            conn.close()
            if cnt > 1:
                time.sleep(0.15)
                continue
        last_acc_id = acc["id"]

        target = targets[target_idx % len(targets)]
        target_idx += 1

        # -------- TREO NGÔN --------
        if freeze_text and count >= freeze_text_after:
            if frozen_text is None:
                frozen_text = blocks[block_idx % len(blocks)]
            raw = frozen_text
        else:
            raw = blocks[block_idx % len(blocks)]
            block_idx += 1

        # Tag
        if tag_uids_names:
            tags = " ".join(["@" + t["name"] for t in tag_uids_names])
            msg = tags + " " + raw
        else:
            msg = raw

        # Icon
        if use_emoji and icon_count > 0:
            msg = AntiBanVIP.append_icons(msg, icon_count)

        # Color
        color = AntiBanVIP.random_color() if use_color else None

        is_group = target.get("type") == "group"
        target_id = target.get("id")

        try:
            cookies = json.loads(acc["cookies"])
            z = Zalo(acc["imei"], cookies)

            z.set_typing(target_id, is_group=is_group)
            time.sleep(random.uniform(0.3, 1.0))

            r = z.send(msg, target_id, color=color, is_group=is_group)
            ok = bool(r and r.status_code == 200)

            update_stats(acc["id"], ok)
            count += 1
            status = "OK" if ok else "ERR"
            cs = "[" + color + "]" if color else ""
            preview = msg.replace("\n", " ⏎ ")[:60]
            tag_frz = ""
            if freeze_text and count > freeze_text_after:
                tag_frz = " ❄️TREO-NGÔN"
            print("[#" + str(count) + "] " + acc["label"] + " → " +
                  str(target_id) + cs + " [" + status + "]" + tag_frz + " " + preview)

        except Exception as e:
            update_stats(acc["id"], False)
            print("[SPAM] Error " + acc["label"] + ": " + str(e))

        # -------- TREO NHÂY --------
        risk = acc["risk"] if acc["risk"] else 0.0
        if freeze_delay and count >= freeze_delay_after:
            if frozen_delay is None:
                frozen_delay = AntiBanVIP.compute_delay(delay, risk)
            actual = frozen_delay
        else:
            actual = AntiBanVIP.compute_delay(delay, risk)

        end = time.time() + actual
        while time.time() < end:
            if stop_event.is_set():
                break
            time.sleep(0.05)

    conn = db()
    conn.execute(
        "UPDATE tasks SET status = 'stopped', stats = ? WHERE id = ?",
        (json.dumps({"sent": count}), tid)
    )
    conn.commit()
    conn.close()
    ACTIVE_TASKS.pop(tid, None)
    print("[SPAM] Task " + tid + " stop - total: " + str(count))


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


@app.route("/api/accounts", methods=["GET"])
@login_required
def api_accounts():
    conn = db()
    rows = conn.execute("""
        SELECT id, label, imei, ok_count, fail_count, risk,
               total_sent, enabled
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
    conn = db()
    conn.execute("""
        INSERT INTO accounts (label, imei, cookies, added_at)
        VALUES (?, ?, ?, ?)
    """, (label, imei, json.dumps(ck_obj), time.time()))
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
        return jsonify({"ok": True, "members": members})
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
        return jsonify({"error": "Không có file"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Tên trống"}), 400
    safe = str(int(time.time())) + "_" + f.filename
    fp = os.path.join(UPLOAD_DIR, safe)
    f.save(fp)
    blocks = parse_blocks(fp, max_blocks=2000)
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
    blocks = parse_blocks(row["filepath"], max_blocks=2000)
    return jsonify({"filename": row["filename"],
                    "total": len(blocks),
                    "preview": blocks[:5],
                    "all": blocks})


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
    delay = float(d.get("delay", 3))
    use_color = bool(d.get("use_color", True))
    use_emoji = bool(d.get("use_emoji", True))
    icon_count = int(d.get("icon_count", 3))
    tag_uids_names = d.get("tag_users", [])

    freeze_text = bool(d.get("freeze_text", False))
    freeze_delay = bool(d.get("freeze_delay", False))
    freeze_text_after = int(d.get("freeze_text_after", 10))
    freeze_delay_after = int(d.get("freeze_delay_after", 10))

    if not targets:
        return jsonify({"error": "Chưa chọn target"}), 400
    if not blocks:
        return jsonify({"error": "Chưa có tin nhắn"}), 400
    if delay < AntiBanVIP.MIN_DELAY:
        delay = AntiBanVIP.MIN_DELAY
    if icon_count < 0:
        icon_count = 0
    if icon_count > 20:
        icon_count = 20
    if freeze_text_after < 0:
        freeze_text_after = 0
    if freeze_delay_after < 0:
        freeze_delay_after = 0

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
              icon_count, tag_uids_names, stop_ev,
              freeze_text, freeze_delay,
              freeze_text_after, freeze_delay_after),
        daemon=True,
    )

    conn = db()
    conn.execute("""
        INSERT INTO tasks (id, type, meta, status, started_at, stats)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tid, "spam",
          json.dumps({"targets": len(targets), "blocks": len(blocks),
                      "delay": delay, "tags": len(tag_uids_names),
                      "freeze_text": freeze_text,
                      "freeze_delay": freeze_delay}),
          "running", time.time(), "{}"))
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
    return jsonify({"error": "Không tồn tại"}), 404


@app.route("/api/tasks/stop_all", methods=["POST"])
@login_required
def api_tasks_stop_all():
    for tid, t in list(ACTIVE_TASKS.items()):
        t["stop"].set()
    return jsonify({"ok": True, "count": len(ACTIVE_TASKS)})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "web-lenh", "version": "26.1"})


# ============================================================
# LOGO SVG — tinh xảo
# ============================================================
LOGO_SVG = """<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" fill="none">
<defs>
<linearGradient id="gA" x1="0" y1="0" x2="1" y2="1">
<stop offset="0%" stop-color="#f093fb"/>
<stop offset="50%" stop-color="#f5576c"/>
<stop offset="100%" stop-color="#764ba2"/>
</linearGradient>
<linearGradient id="gB" x1="0" y1="1" x2="1" y2="0">
<stop offset="0%" stop-color="#667eea"/>
<stop offset="50%" stop-color="#764ba2"/>
<stop offset="100%" stop-color="#f093fb"/>
</linearGradient>
<linearGradient id="gStroke" x1="0" y1="0" x2="1" y2="1">
<stop offset="0%" stop-color="#ffffff" stop-opacity="0.95"/>
<stop offset="100%" stop-color="#ffffff" stop-opacity="0.4"/>
</linearGradient>
<radialGradient id="gC" cx="0.5" cy="0.5" r="0.6">
<stop offset="0%" stop-color="#ffffff" stop-opacity="0.85"/>
<stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
</radialGradient>
<radialGradient id="gGlow" cx="0.5" cy="0.5" r="0.5">
<stop offset="0%" stop-color="#f5576c" stop-opacity="0.8"/>
<stop offset="100%" stop-color="#f5576c" stop-opacity="0"/>
</radialGradient>
<filter id="fg" x="-50%" y="-50%" width="200%" height="200%">
<feGaussianBlur stdDeviation="2.5" result="b"/>
<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
</filter>
<filter id="softGlow"><feGaussianBlur stdDeviation="6"/></filter>
</defs>
<circle cx="60" cy="60" r="56" fill="url(#gGlow)" filter="url(#softGlow)"/>
<circle cx="60" cy="60" r="54" fill="none" stroke="url(#gB)" stroke-width="0.8"
 stroke-dasharray="3 6" opacity="0.55">
<animateTransform attributeName="transform" type="rotate"
 from="0 60 60" to="360 60 60" dur="30s" repeatCount="indefinite"/>
</circle>
<circle cx="60" cy="60" r="48" fill="none" stroke="url(#gA)" stroke-width="0.6"
 opacity="0.35" stroke-dasharray="2 4">
<animateTransform attributeName="transform" type="rotate"
 from="360 60 60" to="0 60 60" dur="20s" repeatCount="indefinite"/>
</circle>
<circle cx="60" cy="60" r="44" fill="url(#gC)" opacity="0.25"/>
<path d="M60 14 C32 14, 14 32, 14 56 C14 78, 32 96, 60 96 C67 96, 74 94, 80 91
 L104 102 L98 80 C107 73, 112 65, 112 56 C112 32, 88 14, 60 14 Z"
 fill="url(#gA)" filter="url(#fg)"/>
<path d="M60 14 C32 14, 14 32, 14 56 C14 60, 15 64, 16 68
 C22 50, 40 30, 60 26 C76 22, 92 30, 100 46
 C104 50, 107 53, 110 56 C112 32, 88 14, 60 14 Z"
 fill="white" opacity="0.18"/>
<path d="M60 14 C32 14, 14 32, 14 56 C14 78, 32 96, 60 96 C67 96, 74 94, 80 91
 L104 102 L98 80 C107 73, 112 65, 112 56 C112 32, 88 14, 60 14 Z"
 fill="none" stroke="url(#gStroke)" stroke-width="1.2"/>
<g>
<circle cx="42" cy="52" r="6" fill="white"/>
<circle cx="42" cy="53" r="3.2" fill="#1a1a2e"/>
<circle cx="43.2" cy="51.4" r="1.1" fill="white"/>
</g>
<g>
<circle cx="62" cy="52" r="6" fill="white"/>
<circle cx="62" cy="53" r="3.2" fill="#1a1a2e"/>
<circle cx="63.2" cy="51.4" r="1.1" fill="white"/>
</g>
<g>
<circle cx="82" cy="52" r="6" fill="white"/>
<circle cx="82" cy="53" r="3.2" fill="#1a1a2e"/>
<circle cx="83.2" cy="51.4" r="1.1" fill="white"/>
</g>
<path d="M36 72 Q60 86 84 72" stroke="white" stroke-width="2.6"
 stroke-linecap="round" fill="none" opacity="0.95"/>
<path d="M94 18 L97 27 L106 30 L97 33 L94 42 L91 33 L82 30 L91 27 Z"
 fill="url(#gB)" filter="url(#fg)">
<animateTransform attributeName="transform" type="rotate"
 from="0 94 30" to="360 94 30" dur="12s" repeatCount="indefinite"/>
</path>
<path d="M18 88 L20 94 L26 96 L20 98 L18 104 L16 98 L10 96 L16 94 Z"
 fill="url(#gB)" filter="url(#fg)" opacity="0.9">
<animateTransform attributeName="transform" type="scale"
 values="1;1.25;1" dur="2.4s" repeatCount="indefinite" additive="sum"/>
</path>
<circle cx="88" cy="76" r="1.4" fill="white" opacity="0.9">
<animate attributeName="opacity" values="0.3;1;0.3" dur="2s" repeatCount="indefinite"/>
</circle>
<circle cx="30" cy="34" r="1.2" fill="white" opacity="0.7">
<animate attributeName="opacity" values="1;0.3;1" dur="1.8s" repeatCount="indefinite"/>
</circle>
</svg>"""


# ============================================================
# CSS ROOT — shared design tokens
# ============================================================
CSS_ROOT = """
:root{
  --bg-0:#f8fafc; --bg-1:#ffffff; --bg-2:#f1f5f9;
  --line:#e5e7eb; --line-2:#eef2f7;
  --txt-0:#0f172a; --txt-1:#1a1a2e; --txt-2:#64748b; --txt-3:#94a3b8;
  --brand-a:#667eea; --brand-b:#764ba2; --brand-c:#f5576c; --brand-d:#f093fb;
  --ok:#10b981; --err:#ef4444; --warn:#f59e0b; --info:#3b82f6;
  --purple:#8b5cf6; --pink:#ec4899; --teal:#14b8a6;
  --grad-brand:linear-gradient(135deg,#667eea 0%,#764ba2 100%);
  --grad-hot:linear-gradient(135deg,#f093fb 0%,#f5576c 100%);
  --grad-ok:linear-gradient(135deg,#10b981,#059669);
  --grad-err:linear-gradient(135deg,#ef4444,#dc2626);
  --grad-warn:linear-gradient(135deg,#f59e0b,#d97706);
  --grad-info:linear-gradient(135deg,#3b82f6,#2563eb);
  --grad-purple:linear-gradient(135deg,#8b5cf6,#7c3aed);
  --grad-pink:linear-gradient(135deg,#ec4899,#db2777);
  --grad-teal:linear-gradient(135deg,#14b8a6,#0d9488);
  --r-xs:8px; --r-sm:10px; --r-md:14px; --r-lg:18px; --r-xl:22px; --r-2xl:28px;
  --sh-0:0 1px 2px rgba(15,23,42,.04);
  --sh-1:0 4px 14px rgba(15,23,42,.06);
  --sh-2:0 10px 30px rgba(15,23,42,.08);
  --sh-3:0 20px 50px rgba(102,126,234,.28);
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
  text-rendering:optimizeLegibility;
  overflow-x:hidden;
}
button,input,textarea,select{font-family:inherit;font-feature-settings:'ss01','cv11'}
::selection{background:rgba(102,126,234,.25)}
*::-webkit-scrollbar{width:8px;height:8px}
*::-webkit-scrollbar-track{background:transparent}
*::-webkit-scrollbar-thumb{background:rgba(100,116,139,.25);border-radius:99px}
*::-webkit-scrollbar-thumb:hover{background:rgba(100,116,139,.45)}
:focus-visible{outline:2px solid var(--brand-a);outline-offset:2px;border-radius:6px}
"""


# ============================================================
# HTML — LOGIN
# ============================================================
HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="theme-color" content="#667eea">
<title>Đăng nhập — ALB Forge</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
""" + CSS_ROOT + """
body{
  display:flex;align-items:center;justify-content:center;
  min-height:100vh;min-height:100dvh;
  padding:20px;
  background:
    radial-gradient(1200px 800px at 10% 0%,rgba(240,147,251,.35),transparent 60%),
    radial-gradient(1000px 700px at 90% 100%,rgba(245,87,108,.35),transparent 60%),
    linear-gradient(-45deg,#667eea,#764ba2,#f093fb,#f5576c);
  background-size:200% 200%,200% 200%,400% 400%;
  animation:bgShift 18s ease infinite;
}
@keyframes bgShift{
  0%{background-position:0% 0%,100% 100%,0% 50%}
  50%{background-position:100% 0%,0% 100%,100% 50%}
  100%{background-position:0% 0%,100% 100%,0% 50%}
}
.card{
  background:rgba(255,255,255,.98);
  backdrop-filter:blur(20px) saturate(180%);
  -webkit-backdrop-filter:blur(20px) saturate(180%);
  padding:46px 34px 38px;
  border-radius:var(--r-2xl);
  border:1px solid rgba(255,255,255,.6);
  box-shadow:
    0 40px 100px rgba(15,23,42,.28),
    0 1px 0 rgba(255,255,255,.9) inset,
    0 -1px 0 rgba(15,23,42,.05) inset;
  width:100%;max-width:420px;text-align:center;
  animation:cardIn .9s var(--ease) both;
  position:relative;overflow:hidden;
}
.card::before{
  content:'';position:absolute;inset:0;border-radius:inherit;pointer-events:none;
  background:linear-gradient(135deg,rgba(255,255,255,.6),transparent 40%);
  mix-blend-mode:overlay;
}
@keyframes cardIn{
  from{opacity:0;transform:translateY(60px) scale(.94)}
  to{opacity:1;transform:translateY(0) scale(1)}
}
.logo-box{
  width:124px;height:124px;margin:0 auto 18px;position:relative;
  animation:float 4s ease-in-out infinite;
  filter:drop-shadow(0 20px 40px rgba(102,126,234,.35));
}
.logo-box::before{
  content:'';position:absolute;inset:-14px;border-radius:50%;
  background:radial-gradient(circle,rgba(245,87,108,.45),transparent 70%);
  filter:blur(24px);animation:glowPulse 3.2s ease-in-out infinite;
  z-index:-1;
}
@keyframes float{0%,100%{transform:translateY(0) rotate(0)}50%{transform:translateY(-9px) rotate(-2.5deg)}}
@keyframes glowPulse{0%,100%{opacity:.55;transform:scale(1)}50%{opacity:.95;transform:scale(1.15)}}
.logo-box svg{width:100%;height:100%;position:relative;z-index:1}
h1{
  color:var(--txt-0);
  font-size:26px;font-weight:900;letter-spacing:-.8px;
  background:linear-gradient(135deg,#1a1a2e,#667eea 60%,#764ba2);
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
  margin-bottom:6px;
}
p.sub{color:var(--txt-2);margin-bottom:26px;font-size:12.5px;font-weight:600;letter-spacing:.2px}
.input-wrap{position:relative;margin-bottom:6px}
input[type=password]{
  width:100%;padding:16px 48px 16px 18px;
  border:2px solid var(--line);border-radius:var(--r-md);
  font-size:15px;font-weight:600;background:#f9fafb;color:var(--txt-0);
  letter-spacing:1px;text-align:left;
  transition:border-color .25s var(--ease),background .25s var(--ease),box-shadow .25s var(--ease);
}
input[type=password]::placeholder{color:var(--txt-3);letter-spacing:normal;font-weight:500}
input[type=password]:focus{
  outline:none;border-color:var(--brand-a);background:#fff;
  box-shadow:0 0 0 4px rgba(102,126,234,.14);
}
.pw-toggle{
  position:absolute;right:6px;top:50%;transform:translateY(-50%);
  width:38px;height:38px;border-radius:10px;border:none;background:transparent;
  color:var(--txt-2);cursor:pointer;font-size:16px;
  display:flex;align-items:center;justify-content:center;
  transition:background .2s var(--ease),color .2s var(--ease);
}
.pw-toggle:hover{background:var(--bg-2);color:var(--txt-0)}
button.submit{
  width:100%;padding:16px;margin-top:16px;
  background:var(--grad-brand);color:#fff;border:none;border-radius:var(--r-md);
  font-size:15px;font-weight:800;letter-spacing:.3px;cursor:pointer;
  box-shadow:0 14px 34px rgba(102,126,234,.4);
  transition:transform .3s var(--ease),box-shadow .3s var(--ease);
  position:relative;overflow:hidden;
  display:flex;align-items:center;justify-content:center;gap:8px;
}
button.submit::before{
  content:'';position:absolute;inset:0;
  background:linear-gradient(120deg,transparent 30%,rgba(255,255,255,.5) 50%,transparent 70%);
  transform:translateX(-100%);transition:transform .8s var(--ease);
}
button.submit:hover::before{transform:translateX(100%)}
button.submit:hover{transform:translateY(-2px);box-shadow:0 20px 44px rgba(102,126,234,.5)}
button.submit:active{transform:translateY(0) scale(.99)}
.error{
  background:linear-gradient(135deg,#fef2f2,#fee2e2);color:#b91c1c;
  padding:12px 16px;border-radius:var(--r-md);margin-bottom:16px;
  font-size:12.5px;font-weight:700;
  border-left:4px solid var(--err);
  animation:shake .5s var(--ease);text-align:left;
}
@keyframes shake{
  0%,100%{transform:translateX(0)}
  20%,60%{transform:translateX(-6px)}
  40%,80%{transform:translateX(6px)}
}
.foot{margin-top:22px;font-size:10.5px;color:var(--txt-3);font-weight:600;letter-spacing:.4px}
.foot b{color:var(--brand-a);font-weight:800}
</style>
</head>
<body>
<div class="card">
<div class="logo-box">""" + LOGO_SVG + """</div>
<h1>ALB FORGE</h1>
<p class="sub">Bot by Anh Khôi • v26.1 VIP</p>
{% if error %}<div class="error">⚠️ {{ error }}</div>{% endif %}
<form method="POST" autocomplete="off">
<div class="input-wrap">
<input type="password" name="password" id="pw" placeholder="Nhập mật khẩu..." autofocus required>
<button type="button" class="pw-toggle" onclick="tgPw()" aria-label="Hiện mật khẩu">👁️</button>
</div>
<button type="submit" class="submit">🚀 Đăng nhập</button>
</form>
<div class="foot">Secured by <b>ALB</b> • Anti-Ban VIP v26.1</div>
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
# HTML — INDEX (FULL REWRITE)
# ============================================================
HTML_INDEX = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="theme-color" content="#667eea">
<title>ALB Forge v26.1</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>
""" + CSS_ROOT + """

/* ---------- HEADER ---------- */
.header{
  background:
    radial-gradient(600px 200px at 0% 0%,rgba(240,147,251,.35),transparent 60%),
    radial-gradient(500px 220px at 100% 100%,rgba(245,87,108,.4),transparent 60%),
    linear-gradient(135deg,#667eea 0%,#764ba2 100%);
  color:#fff;padding:14px 18px;
  padding-top:calc(14px + env(safe-area-inset-top,0px));
  box-shadow:0 6px 30px rgba(102,126,234,.35);
  position:sticky;top:0;z-index:100;
  border-bottom:1px solid rgba(255,255,255,.15);
}
.header-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;gap:12px}
.logo-mini{
  width:42px;height:42px;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  background:rgba(255,255,255,.14);border-radius:12px;
  border:1px solid rgba(255,255,255,.28);
  padding:6px;backdrop-filter:blur(10px);
  animation:logoFl 4s ease-in-out infinite;
  box-shadow:0 8px 22px rgba(0,0,0,.18),inset 0 1px 0 rgba(255,255,255,.3);
}
@keyframes logoFl{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
.logo-mini svg{width:100%;height:100%}
.header-info{flex:1;min-width:0}
.header-info h1{font-size:16px;font-weight:900;letter-spacing:-.4px;line-height:1.1}
.header-info p{font-size:10px;opacity:.9;font-weight:600;margin-top:3px;letter-spacing:.4px}
.logout-btn{
  display:inline-flex;align-items:center;gap:6px;
  background:rgba(255,255,255,.14);color:#fff;
  border:1px solid rgba(255,255,255,.28);
  padding:8px 12px;border-radius:11px;
  font-size:11.5px;font-weight:800;cursor:pointer;
  transition:background .25s var(--ease),transform .25s var(--ease);
  backdrop-filter:blur(10px);
}
.logout-btn:hover{background:rgba(255,255,255,.26);transform:translateY(-1px)}
.logout-btn:active{transform:translateY(0) scale(.97)}

/* ---------- CONTAINER / TABS ---------- */
.container{max-width:1200px;margin:0 auto;padding:14px}
.tabs{
  display:grid;grid-template-columns:repeat(4,1fr);gap:6px;
  margin-bottom:14px;padding:6px;
  background:rgba(255,255,255,.9);
  backdrop-filter:blur(14px);
  border-radius:var(--r-lg);
  box-shadow:0 6px 26px rgba(15,23,42,.06),0 1px 0 rgba(255,255,255,.9) inset;
  border:1px solid var(--line-2);
}
.tab{
  position:relative;padding:11px 4px;border-radius:12px;cursor:pointer;
  font-size:10px;font-weight:800;letter-spacing:.3px;
  text-align:center;color:var(--txt-2);
  display:flex;flex-direction:column;align-items:center;gap:4px;
  user-select:none;background:transparent;border:none;
  transition:color .3s var(--ease),transform .3s var(--ease);
  isolation:isolate;
}
.tab::before{
  content:'';position:absolute;inset:0;border-radius:inherit;
  background:var(--grad-brand);opacity:0;transform:scale(.92);
  transition:opacity .3s var(--ease),transform .3s var(--ease);
  z-index:-1;box-shadow:0 10px 24px rgba(102,126,234,.42);
}
.tab.active{color:#fff;transform:translateY(-2px)}
.tab.active::before{opacity:1;transform:scale(1)}
.tab .tab-icon{font-size:18px;line-height:1;transition:transform .3s var(--ease-2)}
.tab:hover .tab-icon{transform:scale(1.18) rotate(-4deg)}
.tab.active .tab-icon{transform:scale(1.1)}

.panel{display:none;animation:fadeUp .35s var(--ease)}
.panel.active{display:block}
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}

/* ---------- CARD ---------- */
.card{
  position:relative;
  background:linear-gradient(180deg,#fff 0%,#fcfcfe 100%);
  padding:18px;border-radius:var(--r-xl);
  box-shadow:
    0 1px 0 rgba(255,255,255,.9) inset,
    0 -1px 0 rgba(15,23,42,.03) inset,
    0 8px 30px rgba(15,23,42,.06);
  margin-bottom:14px;
  border:1px solid var(--line-2);
  transition:box-shadow .35s var(--ease);
}
.card:hover{box-shadow:0 12px 40px rgba(15,23,42,.08),0 1px 0 rgba(255,255,255,.9) inset}
.card h2{
  font-size:13.5px;font-weight:900;letter-spacing:-.3px;
  margin-bottom:14px;display:flex;align-items:center;gap:9px;
}
.card h2 .bi{
  width:30px;height:30px;border-radius:10px;
  background:var(--grad-brand);
  display:flex;align-items:center;justify-content:center;
  font-size:13px;color:#fff;
  box-shadow:0 6px 16px rgba(102,126,234,.35),inset 0 1px 0 rgba(255,255,255,.4);
}

/* ---------- FORM ---------- */
.form-group{margin-bottom:13px}
.form-group label{
  display:block;margin-bottom:6px;
  font-size:10.5px;font-weight:800;color:#374151;
  text-transform:uppercase;letter-spacing:.6px;
}
.form-group input,
.form-group textarea,
.form-group select{
  width:100%;padding:12px 14px;
  border:2px solid var(--line);border-radius:12px;
  font-size:13px;font-weight:500;
  background:#f9fafb;color:var(--txt-0);
  transition:border-color .25s var(--ease),background .25s var(--ease),box-shadow .25s var(--ease);
}
.form-group input:focus,
.form-group textarea:focus,
.form-group select:focus{
  outline:none;border-color:var(--brand-a);background:#fff;
  box-shadow:0 0 0 4px rgba(102,126,234,.12);
}
.form-group textarea{
  min-height:96px;resize:vertical;
  font-family:'JetBrains Mono',ui-monospace,monospace;
  font-size:12px;line-height:1.55;
}
.form-group select{
  appearance:none;-webkit-appearance:none;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat:no-repeat;background-position:right 14px center;
  padding-right:38px;cursor:pointer;
}

/* ---------- BUTTONS ---------- */
.btn-circle{
  width:52px;height:52px;border-radius:50%;border:none;cursor:pointer;
  display:inline-flex;align-items:center;justify-content:center;
  font-size:20px;color:#fff;
  transition:transform .3s var(--ease-2),box-shadow .3s var(--ease),filter .3s var(--ease);
  box-shadow:0 10px 24px rgba(15,23,42,.16),inset 0 1px 0 rgba(255,255,255,.35);
  position:relative;overflow:hidden;margin:3px;
  isolation:isolate;
}
.btn-circle::before{
  content:'';position:absolute;inset:0;border-radius:inherit;
  background:linear-gradient(120deg,transparent 30%,rgba(255,255,255,.5) 50%,transparent 70%);
  transform:translateX(-120%);
  transition:transform .7s var(--ease);
}
.btn-circle:hover{transform:translateY(-4px) scale(1.06);filter:brightness(1.06)}
.btn-circle:hover::before{transform:translateX(120%)}
.btn-circle:active{transform:translateY(-1px) scale(.98)}
.btn-circle:disabled{opacity:.5;cursor:not-allowed;filter:grayscale(.4)}
.btn-circle.primary{background:var(--grad-brand);box-shadow:0 12px 28px rgba(102,126,234,.45),inset 0 1px 0 rgba(255,255,255,.35)}
.btn-circle.danger{background:var(--grad-err);box-shadow:0 12px 28px rgba(239,68,68,.42),inset 0 1px 0 rgba(255,255,255,.35)}
.btn-circle.success{background:var(--grad-ok);box-shadow:0 12px 28px rgba(16,185,129,.42),inset 0 1px 0 rgba(255,255,255,.35)}
.btn-circle.warning{background:var(--grad-warn);box-shadow:0 12px 28px rgba(245,158,11,.42),inset 0 1px 0 rgba(255,255,255,.35)}
.btn-circle.info{background:var(--grad-info);box-shadow:0 12px 28px rgba(59,130,246,.42),inset 0 1px 0 rgba(255,255,255,.35)}
.btn-circle.purple{background:var(--grad-purple);box-shadow:0 12px 28px rgba(139,92,246,.42),inset 0 1px 0 rgba(255,255,255,.35)}
.btn-circle.pink{background:var(--grad-pink);box-shadow:0 12px 28px rgba(236,72,153,.42),inset 0 1px 0 rgba(255,255,255,.35)}
.btn-circle.teal{background:var(--grad-teal);box-shadow:0 12px 28px rgba(20,184,166,.42),inset 0 1px 0 rgba(255,255,255,.35)}
.btn-circle.small{width:38px;height:38px;font-size:15px}
.btn-circle.big{width:72px;height:72px;font-size:26px}

.btn-rect{
  padding:11px 18px;border:none;border-radius:12px;cursor:pointer;
  font-size:12px;font-weight:800;letter-spacing:.2px;color:#fff;
  display:inline-flex;align-items:center;gap:7px;
  box-shadow:0 10px 22px rgba(15,23,42,.16),inset 0 1px 0 rgba(255,255,255,.3);
  transition:transform .3s var(--ease-2),box-shadow .3s var(--ease),filter .3s var(--ease);
}
.btn-rect:hover{transform:translateY(-3px);filter:brightness(1.06)}
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
  background:linear-gradient(180deg,#f9fafb,#f3f4f6);
  padding:13px 12px;border-radius:var(--r-md);
  border:1px solid var(--line);
  box-shadow:0 1px 0 rgba(255,255,255,.9) inset;
}
.stat::before{
  content:'';position:absolute;top:0;left:0;right:0;height:3px;
  background:var(--grad-brand);
}
.stat::after{
  content:'';position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(120deg,transparent 40%,rgba(255,255,255,.6) 50%,transparent 60%);
  transform:translateX(-100%);
  animation:statShimmer 3.5s ease-in-out infinite;
}
@keyframes statShimmer{0%,60%{transform:translateX(-100%)}80%,100%{transform:translateX(100%)}}
.stat .label{font-size:9px;color:var(--txt-2);margin-bottom:6px;text-transform:uppercase;letter-spacing:.6px;font-weight:800}
.stat .value{font-size:22px;font-weight:900;color:var(--txt-0);line-height:1;font-variant-numeric:tabular-nums}

/* ---------- TABLE ---------- */
.table-wrap{
  overflow-x:auto;border-radius:var(--r-md);
  border:1px solid var(--line-2);background:#fff;
}
.table{width:100%;border-collapse:collapse}
.table th,.table td{
  padding:10px 8px;text-align:left;font-size:11px;
  border-bottom:1px solid var(--line-2);white-space:nowrap;
}
.table th{
  background:#f8fafc;font-weight:800;color:var(--txt-2);
  text-transform:uppercase;font-size:9px;letter-spacing:.6px;
  position:sticky;top:0;z-index:1;
}
.table tbody tr{transition:background .2s var(--ease)}
.table tbody tr:hover{background:#f8fafc}
.table tbody tr:last-child td{border-bottom:none}
.table td code{
  background:#f3f4f6;padding:2px 7px;border-radius:6px;
  font-size:10px;font-family:'JetBrains Mono',ui-monospace,monospace;
  color:#475569;font-weight:600;
}

/* ---------- BADGE ---------- */
.badge{
  display:inline-flex;align-items:center;gap:4px;
  padding:3px 8px;border-radius:20px;
  font-size:9.5px;font-weight:800;letter-spacing:.2px;
}
.badge::before{content:'';width:5px;height:5px;border-radius:50%;background:currentColor;opacity:.7}
.badge-ok{background:#d1fae5;color:#065f46}
.badge-err{background:#fee2e2;color:#991b1b}
.badge-warn{background:#fef3c7;color:#92400e}
.badge-info{background:#dbeafe;color:#1e40af}
.badge-frz{background:linear-gradient(135deg,#dbeafe,#bfdbfe);color:#1e40af}

/* ---------- BOX LIST ---------- */
.box-list{
  max-height:340px;overflow-y:auto;
  border:2px solid var(--line);border-radius:var(--r-md);
  padding:8px;background:#f9fafb;
  box-shadow:inset 0 1px 3px rgba(15,23,42,.04);
}
.box-item{
  padding:11px;border-radius:11px;background:#fff;
  margin-bottom:6px;cursor:pointer;
  border:2px solid transparent;
  display:flex;align-items:center;gap:10px;font-size:12px;
  box-shadow:0 1px 3px rgba(15,23,42,.05);
  transition:border-color .25s var(--ease),transform .25s var(--ease),box-shadow .25s var(--ease);
}
.box-item:hover{border-color:var(--brand-a);transform:translateX(2px);box-shadow:0 6px 18px rgba(102,126,234,.14)}
.box-item.selected{
  border-color:var(--ok);background:linear-gradient(180deg,#ecfdf5,#d1fae5);
  box-shadow:0 6px 18px rgba(16,185,129,.2);
}
.box-item .check{
  width:19px;height:19px;border:2px solid #d1d5db;border-radius:6px;
  display:flex;align-items:center;justify-content:center;
  font-size:10px;color:transparent;font-weight:900;flex-shrink:0;
  transition:background .25s var(--ease),border-color .25s var(--ease),color .25s var(--ease),transform .25s var(--ease-2);
}
.box-item.selected .check{
  background:var(--ok);border-color:var(--ok);color:#fff;transform:scale(1.05);
}
.box-item .info{flex:1;min-width:0}
.box-item .name{font-weight:700;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.box-item .meta{font-size:10px;color:var(--txt-2);font-family:'JetBrains Mono',monospace;margin-top:2px}

/* ---------- FILE ---------- */
.file-item{
  display:flex;align-items:center;gap:10px;
  padding:11px;border-radius:12px;
  background:#fff;margin-bottom:8px;
  border:1px solid var(--line);
  box-shadow:0 1px 3px rgba(15,23,42,.05);
  transition:border-color .25s var(--ease),transform .25s var(--ease),box-shadow .25s var(--ease);
}
.file-item:hover{border-color:var(--brand-a);transform:translateY(-2px);box-shadow:0 10px 24px rgba(102,126,234,.12)}
.file-item .info{flex:1;min-width:0}
.file-item .name{font-weight:700;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.file-item .meta{font-size:10px;color:var(--txt-2);margin-top:2px}

/* ---------- CHIP ---------- */
.chip-group{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px}
.chip{
  position:relative;
  padding:8px 14px;background:#f3f4f6;color:#374151;
  border-radius:20px;font-size:11px;font-weight:800;letter-spacing:.2px;
  cursor:pointer;user-select:none;
  border:2px solid transparent;
  transition:background .25s var(--ease),color .25s var(--ease),transform .25s var(--ease-2),box-shadow .25s var(--ease);
}
.chip:hover{background:#e5e7eb;transform:translateY(-1px)}
.chip.active{
  background:var(--grad-brand);color:#fff;
  box-shadow:0 8px 22px rgba(102,126,234,.45),inset 0 1px 0 rgba(255,255,255,.35);
  transform:translateY(-2px);
}
.chip.freeze.active{
  background:linear-gradient(135deg,#3b82f6,#1d4ed8);
  box-shadow:0 8px 22px rgba(59,130,246,.5),inset 0 1px 0 rgba(255,255,255,.35);
}

/* ---------- TOGGLE ---------- */
.toggle-group{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}
.toggle{
  position:relative;padding:12px 10px;
  border:2px solid var(--line);border-radius:var(--r-md);
  cursor:pointer;text-align:center;
  font-weight:800;font-size:11px;letter-spacing:.2px;
  background:#f9fafb;color:var(--txt-2);
  user-select:none;isolation:isolate;
  transition:color .3s var(--ease),transform .3s var(--ease-2),box-shadow .3s var(--ease);
}
.toggle::before{
  content:'';position:absolute;inset:-2px;border-radius:inherit;
  background:var(--grad-brand);opacity:0;transform:scale(.94);
  transition:opacity .3s var(--ease),transform .3s var(--ease);
  z-index:-1;box-shadow:0 10px 24px rgba(102,126,234,.4);
}
.toggle.active{color:#fff;border-color:transparent;transform:translateY(-2px)}
.toggle.active::before{opacity:1;transform:scale(1)}

/* ---------- TAG SELECTOR ---------- */
.tag-selector{
  max-height:240px;overflow-y:auto;
  border:2px solid var(--line);border-radius:12px;
  padding:8px;background:#f9fafb;display:none;margin-top:8px;
}
.tag-selector.show{display:block}
.tag-member{
  padding:8px;border-radius:8px;background:#fff;margin-bottom:4px;cursor:pointer;
  border:2px solid transparent;font-size:12px;
  display:flex;align-items:center;gap:8px;
  transition:border-color .2s var(--ease),background .2s var(--ease);
}
.tag-member:hover{border-color:var(--purple)}
.tag-member.selected{border-color:var(--purple);background:#f3e8ff}
.tag-member .check{
  width:16px;height:16px;border:2px solid #d1d5db;border-radius:4px;
  display:flex;align-items:center;justify-content:center;
  font-size:9px;color:transparent;font-weight:900;flex-shrink:0;
  transition:background .2s var(--ease),border-color .2s var(--ease),color .2s var(--ease);
}
.tag-member.selected .check{background:var(--purple);border-color:var(--purple);color:#fff}

/* ---------- NOTIFICATION STACK ---------- */
#toast-stack{
  position:fixed;top:calc(20px + env(safe-area-inset-top,0px));right:16px;
  z-index:9999;display:flex;flex-direction:column;gap:10px;
  max-width:380px;width:calc(100% - 32px);pointer-events:none;
}
.toast{
  pointer-events:auto;
  position:relative;overflow:hidden;
  padding:14px 16px 14px 58px;
  border-radius:16px;
  background:rgba(255,255,255,.98);
  backdrop-filter:blur(16px) saturate(180%);
  -webkit-backdrop-filter:blur(16px) saturate(180%);
  box-shadow:
    0 20px 50px rgba(15,23,42,.22),
    0 1px 0 rgba(255,255,255,.9) inset,
    0 -1px 0 rgba(15,23,42,.04) inset;
  border:1px solid rgba(255,255,255,.6);
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
  font-size:16px;color:#fff;
  box-shadow:0 6px 16px rgba(15,23,42,.2),inset 0 1px 0 rgba(255,255,255,.4);
}
.toast.success .t-icon{background:var(--grad-ok)}
.toast.error .t-icon{background:var(--grad-err)}
.toast.warning .t-icon{background:var(--grad-warn)}
.toast.info .t-icon{background:var(--grad-info)}
.toast .t-title{font-size:12.5px;font-weight:900;color:var(--txt-0);letter-spacing:-.2px}
.toast .t-msg{font-size:11.5px;font-weight:600;color:var(--txt-2);line-height:1.45}
.toast .t-progress{
  position:absolute;left:0;right:0;bottom:0;height:2px;
  background:rgba(15,23,42,.06);
  overflow:hidden;
}
.toast .t-progress::after{
  content:'';display:block;height:100%;width:100%;
  background:currentColor;opacity:.4;
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
  transition:background .2s var(--ease),color .2s var(--ease);
}
.toast .t-close:hover{background:var(--bg-2);color:var(--txt-0)}

/* ---------- FREEZE PANEL ---------- */
.freeze-panel{
  margin-top:12px;padding:14px;
  border-radius:var(--r-md);
  background:linear-gradient(135deg,#eff6ff,#dbeafe);
  border:1px solid #bfdbfe;
  display:none;
}
.freeze-panel.show{display:block;animation:fadeUp .35s var(--ease)}
.freeze-panel .fp-title{
  font-size:11px;font-weight:900;color:#1e40af;
  text-transform:uppercase;letter-spacing:.6px;
  display:flex;align-items:center;gap:6px;margin-bottom:8px;
}
.freeze-panel .fp-desc{
  font-size:10.5px;color:#1e3a8a;font-weight:600;line-height:1.55;
  margin-bottom:10px;
}
.freeze-panel input[type=number]{
  width:100%;padding:9px 12px;border:2px solid #bfdbfe;border-radius:10px;
  background:#fff;font-size:12px;font-weight:700;color:#1e3a8a;
  transition:border-color .2s var(--ease),box-shadow .2s var(--ease);
}
.freeze-panel input[type=number]:focus{
  outline:none;border-color:var(--info);
  box-shadow:0 0 0 4px rgba(59,130,246,.15);
}

/* ---------- ANTI-BAN INFO ---------- */
.anti-ban-card{
  background:linear-gradient(135deg,#fef3c7,#fde68a);
  border:2px solid #fbbf24;
}
.anti-ban-card h2{color:#92400e}
.anti-ban-card h2 .bi{background:#92400e;box-shadow:none}
.anti-ban-list{
  color:#78350f;font-size:11px;line-height:1.95;font-weight:600;
}
.anti-ban-list div{display:flex;align-items:flex-start;gap:6px}
.anti-ban-list .dot{flex-shrink:0;margin-top:3px}

/* ---------- RESPONSIVE ---------- */
@media (max-width:640px){
  .container{padding:10px}
  .card{padding:14px;border-radius:var(--r-lg)}
  .header{padding:10px 12px;padding-top:calc(10px + env(safe-area-inset-top,0px))}
  .header-info h1{font-size:14px}
  .header-info p{font-size:9px}
  .logo-mini{width:36px;height:36px}
  .logout-btn{padding:7px 10px;font-size:10.5px}
  .logout-btn span{display:none}
  .tab{padding:9px 3px;font-size:9px}
  .tab .tab-icon{font-size:16px}
  .stat .value{font-size:18px}
  .btn-circle{width:46px;height:46px;font-size:18px}
  .btn-circle.small{width:34px;height:34px;font-size:13px}
  .btn-circle.big{width:62px;height:62px;font-size:22px}
  #toast-stack{left:12px;right:12px;max-width:none;width:auto}
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
      <p>Bot by Anh Khôi • v26.1 VIP</p>
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

<!-- ============ ACCOUNTS ============ -->
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
          <th>ID</th><th>Tên</th><th>OK/Lỗi</th><th>Risk</th><th>Sent</th><th></th>
        </tr></thead>
        <tbody id="accounts-tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ============ BOXES ============ -->
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
        <b>Đã chọn: <span id="selected-count" style="color:#667eea;">0</span></b>
      </div>
      <div class="box-list" id="box-list">
        <div style="text-align:center;padding:20px;color:#999;font-size:11px;">Chưa load</div>
      </div>
    </div>
  </div>
</div>

<!-- ============ FILES ============ -->
<div class="panel" id="panel-files">
  <div class="card">
    <h2><span class="bi">📤</span> Upload file</h2>
    <div class="form-group"><input type="file" id="file-input" accept=".txt" style="padding:6px;"></div>
    <button type="button" class="btn-rect primary full" onclick="uploadFile()">📤 Upload</button>
    <div style="margin-top:10px;font-size:11px;color:#6b7280;line-height:1.6;">
      💡 Mỗi khối ngăn bởi <b>dòng trống</b> = 1 tin nhắn (giữ nguyên multiline)
    </div>
  </div>
  <div class="card">
    <h2><span class="bi">📁</span> File đã upload</h2>
    <div id="files-list"><div style="text-align:center;padding:20px;color:#999;font-size:11px;">Chưa có</div></div>
  </div>
</div>

<!-- ============ SPAM ============ -->
<div class="panel" id="panel-spam">
  <div class="card">
    <h2><span class="bi">🎯</span> Cấu hình spam</h2>

    <div class="form-group">
      <label>Chọn file tin nhắn</label>
      <select id="spam-file-select"><option value="">-- Chọn file --</option></select>
    </div>

    <div class="form-group">
      <label>Hoặc nhập tin (mỗi khối cách nhau dấu ;)</label>
      <textarea id="spam-messages" placeholder="Tin 1 dòng 1&#10;Tin 1 dòng 2;Tin 2"></textarea>
    </div>

    <div class="form-group">
      <label>⏱ Delay (giây)</label>
      <div class="chip-group" id="delay-chips">
        <div class="chip" data-delay="0.3">0.3s</div>
        <div class="chip" data-delay="0.5">0.5s</div>
        <div class="chip" data-delay="1">1s</div>
        <div class="chip active" data-delay="2">2s</div>
        <div class="chip" data-delay="3">3s</div>
        <div class="chip" data-delay="5">5s</div>
        <div class="chip" data-delay="10">10s</div>
        <div class="chip" data-delay="30">30s</div>
      </div>
      <input type="hidden" id="spam-delay" value="2">
    </div>

    <div class="form-group">
      <label>😈 Số icon cuối câu</label>
      <div class="chip-group" id="icon-chips">
        <div class="chip" data-icon="0">0</div>
        <div class="chip" data-icon="2">2</div>
        <div class="chip active" data-icon="5">5</div>
        <div class="chip" data-icon="10">10</div>
        <div class="chip" data-icon="15">15</div>
        <div class="chip" data-icon="20">20</div>
      </div>
      <input type="hidden" id="icon-count" value="5">
    </div>

    <div class="toggle-group">
      <div class="toggle active" id="tg-color" onclick="tgFlag('color')">🎨 Đổi màu</div>
      <div class="toggle active" id="tg-emoji" onclick="tgFlag('emoji')">😈 Thêm icon</div>
    </div>

    <div class="form-group">
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
        <input type="checkbox" id="tg-tag" onchange="tgTag()" style="width:auto;">
        Tag UID trong tin nhắn
      </label>
      <div id="tag-wrap" style="display:none;margin-top:8px;">
        <div class="form-group">
          <select id="member-acc-select"><option value="">-- Chọn acc để load members --</option></select>
        </div>
        <button type="button" class="btn-rect info" onclick="loadMembers()">🔄 Load members</button>
        <div class="tag-selector" id="tag-selector"></div>
        <input type="hidden" id="tag-selected" value="">
      </div>
    </div>
  </div>

  <div class="card">
    <h2><span class="bi">❄️</span> Chế độ treo nâng cao</h2>

    <div class="toggle-group" style="grid-template-columns:1fr 1fr;">
      <div class="toggle" id="tg-freeze-text" onclick="tgFlag('freeze_text')">
        🧊 TREO NGÔN
      </div>
      <div class="toggle" id="tg-freeze-delay" onclick="tgFlag('freeze_delay')">
        🌀 TREO NHÂY
      </div>
    </div>

    <div class="freeze-panel" id="fp-text">
      <div class="fp-title">🧊 TREO NGÔN — Freeze Text Mode</div>
      <div class="fp-desc">
        Sau <b>N</b> tin đầu (xoay vòng bình thường), bot <b>khoá cứng 1 tin duy nhất</b>
        và lặp mãi mãi cho tới khi dừng.<br>
        👉 Dùng khi muốn spam 1 câu cố định với tần suất cao, không đổi nội dung.
      </div>
      <label style="font-size:10.5px;font-weight:800;color:#1e40af;letter-spacing:.5px;text-transform:uppercase;">
        Khoá sau bao nhiêu tin?
      </label>
      <input type="number" id="freeze-text-after" value="10" min="0" max="10000" style="margin-top:6px;">
    </div>

    <div class="freeze-panel" id="fp-delay">
      <div class="fp-title">🌀 TREO NHÂY — Freeze Delay Mode</div>
      <div class="fp-desc">
        Sau <b>N</b> tin đầu (delay có jitter ngẫu nhiên), bot <b>khoá cứng 1 giá trị delay duy nhất</b>
        và dùng nó lặp mãi mãi — không jitter, không dao động.<br>
        👉 Dùng khi muốn nhịp gửi đều tăm tắp, chính xác đến từng ms.
      </div>
      <label style="font-size:10.5px;font-weight:800;color:#1e40af;letter-spacing:.5px;text-transform:uppercase;">
        Khoá delay sau bao nhiêu tin?
      </label>
      <input type="number" id="freeze-delay-after" value="10" min="0" max="10000" style="margin-top:6px;">
    </div>

    <div style="margin-top:12px;font-size:10.5px;color:var(--txt-2);line-height:1.6;padding:10px;background:#f8fafc;border-radius:10px;border-left:3px solid var(--info);">
      💡 <b>2 mode độc lập</b> — bật cùng lúc được. Ví dụ: 10 tin đầu đa dạng → treo cứng 1 câu + nhịp 3s đều.
    </div>
  </div>

  <div style="text-align:center;margin-bottom:14px;">
    <button type="button" class="btn-circle success big" onclick="startSpam()" title="Bắt đầu">▶️</button>
    <button type="button" class="btn-circle danger big" onclick="stopAll()" title="Dừng">⏸️</button>
  </div>

  <div class="card anti-ban-card">
    <h2><span class="bi">🛡️</span> Anti-Ban VIP v26.1</h2>
    <div class="anti-ban-list">
      <div><span class="dot">✅</span><span>Delay min 0.3s — gửi siêu nhanh</span></div>
      <div><span class="dot">✅</span><span>Acc + Target rotation thông minh</span></div>
      <div><span class="dot">✅</span><span>12 màu Zalo ngẫu nhiên</span></div>
      <div><span class="dot">✅</span><span>Icon sát thương Zalo</span></div>
      <div><span class="dot">✅</span><span>Risk adaptive delay</span></div>
      <div><span class="dot">✅</span><span>Fail 50 lần → auto disable</span></div>
      <div><span class="dot">✅</span><span>Giữ nguyên 100% text user</span></div>
      <div><span class="dot">❄️</span><span>2 chế độ treo: ngôn + nhây</span></div>
    </div>
  </div>

  <div class="card">
    <h2><span class="bi">📋</span> Tác vụ</h2>
    <button type="button" class="btn-circle danger small" onclick="stopAll()" title="Dừng hết">⏸️</button>
    <div class="table-wrap" style="margin-top:10px;">
      <table class="table"><thead><tr>
        <th>ID</th><th>Trạng thái</th><th>Bắt đầu</th><th></th>
      </tr></thead><tbody id="tasks-tbody"></tbody></table>
    </div>
  </div>
</div>

</div>

<script>
/* ============================================================
   STATE
============================================================ */
var flags = { color: true, emoji: true, freeze_text: false, freeze_delay: false };
var selectedBoxes = [];
var selectedTags = [];
var _boxes = [];
var _members = [];


/* ============================================================
   TOAST NOTIFICATION SYSTEM
============================================================ */
var Toast = (function(){
  var stack = null;
  function ensure(){ if(!stack) stack = document.getElementById('toast-stack'); return stack; }

  var ICONS = { success:'✓', error:'✕', warning:'!', info:'i' };
  var TITLES = { success:'Thành công', error:'Lỗi', warning:'Cảnh báo', info:'Thông tin' };

  function show(msg, type, title, duration){
    type = type || 'success';
    duration = duration || 3500;
    var s = ensure();
    if(!s) return;

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
    success: function(m,t,d){ return show(m,'success',t,d); },
    error:   function(m,t,d){ return show(m,'error',t,d); },
    warning: function(m,t,d){ return show(m,'warning',t,d); },
    info:    function(m,t,d){ return show(m,'info',t,d); },
    show: show
  };
})();

/* legacy alias */
function showAlert(msg, type){
  type = (type === 'error') ? 'error' : (type === 'warning' ? 'warning' : 'success');
  Toast.show(msg, type);
}


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
   CHIP SELECTORS
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


/* ============================================================
   TOGGLES
============================================================ */
function tgFlag(name){
  flags[name] = !flags[name];
  var el = document.getElementById('tg-' + name.replace('_','-'));
  if(el) el.classList.toggle('active', flags[name]);

  if(name === 'freeze_text'){
    var p = document.getElementById('fp-text');
    if(p) p.classList.toggle('show', flags.freeze_text);
  }
  if(name === 'freeze_delay'){
    var p2 = document.getElementById('fp-delay');
    if(p2) p2.classList.toggle('show', flags.freeze_delay);
  }
}

function tgTag(){
  var c = document.getElementById('tg-tag');
  var wrap = document.getElementById('tag-wrap');
  if(wrap) wrap.style.display = c.checked ? 'block' : 'none';
}


/* ============================================================
   API HELPER (with timeout + error handling)
============================================================ */
async function api(url, opts){
  opts = opts || {};
  var ctrl = new AbortController();
  var to = setTimeout(function(){ ctrl.abort(); }, 60000);
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
    tb.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#999;padding:20px;">Chưa có</td></tr>';
  } else {
    tb.innerHTML = accs.map(function(a){
      var risk = (a.risk || 0).toFixed(2);
      var rc = risk > 0.5 ? 'badge-err' : risk > 0.2 ? 'badge-warn' : 'badge-ok';
      return '<tr>' +
        '<td>' + a.id + '</td>' +
        '<td><b>' + a.label + '</b></td>' +
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
  document.getElementById('stat-active').textContent = accs.filter(function(a){ return a.enabled; }).length;
  document.getElementById('stat-sent').textContent = accs.reduce(function(s,a){ return s + (a.total_sent || 0); }, 0);

  var s1 = document.getElementById('load-acc-select');
  var s2 = document.getElementById('member-acc-select');
  var opts = '<option value="">-- Chọn --</option>' +
    accs.map(function(a){ return '<option value="' + a.id + '">' + a.label + '</option>'; }).join('');
  var v1 = s1.value, v2 = s2.value;
  s1.innerHTML = opts; s1.value = v1;
  s2.innerHTML = opts; s2.value = v2;
}

async function addAccount(){
  var label = document.getElementById('add-label').value.trim();
  var imei = document.getElementById('add-imei').value.trim();
  var cookies = document.getElementById('add-cookies').value.trim();
  if(!imei || !cookies){ return Toast.error('Điền IMEI và cookie'); }
  var r = await api('/api/accounts/add', {
    method: 'POST',
    body: JSON.stringify({ label: label, imei: imei, cookies: cookies })
  });
  if(r.error){ return Toast.error(r.error); }
  Toast.success('Đã thêm tài khoản <b>' + r.label + '</b>');
  document.getElementById('add-label').value = '';
  document.getElementById('add-imei').value = '';
  document.getElementById('add-cookies').value = '';
  refreshAll();
}

async function delAcc(id){
  if(!confirm('Xóa tài khoản #' + id + '?')) return;
  await api('/api/accounts/' + id, { method: 'DELETE' });
  Toast.success('Đã xóa #' + id);
  refreshAll();
}

async function resetAcc(id){
  await api('/api/accounts/' + id + '/reset', { method: 'POST' });
  Toast.info('Đã reset risk #' + id);
  refreshAll();
}

async function checkAcc(id){
  var t = Toast.info('Đang check cookie #' + id + '...', 'Kiểm tra', 20000);
  var r = await api('/api/accounts/' + id + '/check', { method: 'POST' });
  if(r.error){ return Toast.error(r.error, 'Check thất bại'); }
  Toast.success('Cookie sống • UID: <code>' + r.uid + '</code>', 'Check OK');
}


/* ============================================================
   BOXES
============================================================ */
async function loadBoxes(){
  var aid = document.getElementById('load-acc-select').value;
  if(!aid) return Toast.error('Chọn tài khoản trước');
  Toast.info('Đang load box...', 'Vui lòng đợi', 60000);
  var r = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
  if(r.error) return Toast.error(r.error, 'Load thất bại');

  var all = (r.groups || []).concat(r.friends || []);
  var bl = document.getElementById('box-list');
  if(!all.length){
    bl.innerHTML = '<div style="text-align:center;padding:20px;color:#999;">Không có box nào</div>';
    return;
  }
  bl.innerHTML = all.map(function(b, i){
    return '<div class="box-item" data-idx="' + i + '" onclick="tgBox(this, ' + i + ')">' +
      '<div class="check">✓</div>' +
      '<div class="info">' +
        '<div class="name">' + b.name + '</div>' +
        '<div class="meta">' + b.id + ' | ' + b.type + '</div>' +
      '</div>' +
    '</div>';
  }).join('');
  _boxes = all;
  selectedBoxes = [];
  document.getElementById('selected-count').textContent = '0';
  Toast.success('Đã load <b>' + all.length + '</b> box', 'Load OK');
}

function tgBox(el, idx){
  var b = _boxes[idx];
  if(!b) return;
  if(el.classList.contains('selected')){
    el.classList.remove('selected');
    selectedBoxes = selectedBoxes.filter(function(x){ return x.id !== b.id; });
  } else {
    el.classList.add('selected');
    selectedBoxes.push(b);
  }
  document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function selectAllBoxes(){
  document.querySelectorAll('.box-item').forEach(function(el){ el.classList.add('selected'); });
  selectedBoxes = _boxes.slice();
  document.getElementById('selected-count').textContent = selectedBoxes.length;
  Toast.info('Đã chọn ' + selectedBoxes.length + ' box');
}

function clearAllBoxes(){
  document.querySelectorAll('.box-item').forEach(function(el){ el.classList.remove('selected'); });
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
    var r = await fetch('/api/files/upload', { method: 'POST', body: fd }).then(function(x){ return x.json(); });
    if(r.error) return Toast.error(r.error);
    Toast.success('Đã upload <b>' + r.filename + '</b><br>' + r.lines + ' khối tin nhắn', 'Upload OK');
    input.value = '';
    loadFiles();
  } catch(e){
    Toast.error('Upload lỗi: ' + e.message);
  }
}

async function loadFiles(){
  var files = await api('/api/files');
  if(!Array.isArray(files)) files = [];
  var list = document.getElementById('files-list');
  if(!files.length){
    list.innerHTML = '<div style="text-align:center;padding:20px;color:#999;font-size:11px;">Chưa có</div>';
  } else {
    list.innerHTML = files.map(function(f){
      var kb = (f.size / 1024).toFixed(1);
      return '<div class="file-item">' +
        '<div class="info">' +
          '<div class="name">📄 ' + f.filename + '</div>' +
          '<div class="meta">' + f.lines + ' khối • ' + kb + ' KB</div>' +
        '</div>' +
        '<button type="button" class="btn-circle info small" onclick="previewFile(' + f.id + ')" title="Xem">👁️</button>' +
        '<button type="button" class="btn-circle danger small" onclick="delFile(' + f.id + ')" title="Xoá">🗑️</button>' +
      '</div>';
    }).join('');
  }
  var s = document.getElementById('spam-file-select');
  var cur = s.value;
  s.innerHTML = '<option value="">-- Chọn file --</option>' +
    files.map(function(f){ return '<option value="' + f.id + '">' + f.filename + ' (' + f.lines + ')</option>'; }).join('');
  s.value = cur;
}

async function previewFile(fid){
  var r = await api('/api/files/' + fid + '/preview');
  if(r.error) return Toast.error(r.error);
  var pv = (r.preview || []).map(function(m, i){ return '--- Khối ' + (i+1) + ' ---\\n' + m; }).join('\\n\\n');
  alert('File: ' + r.filename + '\\nTổng: ' + r.total + ' khối\\n\\n' + pv);
}

async function delFile(fid){
  if(!confirm('Xóa file?')) return;
  await api('/api/files/' + fid, { method: 'DELETE' });
  Toast.success('Đã xóa file');
  loadFiles();
}


/* ============================================================
   TAG MEMBERS
============================================================ */
async function loadMembers(){
  var aid = document.getElementById('member-acc-select').value;
  if(!aid) return Toast.error('Chọn acc để load members');
  var box = selectedBoxes.find(function(b){ return b.type === 'group'; });
  if(!box) return Toast.error('Cần chọn 1 NHÓM trong tab Box trước');

  Toast.info('Đang load members...', 'Vui lòng đợi', 60000);
  var r = await api('/api/accounts/' + aid + '/members/' + box.id, { method: 'POST' });
  if(r.error) return Toast.error(r.error);

  var mem = r.members || [];
  var sel = document.getElementById('tag-selector');
  sel.classList.add('show');
  if(!mem.length){
    sel.innerHTML = '<div style="padding:14px;text-align:center;color:#999;font-size:11px;">Không có members</div>';
    return;
  }
  sel.innerHTML = mem.map(function(m, i){
    return '<div class="tag-member" data-idx="' + i + '" onclick="tgMember(this, ' + i + ')">' +
      '<div class="check">✓</div>' +
      '<div><b>' + m.name + '</b> <span style="color:#999;font-size:10px;">' + m.id + '</span></div>' +
    '</div>';
  }).join('');
  _members = mem;
  selectedTags = [];
  Toast.success('Đã load <b>' + mem.length + '</b> members — bấm chọn', 'Load OK');
}

function tgMember(el, idx){
  var m = _members[idx];
  if(!m) return;
  if(el.classList.contains('selected')){
    el.classList.remove('selected');
    selectedTags = selectedTags.filter(function(t){ return t.id !== m.id; });
  } else {
    el.classList.add('selected');
    selectedTags.push({ id: m.id, name: m.name });
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
    blocks = direct.split(';').map(function(m){ return m.trim(); }).filter(function(m){ return m; });
  }

  if(!blocks.length) return Toast.error('Chưa có tin nhắn — chọn file hoặc nhập tay');

  var delay = parseFloat(document.getElementById('spam-delay').value) || 2;
  var iconCount = parseInt(document.getElementById('icon-count').value) || 5;

  var tagUsers = [];
  if(document.getElementById('tg-tag').checked) tagUsers = selectedTags;

  var freezeTextAfter = parseInt(document.getElementById('freeze-text-after').value) || 0;
  var freezeDelayAfter = parseInt(document.getElementById('freeze-delay-after').value) || 0;

  var payload = {
    targets: selectedBoxes,
    blocks: blocks,
    delay: delay,
    use_color: flags.color,
    use_emoji: flags.emoji,
    icon_count: iconCount,
    tag_users: tagUsers,
    freeze_text: flags.freeze_text,
    freeze_delay: flags.freeze_delay,
    freeze_text_after: freezeTextAfter,
    freeze_delay_after: freezeDelayAfter
  };

  var r = await api('/api/tasks/start', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
  if(r.error) return Toast.error(r.error);

  var frz = [];
  if(flags.freeze_text) frz.push('❄️ Treo ngôn');
  if(flags.freeze_delay) frz.push('🌀 Treo nhây');
  var suffix = frz.length ? '<br><small>' + frz.join(' • ') + '</small>' : '';
  Toast.success('🚀 Đã bắt đầu: <code>' + r.task_id + '</code>' + suffix, 'Task running', 5000);
  loadTasks();
}

async function stopAll(){
  await api('/api/tasks/stop_all', { method: 'POST' });
  Toast.warning('Đã ra lệnh dừng tất cả task');
  loadTasks();
}

async function loadTasks(){
  var tasks = await api('/api/tasks');
  if(!Array.isArray(tasks)) tasks = [];
  var tb = document.getElementById('tasks-tbody');
  if(!tasks.length){
    tb.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#999;padding:16px;">Chưa có</td></tr>';
    return;
  }
  tb.innerHTML = tasks.map(function(t){
    var st = new Date(t.started_at * 1000).toLocaleString('vi-VN');
    var running = t.status === 'running';
    var b = running ? 'badge-ok' : 'badge-err';
    var txt = running ? 'Đang chạy' : 'Đã dừng';
    var meta = {};
    try { meta = JSON.parse(t.meta || '{}'); } catch(e){}
    var frzTags = '';
    if(meta.freeze_text) frzTags += ' <span class="badge badge-frz">❄️Ngôn</span>';
    if(meta.freeze_delay) frzTags += ' <span class="badge badge-frz">🌀Nhây</span>';
    return '<tr>' +
      '<td><code>' + t.id + '</code></td>' +
      '<td><span class="badge ' + b + '">' + txt + '</span>' + frzTags + '</td>' +
      '<td style="font-size:10px;">' + st + '</td>' +
      '<td>' + (running ? '<button type="button" class="btn-circle danger small" onclick="stopTask(\\'' + t.id + '\\')" title="Dừng">⏸️</button>' : '') + '</td>' +
    '</tr>';
  }).join('');
}

async function stopTask(tid){
  await api('/api/tasks/' + tid + '/stop', { method: 'POST' });
  Toast.warning('Đã dừng task <code>' + tid + '</code>');
  loadTasks();
}


/* ============================================================
   BOOT
============================================================ */
function refreshAll(){
  loadAccounts();
  loadFiles();
  loadTasks();
}

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
