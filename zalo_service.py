# ==============================================================================
# Bản quyền © Phạm Anh Khôi (Verified ) — Ricki Vip
# Mọi quyền được bảo hộ. Nghiêm cấm sao chép hoặc phân phối trái phép.
# ==============================================================================

import json
import time
import random
import base64
import requests
from Crypto.Cipher import AES

from config import (
    ZALO_PALETTE, utf16_len, apply_antiband_zalo_v4
)

class Zalo:
    def __init__(self, imei, cookies):
        self.imei = imei
        self.cookies_str = cookies
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": "https://chat.zalo.me/",
            "Origin": "https://chat.zalo.me"
        })
        self._parse_cookies()
        self.secret_key = None
        self._login()

    def _parse_cookies(self):
        raw = self.cookies_str.strip()
        if raw.startswith("["):
            try:
                arr = json.loads(raw)
                for item in arr:
                    n = item.get("name")
                    v = item.get("value")
                    if n and v:
                        self.session.cookies.set(n, v, domain=".zalo.me")
                return
            except Exception:
                pass
        pairs = raw.split(";")
        for p in pairs:
            if "=" in p:
                k, v = p.strip().split("=", 1)
                self.session.cookies.set(k.strip(), v.strip(), domain=".zalo.me")

    def _login(self):
        url = f"https://chat.zalo.me/api/login/getServerInfo?imei={self.imei}"
        r = self.session.get(url, timeout=10)
        data = r.json()
        if data.get("error_code") != 0:
            raise Exception("Phiên đăng nhập hết hạn hoặc Cookie không hợp lệ")
        info = data.get("data", {})
        self.secret_key = info.get("zpw_enk")
        if not self.secret_key:
            zpw = self.session.cookies.get("zpw_sek")
            if zpw:
                self.secret_key = zpw
        if not self.secret_key:
            raise Exception("Không thể lấy Secret Key Zalo")

    def _pad(self, s):
        bs = AES.block_size
        return s + (bs - len(s) % bs) * chr(bs - len(s) % bs).encode()

    def _unpad(self, s):
        return s[:-ord(s[len(s)-1:])]

    def encrypt(self, data_str):
        raw_key = self.secret_key
        key = raw_key.ljust(32, "0").encode("utf-8")[:32] if len(raw_key) < 32 else raw_key.encode("utf-8")[:32]
        iv = bytes([0] * 16)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded = self._pad(data_str.encode("utf-8"))
        enc = cipher.encrypt(padded)
        return base64.b64encode(enc).decode("utf-8")

    def decrypt(self, enc_str):
        raw_key = self.secret_key
        key = raw_key.ljust(32, "0").encode("utf-8")[:32] if len(raw_key) < 32 else raw_key.encode("utf-8")[:32]
        iv = bytes([0] * 16)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        dec = cipher.decrypt(base64.b64decode(enc_str))
        return self._unpad(dec).decode("utf-8")

    def get_user_profile(self):
        try:
            url = "https://chat.zalo.me/api/profile/get"
            params = {"params": self.encrypt("{}"), "imei": self.imei}
            r = self.session.post(url, data=params, timeout=10)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                return info.get("data", {})
        except Exception:
            pass
        return {}

    def get_friend_map(self):
        fmap = {}
        try:
            url = "https://chat.zalo.me/api/friend/getfriends"
            params = {"params": self.encrypt("{}"), "imei": self.imei}
            r = self.session.post(url, data=params, timeout=10)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                for item in info.get("data", []):
                    uid = str(item.get("userId") or item.get("uid") or "")
                    name = item.get("displayName") or item.get("zaloName") or item.get("name")
                    if uid and name:
                        fmap[uid] = name
        except Exception:
            pass
        return fmap

    def get_conversations(self):
        boxes = []
        try:
            url = "https://chat.zalo.me/api/group/getlg"
            params = {"params": self.encrypt("{}"), "imei": self.imei}
            r = self.session.post(url, data=params, timeout=10)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                for g in info.get("data", {}).get("gridInfoMap", {}).values():
                    boxes.append({
                        "id": str(g.get("grid")),
                        "name": "[Zalo Nhóm] " + g.get("name", "Nhóm không tên"),
                        "type": "group",
                        "platform": "zalo"
                    })
        except Exception:
            pass
        try:
            url = "https://chat.zalo.me/api/friend/getfriends"
            params = {"params": self.encrypt("{}"), "imei": self.imei}
            r = self.session.post(url, data=params, timeout=10)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                for f in info.get("data", []):
                    boxes.append({
                        "id": str(f.get("userId")),
                        "name": "[Zalo Bạn] " + (f.get("displayName") or "Bạn bè"),
                        "type": "user",
                        "platform": "zalo"
                    })
        except Exception:
            pass
        return boxes

    def get_group_members(self, grid):
        """Lấy danh sách thành viên nhóm với đầy đủ UID và Tên thật từ memInfoMap"""
        members = []
        fmap = self.get_friend_map()
        try:
            pl = json.dumps({"grid": str(grid)})
            params = {"params": self.encrypt(pl), "imei": self.imei}
            r = self.session.post("https://chat.zalo.me/api/group/getgridinfo", data=params, timeout=10)
            res = r.json()
            if res.get("data"):
                plain = self.decrypt(res["data"])
                info = json.loads(plain)
                gdata = info.get("data", {})
                mem_list = gdata.get("memList", []) or gdata.get("members", [])
                mem_info_map = gdata.get("memInfoMap", {})

                for m in mem_list:
                    if isinstance(m, dict):
                        uid = str(m.get("uid") or m.get("id") or m.get("userId") or "")
                        info_item = mem_info_map.get(uid, {}) if isinstance(mem_info_map, dict) else {}
                        raw_name = m.get("dName") or m.get("displayName") or m.get("name") or info_item.get("dName") or info_item.get("displayName")
                    else:
                        uid = str(m)
                        info_item = mem_info_map.get(uid, {}) if isinstance(mem_info_map, dict) else {}
                        raw_name = info_item.get("dName") or info_item.get("displayName") or info_item.get("name")

                    if not uid:
                        continue
                    final_name = fmap.get(uid) or raw_name or f"Thành viên {uid[-4:]}"
                    members.append({"id": uid, "name": final_name})
        except Exception:
            pass
        return members

    def build_colored_message(self, raw_text, color_mode="rainbow", fixed_color="red",
                              is_heading=True, color_offset=0, use_badge=True,
                              tag_header="", antiband=True):
        """
        Xây dựng tin nhắn màu Zalo chuẩn xác 100% với đơn vị đo UTF-16 code units.
        Đảm bảo không bao giờ bị lệch vị trí màu khi chèn tag hoặc ký tự đặc biệt.
        """
        raw_lines = raw_text.split("\n")
        processed_lines = []

        for idx, line in enumerate(raw_lines):
            clean_line = line.strip()
            if not clean_line:
                processed_lines.append("")
                continue

            if antiband:
                clean_line = apply_antiband_zalo_v4(clean_line)

            if color_mode == "rainbow":
                color_idx = (idx + color_offset) % len(ZALO_PALETTE)
                col = ZALO_PALETTE[color_idx]
            elif color_mode == "random":
                col = random.choice(ZALO_PALETTE)
            elif color_mode == "fixed":
                col = next((c for c in ZALO_PALETTE if c["id"] == fixed_color), ZALO_PALETTE[0])
            else:
                col = ZALO_PALETTE[0]

            prefix = ""
            if use_badge:
                prefix += col["badge"] + " "
            if is_heading:
                prefix = "# " + prefix

            display_line = prefix + clean_line
            processed_lines.append((display_line, col))

        current_u16_pos = utf16_len(tag_header) if tag_header else 0
        first_hex = ZALO_PALETTE[0]["hex"]
        styles = []
        body_lines_text = []

        for idx, item in enumerate(processed_lines):
            if isinstance(item, tuple):
                display_line, col = item
                clean_hex = col["hex"].lstrip("#").lower()
                if idx == 0:
                    first_hex = clean_hex

                line_len = utf16_len(display_line)
                styles.append({
                    "start": current_u16_pos,
                    "len": line_len,
                    "st": f"c_{clean_hex}"
                })
                body_lines_text.append(display_line)
                current_u16_pos += line_len + 1
            else:
                body_lines_text.append("")
                current_u16_pos += 1

        body_text = "\n".join(body_lines_text)
        final_message = tag_header + body_text if tag_header else body_text

        return final_message, styles, "#" + first_hex

    def build_mentions_payload(self, mentions=None, tag_all=False, tag_mode="rotate", mention_index=0):
        """Tạo tag tokens và mảng mentions payload chuẩn xác 100% cho Zalo"""
        tag_tokens = []
        if tag_all:
            tag_tokens.append({"token": "@All", "uid": "-1", "type": 1})

        if mentions and len(mentions) > 0:
            if tag_mode == "all":
                for u in mentions:
                    uname = (u.get("name") or "Bạn").strip()
                    tag_tokens.append({"token": f"@{uname}", "uid": str(u.get("id")), "type": 0})
            else:
                target_user = mentions[mention_index % len(mentions)]
                uname = (target_user.get("name") or "Bạn").strip()
                tag_tokens.append({"token": f"@{uname}", "uid": str(target_user.get("id")), "type": 0})

        if not tag_tokens:
            return "", []

        tags_str = " ".join([t["token"] for t in tag_tokens])
        m_arr = []
        curr_pos = 0
        for t in tag_tokens:
            tlen = utf16_len(t["token"])
            m_arr.append({
                "uid": t["uid"],
                "pos": curr_pos,
                "len": tlen,
                "type": t["type"]
            })
            curr_pos += tlen + 1

        return tags_str, m_arr

    def send_adv(self, raw_text, target_id, color_mode="rainbow", fixed_color="red",
                 is_group=True, mentions=None, tag_all=False, tag_mode="rotate",
                 mention_index=0, is_heading=True, color_offset=0, use_badge=True,
                 antiband=True, tag_pos="head"):

        tags_str, m_arr = self.build_mentions_payload(
            mentions=mentions, tag_all=tag_all, tag_mode=tag_mode,
            mention_index=mention_index
        )

        tag_header = (tags_str + "\n") if (tags_str and tag_pos == "head") else ""

        final_msg, styles, hex_color = self.build_colored_message(
            raw_text, color_mode=color_mode, fixed_color=fixed_color,
            is_heading=is_heading, color_offset=color_offset, use_badge=use_badge,
            tag_header=tag_header, antiband=antiband
        )

        if tags_str and tag_pos == "tail":
            base_len = utf16_len(final_msg)
            final_msg += " " + tags_str
            m_arr_tail = []
            c_pos = base_len + 1
            for m in m_arr:
                m_copy = dict(m)
                m_copy["pos"] = c_pos
                m_arr_tail.append(m_copy)
                c_pos += m["len"] + 1
            m_arr = m_arr_tail

        ts = int(time.time() * 1000)

        if is_group:
            url = "https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
            pl = {
                "grid": str(target_id),
                "message": final_msg,
                "clientId": ts,
                "client_id": ts,
                "msgType": 1,
                "styles": styles,
                "msgColor": hex_color,
                "imei": self.imei,
                "visibility": 0
            }
            if m_arr:
                pl["mentions"] = m_arr
                pl["mention"] = m_arr
        else:
            url = "https://chat.zalo.me/api/message/sms"
            pl = {
                "toid": str(target_id),
                "message": final_msg,
                "clientId": ts,
                "client_id": ts,
                "msgType": 1,
                "imei": self.imei
            }

        enc = self.encrypt(json.dumps(pl))
        params = {"params": enc, "imei": self.imei}
        r = self.session.post(url, data=params, timeout=12)
        res = r.json()
        if res.get("error_code") == 0:
            return True, res
        return False, res
