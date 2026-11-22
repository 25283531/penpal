package com.junze.penpal.data.repository

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * The single source of truth for the user's points balance (Bug 2).
 *
 * Both the Home screen and the 我的 screen read this one flow, so the
 * two pages can never disagree.
 *
 * Root cause it fixes (verified in HomeScreen.kt / MeScreen.kt before
 * this change): the two pages read DIFFERENT endpoints with DIFFERENT
 * failure semantics.
 * - Home took its number from POST /auth/login (dailyLogin, which also
 *   awards the daily +1) with a GET /points fallback — and on failure
 *   it silently KEPT its last good in-memory value (e.g. 4).
 * - 我的 took its number from GET /points only — and on failure its
 *   state stayed null, which the UI rendered as a literal 0
 *   (`points?.points ?: 0`) with no error shown.
 * The success paths cannot diverge: both backend endpoints read the
 * same `database.points_balance(device_id)`. So a "Home 4 / 我的 0"
 * split can only come from one side failing — Home then shows a stale
 * 4, 我的 shows failure-as-0. Home's ViewModel is also scaffold-scoped
 * (long-lived, keeps its value across tab switches) while 我的 refreshes
 * once in init and never again on tab return, so a single transient
 * failure at 我的' first load stuck at 0 while Home self-healed.
 *
 * Rules of this holder:
 * - The ONLY writer of the displayed balance is GET /points
 *   (via [refresh]); dailyLogin is still called for its +1 award, but
 *   its returned balance is never displayed.
 * - A failed refresh NEVER clears the last good value and NEVER
 *   invents 0: it keeps the old value and records the error, so the
 *   UI can say "couldn't load" instead of showing 0.
 * - Before the first successful load the value is null (unknown), not
 *   0 — the UI must render that as loading / load-failed, never as 0.
 *
 * Pure Kotlin (no Android classes) so the rules above are unit-tested
 * on the JVM (see PointsStateTest).
 */
class PointsState(
    private val fetch: suspend () -> Result<Int>
) {
    private val _points = MutableStateFlow<Int?>(null)
    val points: StateFlow<Int?> = _points

    /** Last refresh failure, if any. Cleared by the next success. */
    private val _error = MutableStateFlow<Throwable?>(null)
    val error: StateFlow<Throwable?> = _error

    /** GET /points once. Returns the fetch result; updates the flows. */
    suspend fun refresh(): Result<Int> {
        val result = fetch()
        result
            .onSuccess {
                _points.value = it
                _error.value = null
            }
            .onFailure { _error.value = it }
        return result
    }
}
