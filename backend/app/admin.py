"""Web admin console backend (/api/v1/admin/*).

Auth: no env-var password. First visit sets a password (scrypt hash
stored in the settings table); afterwards a login form issues a random
session token stored in the DB and sent as an HttpOnly cookie. All
admin endpoints require a valid session.

PRIVACY RED LINE: the admin console only ever sees AGGREGATE numbers —
totals, letters per character, per-type violation counts — EXCEPT for
the audited letter-view path below (/letters … /view + /audit-log).
That path is the single exception, and it is gated: a view needs a
stated reason, decrypts in memory only, and writes one append-only
audit row (time, operator, letter id, reason, result — never content)
before the content is returned. If the audit write fails, the view is
refused. There is no delete endpoint for the audit log.
"""
import hashlib
import hmac
import secrets

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Request, Response

from .errors import ApiError
from pydantic import BaseModel, Field

from . import crypto, database
from .llm import PROVIDER_NAMES

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

ADMIN_COOKIE = "penpal_admin_session"

_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1


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


def _password_set() -> bool:
    return bool(database.get_setting("admin.password_hash", ""))


def _new_session(response: Response) -> None:
    token, max_age = database.create_admin_session()
    response.set_cookie(
        ADMIN_COOKIE, token, max_age=max_age, httponly=True, samesite="lax", path="/",
    )


def require_admin(request: Request) -> str:
    token = request.cookies.get(ADMIN_COOKIE)
    if not token or not database.admin_session_valid(token):
        raise ApiError(401, "admin_login_required", "admin login required")
    return token


def _is_admin(request: Request) -> bool:
    token = request.cookies.get(ADMIN_COOKIE)
    return bool(token) and database.admin_session_valid(token)


class PasswordIn(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


@router.get("/status")
def admin_status(request: Request):
    return {"password_set": _password_set(), "authenticated": _is_admin(request)}


@router.post("/setup")
def admin_setup(body: PasswordIn, response: Response):
    if _password_set():
        raise ApiError(400, "admin_password_already_set", "admin password already set")
    database.set_setting("admin.password_hash", hash_password(body.password))
    _new_session(response)
    return {"ok": True}


@router.post("/login")
def admin_login(body: PasswordIn, response: Response):
    stored = database.get_setting("admin.password_hash", "")
    if not stored or not verify_password(body.password, stored):
        raise ApiError(401, "admin_wrong_password", "wrong password")
    _new_session(response)
    return {"ok": True}


@router.post("/logout")
def admin_logout(request: Request, response: Response):
    token = request.cookies.get(ADMIN_COOKIE)
    if token:
        database.delete_admin_session(token)
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return {"ok": True}


@router.get("/dashboard")
def admin_dashboard(request: Request):
    require_admin(request)
    return database.dashboard_stats()


@router.get("/scheduler-runs")
def admin_scheduler_runs(request: Request, limit: int = 20):
    """Recent automatic reply-scheduler passes (counts only — no
    device ids, no letter text). Lets an operator see whether due
    replies are being generated, queued for want of an LLM key, or
    failing, without looking at any single user's data."""
    require_admin(request)
    return {
        "summary": database.scheduler_summary(),
        "runs": database.list_scheduler_runs(limit=max(1, min(limit, 100))),
    }


# ---------- audited letter view + audit log ----------

# The only permitted reasons for viewing a letter's content. The
# reason is mandatory: a view without one is refused (400) before any
# decryption happens.
AUDIT_REASONS = ("执法检查", "用户申诉", "故障排查", "其他")


def _operator_label(session_token: str) -> str:
    """Operator label for audit rows: a short digest of the admin
    session token — enough to tell sessions apart, never the token."""
    return "admin:" + hashlib.sha256(session_token.encode("utf-8")).hexdigest()[:12]


class LetterViewIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=20)
    note: str | None = Field(None, max_length=500)


@router.get("/letters")
def admin_list_letters(
    request: Request, character_id: str | None = None,
    direction: str | None = None, status: str | None = None,
    device_digest: str | None = None, since: str | None = None,
    until: str | None = None, limit: int = 100,
):
    """Metadata-only letter list (person, time, status, device digest).
    Letter content is NEVER included here."""
    require_admin(request)
    if direction is not None and direction not in ("user", "ai"):
        raise ApiError(400, "invalid_direction", "direction must be 'user' or 'ai'")
    return database.list_letter_metadata(
        character_id=character_id, direction=direction, status=status,
        device_digest=device_digest, since=since, until=until, limit=limit,
    )


@router.get("/letters/{letter_id}")
def admin_letter_metadata(letter_id: int, request: Request):
    """Metadata for one letter (no content)."""
    require_admin(request)
    raw = database.get_letter_raw(letter_id)
    if raw is None:
        raise ApiError(404, "letter_not_found", "letter not found")
    return {k: v for k, v in raw.items() if k != "text_encrypted"}


@router.post("/letters/{letter_id}/view")
def admin_view_letter(letter_id: int, body: LetterViewIn, request: Request):
    """Decrypt and show one letter's content — audited, always.

    Order of operations (deliberate):
    1. reason is validated first (missing/invalid reason -> 400, no
       decryption, no audit row for a view that never happened);
    2. the letter is decrypted in memory;
    3. the audit row is written BEFORE any content is returned — if
       the audit write fails, the view is refused (503) and no content
       is returned;
    4. a decrypt failure is itself audited (result=decrypt_failed)
       and returns an error, never partial content.
    """
    token = require_admin(request)
    operator = _operator_label(token)
    reason = (body.reason or "").strip()
    if reason not in AUDIT_REASONS:
        raise ApiError(
            400, "audit_reason_required",
            "查看信件必须填写查看原因（执法检查 / 用户申诉 / 故障排查 / 其他）",
        )
    note = (body.note or "").strip() or None
    raw = database.get_letter_raw(letter_id)
    if raw is None:
        try:
            database.record_audit_log(
                operator, "letter_view_failed", letter_id, reason, "not_found", note,
            )
        except Exception:
            pass  # a missing letter is a 404 either way
        raise ApiError(404, "letter_not_found", "letter not found")
    try:
        text = crypto.decrypt_text(raw["text_encrypted"])
        result = "ok"
    except (InvalidToken, ValueError):
        text = None
        result = "decrypt_failed"
    try:
        audit = database.record_audit_log(
            operator,
            "letter_view" if result == "ok" else "letter_view_failed",
            letter_id, reason, result, note,
        )
    except Exception as e:
        raise ApiError(
            503, "audit_log_failed",
            "审计日志写入失败，本次查看已被拒绝",
        ) from e
    if text is None:
        raise ApiError(
            502, "letter_decrypt_failed",
            "信件解密失败（密钥可能已更换或数据损坏），本次查看已记入审计日志",
        )
    meta = {k: v for k, v in raw.items() if k != "text_encrypted"}
    return {**meta, "text": text, "audit_id": audit["id"]}


@router.get("/audit-log")
def admin_audit_log(
    request: Request, letter_id: int | None = None,
    since: str | None = None, until: str | None = None, limit: int = 100,
):
    """Append-only audit log (time, operator, action, letter id,
    reason, result). Audit rows never contain letter content, and
    there is intentionally NO delete endpoint for this log."""
    require_admin(request)
    return database.list_audit_logs(
        letter_id=letter_id, since=since, until=until, limit=limit,
    )


@router.get("/key-status")
def admin_key_status(request: Request):
    """Decryption-key status: whether the key file exists, its path and
    its SHA256 fingerprint (first 12 hex chars). The key value itself
    is never returned. Deployment: DATA_DIR=/app/data, so the file is
    /app/data/.encryption.key inside the container's data volume —
    back it up separately from the database; losing it makes all
    encrypted letters permanently unrecoverable."""
    require_admin(request)
    return crypto.key_status()


SETTABLE_KEYS = set(database.DEFAULT_SETTINGS) - {"admin.password_hash", "auth.jwt_secret"}


def _masked_settings() -> dict[str, str]:
    all_settings = database.get_all_settings()
    out: dict[str, str] = {}
    for key in sorted(SETTABLE_KEYS):
        val = all_settings.get(key, "")
        if key in database.SECRET_SETTINGS:
            out[key] = database.SETTING_MASK if val else ""
        else:
            out[key] = val
    return out


def _validate_settings(values: dict) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, raw in values.items():
        if key not in SETTABLE_KEYS:
            raise ApiError(400, "unknown_setting", f"unknown setting: {key}")
        if key in database.SECRET_SETTINGS:
            if raw is None:
                continue
            val = str(raw)
            if val == database.SETTING_MASK:
                continue
            cleaned[key] = val.strip()
            continue
        if key == "llm.default_provider":
            val = str(raw).strip()
            if val not in PROVIDER_NAMES:
                raise ApiError(400, "unknown_llm_provider", f"unknown LLM provider: {val}")
            cleaned[key] = val
        elif key in ("membership.paywalled", "memory.evolution_enabled",
                     "memory.reflection_enabled") or key.endswith(".enabled"):
            cleaned[key] = "1" if raw in (True, 1, "1", "true", "on") else "0"
        elif key == "memory.consolidation_interval_days":
            try:
                n = int(raw)
            except (TypeError, ValueError):
                raise ApiError(400, "invalid_consolidation_interval", "consolidation interval must be an integer")
            if not 1 <= n <= 7:
                raise ApiError(400, "invalid_consolidation_interval", "consolidation interval must be 1-7 days")
            cleaned[key] = str(n)
        elif key == "smtp.port":
            try:
                n = int(raw)
            except (TypeError, ValueError):
                raise ApiError(400, "invalid_smtp_port", "SMTP port must be an integer")
            if not 1 <= n <= 65535:
                raise ApiError(400, "invalid_smtp_port", "SMTP port must be 1-65535")
            cleaned[key] = str(n)
        elif key == "smtp.ssl":
            cleaned[key] = "1" if raw in (True, 1, "1", "true", "on") else "0"
        elif key in ("membership.price_member_cny", "membership.price_premium_cny"):
            try:
                n = float(raw)
            except (TypeError, ValueError):
                raise ApiError(400, "invalid_price", "price must be a number")
            if n < 0:
                raise ApiError(400, "invalid_price", "price must be >= 0")
            cleaned[key] = str(n)
        else:
            cleaned[key] = str(raw).strip() if raw is not None else ""
    return cleaned


class SettingsIn(BaseModel):
    settings: dict = Field(default_factory=dict)


@router.get("/settings")
def get_settings(request: Request):
    require_admin(request)
    return _masked_settings()


@router.post("/settings")
def set_settings(body: SettingsIn, request: Request):
    require_admin(request)
    cleaned = _validate_settings(body.settings)
    if cleaned:
        database.set_settings(cleaned)
    return _masked_settings()


class MessageIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=2000)
    audience: str = "all"
    active: bool = True


@router.get("/messages")
def admin_list_messages(request: Request):
    require_admin(request)
    return database.list_messages(include_inactive=True)


@router.post("/messages", status_code=201)
def admin_create_message(body: MessageIn, request: Request):
    require_admin(request)
    return database.create_message(body.title.strip(), body.body.strip(), body.audience.strip() or "all")


@router.put("/messages/{msg_id}")
def admin_update_message(msg_id: str, body: MessageIn, request: Request):
    require_admin(request)
    updated = database.update_message(
        msg_id,
        {"title": body.title.strip(), "body": body.body.strip(),
         "audience": body.audience.strip() or "all", "active": 1 if body.active else 0},
    )
    if not updated:
        raise ApiError(404, "message_not_found", "message not found")
    return updated


@router.delete("/messages/{msg_id}")
def admin_delete_message(msg_id: str, request: Request):
    require_admin(request)
    if not database.delete_message(msg_id):
        raise ApiError(404, "message_not_found", "message not found")
    return {"ok": True}


class ActivityIn(BaseModel):
    id: str | None = None
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=2000)
    image_url: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    active: bool = True


@router.get("/activities")
def admin_list_activities(request: Request):
    require_admin(request)
    return database.list_activities(include_inactive=True)


@router.post("/activities", status_code=201)
def admin_create_activity(body: ActivityIn, request: Request):
    require_admin(request)
    return database.create_activity(
        {
            "id": (body.id or "").strip() or None,
            "title": body.title.strip(),
            "body": body.body.strip(),
            "image_url": (body.image_url or "").strip() or None,
            "start_at": (body.start_at or "").strip() or None,
            "end_at": (body.end_at or "").strip() or None,
            "active": body.active,
        }
    )


@router.put("/activities/{act_id}")
def admin_update_activity(act_id: str, body: ActivityIn, request: Request):
    require_admin(request)
    updated = database.update_activity(
        act_id,
        {
            "title": body.title.strip(),
            "body": body.body.strip(),
            "image_url": (body.image_url or "").strip() or None,
            "start_at": (body.start_at or "").strip() or None,
            "end_at": (body.end_at or "").strip() or None,
            "active": 1 if body.active else 0,
        },
    )
    if not updated:
        raise ApiError(404, "activity_not_found", "activity not found")
    return updated


@router.delete("/activities/{act_id}")
def admin_delete_activity(act_id: str, request: Request):
    require_admin(request)
    if not database.delete_activity(act_id):
        raise ApiError(404, "activity_not_found", "activity not found")
    return {"ok": True}
