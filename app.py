# ============================================================
# WEB-LENH v25.0 — Dashboard + Spam Anti-Ban Elite
# Bot by Anh Khôi
# Giao diện gọn - Nút tròn - Logo SVG - Icon Zalo
# ============================================================
import os
import json
import time
import sqlite3
import threading
import random
import base64
import string
import hashlib
import re

from functools import wraps
from datetime import datetime

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
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "alb.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "alb-lenh-2026-secret")
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB


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
# ZALO COLORS — mã màu Zalo hỗ trợ (msgColor API)
# ============================================================
ZALO_COLOR_CODES = [
    "red", "orange", "yellow", "green", "teal",
    "blue", "purple", "pink"
]


# ============================================================
# ZALO ICONS — emoji text Zalo
# ============================================================
ZALO_ICONS = [
    ":)", ":/", ":D", ";)", ";-*", ":-*", ":P", ":p",
    ":3", "8-)", "b-)", ">-)", "=))", ":))",
    ":-h", ":-H", ":-?", ":-O", ":o", ":v", ":>",
    ";;)", ":|", ":x", ":-L", "$-)", "8*)",
    ":-bye", ">-|",
    "/-beer", "/-coffee", "/-rose", "/-bd", "/-cake",
    "/-heart", "/-break", "/-shit", "/-li", "/-flag",
    "/-strong", "/-thanks", "/-punch", "/-share",
    "/-no", "/-bad", "/-loveu",
    "_()_",
]


def wrap_icon(text):
    """Chèn icon Zalo vào cuối text — chỉ 1 icon, không spam."""
    if random.random() < 0.5:
        return text + " " + random.choice(ZALO_ICONS)
    return text


def vary_text(text):
    """
    Biến đổi text nhẹ (KHÔNG chèn ký tự lạ liên tục).
    Chỉ: thêm dấu câu cuối, hoa/thường, cắt ngắn.
    """
    r = random.random()

    # Thêm dấu câu cuối (30%)
    if r < 0.3:
        text = text + random.choice(["", ".", "!", "?", "...", "~"])

    # Hoa/thường (15%)
    if random.random() < 0.15:
        mode = random.random()
        if mode < 0.5:
            text = text[0].upper() + text[1:] if text else text
        else:
            text = text.lower()

    # Đôi khi thêm từ filler (10%)
    if random.random() < 0.1:
        fillers = ["nha", "nhé", "đó", "vậy", "nè", "hén"]
        text = text + " " + random.choice(fillers)

    return text


# ============================================================
# ANTI-BAN ELITE v25 — Chuyên sâu
# ============================================================
class AntiBanElite:
    """
    Anti-ban cấp chuyên gia:
    1. Rotate account (không dùng 1 acc liên tiếp)
    2. Adaptive delay theo risk score
    3. Typing simulation (giả lập gõ)
    4. Random break (nghỉ ngắn)
    5. Humanize message (icon + biến thể)
    6. Message fingerprint (mỗi tin khác nhau)
    7. Multi-tier circuit (không dừng hẳn, chỉ chậm lại)
    8. Color rotation (màu chữ thay đổi mỗi tin)
    9. Risk-based skip (bỏ qua acc risk cao)
    """

    MIN_DELAY = 0.5
    MAX_DELAY = 30.0

    @staticmethod
    def compute_risk(ok, fail):
        total = ok + fail
        if total == 0:
            return 0.0
        return min(1.0, fail / total)

    @staticmethod
    def compute_delay(user_delay, risk):
        """Delay điều chỉnh theo risk — không bao giờ dừng hẳn."""
        if risk > 0.8:
            base = max(user_delay, 8)
        elif risk > 0.6:
            base = max(user_delay, 5)
        elif risk > 0.4:
            base = max(user_delay, 3)
        else:
            base = max(user_delay, 0.5)

        actual = base * random.uniform(0.7, 1.4)
        return min(AntiBanElite.MAX_DELAY, actual)

    @staticmethod
    def typing_time(text):
        """Thời gian gõ theo độ dài."""
        if not text:
            return 0.3
        return min(5.0, len(text) * random.uniform(0.03, 0.08))

    @staticmethod
    def maybe_break():
        """Random nghỉ ngắn như người thật."""
        r = random.random()
        if r < 0.03:
            time.sleep(random.uniform(5, 15))
        elif r < 0.08:
            time.sleep(random.uniform(1, 3))


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

    # ---- LOAD BOX ----
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

    def friends(self):
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
            return [{"id": u.get("userId"),
                     "name": u.get("zaloName", "?"),
                     "type": "user"} for u in users]
        except Exception:
            return []

    # ---- SEND ----
    def send(self, msg, thread_id, color=None, is_group=True):
        url = ("https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
               if is_group
               else "https://tt-chat2-wpa.chat.zalo.me/api/message/sms")
        pl = {"message": msg,
              "clientId": str(int(time.time() * 1000)),
              "imei": self.imei}
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
# FILE PARSER — Fast (streaming)
# ============================================================
def parse_file_fast(filepath):
    """Parse file nhanh — đọc 1 lần, bỏ số thứ tự."""
    messages = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    continue
                line = re.sub(r"^\d+[\.\)\-\:]\s*", "", line)
                if line:
                    messages.append(line)
    except Exception as e:
        print("[FILE] parse error: " + str(e))
    return messages


# ============================================================
# SPAM WORKER
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
    risk = AntiBanElite.compute_risk(ok_c, fail_c)
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
        WHERE enabled = 1 AND risk < 0.8
        ORDER BY risk ASC, last_used ASC
        LIMIT 1
    """).fetchall()
    conn.close()
    return rows[0] if rows else None


def spam_worker(tid, targets, messages, delay, use_color, use_icon,
                tag_name, stop_event):
    """
    Spam worker v25:
    - Rotate acc
    - Rotate target
    - Đổi màu chữ mỗi tin
    - Chèn icon cuối tin
    - Tag tên nếu có
    """
    msg_idx = 0
    target_idx = 0
    count = 0
    last_acc_id = None

    print("[SPAM] Task " + tid + " started")
    print("  Targets: " + str(len(targets)))
    print("  Messages: " + str(len(messages)))
    print("  Delay: " + str(delay) + "s")
    print("  Color: " + str(use_color))
    print("  Icon: " + str(use_icon))
    print("  Tag: " + str(tag_name))

    while not stop_event.is_set():
        acc = pick_account()
        if not acc:
            time.sleep(1)
            continue

        if acc["id"] == last_acc_id:
            conn = db()
            cnt = conn.execute(
                "SELECT COUNT(*) as c FROM accounts WHERE enabled = 1"
            ).fetchone()["c"]
            conn.close()
            if cnt > 1:
                time.sleep(0.2)
                continue
        last_acc_id = acc["id"]

        target = targets[target_idx % len(targets)]
        target_idx += 1
        raw_msg = messages[msg_idx % len(messages)]
        msg_idx += 1

        # ==== BIẾN ĐỔI TIN NHẮN ====
        final = raw_msg

        # Tag tên ở đầu (nếu có)
        if tag_name:
            final = "@" + tag_name + " " + final

        # Biến thể text
        final = vary_text(final)

        # Chèn icon cuối
        if use_icon:
            final = wrap_icon(final)

        # Màu ngẫu nhiên
        color = None
        if use_color:
            color = random.choice(ZALO_COLOR_CODES)

        is_group = target.get("type") == "group"
        target_id = target.get("id")

        try:
            cookies = json.loads(acc["cookies"])
            z = Zalo(acc["imei"], cookies)

            # Behavior
            time.sleep(random.uniform(0.3, 1.0))
            z.set_typing(target_id, is_group=is_group)
            time.sleep(AntiBanElite.typing_time(final))

            r = z.send(final, target_id, color=color, is_group=is_group)
            ok = bool(r and r.status_code == 200)

            update_stats(acc["id"], ok)
            count += 1

            status = "OK" if ok else "LOI"
            color_str = "[" + str(color) + "]" if color else ""
            print("[SPAM #" + str(count) + "] " + acc["label"] +
                  " -> " + str(target_id) + color_str +
                  " [" + status + "] " + final[:40])

        except Exception as e:
            update_stats(acc["id"], False)
            print("[SPAM] Error " + acc["label"] + ": " + str(e))

        # Delay
        risk = acc["risk"] if acc["risk"] else 0.0
        actual_delay = AntiBanElite.compute_delay(delay, risk)

        end = time.time() + actual_delay
        while time.time() < end:
            if stop_event.is_set():
                break
            time.sleep(0.1)

        AntiBanElite.maybe_break()

    conn = db()
    conn.execute(
        "UPDATE tasks SET status = 'stopped', stats = ? WHERE id = ?",
        (json.dumps({"sent": count}), tid)
    )
    conn.commit()
    conn.close()
    ACTIVE_TASKS.pop(tid, None)
    print("[SPAM] Task " + tid + " stopped - Total: " + str(count))


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
    label = data.get("label", "").strip() or ("acc" + str(int(time.time())))
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


# ============================================================
# API — LOAD BOXES
# ============================================================
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
        groups = z.groups()
        friends = z.friends()
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

    # Parse nhanh
    messages = parse_file_fast(filepath)
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
    messages = parse_file_fast(row["filepath"])
    return jsonify({
        "filename": row["filename"],
        "total": len(messages),
        "preview": messages[:20],
    })


@app.route("/api/files/<int:fid>/content", methods=["GET"])
@login_required
def api_files_content(fid):
    """Trả về toàn bộ nội dung file — cho spam worker."""
    conn = db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Không tìm thấy"}), 404
    messages = parse_file_fast(row["filepath"])
    return jsonify({
        "filename": row["filename"],
        "total": len(messages),
        "messages": messages,
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
    file_id = data.get("file_id")
    messages = data.get("messages", [])
    delay = float(data.get("delay", 3))
    use_color = bool(data.get("use_color", True))
    use_icon = bool(data.get("use_icon", True))
    tag_name = data.get("tag_name", "").strip()

    # Nếu có file_id → load messages từ file
    if file_id:
        conn = db()
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        conn.close()
        if row:
            messages = parse_file_fast(row["filepath"])

    if not targets:
        return jsonify({"error": "Chưa chọn target"}), 400
    if not messages:
        return jsonify({"error": "Chưa có tin nhắn"}), 400
    if delay < 0.5:
        delay = 0.5

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
        args=(tid, targets, messages, delay, use_color, use_icon,
              tag_name, stop_event),
        daemon=True,
    )

    conn = db()
    conn.execute("""
        INSERT INTO tasks (id, type, meta, status, started_at, stats)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tid, "spam",
          json.dumps({
              "targets": len(targets),
              "messages": len(messages),
              "delay": delay,
          }),
          "running", time.time(), "{}"))
    conn.commit()
    conn.close()

    ACTIVE_TASKS[tid] = {"stop": stop_event, "thread": thread}
    thread.start()

    return jsonify({"ok": True, "task_id": tid})


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
        "version": "25.0",
        "tasks": len(ACTIVE_TASKS),
    })


# ============================================================
# HTML — LOGIN
# ============================================================
HTML_LOGIN = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Đăng nhập — ALB Forge</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
body {
    font-family:'Inter',sans-serif;
    min-height:100vh; min-height:100dvh;
    display:flex; align-items:center; justify-content:center;
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
    background:rgba(255,255,255,0.98);
    backdrop-filter:blur(20px);
    padding:44px 36px; border-radius:32px;
    box-shadow:0 40px 100px rgba(0,0,0,0.35);
    width:100%; max-width:400px;
    text-align:center;
    animation:cardIn 0.8s cubic-bezier(0.16,1,0.3,1);
}
@keyframes cardIn {
    from { opacity:0; transform:translateY(50px) scale(0.95); }
    to { opacity:1; transform:translateY(0) scale(1); }
}
.logo-svg {
    width:100px; height:100px;
    margin:0 auto 24px;
    display:block;
}
h1 {
    color:#1a1a2e; margin-bottom:8px;
    font-size:24px; font-weight:900;
}
p.sub { color:#6b7280; margin-bottom:28px; font-size:14px; font-weight:600; }
input {
    width:100%; padding:16px 18px;
    border:2px solid #e5e7eb; border-radius:16px;
    font-size:16px; font-family:inherit; font-weight:600;
    transition:all 0.3s; background:#f9fafb;
    margin-bottom:16px;
}
input:focus {
    outline:none; border-color:#667eea; background:white;
    box-shadow:0 0 0 5px rgba(102,126,234,0.12);
}
.btn-login {
    width:100%; padding:16px;
    background:linear-gradient(135deg,#667eea,#764ba2);
    color:white; border:none; border-radius:16px;
    font-size:16px; font-weight:900; font-family:inherit;
    cursor:pointer; box-shadow:0 15px 35px rgba(102,126,234,0.5);
    transition:all 0.3s;
}
.btn-login:hover { transform:translateY(-3px); box-shadow:0 20px 45px rgba(102,126,234,0.6); }
.error {
    background:#fef2f2; color:#dc2626;
    padding:14px; border-radius:12px; margin-bottom:20px;
    font-size:14px; font-weight:700;
    border-left:4px solid #dc2626;
}
</style>
</head>
<body>
<div class="card">
    <!-- LOGO SVG DESIGN -->
    <svg class="logo-svg" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="g1" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#667eea"/>
                <stop offset="100%" style="stop-color:#f5576c"/>
            </linearGradient>
            <linearGradient id="g2" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#f093fb"/>
                <stop offset="100%" style="stop-color:#667eea"/>
            </linearGradient>
        </defs>
        <!-- Halo phía sau -->
        <circle cx="50" cy="50" r="45" fill="url(#g2)" opacity="0.15"/>
        <!-- Vòng ngoài xoay -->
        <circle cx="50" cy="50" r="42" fill="none" stroke="url(#g1)" stroke-width="2" stroke-dasharray="20 10">
            <animateTransform attributeName="transform" type="rotate" from="0 50 50" to="360 50 50" dur="8s" repeatCount="indefinite"/>
        </circle>
        <!-- Vòng giữa -->
        <circle cx="50" cy="50" r="34" fill="none" stroke="url(#g2)" stroke-width="1.5" stroke-dasharray="10 8">
            <animateTransform attributeName="transform" type="rotate" from="360 50 50" to="0 50 50" dur="6s" repeatCount="indefinite"/>
        </circle>
        <!-- Center box -->
        <rect x="25" y="25" width="50" height="50" rx="14" fill="url(#g1)"/>
        <!-- Icon phone -->
        <path d="M 38 42 Q 38 38 42 38 L 45 38 Q 48 38 48 41 L 48 44 Q 48 46 46 47 Q 48 52 53 54 Q 54 52 56 52 L 59 52 Q 62 52 62 55 L 62 58 Q 62 62 58 62 Q 42 62 38 46 Z"
              fill="white"/>
        <!-- Ánh sáng lấp lánh -->
        <circle cx="30" cy="35" r="1.5" fill="white" opacity="0.9">
            <animate attributeName="opacity" values="0.9;0.2;0.9" dur="2s" repeatCount="indefinite"/>
        </circle>
        <circle cx="70" cy="45" r="1" fill="white" opacity="0.7">
            <animate attributeName="opacity" values="0.7;0.1;0.7" dur="3s" repeatCount="indefinite"/>
        </circle>
        <circle cx="35" cy="70" r="1.2" fill="white" opacity="0.8">
            <animate attributeName="opacity" values="0.8;0.15;0.8" dur="2.5s" repeatCount="indefinite"/>
        </circle>
    </svg>
    <h1>ALB FORGE</h1>
    <p class="sub">Bot by Anh Khôi</p>
    {% if error %}<div class="error">⚠️ {{ error }}</div>{% endif %}
    <form method="POST">
        <input type="password" name="password" placeholder="Nhập mật khẩu" autofocus required>
        <button class="btn-login" type="submit">Đăng nhập</button>
    </form>
</div>
</body>
</html>
"""


# ============================================================
# HTML — MAIN
# ============================================================
HTML_INDEX = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>ALB Forge</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html { touch-action:manipulation; }
body {
    font-family:'Inter',sans-serif;
    background:linear-gradient(-45deg,#f0f4ff,#f8fafc,#fef3f7,#f0f4ff);
    background-size:400% 400%;
    animation:bgShift 20s ease infinite;
    min-height:100vh;
    color:#1a1a2e;
}
@keyframes bgShift {
    0% { background-position:0% 50%; }
    50% { background-position:100% 50%; }
    100% { background-position:0% 50%; }
}

/* HEADER */
.header {
    background:linear-gradient(135deg,#667eea 0%,#764ba2 50%,#f5576c 100%);
    background-size:200% 200%;
    animation:headerShift 8s ease infinite;
    color:white;
    padding:14px 20px;
    position:sticky; top:0; z-index:100;
    padding-top:calc(14px + env(safe-area-inset-top, 0px));
    box-shadow:0 4px 25px rgba(102,126,234,0.35);
}
@keyframes headerShift {
    0%,100% { background-position:0% 50%; }
    50% { background-position:100% 50%; }
}
.header-inner {
    max-width:1100px; margin:0 auto;
    display:flex; align-items:center; justify-content:space-between; gap:12px;
}
.brand { display:flex; align-items:center; gap:10px; }
.brand-logo {
    width:40px; height:40px;
    filter:drop-shadow(0 4px 10px rgba(0,0,0,0.2));
}
.brand-text h1 { font-size:16px; font-weight:900; letter-spacing:-0.3px; }
.brand-text p { font-size:11px; opacity:0.9; margin-top:1px; }
.btn-logout {
    width:40px; height:40px;
    border-radius:50%;
    background:rgba(255,255,255,0.18);
    border:1px solid rgba(255,255,255,0.3);
    color:white; cursor:pointer;
    display:flex; align-items:center; justify-content:center;
    transition:all 0.3s;
}
.btn-logout:hover { background:rgba(255,255,255,0.3); transform:rotate(90deg); }

.container { max-width:1100px; margin:0 auto; padding:14px; }

/* TABS */
.tabs {
    display:grid; grid-template-columns:repeat(4, 1fr); gap:6px;
    margin-bottom:14px;
    background:white; padding:6px;
    border-radius:16px;
    box-shadow:0 4px 20px rgba(0,0,0,0.05);
}
.tab {
    padding:12px 6px;
    border-radius:12px;
    cursor:pointer;
    font-size:11px; font-weight:800;
    color:#6b7280;
    text-align:center;
    display:flex; flex-direction:column; align-items:center; gap:4px;
    transition:all 0.3s cubic-bezier(0.16,1,0.3,1);
    user-select:none;
}
.tab svg { width:20px; height:20px; }
.tab:hover { background:#f9fafb; color:#667eea; }
.tab.active {
    background:linear-gradient(135deg,#667eea,#764ba2);
    color:white;
    box-shadow:0 6px 18px rgba(102,126,234,0.4);
    transform:translateY(-2px);
}

.panel { display:none; animation:fadeIn 0.4s; }
.panel.active { display:block; }
@keyframes fadeIn {
    from { opacity:0; transform:translateY(10px); }
    to { opacity:1; transform:translateY(0); }
}

/* CARD */
.card {
    background:white;
    padding:20px;
    border-radius:20px;
    box-shadow:0 4px 25px rgba(0,0,0,0.06);
    margin-bottom:14px;
    border:1px solid #f0f2f5;
}
.card h2 {
    font-size:15px; font-weight:900;
    margin-bottom:14px;
    display:flex; align-items:center; gap:8px;
    color:#1a1a2e;
}
.card h2 svg { width:18px; height:18px; color:#667eea; }

/* FORM */
.form-row { margin-bottom:12px; }
.form-row label {
    display:block; margin-bottom:6px;
    font-size:11px; font-weight:800; color:#6b7280;
    text-transform:uppercase; letter-spacing:0.5px;
}
.form-row input,
.form-row textarea {
    width:100%;
    padding:12px 14px;
    border:2px solid #e5e7eb;
    border-radius:12px;
    font-size:14px; font-family:inherit; font-weight:600;
    transition:all 0.3s;
    background:#f9fafb;
    color:#1a1a2e;
}
.form-row input:focus,
.form-row textarea:focus {
    outline:none; border-color:#667eea; background:white;
    box-shadow:0 0 0 4px rgba(102,126,234,0.1);
}
.form-row textarea {
    min-height:80px; resize:vertical;
    font-family:monospace; font-size:12px;
}

/* BUTTONS */
.btn {
    padding:12px 20px;
    border:none; border-radius:12px;
    font-size:13px; font-weight:900;
    font-family:inherit; cursor:pointer;
    display:inline-flex; align-items:center; justify-content:center;
    gap:6px;
    transition:all 0.3s cubic-bezier(0.16,1,0.3,1);
    position:relative; overflow:hidden;
    color:white;
}
.btn::after {
    content:''; position:absolute; inset:0;
    background:linear-gradient(120deg,transparent,rgba(255,255,255,0.4),transparent);
    transform:translateX(-100%);
    transition:transform 0.6s;
}
.btn:hover::after { transform:translateX(100%); }
.btn:hover { transform:translateY(-2px); }
.btn:active { transform:translateY(0) scale(0.98); }
.btn:disabled { opacity:0.6; cursor:not-allowed; }

.btn-primary { background:linear-gradient(135deg,#667eea,#764ba2); box-shadow:0 8px 20px rgba(102,126,234,0.35); }
.btn-success { background:linear-gradient(135deg,#10b981,#059669); box-shadow:0 8px 20px rgba(16,185,129,0.35); }
.btn-danger  { background:linear-gradient(135deg,#ef4444,#dc2626); box-shadow:0 8px 20px rgba(239,68,68,0.35); }
.btn-warning { background:linear-gradient(135deg,#f59e0b,#d97706); box-shadow:0 8px 20px rgba(245,158,11,0.35); }

.btn-block { width:100%; margin-bottom:8px; }

/* CIRCLE BUTTONS */
.btn-circle {
    width:44px; height:44px;
    border-radius:50%;
    border:none;
    display:inline-flex; align-items:center; justify-content:center;
    cursor:pointer;
    transition:all 0.3s cubic-bezier(0.16,1,0.3,1);
    color:white;
    position:relative;
    overflow:hidden;
}
.btn-circle::after {
    content:''; position:absolute; inset:0;
    background:linear-gradient(120deg,transparent,rgba(255,255,255,0.5),transparent);
    transform:translateX(-100%) rotate(45deg);
    transition:transform 0.6s;
}
.btn-circle:hover::after { transform:translateX(100%) rotate(45deg); }
.btn-circle:hover { transform:translateY(-3px) scale(1.05); }
.btn-circle:active { transform:translateY(0) scale(0.95); }
.btn-circle svg { width:20px; height:20px; }
.btn-circle.sm { width:36px; height:36px; }
.btn-circle.sm svg { width:16px; height:16px; }

.btn-circle.purple { background:linear-gradient(135deg,#8b5cf6,#7c3aed); box-shadow:0 6px 15px rgba(139,92,246,0.4); }
.btn-circle.blue   { background:linear-gradient(135deg,#3b82f6,#2563eb); box-shadow:0 6px 15px rgba(59,130,246,0.4); }
.btn-circle.green  { background:linear-gradient(135deg,#10b981,#059669); box-shadow:0 6px 15px rgba(16,185,129,0.4); }
.btn-circle.red    { background:linear-gradient(135deg,#ef4444,#dc2626); box-shadow:0 6px 15px rgba(239,68,68,0.4); }
.btn-circle.orange { background:linear-gradient(135deg,#f59e0b,#d97706); box-shadow:0 6px 15px rgba(245,158,11,0.4); }
.btn-circle.pink   { background:linear-gradient(135deg,#f093fb,#f5576c); box-shadow:0 6px 15px rgba(245,87,108,0.4); }

/* STATS */
.stats {
    display:grid;
    grid-template-columns:repeat(3, 1fr);
    gap:8px;
    margin-bottom:14px;
}
.stat {
    background:linear-gradient(135deg,#f9fafb,#f3f4f6);
    padding:12px 10px;
    border-radius:14px;
    text-align:center;
    border:1px solid #e5e7eb;
    position:relative;
    overflow:hidden;
}
.stat::before {
    content:'';
    position:absolute; top:0; left:0; right:0; height:3px;
    background:linear-gradient(90deg,#667eea,#764ba2,#f5576c);
}
.stat .label {
    font-size:10px; color:#6b7280;
    font-weight:800; text-transform:uppercase;
    letter-spacing:0.3px; margin-bottom:4px;
}
.stat .value {
    font-size:22px; font-weight:900; color:#1a1a2e;
    line-height:1;
}

/* TABLE */
.table-wrap { overflow-x:auto; margin:0 -4px; }
.table { width:100%; border-collapse:separate; border-spacing:0; }
.table th, .table td {
    padding:10px 8px;
    text-align:left;
    font-size:12px;
    border-bottom:1px solid #f0f2f5;
    white-space:nowrap;
}
.table th {
    background:#f9fafb;
    font-weight:900; color:#6b7280;
    font-size:10px; text-transform:uppercase;
    letter-spacing:0.3px;
}
.table th:first-child { border-radius:10px 0 0 10px; }
.table th:last-child { border-radius:0 10px 10px 0; }
.table tr:hover td { background:#f9fafb; }

.badge {
    display:inline-block;
    padding:3px 8px;
    border-radius:20px;
    font-size:10px; font-weight:800;
}
.badge-ok { background:#d1fae5; color:#065f46; }
.badge-err { background:#fee2e2; color:#991b1b; }
.badge-warn { background:#fef3c7; color:#92400e; }
.badge-info { background:#dbeafe; color:#1e40af; }

/* TOGGLE */
.toggle-row {
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:8px;
    margin-bottom:12px;
}
.toggle {
    padding:12px 8px;
    border:2px solid #e5e7eb;
    border-radius:12px;
    cursor:pointer;
    text-align:center;
    font-size:12px; font-weight:800;
    color:#6b7280;
    background:#f9fafb;
    user-select:none;
    transition:all 0.3s;
    display:flex; align-items:center; justify-content:center; gap:6px;
}
.toggle svg { width:16px; height:16px; }
.toggle.active {
    background:linear-gradient(135deg,#667eea,#764ba2);
    color:white;
    border-color:transparent;
    box-shadow:0 6px 15px rgba(102,126,234,0.35);
}

/* DELAY PICKER */
.delay-grid {
    display:grid;
    grid-template-columns:repeat(5, 1fr);
    gap:6px;
    margin-bottom:12px;
}
.delay-item {
    padding:10px 4px;
    border:2px solid #e5e7eb;
    border-radius:10px;
    text-align:center;
    font-size:12px; font-weight:900;
    cursor:pointer;
    background:#f9fafb;
    color:#6b7280;
    transition:all 0.3s;
    user-select:none;
}
.delay-item:hover { border-color:#667eea; color:#667eea; }
.delay-item.active {
    background:linear-gradient(135deg,#667eea,#764ba2);
    color:white;
    border-color:transparent;
    box-shadow:0 6px 15px rgba(102,126,234,0.35);
}

/* BOX LIST */
.box-list {
    max-height:320px;
    overflow-y:auto;
    border:2px solid #e5e7eb;
    border-radius:14px;
    padding:8px;
    background:#f9fafb;
}
.box-item {
    padding:10px 12px;
    border-radius:10px;
    background:white;
    margin-bottom:6px;
    cursor:pointer;
    display:flex; align-items:center; gap:10px;
    border:2px solid transparent;
    transition:all 0.2s;
}
.box-item:hover { border-color:#667eea; }
.box-item.selected {
    border-color:#10b981;
    background:linear-gradient(135deg,#ecfdf5,#d1fae5);
}
.box-check {
    width:20px; height:20px;
    border:2px solid #d1d5db;
    border-radius:6px;
    display:flex; align-items:center; justify-content:center;
    flex-shrink:0;
    color:white;
    font-size:12px; font-weight:900;
}
.box-item.selected .box-check {
    background:#10b981; border-color:#10b981;
}
.box-info { flex:1; min-width:0; }
.box-name {
    font-size:13px; font-weight:800;
    color:#1a1a2e;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.box-id {
    font-size:10px; color:#6b7280;
    font-family:monospace;
    margin-top:2px;
}
.box-type {
    padding:2px 8px;
    border-radius:6px;
    font-size:9px; font-weight:900;
}
.type-group { background:#dbeafe; color:#1e40af; }
.type-user  { background:#fce7f3; color:#9d174d; }

/* FILE ITEM */
.file-item {
    display:flex; align-items:center; gap:10px;
    padding:12px;
    border-radius:12px;
    background:#f9fafb;
    margin-bottom:8px;
    border:1px solid #e5e7eb;
}
.file-info { flex:1; min-width:0; }
.file-name {
    font-size:13px; font-weight:800;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.file-meta {
    font-size:11px; color:#6b7280;
    margin-top:2px;
}

/* ALERT */
.alert {
    padding:14px 18px;
    border-radius:12px;
    font-size:13px; font-weight:800;
    display:none;
    position:fixed;
    top:80px; right:16px;
    z-index:999;
    box-shadow:0 15px 40px rgba(0,0,0,0.2);
    max-width:340px;
    animation:slideIn 0.4s cubic-bezier(0.16,1,0.3,1);
}
@keyframes slideIn {
    from { opacity:0; transform:translateX(120%); }
    to { opacity:1; transform:translateX(0); }
}
.alert.show { display:flex; align-items:center; gap:8px; }
.alert-success { background:linear-gradient(135deg,#d1fae5,#a7f3d0); color:#065f46; border-left:4px solid #10b981; }
.alert-error { background:linear-gradient(135deg,#fee2e2,#fecaca); color:#991b1b; border-left:4px solid #ef4444; }

/* EMPTY */
.empty {
    text-align:center;
    padding:36px 20px;
    color:#9ca3af;
    font-size:13px; font-weight:600;
}
.empty svg { width:48px; height:48px; opacity:0.4; margin-bottom:8px; }

/* RESPONSIVE */
@media (max-width:640px) {
    .container { padding:10px; }
    .card { padding:16px; border-radius:18px; }
    .brand-text h1 { font-size:14px; }
    .brand-text p { font-size:10px; }
    .brand-logo { width:36px; height:36px; }
    .btn-logout { width:36px; height:36px; }
    .tabs { gap:4px; padding:4px; }
    .tab { padding:10px 4px; font-size:10px; border-radius:10px; }
    .tab svg { width:18px; height:18px; }
    .stat .value { font-size:20px; }
    .table th, .table td { padding:8px 6px; font-size:11px; }
    .btn { padding:10px 16px; font-size:12px; }
    .delay-grid { grid-template-columns:repeat(4, 1fr); }
    .alert { left:12px; right:12px; max-width:none; }
}
</style>
</head>
<body>

<div class="header">
    <div class="header-inner">
        <div class="brand">
            <svg class="brand-logo" viewBox="0 0 100 100">
                <defs>
                    <linearGradient id="hg" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" style="stop-color:#ffffff"/>
                        <stop offset="100%" style="stop-color:#f0f4ff"/>
                    </linearGradient>
                </defs>
                <circle cx="50" cy="50" r="45" fill="rgba(255,255,255,0.15)"/>
                <rect x="25" y="25" width="50" height="50" rx="14" fill="url(#hg)"/>
                <path d="M 38 42 Q 38 38 42 38 L 45 38 Q 48 38 48 41 L 48 44 Q 48 46 46 47 Q 48 52 53 54 Q 54 52 56 52 L 59 52 Q 62 52 62 55 L 62 58 Q 62 62 58 62 Q 42 62 38 46 Z"
                      fill="#667eea"/>
            </svg>
            <div class="brand-text">
                <h1>ALB FORGE</h1>
                <p>v25 • by Anh Khôi</p>
            </div>
        </div>
        <button class="btn-logout" onclick="location.href='/logout'" title="Thoát">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="18" height="18">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
                <polyline points="16 17 21 12 16 7"/>
                <line x1="21" y1="12" x2="9" y2="12"/>
            </svg>
        </button>
    </div>
</div>

<div class="container">

<div class="tabs">
    <div class="tab active" data-tab="accounts">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
            <circle cx="12" cy="7" r="4"/>
        </svg>
        <div>Acc</div>
    </div>
    <div class="tab" data-tab="boxes">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
            <polyline points="3.27 6.96 12 12.01 20.73 6.96"/>
            <line x1="12" y1="22.08" x2="12" y2="12"/>
        </svg>
        <div>Box</div>
    </div>
    <div class="tab" data-tab="files">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>
            <polyline points="13 2 13 9 20 9"/>
        </svg>
        <div>File</div>
    </div>
    <div class="tab" data-tab="spam">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
        </svg>
        <div>Spam</div>
    </div>
</div>

<div id="alert" class="alert"></div>

<!-- TAB ACCOUNTS -->
<div class="panel active" id="panel-accounts">
    <div class="card">
        <h2>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="5" x2="12" y2="19"/>
                <line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            Thêm tài khoản
        </h2>
        <div class="form-row">
            <label>Tên gợi nhớ</label>
            <input id="add-label" placeholder="acc1">
        </div>
        <div class="form-row">
            <label>IMEI</label>
            <input id="add-imei" placeholder="000000000000000">
        </div>
        <div class="form-row">
            <label>Cookie (JSON)</label>
            <textarea id="add-cookies" placeholder='{"zpw_sek":"...","zpw_ver":"645"}'></textarea>
        </div>
        <button class="btn btn-primary btn-block" onclick="addAccount()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16">
                <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                <polyline points="17 21 17 13 7 13 7 21"/>
                <polyline points="7 3 7 8 15 8"/>
            </svg>
            Thêm tài khoản
        </button>
    </div>

    <div class="card">
        <h2>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="8" y1="6" x2="21" y2="6"/>
                <line x1="8" y1="12" x2="21" y2="12"/>
                <line x1="8" y1="18" x2="21" y2="18"/>
                <line x1="3" y1="6" x2="3.01" y2="6"/>
                <line x1="3" y1="12" x2="3.01" y2="12"/>
                <line x1="3" y1="18" x2="3.01" y2="18"/>
            </svg>
            Danh sách tài khoản
        </h2>
        <div class="stats">
            <div class="stat">
                <div class="label">Tổng</div>
                <div class="value" id="stat-total">0</div>
            </div>
            <div class="stat">
                <div class="label">Active</div>
                <div class="value" id="stat-active">0</div>
            </div>
            <div class="stat">
                <div class="label">Đã gửi</div>
                <div class="value" id="stat-sent">0</div>
            </div>
        </div>
        <div class="table-wrap">
            <table class="table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Tên</th>
                        <th>OK/Lỗi</th>
                        <th>Risk</th>
                        <th>Sent</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody id="accounts-tbody"></tbody>
            </table>
        </div>
    </div>
</div>

<!-- TAB BOXES -->
<div class="panel" id="panel-boxes">
    <div class="card">
        <h2>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
            </svg>
            Load Box & Chat
        </h2>
        <div class="form-row">
            <label>Chọn tài khoản</label>
            <select id="load-acc-select" style="width:100%; padding:12px; border:2px solid #e5e7eb; border-radius:12px; font-family:inherit; font-weight:600; background:#f9fafb; font-size:14px;">
                <option value="">-- Chọn acc --</option>
            </select>
        </div>
        <button class="btn btn-primary btn-block" onclick="loadBoxes()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16">
                <polyline points="23 4 23 10 17 10"/>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
            </svg>
            Load Box
        </button>
        <div style="display:flex; gap:6px; margin-bottom:12px;">
            <button class="btn btn-success btn-block" onclick="selectAllBoxes()">Chọn hết</button>
            <button class="btn btn-danger btn-block" onclick="clearAllBoxes()">Bỏ chọn</button>
        </div>

        <div style="font-size:12px; font-weight:800; margin-bottom:8px; color:#6b7280;">
            Đã chọn: <span id="selected-count" style="color:#667eea; font-size:14px;">0</span> box
        </div>

        <div class="box-list" id="box-list">
            <div class="empty">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
                </svg>
                <div>Chưa load box</div>
            </div>
        </div>
    </div>
</div>

<!-- TAB FILES -->
<div class="panel" id="panel-files">
    <div class="card">
        <h2>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="17 8 12 3 7 8"/>
                <line x1="12" y1="3" x2="12" y2="15"/>
            </svg>
            Upload file tin nhắn
        </h2>
        <div class="form-row">
            <input type="file" id="file-input" accept=".txt" style="padding:10px; background:white;">
        </div>
        <button class="btn btn-primary btn-block" onclick="uploadFile()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16">
                <polyline points="16 16 12 12 8 16"/>
                <line x1="12" y1="12" x2="12" y2="21"/>
                <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/>
            </svg>
            Upload
        </button>
    </div>

    <div class="card">
        <h2>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
            </svg>
            Quản lý file
        </h2>
        <div id="files-list">
            <div class="empty">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>
                    <polyline points="13 2 13 9 20 9"/>
                </svg>
                <div>Chưa có file</div>
            </div>
        </div>
    </div>
</div>

<!-- TAB SPAM -->
<div class="panel" id="panel-spam">
    <div class="card">
        <h2>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
            </svg>
            Cấu hình spam
        </h2>

        <div class="form-row">
            <label>Chọn file tin nhắn</label>
            <select id="spam-file-select" style="width:100%; padding:12px; border:2px solid #e5e7eb; border-radius:12px; font-family:inherit; font-weight:600; background:#f9fafb; font-size:14px;">
                <option value="">-- Chọn file --</option>
            </select>
        </div>

        <div class="form-row">
            <label>Hoặc nhập tin (cách nhau bằng ;)</label>
            <textarea id="spam-messages" placeholder="Chào;Hello;Hi"></textarea>
        </div>

        <div class="form-row">
            <label>Tag tên (tùy chọn)</label>
            <input id="spam-tag" placeholder="Tên người cần tag">
        </div>

        <div class="form-row">
            <label>Delay giữa các tin</label>
            <div class="delay-grid" id="delay-grid">
                <div class="delay-item" data-delay="0.5">0.5s</div>
                <div class="delay-item" data-delay="1">1s</div>
                <div class="delay-item" data-delay="2">2s</div>
                <div class="delay-item active" data-delay="3">3s</div>
                <div class="delay-item" data-delay="5">5s</div>
                <div class="delay-item" data-delay="10">10s</div>
                <div class="delay-item" data-delay="20">20s</div>
                <div class="delay-item" data-delay="30">30s</div>
                <div class="delay-item" data-delay="60">60s</div>
                <div class="delay-item" data-delay="120">2m</div>
            </div>
        </div>

        <div class="toggle-row">
            <div class="toggle active" id="toggle-color" onclick="toggleFlag('color')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="13.5" cy="6.5" r="2.5"/>
                    <circle cx="17.5" cy="10.5" r="2.5"/>
                    <circle cx="8.5" cy="7.5" r="2.5"/>
                    <circle cx="6.5" cy="12.5" r="2.5"/>
                    <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.9 0 1.8-.1 2.7-.3"/>
                </svg>
                Đổi màu
            </div>
            <div class="toggle active" id="toggle-icon" onclick="toggleFlag('icon')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10"/>
                    <path d="M8 14s1.5 2 4 2 4-2 4-2"/>
                    <line x1="9" y1="9" x2="9.01" y2="9"/>
                    <line x1="15" y1="9" x2="15.01" y2="9"/>
                </svg>
                Icon Zalo
            </div>
        </div>

        <button class="btn btn-success btn-block" onclick="startSpam()" style="font-size:15px; padding:16px;">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="18" height="18">
                <polygon points="5 3 19 12 5 21 5 3" fill="currentColor"/>
            </svg>
            BẮT ĐẦU SPAM
        </button>
        <button class="btn btn-danger btn-block" onclick="stopAll()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16">
                <rect x="6" y="6" width="12" height="12"/>
            </svg>
            DỪNG TẤT CẢ
        </button>
    </div>

    <div class="card">
        <h2>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
            Tác vụ đang chạy
        </h2>
        <div class="table-wrap">
            <table class="table">
                <thead>
                    <tr><th>ID</th><th>Status</th><th></th></tr>
                </thead>
                <tbody id="tasks-tbody">
                    <tr><td colspan="3" class="empty" style="padding:20px;">Chưa có</td></tr>
                </tbody>
            </table>
        </div>
    </div>
</div>

</div>

<script>
let flags = { color: true, icon: true };
let selectedBoxes = [];
let selectedDelay = 3;

// TABS
document.querySelectorAll('.tab').forEach(t => {
    t.onclick = () => {
        document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
        document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
        t.classList.add('active');
        document.getElementById('panel-' + t.dataset.tab).classList.add('active');
        if (t.dataset.tab === 'accounts') loadAccounts();
        if (t.dataset.tab === 'files') loadFiles();
        if (t.dataset.tab === 'spam') loadTasks();
    };
});

// DELAY PICKER
document.querySelectorAll('.delay-item').forEach(d => {
    d.onclick = () => {
        document.querySelectorAll('.delay-item').forEach(x => x.classList.remove('active'));
        d.classList.add('active');
        selectedDelay = parseFloat(d.dataset.delay);
    };
});

function showAlert(msg, type) {
    type = type || 'success';
    const a = document.getElementById('alert');
    a.textContent = (type === 'success' ? '✅ ' : '⚠️ ') + msg;
    a.className = 'alert show alert-' + type;
    setTimeout(() => a.classList.remove('show'), 4000);
}

async function api(url, opts) {
    opts = opts || {};
    const r = await fetch(url, Object.assign({
        headers: { 'Content-Type': 'application/json' },
    }, opts));
    return r.json();
}

function toggleFlag(name) {
    flags[name] = !flags[name];
    document.getElementById('toggle-' + name).classList.toggle('active', flags[name]);
}

// ACCOUNTS
async function loadAccounts() {
    const accounts = await api('/api/accounts');
    const tbody = document.getElementById('accounts-tbody');
    if (!accounts.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty">Chưa có tài khoản</td></tr>';
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
                    '<button class="btn-circle sm green" onclick="checkAcc(' + a.id + ')" title="Check">' +
                        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>' +
                    '</button> ' +
                    '<button class="btn-circle sm blue" onclick="resetAcc(' + a.id + ')" title="Reset">' +
                        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>' +
                    '</button> ' +
                    '<button class="btn-circle sm red" onclick="delAcc(' + a.id + ')" title="Xóa">' +
                        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>' +
                    '</button>' +
                '</td>' +
            '</tr>';
        }).join('');
    }
    document.getElementById('stat-total').textContent = accounts.length;
    document.getElementById('stat-active').textContent = accounts.filter(a => a.enabled).length;
    document.getElementById('stat-sent').textContent = accounts.reduce((s, a) => s + (a.total_sent || 0), 0);

    const sel = document.getElementById('load-acc-select');
    const cur = sel.value;
    sel.innerHTML = '<option value="">-- Chọn acc --</option>' +
        accounts.map(a => '<option value="' + a.id + '">' + a.label + ' (#' + a.id + ')</option>').join('');
    sel.value = cur;
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
    loadAccounts();
}

async function delAcc(id) {
    if (!confirm('Xóa acc này?')) return;
    await api('/api/accounts/' + id, { method: 'DELETE' });
    showAlert('Đã xóa');
    loadAccounts();
}

async function resetAcc(id) {
    await api('/api/accounts/' + id + '/reset', { method: 'POST' });
    showAlert('Đã reset');
    loadAccounts();
}

async function checkAcc(id) {
    const r = await api('/api/accounts/' + id + '/check', { method: 'POST' });
    if (r.error) return showAlert(r.error, 'error');
    showAlert('UID: ' + r.uid);
}

// BOXES
async function loadBoxes() {
    const aid = document.getElementById('load-acc-select').value;
    if (!aid) return showAlert('Chọn acc', 'error');
    showAlert('Đang load box...');
    const r = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
    if (r.error) return showAlert(r.error, 'error');

    const all = (r.groups || []).concat(r.friends || []);
    const boxList = document.getElementById('box-list');
    if (!all.length) {
        boxList.innerHTML = '<div class="empty"><div>Không có box</div></div>';
        return;
    }
    boxList.innerHTML = all.map((b, i) => {
        const typeCls = b.type === 'group' ? 'type-group' : 'type-user';
        const typeLabel = b.type === 'group' ? '👥 Nhóm' : '👤 Chat';
        return '<div class="box-item" data-idx="' + i + '" onclick="toggleBox(this, ' + i + ')">' +
            '<div class="box-check">✓</div>' +
            '<div class="box-info">' +
                '<div class="box-name">' + b.name + '</div>' +
                '<div class="box-id">ID: ' + b.id + '</div>' +
            '</div>' +
            '<span class="box-type ' + typeCls + '">' + typeLabel + '</span>' +
        '</div>';
    }).join('');

    window._allBoxes = all;
    selectedBoxes = [];
    document.getElementById('selected-count').textContent = '0';
    showAlert('Load ' + all.length + ' box (' + r.groups.length + ' nhóm, ' + r.friends.length + ' chat)');
}

function toggleBox(el, idx) {
    const box = window._allBoxes[idx];
    if (el.classList.contains('selected')) {
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
    selectedBoxes = [].concat(window._allBoxes || []);
    document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function clearAllBoxes() {
    document.querySelectorAll('.box-item').forEach(el => el.classList.remove('selected'));
    selectedBoxes = [];
    document.getElementById('selected-count').textContent = '0';
}

// FILES
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
        list.innerHTML = '<div class="empty"><div>Chưa có file</div></div>';
    } else {
        list.innerHTML = files.map(f => {
            const size = (f.size / 1024).toFixed(1);
            const date = new Date(f.uploaded_at * 1000).toLocaleString('vi-VN');
            return '<div class="file-item">' +
                '<div class="file-info">' +
                    '<div class="file-name">📄 ' + f.filename + '</div>' +
                    '<div class="file-meta">' + f.lines + ' dòng • ' + size + ' KB • ' + date + '</div>' +
                '</div>' +
                '<button class="btn-circle sm blue" onclick="previewFile(' + f.id + ')" title="Xem">' +
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>' +
                '</button>' +
                '<button class="btn-circle sm red" onclick="delFile(' + f.id + ')" title="Xóa">' +
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>' +
                '</button>' +
            '</div>';
        }).join('');
    }

    const sel = document.getElementById('spam-file-select');
    const cur = sel.value;
    sel.innerHTML = '<option value="">-- Chọn file --</option>' +
        files.map(f => '<option value="' + f.id + '">' + f.filename + ' (' + f.lines + ' dòng)</option>').join('');
    sel.value = cur;
}

async function previewFile(fid) {
    const r = await api('/api/files/' + fid + '/preview');
    if (r.error) return showAlert(r.error, 'error');
    const preview = r.preview.map((m, i) => (i + 1) + '. ' + m).join('\\n');
    alert('File: ' + r.filename + '\\nTổng: ' + r.total + ' dòng\\n\\nPreview:\\n' + preview);
}

async function delFile(fid) {
    if (!confirm('Xóa file?')) return;
    await api('/api/files/' + fid, { method: 'DELETE' });
    showAlert('Đã xóa');
    loadFiles();
}

// SPAM
async function startSpam() {
    if (!selectedBoxes.length) return showAlert('Chưa chọn box', 'error');

    const fileId = document.getElementById('spam-file-select').value;
    const directMsgs = document.getElementById('spam-messages').value.trim();
    const tagName = document.getElementById('spam-tag').value.trim();

    let messages = [];
    if (!fileId && directMsgs) {
        messages = directMsgs.split(';').map(m => m.trim()).filter(m => m);
    }

    if (!fileId && !messages.length) {
        return showAlert('Chọn file hoặc nhập tin', 'error');
    }

    const r = await api('/api/tasks/start', {
        method: 'POST',
        body: JSON.stringify({
            targets: selectedBoxes,
            file_id: fileId ? parseInt(fileId) : null,
            messages: messages,
            delay: selectedDelay,
            use_color: flags.color,
            use_icon: flags.icon,
            tag_name: tagName,
        }),
    });
    if (r.error) return showAlert(r.error, 'error');
    showAlert('Đã bắt đầu spam: ' + r.task_id);
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
        tbody.innerHTML = '<tr><td colspan="3" class="empty">Chưa có</td></tr>';
        return;
    }
    tbody.innerHTML = tasks.map(t => {
        const cls = t.status === 'running' ? 'badge-ok' : 'badge-err';
        const label = t.status === 'running' ? 'Đang chạy' : 'Đã dừng';
        return '<tr>' +
            '<td><code style="font-size:10px;">' + t.id + '</code></td>' +
            '<td><span class="badge ' + cls + '">' + label + '</span></td>' +
            '<td>' + (t.status === 'running' ?
                '<button class="btn-circle sm red" onclick="stopTask(\\'' + t.id + '\\')">' +
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="6" y="6" width="12" height="12"/></svg>' +
                '</button>' : '') + '</td>' +
        '</tr>';
    }).join('');
}

async function stopTask(tid) {
    await api('/api/tasks/' + tid + '/stop', { method: 'POST' });
    showAlert('Đã dừng');
    loadTasks();
}

setInterval(() => {
    const active = document.querySelector('.panel.active');
    if (!active) return;
    if (active.id === 'panel-accounts') loadAccounts();
    if (active.id === 'panel-spam') loadTasks();
}, 5000);

loadAccounts();
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
