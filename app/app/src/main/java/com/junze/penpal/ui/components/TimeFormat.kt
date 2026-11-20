package com.junze.penpal.ui.components

import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** All dates shown to the user are in Asia/Shanghai. */
val SHANGHAI_ZONE: ZoneId = ZoneId.of("Asia/Shanghai")

/**
 * Parses the backend's date shapes: "YYYY-MM-DD", ISO local datetime,
 * ISO with offset, or ISO with Z. Returns null when unparseable —
 * callers fall back to showing the raw string, never an invented time.
 *
 * Timezone rule (matches the backend): timestamps stored WITHOUT an
 * offset are UTC (SQLite datetime('now') / datetime.now(timezone.utc)
 * formatted "%Y-%m-%d %H:%M:%S"), so naive datetimes are read as UTC
 * and converted to Asia/Shanghai. Date-only values (expected_reply_at)
 * stay date-only.
 */
fun parseShanghaiDateTime(raw: String?): java.time.ZonedDateTime? {
    if (raw.isNullOrBlank()) return null
    val text = raw.trim()
    return try {
        Instant.parse(text).atZone(SHANGHAI_ZONE)
    } catch (_: Exception) {
        try {
            OffsetDateTime.parse(text).atZoneSameInstant(SHANGHAI_ZONE)
        } catch (_: Exception) {
            try {
                val naive = LocalDateTime.parse(
                    text,
                    DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
                )
                naive.atZone(ZoneId.of("UTC")).withZoneSameInstant(SHANGHAI_ZONE)
            } catch (_: Exception) {
                try {
                    LocalDateTime.parse(text).atZone(ZoneId.of("UTC"))
                        .withZoneSameInstant(SHANGHAI_ZONE)
                } catch (_: Exception) {
                    try {
                        LocalDate.parse(text.take(10)).atStartOfDay(SHANGHAI_ZONE)
                    } catch (_: Exception) {
                        null
                    }
                }
            }
        }
    }
}

/** "11月23日 20:15" (Asia/Shanghai). Falls back to the raw string. */
fun formatDateTimeShanghai(raw: String?): String {
    if (raw.isNullOrBlank()) return ""
    val parsed = parseShanghaiDateTime(raw) ?: return raw
    return parsed.format(DateTimeFormatter.ofPattern("M月d日 HH:mm"))
}

/** "11月23日" (Asia/Shanghai). Falls back to the raw string. */
fun formatDateShanghai(raw: String?): String {
    if (raw.isNullOrBlank()) return ""
    val parsed = parseShanghaiDateTime(raw) ?: return raw
    return parsed.format(DateTimeFormatter.ofPattern("M月d日"))
}

/**
 * Expected-reply line, from the backend's expected_reply_at (ISO 8601),
 * falling back to the legacy reply_due_at ("YYYY-MM-DD").
 * - due today -> "预计今天回信"
 * - due later -> "预计 M月d日 回信"
 * - no date at all -> "" (nothing is shown, nothing is invented)
 */
fun expectedReplyText(expectedReplyAt: String?, replyDueAt: String?): String {
    val raw = expectedReplyAt?.takeIf { it.isNotBlank() } ?: replyDueAt?.takeIf { it.isNotBlank() }
        ?: return ""
    val parsed = parseShanghaiDateTime(raw) ?: return "预计回信：$raw"
    val today = LocalDate.now(SHANGHAI_ZONE)
    return if (parsed.toLocalDate() <= today) {
        "预计今天回信"
    } else {
        "预计 ${parsed.format(DateTimeFormatter.ofPattern("M月d日"))} 回信"
    }
}
