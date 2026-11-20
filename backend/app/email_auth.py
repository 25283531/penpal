"""Email accounts, verification codes, image captchas, SMTP mail, privacy text.

M1 additions to the anonymous device auth in auth.py. Nothing here
touches letters/characters/points: an email account is bound to one
device_id created at registration, and login-email returns the same
bearer token format as issue_token(device_id).

Security notes:
- Passwords: scrypt hash only (same format as the admin password in
  admin.py). Never plaintext, never logged.
- Verification codes: only the SHA256 of the 6-digit code is stored;
  the code itself is never stored, never returned by any API, never
  logged. Codes expire after 15 minutes, max 5 verify attempts.
- Captchas: only the SHA256 of the 4-char code is stored; the token is
  single-use and expires after 5 minutes. The PNG is rendered with a
  tiny built-in 5x7 bitmap font and stdlib zlib+struct only — no new
  binary dependency (Pillow is not installed).
- SMTP password is a secret setting (smtp.password): masked in the
  admin API like the LLM keys, never returned, never logged.
"""
import hashlib
import hmac
import re
import secrets
import smtplib
import struct
import zlib
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.text import MIMEText

from . import database

_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1

CODE_TTL_MINUTES = 15
CODE_MAX_ATTEMPTS = 5
CAPTCHA_TTL_MINUTES = 5
CAPTCHA_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PRIVACY_UPDATED_AT = "2026-11-20"
PRIVACY_TEXT = (
    "笔友隐私说明（2026-11-20更新）\n"
    "笔友里的人物都是 AI 生成的虚拟人物，不是真人；你们的关系是知己，不是恋人或伴侣。\n"
    "信件只支持文字，最长 2000 字。信件内容在服务端加密保存，管理员看不到任何信件内容，只能看到汇总数字。\n"
    "我们收集的信息：邮箱、信件内容、设备编号。邮箱只用于验证身份、发送验证码和找回密码。\n"
    "未成年人不能建立虚拟亲密关系；连续使用 2 小时会有休息提醒。\n"
    "结束一段关系后，30 天内可以重新联系；超过 30 天，App 里不再显示这段关系，服务端仍加密留存，仅依法留存，不会再向你展示。\n"
    "退出或注销账号请在 App 内操作或联系管理员；注销后账号不可再用，服务端仍加密留存，仅依法留存。"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(email) and len(email) <= 254 and EMAIL_RE.match(email) is not None


# ---------- passwords (scrypt, same format as admin.py) ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        parts = stored.split("$")
        if len(parts) != 6 or parts[0] != "scrypt":
            return False
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = bytes.fromhex(parts[4])
        dk = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32
        )
        return hmac.compare_digest(dk.hex(), parts[5])
    except (ValueError, TypeError):
        return False


# ---------- verification codes ----------

def _code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def create_verification_code(email: str, purpose: str) -> str:
    """Create a 6-digit code, store only its hash, return the code itself
    (callers must send it by mail immediately, never log or return it)."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = _now() + timedelta(minutes=CODE_TTL_MINUTES)
    database.create_verification_code(email, purpose, _code_hash(code), expires.isoformat())
    return code


def code_expired(code_row: dict) -> bool:
    try:
        expires = datetime.fromisoformat(code_row["expires_at"])
    except (ValueError, KeyError):
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return _now() >= expires


def check_code(email: str, code: str) -> tuple[bool, str]:
    """Validate a code. Returns (ok, reason): reason is one of
    'ok', 'missing', 'expired', 'too_many_attempts', 'wrong'.
    A wrong code increments the attempt counter."""
    row = database.get_latest_unused_code(email)
    if row is None:
        return False, "missing"
    if code_expired(row):
        return False, "expired"
    if row["attempts"] >= CODE_MAX_ATTEMPTS:
        return False, "too_many_attempts"
    if not hmac.compare_digest(_code_hash((code or "").strip()), row["code_hash"]):
        database.increment_code_attempts(row["id"])
        return False, "wrong"
    return True, "ok"


def consume_code(email: str) -> None:
    row = database.get_latest_unused_code(email)
    if row:
        database.mark_code_used(row["id"])


# ---------- captchas (stdlib PNG, 5x7 bitmap font) ----------

_FONT: dict[str, tuple[str, ...]] = {
    "0": (" ### ", "#   #", "#  ##", "# # #", "##  #", "#   #", " ### "),
    "1": ("  #  ", " ##  ", "  #  ", "  #  ", "  #  ", "  #  ", " ### "),
    "2": (" ### ", "#   #", "    #", "   # ", "  #  ", " #   ", "#####"),
    "3": ("#### ", "    #", "    #", " ### ", "    #", "    #", "#### "),
    "4": ("   # ", "  ## ", " # # ", "#  # ", "#####", "   # ", "   # "),
    "5": ("#####", "#    ", "#### ", "    #", "    #", "#   #", " ### "),
    "6": (" ### ", "#    ", "#    ", "#### ", "#   #", "#   #", " ### "),
    "7": ("#####", "    #", "   # ", "   # ", "  #  ", "  #  ", "  #  "),
    "8": (" ### ", "#   #", "#   #", " ### ", "#   #", "#   #", " ### "),
    "9": (" ### ", "#   #", "#   #", " ####", "    #", "    #", " ### "),
    "A": (" ### ", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"),
    "B": ("#### ", "#   #", "#   #", "#### ", "#   #", "#   #", "#### "),
    "C": (" ### ", "#   #", "#    ", "#    ", "#    ", "#   #", " ### "),
    "D": ("#### ", "#   #", "#   #", "#   #", "#   #", "#   #", "#### "),
    "E": ("#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#####"),
    "F": ("#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#    "),
    "G": (" ### ", "#   #", "#    ", "#  ##", "#   #", "#   #", " ### "),
    "H": ("#   #", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"),
    "I": ("###  ", " #   ", " #   ", " #   ", " #   ", " #   ", "###  "),
    "J": ("  ###", "   # ", "   # ", "   # ", "   # ", "   # ", "##   "),
    "K": ("#   #", "#  # ", "# #  ", "##   ", "# #  ", "#  # ", "#   #"),
    "L": ("#    ", "#    ", "#    ", "#    ", "#    ", "#    ", "#####"),
    "M": ("#   #", "## ##", "# # #", "# # #", "#   #", "#   #", "#   #"),
    "N": ("#   #", "##  #", "##  #", "# # #", "#  ##", "#  ##", "#   #"),
    "O": (" ### ", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "),
    "P": ("#### ", "#   #", "#   #", "#### ", "#    ", "#    ", "#    "),
    "Q": (" ### ", "#   #", "#   #", "#   #", "# # #", "#  # ", " ## #"),
    "R": ("#### ", "#   #", "#   #", "#### ", "# #  ", "#  # ", "#   #"),
    "S": (" ####", "#    ", "#    ", " ### ", "    #", "    #", "#### "),
    "T": ("#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "),
    "U": ("#   #", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "),
    "V": ("#   #", "#   #", "#   #", "#   #", "#   #", " # # ", "  #  "),
    "W": ("#   #", "#   #", "#   #", "# # #", "# # #", "## ##", "#   #"),
    "X": ("#   #", "#   #", " # # ", "  #  ", " # # ", "#   #", "#   #"),
    "Y": ("#   #", "#   #", " # # ", "  #  ", "  #  ", "  #  ", "  #  "),
    "Z": ("#####", "    #", "   # ", "  #  ", " #   ", "#    ", "#####"),
}


def _png_bytes(width: int, height: int, pixels: list[list[tuple[int, int, int]]]) -> bytes:
    raw = b"".join(
        b"\x00" + b"".join(bytes(px) for px in row) for row in pixels
    )

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def render_captcha_png(code: str) -> bytes:
    scale = 4
    gap = 6
    pad = 10
    char_w, char_h = 5 * scale, 7 * scale
    width = pad * 2 + len(code) * char_w + (len(code) - 1) * gap
    height = pad * 2 + char_h
    bg = (245, 240, 230)
    pixels = [[bg for _ in range(width)] for _ in range(height)]
    rng = secrets.SystemRandom()
    for i, ch in enumerate(code):
        glyph = _FONT.get(ch.upper(), _FONT["?"] if "?" in _FONT else _FONT["A"])
        color = (rng.randint(20, 90), rng.randint(20, 90), rng.randint(20, 110))
        x0 = pad + i * (char_w + gap)
        y0 = pad + rng.randint(-2, 3)
        for gy, row in enumerate(glyph):
            for gx, cell in enumerate(row):
                if cell != "#":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        x, y = x0 + gx * scale + dx, y0 + gy * scale + dy
                        if 0 <= x < width and 0 <= y < height:
                            pixels[y][x] = color
    # noise: dots + two lines
    for _ in range(140):
        x, y = rng.randrange(width), rng.randrange(height)
        pixels[y][x] = (rng.randint(150, 210), rng.randint(150, 210), rng.randint(150, 210))
    for _ in range(2):
        x1, y1 = rng.randrange(width), rng.randrange(height)
        x2, y2 = rng.randrange(width), rng.randrange(height)
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        for s in range(steps + 1):
            x = x1 + (x2 - x1) * s // steps
            y = y1 + (y2 - y1) * s // steps
            if 0 <= x < width and 0 <= y < height:
                pixels[y][x] = (180, 170, 150)
    return _png_bytes(width, height, pixels)


def create_captcha() -> tuple[str, str, bytes]:
    """Create a captcha: returns (token, code, png). The code is only
    returned here so the caller can render it; only its hash is stored.
    Tests use this helper to obtain a valid token+code pair."""
    code = "".join(secrets.choice(CAPTCHA_CHARS) for _ in range(4))
    token = secrets.token_urlsafe(24)
    expires = _now() + timedelta(minutes=CAPTCHA_TTL_MINUTES)
    database.store_captcha(token, _code_hash(code.upper()), expires.isoformat())
    return token, code, render_captcha_png(code)


def check_captcha(token: str | None, text: str | None) -> tuple[bool, str]:
    """Validate a one-time captcha token+text. The token is deleted on
    any attempt (success or fail). Returns (ok, reason)."""
    if not token or not text:
        return False, "missing"
    row = database.consume_captcha(token)
    if row is None:
        return False, "invalid"
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except ValueError:
        return False, "invalid"
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if _now() >= expires:
        return False, "expired"
    if not hmac.compare_digest(_code_hash(text.strip().upper()), row["code_hash"]):
        return False, "wrong"
    return True, "ok"


# ---------- SMTP ----------

class SmtpNotConfigured(Exception):
    pass


def smtp_configured() -> bool:
    host = database.get_setting("smtp.host", "").strip()
    user = database.get_setting("smtp.user", "").strip()
    return bool(host) and bool(user)


def send_email(to_email: str, subject: str, body: str) -> None:
    """Send one mail via the admin-configured SMTP server. Raises
    SmtpNotConfigured when host/user are not set. Monkeypatched in
    tests (app.email_auth.send_email) — no real mail is sent there."""
    host = database.get_setting("smtp.host", "").strip()
    user = database.get_setting("smtp.user", "").strip()
    password = database.get_setting("smtp.password", "")
    if not host or not user:
        raise SmtpNotConfigured("smtp not configured")
    try:
        port = int(database.get_setting("smtp.port", "465") or "465")
    except ValueError:
        port = 465
    use_ssl = database.get_setting("smtp.ssl", "1") == "1"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = user
    msg["To"] = to_email
    if use_ssl:
        server = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        server = smtplib.SMTP(host, port, timeout=15)
        if port == 587:
            server.starttls()
    try:
        server.login(user, password)
        server.sendmail(user, [to_email], msg.as_string())
    finally:
        try:
            server.quit()
        except Exception:
            pass


def send_verification_email(email: str, code: str, purpose: str) -> None:
    action = "重置密码" if purpose == "reset" else "验证邮箱"
    subject = "笔友：你的验证码"
    body = (
        f"你好，\n\n"
        f"你正在{action}，验证码是：{code}\n\n"
        f"验证码 15 分钟内有效，请勿告诉他人。\n\n"
        f"—— 笔友"
    )
    send_email(email, subject, body)
