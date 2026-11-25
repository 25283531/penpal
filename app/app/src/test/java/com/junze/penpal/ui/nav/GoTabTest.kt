package com.junze.penpal.ui.nav

import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.createGraph
import androidx.navigation.navArgument
import androidx.navigation.testing.TestNavHostController
import com.junze.penpal.navigateToTab
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/**
 * Runtime reproduction of the reported bug: "tapping the '我' tab lands
 * on the change-password page".
 *
 * This test runs the REAL [navigateToTab] from MainActivity.kt (not a
 * copy) against a [TestNavHostController] whose graph mirrors
 * MainScaffold's NavHost route-for-route (same start destination, same
 * routes, same argument types). What it exercises is the exact
 * NavController machinery the app runs on the phone: navigate() with
 * popUpTo(startDestination) { saveState = true } + launchSingleTop +
 * restoreState. Each test asserts both the landing destination AND the
 * full back stack, because the reported symptom could also come from a
 * stale ACCOUNT entry left on the stack (reachable again via
 * system-back from "我").
 *
 * What this test does NOT cover: the Compose layer itself (that the
 * ME destination really renders MeScreen, and that the ACCOUNT
 * destination really renders AccountScreen) — those are separate
 * composable() entries in MainScaffold and cannot swap content.
 * If these tests pass and the user still sees the change-password
 * page, the cause is presentational (MeScreen's own content), not
 * routing — see the "账号与安全" fold in MeScreen.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class GoTabTest {

    private lateinit var navController: TestNavHostController

    /** The back stack as a list of routes, oldest first. */
    private fun stack(): List<String?> =
        navController.backStack.map { it.destination.route }

    @Before
    fun setUp() {
        navController = TestNavHostController(RuntimeEnvironment.getApplication())
        // Mirror of MainScaffold's NavHost: every route, same start.
        navController.graph = navController.createGraph(
            startDestination = Routes.HOME
        ) {
            composable(Routes.HOME) {}
            composable(Routes.CHARACTERS) {}
            composable(
                route = Routes.CHARACTER_DETAIL,
                arguments = listOf(navArgument("characterId") { type = NavType.StringType })
            ) {}
            composable(
                route = Routes.WRITE_LETTER,
                arguments = listOf(navArgument("characterId") { type = NavType.StringType })
            ) {}
            composable(
                route = Routes.LETTER_DETAIL,
                arguments = listOf(navArgument("letterId") { type = NavType.IntType })
            ) {}
            composable(Routes.ME) {}
            composable(Routes.ACCOUNT) {}
            composable(Routes.PRIVACY) {}
        }
        assertEquals(Routes.HOME, navController.currentDestination?.route)
    }

    @Test
    fun home_toMe_landsOnMe() {
        navigateToTab(navController, Routes.ME)
        assertEquals(Routes.ME, navController.currentDestination?.route)
        assertEquals(listOf(Routes.HOME, Routes.ME), stack())
    }

    @Test
    fun characters_toMe_landsOnMe() {
        navController.navigate(Routes.CHARACTERS)
        navigateToTab(navController, Routes.ME)
        assertEquals(Routes.ME, navController.currentDestination?.route)
        assertEquals(listOf(Routes.HOME, Routes.ME), stack())
    }

    @Test
    fun me_account_toMe_popsAccount() {
        // THE reported scenario: on "我", open the account page
        // (change-password form for a verified account), then tap the
        // "我" tab again. Must land on ME with ACCOUNT gone — never on
        // ACCOUNT, and system-back from ME must go HOME, not back to
        // the change-password page.
        navController.navigate(Routes.ME)
        navController.navigate(Routes.ACCOUNT)
        assertEquals(Routes.ACCOUNT, navController.currentDestination?.route)

        navigateToTab(navController, Routes.ME)
        assertEquals(Routes.ME, navController.currentDestination?.route)
        assertEquals(listOf(Routes.HOME, Routes.ME), stack())
        assertFalse(stack().contains(Routes.ACCOUNT))

        assertTrue(navController.popBackStack())
        assertEquals(Routes.HOME, navController.currentDestination?.route)
    }

    @Test
    fun home_account_toMe_landsOnMe() {
        // Home -> account page (login / verify entry) -> "我" tab.
        navController.navigate(Routes.ACCOUNT)
        navigateToTab(navController, Routes.ME)
        assertEquals(Routes.ME, navController.currentDestination?.route)
        assertEquals(listOf(Routes.HOME, Routes.ME), stack())
    }

    @Test
    fun deepLetterStack_toMe_landsOnMe() {
        // 征友信息 -> character detail -> letter detail -> "我" tab.
        navController.navigate(Routes.CHARACTERS)
        navController.navigate(Routes.characterDetail("P01"))
        navController.navigate(Routes.letterDetail(1))
        assertEquals(Routes.LETTER_DETAIL, navController.currentDestination?.route)

        navigateToTab(navController, Routes.ME)
        assertEquals(Routes.ME, navController.currentDestination?.route)
        assertEquals(listOf(Routes.HOME, Routes.ME), stack())
    }

    @Test
    fun me_account_privacy_toMe_popsAll() {
        navController.navigate(Routes.ME)
        navController.navigate(Routes.ACCOUNT)
        navController.navigate(Routes.PRIVACY)
        navigateToTab(navController, Routes.ME)
        assertEquals(Routes.ME, navController.currentDestination?.route)
        assertEquals(listOf(Routes.HOME, Routes.ME), stack())
    }

    @Test
    fun meTab_reselect_doesNotDuplicateMe() {
        navController.navigate(Routes.ME)
        navigateToTab(navController, Routes.ME)
        assertEquals(Routes.ME, navController.currentDestination?.route)
        assertEquals(listOf(Routes.HOME, Routes.ME), stack())
    }

    @Test
    fun account_loginSuccessGoesHome_thenMeTab() {
        // AccountScreen.onLoginSuccess -> goTab(HOME), then "我" tab.
        navController.navigate(Routes.ACCOUNT)
        navigateToTab(navController, Routes.HOME)
        assertEquals(Routes.HOME, navController.currentDestination?.route)
        assertEquals(listOf(Routes.HOME), stack())

        navigateToTab(navController, Routes.ME)
        assertEquals(Routes.ME, navController.currentDestination?.route)
        assertEquals(listOf(Routes.HOME, Routes.ME), stack())
    }

    @Test
    fun onAccount_noTabIsSelected() {
        // While the change-password page is showing, the bottom bar
        // must not highlight any tab (ACCOUNT is not a tab route), so
        // the user cannot mistake the account page for the "我" tab.
        navController.navigate(Routes.ME)
        navController.navigate(Routes.ACCOUNT)
        val current = navController.currentDestination
        val selected = listOf(Routes.HOME, Routes.CHARACTERS, Routes.ME)
            .filter { tab ->
                current?.hierarchy?.any { it.route == tab } == true
            }
        assertTrue(selected.isEmpty())
    }
}
