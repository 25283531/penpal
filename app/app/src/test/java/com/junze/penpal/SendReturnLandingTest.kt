package com.junze.penpal

import com.junze.penpal.ui.nav.Routes
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The "寄出" landing screen (sendReturnLandingRoute in MainActivity.kt):
 * from a letter detail the write screen pops twice, otherwise once.
 * Pure JVM tests (no NavController) over the back-stack routes.
 */
class SendReturnLandingTest {

    @Test
    fun homeDetailReplySend_returnsHome() {
        // The reported bug's path: 首页时间线 -> 信件详情 -> 回信 ->
        // 寄出 must land back on the Home timeline, not on the detail.
        val stack = listOf(
            Routes.HOME,
            Routes.LETTER_DETAIL,
            Routes.WRITE_LETTER
        )
        assertEquals(Routes.HOME, sendReturnLandingRoute(stack, true))
    }

    @Test
    fun characterDetailWriteSend_landsOnThread() {
        // 征友页 / 人物详情 -> 写信 -> 寄出: one pop lands on the
        // character thread, never back onto a letter detail.
        val stack = listOf(
            Routes.HOME,
            Routes.CHARACTERS,
            Routes.CHARACTER_DETAIL,
            Routes.WRITE_LETTER
        )
        assertEquals(Routes.CHARACTER_DETAIL, sendReturnLandingRoute(stack, false))
    }

    @Test
    fun characterThreadDetailReplySend_landsOnThread() {
        // 人物详情 -> 信件详情 -> 回信 -> 寄出: two pops land on the
        // thread under the detail — not the detail, and not Home.
        val stack = listOf(
            Routes.HOME,
            Routes.CHARACTERS,
            Routes.CHARACTER_DETAIL,
            Routes.LETTER_DETAIL,
            Routes.WRITE_LETTER
        )
        assertEquals(Routes.CHARACTER_DETAIL, sendReturnLandingRoute(stack, true))
    }

    @Test
    fun tooShortStack_returnsNull() {
        assertNull(sendReturnLandingRoute(listOf(Routes.WRITE_LETTER), false))
        assertNull(
            sendReturnLandingRoute(
                listOf(Routes.LETTER_DETAIL, Routes.WRITE_LETTER),
                true
            )
        )
    }
}
