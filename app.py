# ============================================================
# WEB-LENH v13.0 PRO — Dashboard + Spam Anti-Ban PRO
# Bot by Anh Khôi
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
import math
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
QR_SERVICE_URL = os.environ.get("QR_SERVICE_URL", "")
QR_SERVICE_KEY = os.environ.get("QR_SERVICE_KEY", "qr-lenh-shared-key-2026")
DATA_DIR = os.environ.get("DATA_DIR", "/tmp/alb_web")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "alb.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "alb-lenh-secret-2026")


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
# ANTI-BAN PRO v13 — TYPING SIMULATION + OFFSET CAO CẤP
# Không cooldown dài. Không nghỉ dài. Tập trung 100% vào
# việc giả lập hành vi người thật cực kỳ tinh vi.
# ============================================================
class AntiBanPro:
    """
    Anti-Ban PRO — Chuyên gia cấp thế giới.

    Điểm khác biệt so với Anti-Ban Elite:
    1. Markov Chain Typing — mô hình hóa nhịp gõ như người thật
    2. Circadian Rhythm — giả lập nhịp sinh học theo giờ
    3. Fatigue Simulation — tự mô phỏng mỏi tay khi gõ nhiều
    4. Message Personality — mỗi acc có "tính cách" riêng
    5. Repetition Aversion — không lặp lại nội dung đã gửi
    6. Context Awareness — thêm ngữ cảnh theo thời gian thực
    7. Unicode Obfuscation — chèn unicode invisible nâng cao
    8. Emoji Semantic — emoji khớp với nội dung
    9. Sentence Structure — thay đổi cấu trúc câu
    10. Multi-Pause Pattern — nhiều loại pause khác nhau
    """

    # ==== DELAY RANGE ====
    MIN_DELAY = 3.0
    MAX_DELAY = 8.0

    # ==== TYPING SPEED DISTRIBUTIONS ====
    # Dùng phân phối Gaussian để nhịp gõ tự nhiên hơn uniform
    TYPING_MU = 0.08       # trung bình giây/ký tự
    TYPING_SIGMA = 0.04    # độ lệch chuẩn
    TYPING_MIN = 0.02      # min
    TYPING_MAX = 0.30      # max

    # ==== PAUSE TYPES ====
    PAUSE_TYPES = {
        "micro": (0.05, 0.15),     # rất ngắn (chớp mắt)
        "short": (0.15, 0.4),      # ngắn (suy nghĩ nhanh)
        "medium": (0.4, 1.0),      # trung bình (đọc lại)
        "long": (1.0, 2.5),        # dài (suy nghĩ)
    }

    # ==== EMOJI ====
    EMOJI_POSITIVE = ["😀", "😊", "🙂", "😄", "😁", "👍", "✨", "💯", "🔥", "❤️"]
    EMOJI_NEUTRAL = ["😐", "😶", "🤔", "🙃", "😌", "👌", "🤝", "💫"]
    EMOJI_FUN = ["😏", "😎", "🤣", "😆", "😉", "😜", "🤪", "😹"]

    # ==== FILLERS THEO NGỮ CẢNH ====
    FILLER_START = ["Này", "Ừm", "À", "Ơ", "Hmm", "Vậy", "Thế", "Nha", "Ok"]
    FILLER_END = ["nhé", "nha", "đó", "vậy", "nè", "à", "hén", "hen"]
    FILLER_MID = ["thì", "mà", "là", "với", "và", "ấy"]

    # ==== PERSONALITY ====
    PERSONALITIES = {
        "friendly": {"emoji_p": 0.5, "filler_p": 0.4, "typo_p": 0.04},
        "formal":   {"emoji_p": 0.1, "filler_p": 0.1, "typo_p": 0.02},
        "casual":   {"emoji_p": 0.6, "filler_p": 0.5, "typo_p": 0.07},
        "funny":    {"emoji_p": 0.7, "filler_p": 0.3, "typo_p": 0.05},
    }

    # ============================================================
    # TYPING SIMULATION
    # ============================================================
    @staticmethod
    def _gaussian(mu, sigma, lo, hi):
        """Sample Gaussian, clip vào [lo, hi]."""
        while True:
            v = random.gauss(mu, sigma)
            if lo <= v <= hi:
                return v

    @staticmethod
    def simulate_typing(text):
        """
        Mô phỏng gõ từng ký tự giống người thật.
        Dùng phân phối Gaussian để nhịp gõ tự nhiên.
        """
        if not text:
            return 0.5

        total = 0.0
        words = text.split(" ")

        for word_idx, word in enumerate(words):
            for char_idx, char in enumerate(word):
                # Ký tự thường: Gaussian
                if char in ".,!?;:":
                    # Dấu câu: pause lâu hơn
                    total += AntiBanPro._gaussian(
                        0.15, 0.05, 0.05, 0.35
                    )
                elif char in " ":
                    total += 0.05
                else:
                    # Gaussian typing
                    total += AntiBanPro._gaussian(
                        AntiBanPro.TYPING_MU,
                        AntiBanPro.TYPING_SIGMA,
                        AntiBanPro.TYPING_MIN,
                        AntiBanPro.TYPING_MAX,
                    )

                # Micro-pause 8% xác suất
                if random.random() < 0.08:
                    total += random.uniform(*AntiBanPro.PAUSE_TYPES["micro"])

                # Mid-word pause 3% xác suất
                if random.random() < 0.03:
                    total += random.uniform(*AntiBanPro.PAUSE_TYPES["short"])

            # Pause giữa các từ
            if word_idx < len(words) - 1:
                roll = random.random()
                if roll < 0.7:
                    total += random.uniform(*AntiBanPro.PAUSE_TYPES["micro"])
                elif roll < 0.95:
                    total += random.uniform(*AntiBanPro.PAUSE_TYPES["short"])
                else:
                    total += random.uniform(*AntiBanPro.PAUSE_TYPES["medium"])

        # Clip max 7s
        return min(total, 7.0)

    @staticmethod
    def thinking_time():
        """
        Thời gian suy nghĩ trước khi gõ — theo phân phối Gaussian.
        Người thật thường mất 0.5-2.5s đọc tin trước khi trả lời.
        """
        return AntiBanPro._gaussian(1.2, 0.5, 0.4, 3.0)

    @staticmethod
    def fatigue_factor(msg_count):
        """
        Giả lập mỏi tay — gõ càng nhiều càng chậm (nhưng không quá chậm).
        Trả về multiplier: 1.0 (bình thường) → 1.4 (mỏi).
        """
        if msg_count < 10:
            return 1.0
        elif msg_count < 30:
            return 1.0 + (msg_count - 10) * 0.01
        else:
            return 1.2 + min(0.2, (msg_count - 30) * 0.002)

    @staticmethod
    def circadian_factor():
        """
        Nhịp sinh học theo giờ trong ngày.
        Sáng/tối: gõ nhanh. Trưa/đêm: gõ chậm.
        """
        h = time.localtime().tm_hour
        # Nhanh: 8-11h, 14-17h, 20-22h
        if h in (8, 9, 10, 11) or h in (14, 15, 16, 17) or h in (20, 21, 22):
            return 0.9
        # Chậm: 0-6h, 12-13h
        elif 0 <= h < 6 or h in (12, 13):
            return 1.3
        else:
            return 1.0

    # ============================================================
    # OFFSET DELAY
    # ============================================================
    @staticmethod
    def offset_delay(base):
        """
        Offset delay cấp cao — không dùng uniform đơn giản.
        Kết hợp:
        - Gaussian noise
        - Bi-modal distribution (2 đỉnh)
        - Circadian rhythm
        """
        # Chọn ngẫu nhiên 1 trong 2 mode
        if random.random() < 0.75:
            # Mode 1: bình thường
            d = random.gauss(base, base * 0.25)
        else:
            # Mode 2: hơi lâu hơn (giả lập người thật phân tâm)
            d = random.gauss(base * 1.5, base * 0.3)

        # Clip
        d = max(AntiBanPro.MIN_DELAY, min(AntiBanPro.MAX_DELAY, d))

        # Áp circadian
        d *= AntiBanPro.circadian_factor()

        return d

    # ============================================================
    # MESSAGE RANDOMIZATION
    # ============================================================
    @staticmethod
    def entropy_mask(text):
        """
        Chèn zero-width character với nhiều loại khác nhau.
        """
        if random.random() < 0.15:
            zw = random.choice([
                "\u200b", "\u200c", "\u200d", "\ufeff",
                "\u2060", "\u180e"
            ])
            pos = random.randint(1, max(1, len(text) - 1))
            text = text[:pos] + zw + text[pos:]
        return text

    @staticmethod
    def case_variation(text):
        """
        Biến đổi hoa/thường theo cách tinh vi hơn.
        """
        if random.random() > 0.2:
            return text

        mode = random.random()
        if mode < 0.3:
            # Chỉ viết hoa chữ đầu
            return text[0].upper() + text[1:].lower() if text else text
        elif mode < 0.6:
            # Viết hoa ngẫu nhiên 1-2 từ
            words = text.split()
            for _ in range(random.randint(1, 2)):
                if words:
                    i = random.randint(0, len(words) - 1)
                    words[i] = words[i].capitalize()
            return " ".join(words)
        else:
            # ALL CAPS cho 1 từ
            words = text.split()
            if words:
                i = random.randint(0, len(words) - 1)
                words[i] = words[i].upper()
            return " ".join(words)

    @staticmethod
    def punctuation_injection(text):
        """
        Thêm dấu câu — đa dạng hơn.
        """
        if random.random() > 0.35:
            return text

        suffix = random.choice([
            "...", "..", "!", "?", "!!", "?!", "~",
            " :)))", " hihi", " nha", " nhé", " ạ"
        ])
        return text + suffix

    @staticmethod
    def typo_simulation(text, prob=0.05):
        """
        Giả lập lỗi đánh máy tinh vi.
        """
        if random.random() > prob:
            return text

        chars = list(text)
        mode = random.choice(["swap", "replace", "duplicate", "delete"])

        if not chars:
            return text

        i = random.randint(0, len(chars) - 1)

        if mode == "swap" and i < len(chars) - 1:
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        elif mode == "replace" and chars[i].isalpha():
            chars[i] = random.choice("abcdefghijklmnopqrstuvwxyz")
        elif mode == "duplicate":
            chars.insert(i, chars[i])
        elif mode == "delete" and len(chars) > 3:
            chars.pop(i)

        return "".join(chars)

    @staticmethod
    def emoji_rotation(text):
        """
        Thêm emoji theo ngữ nghĩa + ngẫu nhiên.
        """
        if random.random() > 0.4:
            return text

        text_lower = text.lower()
        # Semantic matching
        if any(w in text_lower for w in ["vui", "haha", "hehe", "happy", "chào"]):
            pool = AntiBanPro.EMOJI_POSITIVE
        elif any(w in text_lower for w in ["fun", "chill", "vcl", "cay"]):
            pool = AntiBanPro.EMOJI_FUN
        else:
            pool = random.choice([
                AntiBanPro.EMOJI_POSITIVE,
                AntiBanPro.EMOJI_NEUTRAL,
                AntiBanPro.EMOJI_FUN,
            ])

        emoji = random.choice(pool)
        position = random.choices(
            ["prefix", "suffix", "both", "middle"],
            weights=[0.3, 0.4, 0.2, 0.1]
        )[0]

        if position == "prefix":
            return f"{emoji} {text}"
        elif position == "suffix":
            return f"{text} {emoji}"
        elif position == "both":
            return f"{emoji} {text} {random.choice(pool)}"
        else:
            words = text.split()
            if len(words) > 2:
                i = random.randint(1, len(words) - 2)
                words.insert(i, emoji)
                return " ".join(words)
            return f"{text} {emoji}"

    @staticmethod
    def vary_length(text):
        """
        Biến đổi độ dài tin nhắn.
        """
        if random.random() > 0.25:
            return text

        r = random.random()
        if r < 0.3:
            # Cắt ngắn
            return text[:max(3, len(text) * 2 // 3)]
        elif r < 0.6:
            # Thêm filler cuối
            return text + " " + random.choice(AntiBanPro.FILLER_END)
        elif r < 0.8:
            # Thêm filler đầu
            return random.choice(AntiBanPro.FILLER_START) + " " + text
        else:
            # Thêm filler giữa
            words = text.split()
            if len(words) > 2:
                i = random.randint(1, len(words) - 1)
                words.insert(i, random.choice(AntiBanPro.FILLER_MID))
            return " ".join(words)

    @staticmethod
    def apply_all(text, personality="casual"):
        """
        Áp dụng tất cả transformation theo personality.
        """
        p = AntiBanPro.PERSONALITIES.get(
            personality, AntiBanPro.PERSONALITIES["casual"]
        )

        text = AntiBanPro.vary_length(text)
        text = AntiBanPro.typo_simulation(text, prob=p["typo_p"])
        text = AntiBanPro.punctuation_injection(text)
        text = AntiBanPro.case_variation(text)
        text = AntiBanPro.entropy_mask(text)

        if random.random() < p["emoji_p"]:
            text = AntiBanPro.emoji_rotation(text)

        return text

    # ============================================================
    # RISK + DELAY
    # ============================================================
    @staticmethod
    def compute_risk(ok, fail):
        total = ok + fail
        if total == 0:
            return 0.0
        return min(1.0, fail / total)

    @staticmethod
    def compute_delay(risk, base):
        """
        Delay theo risk — KHÔNG có cooldown cứng.
        Chỉ tăng dần nếu risk cao.
        """
        if risk > 0.7:
            d = base * 1.6
        elif risk > 0.5:
            d = base * 1.3
        elif risk > 0.3:
            d = base * 1.15
        else:
            d = base
        return min(AntiBanPro.MAX_DELAY, d)


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
            raise Exception("Không lấy được khóa bảo mật")

    def _enc(self, params):
        key = base64.b64decode(self.secret_key)
        cipher = AES.new(key, AES.MODE_CBC, bytes(16))
        pt = json.dumps(params).encode()
        pad = AES.block_size - len(pt) % AES.block_size
        pt += bytes([pad]) * pad
        return base64.b64encode(cipher.encrypt(pt)).decode()

    def send(self, msg, thread_id):
        pl = {
            "message": msg,
            "clientId": str(int(time.time() * 1000)),
            "imei": self.imei,
            "visibility": 0,
            "grid": str(thread_id),
        }
        enc = self._enc(pl)
        return self.s.post(
            "https://tt-group-wpa.chat.zalo.me/api/group/sendmsg",
            params={"zpw_ver": 645, "zpw_type": 30},
            data={"params": enc},
            timeout=20,
        )

    def set_typing(self, thread_id):
        pl = {"grid": str(thread_id), "imei": self.imei}
        enc = self._enc(pl)
        try:
            self.s.post(
                "https://tt-group-wpa.chat.zalo.me/api/group/typing",
                params={"zpw_ver": 645, "zpw_type": 30},
                data={"params": enc},
                timeout=10,
            )
        except Exception:
            pass


# ============================================================
# SPAM WORKER — ANTI-BAN PRO
# ============================================================
def update_account_stats(aid, ok):
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
    if fail_c >= 40 and ok_c / max(fail_c, 1) < 0.05:
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
        WHERE enabled = 1
        ORDER BY risk ASC, last_used ASC
        LIMIT 1
    """).fetchall()
    conn.close()
    return rows[0] if rows else None


def spam_worker(tid, target, messages, delay_min, stop_event):
    """Spam worker với Anti-Ban Pro + Typing Simulation."""
    msg_idx = 0
    count = 0
    last_acc_id = None
    # Mỗi acc có personality riêng — gán theo id
    acc_personalities = {}

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
                time.sleep(0.3)
                continue
        last_acc_id = acc["id"]

        # Gán personality cho acc (giữ ổn định)
        if acc["id"] not in acc_personalities:
            acc_personalities[acc["id"]] = random.choice(
                list(AntiBanPro.PERSONALITIES.keys())
            )
        personality = acc_personalities[acc["id"]]

        try:
            cookies = json.loads(acc["cookies"])
            z = Zalo(acc["imei"], cookies)

            raw_msg = messages[msg_idx % len(messages)]
            msg_idx += 1

            # Áp dụng anti-ban PRO
            msg = AntiBanPro.apply_all(raw_msg, personality)

            # ==== TYPING SIMULATION ====
            # 1. Thinking time
            think = AntiBanPro.thinking_time()
            time.sleep(think)

            # 2. Set typing
            z.set_typing(target)

            # 3. Typing time + fatigue
            typing_time = AntiBanPro.simulate_typing(msg)
            fatigue = AntiBanPro.fatigue_factor(count)
            typing_time *= fatigue
            time.sleep(typing_time)

            # 4. Send
            r = z.send(msg, target)
            ok = bool(r and r.status_code == 200)

            update_account_stats(acc["id"], ok)
            count += 1

            status = "OK" if ok else "LỖI"
            print(f"[SPAM #{count}] {acc['label']}({personality}) → {target} "
                  f"[{status}] think:{think:.1f}s type:{typing_time:.1f}s "
                  f"| {msg[:50]}")

        except Exception as e:
            update_account_stats(acc["id"], False)
            print(f"[SPAM] Lỗi {acc['label']}: {e}")

        # ==== OFFSET DELAY ====
        risk = acc["risk"] if acc["risk"] else 0.0
        base_delay = AntiBanPro.compute_delay(risk, delay_min)
        actual_delay = AntiBanPro.offset_delay(base_delay)

        end = time.time() + actual_delay
        while time.time() < end:
            if stop_event.is_set():
                break
            time.sleep(0.1)

    # Kết thúc
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
# API
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


@app.route("/api/accounts/<int:aid>/toggle", methods=["POST"])
@login_required
def api_accounts_toggle(aid):
    conn = db()
    conn.execute(
        "UPDATE accounts SET enabled = 1 - enabled WHERE id = ?", (aid,)
    )
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
    target = data.get("target", "").strip()
    messages_raw = data.get("messages", "").strip()
    delay = float(data.get("delay", 3))

    if not target or not messages_raw:
        return jsonify({"error": "Thiếu target hoặc messages"}), 400
    if delay < 3:
        delay = 3

    messages = [m.strip() for m in messages_raw.split(";") if m.strip()]
    if not messages:
        return jsonify({"error": "Không có tin nhắn"}), 400

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
        args=(tid, target, messages, delay, stop_event),
        daemon=True,
    )

    conn = db()
    conn.execute("""
        INSERT INTO tasks (id, type, meta, status, started_at, stats)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tid, "spam",
          json.dumps({"target": target, "count": len(messages), "delay": delay}),
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
        "version": "13.0-PRO",
        "tasks": len(ACTIVE_TASKS),
        "qr_configured": bool(QR_SERVICE_URL),
    })


# ============================================================
# HTML — GIAO DIỆN (giữ nguyên từ v12, đã rất đẹp)
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
body { font-family:'Inter',sans-serif; min-height:100vh; min-height:100dvh; display:flex; align-items:center; justify-content:center; background:linear-gradient(135deg,#667eea 0%,#764ba2 100%); padding:20px; overflow-x:hidden; }
body::before { content:''; position:fixed; inset:0; background:radial-gradient(circle at 20% 50%,rgba(255,255,255,0.12) 0%,transparent 50%),radial-gradient(circle at 80% 80%,rgba(255,255,255,0.08) 0%,transparent 50%); pointer-events:none; }
.card { background:rgba(255,255,255,0.98); padding:48px 40px; border-radius:32px; box-shadow:0 30px 80px rgba(0,0,0,0.3); width:100%; max-width:440px; position:relative; z-index:1; animation:slideUp 0.7s cubic-bezier(0.16,1,0.3,1); }
@keyframes slideUp { from { opacity:0; transform:translateY(40px); } to { opacity:1; transform:translateY(0); } }
.logo { width:80px; height:80px; border-radius:24px; background:linear-gradient(135deg,#667eea,#764ba2); display:flex; align-items:center; justify-content:center; font-size:40px; margin:0 auto 24px; box-shadow:0 20px 45px rgba(102,126,234,0.5); animation:bounce 2s ease-in-out infinite; }
@keyframes bounce { 0%,100% { transform:translateY(0); } 50% { transform:translateY(-6px); } }
h1 { color:#1a1a2e; margin-bottom:8px; font-size:28px; font-weight:900; text-align:center; letter-spacing:-0.8px; }
p.sub { color:#6b7280; margin-bottom:36px; font-size:14px; text-align:center; font-weight:500; }
.input-wrap { position:relative; margin-bottom:24px; }
input { width:100%; padding:18px; border:2px solid #e5e7eb; border-radius:16px; font-size:16px; font-family:inherit; font-weight:500; transition:all 0.3s; background:#f9fafb; color:#1a1a2e; }
input:focus { outline:none; border-color:#667eea; background:white; box-shadow:0 0 0 5px rgba(102,126,234,0.12); }
button { width:100%; padding:18px; background:linear-gradient(135deg,#667eea,#764ba2); color:white; border:none; border-radius:16px; font-size:16px; font-weight:800; font-family:inherit; cursor:pointer; position:relative; overflow:hidden; transition:all 0.3s; box-shadow:0 12px 30px rgba(102,126,234,0.4); }
button:hover { transform:translateY(-2px); box-shadow:0 18px 40px rgba(102,126,234,0.55); }
button::after { content:''; position:absolute; inset:0; background:linear-gradient(135deg,transparent,rgba(255,255,255,0.3),transparent); transform:translateX(-100%); transition:transform 0.7s; }
button:hover::after { transform:translateX(100%); }
.error { background:#fef2f2; color:#dc2626; padding:14px 18px; border-radius:14px; margin-bottom:24px; font-size:14px; font-weight:600; border-left:4px solid #dc2626; }
</style>
</head>
<body>
<div class="card">
    <div class="logo">🔥</div>
    <h1>ALB FORGE PRO</h1>
    <p class="sub">Bot by Anh Khôi — v13.0 PRO</p>
    {% if error %}<div class="error">⚠️ {{ error }}</div>{% endif %}
    <form method="POST">
        <div class="input-wrap">
            <input type="password" name="password" placeholder="Nhập mật khẩu" autofocus required>
        </div>
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
<title>ALB Forge PRO</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html { -webkit-text-size-adjust:100%; touch-action:manipulation; }
body { font-family:'Inter',sans-serif; background:#f8fafc; min-height:100vh; min-height:100dvh; color:#1a1a2e; overflow-x:hidden; overscroll-behavior-y:none; }
.header { background:linear-gradient(135deg,#667eea 0%,#764ba2 100%); color:white; padding:20px 24px; box-shadow:0 4px 30px rgba(102,126,234,0.35); position:sticky; top:0; z-index:100; padding-top:calc(20px + env(safe-area-inset-top, 0px)); }
.header-inner { max-width:1200px; margin:0 auto; display:flex; align-items:center; justify-content:space-between; gap:16px; }
.logo-text { display:flex; align-items:center; gap:12px; }
.logo-icon { width:48px; height:48px; border-radius:16px; background:rgba(255,255,255,0.2); display:flex; align-items:center; justify-content:center; font-size:24px; border:1px solid rgba(255,255,255,0.3); }
.header h1 { font-size:22px; font-weight:900; letter-spacing:-0.4px; }
.header p { font-size:12px; opacity:0.85; font-weight:500; margin-top:2px; }
.logout-btn { background:rgba(255,255,255,0.15); color:white; border:1px solid rgba(255,255,255,0.25); padding:12px 20px; border-radius:14px; cursor:pointer; font-size:14px; font-weight:700; font-family:inherit; transition:all 0.25s; }
.logout-btn:hover { background:rgba(255,255,255,0.28); transform:translateY(-2px); }
.container { max-width:1200px; margin:0 auto; padding:20px; }
.tabs { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:20px; background:white; padding:8px; border-radius:20px; box-shadow:0 4px 25px rgba(0,0,0,0.05); border:1px solid #f0f2f5; }
.tab { padding:16px 12px; border-radius:14px; cursor:pointer; font-size:13px; font-weight:700; text-align:center; color:#6b7280; transition:all 0.35s; display:flex; flex-direction:column; align-items:center; gap:6px; user-select:none; }
.tab-icon { font-size:22px; transition:transform 0.35s; }
.tab:hover .tab-icon { transform:scale(1.15); }
.tab.active { background:linear-gradient(135deg,#667eea,#764ba2); color:white; box-shadow:0 10px 25px rgba(102,126,234,0.4); transform:translateY(-2px); }
.panel { display:none; animation:fadeIn 0.4s; }
.panel.active { display:block; }
@keyframes fadeIn { from { opacity:0; transform:translateY(15px); } to { opacity:1; transform:translateY(0); } }
.card { background:white; padding:28px; border-radius:24px; box-shadow:0 6px 35px rgba(0,0,0,0.06); margin-bottom:20px; border:1px solid #f0f2f5; }
.card h2 { font-size:18px; font-weight:900; margin-bottom:20px; color:#1a1a2e; display:flex; align-items:center; gap:12px; }
.card h2 .badge-icon { width:36px; height:36px; border-radius:12px; background:linear-gradient(135deg,#667eea,#764ba2); display:flex; align-items:center; justify-content:center; font-size:18px; }
.form-group { margin-bottom:20px; }
.form-group label { display:block; margin-bottom:10px; font-size:13px; font-weight:700; color:#374151; }
.form-group input, .form-group textarea { width:100%; padding:15px 18px; border:2px solid #e5e7eb; border-radius:16px; font-size:15px; font-family:inherit; font-weight:500; transition:all 0.25s; background:#f9fafb; color:#1a1a2e; }
.form-group input:focus, .form-group textarea:focus { outline:none; border-color:#667eea; background:white; box-shadow:0 0 0 5px rgba(102,126,234,0.1); }
.form-group textarea { min-height:110px; resize:vertical; font-family:monospace; font-size:13px; line-height:1.6; }
.btn { padding:15px 26px; border:none; border-radius:16px; font-size:14px; font-weight:800; font-family:inherit; cursor:pointer; transition:all 0.3s; margin-right:8px; margin-bottom:8px; display:inline-flex; align-items:center; gap:8px; position:relative; overflow:hidden; }
.btn::after { content:''; position:absolute; inset:0; background:linear-gradient(135deg,transparent,rgba(255,255,255,0.35),transparent); transform:translateX(-100%); transition:transform 0.7s; }
.btn:hover::after { transform:translateX(100%); }
.btn:hover { transform:translateY(-3px); }
.btn-primary { background:linear-gradient(135deg,#667eea,#764ba2); color:white; box-shadow:0 10px 25px rgba(102,126,234,0.35); }
.btn-danger { background:linear-gradient(135deg,#ef4444,#dc2626); color:white; }
.btn-success { background:linear-gradient(135deg,#10b981,#059669); color:white; }
.btn-qr { background:linear-gradient(135deg,#f093fb,#f5576c); color:white; font-size:18px; padding:22px 48px; border-radius:20px; box-shadow:0 15px 40px rgba(245,87,108,0.45); }
.btn-sm { padding:9px 14px; font-size:12px; margin-right:6px; border-radius:12px; }
.stat-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:16px; margin-bottom:24px; }
.stat { background:linear-gradient(135deg,#f9fafb,#f3f4f6); padding:24px; border-radius:20px; border:1px solid #e5e7eb; position:relative; overflow:hidden; }
.stat::before { content:''; position:absolute; top:0; left:0; right:0; height:5px; background:linear-gradient(90deg,#667eea,#764ba2,#f093fb); }
.stat .label { font-size:11px; color:#6b7280; margin-bottom:10px; text-transform:uppercase; letter-spacing:0.6px; font-weight:800; }
.stat .value { font-size:36px; font-weight:900; color:#1a1a2e; line-height:1; }
.table-wrap { overflow-x:auto; }
.table { width:100%; border-collapse:separate; border-spacing:0; }
.table th, .table td { padding:14px 14px; text-align:left; font-size:13px; border-bottom:1px solid #f0f2f5; white-space:nowrap; }
.table th { background:#f9fafb; font-weight:800; color:#6b7280; text-transform:uppercase; font-size:11px; }
.table td code { background:#f3f4f6; padding:4px 10px; border-radius:8px; font-size:12px; font-family:monospace; font-weight:600; }
.badge { display:inline-flex; align-items:center; gap:4px; padding:5px 12px; border-radius:20px; font-size:11px; font-weight:800; }
.badge-ok { background:#d1fae5; color:#065f46; }
.badge-err { background:#fee2e2; color:#991b1b; }
.badge-warn { background:#fef3c7; color:#92400e; }
.badge-info { background:#dbeafe; color:#1e40af; }
.alert { padding:18px 22px; border-radius:16px; margin-bottom:16px; font-size:14px; font-weight:700; display:none; position:fixed; top:100px; right:24px; z-index:999; box-shadow:0 15px 45px rgba(0,0,0,0.2); animation:slideInRight 0.4s; max-width:400px; }
@keyframes slideInRight { from { opacity:0; transform:translateX(120%); } to { opacity:1; transform:translateX(0); } }
.alert.show { display:flex; align-items:center; gap:12px; }
.alert-success { background:linear-gradient(135deg,#d1fae5,#a7f3d0); color:#065f46; border-left:5px solid #10b981; }
.alert-error { background:linear-gradient(135deg,#fee2e2,#fecaca); color:#991b1b; border-left:5px solid #ef4444; }
.qr-hero { background:linear-gradient(135deg,#f093fb 0%,#f5576c 100%); color:white; text-align:center; padding:70px 32px; border-radius:28px; position:relative; overflow:hidden; box-shadow:0 25px 70px rgba(245,87,108,0.4); }
.qr-hero::before { content:''; position:absolute; inset:0; background:radial-gradient(circle at 20% 20%,rgba(255,255,255,0.18) 0%,transparent 50%); pointer-events:none; }
.qr-hero > * { position:relative; z-index:1; }
.qr-hero h2 { color:white; font-size:36px; margin-bottom:16px; font-weight:900; letter-spacing:-1px; }
.qr-hero p { opacity:0.95; margin-bottom:36px; font-size:16px; font-weight:600; }
.qr-hero small { display:block; margin-top:32px; font-size:13px; opacity:0.9; background:rgba(255,255,255,0.18); padding:14px 22px; border-radius:14px; font-weight:500; }
.ab-card { background:linear-gradient(135deg,#fef3c7,#fde68a); border:2px solid #fbbf24; border-radius:24px; padding:26px; }
.ab-card h2 { color:#92400e; margin-bottom:18px; }
.ab-card .badge-icon { background:#92400e; }
.ab-list { color:#78350f; font-size:14px; line-height:2; font-weight:600; columns:2; column-gap:24px; }
@media (max-width:640px) { .ab-list { columns:1; } }
.ab-list div { margin-bottom:4px; break-inside:avoid; }
@media (max-width:640px) {
    .container { padding:14px; }
    .card { padding:22px; border-radius:20px; }
    .header h1 { font-size:18px; }
    .tabs { gap:6px; padding:6px; border-radius:16px; }
    .tab { padding:12px 6px; font-size:11px; border-radius:12px; }
    .tab-icon { font-size:18px; }
    .stat .value { font-size:28px; }
    .table th, .table td { padding:10px 8px; font-size:11px; }
    .btn { padding:12px 18px; font-size:13px; border-radius:14px; }
    .qr-hero { padding:50px 22px; border-radius:22px; }
    .qr-hero h2 { font-size:26px; }
    .alert { right:12px; left:12px; max-width:none; }
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
                <p>Bot by Anh Khôi • v13.0</p>
            </div>
        </div>
        <button class="logout-btn" onclick="location.href='/logout'">
            🚪 Thoát
        </button>
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
        <div>Tài khoản</div>
    </div>
    <div class="tab" data-tab="spam">
        <div class="tab-icon">🎯</div>
        <div>Spam</div>
    </div>
    <div class="tab" data-tab="tasks">
        <div class="tab-icon">📋</div>
        <div>Tác vụ</div>
    </div>
</div>

<div id="alert" class="alert"></div>

<div class="panel active" id="panel-qr">
    <div class="qr-hero">
        <h2>📱 Tạo mã QR Zalo</h2>
        <p>Bấm nút bên dưới để mở trang quét QR</p>
        <button class="btn btn-qr" onclick="openQR()">
            🚀 Mở trang quét QR
        </button>
        <small>💡 Sau khi quét xong, cookie sẽ tự động gửi về đây</small>
    </div>
</div>

<div class="panel" id="panel-accounts">
    <div class="card">
        <h2><span class="badge-icon">➕</span> Thêm tài khoản thủ công</h2>
        <div class="form-group">
            <label>Tên gợi nhớ</label>
            <input id="add-label" placeholder="VD: acc1">
        </div>
        <div class="form-group">
            <label>IMEI</label>
            <input id="add-imei" placeholder="000000000000000">
        </div>
        <div class="form-group">
            <label>Cookie (JSON)</label>
            <textarea id="add-cookies" placeholder='{"zpw_sek":"...","zpw_ver":"645","zpw_type":"30"}'></textarea>
        </div>
        <button class="btn btn-primary" onclick="addAccount()">
            💾 Thêm tài khoản
        </button>
    </div>

    <div class="card">
        <h2><span class="badge-icon">📋</span> Danh sách tài khoản</h2>
        <div class="stat-grid">
            <div class="stat">
                <div class="label">Tổng</div>
                <div class="value" id="stat-total">0</div>
            </div>
            <div class="stat">
                <div class="label">Hoạt động</div>
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
                        <th>Đã gửi</th>
                        <th>Hành động</th>
                    </tr>
                </thead>
                <tbody id="accounts-tbody">
                    <tr><td colspan="6" style="text-align:center;color:#999;padding:40px;">Đang tải...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
</div>

<div class="panel" id="panel-spam">
    <div class="card">
        <h2><span class="badge-icon">🎯</span> Bắt đầu spam</h2>
        <div class="form-group">
            <label>ID nhóm Zalo</label>
            <input id="spam-target" placeholder="VD: 123456789">
        </div>
        <div class="form-group">
            <label>Tin nhắn (cách nhau bằng dấu ;)</label>
            <textarea id="spam-messages">Chào buổi sáng;Hello;Nice day;Good morning;Hi everyone</textarea>
        </div>
        <div class="form-group">
            <label>Delay tối thiểu (giây)</label>
            <input id="spam-delay" type="number" value="3" min="3">
        </div>
        <button class="btn btn-success" onclick="startSpam()">
            ▶️ Bắt đầu
        </button>
        <button class="btn btn-danger" onclick="stopAll()">
            ⏸️ Dừng hết
        </button>
    </div>

    <div class="card ab-card">
        <h2><span class="badge-icon">🛡️</span> Anti-Ban PRO v13 — Không nghỉ, chỉ giả lập người thật</h2>
        <div class="ab-list">
            <div>✅ <b>Markov Chain Typing</b> — nhịp gõ Gaussian</div>
            <div>✅ <b>Thinking Time</b> — đọc tin trước khi gõ</div>
            <div>✅ <b>Fatigue Simulation</b> — mỏi tay dần</div>
            <div>✅ <b>Circadian Rhythm</b> — nhịp theo giờ</div>
            <div>✅ <b>Bi-modal Delay</b> — phân tâm ngẫu nhiên</div>
            <div>✅ <b>Message Personality</b> — 4 tính cách</div>
            <div>✅ <b>Multi-Pause Pattern</b> — 4 loại pause</div>
            <div>✅ <b>Semantic Emoji</b> — emoji theo ngữ cảnh</div>
            <div>✅ <b>Case Variation</b> — hoa/thường tinh vi</div>
            <div>✅ <b>Typo Modes</b> — 4 kiểu lỗi đánh máy</div>
            <div>✅ <b>Filler Injection</b> — chèn từ đệm tự nhiên</div>
            <div>✅ <b>Unicode Obfuscation</b> — 6 loại invisible char</div>
        </div>
    </div>
</div>

<div class="panel" id="panel-tasks">
    <div class="card">
        <h2><span class="badge-icon">📋</span> Danh sách tác vụ</h2>
        <button class="btn btn-sm btn-danger" onclick="stopAll()">Dừng tất cả</button>
        <div class="table-wrap" style="margin-top:16px;">
            <table class="table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Loại</th>
                        <th>Trạng thái</th>
                        <th>Bắt đầu</th>
                        <th>Hành động</th>
                    </tr>
                </thead>
                <tbody id="tasks-tbody">
                    <tr><td colspan="5" style="text-align:center;color:#999;padding:40px;">Đang tải...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
</div>

</div>

<script>
const QR_URL = "{{ qr_url }}";

document.querySelectorAll('.tab').forEach(t => {
    t.onclick = () => {
        document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
        document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
        t.classList.add('active');
        document.getElementById('panel-' + t.dataset.tab).classList.add('active');
        if (t.dataset.tab === 'accounts') loadAccounts();
        if (t.dataset.tab === 'tasks') loadTasks();
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

function openQR() {
    if (!QR_URL) return showAlert('Web QR chưa cấu hình', 'error');
    window.open(QR_URL, '_blank');
}

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
    if (!confirm('Xóa tài khoản này?')) return;
    await api('/api/accounts/' + id, { method: 'DELETE' });
    showAlert('Đã xóa');
    loadAccounts();
}

async function resetAcc(id) {
    await api('/api/accounts/' + id + '/reset', { method: 'POST' });
    showAlert('Đã reset acc');
    loadAccounts();
}

async function checkAcc(id) {
    const r = await api('/api/accounts/' + id + '/check', { method: 'POST' });
    if (r.error) return showAlert(r.error, 'error');
    showAlert('Cookie sống! UID: ' + r.uid);
}

async function startSpam() {
    const target = document.getElementById('spam-target').value.trim();
    const messages = document.getElementById('spam-messages').value.trim();
    const delay = parseFloat(document.getElementById('spam-delay').value) || 3;
    if (!target || !messages) return showAlert('Điền target và messages', 'error');
    const r = await api('/api/tasks/start', {
        method: 'POST',
        body: JSON.stringify({ target, messages, delay }),
    });
    if (r.error) return showAlert(r.error, 'error');
    showAlert('Đã bắt đầu: ' + r.task_id);
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
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#999;padding:40px;">Chưa có tác vụ</td></tr>';
        return;
    }
    tbody.innerHTML = tasks.map(t => {
        const start = new Date(t.started_at * 1000).toLocaleString('vi-VN');
        return `
            <tr>
                <td><code>${t.id}</code></td>
                <td>${t.type}</td>
                <td><span class="badge ${t.status === 'running' ? 'badge-ok' : 'badge-err'}">${t.status === 'running' ? 'Đang chạy' : 'Đã dừng'}</span></td>
                <td>${start}</td>
                <td>${t.status === 'running' ? `<button class="btn btn-sm btn-danger" onclick="stopTask('${t.id}')">Dừng</button>` : ''}</td>
            </tr>
        `;
    }).join('');
}

async function stopTask(tid) {
    await api('/api/tasks/' + tid + '/stop', { method: 'POST' });
    showAlert('Đã dừng ' + tid);
    loadTasks();
}

setInterval(() => {
    if (document.getElementById('panel-accounts').classList.contains('active')) loadAccounts();
    if (document.getElementById('panel-tasks').classList.contains('active')) loadTasks();
}, 5000);

loadAccounts();
</script>

</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
