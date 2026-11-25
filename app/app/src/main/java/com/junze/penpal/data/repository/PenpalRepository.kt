package com.junze.penpal.data.repository

import android.graphics.BitmapFactory
import com.junze.penpal.data.api.ActivityDto
import com.junze.penpal.data.api.ApiClient
import com.junze.penpal.data.api.ApiService
import com.junze.penpal.data.api.AuthResponse
import com.junze.penpal.data.api.CaptchaResult
import com.junze.penpal.data.api.ChangePasswordRequest
import com.junze.penpal.data.api.CharacterDto
import com.junze.penpal.data.api.DailyLoginResponse
import com.junze.penpal.data.api.CharacterPhotoDto
import com.junze.penpal.data.api.DeviceAuthRequest
import com.junze.penpal.data.api.EmailRequest
import com.junze.penpal.data.api.GenericOkResponse
import com.junze.penpal.data.api.LetterDto
import com.junze.penpal.data.api.LoginEmailRequest
import com.junze.penpal.data.api.MembershipStatusDto
import com.junze.penpal.data.api.MessageDto
import com.junze.penpal.data.api.PointsDto
import com.junze.penpal.data.api.PrivacyDto
import com.junze.penpal.data.api.ProcessDueResponse
import com.junze.penpal.data.api.ProfileDto
import com.junze.penpal.data.api.ReadLetterResponse
import com.junze.penpal.data.api.RegisterRequest
import com.junze.penpal.data.api.ResetPasswordRequest
import com.junze.penpal.data.api.SendCodeRequest
import com.junze.penpal.data.api.SendLetterRequest
import com.junze.penpal.data.api.UnlocksDto
import com.junze.penpal.data.api.UnreadCountDto
import com.junze.penpal.data.api.UpdateDisplayNameRequest
import com.junze.penpal.data.api.VerifyRequest
import com.junze.penpal.data.api.VerifyResponse
import com.junze.penpal.data.local.AppDatabase
import com.junze.penpal.data.local.CharacterEntity
import com.junze.penpal.data.local.LetterEntity
import com.junze.penpal.data.prefs.SettingsStore
import com.junze.penpal.ui.components.DeviceAuthException
import com.junze.penpal.ui.components.SessionExpiredException
import com.junze.penpal.ui.components.isAgeGateFailure
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import retrofit2.HttpException
import java.io.IOException

/** Max length of a letter, enforced by the server and by the UI counter. */
const val MAX_LETTER_CHARS = 2000

/**
 * Single source of truth for screens.
 *
 * - Characters / letters: Room cache first, network refresh on top. Offline
 *   the cached rows are shown and a "showing cached content" flag is surfaced.
 * - Auth: device id (UUID, stored once) -> POST /auth/device -> Bearer token.
 *   Email accounts (register / login-email / verify / change-password) use
 *   the same token slot: the account token replaces the device token.
 *   Once an email account exists on this device the anonymous identity is
 *   RETIRED: the backend deletes the anonymous device row on migration,
 *   so its old token 401s. From then on the email account is the only
 *   identity — a 401 never falls back to anonymous auth (that would
 *   silently read a fresh, empty anonymous account's letters / points,
 *   which is exactly how "home shows no letters while a letter is
 *   unanswered" happened). Instead the call fails with
 *   SessionExpiredException and the UI asks the user to sign in.
 * - A connection failure (server not reachable yet) surfaces as IOException;
 *   screens show "服务器未连接，请稍后再试".
 */
class PenpalRepository(
    private val apiClient: ApiClient,
    private val settings: SettingsStore,
    private val db: AppDatabase
) {

    // ---------- Observables (Room cache) ----------

    val characters: Flow<List<CharacterDto>> =
        db.characterDao().observeAll().map { rows -> rows.map { it.toDto() } }

    val letters: Flow<List<LetterDto>> =
        db.letterDao().observeAll().map { rows -> rows.map { it.toDto() } }

    fun lettersForCharacter(characterId: String): Flow<List<LetterDto>> =
        db.letterDao().observeByCharacter(characterId).map { rows -> rows.map { it.toDto() } }

    // ---------- Auth ----------

    /**
     * True once an email account has existed on this device (the stored
     * flag, or a stored account email from an install predating the flag).
     * From then on the anonymous identity is retired — never use it again.
     */
    private suspend fun isAnonymousRetired(): Boolean =
        settings.anonymousRetired.first() || settings.accountEmail.first() != null

    private suspend fun authHeader(): String {
        var token = settings.token.first()
        if (token.isNullOrBlank()) {
            // No session at all: a retired device has no identity to fall
            // back to — ask the user to sign in instead of silently
            // creating a fresh, empty anonymous account.
            if (isAnonymousRetired()) throw SessionExpiredException()
            token = authenticate()
        }
        return "Bearer $token"
    }

    /**
     * First-launch device registration. Works before any email registration,
     * so browsing is usable anonymously. Never called once an email account
     * exists (see isAnonymousRetired). Anonymous auth has no age gate:
     * if an old server still answers it with an age error (400
     * age_required / age_under_18), that failure is converted to a
     * generic [DeviceAuthException] — age wording must never surface
     * for a browse-only identity. Other failures pass through
     * unchanged (a connection failure stays "server unreachable").
     */
    private suspend fun authenticate(): String {
        val deviceId = settings.getOrCreateDeviceId()
        try {
            val response = apiClient.service().authDevice(DeviceAuthRequest(deviceId))
            settings.saveToken(response.token)
            return response.token
        } catch (e: HttpException) {
            if (e.isAgeGateFailure()) throw DeviceAuthException()
            throw e
        }
    }

    /**
     * Runs [block] with a valid token. On HTTP 401:
     * - anonymous device (never registered): re-authenticate once and retry.
     * - email account (anonymous retired): FAIL with SessionExpiredException.
     *   The old anonymous token 401s after the backend migration deletes
     *   the anonymous device, and re-authenticating anonymously would
     *   silently switch the app to a fresh empty account — the exact
     *   cause of the "no letters" / "points are 0" reports.
     * Returns Result.failure on any other error (callers show cached data).
     */
    private suspend fun <T> withAuth(block: suspend (ApiService, String) -> T): Result<T> {
        return try {
            val header = authHeader()
            Result.success(block(apiClient.service(), header))
        } catch (e: SessionExpiredException) {
            Result.failure(e)
        } catch (e: HttpException) {
            if (e.code() == 401) {
                if (runCatching { isAnonymousRetired() }.getOrDefault(false)) {
                    return Result.failure(SessionExpiredException())
                }
                return try {
                    settings.saveToken(null)
                    val header = "Bearer ${authenticate()}"
                    Result.success(block(apiClient.service(), header))
                } catch (retryError: Exception) {
                    Result.failure(retryError)
                }
            }
            Result.failure(e)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // ---------- Email accounts ----------

    /** The account token replaces the device token in the same slot.
     * Backend responses are flat (email / email_verified at top level);
     * a nested `user` object is accepted as a fallback. Registering /
     * logging in also retires the anonymous identity on this device and
     * stores the virtual-world name the user chose. */
    private suspend fun saveAccountSession(response: AuthResponse) {
        settings.saveToken(response.token)
        val email = response.user?.email ?: response.email
        if (email != null) settings.saveAccountEmail(email)
        val verified = response.user?.emailVerified ?: response.emailVerified
        if (verified != null) settings.saveEmailVerified(verified)
        if (response.displayName != null) settings.saveDisplayName(response.displayName)
        settings.setAnonymousRetired(true)
    }

    /**
     * The anonymous device to hand to register / login-email for the
     * one-time migration. Only when the current session is still
     * anonymous (no email account yet): the device id + its bearer token
     * prove ownership, so the backend can fold the trial period's
     * letters / points / relationships / unlocks into the email account.
     * Returns nulls once an email account exists (nothing to migrate).
     */
    private suspend fun anonymousLink(): Pair<String?, String?> {
        if (settings.accountEmail.first() != null) return null to null
        val deviceId = settings.getOrCreateDeviceId().takeIf { it.isNotBlank() }
        val token = settings.token.first().takeIf { !it.isNullOrBlank() }
        return deviceId to token
    }

    /**
     * Captcha image (PNG) + token. The backend delivers the token in a
     * response header (X-Captcha-Token, falling back to Captcha-Token);
     * if the backend ships it another way, adjust here.
     */
    suspend fun getCaptcha(): Result<CaptchaResult> = runCatching {
        val response = apiClient.service().getCaptcha()
        if (!response.isSuccessful) {
            throw HttpException(response)
        }
        val bytes = response.body()?.bytes()
            ?: throw IOException("empty captcha")
        val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        val token = response.headers()["X-Captcha-Token"]
            ?: response.headers()["Captcha-Token"]
            ?: response.headers()["x-captcha-token"]
        CaptchaResult(bitmap, token)
    }

    /**
     * Register an email account. The birth date (YYYY-MM-DD) is required
     * and must be 18+ — the ViewModel enforces that locally first, and
     * the backend refuses under-18s with 400 `age_under_18`. The current
     * anonymous device (id + token) is handed over so the backend
     * migrates the trial period's data into the new account and retires
     * the anonymous identity. From then on the email account is the only
     * identity on this device.
     */
    suspend fun register(
        email: String, password: String, birthDate: String, captchaToken: String, captchaText: String,
        displayName: String
    ): Result<AuthResponse> = runCatching {
        val (deviceId, deviceToken) = anonymousLink()
        apiClient.service().register(
            RegisterRequest(email, password, birthDate, captchaToken, captchaText, displayName, deviceId, deviceToken)
        ).also { saveAccountSession(it) }
    }

    suspend fun sendCode(
        email: String, purpose: String,
        captchaToken: String? = null, captchaText: String? = null
    ): Result<GenericOkResponse> = runCatching {
        apiClient.service().sendCode(SendCodeRequest(email, purpose, captchaToken, captchaText))
    }

    suspend fun verifyEmail(email: String, code: String): Result<VerifyResponse> = runCatching {
        apiClient.service().verify(VerifyRequest(email, code))
            .also { settings.saveEmailVerified(true) }
    }

    /**
     * Log in with email. When the current session is still anonymous, the
     * anonymous device is handed over for the same one-time migration as
     * register (accounts registered before the merge existed). Afterwards
     * the email account is the only identity.
     */
    suspend fun loginEmail(email: String, password: String): Result<AuthResponse> = runCatching {
        val (deviceId, deviceToken) = anonymousLink()
        apiClient.service().loginEmail(LoginEmailRequest(email, password, deviceId, deviceToken))
            .also { saveAccountSession(it) }
    }

    /** Server-truth profile (email + virtual-world name); syncs the local
     * copy so the 我的 page never shows a stale name. */
    suspend fun getProfile(): Result<ProfileDto> =
        withAuth { api, header ->
            api.getProfile(header).also { profile ->
                if (profile.displayName != null) settings.saveDisplayName(profile.displayName)
                if (profile.emailVerified != null) settings.saveEmailVerified(profile.emailVerified)
            }
        }

    /** Rename the virtual-world name (email accounts only). Takes effect
     * immediately on the server; the local copy is updated with the
     * response so the 我的 page shows it at once. */
    suspend fun updateDisplayName(name: String): Result<ProfileDto> =
        withAuth { api, header ->
            api.updateDisplayName(header, UpdateDisplayNameRequest(name)).also { profile ->
                if (profile.displayName != null) settings.saveDisplayName(profile.displayName)
            }
        }

    /**
     * Log out of the email account. The anonymous identity stays retired:
     * the session is simply cleared and the UI asks the user to sign in
     * again — the app never silently creates a fresh anonymous account
     * (its letters / points would be empty). On a device that never
     * registered, the old behaviour (anonymous re-auth) is kept.
     */
    suspend fun logout(): Result<Unit> = runCatching {
        val retired = isAnonymousRetired()
        settings.saveToken(null)
        settings.saveAccountEmail(null)
        settings.saveEmailVerified(false)
        settings.saveDisplayName(null)
        if (!retired) authenticate()
        Unit
    }

    suspend fun forgotPassword(email: String): Result<GenericOkResponse> = runCatching {
        apiClient.service().forgotPassword(EmailRequest(email))
    }

    suspend fun resetPassword(
        email: String, code: String, newPassword: String
    ): Result<GenericOkResponse> = runCatching {
        apiClient.service().resetPassword(ResetPasswordRequest(email, code, newPassword))
    }

    suspend fun changePassword(
        currentPassword: String, newPassword: String
    ): Result<GenericOkResponse> =
        withAuth { api, header ->
            api.changePassword(header, ChangePasswordRequest(currentPassword, newPassword))
        }

    /** Daily login point (M0 endpoint, no body). Best effort. */
    suspend fun dailyLogin(): Result<DailyLoginResponse> =
        withAuth { api, header -> api.dailyLogin(header) }

    suspend fun getPrivacy(): Result<PrivacyDto> = runCatching {
        apiClient.service().getPrivacy()
    }

    // ---------- Characters ----------

    suspend fun refreshCharacters(): Result<Unit> =
        withAuth { api, header ->
            val remote = api.getCharacters(header)
            db.characterDao().insertAll(remote.map { it.toEntity() })
        }

    suspend fun getCharacter(id: String): CharacterDto? =
        db.characterDao().getById(id)?.toDto()

    // ---------- Letters ----------

    suspend fun refreshLetters(characterId: String? = null): Result<Unit> =
        withAuth { api, header ->
            val remote = api.getLetters(header, characterId)
            db.letterDao().insertAll(remote.map { it.toEntity() })
        }

    suspend fun sendLetter(characterId: String, text: String): Result<LetterDto> =
        withAuth { api, header ->
            val created = api.sendLetter(header, SendLetterRequest(characterId, text))
            db.letterDao().insert(created.toEntity())
            created
        }

    suspend fun getLetter(id: Int): LetterDto? = db.letterDao().getById(id)?.toDto()

    suspend fun markLetterRead(id: Int): Result<ReadLetterResponse> =
        withAuth { api, header ->
            api.markLetterRead(header, id).also { updated ->
                db.letterDao().getById(id)?.let { existing ->
                    db.letterDao().insert(
                        existing.copy(
                            readAt = updated.readAt ?: updated.userReadAt,
                            userReadAt = updated.userReadAt ?: updated.readAt,
                            characterReadAt = updated.characterReadAt
                                ?: existing.characterReadAt,
                            expectedReplyAt = updated.expectedReplyAt
                                ?: existing.expectedReplyAt,
                            deliveryStage = updated.deliveryStage
                                ?: existing.deliveryStage,
                            deliveryStageText = updated.deliveryStageText
                                ?: existing.deliveryStageText
                        )
                    )
                }
            }
        }

    /** Unread AI replies, counted by the backend (GET /letters/unread-count). */
    suspend fun getUnreadCount(): Result<Int> =
        withAuth { api, header -> api.getUnreadCount(header).unreadCount }

    /**
     * App-side fallback trigger for due replies (Bug 1): POST
     * /letters/process-due with an empty body (backend defaults to
     * today). Best effort by design — callers ignore failures silently
     * and never block the timeline on this. The reply letters it
     * creates are picked up by the refreshLetters() that follows.
     */
    suspend fun processDue(): Result<ProcessDueResponse> =
        withAuth { api, header -> api.processDue(header) }

    // ---------- Membership / points / unlocks / messages / activities ----------

    /**
     * The single shared points balance (Bug 2): Home and 我的 both
     * read [pointsState].points. The ONLY writer is GET /points;
     * dailyLogin is still called for its +1 award, but its returned
     * balance is never displayed.
     */
    val pointsState = PointsState { getPoints().map { it.points } }

    /** Refresh the shared balance from GET /points. Failure keeps the
     * last good value and records the error — it never resets to 0. */
    suspend fun refreshPoints(): Result<Int> = pointsState.refresh()

    suspend fun getMembershipStatus(): Result<MembershipStatusDto> =
        withAuth { api, header -> api.getMembershipStatus(header) }

    suspend fun getPoints(): Result<PointsDto> =
        withAuth { api, header -> api.getPoints(header) }

    suspend fun getUnlocks(): Result<UnlocksDto> =
        withAuth { api, header -> api.getUnlocks(header) }

    suspend fun getMessages(): Result<List<MessageDto>> =
        withAuth { api, header -> api.getMessages(header) }

    suspend fun getActivities(): Result<List<ActivityDto>> =
        withAuth { api, header -> api.getActivities(header) }

    // ---------- DTO <-> Entity mapping ----------

    private fun CharacterDto.toEntity() = CharacterEntity(
        id = id, name = name, age = age, gender = gender, occupation = occupation,
        appearance = appearance, personality = personality,
        hobbies = hobbies?.joinToString("\n"),
        writingStyle = writingStyle,
        topics = topics?.joinToString("\n"),
        relationship = relationship, photoUrl = photoUrl,
        photoStatus = photoStatus, motto = motto, city = city,
        photos = photos?.mapNotNull { it.photoUrl }?.joinToString("\n"),
        candidPhotos = candidPhotos?.mapNotNull { it.photoUrl }?.joinToString("\n"),
        unlocked = unlocked
    )

    private fun CharacterEntity.toDto() = CharacterDto(
        id = id, name = name, age = age, gender = gender, occupation = occupation,
        appearance = appearance, personality = personality,
        hobbies = hobbies?.split("\n")?.filter { it.isNotBlank() },
        writingStyle = writingStyle,
        topics = topics?.split("\n")?.filter { it.isNotBlank() },
        relationship = relationship, photoUrl = photoUrl,
        photoStatus = photoStatus, motto = motto, city = city,
        photos = photos?.split("\n")?.filter { it.isNotBlank() }
            ?.map { CharacterPhotoDto(photoUrl = it) },
        candidPhotos = candidPhotos?.split("\n")?.filter { it.isNotBlank() }
            ?.map { CharacterPhotoDto(photoUrl = it) },
        unlocked = unlocked
    )

    private fun LetterDto.toEntity() = LetterEntity(
        id = id, characterId = characterId, direction = direction, text = text,
        status = status, replyDueAt = replyDueAt, isFirst = isFirst,
        aiGenerated = aiGenerated, readAt = readAt, createdAt = createdAt,
        userReadAt = userReadAt, characterReadAt = characterReadAt,
        expectedReplyAt = expectedReplyAt, deliveryStage = deliveryStage,
        deliveryStageText = deliveryStageText
    )

    private fun LetterEntity.toDto() = LetterDto(
        id = id, characterId = characterId, direction = direction, text = text,
        status = status, replyDueAt = replyDueAt, isFirst = isFirst,
        aiGenerated = aiGenerated,
        aiLabel = if (aiGenerated == true) "AI 生成" else null,
        readAt = readAt, createdAt = createdAt,
        userReadAt = userReadAt, characterReadAt = characterReadAt,
        expectedReplyAt = expectedReplyAt, deliveryStage = deliveryStage,
        deliveryStageText = deliveryStageText
    )
}
