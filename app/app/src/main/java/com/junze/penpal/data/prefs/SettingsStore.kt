package com.junze.penpal.data.prefs

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import java.util.UUID

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "penpal_settings")

/**
 * Small persistent settings: device id (generated once), auth token,
 * logged-in account email + whether that email is verified.
 * The backend address is built into the app (ApiClient.DEFAULT_BASE_URL)
 * and is deliberately NOT stored here — the user cannot change it.
 */
class SettingsStore(context: Context) {

    private val store = context.applicationContext.dataStore

    val deviceId: Flow<String> = store.data.map { prefs ->
        prefs[KEY_DEVICE_ID] ?: ""
    }

    val token: Flow<String?> = store.data.map { prefs -> prefs[KEY_TOKEN] }

    val accountEmail: Flow<String?> = store.data.map { prefs -> prefs[KEY_ACCOUNT_EMAIL] }

    val emailVerified: Flow<Boolean> = store.data.map { prefs ->
        prefs[KEY_EMAIL_VERIFIED] ?: false
    }

    /** Virtual-world name (the name pen pals call the user by). Null
     * when no email account is registered / the name is not set yet. */
    val displayName: Flow<String?> = store.data.map { prefs -> prefs[KEY_DISPLAY_NAME] }

    /**
     * True once an email account has been registered / logged in on this
     * device. From then on the email account is the ONLY identity: the
     * anonymous device is retired and the app must never authenticate
     * anonymously again (its token 401s after the backend migration).
     */
    val anonymousRetired: Flow<Boolean> = store.data.map { prefs ->
        prefs[KEY_ANONYMOUS_RETIRED] ?: false
    }

    /** App language: "zh" (default) or "en". Persisted; survives process death. */
    val language: Flow<String> = store.data.map { prefs ->
        prefs[KEY_LANGUAGE] ?: LANGUAGE_DEFAULT
    }

    suspend fun saveLanguage(code: String) {
        val normalized = if (code == LANGUAGE_EN) LANGUAGE_EN else LANGUAGE_DEFAULT
        store.edit { it[KEY_LANGUAGE] = normalized }
    }

    /** Returns the stored device id, generating + persisting one on first run. */
    suspend fun getOrCreateDeviceId(): String {
        val existing = store.data.map { it[KEY_DEVICE_ID] }.first()
        if (!existing.isNullOrBlank()) return existing
        val created = UUID.randomUUID().toString()
        store.edit { it[KEY_DEVICE_ID] = created }
        return created
    }

    suspend fun saveToken(token: String?) {
        store.edit { prefs ->
            if (token == null) prefs.remove(KEY_TOKEN) else prefs[KEY_TOKEN] = token
        }
    }

    suspend fun saveAccountEmail(email: String?) {
        store.edit { prefs ->
            if (email == null) prefs.remove(KEY_ACCOUNT_EMAIL) else prefs[KEY_ACCOUNT_EMAIL] = email
        }
    }

    suspend fun saveEmailVerified(verified: Boolean) {
        store.edit { it[KEY_EMAIL_VERIFIED] = verified }
    }

    suspend fun saveDisplayName(name: String?) {
        store.edit { prefs ->
            if (name == null) prefs.remove(KEY_DISPLAY_NAME) else prefs[KEY_DISPLAY_NAME] = name
        }
    }

    suspend fun setAnonymousRetired(retired: Boolean) {
        store.edit { it[KEY_ANONYMOUS_RETIRED] = retired }
    }

    companion object {
        const val LANGUAGE_DEFAULT = "zh"
        const val LANGUAGE_EN = "en"
        private val KEY_DEVICE_ID = stringPreferencesKey("device_id")
        private val KEY_TOKEN = stringPreferencesKey("auth_token")
        private val KEY_ACCOUNT_EMAIL = stringPreferencesKey("account_email")
        private val KEY_EMAIL_VERIFIED = booleanPreferencesKey("email_verified")
        private val KEY_DISPLAY_NAME = stringPreferencesKey("display_name")
        private val KEY_ANONYMOUS_RETIRED = booleanPreferencesKey("anonymous_retired")
        private val KEY_LANGUAGE = stringPreferencesKey("language")
    }
}
