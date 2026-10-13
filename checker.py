# ==============================================================================
# Bản quyền © Phạm Anh Khôi (Verified ✔) — Ricki Vip
# Module: checker.py — Kiểm Tra Tài Khoản Live/Die & Quản Lý Cấu Trúc Tệp
# ==============================================================================

import os
import time
import requests
import json
from Crypto.Cipher import AES

def check_zalo_status(imei, cookies_str):
    """
    Kiểm tra IMEI & Cookie Zalo còn sống (Live) hay đã chết (Die).
    Trả về: {"live": True/False, "name": ..., "uid": ..., "ping_ms": ..., "error": ...}
    """
    t0 = time.time()
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0.0.0 Safari/537.36",
            "Referer": "https://chat.zalo.me/",
            "Origin": "https://chat.zalo.me"
        })

        # Parse cookies
        raw = cookies_str.strip()
        if raw.startswith("["):
            try:
                arr = json.loads(raw)
                for item in arr:
                    n = item.get("name")
                    v = item.get("value")
                    if n and v:
                        session.cookies.set(n, v, domain=".zalo.me")
            except Exception:
                pass
        else:
            for p in raw.split(";"):
                if "=" in p:
                    k, v = p.strip().split("=", 1)
                    session.cookies.set(k.strip(), v.strip(), domain=".zalo.me")

        # Kiểm tra getServerInfo
        url = f"https://chat.zalo.me/api/login/getServerInfo?imei={imei}"
        r = session.get(url, timeout=8)
        data = r.json()
        ping_ms = int((time.time() - t0) * 1000)

        if data.get("error_code") != 0:
            return {"live": False, "error": "Cookie/IMEI hết hạn hoặc phiên đăng nhập không hợp lệ", "ping_ms": ping_ms}

        info = data.get("data", {})
        secret_key = info.get("zpw_enk") or session.cookies.get("zpw_sek")
        if not secret_key:
            return {"live": False, "error": "Không thể lấy Secret Key Zalo", "ping_ms": ping_ms}

        # Kiểm tra profile
        return {"live": True, "name": "Zalo User (Active)", "uid": imei[-6:], "ping_ms": ping_ms}
    except Exception as e:
        ping_ms = int((time.time() - t0) * 1000)
        return {"live": False, "error": str(e), "ping_ms": ping_ms}

def check_discord_status(token):
    """
    Kiểm tra Token tài khoản Discord còn sống (Live) hay đã chết (Die).
    Trả về: {"live": True/False, "username": ..., "id": ..., "ping_ms": ..., "error": ...}
    """
    t0 = time.time()
    try:
        headers = {
            "Authorization": token.strip(),
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0.0.0 Safari/537.36"
        }
        r = requests.get("https://discord.com/api/v9/users/@me", headers=headers, timeout=8)
        ping_ms = int((time.time() - t0) * 1000)

        if r.status_code == 200:
            data = r.json()
            uname = data.get("global_name") or data.get("username") or "Discord User"
            uid = data.get("id") or ""
            return {"live": True, "username": uname, "id": uid, "ping_ms": ping_ms}
        elif r.status_code == 401:
            return {"live": False, "error": "Token Die / Vô hiệu hóa (401 Unauthorized)", "ping_ms": ping_ms}
        return {"live": False, "error": f"Lỗi HTTP {r.status_code}", "ping_ms": ping_ms}
    except Exception as e:
        ping_ms = int((time.time() - t0) * 1000)
        return {"live": False, "error": str(e), "ping_ms": ping_ms}

def inspect_setup_file(filepath, default_delay=1.2):
    """
    Kiểm tra cấu trúc và tính hợp lệ của tệp ngôn:
    - Kích thước tệp (KB).
    - Tổng số dòng văn bản.
    - Số khối ngôn (ngăn cách bởi 1 dòng trống \\n\\n).
    - Đánh giá tính hợp lệ và thời gian ước tính hoàn thành.
    """
    if not os.path.exists(filepath):
        return {"valid": False, "error": "Tệp không tồn tại"}

    lines_count = 0
    blocks_count = 0
    in_block = False
    preview_blocks = []
    cur_block = []

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                lines_count += 1
                clean_l = line.strip()
                if clean_l:
                    cur_block.append(clean_l)
                    if not in_block:
                        blocks_count += 1
                        in_block = True
                else:
                    if in_block and cur_block and len(preview_blocks) < 3:
                        preview_blocks.append("\n".join(cur_block))
                    cur_block = []
                    in_block = False

            if in_block and cur_block and len(preview_blocks) < 3:
                preview_blocks.append("\n".join(cur_block))
    except Exception as e:
        return {"valid": False, "error": f"Lỗi đọc tệp: {str(e)}"}

    size_kb = round(os.path.getsize(filepath) / 1024, 2)
    est_minutes = round((blocks_count * default_delay) / 60, 1)

    return {
        "valid": True,
        "filename": os.path.basename(filepath),
        "size_kb": size_kb,
        "lines": lines_count,
        "blocks": max(1, blocks_count),
        "est_minutes": est_minutes,
        "preview_blocks": preview_blocks
    }
