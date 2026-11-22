package com.junze.penpal.ui.components

import com.junze.penpal.R
import java.io.IOException
import retrofit2.HttpException

/**
 * Localised error handling.
 *
 * The backend returns `{detail, code}` (see backend/app/errors.py):
 * `code` is a stable machine-readable key, `detail` is a human-readable
 * string in either English or Chinese. The app NEVER shows `detail` to
 * the user — it maps the error to a localised string resource instead:
 *
 *   1. `code` (exact match) — the primary key, stable across wording.
 *   2. `detail` substring rules — safety net for responses without a
 *      code (mirrors the backend's own _DETAIL_RULES order).
 *   3. HTTP status fallback — generic per-status text.
 *   4. Unknown / unparseable -> generic localised text.
 *
 * The mapping itself is pure Kotlin (`errorMappingFor` /
 * `Throwable.errorMapping`): no Android Context is needed, so it is
 * unit-testable on the JVM (see ErrorMessagesTest). Screens resolve
 * the [Notice] with stringResource, so the displayed language follows
 * the app's current locale.
 *
 * [Notice] is what ViewModels store: a string resource id plus its
 * format args. Nothing user-visible is ever built from a raw
 * exception message or a backend `detail` string.
 */
data class Notice(val resId: Int, val args: List<Any> = emptyList())

/** Stable keys for every user-facing error. Each maps to R.string.err_*. */
enum class ErrorKey {
    UNANSWERED_LETTER,
    CHARACTER_LIMIT,
    DAILY_LIMIT,
    TOO_FREQUENT,
    CHARACTER_LOCKED,
    LETTER_EMPTY,
    LETTER_TOO_LONG,
    LETTER_INVALID,
    SESSION_EXPIRED,
    INVALID_EMAIL,
    PASSWORD_TOO_SHORT,
    EMAIL_REGISTERED,
    INVALID_CREDENTIALS,
    INVALID_REQUEST,
    CODE_INVALID,
    CODE_EXPIRED,
    CODE_TOO_MANY_ATTEMPTS,
    EMAIL_NOT_BOUND,
    EMAIL_REQUIRED,
    INVALID_DISPLAY_NAME,
    DEVICE_ALREADY_BOUND,
    DEVICE_MISMATCH,
    EMAIL_NOT_VERIFIED,
    CURRENT_PASSWORD_WRONG,
    CAPTCHA_MISSING,
    CAPTCHA_INVALID,
    CAPTCHA_EXPIRED,
    EMAIL_NOT_CONFIGURED,
    EMAIL_SEND_FAILED,
    LLM_NOT_CONFIGURED,
    REPLY_FAILED,
    CONTENT_FILTER_FAILED,
    NOT_FOUND,
    RELATIONSHIP_GONE,
    NOT_AI_REPLY,
    INVALID_DATE,
    SELF_REFERRAL,
    AGE_INVALID,
    AGE_UNDER_18,
    VALIDATION_ERROR,
    BAD_REQUEST,
    FORBIDDEN,
    CONFLICT,
    SERVICE_UNAVAILABLE,
    BAD_GATEWAY,
    SERVER_UNREACHABLE,
    UNKNOWN_ERROR
}

/** Result of the pure mapping: which text to show, and its format args. */
data class ErrorMapping(val key: ErrorKey, val args: List<Any> = emptyList())

fun ErrorKey.resId(): Int = when (this) {
    ErrorKey.UNANSWERED_LETTER -> R.string.err_unanswered_letter
    ErrorKey.CHARACTER_LIMIT -> R.string.err_character_limit
    ErrorKey.DAILY_LIMIT -> R.string.err_daily_limit
    ErrorKey.TOO_FREQUENT -> R.string.err_too_frequent
    ErrorKey.CHARACTER_LOCKED -> R.string.err_character_locked
    ErrorKey.LETTER_EMPTY -> R.string.err_letter_empty
    ErrorKey.LETTER_TOO_LONG -> R.string.err_letter_too_long
    ErrorKey.LETTER_INVALID -> R.string.err_letter_invalid
    ErrorKey.SESSION_EXPIRED -> R.string.err_session_expired
    ErrorKey.INVALID_EMAIL -> R.string.err_invalid_email
    ErrorKey.PASSWORD_TOO_SHORT -> R.string.err_password_too_short
    ErrorKey.EMAIL_REGISTERED -> R.string.err_email_registered
    ErrorKey.INVALID_CREDENTIALS -> R.string.err_invalid_credentials
    ErrorKey.INVALID_REQUEST -> R.string.err_invalid_request
    ErrorKey.CODE_INVALID -> R.string.err_code_invalid
    ErrorKey.CODE_EXPIRED -> R.string.err_code_expired
    ErrorKey.CODE_TOO_MANY_ATTEMPTS -> R.string.err_code_too_many_attempts
    ErrorKey.EMAIL_NOT_BOUND -> R.string.err_email_not_bound
    ErrorKey.EMAIL_REQUIRED -> R.string.err_email_required
    ErrorKey.INVALID_DISPLAY_NAME -> R.string.err_invalid_display_name
    ErrorKey.DEVICE_ALREADY_BOUND -> R.string.err_device_already_bound
    ErrorKey.DEVICE_MISMATCH -> R.string.err_device_mismatch
    ErrorKey.EMAIL_NOT_VERIFIED -> R.string.err_email_not_verified
    ErrorKey.CURRENT_PASSWORD_WRONG -> R.string.err_current_password_wrong
    ErrorKey.CAPTCHA_MISSING -> R.string.err_captcha_missing
    ErrorKey.CAPTCHA_INVALID -> R.string.err_captcha_invalid
    ErrorKey.CAPTCHA_EXPIRED -> R.string.err_captcha_expired
    ErrorKey.EMAIL_NOT_CONFIGURED -> R.string.err_email_not_configured
    ErrorKey.EMAIL_SEND_FAILED -> R.string.err_email_send_failed
    ErrorKey.LLM_NOT_CONFIGURED -> R.string.err_llm_not_configured
    ErrorKey.REPLY_FAILED -> R.string.err_reply_failed
    ErrorKey.CONTENT_FILTER_FAILED -> R.string.err_content_filter_failed
    ErrorKey.NOT_FOUND -> R.string.err_not_found
    ErrorKey.RELATIONSHIP_GONE -> R.string.err_relationship_gone
    ErrorKey.NOT_AI_REPLY -> R.string.err_not_ai_reply
    ErrorKey.INVALID_DATE -> R.string.err_invalid_date
    ErrorKey.SELF_REFERRAL -> R.string.err_self_referral
    ErrorKey.AGE_INVALID -> R.string.err_age_invalid
    ErrorKey.AGE_UNDER_18 -> R.string.err_age_under_18
    ErrorKey.VALIDATION_ERROR -> R.string.err_validation_error
    ErrorKey.BAD_REQUEST -> R.string.err_bad_request
    ErrorKey.FORBIDDEN -> R.string.err_forbidden
    ErrorKey.CONFLICT -> R.string.err_conflict
    ErrorKey.SERVICE_UNAVAILABLE -> R.string.err_service_unavailable
    ErrorKey.BAD_GATEWAY -> R.string.err_bad_gateway
    ErrorKey.SERVER_UNREACHABLE -> R.string.server_unreachable
    ErrorKey.UNKNOWN_ERROR -> R.string.unknown_error
}

/** Backend `code` -> key. Exact match wins over detail inference. */
private fun keyForCode(code: String): ErrorKey? = when (code) {
    "unanswered_letter" -> ErrorKey.UNANSWERED_LETTER
    "active_character_limit" -> ErrorKey.CHARACTER_LIMIT
    "daily_send_limit" -> ErrorKey.DAILY_LIMIT
    "rate_limited" -> ErrorKey.TOO_FREQUENT
    "character_locked" -> ErrorKey.CHARACTER_LOCKED
    "letter_empty" -> ErrorKey.LETTER_EMPTY
    "letter_too_long" -> ErrorKey.LETTER_TOO_LONG
    "invalid_letter" -> ErrorKey.LETTER_INVALID
    "invalid_token", "unknown_device", "missing_token" -> ErrorKey.SESSION_EXPIRED
    "invalid_email" -> ErrorKey.INVALID_EMAIL
    "password_too_short" -> ErrorKey.PASSWORD_TOO_SHORT
    "email_already_registered" -> ErrorKey.EMAIL_REGISTERED
    "invalid_credentials" -> ErrorKey.INVALID_CREDENTIALS
    "invalid_request" -> ErrorKey.INVALID_REQUEST
    "verification_code_invalid", "verification_code_wrong" -> ErrorKey.CODE_INVALID
    "verification_code_expired" -> ErrorKey.CODE_EXPIRED
    "verification_code_too_many_attempts" -> ErrorKey.CODE_TOO_MANY_ATTEMPTS
    "account_email_not_bound" -> ErrorKey.EMAIL_NOT_BOUND
    "anonymous_letter_forbidden" -> ErrorKey.EMAIL_REQUIRED
    "invalid_display_name" -> ErrorKey.INVALID_DISPLAY_NAME
    "device_already_bound" -> ErrorKey.DEVICE_ALREADY_BOUND
    "device_mismatch" -> ErrorKey.DEVICE_MISMATCH
    "email_not_verified" -> ErrorKey.EMAIL_NOT_VERIFIED
    "current_password_wrong" -> ErrorKey.CURRENT_PASSWORD_WRONG
    "captcha_missing" -> ErrorKey.CAPTCHA_MISSING
    "captcha_invalid", "captcha_wrong" -> ErrorKey.CAPTCHA_INVALID
    "captcha_expired" -> ErrorKey.CAPTCHA_EXPIRED
    "email_not_configured" -> ErrorKey.EMAIL_NOT_CONFIGURED
    "email_send_failed" -> ErrorKey.EMAIL_SEND_FAILED
    "llm_not_configured" -> ErrorKey.LLM_NOT_CONFIGURED
    "reply_generation_failed" -> ErrorKey.REPLY_FAILED
    "content_filter_failed" -> ErrorKey.CONTENT_FILTER_FAILED
    "character_not_found", "letter_not_found", "photo_not_found",
    "relationship_not_found", "message_not_found", "activity_not_found",
    "not_found" -> ErrorKey.NOT_FOUND
    "relationship_expired", "gone" -> ErrorKey.RELATIONSHIP_GONE
    "not_ai_reply" -> ErrorKey.NOT_AI_REPLY
    "invalid_date" -> ErrorKey.INVALID_DATE
    "self_referral" -> ErrorKey.SELF_REFERRAL
    "age_required", "age_invalid", "underage_refused" -> ErrorKey.AGE_INVALID
    "age_under_18", "under_18" -> ErrorKey.AGE_UNDER_18
    "validation_error" -> ErrorKey.VALIDATION_ERROR
    "bad_request" -> ErrorKey.BAD_REQUEST
    "unauthorized" -> ErrorKey.SESSION_EXPIRED
    "forbidden" -> ErrorKey.FORBIDDEN
    "conflict" -> ErrorKey.CONFLICT
    "service_unavailable" -> ErrorKey.SERVICE_UNAVAILABLE
    "bad_gateway" -> ErrorKey.BAD_GATEWAY
    "internal_error" -> ErrorKey.UNKNOWN_ERROR
    else -> null
}

/**
 * Detail-substring fallback, in the same most-specific-first order as
 * the backend's _DETAIL_RULES (backend/app/errors.py). Covers responses
 * that carry no `code`, and older servers. Never returns a `detail`
 * string — only a key.
 */
private val DETAIL_RULES: List<Pair<String, ErrorKey>> = listOf(
    "active character limit reached" to ErrorKey.CHARACTER_LIMIT,
    "reconnect window (30 days) has passed" to ErrorKey.RELATIONSHIP_GONE,
    "this relationship ended more than 30 days ago" to ErrorKey.RELATIONSHIP_GONE,
    "daily send limit reached" to ErrorKey.DAILY_LIMIT,
    "unanswered letter" to ErrorKey.UNANSWERED_LETTER,
    "character is locked" to ErrorKey.CHARACTER_LOCKED,
    "letter is empty" to ErrorKey.LETTER_EMPTY,
    "must be at most 2000" to ErrorKey.LETTER_TOO_LONG,
    "length " to ErrorKey.LETTER_TOO_LONG,
    "invalid token" to ErrorKey.SESSION_EXPIRED,
    "unknown device" to ErrorKey.SESSION_EXPIRED,
    "missing bearer token" to ErrorKey.SESSION_EXPIRED,
    "age is required" to ErrorKey.AGE_INVALID,
    "age must be" to ErrorKey.AGE_INVALID,
    // Under-18 refusal (400 age_under_18): the registration age gate is
    // 18+, not 14 — the old "users under 14" wording is retired with it.
    "under 18" to ErrorKey.AGE_UNDER_18,
    "must be 18" to ErrorKey.AGE_UNDER_18,
    "未满 18" to ErrorKey.AGE_UNDER_18,
    "年满 18" to ErrorKey.AGE_UNDER_18,
    "cannot refer yourself" to ErrorKey.SELF_REFERRAL,
    "relationship not found" to ErrorKey.NOT_FOUND,
    "character not found" to ErrorKey.NOT_FOUND,
    "letter not found" to ErrorKey.NOT_FOUND,
    "photo not found" to ErrorKey.NOT_FOUND,
    "only AI replies can be marked read" to ErrorKey.NOT_AI_REPLY,
    "date must be YYYY-MM-DD" to ErrorKey.INVALID_DATE,
    "邮箱格式不正确" to ErrorKey.INVALID_EMAIL,
    "密码至少 8 位" to ErrorKey.PASSWORD_TOO_SHORT,
    "新密码至少 8 位" to ErrorKey.PASSWORD_TOO_SHORT,
    "该邮箱已注册" to ErrorKey.EMAIL_REGISTERED,
    "邮箱或密码错误" to ErrorKey.INVALID_CREDENTIALS,
    "请求无效" to ErrorKey.INVALID_REQUEST,
    "email not configured" to ErrorKey.EMAIL_NOT_CONFIGURED,
    "邮件发送失败" to ErrorKey.EMAIL_SEND_FAILED,
    "发送过于频繁" to ErrorKey.TOO_FREQUENT,
    "验证码尝试次数过多" to ErrorKey.CODE_TOO_MANY_ATTEMPTS,
    "验证码错误或已过期" to ErrorKey.CODE_INVALID,
    "验证码已过期" to ErrorKey.CODE_EXPIRED,
    "验证码错误" to ErrorKey.CODE_INVALID,
    "该账号未绑定邮箱" to ErrorKey.EMAIL_NOT_BOUND,
    "发信需要注册邮箱账号" to ErrorKey.EMAIL_REQUIRED,
    "anonymous browsing is read-only" to ErrorKey.EMAIL_REQUIRED,
    "虚拟世界姓名" to ErrorKey.INVALID_DISPLAY_NAME,
    "已绑定其他邮箱账号" to ErrorKey.DEVICE_ALREADY_BOUND,
    "device_id 与 device_token 不一致" to ErrorKey.DEVICE_MISMATCH,
    "邮箱未验证，请使用验证码修改密码" to ErrorKey.EMAIL_NOT_VERIFIED,
    "该邮箱未验证，无法找回密码" to ErrorKey.EMAIL_NOT_VERIFIED,
    "当前密码错误" to ErrorKey.CURRENT_PASSWORD_WRONG,
    "需要图形验证码" to ErrorKey.CAPTCHA_MISSING,
    "图形验证码无效或已过期" to ErrorKey.CAPTCHA_INVALID,
    "图形验证码已过期" to ErrorKey.CAPTCHA_EXPIRED,
    "图形验证码错误" to ErrorKey.CAPTCHA_INVALID,
    "did not pass the content filter" to ErrorKey.CONTENT_FILTER_FAILED,
    "no LLM provider is configured" to ErrorKey.LLM_NOT_CONFIGURED,
    "is not configured" to ErrorKey.LLM_NOT_CONFIGURED,
    "is disabled" to ErrorKey.LLM_NOT_CONFIGURED
)

private fun keyForStatus(status: Int?): ErrorKey = when (status) {
    400 -> ErrorKey.BAD_REQUEST
    401 -> ErrorKey.SESSION_EXPIRED
    403 -> ErrorKey.FORBIDDEN
    404 -> ErrorKey.NOT_FOUND
    409 -> ErrorKey.CONFLICT
    410 -> ErrorKey.RELATIONSHIP_GONE
    422 -> ErrorKey.VALIDATION_ERROR
    429 -> ErrorKey.TOO_FREQUENT
    500 -> ErrorKey.UNKNOWN_ERROR
    502 -> ErrorKey.BAD_GATEWAY
    503 -> ErrorKey.SERVICE_UNAVAILABLE
    else -> ErrorKey.UNKNOWN_ERROR
}

/** "active character limit reached (1); ..." -> 1 (default when absent). */
internal fun parseLimitCount(detail: String?): Int {
    if (detail.isNullOrBlank()) return 1
    val match = Regex("\\((\\d+)\\)").find(detail)
    return match?.groupValues?.getOrNull(1)?.toIntOrNull() ?: 1
}

/**
 * Pure mapping: backend `code` + HTTP status + raw `detail` -> the key
 * (and format args) to display. `detail` is only ever matched against,
 * never returned.
 */
fun errorMappingFor(code: String?, status: Int?, detail: String?): ErrorMapping {
    val fromCode = code?.trim()?.takeIf { it.isNotEmpty() }?.let { keyForCode(it) }
    if (fromCode != null) {
        val args = if (fromCode == ErrorKey.CHARACTER_LIMIT) {
            listOf(parseLimitCount(detail))
        } else {
            emptyList()
        }
        return ErrorMapping(fromCode, args)
    }
    if (!detail.isNullOrBlank()) {
        for ((needle, key) in DETAIL_RULES) {
            if (needle in detail) {
                val args = if (key == ErrorKey.CHARACTER_LIMIT) {
                    listOf(parseLimitCount(detail))
                } else {
                    emptyList()
                }
                return ErrorMapping(key, args)
            }
        }
    }
    return ErrorMapping(keyForStatus(status))
}

/** Extracts a top-level string field ("code" / "detail") from an error body. */
internal fun extractJsonString(body: String, field: String): String? {
    // `"field": "value"` with \" and \\ unescaped. Deliberately tiny:
    // org.json is an Android-framework class and must not be used here,
    // so this parser stays JVM-testable. A 422 body carries detail as a
    // list, not a string — that simply yields null here.
    val regex = Regex("\"$field\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"")
    val raw = regex.find(body)?.groupValues?.getOrNull(1) ?: return null
    return raw
        .replace("\\\"", "\"")
        .replace("\\\\", "\\")
        .replace("\\n", "\n")
        .replace("\\/", "/")
}

/** The stored session is gone (or the account was retired): the user must
 * sign in again. Thrown by the repository instead of silently falling
 * back to anonymous auth once an email account exists. */
class SessionExpiredException : Exception("session expired")

/** Pure mapping for a failure: never returns backend text or a raw message. */
fun Throwable.errorMapping(): ErrorMapping {
    if (this is SessionExpiredException) {
        return ErrorMapping(ErrorKey.SESSION_EXPIRED)
    }
    if (this is IOException) {
        return ErrorMapping(ErrorKey.SERVER_UNREACHABLE)
    }
    if (this is HttpException) {
        val status = code()
        var bodyCode: String? = null
        var bodyDetail: String? = null
        try {
            val body = response()?.errorBody()?.string()
            if (!body.isNullOrBlank()) {
                bodyCode = extractJsonString(body, "code")
                bodyDetail = extractJsonString(body, "detail")
            }
        } catch (_: Exception) {
            // Unparseable body: fall through to the status mapping.
        }
        return errorMappingFor(bodyCode, status, bodyDetail)
    }
    return ErrorMapping(ErrorKey.UNKNOWN_ERROR)
}

/** What ViewModels store for a failure: a localised notice, never raw text. */
fun Throwable.userNotice(): Notice {
    val mapping = errorMapping()
    return Notice(mapping.key.resId(), mapping.args)
}
