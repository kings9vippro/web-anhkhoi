# ============================================================
# WEB-LENH v26.0 — Bot by Anh Khôi
# Anti-Ban VIP, block parse, auto UID tag, delay nhanh
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
# ICON ZALO — BỘ SÁT THƯƠNG
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
# ANTI-BAN VIP v26
# ============================================================
class AntiBanVIP:
    MIN_DELAY = 0.3
    MAX_DELAY = 30.0

    @staticmethod
    def compute_delay(user_delay, risk):
        """Delay nhanh — min 0.3s, tăng khi risk cao."""
        d = max(AntiBanVIP.MIN_DELAY, user_delay)
        if risk > 0.85:
            d = max(d, 15.0)
        elif risk > 0.7:
            d = max(d, 8.0)
        elif risk > 0.5:
            d = max(d, 4.0)
        # Jitter ±25% thôi
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
        """Lấy danh sách thành viên nhóm kèm UID + tên."""
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
        # Gọi API lấy profile của tất cả members 1 lần
        uids = [m.split("_")[0] for m in mem_list]
        if not uids:
            return []

        # Zalo cho phép query nhiều uid 1 lần
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
# PARSE FILE — THEO BLOCK (dòng trống = ngăn cách)
# ============================================================
def parse_blocks(filepath, max_blocks=2000):
    """
    Parse file thành các block ngăn bởi dòng trống.
    Mỗi block = 1 tin nhắn (giữ nguyên multiline).
    """
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
# WORKER
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
                icon_count, tag_uids_names, stop_event):
    """
    Worker:
    - blocks: list các tin nhắn (đã là multiline sẵn)
    - tag_uids_names: list {id, name} cần tag
    - icon_count: số icon thêm cuối (chỉ khi use_emoji)
    """
    block_idx = 0
    target_idx = 0
    count = 0
    last_acc_id = None

    print("[SPAM] Bắt đầu: " + tid)
    print("  Targets: " + str(len(targets)))
    print("  Blocks: " + str(len(blocks)))
    print("  Delay: " + str(delay) + "s")
    print("  Tags: " + str(len(tag_uids_names)))

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

        # Lấy block nguyên (giữ multiline)
        raw = blocks[block_idx % len(blocks)]
        block_idx += 1

        # Tag nếu có
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

            # Behavior
            z.set_typing(target_id, is_group=is_group)
            time.sleep(random.uniform(0.3, 1.0))

            r = z.send(msg, target_id, color=color, is_group=is_group)
            ok = bool(r and r.status_code == 200)

            update_stats(acc["id"], ok)
            count += 1
            status = "OK" if ok else "ERR"
            cs = "[" + color + "]" if color else ""
            preview = msg.replace("\n", " ⏎ ")[:60]
            print("[#" + str(count) + "] " + acc["label"] + " → " +
                  str(target_id) + cs + " [" + status + "] " + preview)

        except Exception as e:
            update_stats(acc["id"], False)
            print("[SPAM] Error " + acc["label"] + ": " + str(e))

        # Delay
        risk = acc["risk"] if acc["risk"] else 0.0
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


# ---- ACCOUNTS ----
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
    delay = float(d.get("delay", 3))
    use_color = bool(d.get("use_color", True))
    use_emoji = bool(d.get("use_emoji", True))
    icon_count = int(d.get("icon_count", 3))
    tag_uids_names = d.get("tag_users", [])  # [{id, name}]

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
              icon_count, tag_uids_names, stop_ev),
        daemon=True,
    )

    conn = db()
    conn.execute("""
        INSERT INTO tasks (id, type, meta, status, started_at, stats)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tid, "spam",
          json.dumps({"targets": len(targets), "blocks": len(blocks),
                      "delay": delay, "tags": len(tag_uids_names)}),
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
    return jsonify({"status": "ok", "service": "web-lenh", "version": "26.0"})


# ============================================================
# LOGO SVG
# ============================================================
LOGO_SVG = """<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" fill="none">
<defs>
<linearGradient id="gA" x1="0" y1="0" x2="1" y2="1">
<stop offset="0%" stop-color="#f093fb"/>
<stop offset="100%" stop-color="#f5576c"/>
</linearGradient>
<linearGradient id="gB" x1="0" y1="1" x2="1" y2="0">
<stop offset="0%" stop-color="#667eea"/>
<stop offset="100%" stop-color="#764ba2"/>
</linearGradient>
<radialGradient id="gC" cx="0.5" cy="0.5" r="0.6">
<stop offset="0%" stop-color="#ffffff" stop-opacity="0.9"/>
<stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
</radialGradient>
<filter id="fg">
<feGaussianBlur stdDeviation="3" result="b"/>
<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
</filter>
</defs>
<circle cx="60" cy="60" r="52" fill="url(#gB)" opacity="0.15"/>
<circle cx="60" cy="60" r="42" fill="url(#gC)" opacity="0.3"/>
<path d="M60 12 C30 12, 10 32, 10 58 C10 82, 30 102, 60 102 C68 102, 76 100, 82 96 L108 108 L100 84 C110 76, 116 68, 116 58 C116 32, 90 12, 60 12 Z"
 fill="url(#gA)" filter="url(#fg)"/>
<path d="M60 12 C30 12, 10 32, 10 58 C10 82, 30 102, 60 102 C68 102, 76 100, 82 96 L108 108 L100 84 C110 76, 116 68, 116 58 C116 32, 90 12, 60 12 Z"
 fill="none" stroke="white" stroke-width="1.5" opacity="0.7"/>
<circle cx="40" cy="55" r="5.5" fill="white"/>
<circle cx="60" cy="55" r="5.5" fill="white"/>
<circle cx="80" cy="55" r="5.5" fill="white"/>
<path d="M32 78 Q60 92 88 78" stroke="white" stroke-width="3" stroke-linecap="round" fill="none"/>
<path d="M92 20 L96 30 L106 33 L96 36 L92 46 L88 36 L78 33 L88 30 Z"
 fill="url(#gB)" filter="url(#fg)"/>
<path d="M20 90 L24 97 L31 100 L24 103 L20 110 L16 103 L9 100 L16 97 Z"
 fill="url(#gB)" filter="url(#fg)" opacity="0.85"/>
</svg>"""


# ============================================================
# HTML — LOGIN
# ============================================================
HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Đăng nhập — ALB Forge</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:'Inter',sans-serif;min-height:100vh;min-height:100dvh;display:flex;align-items:center;justify-content:center;
background:linear-gradient(-45deg,#667eea,#764ba2,#f093fb,#f5576c);background-size:400% 400%;animation:bg 15s ease infinite;padding:20px}
@keyframes bg{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
.card{background:rgba(255,255,255,0.98);padding:44px 34px;border-radius:32px;box-shadow:0 40px 100px rgba(0,0,0,0.3);
width:100%;max-width:420px;text-align:center;animation:in 0.8s cubic-bezier(0.16,1,0.3,1)}
@keyframes in{from{opacity:0;transform:translateY(50px) scale(0.94)}to{opacity:1;transform:translateY(0) scale(1)}}
.logo-box{width:120px;height:120px;margin:0 auto 20px;animation:fl 3.5s ease-in-out infinite;position:relative}
.logo-box::before{content:'';position:absolute;inset:-20px;border-radius:50%;
background:radial-gradient(circle,rgba(245,87,108,0.5),transparent 70%);filter:blur(20px);animation:gl 3s ease-in-out infinite}
@keyframes fl{0%,100%{transform:translateY(0) rotate(0)}50%{transform:translateY(-10px) rotate(-3deg)}}
@keyframes gl{0%,100%{opacity:0.5;transform:scale(1)}50%{opacity:0.9;transform:scale(1.2)}}
.logo-box svg{width:100%;height:100%;position:relative;z-index:1}
h1{color:#1a1a2e;margin-bottom:6px;font-size:24px;font-weight:900;letter-spacing:-0.6px}
p.sub{color:#6b7280;margin-bottom:28px;font-size:13px}
input{width:100%;padding:16px;border:2px solid #e5e7eb;border-radius:14px;font-size:15px;
font-family:inherit;font-weight:500;background:#f9fafb;text-align:center}
input:focus{outline:none;border-color:#667eea;background:white;box-shadow:0 0 0 4px rgba(102,126,234,0.12)}
button{width:100%;padding:16px;margin-top:14px;background:linear-gradient(135deg,#667eea,#764ba2);color:white;
border:none;border-radius:14px;font-size:15px;font-weight:800;font-family:inherit;cursor:pointer;
box-shadow:0 12px 30px rgba(102,126,234,0.4);transition:0.3s;position:relative;overflow:hidden}
button::before{content:'';position:absolute;inset:0;background:linear-gradient(120deg,transparent,rgba(255,255,255,0.4),transparent);
transform:translateX(-100%);transition:0.7s}
button:hover::before{transform:translateX(100%)}
button:hover{transform:translateY(-2px)}
.error{background:#fef2f2;color:#dc2626;padding:12px 16px;border-radius:12px;margin-bottom:16px;
font-size:13px;font-weight:600;border-left:4px solid #dc2626}
</style>
</head>
<body>
<div class="card">
<div class="logo-box">""" + LOGO_SVG + """</div>
<h1>ALB FORGE</h1>
<p class="sub">Bot by Anh Khôi • v26.0</p>
{% if error %}<div class="error">⚠️ {{ error }}</div>{% endif %}
<form method="POST">
<input type="password" name="password" placeholder="Nhập mật khẩu" autofocus required>
<button type="submit">🚀 Đăng nhập</button>
</form>
</div>
</body>
</html>
"""


# ============================================================
# HTML — INDEX
# ============================================================
HTML_INDEX = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>ALB Forge</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{touch-action:manipulation}
body{font-family:'Inter',sans-serif;background:#f8fafc;min-height:100vh;color:#1a1a2e;overflow-x:hidden}

.header{background:linear-gradient(135deg,#667eea,#764ba2);color:white;padding:14px 18px;
box-shadow:0 4px 30px rgba(102,126,234,0.35);position:sticky;top:0;z-index:100;
padding-top:calc(14px + env(safe-area-inset-top,0px))}
.header-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:10px}
.logo-mini{width:42px;height:42px;display:flex;align-items:center;justify-content:center;
background:rgba(255,255,255,0.15);border-radius:12px;border:1px solid rgba(255,255,255,0.25);padding:6px;
animation:logoFl 3.5s ease-in-out infinite}
@keyframes logoFl{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
.logo-mini svg{width:100%;height:100%}
.header-info{flex:1}
.header-info h1{font-size:16px;font-weight:900;letter-spacing:-0.3px}
.header-info p{font-size:10px;opacity:0.85;font-weight:500;margin-top:2px}
.logout-btn{background:rgba(255,255,255,0.15);color:white;border:1px solid rgba(255,255,255,0.25);
padding:8px 14px;border-radius:10px;font-size:12px;font-weight:700;font-family:inherit;cursor:pointer;transition:0.25s}
.logout-btn:hover{background:rgba(255,255,255,0.28)}

.container{max-width:1200px;margin:0 auto;padding:14px}

.tabs{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:14px;
background:white;padding:6px;border-radius:16px;box-shadow:0 4px 25px rgba(0,0,0,0.05)}
.tab{padding:10px 4px;border-radius:12px;cursor:pointer;font-size:10px;font-weight:800;
text-align:center;color:#6b7280;transition:0.3s;display:flex;flex-direction:column;
align-items:center;gap:3px;user-select:none}
.tab-icon{font-size:18px;transition:0.3s}
.tab:hover .tab-icon{transform:scale(1.15)}
.tab.active{background:linear-gradient(135deg,#667eea,#764ba2);color:white;
box-shadow:0 8px 20px rgba(102,126,234,0.4);transform:translateY(-2px)}
.panel{display:none;animation:fade 0.35s}
.panel.active{display:block}
@keyframes fade{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}

.card{background:white;padding:18px;border-radius:20px;box-shadow:0 6px 30px rgba(0,0,0,0.05);
margin-bottom:14px;border:1px solid #f0f2f5}
.card h2{font-size:14px;font-weight:900;margin-bottom:14px;display:flex;align-items:center;gap:8px;letter-spacing:-0.3px}
.card h2 .bi{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,#667eea,#764ba2);
display:flex;align-items:center;justify-content:center;font-size:14px;color:white}

.form-group{margin-bottom:12px}
.form-group label{display:block;margin-bottom:5px;font-size:11px;font-weight:800;color:#374151;
text-transform:uppercase;letter-spacing:0.5px}
.form-group input,.form-group textarea,.form-group select{width:100%;padding:11px 13px;border:2px solid #e5e7eb;
border-radius:12px;font-size:13px;font-family:inherit;font-weight:500;background:#f9fafb;color:#1a1a2e;transition:0.25s}
.form-group input:focus,.form-group textarea:focus,.form-group select:focus{outline:none;border-color:#667eea;
background:white;box-shadow:0 0 0 4px rgba(102,126,234,0.1)}
.form-group textarea{min-height:90px;resize:vertical;font-family:monospace;font-size:12px;line-height:1.5}

.btn-circle{width:52px;height:52px;border-radius:50%;border:none;cursor:pointer;display:inline-flex;
align-items:center;justify-content:center;font-size:20px;color:white;transition:all 0.3s cubic-bezier(0.16,1,0.3,1);
box-shadow:0 10px 25px rgba(0,0,0,0.15);position:relative;overflow:hidden;margin:3px}
.btn-circle::before{content:'';position:absolute;inset:0;
background:linear-gradient(120deg,transparent,rgba(255,255,255,0.4),transparent);transform:translateX(-100%);transition:0.6s}
.btn-circle:hover::before{transform:translateX(100%)}
.btn-circle:hover{transform:translateY(-4px) scale(1.06);box-shadow:0 15px 35px rgba(0,0,0,0.25)}
.btn-circle:active{transform:translateY(-1px) scale(0.98)}
.btn-circle.primary{background:linear-gradient(135deg,#667eea,#764ba2)}
.btn-circle.danger{background:linear-gradient(135deg,#ef4444,#dc2626)}
.btn-circle.success{background:linear-gradient(135deg,#10b981,#059669)}
.btn-circle.warning{background:linear-gradient(135deg,#f59e0b,#d97706)}
.btn-circle.info{background:linear-gradient(135deg,#3b82f6,#2563eb)}
.btn-circle.purple{background:linear-gradient(135deg,#8b5cf6,#7c3aed)}
.btn-circle.pink{background:linear-gradient(135deg,#ec4899,#db2777)}
.btn-circle.teal{background:linear-gradient(135deg,#14b8a6,#0d9488)}
.btn-circle.small{width:38px;height:38px;font-size:15px}
.btn-circle.big{width:70px;height:70px;font-size:26px}

.btn-rect{padding:11px 18px;border:none;border-radius:12px;cursor:pointer;font-size:12px;font-weight:800;
font-family:inherit;color:white;transition:0.3s;box-shadow:0 8px 20px rgba(0,0,0,0.15);
display:inline-flex;align-items:center;gap:6px}
.btn-rect:hover{transform:translateY(-3px)}
.btn-rect.primary{background:linear-gradient(135deg,#667eea,#764ba2)}
.btn-rect.danger{background:linear-gradient(135deg,#ef4444,#dc2626)}
.btn-rect.success{background:linear-gradient(135deg,#10b981,#059669)}
.btn-rect.info{background:linear-gradient(135deg,#3b82f6,#2563eb)}
.btn-rect.purple{background:linear-gradient(135deg,#8b5cf6,#7c3aed)}

.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:8px;margin-bottom:14px}
.stat{background:linear-gradient(135deg,#f9fafb,#f3f4f6);padding:12px;border-radius:14px;
border:1px solid #e5e7eb;position:relative;overflow:hidden}
.stat::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;
background:linear-gradient(90deg,#667eea,#764ba2)}
.stat .label{font-size:9px;color:#6b7280;margin-bottom:5px;text-transform:uppercase;
letter-spacing:0.5px;font-weight:800}
.stat .value{font-size:22px;font-weight:900;color:#1a1a2e;line-height:1}

.table-wrap{overflow-x:auto}
.table{width:100%;border-collapse:collapse}
.table th,.table td{padding:9px 6px;text-align:left;font-size:11px;border-bottom:1px solid #f0f2f5;white-space:nowrap}
.table th{background:#f9fafb;font-weight:800;color:#6b7280;text-transform:uppercase;font-size:9px;letter-spacing:0.5px}
.table td code{background:#f3f4f6;padding:2px 6px;border-radius:5px;font-size:10px;font-family:monospace}

.badge{display:inline-flex;align-items:center;gap:2px;padding:3px 7px;border-radius:20px;font-size:9px;font-weight:800}
.badge-ok{background:#d1fae5;color:#065f46}
.badge-err{background:#fee2e2;color:#991b1b}
.badge-warn{background:#fef3c7;color:#92400e}
.badge-info{background:#dbeafe;color:#1e40af}

.box-list{max-height:340px;overflow-y:auto;border:2px solid #e5e7eb;border-radius:14px;
padding:8px;background:#f9fafb}
.box-item{padding:10px;border-radius:10px;background:white;margin-bottom:6px;cursor:pointer;
border:2px solid transparent;transition:0.2s;display:flex;align-items:center;gap:10px;font-size:12px}
.box-item:hover{border-color:#667eea}
.box-item.selected{border-color:#10b981;background:#ecfdf5}
.box-item .check{width:18px;height:18px;border:2px solid #d1d5db;border-radius:5px;
display:flex;align-items:center;justify-content:center;font-size:10px;color:white;font-weight:900;flex-shrink:0}
.box-item.selected .check{background:#10b981;border-color:#10b981}
.box-item .info{flex:1;min-width:0}
.box-item .name{font-weight:700;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.box-item .meta{font-size:10px;color:#6b7280;font-family:monospace;margin-top:2px}

.file-item{display:flex;align-items:center;gap:10px;padding:10px;border-radius:12px;
background:#f9fafb;margin-bottom:8px;border:1px solid #e5e7eb}
.file-item .info{flex:1;min-width:0}
.file-item .name{font-weight:700;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.file-item .meta{font-size:10px;color:#6b7280;margin-top:2px}

.chip-group{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px}
.chip{padding:7px 13px;background:#f3f4f6;color:#374151;border-radius:20px;font-size:11px;
font-weight:800;cursor:pointer;transition:0.2s;border:2px solid transparent;user-select:none}
.chip:hover{background:#e5e7eb}
.chip.active{background:linear-gradient(135deg,#667eea,#764ba2);color:white;
box-shadow:0 4px 15px rgba(102,126,234,0.4)}

.toggle-group{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}
.toggle{padding:11px;border:2px solid #e5e7eb;border-radius:12px;cursor:pointer;
text-align:center;font-weight:800;font-size:11px;background:#f9fafb;color:#6b7280;user-select:none;transition:0.25s}
.toggle.active{background:linear-gradient(135deg,#667eea,#764ba2);color:white;border-color:transparent;
box-shadow:0 8px 20px rgba(102,126,234,0.4);transform:translateY(-2px)}

.alert{padding:13px 16px;border-radius:12px;margin-bottom:10px;font-size:12px;font-weight:700;display:none;
position:fixed;top:80px;right:14px;z-index:999;box-shadow:0 15px 45px rgba(0,0,0,0.2);max-width:320px}
.alert.show{display:flex;gap:8px;animation:sl 0.35s}
@keyframes sl{from{opacity:0;transform:translateX(120%)}to{opacity:1;transform:translateX(0)}}
.alert-success{background:linear-gradient(135deg,#d1fae5,#a7f3d0);color:#065f46;border-left:5px solid #10b981}
.alert-error{background:linear-gradient(135deg,#fee2e2,#fecaca);color:#991b1b;border-left:5px solid #ef4444}

.tag-selector{max-height:240px;overflow-y:auto;border:2px solid #e5e7eb;border-radius:12px;
padding:8px;background:#f9fafb;display:none;margin-top:8px}
.tag-selector.show{display:block}
.tag-member{padding:8px;border-radius:8px;background:white;margin-bottom:4px;cursor:pointer;
border:2px solid transparent;font-size:12px;display:flex;align-items:center;gap:8px}
.tag-member:hover{border-color:#8b5cf6}
.tag-member.selected{border-color:#8b5cf6;background:#f3e8ff}
.tag-member .check{width:16px;height:16px;border:2px solid #d1d5db;border-radius:4px;
display:flex;align-items:center;justify-content:center;font-size:9px;color:white;font-weight:900;flex-shrink:0}
.tag-member.selected .check{background:#8b5cf6;border-color:#8b5cf6}

@media (max-width:640px){
.container{padding:10px}
.card{padding:14px;border-radius:18px}
.header{padding:10px 12px}
.header-info h1{font-size:14px}
.header-info p{font-size:9px}
.logo-mini{width:36px;height:36px}
.logout-btn{padding:7px 10px;font-size:11px}
.tab{padding:9px 3px;font-size:9px}
.tab-icon{font-size:16px}
.stat .value{font-size:18px}
.btn-circle{width:46px;height:46px;font-size:18px}
.btn-circle.small{width:34px;height:34px;font-size:13px}
.btn-circle.big{width:62px;height:62px;font-size:22px}
.alert{left:10px;right:10px;max-width:none}
}
</style>
</head>
<body>

<div class="header">
<div class="header-inner">
<div class="logo-mini">""" + LOGO_SVG + """</div>
<div class="header-info">
<h1>ALB FORGE</h1>
<p>Bot by Anh Khôi • v26.0 VIP</p>
</div>
<button class="logout-btn" onclick="location.href='/logout'">🚪 Thoát</button>
</div>
</div>

<div class="container">

<div class="tabs">
<div class="tab active" data-tab="accounts"><div class="tab-icon">🔐</div><div>Acc</div></div>
<div class="tab" data-tab="boxes"><div class="tab-icon">📦</div><div>Box</div></div>
<div class="tab" data-tab="files"><div class="tab-icon">📁</div><div>File</div></div>
<div class="tab" data-tab="spam"><div class="tab-icon">🎯</div><div>Spam</div></div>
</div>

<div id="alert" class="alert"></div>

<!-- ACCOUNTS -->
<div class="panel active" id="panel-accounts">
<div class="card">
<h2><span class="bi">➕</span> Thêm tài khoản</h2>
<div class="form-group"><label>Tên gợi nhớ</label><input id="add-label" placeholder="acc1"></div>
<div class="form-group"><label>IMEI</label><input id="add-imei" placeholder="000000000000000"></div>
<div class="form-group"><label>Cookie (JSON)</label>
<textarea id="add-cookies" placeholder='{"zpw_sek":"...","zpw_ver":"645","zpw_type":"30"}'></textarea></div>
<button class="btn-rect primary" onclick="addAccount()">💾 Thêm tài khoản</button>
</div>
<div class="card">
<h2><span class="bi">📋</span> Danh sách</h2>
<div class="stat-grid">
<div class="stat"><div class="label">Tổng</div><div class="value" id="stat-total">0</div></div>
<div class="stat"><div class="label">Active</div><div class="value" id="stat-active">0</div></div>
<div class="stat"><div class"="label">Sent</div><div class="value" onclick id="stat-sent">0</div></div>
="</div>
<div class="table-wrap"><table classclear="table"><thead><tr>
<th>ID</th><th>Tên</th><th>OK/Lỗi</th><th>Risk</th><th>Sent</th><th></th>
</tr></thead><tbody id="accounts-tbody"></tbody></table></div>
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
<button class="btn-circle primary" onclick="loadBoxes()" title="Load">🔄</button>
<button class="btn-circle success" onclick="selectAllBoxes()" title="Chọn tất cả">✅</button>
<button class="btn-circle dangerAllBoxes()" title="Bỏ chọn">❌</button>
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

<!-- FILES -->
<div class="panel" id="panel-files">
<div class="card">
<h2><span class="bi">📤</span> Upload file</h2>
<div class="form-group"><input type="file" id="file-input" accept=".txt" style="padding:6px;"></div>
<button class="btn-rect primary" onclick="uploadFile()">📤 Upload</button>
<div style="margin-top:10px;font-size:11px;color:#6b7280;line-height:1.6;">
💡 Mỗi khối ngăn bởi **dòng trống** = 1 tin nhắn (giữ nguyên multiline)
</div>
</div>
<div class="card">
<h2><span class="bi">📁</span> File đã upload</h2>
<div id="files-list"><div style="text-align:center;padding:20px;color:#999;font-size:11px;">Chưa có</div></div>
</div>
</div>

<!-- SPAM -->
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
<button class="btn-rect info" onclick="loadMembers()">🔄 Load members</button>
<div class="tag-selector" id="tag-selector"></div>
<input type="hidden" id="tag-selected" value="">
</div>
</div>

<div style="text-align:center;margin-top:18px;">
<button class="btn-circle success big" onclick="startSpam()" title="Bắt đầu">▶️</button>
<button class="btn-circle danger big" onclick="stopAll()" title="Dừng">⏸️</button>
</div>
</div>

<div class="card" style="background:linear-gradient(135deg,#fef3c7,#fde68a);border:2px solid #fbbf24;">
<h2 style="color:#92400e;"><span class="bi" style="background:#92400e;">🛡️</span> Anti-Ban VIP v26</h2>
<div style="color:#78350f;font-size:11px;line-height:1.9;font-weight:600;">
✅ Delay min 0.3s — gửi siêu nhanh<br>
✅ Không warmup chậm<br>
✅ Acc + Target rotation<br>
✅ 12 màu Zalo ngẫu nhiên<br>
✅ Icon sát thương Zalo<br>
✅ Risk adaptive delay<br>
✅ Fail 50 lần → auto disable<br>
✅ Giữ nguyên 100% text user
</div>
</div>

<div class="card">
<h2><span class="bi">📋</span> Tác vụ</h2>
<button class="btn-circle danger small" onclick="stopAll()" title="Dừng hết">⏸️</button>
<div class="table-wrap" style="margin-top:10px;">
<table class="table"><thead><tr>
<th>ID</th><th>Trạng thái</th><th>Bắt đầu</th><th></th>
</tr></thead><tbody id="tasks-tbody"></tbody></table>
</div>
</div>
</div>

</div>

<script>
let flags = { color: true, emoji: true };
let selectedBoxes = [];
let selectedTags = [];

document.querySelectorAll('.tab').forEach(t => {
    t.onclick = () => {
        document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
        document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
        t.classList.add('active');
        document.getElementById('panel-' + t.dataset.tab).classList.add('active');
        refreshAll();
    };
});

document.querySelectorAll('#delay-chips .chip').forEach(c => {
    c.onclick = () => {
        document.querySelectorAll('#delay-chips .chip').forEach(x => x.classList.remove('active'));
        c.classList.add('active');
        document.getElementById('spam-delay').value = c.dataset.delay;
    };
});

document.querySelectorAll('#icon-chips .chip').forEach(c => {
    c.onclick = () => {
        document.querySelectorAll('#icon-chips .chip').forEach(x => x.classList.remove('active'));
        c.classList.add('active');
        document.getElementById('icon-count').value = c.dataset.icon;
    };
});

function showAlert(msg, type) {
    type = type || 'success';
    const a = document.getElementById('alert');
    a.innerHTML = (type === 'success' ? '✅ ' : '⚠️ ') + msg;
    a.className = 'alert show alert-' + type;
    setTimeout(() => a.classList.remove('show'), 3500);
}

async function api(url, opts) {
    opts = opts || {};
    const r = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    return r.json();
}

function tgFlag(name) {
    flags[name] = !flags[name];
    document.getElementById('tg-' + name).classList.toggle('active', flags[name]);
}

function tgTag() {
    const c = document.getElementById('tg-tag').checked;
    document.getElementById('tag-wrap').style.display = c ? 'block' : 'none';
}

async function loadAccounts() {
    const accs = await api('/api/accounts');
    const tb = document.getElementById('accounts-tbody');
    if (!accs.length) {
        tb.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#999;padding:20px;">Chưa có</td></tr>';
    } else {
        tb.innerHTML = accs.map(a => {
            const risk = (a.risk || 0).toFixed(2);
            const rc = risk > 0.5 ? 'badge-err' : risk > 0.2 ? 'badge-warn' : 'badge-ok';
            return '<tr>' +
                '<td>' + a.id + '</td>' +
                '<td><b>' + a.label + '</b></td>' +
                '<td><span class="badge badge-ok">' + a.ok_count + '</span> <span class="badge badge-err">' + a.fail_count + '</span></td>' +
                '<td><span class="badge ' + rc + '">' + risk + '</span></td>' +
                '<td><span class="badge badge-info">' + (a.total_sent || 0) + '</span></td>' +
                '<td>' +
                    '<button class="btn-circle primary small" onclick="checkAcc(' + a.id + ')">🔍</button>' +
                    '<button class="btn-circle warning small" onclick="resetAcc(' + a.id + ')">🔄</button>' +
                    '<button class="btn-circle danger small" onclick="delAcc(' + a.id + ')">🗑️</button>' +
                '</td>' +
            '</tr>';
        }).join('');
    }
    document.getElementById('stat-total').textContent = accs.length;
    document.getElementById('stat-active').textContent = accs.filter(a => a.enabled).length;
    document.getElementById('stat-sent').textContent = accs.reduce((s, a) => s + (a.total_sent || 0), 0);

    const s1 = document.getElementById('load-acc-select');
    const s2 = document.getElementById('member-acc-select');
    const opts = '<option value="">-- Chọn --</option>' +
        accs.map(a => '<option value="' + a.id + '">' + a.label + '</option>').join('');
    const v1 = s1.value, v2 = s2.value;
    s1.innerHTML = opts; s1.value = v1;
    s2.innerHTML = opts; s2.value = v2;
}

async function addAccount() {
    const label = document.getElementById('add-label').value.trim();
    const imei = document.getElementById('add-imei').value.trim();
    const cookies = document.getElementById('add-cookies').value.trim();
    if (!imei || !cookies) return showAlert('Điền IMEI và cookie', 'error');
    const r = await api('/api/accounts/add', {
        method: 'POST',
        body: JSON.stringify({ label, imei, cookies }),
    });
    if (r.error) return showAlert(r.error, 'error');
    showAlert('Đã thêm ' + r.label);
    document.getElementById('add-label').value = '';
    document.getElementById('add-imei').value = '';
    document.getElementById('add-cookies').value = '';
    refreshAll();
}

async function delAcc(id) {
    if (!confirm('Xóa?')) return;
    await api('/api/accounts/' + id, { method: 'DELETE' });
    showAlert('Đã xóa');
    refreshAll();
}

async function resetAcc(id) {
    await api('/api/accounts/' + id + '/reset', { method: 'POST' });
    showAlert('Đã reset');
    refreshAll();
}

async function checkAcc(id) {
    const r = await api('/api/accounts/' + id + '/check', { method: 'POST' });
    if (r.error) return showAlert(r.error, 'error');
    showAlert('Cookie sống! UID: ' + r.uid);
}

async function loadBoxes() {
    const aid = document.getElementById('load-acc-select').value;
    if (!aid) return showAlert('Chọn acc', 'error');
    showAlert('Đang load...');
    const r = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
    if (r.error) return showAlert(r.error, 'error');

    const all = [...(r.groups || []), ...(r.friends || [])];
    const bl = document.getElementById('box-list');
    if (!all.length) {
        bl.innerHTML = '<div style="text-align:center;padding:20px;color:#999;">Không có</div>';
        return;
    }
    bl.innerHTML = all.map((b, i) =>
        '<div class="box-item" data-idx="' + i + '" onclick="tgBox(this, ' + i + ')">' +
            '<div class="check">✓</div>' +
            '<div class="info">' +
                '<div class="name">' + b.name + '</div>' +
                '<div class="meta">' + b.id + ' | ' + b.type + '</div>' +
            '</div>' +
        '</div>'
    ).join('');
    window._boxes = all;
    selectedBoxes = [];
    document.getElementById('selected-count').textContent = '0';
    showAlert('Đã load ' + all.length + ' box');
}

function tgBox(el, idx) {
    const b = window._boxes[idx];
    if (el.classList.contains('selected')) {
        el.classList.remove('selected');
        selectedBoxes = selectedBoxes.filter(x => x.id !== b.id);
    } else {
        el.classList.add('selected');
        selectedBoxes.push(b);
    }
    document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function selectAllBoxes() {
    document.querySelectorAll('.box-item').forEach(el => el.classList.add('selected'));
    selectedBoxes = [...(window._boxes || [])];
    document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function clearAllBoxes() {
    document.querySelectorAll('.box-item').forEach(el => el.classList.remove('selected'));
    selectedBoxes = [];
    document.getElementById('selected-count').textContent = '0';
}

async function uploadFile() {
    const input = document.getElementById('file-input');
    if (!input.files.length) return showAlert('Chọn file', 'error');
    const fd = new FormData();
    fd.append('file', input.files[0]);
    showAlert('Đang upload...');
    const r = await fetch('/api/files/upload', { method: 'POST', body: fd }).then(r => r.json());
    if (r.error) return showAlert(r.error, 'error');
    showAlert('Đã upload ' + r.filename + ' (' + r.lines + ' khối)');
    input.value = '';
    loadFiles();
}

async function loadFiles() {
    const files = await api('/api/files');
    const list = document.getElementById('files-list');
    if (!files.length) {
        list.innerHTML = '<div style="text-align:center;padding:20px;color:#999;font-size:11px;">Chưa có</div>';
    } else {
        list.innerHTML = files.map(f => {
            const kb = (f.size / 1024).toFixed(1);
            return '<div class="file-item">' +
                '<div class="info">' +
                    '<div class="name">📄 ' + f.filename + '</div>' +
                    '<div class="meta">' + f.lines + ' khối • ' + kb + ' KB</div>' +
                '</div>' +
                '<button class="btn-circle info small" onclick="previewFile(' + f.id + ')">👁️</button>' +
                '<button class="btn-circle danger small" onclick="delFile(' + f.id + ')">🗑️</button>' +
            '</div>';
        }).join('');
    }
    const s = document.getElementById('spam-file-select');
    s.innerHTML = '<option value="">-- Chọn file --</option>' +
        files.map(f => '<option value="' + f.id + '">' + f.filename + ' (' + f.lines + ')</option>').join('');
}

async function previewFile(fid) {
    const r = await api('/api/files/' + fid + '/preview');
    if (r.error) return showAlert(r.error, 'error');
    const pv = r.preview.map((m, i) => '--- Khối ' + (i + 1) + ' ---\n' + m).join('\n\n');
    alert('File: ' + r.filename + '\nTổng: ' + r.total + ' khối\n\n' + pv);
}

async function delFile(fid) {
    if (!confirm('Xóa file?')) return;
    await api('/api/files/' + fid, { method: 'DELETE' });
    showAlert('Đã xóa');
    loadFiles();
}

async function loadMembers() {
    const aid = document.getElementById('member-acc-select').value;
    if (!aid) return showAlert('Chọn acc', 'error');
    const box = selectedBoxes.find(b => b.type === 'group');
    if (!box) return showAlert('Cần chọn 1 nhóm trước', 'error');

    showAlert('Đang load members...');
    const r = await api('/api/accounts/' + aid + '/members/' + box.id, { method: 'POST' });
    if (r.error) return showAlert(r.error, 'error');

    const mem = r.members || [];
    const sel = document.getElementById('tag-selector');
    sel.classList.add('show');
    if (!mem.length) {
        sel.innerHTML = '<div style="padding:14px;text-align:center;color:#999;font-size:11px;">Không có members</div>';
        return;
    }
    sel.innerHTML = mem.map((m, i) =>
        '<div class="tag-member" data-idx="' + i + '" onclick="tgMember(this, ' + i + ')">' +
            '<div class="check">✓</div>' +
            '<div><b>' + m.name + '</b> <span style="color:#999;font-size:10px;">' + m.id + '</span></div>' +
        '</div>'
    ).join('');
    window._members = mem;
    showAlert('Đã load ' + mem.length + ' members - bấm chọn');
}

function tgMember(el, idx) {
    const m = window._members[idx];
    if (el.classList.contains('selected')) {
        el.classList.remove('selected');
        selectedTags = selectedTags.filter(t => t.id !== m.id);
    } else {
        el.classList.add('selected');
        selectedTags.push({ id: m.id, name: m.name });
    }
    document.getElementById('tag-selected').value = JSON.stringify(selectedTags);
}

async function startSpam() {
    if (!selectedBoxes.length) return showAlert('Chưa chọn box', 'error');

    const fid = document.getElementById('spam-file-select').value;
    const direct = document.getElementById('spam-messages').value.trim();
    let blocks = [];

    if (fid) {
        const r = await api('/api/files/' + fid + '/preview');
        if (r.error) return showAlert('Lỗi file: ' + r.error, 'error');
        blocks = r.all || [];
    } else if (direct) {
        blocks = direct.split(';').map(m => m.trim()).filter(m => m);
    }

    if (!blocks.length) return showAlert('Chưa có tin', 'error');

    const delay = parseFloat(document.getElementById('spam-delay').value) || 2;
    const iconCount = parseInt(document.getElementById('icon-count').value) || 5;

    let tagUsers = [];
    if (document.getElementById('tg-tag').checked) {
        tagUsers = selectedTags;
    }

    const r = await api('/api/tasks/start', {
        method: 'POST',
        body: JSON.stringify({
            targets: selectedBoxes,
            blocks: blocks,
            delay: delay,
            use_color: flags.color,
            use_emoji: flags.emoji,
            icon_count: iconCount,
            tag_users: tagUsers,
        }),
    });
    if (r.error) return showAlert(r.error, 'error');
    showAlert('🚀 Đã bắt đầu: ' + r.task_id);
    loadTasks();
}

async function stopAll() {
    await api('/api/tasks/stop_all', { method: 'POST' });
    showAlert('Đã dừng tất cả');
    loadTasks();
}

async function loadTasks() {
    const tasks = await api('/api/tasks');
    const tb = document.getElementById('tasks-tbody');
    if (!tasks.length) {
        tb.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#999;padding:16px;">Chưa có</td></tr>';
        return;
    }
    tb.innerHTML = tasks.map(t => {
        const st = new Date(t.started_at * 1000).toLocaleString('vi-VN');
        const b = t.status === 'running' ? 'badge-ok' : 'badge-err';
        const txt = t.status === 'running' ? 'Đang chạy' : 'Đã dừng';
        return '<tr>' +
            '<td><code>' + t.id + '</code></td>' +
            '<td><span class="badge ' + b + '">' + txt + '</span></td>' +
            '<td style="font-size:10px;">' + st + '</td>' +
            '<td>' + (t.status === 'running' ? '<button class="btn-circle danger small" onclick="stopTask(\'' + t.id + '\')">⏸️</button>' : '') + '</td>' +
        '</tr>';
    }).join('');
}

async function stopTask(tid) {
    await api('/api/tasks/' + tid + '/stop', { method: 'POST' });
    showAlert('Đã dừng');
    loadTasks();
}

function refreshAll() {
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
