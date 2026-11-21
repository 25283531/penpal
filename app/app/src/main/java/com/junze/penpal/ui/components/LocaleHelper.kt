package com.junze.penpal.ui.components

import android.content.Context
import android.content.res.Configuration
import android.os.Build
import com.junze.penpal.data.prefs.SettingsStore
import java.util.Locale
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking

/**
 * In-app language (Chinese default, English optional).
 *
 * The language is stored in DataStore ([SettingsStore.language]) and
 * applied two ways, because neither alone covers everything:
 * - [wrap]: returns a Context whose resources resolve values-en when
 *   English is chosen. MainActivity applies it in attachBaseContext,
 *   so every stringResource in the UI follows the chosen language.
 * - [apply]: sets Locale.getDefault(), which the non-composable
 *   formatters (TimeFormat date patterns, displayGender) read.
 *
 * Switching recreates the Activity (not the app): the new locale is
 * read back in attachBaseContext and the UI rebuilds immediately.
 * The choice survives process death because it is persisted.
 */
object LocaleHelper {

    const val LANGUAGE_ZH = "zh"
    const val LANGUAGE_EN = "en"

    fun localeFor(code: String): Locale = when (code) {
        LANGUAGE_EN -> Locale.ENGLISH
        else -> Locale.CHINESE
    }

    fun isEnglish(code: String): Boolean = code == LANGUAGE_EN

    /** Sets the JVM default locale used by the plain (non-composable) formatters. */
    fun apply(code: String) {
        Locale.setDefault(localeFor(code))
    }

    /** Context whose resources resolve in [code]'s language. */
    fun wrap(base: Context, code: String): Context {
        val locale = localeFor(code)
        Locale.setDefault(locale)
        val config = Configuration(base.resources.configuration)
        config.setLocale(locale)
        // setLayoutDirection follows the locale; both supported languages
        // are LTR, but keep the call correct for future RTL languages.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR1) {
            config.setLayoutDirection(locale)
        }
        return base.createConfigurationContext(config)
    }

    /**
     * Synchronous read of the stored language, for attachBaseContext
     * (no coroutine scope exists yet). Falls back to Chinese on any
     * failure — the default language must never crash startup.
     */
    fun readStoredLanguage(context: Context): String {
        return try {
            runBlocking {
                SettingsStore(context.applicationContext).language.first()
            }
        } catch (_: Exception) {
            LANGUAGE_ZH
        }
    }
}
