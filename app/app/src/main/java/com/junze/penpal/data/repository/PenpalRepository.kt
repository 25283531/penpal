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
import com.junze.penpal.data.api.ReadLetterResponse
import com.junze.penpal.data.api.RegisterRequest
import com.junze.penpal.data.api.ResetPasswordRequest
import com.junze.penpal.data.api.SendCodeRequest
import com.junze.penpal.data.api.SendLetterRequest
import com.junze.penpal.data.api.UnlocksDto
import com.junze.penpal.data.api.UnreadCountDto
import com.junze.penpal.data.api.VerifyRequest
import com.junze.penpal.data.api.VerifyResponse
import com.junze.penpal.data.local.AppDatabase
import com.junze.penpal.data.local.CharacterEntity
import com.junze.penpal.data.local.LetterEntity
import com.junze.penpal.data.prefs.SettingsStore
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
 *   On HTTP 401 the token is refreshed once and the call retried.
 *   Email accounts (register / login-email / verify / change-password) use
 *   the same token slot: the account token replaces the device token.
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

    private suspend fun authHeader(): String {
        var token = settings.token.first()
        if (token.isNullOrBlank()) {
            token = authenticate()
        }
        return "Bearer $token"
    }

    /**
     * First-launch device registration. Works before any email registration,
     * so the letter flow is usable anonymously. Never blocks on email.
     */
    private suspend fun authenticate(): String {
        val deviceId = settings.getOrCreateDeviceId()
        val response = apiClient.service().authDevice(DeviceAuthRequest(deviceId))
        settings.saveToken(response.token)
        return response.token
    }

    /**
     * Runs [block] with a valid token; on 401 re-authenticates once and retries.
     * Returns Result.failure on any other error (callers show cached data).
     */
    private suspend fun <T> withAuth(block: suspend (ApiService, String) -> T): Result<T> {
        return try {
            val header = authHeader()
            Result.success(block(apiClient.service(), header))
        } catch (e: HttpException) {
            if (e.code() == 401) {
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
     * a nested `user` object is accepted as a fallback. */
    private suspend fun saveAccountSession(response: AuthResponse) {
        settings.saveToken(response.token)
        val email = response.user?.email ?: response.email
        if (email != null) settings.saveAccountEmail(email)
        val verified = response.user?.emailVerified ?: response.emailVerified
        if (verified != null) settings.saveEmailVerified(verified)
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

    suspend fun register(
        email: String, password: String, age: Int, captchaToken: String, captchaText: String
    ): Result<AuthResponse> = runCatching {
        apiClient.service().register(
            RegisterRequest(email, password, age, captchaToken, captchaText)
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

    suspend fun loginEmail(email: String, password: String): Result<AuthResponse> = runCatching {
        apiClient.service().loginEmail(LoginEmailRequest(email, password))
            .also { saveAccountSession(it) }
    }

    /** Log out of the email account and fall back to anonymous device auth. */
    suspend fun logout(): Result<Unit> = runCatching {
        settings.saveToken(null)
        settings.saveAccountEmail(null)
        settings.saveEmailVerified(false)
        authenticate()
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

    // ---------- Membership / points / unlocks / messages / activities ----------

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
