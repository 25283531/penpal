package com.junze.penpal.data.repository

import java.io.IOException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The shared points balance (Bug 2): Home and 我的 read the same
 * [PointsState.points] flow, written only by GET /points.
 *
 * Regression test for the reported "Home shows 4, 我的 shows 0":
 * the two pages used to read different endpoints with different
 * failure semantics — Home kept its last good value on failure,
 * 我的 rendered a failed load as a literal 0. These tests pin the
 * rules that must never regress:
 *  - before the first successful load the value is null (unknown),
 *    never 0;
 *  - a failed refresh keeps the last good value and records the
 *    error, it never clears the value or invents 0;
 *  - two readers of the same state (Home + 我的) always see the
 *    identical value, success or failure.
 *
 * Pure JVM (no Android framework): only the state holder is tested
 * here. The ViewModels just expose this flow, so if the holder holds,
 * the screens cannot diverge.
 */
class PointsStateTest {

    /** Fake GET /points: the test controls what each refresh returns. */
    private class FakePointsApi {
        var next: Result<Int> = Result.success(0)
        var calls = 0
        suspend fun fetch(): Result<Int> {
            calls++
            return next
        }
    }

    @Test
    fun initialValue_isNullNotZero() {
        val state = PointsState { Result.success(4) }
        // Unknown, not 0: the UI must show loading / load-failed.
        assertNull(state.points.value)
        assertNull(state.error.value)
    }

    @Test
    fun success_setsValueAndClearsPreviousError() = runBlocking {
        val api = FakePointsApi()
        val state = PointsState { api.fetch() }

        api.next = Result.failure(IOException("unreachable"))
        state.refresh()
        assertNull(state.points.value)
        assertTrue(state.error.value is IOException)

        api.next = Result.success(4)
        val result = state.refresh()
        assertEquals(Result.success(4), result)
        assertEquals(4, state.points.value)
        assertNull(state.error.value)
    }

    @Test
    fun failure_keepsLastGoodValue_neverResetsToNullOrZero() = runBlocking {
        // Regression: Home showed the stale 4 while 我的 showed 0
        // after the same failed refresh. One shared value must keep 4
        // for BOTH pages; the failure is recorded as an error, not as 0.
        val api = FakePointsApi()
        val state = PointsState { api.fetch() }

        api.next = Result.success(4)
        state.refresh()
        assertEquals(4, state.points.value)

        api.next = Result.failure(IOException("unreachable"))
        val result = state.refresh()
        assertTrue(result.isFailure)
        assertEquals(4, state.points.value)
        assertTrue(state.error.value is IOException)
    }

    @Test
    fun twoReadersSeeSameValue_successAndFailure() = runBlocking {
        // Home and 我的 are just two readers of the same flow: after
        // one refresh they must agree, and after a failed refresh they
        // must still agree (on the last good value).
        val api = FakePointsApi()
        val state = PointsState { api.fetch() }
        val homePoints: () -> Int? = { state.points.value }
        val mePoints: () -> Int? = { state.points.value }

        api.next = Result.success(4)
        state.refresh()
        assertEquals(4, homePoints())
        assertEquals(4, mePoints())
        assertEquals(homePoints(), mePoints())

        api.next = Result.failure(IOException("unreachable"))
        state.refresh()
        assertEquals(4, homePoints())
        assertEquals(4, mePoints())
        assertEquals(homePoints(), mePoints())
    }

    @Test
    fun refresh_returnsFetchResult() = runBlocking {
        val api = FakePointsApi()
        val state = PointsState { api.fetch() }
        api.next = Result.success(7)
        assertEquals(Result.success(7), state.refresh())
        assertEquals(1, api.calls)
    }
}
