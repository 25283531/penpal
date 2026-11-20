package com.junze.penpal.data.api

import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
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
    val captchaText: String
)

data class LoginEmailRequest(
    val email: String,
    val password: String
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
    val user: AccountDto? = null,
    val emailSent: Boolean? = null
)

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
    val repliedAt: String? = null
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
    val pointsAwarded: Int? = null
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
