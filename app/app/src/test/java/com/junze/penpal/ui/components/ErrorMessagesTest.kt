package com.junze.penpal.ui.components

import java.io.IOException
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

/**
 * Backend error -> localised key mapping (ErrorMessages.kt).
 *
 * These tests run on the JVM (no Android framework): they assert the
 * pure mapping only — which key + args a given backend `code` / HTTP
 * status / `detail` produces. The key -> actual Chinese/English text
 * lives in values/strings.xml + values-en/strings.xml and is checked
 * for parity by check_strings.py (every ErrorKey must have a string
 * in both files).
 *
 * The two reported bugs are covered first: a 409 with
 * code=unanswered_letter and a 409 with code=active_character_limit
 * must map to their specific keys (never to the raw English detail).
 */
class ErrorMessagesTest {

    private fun httpError(status: Int, body: String): HttpException {
        val responseBody = body.toResponseBody("application/json".toMediaType())
        return HttpException(Response.error<Any>(status, responseBody))
    }

    // ---- The two reported 409s ----

    @Test
    fun unansweredLetter_409_byCode() {
        val e = httpError(
            409,
            """{"detail":"this character has an unanswered letter; wait for the reply before writing again","code":"unanswered_letter"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.UNANSWERED_LETTER), e.errorMapping())
    }

    @Test
    fun unansweredLetter_409_byDetailOnly() {
        // Older responses may carry no `code`: the detail substring
        // fallback must still find the specific key.
        val e = httpError(
            409,
            """{"detail":"this character has an unanswered letter; wait for the reply before writing again"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.UNANSWERED_LETTER), e.errorMapping())
    }

    @Test
    fun activeCharacterLimit_409_byCode_withCount() {
        val e = httpError(
            409,
            """{"detail":"active character limit reached (1); end a relationship or upgrade first","code":"active_character_limit"}"""
        )
        assertEquals(
            ErrorMapping(ErrorKey.CHARACTER_LIMIT, listOf(1)),
            e.errorMapping()
        )
    }

    @Test
    fun activeCharacterLimit_409_byDetailOnly_withCount() {
        val e = httpError(
            409,
            """{"detail":"active character limit reached (5); end a relationship or upgrade first"}"""
        )
        assertEquals(
            ErrorMapping(ErrorKey.CHARACTER_LIMIT, listOf(5)),
            e.errorMapping()
        )
    }

    // ---- Other letter / account errors ----

    @Test
    fun dailySendLimit_429() {
        val e = httpError(
            429,
            """{"detail":"daily send limit reached (1 letter(s) per day for the free plan)","code":"daily_send_limit"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.DAILY_LIMIT), e.errorMapping())
    }

    @Test
    fun characterLocked_403() {
        val e = httpError(
            403,
            """{"detail":"character is locked; unlock it first","code":"character_locked"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.CHARACTER_LOCKED), e.errorMapping())
    }

    @Test
    fun letterEmpty_400() {
        val e = httpError(
            400,
            """{"detail":"letter is empty","code":"letter_empty"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.LETTER_EMPTY), e.errorMapping())
    }

    @Test
    fun letterTooLong_400() {
        val e = httpError(
            400,
            """{"detail":"length 2001 chars, must be at most 2000","code":"letter_too_long"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.LETTER_TOO_LONG), e.errorMapping())
    }

    @Test
    fun sessionExpired_401() {
        val e = httpError(401, """{"detail":"invalid token","code":"invalid_token"}""")
        assertEquals(ErrorMapping(ErrorKey.SESSION_EXPIRED), e.errorMapping())
    }

    @Test
    fun notFound_404() {
        val e = httpError(404, """{"detail":"letter not found","code":"letter_not_found"}""")
        assertEquals(ErrorMapping(ErrorKey.NOT_FOUND), e.errorMapping())
    }

    @Test
    fun relationshipGone_410() {
        val e = httpError(
            410,
            """{"detail":"this relationship ended more than 30 days ago and is no longer visible to you","code":"relationship_expired"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.RELATIONSHIP_GONE), e.errorMapping())
    }

    @Test
    fun emailNotConfigured_503() {
        val e = httpError(
            503,
            """{"detail":"email not configured","code":"email_not_configured"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.EMAIL_NOT_CONFIGURED), e.errorMapping())
    }

    @Test
    fun llmNotConfigured_503_byDetail() {
        val e = httpError(
            503,
            """{"detail":"no LLM provider is configured on the server; set at least one provider API key in the admin console (/admin); reply generation is unavailable"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.LLM_NOT_CONFIGURED), e.errorMapping())
    }

    @Test
    fun replyGenerationFailed_502_byCode() {
        val e = httpError(
            502,
            """{"detail":"generated reply did not pass the content filter after 2 attempts","code":"content_filter_failed"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.CONTENT_FILTER_FAILED), e.errorMapping())
    }

    @Test
    fun chineseAuthDetail_400_byDetail() {
        // Backend auth errors are already Chinese; they must still map
        // to a key (so English mode shows the English string, not the
        // Chinese detail).
        val e = httpError(400, """{"detail":"验证码错误或已过期"}""")
        assertEquals(ErrorMapping(ErrorKey.CODE_INVALID), e.errorMapping())
        val e2 = httpError(401, """{"detail":"邮箱或密码错误"}""")
        assertEquals(ErrorMapping(ErrorKey.INVALID_CREDENTIALS), e2.errorMapping())
    }

    // ---- Fallbacks: never leak raw text ----

    @Test
    fun unknownCode_fallsBackToStatus() {
        val e = httpError(429, """{"detail":"something brand new","code":"brand_new_code"}""")
        assertEquals(ErrorMapping(ErrorKey.TOO_FREQUENT), e.errorMapping())
    }

    @Test
    fun unknownEnglishDetail_neverSurfaces() {
        val e = httpError(400, """{"detail":"some future english error nobody mapped yet"}""")
        assertEquals(ErrorMapping(ErrorKey.BAD_REQUEST), e.errorMapping())
    }

    @Test
    fun validationListDetail_422() {
        // FastAPI 422 bodies carry detail as a list, not a string.
        val e = httpError(
            422,
            """{"detail":[{"loc":["body","text"],"msg":"field required","type":"missing"}]}"""
        )
        assertEquals(ErrorMapping(ErrorKey.VALIDATION_ERROR), e.errorMapping())
    }

    @Test
    fun ioException_isServerUnreachable() {
        assertEquals(
            ErrorMapping(ErrorKey.SERVER_UNREACHABLE),
            IOException("Unable to resolve host").errorMapping()
        )
    }

    @Test
    fun genericException_isUnknown() {
        // A raw exception message (e.g. "empty captcha") must never
        // reach the user.
        assertEquals(
            ErrorMapping(ErrorKey.UNKNOWN_ERROR),
            RuntimeException("empty captcha").errorMapping()
        )
    }

    @Test
    fun parseLimitCount_defaultsToOne() {
        assertEquals(1, parseLimitCount(null))
        assertEquals(1, parseLimitCount("active character limit reached; end first"))
        assertEquals(3, parseLimitCount("active character limit reached (3); end first"))
    }

    // ---- 18+ registration gate (400 age_under_18) ----

    @Test
    fun ageUnder18_400_byCode() {
        val e = httpError(
            400,
            """{"detail":"users under 18 are not allowed to register","code":"age_under_18"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.AGE_UNDER_18), e.errorMapping())
    }

    @Test
    fun ageUnder18_400_byDetailOnly() {
        // Older / codeless responses: the detail substring fallback must
        // still find the under-18 key (never the raw English detail).
        val e = httpError(
            400,
            """{"detail":"you must be 18 years old to use this app"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.AGE_UNDER_18), e.errorMapping())
    }

    @Test
    fun ageUnder18_400_byChineseDetailOnly() {
        val e = httpError(400, """{"detail":"未满 18 周岁不能注册"}""")
        assertEquals(ErrorMapping(ErrorKey.AGE_UNDER_18), e.errorMapping())
    }

    @Test
    fun invalidBirthDate_400_byCode() {
        val e = httpError(
            400,
            """{"detail":"invalid birth date","code":"invalid_birth_date"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.BIRTH_DATE_INVALID), e.errorMapping())
    }

    @Test
    fun birthDateInFuture_400_byCode() {
        val e = httpError(
            400,
            """{"detail":"birth date cannot be in the future","code":"birth_date_in_future"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.BIRTH_DATE_FUTURE), e.errorMapping())
    }

    // ---- Anonymous write gate (403 anonymous_letter_forbidden) ----

    @Test
    fun anonymousLetterForbidden_403_byCode() {
        val e = httpError(
            403,
            """{"detail":"发信需要注册邮箱账号，匿名浏览只能看看","code":"anonymous_letter_forbidden"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.EMAIL_REQUIRED), e.errorMapping())
    }

    @Test
    fun anonymousLetterForbidden_403_byChineseDetailOnly() {
        val e = httpError(403, """{"detail":"发信需要注册邮箱账号，匿名浏览只能看看"}""")
        assertEquals(ErrorMapping(ErrorKey.EMAIL_REQUIRED), e.errorMapping())
    }

    @Test
    fun anonymousLetterForbidden_403_byEnglishDetailOnly() {
        val e = httpError(
            403,
            """{"detail":"anonymous browsing is read-only; sending letters needs an email account"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.EMAIL_REQUIRED), e.errorMapping())
    }

    // ---- Virtual-world name + device-link codes ----

    @Test
    fun invalidDisplayName_400_byCode() {
        val e = httpError(
            400,
            """{"detail":"虚拟世界姓名为 1-20 字，仅限中文、字母、数字","code":"invalid_display_name"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.INVALID_DISPLAY_NAME), e.errorMapping())
    }

    @Test
    fun deviceAlreadyBound_409_byCode() {
        val e = httpError(
            409,
            """{"detail":"该设备已绑定其他邮箱账号","code":"device_already_bound"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.DEVICE_ALREADY_BOUND), e.errorMapping())
    }

    @Test
    fun deviceMismatch_400_byCode() {
        val e = httpError(
            400,
            """{"detail":"device_id 与 device_token 不一致","code":"device_mismatch"}"""
        )
        assertEquals(ErrorMapping(ErrorKey.DEVICE_MISMATCH), e.errorMapping())
    }

    @Test
    fun sessionExpiredException_mapsToSessionExpired() {
        assertEquals(
            ErrorMapping(ErrorKey.SESSION_EXPIRED),
            SessionExpiredException().errorMapping()
        )
    }
}
