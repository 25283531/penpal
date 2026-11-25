package com.junze.penpal.ui.nav

import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavType
import androidx.navigation.compose.ComposeNavigator
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

    /**
     * The back stack as a list of routes, oldest first. The NavController
     * also keeps an entry for the NavGraph itself (route null) at the
     * bottom of the queue — it is not a destination, so filter it out.
     */
    private fun stack(): List<String?> =
        navController.backStack.mapNotNull { it.destination.route }

    @Before
    fun setUp() {
        navController = TestNavHostController(RuntimeEnvironment.getApplication())
        // TestNavHostController's provider has no ComposeNavigator, and the
        // composable() graph builder casts its fallback navigator to one
        // (ClassCastException at the first composable() call). Register the
        // real one: destination content never executes under the test
        // controller, only the NavController back-stack machinery runs.
        navController.navigatorProvider.addNavigator(ComposeNavigator())
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

    /**
     * Diagnostic dump: current destination + the full back stack
     * (including the NavGraph entry, shown as "<graph>"), printed to
     * stdout so the CI JUnit XML (system-out) shows exactly what the
     * NavController did at each step, instead of only the final
     * expected/actual of a failed assertion.
     */
    private fun dump(tag: String) {
        val entries = navController.backStack.joinToString(", ") {
            it.destination.route ?: "<graph>"
        }
        println(
            "GOTAB-DIAG [$tag] current=" +
                "${navController.currentDestination?.route} stack=[$entries]"
        )
    }

    /**
     * No assertions — pure diagnosis of the failing shape
     * [home, me, account] -> goTab(ME). The dumps distinguish:
     *  - stack unchanged [home, me, account]: navigate() was a
     *    complete no-op (popUpTo never ran);
     *  - stack [home]: popUpTo ran but ME was never re-added
     *    (restore / launchSingleTop / create all failed);
     *  - stack [home, me]: it worked (then the CI failure would be
     *    elsewhere).
     * The probes then show whether a plain navigate(ME) works from
     * the post-goTab state, and whether popBackStack works at all.
     */
    @Test
    fun diagnose_me_account_toMe() {
        navController.navigate(Routes.ME)
        navController.navigate(Routes.ACCOUNT)
        dump("before goTab(ME)")
        navigateToTab(navController, Routes.ME)
        dump("after goTab(ME)")
        navController.navigate(Routes.ME)
        dump("after plain navigate(ME)")
        val popped = navController.popBackStack()
        dump("after popBackStack=$popped")
    }

    /** goTab variant WITHOUT restoreState (popUpTo saveState +
     * launchSingleTop only). If this lands on ME, restoreState is the
     * culprit and the production fix is to drop it. */
    private fun goTabNoRestore(navController: TestNavHostController, route: String) {
        navController.navigate(route) {
            popUpTo(navController.graph.findStartDestination().id) {
                saveState = true
            }
            launchSingleTop = true
        }
    }

    /** goTab variant WITHOUT saveState/restoreState at all
     * (plain popUpTo + launchSingleTop). */
    private fun goTabNoState(navController: TestNavHostController, route: String) {
        navController.navigate(route) {
            popUpTo(navController.graph.findStartDestination().id)
            launchSingleTop = true
        }
    }

    @Test
    fun variant_noRestore_me_account_toMe() {
        navController.navigate(Routes.ME)
        navController.navigate(Routes.ACCOUNT)
        goTabNoRestore(navController, Routes.ME)
        dump("variant noRestore after goTab(ME)")
        assertEquals(Routes.ME, navController.currentDestination?.route)
        assertEquals(listOf(Routes.HOME, Routes.ME), stack())
    }

    @Test
    fun variant_noRestore_loginHome_thenMe() {
        navController.navigate(Routes.ACCOUNT)
        goTabNoRestore(navController, Routes.HOME)
        dump("variant noRestore after goTab(HOME)")
        assertEquals(Routes.HOME, navController.currentDestination?.route)
        assertEquals(listOf(Routes.HOME), stack())

        goTabNoRestore(navController, Routes.ME)
        dump("variant noRestore after goTab(ME)")
        assertEquals(Routes.ME, navController.currentDestination?.route)
        assertEquals(listOf(Routes.HOME, Routes.ME), stack())
    }

    @Test
    fun variant_noState_me_account_toMe() {
        navController.navigate(Routes.ME)
        navController.navigate(Routes.ACCOUNT)
        goTabNoState(navController, Routes.ME)
        dump("variant noState after goTab(ME)")
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
