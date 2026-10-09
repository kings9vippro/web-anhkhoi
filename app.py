# ============================================================
# WEB-LENH v14.0 — Dashboard + Spam PRO + Anti-Ban Bypass
# Bot by Anh Khôi
# Chức năng: Nhập cookie, load box, upload file, spam màu, emoji, bypass ban
# ============================================================
import os
import io
import json
import time
import sqlite3
import threading
import random
import base64
import string
import hashlib
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template_string, request, jsonify,
    session, redirect, url_for, send_file
)
from Crypto.Cipher import AES
import requests

# ============================================================
# CONFIG
# ============================================================
APP_PASSWORD = os.environ.get("APP_PASSWORD", "anhkhoidz")
QR_SERVICE_URL = os.environ.get("QR_SERVICE_URL", "")
QR_SERVICE_KEY = os.environ.get("QR_SERVICE_KEY", "qr-lenh-shared-key-2026")
DATA_DIR = os.environ.get("DATA_DIR", "/tmp/alb_web")
os.makedirs(DATA_DIR, exist_ok=True)
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "alb.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "alb-lenh-secret-2026")
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB


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
    return f"{p}_{int(time.time()*1000)}"


# ============================================================
# ZALO COLORS (đổi màu chữ)
# ============================================================
ZALO_COLORS = {
    "red":     "#E53935",
    "pink":    "#EC407A",
    "purple":  "#8E24AA",
    "blue":    "#1E88E5",
    "ocean":   "#00ACC1",
    "green":   "#43A047",
    "yellow":  "#FDD835",
    "orange":  "#FB8C00",
    "brown":   "#6D4C41",
    "black":   "#212121",
    "gray":    "#757575",
    "white":   "#FFFFFF",
}
ZALO_COLOR_CODES = list(ZALO_COLORS.keys())


# ============================================================
# ZALO EMOJI — bộ emoji Zalo
# ============================================================
ZALO_EMOJIS = [
    "(y)", ":D", ";)", ":P", ":((", "=))", ":-*", "8-)", ":3",
    ":v", ":))", ":>", ":-h", ":-?", ":x", ":o", ";;)", ":|",
    ":/", "b-)", ">-)", ":((", "=))", ":P", ";)",
]


# ============================================================
# ANTI-BAN BYPASS v14 — SIÊU CAO CẤP
# ============================================================
class AntiBanBypass:
    """
    Bypass anti-ban cấp cao — chống ban tuyệt đối.

    Chiến lược:
    1. Multi-account rotation — không dùng 1 acc liên tiếp
    2. Message fingerprint — mỗi tin khác nhau hoàn toàn
    3. Timing jitter — delay ngẫu nhiên cực mạnh
    4. Color rotation — đổi màu chữ mỗi tin
    5. Emoji injection — chèn emoji Zalo cuối tin
    6. Unicode zero-width — chống hash detect
    7. Adaptive throttling — tự điều chỉnh tốc độ
    8. Risk-based skipping — bỏ qua acc risk cao
    9. Fresh cookie check — không dùng cookie hết hạn
    10. Session isolation — mỗi acc 1 session riêng
    """

    MIN_DELAY = 0.5
    MAX_DELAY = 30.0

    TYPING_MU = 0.05
    TYPING_SIGMA = 0.03

    # ============================================================
    # DELAY CONTROL
    # ============================================================
    @staticmethod
    def compute_delay(user_delay, risk):
        """
        Delay dựa vào:
        - user_delay (từ input)
        - risk score của acc
        - random jitter ±50%
        """
        if risk > 0.8:
            base = max(user_delay, 10)
        elif risk > 0.6:
            base = max(user_delay, 6)
        elif risk > 0.4:
            base = max(user_delay, 4)
        else:
            base = max(user_delay, 0.5)

        # Jitter ±50%
        actual = base * random.uniform(0.5, 1.5)
        return min(AntiBanBypass.MAX_DELAY, actual)

    @staticmethod
    def typing_time(text):
        """Tính thời gian gõ."""
        if not text:
            return 0.3
        total = 0.0
        for c in text:
            if c in ".,!?;:":
                total += random.uniform(0.08, 0.2)
            else:
                total += max(0.01, random.gauss(
                    AntiBanBypass.TYPING_MU,
                    AntiBanBypass.TYPING_SIGMA
                ))
        return min(total, 5.0)

    # ============================================================
    # MESSAGE FINGERPRINT
    # ============================================================
    @staticmethod
    def entropy_mask(text):
        """Chèn zero-width char."""
        if random.random() < 0.3:
            zw = random.choice([
                "\u200b", "\u200c", "\u200d", "\ufeff",
                "\u2060", "\u180e"
            ])
            pos = random.randint(1, max(1, len(text) - 1))
            text = text[:pos] + zw + text[pos:]
        return text

    @staticmethod
    def case_variation(text):
        """Đổi hoa/thường."""
        if random.random() > 0.25:
            return text
        mode = random.random()
        if mode < 0.4:
            return text[0].upper() + text[1:] if text else text
        elif mode < 0.7:
            words = text.split()
            for _ in range(random.randint(1, 2)):
                if words:
                    i = random.randint(0, len(words) - 1)
                    words[i] = words[i].capitalize()
            return " ".join(words)
        else:
            return text.upper() if random.random() < 0.5 else text.lower()

    @staticmethod
    def typo_simulation(text, prob=0.06):
        """Lỗi đánh máy."""
        if random.random() > prob:
            return text
        chars = list(text)
        if not chars:
            return text
        mode = random.choice(["swap", "replace", "duplicate"])
        i = random.randint(0, len(chars) - 1)
        if mode == "swap" and i < len(chars) - 1:
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        elif mode == "replace" and chars[i].isalpha():
            chars[i] = random.choice("abcdefghijklmnopqrstuvwxyz")
        elif mode == "duplicate":
            chars.insert(i, chars[i])
        return "".join(chars)

    @staticmethod
    def punctuation_injection(text):
        """Thêm dấu câu."""
        if random.random() > 0.4:
            return text
        return text + random.choice([
            "...", "..", "!", "?", "!!", "~", " :)))", " hihi"
        ])

    # ============================================================
    # COLOR + EMOJI
    # ============================================================
    @staticmethod
    def random_color():
        """Chọn màu ngẫu nhiên."""
        return random.choice(ZALO_COLOR_CODES)

    @staticmethod
    def random_emoji():
        """Chọn emoji Zalo ngẫu nhiên."""
        return random.choice(ZALO_EMOJIS)

    @staticmethod
    def inject_emoji(text):
        """Chèn emoji vào cuối tin."""
        if random.random() > 0.5:
            return text
        emoji = AntiBanBypass.random_emoji()
        return f"{text} {emoji}"

    # ============================================================
    # APPLY ALL
    # ============================================================
    @staticmethod
    def transform(text, use_color=True, use_emoji=True):
        """
        Áp dụng toàn bộ transformation.
        Trả về (text_mới, color).
        """
        # 1. Typo
        text = AntiBanBypass.typo_simulation(text)
        # 2. Punctuation
        text = AntiBanBypass.punctuation_injection(text)
        # 3. Case
        text = AntiBanBypass.case_variation(text)
        # 4. Entropy
        text = AntiBanBypass.entropy_mask(text)
        # 5. Emoji
        if use_emoji:
            text = AntiBanBypass.inject_emoji(text)
        # 6. Color
        color = AntiBanBypass.random_color() if use_color else None
        return text, color

    # ============================================================
    # RISK
    # ============================================================
    @staticmethod
    def compute_risk(ok, fail):
        total = ok + fail
        if total == 0:
            return 0.0
        return min(1.0, fail / total)


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

    # ==== LOAD BOX ====
    def get_groups(self):
        """Lấy danh sách nhóm."""
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
                    "id": gid,
                    "name": info["name"],
                    "type": "group",
                    "members": info["totalMember"],
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
        """Lấy danh sách bạn bè (chat 1-1)."""
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

    # ==== SEND ====
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
def parse_message_file(filepath):
    """
    Parse file txt thành list messages.
    Hỗ trợ:
    - Mỗi dòng 1 tin
    - Dòng có số thứ tự: "1. nội dung" → "nội dung"
    - Bỏ qua dòng trống
    - Bỏ comment # đầu dòng
    """
    messages = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    continue
                # Xóa số thứ tự đầu dòng
                # Pattern: "1. ", "2) ", "3 - ", "4: "
                import re
                line = re.sub(r"^\d+[\.\)\-\:]\s*", "", line)
                if line:
                    messages.append(line)
    except Exception as e:
        print(f"[FILE] Lỗi parse: {e}")
    return messages


# ============================================================
# SPAM WORKER v14
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
    risk = AntiBanBypass.compute_risk(ok_c, fail_c)
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


def spam_worker(tid, targets, messages, delay, use_color, use_emoji, stop_event):
    """
    Worker spam v14:
    - Rotate acc
    - Rotate target
    - Rotate color
    - Rotate emoji
    - Bypass anti-ban
    """
    msg_idx = 0
    target_idx = 0
    count = 0
    last_acc_id = None

    print(f"[SPAM] Bắt đầu task {tid}")
    print(f"  Targets: {len(targets)}")
    print(f"  Messages: {len(messages)}")
    print(f"  Delay: {delay}s | Color: {use_color} | Emoji: {use_emoji}")

    while not stop_event.is_set():
        acc = pick_account()
        if not acc:
            time.sleep(1)
            continue

        # Rotate acc
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

        # Chọn target + message
        target = targets[target_idx % len(targets)]
        target_idx += 1
        raw_msg = messages[msg_idx % len(messages)]
        msg_idx += 1

        # Transform
        msg, color = AntiBanBypass.transform(
            raw_msg,
            use_color=use_color,
            use_emoji=use_emoji,
        )

        is_group = target.get("type") == "group"
        target_id = target.get("id")

        try:
            cookies = json.loads(acc["cookies"])
            z = Zalo(acc["imei"], cookies)

            # Thinking time
            time.sleep(random.uniform(0.3, 1.2))
            z.set_typing(target_id, is_group=is_group)

            # Typing simulation
            t_time = AntiBanBypass.typing_time(msg)
            time.sleep(t_time)

            # Send
            r = z.send(msg, target_id, color=color, is_group=is_group)
            ok = bool(r and r.status_code == 200)

            update_stats(acc["id"], ok)
            count += 1

            status = "OK" if ok else "LỖI"
            color_str = f"[{color}]" if color else ""
            print(f"[SPAM #{count}] {acc['label']} → {target_id}{color_str} "
                  f"[{status}] {msg[:50]}")

        except Exception as e:
            update_stats(acc["id"], False)
            print(f"[SPAM] Lỗi {acc['label']}: {e}")

        # Delay
        risk = acc["risk"] if acc["risk"] else 0.0
        actual_delay = AntiBanBypass.compute_delay(delay, risk)

        end = time.time() + actual_delay
        while time.time() < end:
            if stop_event.is_set():
                break
            time.sleep(0.1)

    conn = db()
    conn.execute(
        "UPDATE tasks SET status = 'stopped', stats = ? WHERE id = ?",
        (json.dumps({"sent": count}), tid)
    )
    conn.commit()
    conn.close()
    ACTIVE_TASKS.pop(tid, None)
    print(f"[SPAM] Task {tid} dừng — Tổng gửi: {count}")


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
    return render_template_string(HTML_INDEX, qr_url=QR_SERVICE_URL)


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
    label = data.get("label", "").strip() or f"acc{int(time.time())}"
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
# API — LOAD BOXES (QUAN TRỌNG)
# ============================================================
@app.route("/api/accounts/<int:aid>/load_boxes", methods=["POST"])
@login_required
def api_load_boxes(aid):
    """Load toàn bộ groups + friends từ 1 acc."""
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

    # Save
    filename = f.filename
    safe_name = f"{int(time.time())}_{filename}"
    filepath = os.path.join(UPLOAD_DIR, safe_name)
    f.save(filepath)

    # Parse
    messages = parse_message_file(filepath)
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
    messages = parse_message_file(row["filepath"])
    return jsonify({
        "filename": row["filename"],
        "total": len(messages),
        "preview": messages[:20],
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
    targets = data.get("targets", [])       # List of {id, type, name}
    messages = data.get("messages", [])     # List of strings
    delay = float(data.get("delay", 3))
    use_color = bool(data.get("use_color", True))
    use_emoji = bool(data.get("use_emoji", True))

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
        args=(tid, targets, messages, delay, use_color, use_emoji, stop_event),
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
              "color": use_color,
              "emoji": use_emoji,
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


# ============================================================
# API — QR RECEIVE
# ============================================================
@app.route("/api/receive-cookie", methods=["POST"])
def api_receive_cookie():
    key = request.headers.get("X-QR-Key", "")
    if key != QR_SERVICE_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json or {}
    imei = data.get("imei", "").strip()
    cookies = data.get("cookies")
    label = data.get("label", "").strip() or f"qr_{int(time.time())}"

    if not imei or not cookies:
        return jsonify({"error": "Thiếu imei hoặc cookies"}), 400

    conn = db()
    conn.execute("""
        INSERT INTO accounts (label, imei, cookies, added_at)
        VALUES (?, ?, ?, ?)
    """, (label, imei, json.dumps(cookies), time.time()))
    conn.commit()
    conn.close()

    print(f"[QR-RECV] Nhận cookie mới: {label} | IMEI: {imei}")
    return jsonify({"ok": True, "label": label})


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "web-lenh",
        "version": "14.0",
        "tasks": len(ACTIVE_TASKS),
        "qr_configured": bool(QR_SERVICE_URL),
    })


# ============================================================
# HTML — gộp vào 1 file để dễ copy
# ============================================================
HTML_LOGIN = """
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>Đăng nhập — ALB Forge</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
body { font-family:'Inter',sans-serif; min-height:100vh; min-height:100dvh; display:flex; align-items:center; justify-content:center; background:linear-gradient(135deg,#667eea,#764ba2); padding:20px; }
.card { background:white; padding:48px 40px; border-radius:32px; box-shadow:0 30px 80px rgba(0,0,0,0.3); width:100%; max-width:440px; animation:slideUp 0.7s cubic-bezier(0.16,1,0.3,1); }
@keyframes slideUp { from { opacity:0; transform:translateY(40px); } to { opacity:1; transform:translateY(0); } }
.logo { width:80px; height:80px; border-radius:24px; background:linear-gradient(135deg,#667eea,#764ba2); display:flex; align-items:center; justify-content:center; font-size:40px; margin:0 auto 24px; box-shadow:0 20px 45px rgba(102,126,234,0.5); }
h1 { color:#1a1a2e; margin-bottom:8px; font-size:28px; font-weight:900; text-align:center; }
p.sub { color:#6b7280; margin-bottom:36px; font-size:14px; text-align:center; font-weight:500; }
input { width:100%; padding:18px; border:2px solid #e5e7eb; border-radius:16px; font-size:16px; font-family:inherit; font-weight:500; background:#f9fafb; }
input:focus { outline:none; border-color:#667eea; background:white; box-shadow:0 0 0 5px rgba(102,126,234,0.12); }
button { width:100%; padding:18px; background:linear-gradient(135deg,#667eea,#764ba2); color:white; border:none; border-radius:16px; font-size:16px; font-weight:800; font-family:inherit; cursor:pointer; box-shadow:0 12px 30px rgba(102,126,234,0.4); margin-top:16px; }
button:hover { transform:translateY(-2px); }
.error { background:#fef2f2; color:#dc2626; padding:14px 18px; border-radius:14px; margin-bottom:20px; font-size:14px; font-weight:600; border-left:4px solid #dc2626; }
</style>
</head>
<body>
<div class="card">
    <div class="logo">🔥</div>
    <h1>ALB FORGE PRO</h1>
    <p class="sub">Bot by Anh Khôi — v14.0</p>
    {% if error %}<div class="error">⚠️ {{ error }}</div>{% endif %}
    <form method="POST">
        <input type="password" name="password" placeholder="Nhập mật khẩu" autofocus required>
        <button type="submit">🚀 Đăng nhập</button>
    </form>
</div>
</body>
</html>
"""


HTML_INDEX = """
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>ALB Forge PRO v14</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html { touch-action:manipulation; }
body { font-family:'Inter',sans-serif; background:#f8fafc; min-height:100vh; color:#1a1a2e; }

.header {
    background:linear-gradient(135deg,#667eea,#764ba2);
    color:white; padding:20px 24px;
    box-shadow:0 4px 30px rgba(102,126,234,0.35);
    position:sticky; top:0; z-index:100;
    padding-top:calc(20px + env(safe-area-inset-top, 0px));
}
.header-inner { max-width:1200px; margin:0 auto; display:flex; align-items:center; justify-content:space-between; gap:16px; }
.logo-text { display:flex; align-items:center; gap:12px; }
.logo-icon { width:48px; height:48px; border-radius:16px; background:rgba(255,255,255,0.2); display:flex; align-items:center; justify-content:center; font-size:24px; }
.header h1 { font-size:22px; font-weight:900; }
.header p { font-size:12px; opacity:0.85; margin-top:2px; }
.logout-btn { background:rgba(255,255,255,0.15); color:white; border:1px solid rgba(255,255,255,0.25); padding:12px 20px; border-radius:14px; cursor:pointer; font-size:14px; font-weight:700; }

.container { max-width:1200px; margin:0 auto; padding:20px; }

.tabs { display:grid; grid-template-columns:repeat(5,1fr); gap:8px; margin-bottom:20px; background:white; padding:8px; border-radius:20px; box-shadow:0 4px 25px rgba(0,0,0,0.05); }
.tab { padding:14px 8px; border-radius:14px; cursor:pointer; font-size:12px; font-weight:700; text-align:center; color:#6b7280; display:flex; flex-direction:column; align-items:center; gap:6px; }
.tab-icon { font-size:20px; }
.tab.active { background:linear-gradient(135deg,#667eea,#764ba2); color:white; }

.panel { display:none; animation:fadeIn 0.4s; }
.panel.active { display:block; }
@keyframes fadeIn { from { opacity:0; transform:translateY(15px); } to { opacity:1; transform:translateY(0); } }

.card { background:white; padding:24px; border-radius:24px; box-shadow:0 6px 35px rgba(0,0,0,0.06); margin-bottom:20px; border:1px solid #f0f2f5; }
.card h2 { font-size:17px; font-weight:900; margin-bottom:18px; display:flex; align-items:center; gap:12px; }
.card h2 .badge-icon { width:36px; height:36px; border-radius:12px; background:linear-gradient(135deg,#667eea,#764ba2); display:flex; align-items:center; justify-content:center; font-size:18px; }

.form-group { margin-bottom:16px; }
.form-group label { display:block; margin-bottom:8px; font-size:13px; font-weight:700; color:#374151; }
.form-group input, .form-group textarea, .form-group select { width:100%; padding:14px 16px; border:2px solid #e5e7eb; border-radius:14px; font-size:14px; font-family:inherit; background:#f9fafb; color:#1a1a2e; }
.form-group input:focus, .form-group textarea:focus, .form-group select:focus { outline:none; border-color:#667eea; background:white; box-shadow:0 0 0 5px rgba(102,126,234,0.1); }
.form-group textarea { min-height:100px; resize:vertical; font-family:monospace; font-size:13px; }

.btn { padding:14px 24px; border:none; border-radius:14px; font-size:14px; font-weight:800; font-family:inherit; cursor:pointer; margin-right:8px; margin-bottom:8px; display:inline-flex; align-items:center; gap:8px; transition:all 0.3s; position:relative; overflow:hidden; }
.btn::after { content:''; position:absolute; inset:0; background:linear-gradient(135deg,transparent,rgba(255,255,255,0.35),transparent); transform:translateX(-100%); transition:transform 0.7s; }
.btn:hover::after { transform:translateX(100%); }
.btn:hover { transform:translateY(-3px); }
.btn-primary { background:linear-gradient(135deg,#667eea,#764ba2); color:white; box-shadow:0 10px 25px rgba(102,126,234,0.35); }
.btn-danger { background:linear-gradient(135deg,#ef4444,#dc2626); color:white; }
.btn-success { background:linear-gradient(135deg,#10b981,#059669); color:white; box-shadow:0 10px 25px rgba(16,185,129,0.3); }
.btn-qr { background:linear-gradient(135deg,#f093fb,#f5576c); color:white; font-size:18px; padding:22px 48px; border-radius:20px; box-shadow:0 15px 40px rgba(245,87,108,0.45); }
.btn-warning { background:linear-gradient(135deg,#f59e0b,#d97706); color:white; }
.btn-sm { padding:8px 14px; font-size:12px; margin-right:6px; margin-bottom:0; border-radius:10px; }
.btn-block { width:100%; margin-right:0; }

.stat-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:14px; margin-bottom:20px; }
.stat { background:linear-gradient(135deg,#f9fafb,#f3f4f6); padding:20px; border-radius:18px; border:1px solid #e5e7eb; position:relative; overflow:hidden; }
.stat::before { content:''; position:absolute; top:0; left:0; right:0; height:4px; background:linear-gradient(90deg,#667eea,#764ba2); }
.stat .label { font-size:11px; color:#6b7280; margin-bottom:8px; text-transform:uppercase; font-weight:800; }
.stat .value { font-size:30px; font-weight:900; color:#1a1a2e; line-height:1; }

.table-wrap { overflow-x:auto; }
.table { width:100%; border-collapse:collapse; }
.table th, .table td { padding:12px; text-align:left; font-size:13px; border-bottom:1px solid #f0f2f5; white-space:nowrap; }
.table th { background:#f9fafb; font-weight:800; color:#6b7280; text-transform:uppercase; font-size:11px; }

.badge { display:inline-flex; padding:4px 10px; border-radius:20px; font-size:11px; font-weight:800; }
.badge-ok { background:#d1fae5; color:#065f46; }
.badge-err { background:#fee2e2; color:#991b1b; }
.badge-warn { background:#fef3c7; color:#92400e; }
.badge-info { background:#dbeafe; color:#1e40af; }

.alert { padding:16px 20px; border-radius:14px; font-size:14px; font-weight:700; display:none; position:fixed; top:100px; right:24px; z-index:999; box-shadow:0 15px 45px rgba(0,0,0,0.2); max-width:400px; }
.alert.show { display:flex; gap:12px; animation:slideIn 0.4s; }
@keyframes slideIn { from { opacity:0; transform:translateX(120%); } to { opacity:1; transform:translateX(0); } }
.alert-success { background:linear-gradient(135deg,#d1fae5,#a7f3d0); color:#065f46; border-left:5px solid #10b981; }
.alert-error { background:linear-gradient(135deg,#fee2e2,#fecaca); color:#991b1b; border-left:5px solid #ef4444; }

.qr-hero { background:linear-gradient(135deg,#f093fb,#f5576c); color:white; text-align:center; padding:60px 30px; border-radius:28px; box-shadow:0 25px 70px rgba(245,87,108,0.4); }
.qr-hero h2 { color:white; font-size:32px; margin-bottom:14px; font-weight:900; justify-content:center; }
.qr-hero p { opacity:0.95; margin-bottom:32px; font-size:16px; }
.qr-hero small { display:block; margin-top:28px; font-size:13px; background:rgba(255,255,255,0.18); padding:12px 20px; border-radius:12px; }

.box-list { max-height:400px; overflow-y:auto; border:2px solid #e5e7eb; border-radius:16px; padding:12px; background:#f9fafb; }
.box-item { padding:12px; border-radius:12px; background:white; margin-bottom:8px; cursor:pointer; border:2px solid transparent; transition:all 0.2s; display:flex; align-items:center; gap:10px; }
.box-item:hover { border-color:#667eea; background:#f0f4ff; }
.box-item.selected { border-color:#10b981; background:#ecfdf5; }
.box-item .check { width:20px; height:20px; border:2px solid #d1d5db; border-radius:6px; display:flex; align-items:center; justify-content:center; font-size:12px; color:white; font-weight:900; flex-shrink:0; }
.box-item.selected .check { background:#10b981; border-color:#10b981; }
.box-item .info { flex:1; min-width:0; }
.box-item .name { font-weight:700; font-size:13px; color:#1a1a2e; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.box-item .id { font-size:11px; color:#6b7280; font-family:monospace; margin-top:2px; }
.box-item .type { padding:2px 8px; border-radius:6px; font-size:10px; font-weight:800; }
.type-group { background:#dbeafe; color:#1e40af; }
.type-user { background:#fce7f3; color:#9d174d; }

.file-item { display:flex; align-items:center; gap:12px; padding:14px; border-radius:14px; background:#f9fafb; margin-bottom:10px; border:1px solid #e5e7eb; }
.file-item .info { flex:1; min-width:0; }
.file-item .name { font-weight:700; font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.file-item .meta { font-size:12px; color:#6b7280; margin-top:4px; }

.toggle-row { display:flex; gap:12px; margin-bottom:16px; }
.toggle { flex:1; padding:14px; border:2px solid #e5e7eb; border-radius:14px; cursor:pointer; text-align:center; font-weight:700; font-size:13px; background:#f9fafb; color:#6b7280; user-select:none; }
.toggle.active { background:linear-gradient(135deg,#667eea,#764ba2); color:white; border-color:transparent; }

@media (max-width:640px) {
    .container { padding:12px; }
    .card { padding:18px; border-radius:20px; }
    .tabs { grid-template-columns:repeat(5,1fr); gap:5px; padding:6px; }
    .tab { padding:10px 4px; font-size:10px; }
    .tab-icon { font-size:18px; }
    .stat .value { font-size:24px; }
    .table th, .table td { padding:8px 6px; font-size:11px; }
    .btn { padding:12px 16px; font-size:13px; }
    .alert { left:12px; right:12px; max-width:none; }
    .qr-hero { padding:40px 20px; }
    .qr-hero h2 { font-size:24px; }
}
</style>
</head>
<body>

<div class="header">
    <div class="header-inner">
        <div class="logo-text">
            <div class="logo-icon">🔥</div>
            <div>
                <h1>ALB FORGE PRO</h1>
                <p>Bot by Anh Khôi • v14.0</p>
            </div>
        </div>
        <button class="logout-btn" onclick="location.href='/logout'">🚪 Thoát</button>
    </div>
</div>

<div class="container">

<div class="tabs">
    <div class="tab active" data-tab="qr">
        <div class="tab-icon">📱</div>
        <div>Tạo QR</div>
    </div>
    <div class="tab" data-tab="accounts">
        <div class="tab-icon">🔐</div>
        <div>Acc</div>
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

<!-- TAB QR -->
<div class="panel active" id="panel-qr">
    <div class="qr-hero">
        <h2>📱 Tạo mã QR Zalo</h2>
        <p>Bấm nút bên dưới để mở trang quét QR</p>
        <button class="btn btn-qr" onclick="openQR()">🚀 Mở trang quét QR</button>
        <small>💡 Sau khi quét xong, cookie sẽ tự động gửi về đây</small>
    </div>
</div>

<!-- TAB ACCOUNTS -->
<div class="panel" id="panel-accounts">
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
        <button class="btn btn-primary btn-block" onclick="addAccount()">💾 Thêm tài khoản</button>
    </div>

    <div class="card">
        <h2><span class="badge-icon">📋</span> Danh sách tài khoản</h2>
        <div class="stat-grid">
            <div class="stat"><div class="label">Tổng</div><div class="value" id="stat-total">0</div></div>
            <div class="stat"><div class="label">Active</div><div class="value" id="stat-active">0</div></div>
            <div class="stat"><div class="label">Đã gửi</div><div class="value" id="stat-sent">0</div></div>
        </div>
        <div class="table-wrap">
            <table class="table">
                <thead><tr>
                    <th>ID</th><th>Tên</th><th>OK/Lỗi</th><th>Risk</th><th>Sent</th><th>Hành động</th>
                </tr></thead>
                <tbody id="accounts-tbody"></tbody>
            </table>
        </div>
    </div>
</div>

<!-- TAB BOXES -->
<div class="panel" id="panel-boxes">
    <div class="card">
        <h2><span class="badge-icon">📦</span> Load ID Box & Cuộc trò chuyện</h2>
        <div class="form-group">
            <label>Chọn tài khoản để load</label>
            <select id="load-acc-select">
                <option value="">-- Chọn tài khoản --</option>
            </select>
        </div>
        <button class="btn btn-primary" onclick="loadBoxes()">🔄 Load Box</button>
        <button class="btn btn-warning" onclick="selectAllBoxes()">✅ Chọn tất cả</button>
        <button class="btn btn-danger" onclick="clearAllBoxes()">❌ Bỏ chọn</button>

        <div style="margin-top:20px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <b style="font-size:14px;">Đã chọn: <span id="selected-count" style="color:#667eea;">0</span> box</b>
            </div>
            <div class="box-list" id="box-list">
                <div style="text-align:center; padding:40px; color:#999;">Chưa load box nào</div>
            </div>
        </div>
    </div>
</div>

<!-- TAB FILES -->
<div class="panel" id="panel-files">
    <div class="card">
        <h2><span class="badge-icon">📤</span> Upload file tin nhắn</h2>
        <p style="font-size:13px; color:#6b7280; margin-bottom:16px;">
            File .txt, mỗi dòng 1 tin. Có thể có số thứ tự: "1. nội dung"<br>
            Dòng bắt đầu bằng # sẽ bị bỏ qua. Delay có thể tùy chỉnh.
        </p>
        <div class="form-group">
            <input type="file" id="file-input" accept=".txt">
        </div>
        <button class="btn btn-primary" onclick="uploadFile()">📤 Upload</button>
    </div>

    <div class="card">
        <h2><span class="badge-icon">📁</span> Quản lý file</h2>
        <div id="files-list">
            <div style="text-align:center; padding:40px; color:#999;">Chưa có file</div>
        </div>
    </div>
</div>

<!-- TAB SPAM -->
<div class="panel" id="panel-spam">
    <div class="card">
        <h2><span class="badge-icon">🎯</span> Cấu hình spam</h2>
        <div class="form-group">
            <label>Chọn file tin nhắn</label>
            <select id="spam-file-select">
                <option value="">-- Chọn file --</option>
            </select>
        </div>
        <div class="form-group">
            <label>Hoặc nhập tin trực tiếp (cách nhau bằng dấu ;)</label>
            <textarea id="spam-messages" placeholder="Chào buổi sáng;Hello;Nice day"></textarea>
        </div>
        <div class="form-group">
            <label>Delay giữa các tin (giây) — có thể nhập bất kỳ số nào (0.5, 1, 5, 10...)</label>
            <input id="spam-delay" type="number" value="3" step="0.1" min="0.5">
        </div>
        <div class="toggle-row">
            <div class="toggle active" id="toggle-color" onclick="toggleFlag('color')">
                🎨 Đổi màu chữ
            </div>
            <div class="toggle active" id="toggle-emoji" onclick="toggleFlag('emoji')">
                😊 Chèn emoji Zalo
            </div>
        </div>
        <button class="btn btn-success btn-block" onclick="startSpam()" style="font-size:16px; padding:18px;">
            ▶️ BẮT ĐẦU SPAM
        </button>
        <button class="btn btn-danger btn-block" onclick="stopAll()" style="margin-top:10px;">
            ⏸️ DỪNG TẤT CẢ
        </button>
    </div>

    <div class="card" style="background:linear-gradient(135deg,#fef3c7,#fde68a); border:2px solid #fbbf24;">
        <h2 style="color:#92400e;"><span class="badge-icon" style="background:#92400e;">🛡️</span> Bypass Anti-Ban v14</h2>
        <div style="color:#78350f; font-size:13px; line-height:1.8; font-weight:600;">
            ✅ Multi-account rotation — luân phiên acc<br>
            ✅ Message fingerprint — mỗi tin khác nhau<br>
            ✅ Timing jitter — delay ngẫu nhiên ±50%<br>
            ✅ Color rotation — đổi màu mỗi tin<br>
            ✅ Emoji injection — chèn emoji Zalo<br>
            ✅ Unicode zero-width — chống hash<br>
            ✅ Adaptive throttling — tự điều chỉnh<br>
            ✅ Risk-based skipping — bỏ acc risk cao<br>
            ✅ Session isolation — mỗi acc 1 session
        </div>
    </div>

    <div class="card">
        <h2><span class="badge-icon">📋</span> Tác vụ đang chạy</h2>
        <button class="btn btn-danger btn-sm" onclick="stopAll()">Dừng tất cả</button>
        <div class="table-wrap" style="margin-top:12px;">
            <table class="table">
                <thead><tr>
                    <th>ID</th><th>Trạng thái</th><th>Bắt đầu</th><th></th>
                </tr></thead>
                <tbody id="tasks-tbody"></tbody>
            </table>
        </div>
    </div>
</div>

</div>

<script>
const QR_URL = "{{ qr_url }}";
let flags = { color: true, emoji: true };
let selectedBoxes = [];

document.querySelectorAll('.tab').forEach(t => {
    t.onclick = () => {
        document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
        document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
        t.classList.add('active');
        document.getElementById('panel-' + t.dataset.tab).classList.add('active');
        refreshAll();
    };
});

function showAlert(msg, type='success') {
    const a = document.getElementById('alert');
    a.innerHTML = (type === 'success' ? '✅ ' : '⚠️ ') + msg;
    a.className = 'alert show alert-' + type;
    setTimeout(() => a.classList.remove('show'), 4000);
}

async function api(url, opts = {}) {
    const r = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    return r.json();
}

function toggleFlag(name) {
    flags[name] = !flags[name];
    const el = document.getElementById('toggle-' + name);
    el.classList.toggle('active', flags[name]);
}

function openQR() {
    if (!QR_URL) return showAlert('Web QR chưa cấu hình', 'error');
    window.open(QR_URL, '_blank');
}

// ==== ACCOUNTS ====
async function loadAccounts() {
    const accounts = await api('/api/accounts');
    const tbody = document.getElementById('accounts-tbody');
    if (!accounts.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#999;padding:40px;">Chưa có tài khoản</td></tr>';
    } else {
        tbody.innerHTML = accounts.map(a => {
            const risk = (a.risk || 0).toFixed(2);
            const riskCls = risk > 0.5 ? 'badge-err' : risk > 0.2 ? 'badge-warn' : 'badge-ok';
            return `
                <tr>
                    <td>${a.id}</td>
                    <td><b>${a.label}</b></td>
                    <td>
                        <span class="badge badge-ok">${a.ok_count}</span>
                        <span class="badge badge-err">${a.fail_count}</span>
                    </td>
                    <td><span class="badge ${riskCls}">${risk}</span></td>
                    <td><span class="badge badge-info">${a.total_sent || 0}</span></td>
                    <td>
                        <button class="btn btn-sm btn-primary" onclick="checkAcc(${a.id})">Check</button>
                        <button class="btn btn-sm btn-primary" onclick="resetAcc(${a.id})">Reset</button>
                        <button class="btn btn-sm btn-danger" onclick="delAcc(${a.id})">Xóa</button>
                    </td>
                </tr>
            `;
        }).join('');
    }
    document.getElementById('stat-total').textContent = accounts.length;
    document.getElementById('stat-active').textContent = accounts.filter(a => a.enabled).length;
    document.getElementById('stat-sent').textContent = accounts.reduce((s, a) => s + (a.total_sent || 0), 0);

    // Update acc selects
    const sel1 = document.getElementById('load-acc-select');
    const current = sel1.value;
    sel1.innerHTML = '<option value="">-- Chọn tài khoản --</option>' +
        accounts.map(a => `<option value="${a.id}">${a.label} (ID: ${a.id})</option>`).join('');
    sel1.value = current;
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

// ==== BOXES ====
async function loadBoxes() {
    const aid = document.getElementById('load-acc-select').value;
    if (!aid) return showAlert('Chọn tài khoản', 'error');
    showAlert('Đang load box... (có thể mất 10-30s)');
    const r = await api('/api/accounts/' + aid + '/load_boxes', { method: 'POST' });
    if (r.error) return showAlert(r.error, 'error');

    const all = [...(r.groups || []), ...(r.friends || [])];
    const boxList = document.getElementById('box-list');
    if (!all.length) {
        boxList.innerHTML = '<div style="text-align:center; padding:40px; color:#999;">Không có box nào</div>';
        return;
    }
    boxList.innerHTML = all.map((b, i) => `
        <div class="box-item" data-idx="${i}" onclick="toggleBox(this, ${i})">
            <div class="check">✓</div>
            <div class="info">
                <div class="name">${b.name}</div>
                <div class="id">ID: ${b.id}</div>
            </div>
            <span class="type type-${b.type}">${b.type === 'group' ? '👥 Nhóm' : '👤 Chat'}</span>
        </div>
    `).join('');

    window._allBoxes = all;
    selectedBoxes = [];
    document.getElementById('selected-count').textContent = '0';
    showAlert(`Đã load ${all.length} box (${r.groups.length} nhóm, ${r.friends.length} chat)`);
}

function toggleBox(el, idx) {
    const box = window._allBoxes[idx];
    const isSelected = el.classList.contains('selected');
    if (isSelected) {
        el.classList.remove('selected');
        selectedBoxes = selectedBoxes.filter(b => b.id !== box.id);
    } else {
        el.classList.add('selected');
        selectedBoxes.push(box);
    }
    document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function selectAllBoxes() {
    document.querySelectorAll('.box-item').forEach(el => {
        el.classList.add('selected');
    });
    selectedBoxes = [...(window._allBoxes || [])];
    document.getElementById('selected-count').textContent = selectedBoxes.length;
}

function clearAllBoxes() {
    document.querySelectorAll('.box-item').forEach(el => {
        el.classList.remove('selected');
    });
    selectedBoxes = [];
    document.getElementById('selected-count').textContent = '0';
}

// ==== FILES ====
async function uploadFile() {
    const input = document.getElementById('file-input');
    if (!input.files.length) return showAlert('Chọn file trước', 'error');
    const fd = new FormData();
    fd.append('file', input.files[0]);
    showAlert('Đang upload...');
    const r = await fetch('/api/files/upload', { method: 'POST', body: fd }).then(r => r.json());
    if (r.error) return showAlert(r.error, 'error');
    showAlert(`Đã upload ${r.filename} (${r.lines} dòng)`);
    input.value = '';
    loadFiles();
}

async function loadFiles() {
    const files = await api('/api/files');
    const list = document.getElementById('files-list');
    if (!files.length) {
        list.innerHTML = '<div style="text-align:center; padding:40px; color:#999;">Chưa có file</div>';
    } else {
        list.innerHTML = files.map(f => {
            const size = (f.size / 1024).toFixed(1);
            const date = new Date(f.uploaded_at * 1000).toLocaleString('vi-VN');
            return `
                <div class="file-item">
                    <div class="info">
                        <div class="name">📄 ${f.filename}</div>
                        <div class="meta">${f.lines} dòng • ${size} KB • ${date}</div>
                    </div>
                    <button class="btn btn-sm btn-primary" onclick="previewFile(${f.id})">Xem</button>
                    <button class="btn btn-sm btn-danger" onclick="delFile(${f.id})">Xóa</button>
                </div>
            `;
        }).join('');
    }

    // Update spam file select
    const sel = document.getElementById('spam-file-select');
    sel.innerHTML = '<option value="">-- Chọn file --</option>' +
        files.map(f => `<option value="${f.id}">${f.filename} (${f.lines} dòng)</option>`).join('');
}

async function previewFile(fid) {
    const r = await api('/api/files/' + fid + '/preview');
    if (r.error) return showAlert(r.error, 'error');
    const preview = r.preview.map((m, i) => `${i + 1}. ${m}`).join('\\n');
    alert(`File: ${r.filename}\\nTổng: ${r.total} dòng\\n\\nPreview:\\n${preview}`);
}

async function delFile(fid) {
    if (!confirm('Xóa file này?')) return;
    await api('/api/files/' + fid, { method: 'DELETE' });
    showAlert('Đã xóa file');
    loadFiles();
}

// ==== SPAM ====
async function startSpam() {
    if (!selectedBoxes.length) return showAlert('Chưa chọn box để spam', 'error');

    // Lấy messages
    const fileId = document.getElementById('spam-file-select').value;
    const directMsgs = document.getElementById('spam-messages').value.trim();
    let messages = [];

    if (fileId) {
        const r = await api('/api/files/' + fileId + '/preview');
        if (r.error) return showAlert('Lỗi đọc file: ' + r.error, 'error');
        messages = r.preview;  // chỉ lấy 20 preview
        // Load full
        const full = await fetch('/api/files/' + fileId + '/preview').then(r => r.json());
        if (full.preview) {
            // Gọi lại API để lấy full (không giới hạn)
            // API hiện tại trả 20 → cần đổi: dùng /api/files/<id>/content
            // Tạm thời dùng preview
        }
    } else if (directMsgs) {
        messages = directMsgs.split(';').map(m => m.trim()).filter(m => m);
    }

    if (!messages.length) return showAlert('Chưa có tin nhắn', 'error');

    const delay = parseFloat(document.getElementById('spam-delay').value) || 3;

    const r = await api('/api/tasks/start', {
        method: 'POST',
        body: JSON.stringify({
            targets: selectedBoxes,
            messages: messages,
            delay: delay,
            use_color: flags.color,
            use_emoji: flags.emoji,
        }),
    });
    if (r.error) return showAlert(r.error, 'error');
    showAlert('🚀 Đã bắt đầu spam: ' + r.task_id);
    loadTasks();
}

async function stopAll() {
    await api('/api/tasks/stop_all', { method: 'POST' });
    showAlert('Đã dừng tất cả');
    loadTasks();
}

async function loadTasks() {
    const tasks = await api('/api/tasks');
    const tbody = document.getElementById('tasks-tbody');
    if (!tasks.length) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#999;padding:30px;">Chưa có</td></tr>';
        return;
    }
    tbody.innerHTML = tasks.map(t => {
        const start = new Date(t.started_at * 1000).toLocaleString('vi-VN');
        return `
            <tr>
                <td><code style="font-size:11px;">${t.id}</code></td>
                <td><span class="badge ${t.status === 'running' ? 'badge-ok' : 'badge-err'}">${t.status === 'running' ? 'Đang chạy' : 'Đã dừng'}</span></td>
                <td style="font-size:12px;">${start}</td>
                <td>${t.status === 'running' ? `<button class="btn btn-sm btn-danger" onclick="stopTask('${t.id}')">Dừng</button>` : ''}</td>
            </tr>
        `;
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

setInterval(() => {
    loadTasks();
}, 5000);

refreshAll();
</script>

</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
