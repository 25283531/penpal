package com.junze.penpal.data.api

import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Backend contract: base url is <server>/api/v1 (see ApiClient).
 *
 * Email-auth endpoints were verified against the backend's actual M1
 * code (backend/app/main.py + email_auth.py, read 2026-11-20) and the
 * DTOs below match what it really returns — notably:
 * - register / login-email return a FLAT object: token, device_id,
 *   email, email_verified (no nested `user`, no `email_sent`).
 * - register sends NO email; verification is POST /auth/send-code
 *   {email, purpose:"verify"} then POST /auth/verify {email, code}.
 * - GET /auth/captcha returns PNG bytes with the token in the
 *   X-Captcha-Token response header.
 * - POST /auth/change-password takes {current_password?, code?,
 *   new_password} with a Bearer token (verified users use the password).
 * - GET /privacy returns {text, updated_at} with no auth header.
 * - POST /auth/login in M0 is the daily-login points call (no body);
 *   email login is POST /auth/login-email.
 * - M0 has no GET /api/v1/auth/me; the app keeps the verification state
 *   from the register / login-email response and persists it locally.
 *   (2026-11-21: the backend added GET /auth/me + PATCH
 *   /auth/display-name; see ProfileDto below.)
 * - Letter ids are ints in the backend (not strings).
 */

// ---------- Device auth (exists in M0) ----------

data class DeviceAuthRequest(val deviceId: String)

data class DeviceAuthResponse(
    val token: String,
    val deviceId: String? = null,
    val plan: String? = null,
    val minorMode: Boolean? = null,
    val age: Int? = null
)

data class DailyLoginResponse(
    val deviceId: String? = null,
    val pointsAwarded: Int? = null,
    val points: Int? = null
)

// ---------- Email accounts [email-auth] ----------

/**
 * Captcha image (PNG bytes) + the token that must be sent back with
 * [RegisterRequest.captchaToken]. The backend delivers the token in a
 * response header (X-Captcha-Token / Captcha-Token); see
 * PenpalRepository.getCaptcha.
 */
data class CaptchaResult(
    val bitmap: android.graphics.Bitmap?,
    val token: String?
)

data class RegisterRequest(
    val email: String,
    val password: String,
    val age: Int,
    val captchaToken: String,
    val captchaText: String,
    /** Virtual-world name (required): 1-20 chars, Chinese / letters / digits. */
    val displayName: String,
    /** Anonymous device whose data migrates into the new email account
     * (letters / points / relationships / unlocks); null = no link. */
    val deviceId: String? = null,
    /** Anonymous bearer token for the same device (proves ownership);
     * wins over deviceId when both are given. */
    val deviceToken: String? = null
)

data class LoginEmailRequest(
    val email: String,
    val password: String,
    /** Anonymous device to merge into this email account on login
     * (one-time migration for accounts registered before the merge
     * existed); null = no merge. */
    val deviceId: String? = null,
    val deviceToken: String? = null
)

data class AccountDto(
    val id: Int? = null,
    val email: String,
    val emailVerified: Boolean = false,
    val createdAt: String? = null
)

/** Returned by register / login-email. The backend returns a FLAT object
 * (verified against backend/app/main.py 2026-11-20): token, device_id,
 * email, email_verified — there is NO nested `user` object and NO
 * `email_sent` (registration sends no email; verification uses send-code).
 * The nested-user fields are kept only as a fallback if the backend
 * ever nests them. */
data class AuthResponse(
    val token: String,
    val deviceId: String? = null,
    val email: String? = null,
    val emailVerified: Boolean? = null,
    /** Virtual-world name (register / login-email echo it back). */
    val displayName: String? = null,
    /** True when an anonymous device was linked + migrated. */
    val linkedAnonymousDevice: Boolean? = null,
    /** What the one-time anonymous -> email migration moved, if any. */
    val migrated: MigratedDto? = null,
    val user: AccountDto? = null,
    val emailSent: Boolean? = null
)

/** Counts from the backend's one-time anonymous -> email merge. */
data class MigratedDto(
    val merged: Boolean? = null,
    val lettersMoved: Int? = null,
    val pointsMoved: Int? = null,
    val pointsDroppedDuplicate: Int? = null,
    val relationshipsMoved: Int? = null,
    val memoriesMoved: Int? = null
)

/** GET /api/v1/auth/me: email account + virtual-world name. Anonymous
 * devices get email / displayName null. */
data class ProfileDto(
    val deviceId: String? = null,
    val email: String? = null,
    val displayName: String? = null,
    val emailVerified: Boolean? = null,
    val plan: String? = null
)

data class UpdateDisplayNameRequest(val displayName: String)

data class SendCodeRequest(
    val email: String,
    /** "verify" (email verification) or "reset" (forgot password). */
    val purpose: String,
    /** Only needed after 2 failed send-code attempts (backend captcha gate). */
    val captchaToken: String? = null,
    val captchaText: String? = null
)

data class VerifyRequest(
    val email: String,
    val code: String
)

data class EmailRequest(val email: String)

data class ResetPasswordRequest(
    val email: String,
    val code: String,
    val newPassword: String
)

data class ChangePasswordRequest(
    val currentPassword: String,
    val newPassword: String
)

data class GenericOkResponse(
    val ok: Boolean? = null,
    val message: String? = null,
    val detail: String? = null,
    val emailSent: Boolean? = null,
    val alreadyVerified: Boolean? = null
)

/** Backend returns {"ok": true, "email_verified": true}. */
data class VerifyResponse(
    val ok: Boolean? = null,
    val emailVerified: Boolean? = null,
    val user: AccountDto? = null,
    val message: String? = null
)

// ---------- Privacy ----------

data class PrivacyDto(
    val version: String? = null,
    val updatedAt: String? = null,
    val text: String
)

// ---------- Characters (exists in M0) ----------

data class CharacterPhotoDto(
    val photoUrl: String? = null,
    val isPlaceholder: Boolean? = null,
    val label: String? = null,
    /** Which slot this is, e.g. "主生活照" / "工作场景" / "日常场景". */
    val scene: String? = null
)

data class CharacterDto(
    val id: String,
    val name: String,
    val age: Int? = null,
    val gender: String? = null,
    val occupation: String? = null,
    val appearance: String? = null,
    val personality: String? = null,
    val hobbies: List<String>? = null,
    val writingStyle: String? = null,
    val topics: List<String>? = null,
    val relationship: String? = null,
    val isAi: Boolean? = null,
    val aiLabel: String? = null,
    val photoUrl: String? = null,
    val photoStatus: String? = null,
    /** 交友宣言 (backend: motto). */
    val motto: String? = null,
    val city: String? = null,
    /** 3 张生活照；photo_url 为 null / is_placeholder 时是占位 (backend: photos). */
    val photos: List<CharacterPhotoDto>? = null,
    /** 2 张随拍，后端已备好字段，供以后回信附图用；App 暂不展示 (backend: candid_photos). */
    val candidPhotos: List<CharacterPhotoDto>? = null,
    /** True when this device may write to the character; locked ones are hidden. */
    val unlocked: Boolean = true
)

// ---------- Letters (exists in M0) ----------

data class LetterDto(
    val id: Int,
    val characterId: String,
    /** "user" (mine) or "ai" (reply). */
    val direction: String,
    val text: String,
    val status: String? = null,
    /** "YYYY-MM-DD" — when the reply is due (first letter: same day). */
    val replyDueAt: String? = null,
    val isFirst: Boolean? = null,
    val aiGenerated: Boolean? = null,
    val aiLabel: String? = null,
    val readAt: String? = null,
    val createdAt: String? = null,
    val repliedAt: String? = null,
    /** 用户读回信的时间 (ISO 8601)，null = 未读。 */
    val userReadAt: String? = null,
    /** 虚拟人物读用户来信的时间 (ISO 8601)，null = 尚未读信。 */
    val characterReadAt: String? = null,
    /** 预计回信时间 (ISO 8601)。 */
    val expectedReplyAt: String? = null,
    /** 在途阶段英文枚举，如 "delivered" / "on_the_way" / "replying"。 */
    val deliveryStage: String? = null,
    /** 诗意中文状态，后端原样返回，客户端不编进度。 */
    val deliveryStageText: String? = null
)

data class SendLetterRequest(
    val characterId: String,
    val text: String
)

data class ReadLetterResponse(
    val id: Int,
    val characterId: String,
    val direction: String,
    val text: String,
    val status: String? = null,
    val replyDueAt: String? = null,
    val isFirst: Boolean? = null,
    val aiGenerated: Boolean? = null,
    val aiLabel: String? = null,
    val readAt: String? = null,
    val createdAt: String? = null,
    val repliedAt: String? = null,
    val userReadAt: String? = null,
    val characterReadAt: String? = null,
    val expectedReplyAt: String? = null,
    val deliveryStage: String? = null,
    val deliveryStageText: String? = null,
    val pointsAwarded: Int? = null
)

/** GET /api/v1/letters/unread-count returns {"unread_count": N}. */
data class UnreadCountDto(
    val unreadCount: Int = 0
)

/**
 * POST /api/v1/letters/process-due: App-side fallback trigger for due
 * replies (Bug 1). The backend has no scheduled job, so without this
 * call a due reply is only generated when somebody POSTs manually.
 * Body is `{}` (date omitted -> the backend defaults to today);
 * `date` is only a test/simulation override ("YYYY-MM-DD").
 * Response: {"processed": n, "replied": n, "queued": n, "failed": n,
 * "llm_unavailable": bool, "details": [...]}. `queued` counts letters
 * not due yet OR un-generatable (no LLM configured) — both honestly
 * stay in_transit; a reply is never faked.
 */
data class ProcessDueRequest(
    val date: String? = null
)

data class ProcessDueDetailDto(
    val letterId: Int? = null,
    val replyId: Int? = null,
    val status: String? = null,
    val code: String? = null
)

data class ProcessDueResponse(
    val processed: Int = 0,
    val replied: Int = 0,
    val queued: Int = 0,
    val failed: Int = 0,
    val llmUnavailable: Boolean = false,
    val details: List<ProcessDueDetailDto>? = null
)

// ---------- Membership / points / unlocks (exist in M0) ----------

data class MembershipStatusDto(
    /** "free" | "member" | "premium" (phase 1: everyone free). */
    val plan: String,
    val phase1Free: Boolean? = null,
    val paywalled: Boolean? = null,
    val maxActiveCharacters: Int? = null,
    val dailySendCap: Int? = null,
    val replyIntervalDays: Int? = null,
    val priceMemberCny: Double? = null,
    val pricePremiumCny: Double? = null
)

data class PointEventDto(
    val id: Int? = null,
    val kind: String? = null,
    val points: Int? = null,
    val refId: String? = null,
    val date: String? = null,
    val createdAt: String? = null
)

data class PointsDto(
    val points: Int,
    val events: List<PointEventDto>? = null
)

data class UnlocksDto(
    val points: Int? = null,
    val referralCount: Int? = null,
    val pointsUnlocks: Int? = null,
    val referralUnlocks: Int? = null,
    val entitledCharacterIds: List<String>? = null,
    val unlockedCharacterIds: List<String>? = null,
    val thresholds: Map<String, List<Int>>? = null
)

// ---------- Messages / activities (exist in M0, fetch-on-open) ----------

data class MessageDto(
    val id: Int,
    val title: String,
    val body: String? = null,
    val content: String? = null,
    val createdAt: String? = null
) {
    fun text(): String = body ?: content ?: ""
}

data class ActivityDto(
    val id: Int,
    val title: String,
    val body: String? = null,
    val content: String? = null,
    val imageUrl: String? = null,
    val startAt: String? = null,
    val endAt: String? = null
) {
    fun text(): String = body ?: content ?: ""
}

interface ApiService {

    @POST("auth/device")
    suspend fun authDevice(@Body request: DeviceAuthRequest): DeviceAuthResponse

    /** Daily login point (M0: no body, awards +1 once per day). */
    @POST("auth/login")
    suspend fun dailyLogin(@Header("Authorization") token: String): DailyLoginResponse

    // ---- Email accounts [email-auth] ----

    @GET("auth/captcha")
    suspend fun getCaptcha(): Response<ResponseBody>

    @POST("auth/register")
    suspend fun register(@Body request: RegisterRequest): AuthResponse

    @POST("auth/send-code")
    suspend fun sendCode(@Body request: SendCodeRequest): GenericOkResponse

    @POST("auth/verify")
    suspend fun verify(@Body request: VerifyRequest): VerifyResponse

    @POST("auth/login-email")
    suspend fun loginEmail(@Body request: LoginEmailRequest): AuthResponse

    /** Profile for the 我的 page: email account + virtual-world name. */
    @GET("auth/me")
    suspend fun getProfile(@Header("Authorization") token: String): ProfileDto

    /** Rename the virtual-world name (email accounts only; takes effect
     * immediately — the next reply generation reads it live). */
    @PATCH("auth/display-name")
    suspend fun updateDisplayName(
        @Header("Authorization") token: String,
        @Body request: UpdateDisplayNameRequest
    ): ProfileDto

    @POST("auth/change-password")
    suspend fun changePassword(
        @Header("Authorization") token: String,
        @Body request: ChangePasswordRequest
    ): GenericOkResponse

    @POST("auth/forgot-password")
    suspend fun forgotPassword(@Body request: EmailRequest): GenericOkResponse

    @POST("auth/reset-password")
    suspend fun resetPassword(@Body request: ResetPasswordRequest): GenericOkResponse

    // ---- Privacy (public; no auth header) ----

    @GET("privacy")
    suspend fun getPrivacy(): PrivacyDto

    // ---- Characters ----

    @GET("characters")
    suspend fun getCharacters(@Header("Authorization") token: String): List<CharacterDto>

    @GET("characters/{id}")
    suspend fun getCharacter(
        @Header("Authorization") token: String,
        @Path("id") id: String
    ): CharacterDto

    // ---- Letters ----

    @POST("letters")
    suspend fun sendLetter(
        @Header("Authorization") token: String,
        @Body request: SendLetterRequest
    ): LetterDto

    @GET("letters")
    suspend fun getLetters(
        @Header("Authorization") token: String,
        @Query("character_id") characterId: String? = null
    ): List<LetterDto>

    @GET("letters/{id}")
    suspend fun getLetter(
        @Header("Authorization") token: String,
        @Path("id") id: Int
    ): LetterDto

    @POST("letters/{id}/read")
    suspend fun markLetterRead(
        @Header("Authorization") token: String,
        @Path("id") id: Int
    ): ReadLetterResponse

    /** Unread AI replies, counted by the backend — never guessed locally. */
    @GET("letters/unread-count")
    suspend fun getUnreadCount(
        @Header("Authorization") token: String
    ): UnreadCountDto

    /**
     * Generate replies for this account's due letters (App-side
     * fallback — the backend runs no scheduler yet). Empty body means
     * "today". Safe to call when nothing is due: it just returns
     * processed=0. Callers treat any failure as best-effort/silent.
     */
    @POST("letters/process-due")
    suspend fun processDue(
        @Header("Authorization") token: String,
        @Body request: ProcessDueRequest = ProcessDueRequest()
    ): ProcessDueResponse

    // ---- Membership / points / unlocks ----

    @GET("membership/status")
    suspend fun getMembershipStatus(@Header("Authorization") token: String): MembershipStatusDto

    @GET("points")
    suspend fun getPoints(@Header("Authorization") token: String): PointsDto

    @GET("unlocks")
    suspend fun getUnlocks(@Header("Authorization") token: String): UnlocksDto

    // ---- Messages / activities ----

    @GET("activities")
    suspend fun getActivities(@Header("Authorization") token: String): List<ActivityDto>

    @GET("messages")
    suspend fun getMessages(@Header("Authorization") token: String): List<MessageDto>
}
