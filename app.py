# ============================================================
# WEB-LENH v26.0 — Spam PRO MAX (Bot by Anh Khôi)
# 2 chế độ: Nhây (theo số) + Ngôn (y chang)
# Anti-ban chuyên gia — Spam siêu nhanh
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
import string
import hashlib
import re
from functools import wraps
from datetime import datetime
from collections import deque

from flask import (
    Flask, render_template_string, request, jsonify,
    session, redirect, url_for
)
from Crypto.Cipher import AES
import requests

# ============================================================
# CONFIG
# ============================================================
APP_PASSWORD = os.environ.get("APP_PASSWORD", "anhkhoidz")
DATA_DIR = os.environ.get("DATA_DIR", "/tmp/alb_web")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "alb.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "alb-lenh-2026-secret")
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
            label TEXT,
            imei TEXT,
            cookies TEXT,
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
            id TEXT PRIMARY KEY,
            type TEXT,
            meta TEXT,
            status TEXT,
            started_at REAL,
            stats TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            filepath TEXT,
            lines INTEGER DEFAULT 0,
            size INTEGER DEFAULT 0,
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
# ZALO ICONS / EMOJI
# ============================================================
ZALO_UNICODE = [
    "😀", "😁", "😂", "🤣", "😃", "😄", "😅", "😆", "😉", "😊",
    "😋", "😎", "😍", "😘", "🥰", "😗", "😙", "😚", "🙂", "🤗",
    "🤩", "🤔", "🤨", "😐", "😑", "😶", "🙄", "😏", "😣", "😥",
    "😮", "🤐", "😯", "😪", "😫", "🥱", "😴", "😌", "😛", "😜",
    "😝", "🤤", "😒", "😓", "😔", "😕", "🙃", "🤑", "😲", "🙁",
    "❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💔",
    "❣️", "💕", "💞", "💓", "💗", "💖", "💘", "💝", "💟", "☮️",
    "👍", "👎", "👊", "✊", "🤛", "🤜", "🤞", "✌️", "🤟", "🤘",
    "🔥", "💯", "✨", "⭐", "🌟", "💫", "⚡", "💥", "💢", "💨",
    "🎉", "🎊", "🎈", "🎁", "🏆", "🥇", "🥈", "🥉", "🎯", "🎮",
]

ZALO_EMOJI_CODES = [
    ":-*", ":-d", ":-p", ":-(", ":-)", "=))", "b-)", ":-o",
    ":-s", ":-h", "8-|", ":->", ";;)", ":-<", ":-$", ":3",
    ":-?", ":-x", "8*)", "=d>", ":-bd", ":-L", ":-R",
    ":-F", ";-)", "p-(", ":-bye", ";-/", ":-q", "x-)", ";-!",
]


def get_random_emoji():
    if random.random() < 0.5:
        return random.choice(ZALO_UNICODE)
    return random.choice(ZALO_EMOJI_CODES)


# ============================================================
# ANTI-BAN CHUYÊN GIA v26 — CỰC MẠNH
# ============================================================
class AntiBanExpert:
    """
    Anti-ban chuyên gia — chống ban Zalo cực mạnh:

    1. Adaptive delay: tự điều chỉnh theo tỉ lệ thành công
    2. Session rotation: đổi session sau N request
    3. Zero-width Unicode mask: 8 loại ký tự vô hình
    4. Content variation: xoay dòng ngẫu nhiên (nhây) hoặc y chang (ngôn)
    5. Emoji rotation: nhiều emoji mỗi tin
    6. Color rotation: 12 màu Zalo
    7. Account rotation: đổi acc mỗi tin
    8. Target rotation: đổi box mỗi tin
    9. Warmup: 2 tin đầu delay dài
    10. Risk score: tự disable acc yếu
    11. Dedup: không gửi trùng 5 tin gần nhất
    12. Human typing: set typing trước khi gửi
    13. Micro-pause: nghỉ ngẫu nhiên giữa tin
    """

    MIN_DELAY = 0.3
    MAX_DELAY = 30.0
    WARMUP_COUNT = 2

    ZERO_WIDTH = ["\u200b", "\u200c", "\u200d", "\ufeff",
                  "\u2060", "\u180e", "\u2061", "\u2062"]

    ZALO_COLORS = [
        "red", "orange", "yellow", "green",
        "ocean", "blue", "purple", "pink",
        "brown", "black", "gray", "white",
    ]

    @staticmethod
    def compute_delay(user_delay, risk, ok_count):
        """Delay adaptive: min = user_delay, max = 30s nếu risk cao."""
        d = user_delay
        if ok_count < AntiBanExpert.WARMUP_COUNT:
            d = max(d, 4.0)
        if risk > 0.7:
            d = max(d, 10.0)
        elif risk > 0.5:
            d = max(d, 5.0)
        elif risk > 0.3:
            d = max(d, 3.0)
        # Jitter ±30%
        d = d * random.uniform(0.7, 1.3)
        return max(AntiBanExpert.MIN_DELAY, min(AntiBanExpert.MAX_DELAY, d))

    @staticmethod
    def entropy_mask(text):
        """Chèn zero-width char — không thay đổi nội dung hiển thị."""
        if random.random() < 0.5:
            zw = random.choice(AntiBanExpert.ZERO_WIDTH)
            pos = random.randint(1, max(1, len(text) - 1))
            text = text[:pos] + zw + text[pos:]
        return text

    @staticmethod
    def append_emojis(text, count=10):
        """Thêm N emoji ngẫu nhiên cuối câu."""
        if count <= 0:
            return text
        emojis = [get_random_emoji() for _ in range(count)]
        return text + " " + " ".join(emojis)

    @staticmethod
    def random_color():
        return random.choice(AntiBanExpert.ZALO_COLORS)

    @staticmethod
    def compute_risk(ok, fail):
        total = ok + fail
        if total == 0:
            return 0.0
        return min(1.0, fail / total)

    @staticmethod
    def micro_pause():
        """Nghỉ ngắn random."""
        if random.random() < 0.1:
            time.sleep(random.uniform(0.3, 1.5))


# ============================================================
# ZALO TOOLS
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
            raise Exception("Cookie hoặc IMEI không đúng")
        self.uid = ud.get("send2me_id")
        self.secret_key = ud.get("zpw_enk")
        if not self.secret_key:
            raise Exception("Không lấy được khóa")

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

    def get_groups(self):
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
                out.append({
                    "id": gid, "name": info["name"],
                    "type": "group", "members": info["totalMember"],
                })
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

    def get_friends(self):
        try:
            enc = self._enc({"offset": 0, "count": 500})
            r = self.s.post(
                "https://profile-wpa.chat.zalo.me/api/social/friend/getfriends",
                params={"zpw_ver": 645, "zpw_type": 30},
                data={"params": enc}, timeout=20,
            )
            dec = self._dec(r.json()["data"])
            data = json.loads(dec).get("data", [])
            users = data if isinstance(data, list) else data.get("users", [])
            out = []
            for u in users:
                out.append({
                    "id": u.get("userId"),
                    "name": u.get("zaloName", "?"),
                    "type": "user",
                })
            return out
        except Exception:
            return []

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
# FILE PARSER
# ============================================================
def parse_message_file(filepath, max_lines=10000):
    messages = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                line = re.sub(r"^\d+[\.\)\-\:]\s*", "", line)
                if line:
                    messages.append(line)
    except Exception as e:
        print("[FILE] parse error: " + str(e))
    return messages


# ============================================================
# SPAM WORKER — 2 CHẾ ĐỘ
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
    risk = AntiBanExpert.compute_risk(ok_c, fail_c)
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


def spam_worker(tid, targets, messages, delay, use_color, use_emoji,
                emoji_count, tag_uids, mode, stop_event):
    """
    Worker 2 chế độ:
    - mode='nhay': xoay dòng ngẫu nhiên, không trùng 5 tin gần nhất
    - mode='ngon': gửi Y CHANG nội dung, không đổi
    """
    target_idx = 0
    count = 0
    last_acc_id = None
    recent_msgs = deque(maxlen=5)

    # Xoay dòng: trộn list 1 lần, dùng tuần tự, khi hết thì trộn lại
    shuffled_msgs = []
    shuffle_idx = 0

    def next_nhay():
        nonlocal shuffled_msgs, shuffle_idx
        if not shuffled_msgs or shuffle_idx >= len(shuffled_msgs):
            shuffled_msgs = random.sample(messages, len(messages))
            shuffle_idx = 0
        m = shuffled_msgs[shuffle_idx]
        shuffle_idx += 1
        return m

    print("[SPAM] Task " + tid + " | Mode: " + mode)
    print("  Targets: " + str(len(targets)))
    print("  Messages: " + str(len(messages)))
    print("  Delay: " + str(delay) + "s")
    print("  Color: " + str(use_color) + " | Emoji: " + str(use_emoji))

    while not stop_event.is_set():
        acc = pick_account()
        if not acc:
            time.sleep(0.5)
            continue

        # Rotate acc
        if acc["id"] == last_acc_id:
            conn = db()
            cnt = conn.execute(
                "SELECT COUNT(*) as c FROM accounts WHERE enabled = 1"
            ).fetchone()["c"]
            conn.close()
            if cnt > 1:
                time.sleep(0.1)
                continue
        last_acc_id = acc["id"]

        # Target rotation
        target = targets[target_idx % len(targets)]
        target_idx += 1

        # Lấy message theo mode
        if mode == "nhay":
            raw_msg = next_nhay()
            tries = 0
            while raw_msg in recent_msgs and tries < 10:
                raw_msg = next_nhay()
                tries += 1
            recent_msgs.append(raw_msg)
            # Nhây: chèn entropy + emoji
            msg = raw_msg
            msg = AntiBanExpert.entropy_mask(msg)
            if use_emoji and emoji_count > 0:
                msg = AntiBanExpert.append_emojis(msg, emoji_count)
        else:
            # Ngôn: y chang, KHÔNG đổi
            msg = messages[count % len(messages)]

        # Tag UID
        if tag_uids:
            tags = " ".join(["@" + u for u in tag_uids])
            msg = tags + " " + msg

        # Color
        color = AntiBanExpert.random_color() if use_color else None

        is_group = target.get("type") == "group"
        target_id = target.get("id")

        try:
            cookies = json.loads(acc["cookies"])
            z = Zalo(acc["imei"], cookies)

            # Warmup
            if acc["ok_count"] < AntiBanExpert.WARMUP_COUNT:
                time.sleep(random.uniform(2, 4))

            # Behavior
            z.set_typing(target_id, is_group=is_group)
            time.sleep(random.uniform(0.2, 0.8))

            r = z.send(msg, target_id, color=color, is_group=is_group)
            ok = bool(r and r.status_code == 200)

            update_stats(acc["id"], ok)
            count += 1

            status = "OK" if ok else "ERR"
            color_s = "[" + color + "]" if color else ""
            print("[#" + str(count) + "] " + acc["label"] + " -> " +
                  str(target_id) + color_s + " [" + status + "] " + msg[:60])

        except Exception as e:
            update_stats(acc["id"], False)
            print("[SPAM] Error " + acc["label"] + ": " + str(e))

        # Delay
        risk = acc["risk"] if acc["risk"] else 0.0
        ok_c = acc["ok_count"] if acc["ok_count"] else 0
        actual = AntiBanExpert.compute_delay(delay, risk, ok_c)

        end = time.time() + actual
        while time.time() < end:
            if stop_event.is_set():
                break
            time.sleep(0.05)

        AntiBanExpert.micro_pause()

    conn = db()
    conn.execute(
        "UPDATE tasks SET status = 'stopped', stats = ? WHERE id = ?",
        (json.dumps({"sent": count}), tid)
    )
    conn.commit()
    conn.close()
    ACTIVE_TASKS.pop(tid, None)
    print("[SPAM] Task " + tid + " dừng - Tổng: " + str(count))


# ============================================================
# AUTH + ROUTES
# ============================================================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


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


# ============================================================
# API — ACCOUNTS
# ============================================================
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
    data = request.json
    label = data.get("label", "").strip() or "acc" + str(int(time.time()))
    imei = data.get("imei", "").strip()
    ck_raw = data.get("cookies", "").strip()

    if not imei or not ck_raw:
        return jsonify({"error": "Thiếu IMEI hoặc cookie"}), 400
    try:
        cookies = json.loads(ck_raw)
    except Exception:
        return jsonify({"error": "Cookie không phải JSON"}), 400

    conn = db()
    conn.execute("""
        INSERT INTO accounts (label, imei, cookies, added_at)
        VALUES (?, ?, ?, ?)
    """, (label, imei, json.dumps(cookies), time.time()))
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
    conn.execute(
        "UPDATE accounts SET risk = 0, enabled = 1 WHERE id = ?", (aid,)
    )
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
        cookies = json.loads(row["cookies"])
        z = Zalo(row["imei"], cookies)
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
        cookies = json.loads(row["cookies"])
        z = Zalo(row["imei"], cookies)
        groups = z.get_groups()
        friends = z.get_friends()
        return jsonify({
            "ok": True,
            "groups": groups,
            "friends": friends,
            "total": len(groups) + len(friends),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ============================================================
# API — FILES
# ============================================================
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
        return jsonify({"error": "Tên file trống"}), 400

    filename = f.filename
    safe_name = str(int(time.time())) + "_" + filename
    filepath = os.path.join(UPLOAD_DIR, safe_name)
    f.save(filepath)

    messages = parse_message_file(filepath, max_lines=10000)
    size = os.path.getsize(filepath)

    conn = db()
    conn.execute("""
        INSERT INTO files (filename, filepath, lines, size, uploaded_at)
        VALUES (?, ?, ?, ?, ?)
    """, (filename, filepath, len(messages), size, time.time()))
    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "filename": filename,
        "lines": len(messages),
        "preview": messages[:5],
    })


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
    messages = parse_message_file(row["filepath"], max_lines=10000)
    return jsonify({
        "filename": row["filename"],
        "total": len(messages),
        "preview": messages[:20],
        "all": messages,
    })


# ============================================================
# API — TASKS
# ============================================================
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
    data = request.json
    targets = data.get("targets", [])
    messages = data.get("messages", [])
    delay = float(data.get("delay", 3))
    use_color = bool(data.get("use_color", True))
    use_emoji = bool(data.get("use_emoji", True))
    emoji_count = int(data.get("emoji_count", 10))
    tag_uids = data.get("tag_uids", [])
    mode = data.get("mode", "nhay")  # nhay / ngon

    if not targets:
        return jsonify({"error": "Chưa chọn target"}), 400
    if not messages:
        return jsonify({"error": "Chưa có tin nhắn"}), 400
    if delay < 0.3:
        delay = 0.3
    if emoji_count < 0:
        emoji_count = 0
    if emoji_count > 15:
        emoji_count = 15
    if mode not in ("nhay", "ngon"):
        mode = "nhay"

    conn = db()
    count = conn.execute(
        "SELECT COUNT(*) as c FROM accounts WHERE enabled = 1"
    ).fetchone()["c"]
    conn.close()

    if count == 0:
        return jsonify({"error": "Kho tài khoản trống"}), 400

    tid = new_tid("spam")
    stop_event = threading.Event()
    thread = threading.Thread(
        target=spam_worker,
        args=(tid, targets, messages, delay, use_color, use_emoji,
              emoji_count, tag_uids, mode, stop_event),
        daemon=True,
    )

    conn = db()
    conn.execute("""
        INSERT INTO tasks (id, type, meta, status, started_at, stats)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tid, "spam_" + mode,
          json.dumps({
              "targets": len(targets),
              "messages": len(messages),
              "delay": delay,
              "mode": mode,
          }),
          "running", time.time(), "{}"))
    conn.commit()
    conn.close()

    ACTIVE_TASKS[tid] = {"stop": stop_event, "thread": thread}
    thread.start()

    return jsonify({"ok": True, "task_id": tid, "mode": mode})


@app.route("/api/tasks/<tid>/stop", methods=["POST"])
@login_required
def api_tasks_stop(tid):
    if tid in ACTIVE_TASKS:
        ACTIVE_TASKS[tid]["stop"].set()
        return jsonify({"ok": True})
    return jsonify({"error": "Task không tồn tại"}), 404


@app.route("/api/tasks/stop_all", methods=["POST"])
@login_required
def api_tasks_stop_all():
    for tid, t in list(ACTIVE_TASKS.items()):
        t["stop"].set()
    return jsonify({"ok": True, "count": len(ACTIVE_TASKS)})


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "web-lenh",
        "version": "26.0",
        "tasks": len(ACTIVE_TASKS),
    })


# ============================================================
# LOGO SVG
# ============================================================
LOGO_SVG = """<svg class="logo-svg" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
    <defs>
        <linearGradient id="lg1" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#f093fb"/>
            <stop offset="50%" stop-color="#f5576c"/>
            <stop offset="100%" stop-color="#ee5a6f"/>
        </linearGradient>
    </defs>
    <path d="M50 5 C30 5, 15 20, 15 40 C15 60, 30 75, 50 75 C55 75, 60 74, 64 72 L85 85 L82 65 C90 58, 95 49, 95 40 C95 20, 70 5, 50 5 Z"
          fill="url(#lg1)"/>
    <circle cx="35" cy="40" r="4" fill="white"/>
    <circle cx="50" cy="40" r="4" fill="white"/>
    <circle cx="65" cy="40" r="4" fill="white"/>
    <path d="M30 55 Q50 65 70 55" stroke="white" stroke-width="2.5"
          stroke-linecap="round" fill="none"/>
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
* { margin:0; padding:0; box-sizing:border-box; }
body {
    font-family:'Inter',sans-serif;
    min-height:100vh; display:flex; align-items:center; justify-content:center;
    background:linear-gradient(-45deg,#667eea,#764ba2,#f093fb,#f5576c);
    background-size:400% 400%;
    animation:gradientShift 15s ease infinite;
    padding:20px;
}
@keyframes gradientShift {
    0% { background-position:0% 50%; }
    50% { background-position:100% 50%; }
    100% { background-position:0% 50%; }
}
.card {
    background:white; padding:44px 32px; border-radius:32px;
    box-shadow:0 40px 100px rgba(0,0,0,0.3);
    width:100%; max-width:400px; text-align:center;
    animation:cardIn 0.8s cubic-bezier(0.16,1,0.3,1);
}
@keyframes cardIn {
    from { opacity:0; transform:translateY(50px) scale(0.94); }
    to { opacity:1; transform:translateY(0) scale(1); }
}
.logo-svg { width:100px; height:100px; margin:0 auto 20px; display:block;
    animation:logoFloat 3.5s ease-in-out infinite; }
@keyframes logoFloat {
    0%,100% { transform:translateY(0) rotate(0deg); }
    50% { transform:translateY(-10px) rotate(-3deg); }
}
h1 { color:#1a1a2e; margin-bottom:8px; font-size:26px; font-weight:900; }
p.sub { color:#6b7280; margin-bottom:28px; font-size:13px; }
input {
    width:100%; padding:16px;
    border:2px solid #e5e7eb; border-radius:14px;
    font-size:16px; font-family:inherit; font-weight:500;
    background:#f9fafb; text-align:center;
}
input:focus {
    outline:none; border-color:#667eea; background:white;
    box-shadow:0 0 0 5px rgba(102,126,234,0.12);
}
button {
    width:100%; padding:16px; margin-top:14px;
    background:linear-gradient(135deg,#667eea,#764ba2);
    color:white; border:none; border-radius:14px;
    font-size:16px; font-weight:800; font-family:inherit;
    cursor:pointer; box-shadow:0 12px 30px rgba(102,126,234,0.4);
    transition:all 0.3s;
}
button:hover { transform:translateY(-2px); }
.error {
    background:#fef2f2; color:#dc2626;
    padding:12px 16px; border-radius:12px;
    margin-bottom:18px; font-size:13px; font-weight:600;
    border-left:4px solid #dc2626;
}
</style>
</head>
<body>
<div class="card">
    <div class="logo-svg">""" + LOGO_SVG + """</div>
    <h1>ALB FORGE</h1>
    <p class="sub">Bot by Anh Khôi — v26.0 PRO MAX</p>
    {% if error %}<div class="error">⚠️ {{ error }}</div>{% endif %}
    <form method="POST">
        <input type="password" name="password" placeholder="Mật khẩu" autofocus required>
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
<title>ALB Forge v26</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
body { font-family:'Inter',sans-serif; background:#f8fafc; min-height:100vh; color:#1a1a2e; }

.header {
    background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);
    color:white; padding:16px 20px;
    box-shadow:0 4px 30px rgba(102,126,234,0.35);
    position:sticky; top:0; z-index:100;
    padding-top:calc(16px + env(safe-area-inset-top, 0px));
}
.header-inner {
    max-width:1200px; margin:0 auto;
    display:flex; align-items:center; justify-content:space-between; gap:12px;
}
.logo-mini {
    width:44px; height:44px;
    display:flex; align-items:center; justify-content:center;
    background:rgba(255,255,255,0.15);
    border-radius:14px;
    border:1px solid rgba(255,255,255,0.25);
    padding:8px;
}
.logo-mini svg { width:100%; height:100%; }
.header-info { flex:1; }
.header-info h1 { font-size:18px; font-weight:900; }
.header-info p { font-size:11px; opacity:0.85; margin-top:2px; }
.logout-btn {
    background:rgba(255,255,255,0.15); color:white;
    border:1px solid rgba(255,255,255,0.25);
    padding:10px 16px; border-radius:12px;
    font-size:12px; font-weight:700; font-family:inherit;
    cursor:pointer; transition:all 0.25s;
}
.logout-btn:hover { background:rgba(255,255,255,0.28); }

.container { max-width:1200px; margin:0 auto; padding:16px; }

.tabs {
    display:grid; grid-template-columns:repeat(4,1fr);
    gap:6px; margin-bottom:16px;
    background:white; padding:6px;
    border-radius:18px;
    box-shadow:0 4px 25px rgba(0,0,0,0.05);
}
.tab {
    padding:12px 6px; border-radius:14px;
    cursor:pointer; font-size:11px; font-weight:800;
    text-align:center; color:#6b7280;
    transition:all 0.3s;
    display:flex; flex-direction:column; align-items:center; gap:4px;
}
.tab-icon { font-size:18px; }
.tab.active {
    background:linear-gradient(135deg,#667eea,#764ba2);
    color:white;
    box-shadow:0 8px 20px rgba(102,126,234,0.4);
}

.panel { display:none; animation:fadeIn 0.35s; }
.panel.active { display:block; }
@keyframes fadeIn {
    from { opacity:0; transform:translateY(12px); }
    to { opacity:1; transform:translateY(0); }
}

.card {
    background:white; padding:20px;
    border-radius:22px;
    box-shadow:0 6px 30px rgba(0,0,0,0.05);
    margin-bottom:16px;
    border:1px solid #f0f2f5;
}
.card h2 {
    font-size:15px; font-weight:900;
    margin-bottom:16px;
    display:flex; align-items:center; gap:10px;
}
.card h2 .badge-icon {
    width:32px; height:32px; border-radius:10px;
    background:linear-gradient(135deg,#667eea,#764ba2);
    display:flex; align-items:center; justify-content:center;
    font-size:15px;
}

.form-group { margin-bottom:14px; }
.form-group label {
    display:block; margin-bottom:6px;
    font-size:12px; font-weight:800; color:#374151;
    text-transform:uppercase; letter-spacing:0.5px;
}
.form-group input, .form-group textarea, .form-group select {
    width:100%; padding:12px 14px;
    border:2px solid #e5e7eb; border-radius:14px;
    font-size:14px; font-family:inherit; font-weight:500;
    background:#f9fafb;
}
.form-group input:focus, .form-group textarea:focus, .form-group select:focus {
    outline:none; border-color:#667eea; background:white;
    box-shadow:0 0 0 4px rgba(102,126,234,0.1);
}
.form-group textarea {
    min-height:90px; resize:vertical;
    font-family:monospace; font-size:12px;
}

.btn-circle {
    width:56px; height:56px; border-radius:50%;
    border:none; cursor:pointer;
    display:inline-flex; align-items:center; justify-content:center;
    font-size:22px; color:white;
    transition:all 0.3s cubic-bezier(0.16,1,0.3,1);
    box-shadow:0 10px 25px rgba(0,0,0,0.15);
    position:relative; overflow:hidden;
    margin:4px;
}
.btn-circle::before {
    content:''; position:absolute; inset:0;
    background:linear-gradient(120deg,transparent,rgba(255,255,255,0.4),transparent);
    transform:translateX(-100%);
    transition:transform 0.6s;
}
.btn-circle:hover::before { transform:translateX(100%); }
.btn-circle:hover { transform:translateY(-4px) scale(1.06); }
.btn-circle:active { transform:translateY(-1px) scale(0.98); }

.btn-circle.primary { background:linear-gradient(135deg,#667eea,#764ba2); }
.btn-circle.danger { background:linear-gradient(135deg,#ef4444,#dc2626); }
.btn-circle.success { background:linear-gradient(135deg,#10b981,#059669); }
.btn-circle.warning { background:linear-gradient(135deg,#f59e0b,#d97706); }
.btn-circle.info { background:linear-gradient(135deg,#3b82f6,#2563eb); }
.btn-circle.purple { background:linear-gradient(135deg,#8b5cf6,#7c3aed); }
.btn-circle.pink { background:linear-gradient(135deg,#ec4899,#db2777); }
.btn-circle.small { width:42px; height:42px; font-size:16px; }

.btn-rect {
    padding:12px 20px; border:none;
    border-radius:14px; cursor:pointer;
    font-size:13px; font-weight:800; font-family:inherit;
    color:white;
    transition:all 0.3s;
    box-shadow:0 8px 20px rgba(0,0,0,0.15);
    display:inline-flex; align-items:center; gap:8px;
}
.btn-rect:hover { transform:translateY(-3px); }
.btn-rect.primary { background:linear-gradient(135deg,#667eea,#764ba2); }
.btn-rect.danger { background:linear-gradient(135deg,#ef4444,#dc2626); }
.btn-rect.success { background:linear-gradient(135deg,#10b981,#059669); }
.btn-rect.info { background:linear-gradient(135deg,#3b82f6,#2563eb); }
.btn-rect.purple { background:linear-gradient(135deg,#8b5cf6,#7c3aed); }
.btn-rect.pink { background:linear-gradient(135deg,#ec4899,#db2777); }

.stat-grid {
    display:grid; grid-template-columns:repeat(auto-fit,minmax(110px,1fr));
    gap:10px; margin-bottom:16px;
}
.stat {
    background:linear-gradient(135deg,#f9fafb,#f3f4f6);
    padding:14px; border-radius:16px;
    border:1px solid #e5e7eb;
    position:relative; overflow:hidden;
}
.stat::before {
    content:''; position:absolute; top:0; left:0; right:0; height:4px;
    background:linear-gradient(90deg,#667eea,#764ba2);
}
.stat .label {
    font-size:10px; color:#6b7280;
    margin-bottom:6px; text-transform:uppercase;
    letter-spacing:0.5px; font-weight:800;
}
.stat .value {
    font-size:24px; font-weight:900;
}

.table-wrap { overflow-x:auto; }
.table { width:100%; border-collapse:collapse; }
.table th, .table td {
    padding:10px 8px; text-align:left;
    font-size:12px;
    border-bottom:1px solid #f0f2f5;
    white-space:nowrap;
}
.table th {
    background:#f9fafb; font-weight:800;
    color:#6b7280; text-transform:uppercase;
    font-size:10px;
}
.table td code {
    background:#f3f4f6; padding:3px 8px;
    border-radius:6px; font-size:11px;
    font-family:monospace;
}

.badge {
    display:inline-flex; align-items:center; gap:3px;
    padding:4px 8px; border-radius:20px;
    font-size:10px; font-weight:800;
}
.badge-ok { background:#d1fae5; color:#065f46; }
.badge-err { background:#fee2e2; color:#991b1b; }
.badge-warn { background:#fef3c7; color:#92400e; }
.badge-info { background:#dbeafe; color:#1e40af; }

.box-list {
    max-height:320px; overflow-y:auto;
    border:2px solid #e5e7eb; border-radius:14px;
    padding:8px; background:#f9fafb;
}
.box-item {
    padding:10px; border-radius:10px;
    background:white; margin-bottom:6px;
    cursor:pointer; border:2px solid transparent;
    transition:all 0.2s;
    display:flex; align-items:center; gap:10px;
    font-size:12px;
}
.box-item:hover { border-color:#667eea; }
.box-item.selected { border-color:#10b981; background:#ecfdf5; }
.box-item .check {
    width:18px; height:18px;
    border:2px solid #d1d5db; border-radius:5px;
    display:flex; align-items:center; justify-content:center;
    font-size:10px; color:white; font-weight:900;
    flex-shrink:0;
}
.box-item.selected .check { background:#10b981; border-color:#10b981; }
.box-item .info { flex:1; min-width:0; }
.box-item .name {
    font-weight:700; font-size:12px;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.box-item .meta {
    font-size:10px; color:#6b7280;
    font-family:monospace; margin-top:2px;
}

.file-item {
    display:flex; align-items:center; gap:10px;
    padding:10px; border-radius:12px;
    background:#f9fafb; margin-bottom:8px;
    border:1px solid #e5e7eb;
}
.file-item .info { flex:1; min-width:0; }
.file-item .name {
    font-weight:700; font-size:12px;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.file-item .meta {
    font-size:10px; color:#6b7280; margin-top:2px;
}

.chip-group {
    display:flex; flex-wrap:wrap; gap:6px;
    margin-top:6px;
}
.chip {
    padding:8px 14px;
    background:#f3f4f6; color:#374151;
    border-radius:20px; font-size:12px;
    font-weight:800; cursor:pointer;
    transition:all 0.2s;
    border:2px solid transparent;
}
.chip:hover { background:#e5e7eb; }
.chip.active {
    background:linear-gradient(135deg,#667eea,#764ba2);
    color:white;
    box-shadow:0 4px 15px rgba(102,126,234,0.4);
}
.chip.fast {
    background:#fef3c7; color:#92400e;
}
.chip.fast:hover { background:#fde68a; }
.chip.fast.active {
    background:linear-gradient(135deg,#f59e0b,#d97706);
    color:white;
}

.mode-group {
    display:grid; grid-template-columns:1fr 1fr;
    gap:8px; margin-bottom:14px;
}
.mode-btn {
    padding:16px 12px;
    border:2px solid #e5e7eb;
    border-radius:16px; cursor:pointer;
    text-align:center; background:#f9fafb;
    transition:all 0.25s;
}
.mode-btn:hover { border-color:#667eea; }
.mode-btn.active {
    background:linear-gradient(135deg,#667eea,#764ba2);
    color:white; border-color:transparent;
    box-shadow:0 8px 25px rgba(102,126,234,0.4);
}
.mode-btn .icon { font-size:28px; margin-bottom:6px; }
.mode-btn .title { font-size:14px; font-weight:900; margin-bottom:4px; }
.mode-btn .desc {
    font-size:10px; font-weight:600; opacity:0.7;
    line-height:1.4;
}

.toggle-group {
    display:grid; grid-template-columns:1fr 1fr;
    gap:8px; margin-bottom:14px;
}
.toggle {
    padding:12px; border:2px solid #e5e7eb;
    border-radius:14px; cursor:pointer;
    text-align:center; font-weight:800;
    font-size:12px; background:#f9fafb;
    color:#6b7280;
    transition:all 0.25s;
}
.toggle.active {
    background:linear-gradient(135deg,#667eea,#764ba2);
    color:white; border-color:transparent;
    box-shadow:0 8px 20px rgba(102,126,234,0.4);
}

.alert {
    padding:14px 18px; border-radius:14px;
    margin-bottom:12px; font-size:13px;
    font-weight:700; display:none;
    position:fixed; top:90px; right:16px;
    z-index:999; box-shadow:0 15px 45px rgba(0,0,0,0.2);
    max-width:340px;
}
.alert.show { display:flex; gap:10px; animation:slideIn 0.35s; }
@keyframes slideIn {
    from { opacity:0; transform:translateX(120%); }
    to { opacity:1; transform:translateX(0); }
}
.alert-success {
    background:linear-gradient(135deg,#d1fae5,#a7f3d0);
    color:#065f46; border-left:5px solid #10b981;
}
.alert-error {
    background:linear-gradient(135deg,#fee2e2,#fecaca);
    color:#991b1b; border-left:5px solid #ef4444;
}

@media (max-width:640px) {
    .container { padding:10px; }
    .card { padding:16px; border-radius:18px; }
    .header-info h1 { font-size:15px; }
    .header-info p { font-size:10px; }
    .logo-mini { width:38px; height:38px; }
    .logout-btn { padding:8px 12px; font-size:11px; }
    .tab { padding:10px 4px; font-size:10px; }
    .tab-icon { font-size:16px; }
    .stat .value { font-size:20px; }
    .btn-circle { width:48px; height:48px; font-size:18px; }
    .btn-circle.small { width:38px; height:38px; font-size:14px; }
    .alert { left:12px; right:12px; max-width:none; }
}
</style>
</head>
<body>

<div class="header">
    <div class="header-inner">
        <div class="logo-mini">""" + LOGO_SVG + """</div>
        <div class="header-info">
            <h1>ALB FORGE</h1>
            <p>Bot by Anh Khôi • v26.0 PRO MAX</p>
        </div>
        <button class="logout-btn" onclick="location.href='/logout'">🚪 Thoát</button>
    </div>
</div>

<div class="container">

<div class="tabs">
    <div class="tab active" data-tab="accounts">
        <div class="tab-icon">🔐</div>
        <div>Tài khoản</div>
    </div>
    <div class="tab" data-tab="boxes">
        <div class="tab-icon">📦</div>
        <div>Box</div>
    </div>
    <div class="tab" data-tab="files">
        <div class="tab-icon">📁</div>
        <div>File</div>
    </div>
    <div class="tab" data-tab="spam">
        <div class="tab-icon">🎯</div>
        <div>Spam</div>
    </div>
</div>

<div id="alert" class="alert"></div>

<!-- TAB ACCOUNTS -->
<div class="panel active" id="panel-accounts">
    <div class="card">
        <h2><span class="badge-icon">➕</span> Thêm tài khoản</h2>
        <div class="form-group">
            <label>Tên gợi nhớ</label>
            <input id="add-label" placeholder="acc1">
        </div>
        <div class="form-group">
            <label>IMEI</label>
            <input id="add-imei" placeholder="000000000000000">
        </div>
        <div class="form-group">
            <label>Cookie (JSON)</label>
            <textarea id="add-cookies" placeholder='{"zpw_sek":"...","zpw_ver":"645","zpw_type":"30"}'></textarea>
        </div>
        <button class="btn-rect primary" onclick="addAccount()">💾 Thêm tài khoản</button>
    </div>

    <div class="card">
        <h2><span class="badge-icon">📋</span> Danh sách</h2>
        <div class="stat-grid">
            <div class="stat"><div class="label">Tổng</div><div class="value" id="stat-total">0</div></div>
            <div class="stat"><div class="label">Active</div><div class="value" id="stat-active">0</div></div>
            <div class="stat"><div class="label">Đã gửi</div><div class="value" id="stat-sent">0</div></div>
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

<!-- TAB BOXES -->
<div class="panel" id="panel-boxes">
    <div class="card">
        <h2><span class="badge-icon">📦</span> Load Box</h2>
        <div class="form-group">
            <label>Chọn tài khoản</label>
            <select id="load-acc-select">
                <option value="">-- Chọn --</option>
            </select>
        </div>
        <div style="text-align:center;">
            <button class="btn-circle primary" onclick="loadBoxes()" title="Load">🔄</button>
            <button class="btn-circle success" onclick="selectAllBoxes()" title="Chọn hết">✅</button>
            <button class="btn-circle danger" onclick="clearAllBoxes()" title="Bỏ chọn">❌</button>
        </div>
        <div style="margin-top:14px;">
            <div style="margin-bottom:8px;font-size:12px;">
                <b>Đã chọn: <span id="selected-count" style="color:#667eea;">0</span></b>
            </div>
            <div class="box-list" id="box-list">
                <div style="text-align:center;padding:24px;color:#999;font-size:12px;">Chưa load box</div>
            </div>
        </div>
    </div>
</div>

<!-- TAB FILES -->
<div class="panel" id="panel-files">
    <div class="card">
        <h2><span class="badge-icon">📤</span> Upload file</h2>
        <div class="form-group">
            <input type="file" id="file-input" accept=".txt" style="padding:8px;">
        </div>
        <button class="btn-rect primary" onclick="uploadFile()">📤 Upload</button>
    </div>

    <div class="card">
        <h2><span class="badge-icon">📁</span> Quản lý file</h2>
        <div id="files-list">
            <div style="text-align:center;padding:24px;color:#999;font-size:12px;">Chưa có file</div>
        </div>
    </div>
</div>

<!-- TAB SPAM -->
<div class="panel" id="panel-spam">

    <div class="card">
        <h2><span class="badge-icon">⚡</span> Chế độ spam</h2>
        <div class="mode-group">
            <div class="mode-btn active" data-mode="nhay" onclick="selectMode('nhay')">
                <div class="icon">🌀</div>
                <div class="title">TREO NHÂY</div>
                <div class="desc">Gửi theo số thứ tự<br>random, không trùng</div>
            </div>
            <div class="mode-btn" data-mode="ngon" onclick="selectMode('ngon')">
                <div class="icon">📢</div>
                <div class="title">TREO NGÔN</div>
                <div class="desc">Gửi y chang<br>không đổi nội dung</div>
            </div>
        </div>
        <input type="hidden" id="spam-mode" value="nhay">
    </div>

    <div class="card">
        <h2><span class="badge-icon">🎯</span> Cấu hình</h2>

        <div class="form-group">
            <label>Chọn file tin nhắn</label>
            <select id="spam-file-select">
                <option value="">-- Chọn file --</option>
            </select>
        </div>

        <div class="form-group">
            <label>Hoặc nhập tin (cách nhau dấu ;)</label>
            <textarea id="spam-messages" placeholder="Tin 1;Tin 2;Tin 3"></textarea>
        </div>

        <div class="form-group">
            <label>⚡ Delay giữa các tin</label>
            <div class="chip-group" id="delay-chips">
                <div class="chip fast" data-delay="0.3">0.3s 🚀</div>
                <div class="chip fast" data-delay="0.5">0.5s 🚀</div>
                <div class="chip fast" data-delay="1">1s ⚡</div>
                <div class="chip active" data-delay="3">3s</div>
                <div class="chip" data-delay="5">5s</div>
                <div class="chip" data-delay="10">10s</div>
                <div class="chip" data-delay="30">30s</div>
                <div class="chip" data-delay="60">60s</div>
            </div>
            <input type="hidden" id="spam-delay" value="3">
        </div>

        <div class="form-group">
            <label>Số emoji cuối câu</label>
            <div class="chip-group" id="emoji-chips">
                <div class="chip" data-emoji="0">0</div>
                <div class="chip" data-emoji="3">3</div>
                <div class="chip" data-emoji="5">5</div>
                <div class="chip active" data-emoji="10">10</div>
                <div class="chip" data-emoji="15">15</div>
            </div>
            <input type="hidden" id="emoji-count" value="10">
        </div>

        <div class="toggle-group">
            <div class="toggle active" id="toggle-color" onclick="toggleFlag('color')">
                🎨 Đổi màu chữ
            </div>
            <div class="toggle active" id="toggle-emoji" onclick="toggleFlag('emoji')">
                😊 Thêm emoji
            </div>
        </div>

        <div class="form-group">
            <label>
                <input type="checkbox" id="toggle-tag" onchange="toggleTag()" style="width:auto;margin-right:8px;">
                Tag UID trong tin
            </label>
            <div id="tag-input-wrap" style="display:none;margin-top:8px;">
                <input id="tag-uids" placeholder="UID1,UID2,... (cách nhau dấu phẩy)">
            </div>
        </div>

        <div style="text-align:center;margin-top:20px;">
            <button class="btn-circle success" onclick="startSpam()" title="Bắt đầu" style="width:80px;height:80px;font-size:32px;">▶️</button>
            <button class="btn-circle danger" onclick="stopAll()" title="Dừng" style="width:80px;height:80px;font-size:32px;">⏸️</button>
        </div>
    </div>

    <div class="card" style="background:linear-gradient(135deg,#fef3c7,#fde68a);border:2px solid #fbbf24;">
        <h2 style="color:#92400e;"><span class="badge-icon" style="background:#92400e;">🛡️</span> Anti-Ban v26</h2>
        <div style="color:#78350f;font-size:12px;line-height:1.9;font-weight:600;">
            ✅ Adaptive delay theo risk<br>
            ✅ Zero-width entropy mask (8 loại)<br>
            ✅ 12 màu Zalo ngẫu nhiên<br>
            ✅ 10 emoji cuối câu<br>
            ✅ Account + Target rotation<br>
            ✅ Warmup 2 tin đầu<br>
            ✅ Dedup 5 tin gần nhất<br>
            ✅ Micro-pause human-like<br>
            ✅ Risk score + auto disable
        </div>
    </div>

    <div class="card">
        <h2><span class="badge-icon">📋</span> Tác vụ</h2>
        <button class="btn-circle danger small" onclick="stopAll()">⏸️</button>
        <div class="table-wrap" style="margin-top:12px;">
            <table class="table">
                <thead><tr>
                    <th>ID</th><th>Chế độ</th><th>Trạng thái</th><th></th>
                </tr></thead>
                <tbody id="tasks-tbody"></tbody>
            </table>
        </div>
    </div>
</div>

</div>

<script>
let flags = { color: true, emoji: true };
let selectedBoxes = [];
let currentMode = 'nhay';

document.querySelectorAll('.tab').forEach(t => {
    t.onclick = () => {
        document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
        document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
        t.classList.add('active');
        document.getElementById('panel-' + t.dataset.tab).classList.add('active');
        refreshAll();
    };
});

function selectMode(mode) {
    currentMode = mode;
    document.querySelectorAll('.mode-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === mode);
    });
    document.getElementById('spam-mode').value = mode;
}

document.querySelectorAll('#delay-chips .chip').forEach(c => {
    c.onclick = () => {
        document.querySelectorAll('#delay-chips .chip').forEach(x => x.classList.remove('active'));
        c.classList.add('active');
        document.getElementById('spam-delay').value = c.dataset.delay;
    };
});

document.querySelectorAll('#emoji-chips .chip').forEach(c => {
    c.onclick = () => {
        document.querySelectorAll('#emoji-chips .chip').forEach(x => x.classList.remove('active'));
        c.classList.add('active');
        document.getElementById('emoji-count').value = c.dataset.emoji;
    };
});

function showAlert(msg, type) {
    type = type || 'success';
    const a = document.getElementById('alert');
    a.innerHTML = (type === 'success' ? '✅ ' : '⚠️ ') + msg;
    a.className = 'alert show alert-' + type;
    setTimeout(() => a.classList.remove('show'), 4000);
}

async function api(url, opts) {
    opts = opts || {};
    const r = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    return r.json();
}

function toggleFlag(name) {
    flags[name] = !flags[name];
    document.getElementById('toggle-' + name).classList.toggle('active', flags[name]);
}

function toggleTag() {
    const checked = document.getElementById('toggle-tag').checked;
    document.getElementById('tag-input-wrap').style.display = checked ? 'block' : 'none';
}

async function loadAccounts() {
    const accounts = await api('/api/accounts');
    const tbody = document.getElementById('accounts-tbody');
    if (!accounts.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#999;padding:24px;">Chưa có</td></tr>';
    } else {
        tbody.innerHTML = accounts.map(a => {
            const risk = (a.risk || 0).toFixed(2);
            const riskCls = risk > 0.5 ? 'badge-err' : risk > 0.2 ? 'badge-warn' : 'badge-ok';
            return '<tr>' +
                '<td>' + a.id + '</td>' +
                '<td><b>' + a.label + '</b></td>' +
                '<td><span class="badge badge-ok">' + a.ok_count + '</span> <span class="badge badge-err">' + a.fail_count + '</span></td>' +
                '<td><span class="badge ' + riskCls + '">' + risk + '</span></td>' +
                '<td><span class="badge badge-info">' + (a.total_sent || 0) + '</span></td>' +
                '<td>' +
                    '<button class="btn-circle primary small" onclick="checkAcc(' + a.id + ')" title="Check">🔍</button>' +
                    '<button class="btn-circle warning small" onclick="resetAcc(' + a.id + ')" title="Reset">🔄</button>' +
                    '<button class="btn-circle danger small" onclick="delAcc(' + a.id + ')" title="Xóa">🗑️</button>' +
                '</td>' +
            '</tr>';
        }).join('');
    }
    document.getElementById('stat-total').textContent = accounts.length;
    document.getElementById('stat-active').textContent = accounts.filter(a => a.enabled).length;
    document.getElementById('stat-sent').textContent = accounts.reduce((s, a) => s + (a.total_sent || 0), 0);

    const sel1 = document.getElementById('load-acc-select');
    const v1 = sel1.value;
    sel1.innerHTML = '<option value="">-- Chọn --</option>' +
        accounts.map(a => '<option value="' + a.id + '">' + a.label + ' (ID: ' + a.id + ')</option>').join('');
    sel1.value = v1;
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
    if (!confirm('Xóa tài khoản này?')) return;
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
    if (!aid) return showAlert('Chọn tài khoản', 'error');
    showAlert('Đang load...');
    const r = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
    if (r.error) return showAlert(r.error, 'error');

    const all = [...(r.groups || []), ...(r.friends || [])];
    const boxList = document.getElementById('box-list');
    if (!all.length) {
        boxList.innerHTML = '<div style="text-align:center;padding:24px;color:#999;">Không có</div>';
        return;
    }
    boxList.innerHTML = all.map((b, i) =>
        '<div class="box-item" data-idx="' + i + '" onclick="toggleBox(this, ' + i + ')">' +
            '<div class="check">✓</div>' +
            '<div class="info">' +
                '<div class="name">' + b.name + '</div>' +
                '<div class="meta">' + b.id + ' | ' + b.type + '</div>' +
            '</div>' +
        '</div>'
    ).join('');

    window._allBoxes = all;
    selectedBoxes = [];
    document.getElementById('selected-count').textContent = '0';
    showAlert('Đã load ' + all.length + ' box');
}

function toggleBox(el, idx) {
    const box = window._allBoxes[idx];
    const isSel = el.classList.contains('selected');
    if (isSel) {
        el.classList.remove('selected');
        selectedBoxes = selectedBoxes.filter(b => b.id !== box.id);
    } else {
        el.classList.add('selected');
        selectedBoxes.push(box);
    }
    document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function selectAllBoxes() {
    document.querySelectorAll('.box-item').forEach(el => el.classList.add('selected'));
    selectedBoxes = [...(window._allBoxes || [])];
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
    showAlert('Đã upload ' + r.filename + ' (' + r.lines + ' dòng)');
    input.value = '';
    loadFiles();
}

async function loadFiles() {
    const files = await api('/api/files');
    const list = document.getElementById('files-list');
    if (!files.length) {
        list.innerHTML = '<div style="text-align:center;padding:24px;color:#999;font-size:12px;">Chưa có file</div>';
    } else {
        list.innerHTML = files.map(f => {
            const size = (f.size / 1024).toFixed(1);
            return '<div class="file-item">' +
                '<div class="info">' +
                    '<div class="name">📄 ' + f.filename + '</div>' +
                    '<div class="meta">' + f.lines + ' dòng • ' + size + ' KB</div>' +
                '</div>' +
                '<button class="btn-circle info small" onclick="previewFile(' + f.id + ')" title="Xem">👁️</button>' +
                '<button class="btn-circle danger small" onclick="delFile(' + f.id + ')" title="Xóa">🗑️</button>' +
            '</div>';
        }).join('');
    }
    const sel = document.getElementById('spam-file-select');
    sel.innerHTML = '<option value="">-- Chọn file --</option>' +
        files.map(f => '<option value="' + f.id + '">' + f.filename + ' (' + f.lines + ' dòng)</option>').join('');
}

async function previewFile(fid) {
    const r = await api('/api/files/' + fid + '/preview');
    if (r.error) return showAlert(r.error, 'error');
    const preview = r.preview.map((m, i) => (i + 1) + '. ' + m).join('\\n');
    alert('File: ' + r.filename + '\\nTổng: ' + r.total + ' dòng\\n\\n' + preview);
}

async function delFile(fid) {
    if (!confirm('Xóa file này?')) return;
    await api('/api/files/' + fid, { method: 'DELETE' });
    showAlert('Đã xóa');
    loadFiles();
}

async function startSpam() {
    if (!selectedBoxes.length) return showAlert('Chưa chọn box', 'error');

    const fileId = document.getElementById('spam-file-select').value;
    const directMsgs = document.getElementById('spam-messages').value.trim();
    let messages = [];

    if (fileId) {
        const r = await api('/api/files/' + fileId + '/preview');
        if (r.error) return showAlert('Lỗi file: ' + r.error, 'error');
        messages = r.all || r.preview || [];
    } else if (directMsgs) {
        messages = directMsgs.split(';').map(m => m.trim()).filter(m => m);
    }

    if (!messages.length) return showAlert('Chưa có tin nhắn', 'error');

    const delay = parseFloat(document.getElementById('spam-delay').value) || 3;
    const emojiCount = parseInt(document.getElementById('emoji-count').value) || 10;
    const tagInput = document.getElementById('tag-uids').value.trim();
    const tagUids = tagInput ? tagInput.split(',').map(t => t.trim()).filter(t => t) : [];
    const mode = document.getElementById('spam-mode').value;

    const r = await api('/api/tasks/start', {
        method: 'POST',
        body: JSON.stringify({
            targets: selectedBoxes,
            messages: messages,
            delay: delay,
            use_color: flags.color,
            use_emoji: flags.emoji,
            emoji_count: emojiCount,
            tag_uids: tagUids,
            mode: mode,
        }),
    });
    if (r.error) return showAlert(r.error, 'error');
    showAlert('🚀 Đã bắt đầu [' + r.mode.toUpperCase() + ']: ' + r.task_id);
    loadTasks();
}

async function stopAll() {
    await api('/api/tasks/stop_all', { method: 'POST' });
    showAlert('Đã dừng');
    loadTasks();
}

async function loadTasks() {
    const tasks = await api('/api/tasks');
    const tbody = document.getElementById('tasks-tbody');
    if (!tasks.length) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#999;padding:20px;">Chưa có</td></tr>';
        return;
    }
    tbody.innerHTML = tasks.map(t => {
        const badge = t.status === 'running' ? 'badge-ok' : 'badge-err';
        const text = t.status === 'running' ? 'Chạy' : 'Dừng';
        const mode = t.type === 'spam_nhay' ? '🌀 Nhây' : (t.type === 'spam_ngon' ? '📢 Ngôn' : t.type);
        return '<tr>' +
            '<td><code>' + t.id + '</code></td>' +
            '<td>' + mode + '</td>' +
            '<td><span class="badge ' + badge + '">' + text + '</span></td>' +
            '<td>' + (t.status === 'running' ? '<button class="btn-circle danger small" onclick="stopTask(\\'' + t.id + '\\')">⏸️</button>' : '') + '</td>' +
        '</tr>';
    }).join('');
}

async function stopTask(tid) {
    await api('/api/tasks/' + tid + '/stop', { method: 'POST' });
    loadTasks();
}

function refreshAll() {
    loadAccounts();
    loadFiles();
    loadTasks();
}

setInterval(() => { loadTasks(); }, 5000);
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
