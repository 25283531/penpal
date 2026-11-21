"""Machine-readable error codes — additive only.

Contract (never break the existing API):
- Every error response keeps its existing ``detail`` value and HTTP
  status code exactly as before. ``detail`` stays a plain string for
  ``HTTPException`` errors (and the usual list for 422 validation
  errors); only a stable top-level ``code`` field is added, e.g.::

      {"detail": "this character has an unanswered letter; ...",
       "code": "unanswered_letter"}

- The Android app localises by ``code`` (frontend mapping is the
  source of truth for user-facing text); ``detail`` remains the
  human-readable fallback and its wording is unchanged.

How a code is attached:
- Preferred: raise :class:`ApiError` with an explicit ``code`` at the
  raise site (see ``app/main.py`` / ``app/auth.py`` / ``app/admin.py``).
- Safety net: :func:`code_for_exception` infers the code from a plain
  ``HTTPException``'s ``detail`` text (covers ``ValueError`` messages
  re-raised as 409/410, and any raise site not yet converted), so no
  error path can slip through without a code. Inference is keyed on
  stable substrings of the existing detail text, never on new text.
- Unknown errors fall back to a per-status generic code
  (``bad_request`` / ``unauthorized`` / ``not_found`` / ...).

Codes are snake_case, stable, and documented in ``ERROR_CODES`` below.
"""
from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# --- explicit code registry (for reference; the handlers below are
# --- what actually attaches codes, so the registry never drifts from
# --- behaviour) -------------------------------------------------------
ERROR_CODES: dict[str, str] = {
    # letters
    "letter_empty": "letter text is empty",
    "letter_too_long": "letter exceeds 2000 chars",
    "invalid_letter": "letter failed validation",
    "character_not_found": "no such character",
    "character_locked": "character is locked; unlock it first",
    "unanswered_letter": "character already has an unanswered letter",
    "daily_send_limit": "daily send cap reached",
    "active_character_limit": "active-character slot limit reached",
    "relationship_not_found": "no such relationship",
    "relationship_expired": "relationship ended >30 days ago / reconnect window passed",
    "letter_not_found": "no such letter",
    "not_ai_reply": "only AI replies can be marked read",
    "invalid_date": "date must be YYYY-MM-DD",
    "self_referral": "cannot refer yourself",
    # device auth
    "age_required": "age is required at registration",
    "age_invalid": "age must be an integer between 1 and 120",
    "underage_refused": "users under 14 are refused registration",
    "invalid_token": "token signature is invalid",
    "unknown_device": "token device does not exist",
    "missing_token": "missing bearer token",
    # email accounts
    "invalid_email": "email format is invalid",
    "password_too_short": "password must be at least 8 chars",
    "email_already_registered": "email is already registered",
    "invalid_credentials": "email or password is wrong",
    "invalid_request": "request is invalid (bad email or purpose)",
    "email_not_configured": "SMTP is not configured on the server",
    "email_send_failed": "verification email could not be sent",
    "rate_limited": "too many requests; retry later",
    "captcha_missing": "captcha is required",
    "captcha_invalid": "captcha is invalid or expired",
    "captcha_expired": "captcha has expired",
    "captcha_wrong": "captcha is wrong",
    "verification_code_invalid": "verification code is wrong or expired",
    "verification_code_expired": "verification code has expired",
    "verification_code_wrong": "verification code is wrong",
    "verification_code_too_many_attempts": "too many verification attempts",
    "account_email_not_bound": "account has no bound email",
    "email_not_verified": "email is not verified",
    "current_password_wrong": "current password is wrong",
    "anonymous_letter_forbidden": "anonymous browsing is read-only; sending letters needs an email account",
    "invalid_display_name": "virtual-world name must be 1-20 chars, Chinese / letters / digits only",
    "device_already_bound": "device is already bound to another email account",
    "device_mismatch": "device_id and device_token disagree",
    # admin console
    "admin_login_required": "admin login required",
    "admin_password_already_set": "admin password already set",
    "admin_wrong_password": "admin password is wrong",
    "unknown_setting": "unknown admin setting key",
    "unknown_llm_provider": "unknown LLM provider",
    "invalid_consolidation_interval": "consolidation interval must be an integer 1-7",
    "invalid_smtp_port": "SMTP port must be an integer 1-65535",
    "invalid_price": "price must be a number >= 0",
    "message_not_found": "no such admin message",
    "activity_not_found": "no such admin activity",
    # photos / misc
    "photo_not_found": "no such character photo",
    # LLM / reply generation (also used in process-due detail entries)
    "llm_not_configured": "no LLM provider is configured on the server",
    "reply_generation_failed": "LLM reply generation failed",
    "content_filter_failed": "generated reply did not pass the content filter",
    # generic fallbacks
    "validation_error": "request validation failed",
    "bad_request": "bad request",
    "unauthorized": "unauthorized",
    "forbidden": "forbidden",
    "not_found": "not found",
    "conflict": "conflict",
    "gone": "gone",
    "service_unavailable": "service unavailable",
    "bad_gateway": "bad gateway",
    "internal_error": "internal error",
}

# Substring -> code, checked in order (most specific first). Keys are
# substrings of the *existing* detail texts — do not change the detail
# texts to match these; change these if a detail text ever changes.
_DETAIL_RULES: list[tuple[str, str]] = [
    ("active character limit reached", "active_character_limit"),
    ("reconnect window (30 days) has passed", "relationship_expired"),
    ("this relationship ended more than 30 days ago", "relationship_expired"),
    ("daily send limit reached", "daily_send_limit"),
    ("unanswered letter", "unanswered_letter"),
    ("character is locked", "character_locked"),
    ("letter is empty", "letter_empty"),
    ("must be at most 2000", "letter_too_long"),
    ("length ", "letter_too_long"),  # "length N chars, must be at most 2000"
    ("invalid token", "invalid_token"),
    ("unknown device", "unknown_device"),
    ("missing bearer token", "missing_token"),
    ("age is required", "age_required"),
    ("age must be", "age_invalid"),
    ("users under 14", "underage_refused"),
    ("cannot refer yourself", "self_referral"),
    ("relationship not found", "relationship_not_found"),
    ("character not found", "character_not_found"),
    ("letter not found", "letter_not_found"),
    ("photo not found", "photo_not_found"),
    ("only AI replies can be marked read", "not_ai_reply"),
    ("date must be YYYY-MM-DD", "invalid_date"),
    ("邮箱格式不正确", "invalid_email"),
    ("密码至少 8 位", "password_too_short"),
    ("新密码至少 8 位", "password_too_short"),
    ("该邮箱已注册", "email_already_registered"),
    ("邮箱或密码错误", "invalid_credentials"),
    ("请求无效", "invalid_request"),
    ("email not configured", "email_not_configured"),
    ("邮件发送失败", "email_send_failed"),
    ("发送过于频繁", "rate_limited"),
    ("验证码尝试次数过多", "verification_code_too_many_attempts"),
    ("验证码错误或已过期", "verification_code_invalid"),
    ("验证码已过期", "verification_code_expired"),
    ("验证码错误", "verification_code_wrong"),
    ("该账号未绑定邮箱", "account_email_not_bound"),
    ("邮箱未验证，请使用验证码修改密码", "email_not_verified"),
    ("该邮箱未验证，无法找回密码", "email_not_verified"),
    ("发信需要注册邮箱账号", "anonymous_letter_forbidden"),
    ("虚拟世界姓名", "invalid_display_name"),
    ("已绑定其他邮箱账号", "device_already_bound"),
    ("device_id 与 device_token 不一致", "device_mismatch"),
    ("当前密码错误", "current_password_wrong"),
    ("需要图形验证码", "captcha_missing"),
    ("图形验证码无效或已过期", "captcha_invalid"),
    ("图形验证码已过期", "captcha_expired"),
    ("图形验证码错误", "captcha_wrong"),
    ("admin login required", "admin_login_required"),
    ("admin password already set", "admin_password_already_set"),
    ("wrong password", "admin_wrong_password"),
    ("unknown setting", "unknown_setting"),
    ("unknown LLM provider", "unknown_llm_provider"),
    ("consolidation interval must be", "invalid_consolidation_interval"),
    ("consolidation interval must be 1-7 days", "invalid_consolidation_interval"),
    ("SMTP port must be", "invalid_smtp_port"),
    ("price must be", "invalid_price"),
    ("message not found", "message_not_found"),
    ("activity not found", "activity_not_found"),
    ("did not pass the content filter", "content_filter_failed"),
    ("no LLM provider is configured", "llm_not_configured"),
    ("is not configured", "llm_not_configured"),
    ("is disabled", "llm_not_configured"),
    ("unknown plan", "bad_request"),
    ("unknown memory kind", "bad_request"),
    ("unknown point kind", "bad_request"),
]

_FALLBACK_BY_STATUS: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    410: "gone",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "bad_gateway",
    503: "service_unavailable",
}


class ApiError(HTTPException):
    """HTTPException with an explicit stable machine-readable ``code``.

    ``detail`` stays the human-readable string, unchanged.
    """

    def __init__(self, status_code: int, code: str, detail: str,
                 headers: dict | None = None):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


def code_for_exception(exc: HTTPException) -> str:
    """Resolve the stable code for any HTTPException (explicit or inferred)."""
    if isinstance(exc, ApiError):
        return exc.code
    detail = exc.detail
    if isinstance(detail, str):
        for needle, code in _DETAIL_RULES:
            if needle in detail:
                return code
    return _FALLBACK_BY_STATUS.get(exc.status_code, "internal_error")


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Replace FastAPI's default handler: same ``detail`` + status,
    plus a top-level ``code``. Original headers (e.g. Retry-After)
    are preserved."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": code_for_exception(exc)},
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422s keep FastAPI's ``detail`` error list; only ``code`` is added."""
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "code": "validation_error"},
    )
