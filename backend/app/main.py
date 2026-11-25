"""笔友 (Penpal) backend — FastAPI + SQLite. M0, backend only.

Slow letters with virtual pen pals (知己 confidants, never lovers):
a user writes a text-only letter (max 2000 chars) to one of P01–P05;
the character replies once, on a schedule — first letter same day,
then free every 3 days / member+premium daily. One outstanding letter
per character (turn-taking); daily send cap per user per day (free/
member 1, premium 5) — reaching the cap blocks further sends that day
even to a different character.

Anonymous device auth has NO age gate: a fresh device always gets a
token (age stored NULL when unknown), so first launch can always
browse. Email registration takes a birth date (strict YYYY-MM-DD)
and refuses anyone under 18 on the day of registration
(age_under_18) — and a missing birth date is refused outright
(birth_date_required); an `age` number alone never satisfies
registration. The birth date is encrypted at rest and never
returned — APIs only ever expose an `is_adult` flag. Already-
registered accounts are never re-gated. Full minor mode is M2).
Phase 1 is FREE: everyone is on the free tier, no payment is taken;
tier checks are enforced anyway.

Anonymous browsing is READ-ONLY: an anonymous device can look around
but cannot send letters (403 anonymous_letter_forbidden) and earns no
points. Only email-registered accounts write, collect points and hold
relationships; unregistered users pick a virtual-world name at
registration, and data from the anonymous trial period migrates into
the email account once (see merge_device_data). Unverified email
accounts can still send — verification only gates password
change / recovery.

All API keys live in the SQLite settings table (admin console /admin).
User content (letters / memories / persona summaries) is encrypted at
rest (see crypto.py); the admin console only ever sees aggregate
numbers, never user text. A reply is only 'replied' when the LLM
actually generated and stored it — without an LLM key, letters stay
queued (never a fake reply).
"""
import logging
import re
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from . import admin, database, email_auth, evolution, scheduler
from .auth import get_current_device, issue_token, verify_token
from .characters import BY_ID, PHOTO_FILES, public_character
from .content_filter import validate_user_letter
from .errors import (
    ApiError,
    http_exception_handler,
    validation_exception_handler,
)
from .llm import list_llm_providers
from .membership import PHASE1_FREE, delivery_stage, expected_reply_at, reply_due_date, tier_for
from .replies import process_due_replies

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    # Reply scheduler (Bug 1 fix): in-process daemon thread, first pass
    # immediately (clears the backlog of already-due letters), then
    # hourly. Stopped on shutdown; a pass never blocks startup — the
    # first pass runs in the thread, not here.
    scheduler.start_scheduler()
    try:
        yield
    finally:
        scheduler.stop_scheduler()


app = FastAPI(title="笔友 Penpal API", version="0.1.0", lifespan=lifespan)
# Error responses keep their existing `detail` + status, and gain a
# stable top-level `code` (see app/errors.py) for app-side localisation.
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/admin", status_code=302)


@app.get("/admin", include_in_schema=False)
def admin_page():
    path = Path(__file__).resolve().parent / "admin.html"
    return FileResponse(path, media_type="text/html")


# ---------- character photos (shipped inside the image) ----------

# Photos live in the image at backend/app/static/photos/<PID>/<file>.jpg
# — NOT in the /app/data volume (a volume mount would hide/erase them).
# URLs are relative (/static/photos/P01/avatar.jpg); the app prepends
# its built-in base URL. Filenames are immutable per release, so a
# 1-day public cache is safe; unknown ids / filenames 404.
PHOTOS_DIR = Path(__file__).resolve().parent / "static" / "photos"


@app.get("/static/photos/{character_id}/{filename}", include_in_schema=False)
def character_photo(character_id: str, filename: str):
    if character_id not in BY_ID or filename not in PHOTO_FILES:
        raise ApiError(404, "photo_not_found", "photo not found")
    path = PHOTOS_DIR / character_id / filename
    if not path.is_file():
        raise ApiError(404, "photo_not_found", "photo not found")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ---------- schemas ----------

class DeviceAuthIn(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)
    age: int | None = Field(None, ge=1, le=120)
    # New clients send birth_date (18+ gate, wins over age); a
    # supplied `age` is stored when usable but NEVER gates anonymous
    # auth — the 18+ gate lives only on email registration.
    birth_date: str | None = None
    emergency_contact: str | None = Field(None, max_length=128)


class LetterIn(BaseModel):
    character_id: str
    # No max_length here: the 2000-char limit is enforced by
    # validate_user_letter so it returns 400 (not Pydantic's 422).
    text: str = Field(..., min_length=1)


class ProcessDueIn(BaseModel):
    date: str | None = None  # "YYYY-MM-DD"; test/simulation override, default today


class ReferralIn(BaseModel):
    referred_device_id: str = Field(..., min_length=1, max_length=128)


class RegisterIn(BaseModel):
    email: str
    password: str = Field(..., min_length=1, max_length=128)
    age: int | None = Field(None, ge=1, le=120)
    # Birth date (YYYY-MM-DD) is REQUIRED for registration: the 18+
    # gate is computed from it. A bare `age` number never satisfies
    # registration (birth_date_required); when both are sent,
    # birth_date wins and `age` is ignored.
    birth_date: str | None = None
    captcha_token: str | None = None
    captcha_text: str | None = None
    # Virtual-world name (required at registration): 1-20 chars,
    # Chinese / letters / digits only. This is NOT a real name and is
    # never identity-checked; pen pals address the user by it.
    # Length/charset are enforced by _validate_display_name (400
    # invalid_display_name), not by Pydantic, so the error stays the
    # stable code instead of a generic 422.
    display_name: str
    # Anonymous device whose data migrates into this new email account
    # (letters / points / relationships / unlocks). After the merge the
    # anonymous device is retired — the email account is the only
    # identity from then on.
    device_id: str | None = None
    # Anonymous bearer token for the same device (proves ownership);
    # wins over device_id when both are given.
    device_token: str | None = None


class LoginEmailIn(BaseModel):
    email: str
    password: str = Field(..., min_length=1, max_length=128)
    # Anonymous device whose data should be merged into this email
    # account on login (one-time migration, anonymous device retired;
    # see RegisterIn).
    device_id: str | None = None
    device_token: str | None = None


class DisplayNameIn(BaseModel):
    display_name: str  # validated by _validate_display_name (see RegisterIn)


class SendCodeIn(BaseModel):
    email: str
    purpose: str = "verify"
    captcha_token: str | None = None
    captcha_text: str | None = None


class VerifyIn(BaseModel):
    email: str
    code: str


class ChangePasswordIn(BaseModel):
    current_password: str | None = None
    code: str | None = None
    new_password: str = Field(..., min_length=1, max_length=128)


class ForgotPasswordIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    email: str
    code: str
    new_password: str = Field(..., min_length=1, max_length=128)


# ---------- helpers ----------

def _device_plan(device_id: str) -> tuple[dict, dict]:
    device = database.get_device(device_id)
    plan = device["plan"] if device else "free"
    return device, tier_for(plan)


def _public_letter(letter: dict, plan: str = "free") -> dict:
    """Public view of a letter.

    Read times: `user_read_at` is when the user first opened an AI
    reply (first call only, never overwritten); `character_read_at` is
    when the character 'read' the user's letter, derived when the reply
    was generated (replied_at minus up to 3h, clamped inside
    [sent, replied], minute precision — never a faked exact second).
    `read_at` is the legacy alias of `user_read_at`, kept for
    backward compatibility. Old rows read NULL for both — normal.

    Delivery: user letters carry `expected_reply_at` (ISO 8601 date,
    from the same reply_due_date rule used at send time — first letter
    same day, then free +3 days / member+premium +1 day) and
    `delivery_stage` / `delivery_stage_text`, derived from real state
    (sent time, due date, whether a reply was generated, now). AI
    replies carry None for all three.
    """
    is_user = letter["direction"] == "user"
    exp_reply = None
    stage = stage_text = None
    if is_user:
        if letter.get("reply_due_at"):
            exp_reply = letter["reply_due_at"]
        else:
            try:
                sent_date = date.fromisoformat(str(letter["created_at"])[:10])
                exp_reply = expected_reply_at(
                    sent_date, plan, bool(letter.get("is_first"))
                ).isoformat()
            except (ValueError, TypeError):
                exp_reply = None
        char = database.get_character(letter["character_id"])
        stage, stage_text = delivery_stage(
            letter.get("created_at"),
            letter.get("reply_due_at"),
            letter.get("status") == "replied",
            city=(char or {}).get("city") or "",
            name=(char or {}).get("name") or "",
        )
    return {
        "id": letter["id"],
        "character_id": letter["character_id"],
        "direction": letter["direction"],
        "text": letter["text"],
        "status": letter["status"],
        "reply_due_at": letter.get("reply_due_at"),
        "expected_reply_at": exp_reply,
        "delivery_stage": stage,
        "delivery_stage_text": stage_text,
        "is_first": bool(letter.get("is_first")),
        "ai_generated": bool(letter.get("ai_generated")),
        "ai_label": "AI 生成" if letter.get("ai_generated") else None,
        "read_at": letter.get("read_at"),
        "user_read_at": letter.get("user_read_at"),
        "character_read_at": letter.get("character_read_at"),
        "created_at": letter["created_at"],
        "replied_at": letter.get("replied_at"),
    }


# ---------- health / auth ----------

@app.get("/api/v1/health")
def health():
    providers = [p["id"] for p in list_llm_providers() if p["configured"]]
    return {
        "status": "ok",
        "version": app.version,
        "port": 7000,
        "phase1_free": PHASE1_FREE,
        "providers_configured": providers,
        "reply_scheduler": scheduler.scheduler_status(),
    }


def _resolve_registration_age(
    birth_date: str | None, age: int | None,
) -> tuple[int | None, str | None, str]:
    """Resolve the effective age for an EMAIL registration.

    Returns (age, birth_date_iso, age_source). `birth_date` is
    REQUIRED: a missing one is refused outright
    (birth_date_required) — an `age` number alone never satisfies
    registration, so the legacy age-only path cannot slip through.
    When `birth_date` is given it wins: strict YYYY-MM-DD, never a
    future date, and the registrant must be 18+ on the day of
    registration (whole years — the birthday must already have passed
    this year). Failures raise ApiError with stable codes
    (birth_date_required / invalid_birth_date /
    birth_date_in_future / age_under_18).
    """
    if birth_date is None:
        raise ApiError(
            400, "birth_date_required", "请填写出生日期",
        )
    try:
        born = database.parse_birth_date(birth_date)
    except ValueError as e:
        if "future" in str(e):
            raise ApiError(
                400, "birth_date_in_future", "出生日期不能是未来日期",
            ) from e
        raise ApiError(
            400, "invalid_birth_date",
            "出生日期格式不正确，请使用 YYYY-MM-DD",
        ) from e
    effective_age = database.age_from_birth_date(born)
    if effective_age < database.ADULT_AGE:
        raise ApiError(
            400, "age_under_18",
            "不符合使用条件，必须年满 18 周岁才能使用本软件",
        )
    if effective_age > 120:
        raise ApiError(
            400, "invalid_birth_date",
            "出生日期格式不正确，请使用 YYYY-MM-DD",
        )
    return effective_age, born.isoformat(), "birth_date"


@app.post("/api/v1/auth/device")
def auth_device(body: DeviceAuthIn):
    device_id = body.device_id.strip()
    # Anonymous browsing has NO age gate (the 18+ gate lives only on
    # email registration): a fresh device with no age at all must
    # always get a token, and a supplied age / birth date can never
    # fail this call. A birth date sent by an old client is stored
    # when usable (age derived, minor_mode set) and silently ignored
    # when it is not (malformed, future, or out of range) — anonymous
    # auth never returns an age error code in any case.
    birth_date_iso: str | None = None
    effective_age = body.age
    if body.birth_date is not None:
        try:
            born = database.parse_birth_date(body.birth_date)
        except ValueError:
            born = None
        if born is not None:
            derived = database.age_from_birth_date(born)
            if 1 <= derived <= 120:
                birth_date_iso = born.isoformat()
                effective_age = derived
    try:
        device = database.get_or_create_device(
            device_id, age=effective_age, emergency_contact=body.emergency_contact,
            birth_date=birth_date_iso, allow_unknown_age=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # Anonymous browsing earns no points: only email-registered
    # accounts collect login points (see _is_registered).
    if _is_registered(device_id):
        database.award_point(device_id, "login")
    return {
        "token": issue_token(device["device_id"]),
        "device_id": device["device_id"],
        "plan": device["plan"],
        "minor_mode": bool(device["minor_mode"]),
        "age": device["age"],
        # What the stored row actually carries (a pre-existing device
        # keeps its old state — old accounts are never re-gated).
        "is_adult": device.get("is_adult"),
        "age_source": "birth_date" if device.get("has_birth_date") else "legacy_age",
    }


@app.post("/api/v1/auth/login")
def auth_login(device_id: str = Depends(get_current_device)):
    # Anonymous browsing earns no points (see auth_device).
    awarded = database.award_point(device_id, "login") if _is_registered(device_id) else 0
    return {"device_id": device_id, "points_awarded": awarded, "points": database.points_balance(device_id)}


# ---------- email accounts (M1) ----------

def _client_ip(request: Request) -> str:
    if request.client:
        return request.client.host
    return "unknown"


def _require_captcha_or_400(token: str | None, text: str | None) -> None:
    ok, reason = email_auth.check_captcha(token, text)
    if not ok:
        code, detail = {
            "missing": ("captcha_missing", "需要图形验证码"),
            "invalid": ("captcha_invalid", "图形验证码无效或已过期"),
            "expired": ("captcha_expired", "图形验证码已过期"),
            "wrong": ("captcha_wrong", "图形验证码错误"),
        }.get(reason, ("captcha_wrong", "图形验证码错误"))
        raise ApiError(400, code, detail)


def _is_registered(device_id: str) -> bool:
    """True when this device belongs to an email-registered account
    (a row in users) — as opposed to a purely anonymous device.
    Anonymous browsing is read-only: no letters, no points, no
    relationships. Registered-but-unverified accounts count as
    registered (verification only gates password change / recovery)."""
    return database.get_user_by_device(device_id) is not None


def _resolve_link_device(device_id: str | None, device_token: str | None) -> str | None:
    """Anonymous device the client asks to migrate, if any. A
    device_token (anonymous bearer token) proves ownership and wins; a
    bare device_id is accepted too — anonymous ids are unguessable
    client-generated ids and /auth/device already issues a token for
    any claimed id, so this matches the existing trust model. A token
    and an id that disagree are refused."""
    linked = None
    if device_token:
        linked = verify_token(device_token.strip())
    if device_id:
        did = device_id.strip()
        if did:
            if linked is not None and linked != did:
                raise ApiError(400, "device_mismatch", "device_id 与 device_token 不一致")
            linked = did
    return linked


# Virtual-world name: 1-20 chars, Chinese / letters / digits only.
# No real-name check is ever done; the name is only how pen pals
# address the user.
_DISPLAY_NAME_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9]{1,20}$")


def _validate_display_name(value: object) -> str:
    name = value.strip() if isinstance(value, str) else ""
    if not _DISPLAY_NAME_RE.match(name):
        raise ApiError(
            400, "invalid_display_name",
            "虚拟世界姓名为 1-20 字，仅限中文、字母、数字",
        )
    return name


def _public_profile(device_id: str) -> dict:
    device = database.get_device(device_id)
    user = database.get_user_by_device(device_id)
    return {
        "device_id": device_id,
        "email": user["email"] if user else None,
        "display_name": user["display_name"] if user else None,
        "email_verified": bool(user["email_verified"]) if user else False,
        "plan": device["plan"] if device else "free",
    }


@app.post("/api/v1/auth/register")
def auth_register(body: RegisterIn):
    email = email_auth.normalize_email(body.email)
    if not email_auth.valid_email(email):
        raise ApiError(400, "invalid_email", "邮箱格式不正确")
    if len(body.password) < 8:
        raise ApiError(400, "password_too_short", "密码至少 8 位")
    # Birth-date gate first, before the single-use captcha is spent:
    # an under-18 / malformed / future / missing birth date must not
    # burn it. _resolve_registration_age refuses a missing birth date
    # outright — an `age` number alone never registers.
    effective_age, birth_date_iso, age_source = _resolve_registration_age(
        body.birth_date, body.age,
    )
    _require_captcha_or_400(body.captcha_token, body.captcha_text)
    if database.get_user_by_email(email):
        raise ApiError(400, "email_already_registered", "该邮箱已注册")
    display_name = _validate_display_name(body.display_name)
    linked = _resolve_link_device(body.device_id, body.device_token)
    if linked is not None:
        other = database.get_user_by_device(linked)
        if other is not None:
            raise ApiError(409, "device_already_bound", "该设备已绑定其他邮箱账号")
    # The email account is a fresh "email-" device: the only identity
    # from now on. Anonymous data migrates into it (deduped, idempotent)
    # and the anonymous device is retired — it can no longer produce
    # new data.
    device_id = "email-" + secrets.token_hex(12)
    try:
        device = database.get_or_create_device(
            device_id, age=effective_age, birth_date=birth_date_iso,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    migrated = dict(database.ZERO_MERGE)
    if linked is not None and linked != device_id:
        migrated = database.merge_device_data(linked, device_id, retire_source=True)
    database.create_user(
        email, email_auth.hash_password(body.password),
        effective_age if effective_age is not None else device.get("age"),
        device_id,
        display_name=display_name,
        birth_date=birth_date_iso,
    )
    database.award_point(device_id, "login")
    return {
        "token": issue_token(device_id),
        "device_id": device_id,
        "email": email,
        "email_verified": False,
        "display_name": display_name,
        "plan": device["plan"],
        "minor_mode": bool(device["minor_mode"]),
        "age": device["age"],
        # The birth date itself is never returned — at most the
        # already-adult flag, plus which client path supplied the age.
        "is_adult": device.get("is_adult"),
        "age_source": "birth_date" if device.get("has_birth_date") else "legacy_age",
        "linked_anonymous_device": linked is not None,
        "migrated": migrated,
    }


@app.post("/api/v1/auth/login-email")
def auth_login_email(body: LoginEmailIn):
    email = email_auth.normalize_email(body.email)
    user = database.get_user_by_email(email)
    if not user or not email_auth.verify_password(body.password, user["password_hash"]):
        raise ApiError(401, "invalid_credentials", "邮箱或密码错误")
    device_id = user["device_id"]
    linked = _resolve_link_device(body.device_id, body.device_token)
    migrated = dict(database.ZERO_MERGE)
    if linked is not None and linked != device_id:
        # One-time migration for accounts registered before the merge
        # existed: fold the anonymous device's data into the email
        # account (deduped, idempotent) and retire the anonymous
        # device. A device already bound to another email is refused.
        other = database.get_user_by_device(linked)
        if other is not None and other["email"] != email:
            raise ApiError(409, "device_already_bound", "该设备已绑定其他邮箱账号")
        migrated = database.merge_device_data(linked, device_id, retire_source=True)
    database.award_point(device_id, "login")
    device = database.get_device(device_id)
    return {
        "token": issue_token(device_id),
        "device_id": device_id,
        "email": email,
        "email_verified": bool(user["email_verified"]),
        "display_name": user.get("display_name"),
        "plan": device["plan"] if device else "free",
        "migrated": migrated,
    }


@app.get("/api/v1/auth/me")
def auth_me(device_id: str = Depends(get_current_device)):
    """Profile for the 我的 page: email account + virtual-world name.
    Anonymous devices get email/display_name None."""
    return _public_profile(device_id)


@app.patch("/api/v1/auth/display-name")
def auth_update_display_name(body: DisplayNameIn, device_id: str = Depends(get_current_device)):
    """Rename the virtual-world name. Takes effect immediately — the
    next reply generation reads it live from the users row. Email
    accounts only: anonymous devices have no name to rename."""
    user = database.get_user_by_device(device_id)
    if not user:
        raise ApiError(400, "account_email_not_bound", "该账号未绑定邮箱，请先注册邮箱账号")
    name = _validate_display_name(body.display_name)
    database.update_user_display_name(user["email"], name)
    return _public_profile(device_id)


@app.get("/api/v1/auth/captcha")
def auth_captcha():
    token, _code, png = email_auth.create_captcha()
    return Response(
        content=png,
        media_type="image/png",
        headers={"X-Captcha-Token": token, "Cache-Control": "no-store"},
    )


def _captcha_required(email: str, ip: str) -> bool:
    """Captcha is required on send-code after 2 failed send-code
    attempts for that email or that IP within an hour."""
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    return (
        database.count_send_failures(email=email, since=since) >= 2
        or database.count_send_failures(ip=ip, since=since) >= 2
    )


def _request_code(email_raw: str, purpose: str, ip: str,
                  captcha_token: str | None, captcha_text: str | None,
                  captcha_gate: bool = True) -> dict:
    """Shared send-code / forgot-password flow. Responses are generic
    and never reveal whether an email is registered."""
    email = email_auth.normalize_email(email_raw)
    if not email_auth.valid_email(email) or purpose not in ("verify", "reset"):
        database.record_send_failure(email, ip)
        raise ApiError(400, "invalid_request", "请求无效")
    if captcha_gate and _captcha_required(email, ip):
        try:
            _require_captcha_or_400(captcha_token, captcha_text)
        except HTTPException:
            database.record_send_failure(email, ip)
            raise
    if not email_auth.smtp_configured():
        raise ApiError(503, "email_not_configured", "email not configured")
    now = datetime.now(timezone.utc)
    # per-email 1/min, 5/hour; per-IP 10/hour
    since_min = (now - timedelta(minutes=1)).isoformat()
    since_hour = (now - timedelta(hours=1)).isoformat()
    retry_after = None
    if database.count_send_events(email=email, since=since_min) >= 1:
        last = database.latest_send_event_at(email, since_min)
        try:
            elapsed = (now - datetime.fromisoformat(last)).total_seconds()
        except (TypeError, ValueError):
            elapsed = 0
        retry_after = max(1, int(60 - elapsed))
    elif database.count_send_events(email=email, since=since_hour) >= 5:
        retry_after = 3600
    elif database.count_send_events(ip=ip, since=since_hour) >= 10:
        retry_after = 3600
    if retry_after is not None:
        database.record_send_failure(email, ip)
        raise ApiError(
            429, "rate_limited", "发送过于频繁，请稍后再试",
            headers={"Retry-After": str(retry_after)},
        )
    database.record_send_event(email, ip)
    user = database.get_user_by_email(email)
    if user is not None:
        code = email_auth.create_verification_code(email, purpose)
        try:
            email_auth.send_verification_email(email, code, purpose)
        except email_auth.SmtpNotConfigured as e:
            raise ApiError(503, "email_not_configured", "email not configured") from e
        except Exception as e:
            raise ApiError(503, "email_send_failed", "邮件发送失败，请稍后再试") from e
    return {"ok": True, "message": "验证码已发送"}


@app.post("/api/v1/auth/send-code")
def auth_send_code(body: SendCodeIn, request: Request):
    return _request_code(body.email, body.purpose, _client_ip(request),
                         body.captcha_token, body.captcha_text)


@app.post("/api/v1/auth/verify")
def auth_verify(body: VerifyIn):
    email = email_auth.normalize_email(body.email)
    ok, reason = email_auth.check_code(email, body.code)
    if not ok:
        code, detail = {
            "missing": ("verification_code_invalid", "验证码错误或已过期"),
            "expired": ("verification_code_expired", "验证码已过期，请重新获取"),
            "too_many_attempts": ("verification_code_too_many_attempts", "验证码尝试次数过多，请重新获取"),
            "wrong": ("verification_code_wrong", "验证码错误"),
        }.get(reason, ("verification_code_invalid", "验证码错误或已过期"))
        raise ApiError(400, code, detail)
    email_auth.consume_code(email)
    database.set_user_verified(email)
    return {"ok": True, "email_verified": True}


@app.post("/api/v1/auth/change-password")
def auth_change_password(body: ChangePasswordIn, device_id: str = Depends(get_current_device)):
    user = database.get_user_by_device(device_id)
    if not user:
        raise ApiError(400, "account_email_not_bound", "该账号未绑定邮箱，请先注册邮箱账号")
    if len(body.new_password) < 8:
        raise ApiError(400, "password_too_short", "新密码至少 8 位")
    if body.code:
        ok, reason = email_auth.check_code(user["email"], body.code)
        if not ok:
            raise ApiError(400, "verification_code_invalid", "验证码错误或已过期")
        email_auth.consume_code(user["email"])
    elif not user["email_verified"]:
        raise ApiError(400, "email_not_verified", "邮箱未验证，请使用验证码修改密码")
    elif not body.current_password or not email_auth.verify_password(
        body.current_password, user["password_hash"]
    ):
        raise ApiError(400, "current_password_wrong", "当前密码错误")
    database.update_user_password(user["email"], email_auth.hash_password(body.new_password))
    return {"ok": True}


@app.post("/api/v1/auth/forgot-password")
def auth_forgot_password(body: ForgotPasswordIn, request: Request):
    # Forgot-password carries no captcha fields; the captcha gate
    # applies to send-code only. Rate limits + generic response still apply.
    return _request_code(body.email, "reset", _client_ip(request), None, None,
                         captcha_gate=False)


@app.post("/api/v1/auth/reset-password")
def auth_reset_password(body: ResetPasswordIn):
    email = email_auth.normalize_email(body.email)
    if len(body.new_password) < 8:
        raise ApiError(400, "password_too_short", "新密码至少 8 位")
    user = database.get_user_by_email(email)
    if user is None:
        raise ApiError(400, "verification_code_invalid", "验证码错误或已过期")
    if not user["email_verified"] and not user["verified_at"]:
        raise ApiError(
            400, "email_not_verified", "该邮箱未验证，无法找回密码"
        )
    ok, reason = email_auth.check_code(email, body.code)
    if not ok:
        raise ApiError(400, "verification_code_invalid", "验证码错误或已过期")
    email_auth.consume_code(email)
    database.invalidate_codes_for_email(email)
    database.update_user_password(email, email_auth.hash_password(body.new_password))
    return {"ok": True}


# ---------- privacy ----------

@app.get("/api/v1/privacy")
def privacy_json():
    return {"text": email_auth.PRIVACY_TEXT, "updated_at": email_auth.PRIVACY_UPDATED_AT}


@app.get("/privacy", include_in_schema=False)
def privacy_page():
    paras = "".join(
        f"<p>{line}</p>" for line in email_auth.PRIVACY_TEXT.split("\n") if line.strip()
    )
    html = (
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>笔友 · 隐私说明</title>"
        "<style>body{font-family:-apple-system,\"PingFang SC\",\"Microsoft YaHei\",sans-serif;"
        "max-width:640px;margin:40px auto;padding:0 20px;line-height:1.8;color:#333;"
        "background:#F2F0EB}h1{font-size:20px;color:#2F5D50}</style></head>"
        f"<body><h1>笔友 · 隐私说明</h1>{paras}"
        f"<p style=\"color:#999;font-size:13px\">更新于 {email_auth.PRIVACY_UPDATED_AT}</p>"
        "</body></html>"
    )
    return HTMLResponse(content=html)


# ---------- characters ----------

@app.get("/api/v1/characters")
def list_characters(device_id: str = Depends(get_current_device)):
    unlocked = set(database.unlocked_character_ids(device_id))
    return [
        {**public_character(c), "unlocked": c["id"] in unlocked}
        for c in database.list_characters()
    ]


@app.get("/api/v1/characters/{character_id}")
def get_character(character_id: str, device_id: str = Depends(get_current_device)):
    char = database.get_character(character_id)
    if not char:
        raise ApiError(404, "character_not_found", "character not found")
    unlocked = character_id in database.unlocked_character_ids(device_id)
    return {**public_character(char), "unlocked": unlocked}


# ---------- letters ----------

@app.post("/api/v1/letters", status_code=status.HTTP_201_CREATED)
def send_letter(body: LetterIn, device_id: str = Depends(get_current_device)):
    # Sending needs an email-registered account: anonymous browsing is
    # read-only. Registered-but-unverified accounts CAN send (only
    # password change / recovery require verification).
    if not _is_registered(device_id):
        raise ApiError(
            403, "anonymous_letter_forbidden",
            "发信需要注册邮箱账号，匿名浏览只能看看",
        )
    ok, problems = validate_user_letter(body.text)
    if not ok:
        detail = "; ".join(problems)
        if any(p == "letter is empty" for p in problems):
            code = "letter_empty"
        elif any("must be at most" in p for p in problems):
            code = "letter_too_long"
        else:
            code = "invalid_letter"
        raise ApiError(400, code, detail)
    character_id = body.character_id.strip()
    char = database.get_character(character_id)
    if not char:
        raise ApiError(404, "character_not_found", "character not found")
    if character_id not in database.unlocked_character_ids(device_id):
        raise ApiError(403, "character_locked", "character is locked; unlock it first")
    device, tier = _device_plan(device_id)

    # 1. Turn-taking: one outstanding letter per character (checked
    # first so a double-send to the same character gets the specific
    # 409, not the generic daily-cap 429).
    if database.outstanding_letter(device_id, character_id):
        raise ApiError(
            409, "unanswered_letter",
            "this character has an unanswered letter; wait for the reply before writing again",
        )
    # 2. Daily send cap (per user per day, not per character).
    if database.count_today_sends(device_id) >= tier["daily_send_cap"]:
        raise ApiError(
            429, "daily_send_limit",
            f"daily send limit reached ({tier['daily_send_cap']} letter(s) per day for the {device['plan']} plan)",
        )
    # 3. Relationship must be active (auto-start if a slot is free).
    rel = database.get_relationship(device_id, character_id)
    if not rel or rel["status"] != "active":
        try:
            database.start_relationship(device_id, character_id, tier["max_active_characters"])
        except ValueError as e:
            # start_relationship only raises for the slot limit; the
            # handler would infer the same code, but attach it
            # explicitly so the code never depends on message text.
            raise ApiError(409, "active_character_limit", str(e)) from e

    is_first = database.count_user_letters(device_id, character_id) == 0
    due = reply_due_date(date.today(), device["plan"], is_first)
    letter = database.create_user_letter(
        device_id, character_id, body.text.strip(), due.isoformat(), is_first,
    )
    database.award_point(device_id, "write", ref_id=str(letter["id"]))
    database.mark_referral_successful(device_id)
    evolution.after_interaction(device_id, character_id, event="letter")
    return _public_letter(letter, device["plan"])


def _thread_visible(device_id: str, character_id: str) -> None:
    """A thread is user-visible while the relationship is active or
    inside its 30-day reconnect window. Past the window the user sees
    nothing (410) — the encrypted server data is retained for
    legal/audit only."""
    rel = database.get_relationship(device_id, character_id)
    if rel and rel["status"] == "ended":
        if not rel.get("reconnect_until") or rel["reconnect_until"] < date.today().isoformat():
            raise ApiError(
                410, "relationship_expired",
                "this relationship ended more than 30 days ago and is no longer visible to you",
            )


@app.get("/api/v1/letters/unread-count")
def unread_count(device_id: str = Depends(get_current_device)):
    """Unread AI replies: delivered and never opened (user_read_at is
    empty; legacy read_at counts as read too)."""
    return {"unread_count": database.count_unread_replies(device_id)}


@app.get("/api/v1/letters")
def list_letters(character_id: str | None = None, device_id: str = Depends(get_current_device)):
    _device, _tier = _device_plan(device_id)
    plan = _device["plan"] if _device else "free"
    if character_id:
        if not database.get_character(character_id):
            raise ApiError(404, "character_not_found", "character not found")
        _thread_visible(device_id, character_id)
        return [_public_letter(l, plan) for l in database.list_thread(device_id, character_id)]
    return [_public_letter(l, plan) for l in database.list_all_letters(device_id)]


@app.get("/api/v1/letters/{letter_id}")
def get_letter(letter_id: int, device_id: str = Depends(get_current_device)):
    letter = database.get_letter(device_id, letter_id)
    if not letter:
        raise ApiError(404, "letter_not_found", "letter not found")
    _thread_visible(device_id, letter["character_id"])
    _device, _tier = _device_plan(device_id)
    plan = _device["plan"] if _device else "free"
    return _public_letter(letter, plan)


@app.post("/api/v1/letters/{letter_id}/read")
def read_letter(letter_id: int, device_id: str = Depends(get_current_device)):
    letter = database.get_letter(device_id, letter_id)
    if not letter:
        raise ApiError(404, "letter_not_found", "letter not found")
    if letter["direction"] != "ai":
        raise ApiError(400, "not_ai_reply", "only AI replies can be marked read")
    # Unread = neither the new user_read_at nor the legacy read_at set.
    # First call records user_read_at and awards +1 (once per letter,
    # enforced by award_point's ref dedupe); repeats never overwrite.
    # Anonymous browsing earns no points (see _is_registered).
    was_unread = not letter.get("user_read_at") and not letter.get("read_at")
    letter = database.mark_letter_read(device_id, letter_id)
    awarded = 0
    if was_unread and _is_registered(device_id):
        awarded = database.award_point(device_id, "read", ref_id=str(letter_id))
    _device, _tier = _device_plan(device_id)
    plan = _device["plan"] if _device else "free"
    return {**_public_letter(letter, plan), "points_awarded": awarded}


@app.post("/api/v1/letters/process-due")
def process_due(body: ProcessDueIn | None = None, device_id: str = Depends(get_current_device)):
    day = (body.date if body else None) or date.today().isoformat()
    try:
        date.fromisoformat(day)
    except ValueError as e:
        raise ApiError(400, "invalid_date", "date must be YYYY-MM-DD") from e
    return process_due_replies(device_id, day)


# ---------- relationships ----------

@app.get("/api/v1/relationships")
def list_relationships(device_id: str = Depends(get_current_device)):
    return database.list_relationships(device_id)


@app.post("/api/v1/relationships/{character_id}/end")
def end_relationship(character_id: str, device_id: str = Depends(get_current_device)):
    rel = database.end_relationship(device_id, character_id)
    if not rel:
        raise ApiError(404, "relationship_not_found", "relationship not found")
    return {
        **rel,
        "note": "30 天内可以再次联系到原来的人物；超过 30 天后 App 里不再显示这段关系，"
                "服务端仍加密留存（依法留存），用户侧不可恢复。",
    }


@app.post("/api/v1/relationships/{character_id}/reconnect")
def reconnect_relationship(character_id: str, device_id: str = Depends(get_current_device)):
    device, tier = _device_plan(device_id)
    try:
        rel = database.reconnect_relationship(
            device_id, character_id, tier["max_active_characters"]
        )
    except ValueError as e:
        # Past the 30-day window: user-side gone (410).
        if "30 days" in str(e):
            raise ApiError(410, "relationship_expired", str(e)) from e
        if "active character limit" in str(e):
            raise ApiError(409, "active_character_limit", str(e)) from e
        raise ApiError(409, "relationship_not_found", str(e)) from e
    return rel


# ---------- points / unlocks / referrals ----------

@app.get("/api/v1/points")
def get_points(device_id: str = Depends(get_current_device)):
    return {
        "points": database.points_balance(device_id),
        "events": database.list_point_events(device_id),
    }


@app.get("/api/v1/unlocks")
def get_unlocks(device_id: str = Depends(get_current_device)):
    points = database.points_balance(device_id)
    refs = database.referral_count(device_id)
    return {
        "points": points,
        "referral_count": refs,
        "points_unlocks": database.points_unlocks(points),
        "referral_unlocks": database.referral_unlocks(refs),
        "entitled_character_ids": database.evaluate_unlocks(device_id),
        "unlocked_character_ids": database.unlocked_character_ids(device_id),
        "thresholds": {"points": [100, 300], "referrals": [1, 10, 30, 40, 50]},
    }


@app.post("/api/v1/referrals", status_code=status.HTTP_201_CREATED)
def record_referral(body: ReferralIn, device_id: str = Depends(get_current_device)):
    try:
        return database.record_referral(device_id, body.referred_device_id.strip())
    except ValueError as e:
        raise ApiError(400, "self_referral", str(e)) from e


# ---------- LLM providers ----------

@app.get("/api/v1/llm/providers")
def list_providers(device_id: str = Depends(get_current_device)):
    return list_llm_providers()


# ---------- activities / messages (fetch-on-open) ----------

@app.get("/api/v1/activities")
def list_activities(device_id: str = Depends(get_current_device)):
    return [
        {
            "id": a["id"], "title": a["title"], "body": a["body"],
            "image_url": a["image_url"], "start_at": a["start_at"],
            "end_at": a["end_at"], "active": bool(a["active"]),
        }
        for a in database.list_activities()
    ]


@app.get("/api/v1/messages")
def list_messages(device_id: str = Depends(get_current_device)):
    return [
        {"id": m["id"], "title": m["title"], "body": m["body"], "created_at": m["created_at"]}
        for m in database.list_messages()
    ]


# ---------- membership (phase 1: free, no payment) ----------

@app.get("/api/v1/membership/status")
def membership_status(device_id: str = Depends(get_current_device)):
    device, tier = _device_plan(device_id)
    return {
        "plan": device["plan"],
        "phase1_free": PHASE1_FREE,
        "paywalled": False,
        "max_active_characters": tier["max_active_characters"],
        "daily_send_cap": tier["daily_send_cap"],
        "reply_interval_days": tier["reply_interval_days"],
        "price_member_cny": 9.9,
        "price_premium_cny": 19.9,
    }
