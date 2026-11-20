package com.junze.penpal.worker

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.junze.penpal.MainActivity
import com.junze.penpal.R

/**
 * Launcher-badge best effort for the unread-reply count.
 *
 * There is NO unified Android API for a launcher icon badge.
 * The only official mechanism is a notification on a channel with
 * setShowBadge(true) + NotificationCompat.setNumber(n): the launcher
 * then decides what to show. What actually happens depends on the
 * launcher / vendor, not on this app:
 *
 * - Pixel launcher (Android 8+): shows a DOT, never a number.
 * - Samsung One UI: shows the NUMBER from setNumber.
 * - Xiaomi MIUI / HyperOS: shows a number, but only if the user
 *   allowed "桌面角标" for the app in system settings; MIUI may
 *   also need the notification to be visible.
 * - Huawei EMUI / HarmonyOS, OPPO ColorOS, vivo OriginOS: show a
 *   number from the notification badge in most versions, but each
 *   has its own settings toggle and its own quirks; some versions
 *   ignore setNumber and show only a dot.
 * - Third-party launchers (Nova etc.): usually a dot, or nothing.
 * - If notifications are denied (Android 13+ permission), no badge
 *   can appear at all — the notify() call is silently dropped.
 *
 * The old vendor broadcast hacks (ShortcutBadger etc.) are dead:
 * unmaintained, blocked on modern Android, and not used here.
 *
 * So this helper posts ONE quiet notification carrying the count and
 * cancels it as soon as the count reaches 0 (read = badge cleared).
 * The count itself always comes from GET /letters/unread-count —
 * it is never guessed locally.
 */
object UnreadBadge {

    const val CHANNEL_ID = "penpal_unread"
    const val NOTIFICATION_ID = 1002

    fun update(context: Context, unread: Int) {
        val manager = NotificationManagerCompat.from(context)
        if (unread <= 0) {
            manager.cancel(NOTIFICATION_ID)
            return
        }
        createChannel(context)
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        val pendingIntent = PendingIntent.getActivity(
            context, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(context.getString(R.string.unread_notification_title, unread))
            .setContentText(context.getString(R.string.unread_notification_text))
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setNumber(unread)
            .setBadgeIconType(NotificationCompat.BADGE_ICON_SMALL)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setSilent(true)
            .build()
        try {
            manager.notify(NOTIFICATION_ID, notification)
        } catch (_: SecurityException) {
            // Notifications denied: no badge can appear. Nothing else to do.
        }
    }

    private fun createChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            context.getString(R.string.unread_channel_name),
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = context.getString(R.string.unread_channel_desc)
            setShowBadge(true)
        }
        context.getSystemService(NotificationManager::class.java)
            ?.createNotificationChannel(channel)
    }
}
