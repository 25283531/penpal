package com.junze.penpal.worker

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.junze.penpal.MainActivity
import com.junze.penpal.R
import com.junze.penpal.ui.components.LocaleHelper
import java.util.Calendar
import java.util.concurrent.TimeUnit

/**
 * Local daily reminders (no server push): 8:00 "read your reply",
 * 20:00 "write a letter". WorkManager survives reboot; the two periodic
 * works are scheduled once from PenpalApp.
 */
class ReminderWorker(
    appContext: Context,
    params: WorkerParameters
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val slot = inputData.getString(KEY_SLOT) ?: SLOT_MORNING
        // Notifications use the application context, whose resources do
        // not follow the Activity locale — wrap it in the stored app
        // language so reminders arrive in the language the user chose.
        val context = LocaleHelper.wrap(
            applicationContext,
            LocaleHelper.readStoredLanguage(applicationContext)
        )
        val (title, text) = if (slot == SLOT_EVENING) {
            context.getString(R.string.reminder_evening_title) to
                context.getString(R.string.reminder_evening_text)
        } else {
            context.getString(R.string.reminder_morning_title) to
                context.getString(R.string.reminder_morning_text)
        }
        showNotification(title, text)
        return Result.success()
    }

    private fun showNotification(title: String, text: String) {
        val context = applicationContext
        createChannel(
            LocaleHelper.wrap(context, LocaleHelper.readStoredLanguage(context))
        )
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        val pendingIntent = PendingIntent.getActivity(
            context, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(text)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .build()
        NotificationManagerCompat.from(context).notify(NOTIFICATION_ID, notification)
    }

    private fun createChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            context.getString(R.string.reminder_channel_name),
            NotificationManager.IMPORTANCE_DEFAULT
        ).apply { description = context.getString(R.string.reminder_channel_desc) }
        context.getSystemService(NotificationManager::class.java)
            ?.createNotificationChannel(channel)
    }

    companion object {
        const val CHANNEL_ID = "penpal_reminders"
        const val NOTIFICATION_ID = 1001
        const val KEY_SLOT = "slot"
        const val SLOT_MORNING = "morning"
        const val SLOT_EVENING = "evening"

        fun schedule(context: Context) {
            val workManager = WorkManager.getInstance(context.applicationContext)
            scheduleSlot(workManager, SLOT_MORNING, 8)
            scheduleSlot(workManager, SLOT_EVENING, 20)
        }

        private fun scheduleSlot(workManager: WorkManager, slot: String, hour: Int) {
            val now = Calendar.getInstance()
            val next = Calendar.getInstance().apply {
                set(Calendar.HOUR_OF_DAY, hour)
                set(Calendar.MINUTE, 0)
                set(Calendar.SECOND, 0)
                set(Calendar.MILLISECOND, 0)
                if (before(now)) add(Calendar.DAY_OF_YEAR, 1)
            }
            val delayMs = next.timeInMillis - now.timeInMillis
            val request = PeriodicWorkRequestBuilder<ReminderWorker>(24, TimeUnit.HOURS)
                .setInitialDelay(delayMs, TimeUnit.MILLISECONDS)
                .setInputData(workDataOf(KEY_SLOT to slot))
                .build()
            workManager.enqueueUniquePeriodicWork(
                "reminder_$slot",
                ExistingPeriodicWorkPolicy.KEEP,
                request
            )
        }
    }
}
