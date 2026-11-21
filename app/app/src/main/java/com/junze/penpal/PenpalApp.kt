package com.junze.penpal

import android.app.Application
import com.junze.penpal.data.api.ApiClient
import com.junze.penpal.data.local.AppDatabase
import com.junze.penpal.data.prefs.SettingsStore
import com.junze.penpal.data.repository.PenpalRepository
import com.junze.penpal.ui.components.LocaleHelper
import com.junze.penpal.worker.ReminderWorker

/**
 * Manual DI container — no DI framework, everything is wired here and
 * passed to screens from MainActivity.
 *
 * The backend address is built into the app (ApiClient.DEFAULT_BASE_URL)
 * — the user cannot change it.
 */
class PenpalApp : Application() {

    lateinit var settings: SettingsStore
        private set
    lateinit var apiClient: ApiClient
        private set
    lateinit var repository: PenpalRepository
        private set

    override fun onCreate() {
        super.onCreate()
        settings = SettingsStore(this)
        // Apply the stored language before anything reads Locale.getDefault()
        // (TimeFormat, displayGender). Activity resources are wrapped
        // separately in MainActivity.attachBaseContext.
        LocaleHelper.apply(LocaleHelper.readStoredLanguage(this))
        apiClient = ApiClient()
        repository = PenpalRepository(
            apiClient = apiClient,
            settings = settings,
            db = AppDatabase.get(this)
        )

        // Daily local reminders at 8:00 and 20:00.
        ReminderWorker.schedule(this)
    }
}
