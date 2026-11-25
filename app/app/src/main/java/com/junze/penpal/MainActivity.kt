package com.junze.penpal

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.MailOutline
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.junze.penpal.ui.account.AccountScreen
import com.junze.penpal.ui.account.AccountViewModel
import com.junze.penpal.ui.home.HomeScreen
import com.junze.penpal.ui.home.HomeViewModel
import com.junze.penpal.ui.home.UnreadViewModel
import com.junze.penpal.ui.letters.CharacterDetailScreen
import com.junze.penpal.ui.letters.CharactersScreen
import com.junze.penpal.ui.letters.CharactersViewModel
import com.junze.penpal.ui.letters.LetterDetailScreen
import com.junze.penpal.ui.letters.LetterDetailViewModel
import com.junze.penpal.ui.letters.WriteLetterScreen
import com.junze.penpal.ui.letters.WriteLetterViewModel
import com.junze.penpal.ui.components.LocaleHelper
import com.junze.penpal.ui.me.MeScreen
import com.junze.penpal.ui.me.MeViewModel
import com.junze.penpal.ui.privacy.PrivacyScreen
import com.junze.penpal.ui.privacy.PrivacyViewModel
import com.junze.penpal.ui.components.Notice
import com.junze.penpal.ui.nav.Routes
import com.junze.penpal.ui.theme.PenpalTheme
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* best effort */ }

    /**
     * Resources for this Activity resolve in the stored app language
     * (Chinese default). The language is read synchronously here because
     * no coroutine scope exists yet in attachBaseContext.
     */
    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(
            LocaleHelper.wrap(newBase, LocaleHelper.readStoredLanguage(newBase))
        )
    }

    /**
     * Language switch from the "我" page: persist, apply to
     * Locale.getDefault(), then recreate this Activity (not the app) so
     * the new resources load immediately. The recreated Activity reads
     * the saved language back in attachBaseContext.
     */
    fun setAppLanguage(code: String) {
        lifecycleScope.launch {
            (application as PenpalApp).settings.saveLanguage(code)
            LocaleHelper.apply(code)
            recreate()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestNotificationPermissionIfNeeded()
        setContent {
            PenpalTheme {
                MainScaffold(
                    app = application as PenpalApp,
                    onLanguageChange = { code -> setAppLanguage(code) }
                )
            }
        }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(
                this, Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
            if (!granted) {
                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }
}

private data class Tab(
    val route: String,
    val labelRes: Int,
    val icon: ImageVector
)

private val TABS = listOf(
    Tab(Routes.HOME, R.string.nav_home, Icons.Filled.Home),
    Tab(Routes.CHARACTERS, R.string.nav_letters, Icons.Filled.MailOutline),
    Tab(Routes.ME, R.string.nav_me, Icons.Filled.Person)
)

/** Generic factory for ViewModels wired by hand (no DI framework). */
inline fun <reified T : ViewModel> vmFactory(crossinline create: () -> T) =
    object : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T2 : ViewModel> create(modelClass: Class<T2>): T2 = create() as T2
    }

@Composable
private fun MainScaffold(app: PenpalApp, onLanguageChange: (String) -> Unit) {
    val navController = rememberNavController()
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentDestination = navBackStackEntry?.destination

    // One unread-count source for the Home badge + the screens. Refreshes
    // on every navigation change (cheap GET; silent on failure) so the
    // badge is never a locally guessed number.
    val unreadViewModel: UnreadViewModel = viewModel(
        factory = vmFactory { UnreadViewModel(app, app.repository) }
    )
    val unreadCount by unreadViewModel.unreadCount.collectAsState()

    // Home's ViewModel lives at the scaffold level (not inside the HOME
    // route) so returning to HOME can trigger a timeline refresh — e.g.
    // after a failed send, the outstanding letter the server already
    // holds must appear as soon as the user comes back.
    val homeViewModel: HomeViewModel = viewModel(
        factory = vmFactory { HomeViewModel(app.repository, app.settings) }
    )

    // Whether an email account is registered: gates all write entries
    // (anonymous browsing is read-only). Null = not loaded yet.
    val registeredEmail by app.settings.accountEmail.collectAsState(initial = null)
    val isRegistered = registeredEmail != null

    LaunchedEffect(navBackStackEntry) {
        unreadViewModel.refresh()
        if (navBackStackEntry?.destination?.route == Routes.HOME) {
            homeViewModel.refresh()
        }
    }

    val goTab: (String) -> Unit = { route ->
        navController.navigate(route) {
            popUpTo(navController.graph.findStartDestination().id) {
                saveState = true
            }
            launchSingleTop = true
            restoreState = true
        }
    }

    Scaffold(
        bottomBar = {
            NavigationBar {
                TABS.forEach { tab ->
                    val selected = currentDestination?.hierarchy?.any { it.route == tab.route } == true
                    NavigationBarItem(
                        selected = selected,
                        onClick = { goTab(tab.route) },
                        icon = {
                            if (tab.route == Routes.HOME && unreadCount > 0) {
                                BadgedBox(
                                    badge = { Badge { Text(text = unreadCount.toString()) } }
                                ) {
                                    Icon(tab.icon, contentDescription = null)
                                }
                            } else {
                                Icon(tab.icon, contentDescription = null)
                            }
                        },
                        label = { Text(text = stringResource(tab.labelRes)) }
                    )
                }
            }
        }
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = Routes.HOME,
            modifier = Modifier.padding(innerPadding)
        ) {
            composable(Routes.HOME) {
                HomeScreen(
                    viewModel = homeViewModel,
                    onLetterClick = { id ->
                        navController.navigate(Routes.letterDetail(id))
                    },
                    onVerifyClick = { navController.navigate(Routes.ACCOUNT) },
                    onRefreshUnread = { unreadViewModel.refresh() },
                    onLoginClick = { navController.navigate(Routes.ACCOUNT) }
                )
            }
            composable(Routes.CHARACTERS) {
                val vm: CharactersViewModel = viewModel(
                    factory = vmFactory { CharactersViewModel(app.repository) }
                )
                CharactersScreen(
                    viewModel = vm,
                    onCharacterClick = { id ->
                        navController.navigate(Routes.characterDetail(id))
                    }
                )
            }
            composable(
                route = Routes.CHARACTER_DETAIL,
                arguments = listOf(navArgument("characterId") { type = NavType.StringType })
            ) { backStackEntry ->
                val characterId = backStackEntry.arguments?.getString("characterId")
                    ?: return@composable
                val vm: CharactersViewModel = viewModel(
                    factory = vmFactory { CharactersViewModel(app.repository) }
                )
                CharacterDetailScreen(
                    characterId = characterId,
                    viewModel = vm,
                    onWriteClick = { navController.navigate(Routes.writeLetter(characterId)) },
                    onLetterClick = { id ->
                        navController.navigate(Routes.letterDetail(id))
                    },
                    onBack = { navController.popBackStack() },
                    isRegistered = isRegistered,
                    onRegisterClick = { navController.navigate(Routes.ACCOUNT) }
                )
            }
            composable(
                route = Routes.WRITE_LETTER,
                arguments = listOf(navArgument("characterId") { type = NavType.StringType })
            ) { backStackEntry ->
                val characterId = backStackEntry.arguments?.getString("characterId")
                    ?: return@composable
                val vm: WriteLetterViewModel = viewModel(
                    factory = vmFactory { WriteLetterViewModel(app.repository, app.settings) }
                )
                WriteLetterScreen(
                    characterId = characterId,
                    viewModel = vm,
                    onSent = {
                        // Back to the timeline, where the new letter (with
                        // its expected reply time) is visible. From the
                        // character page one pop already lands on the
                        // thread; from a letter detail page pop twice —
                        // write -> letter detail -> the timeline under it
                        // (character thread, or Home when the detail was
                        // opened from there).
                        val cameFromLetterDetail =
                            navController.previousBackStackEntry?.destination?.route ==
                                Routes.LETTER_DETAIL
                        navController.popBackStack()
                        if (cameFromLetterDetail) navController.popBackStack()
                    },
                    onBack = { navController.popBackStack() },
                    isRegistered = isRegistered,
                    onRegisterClick = { navController.navigate(Routes.ACCOUNT) }
                )
            }
            composable(
                route = Routes.LETTER_DETAIL,
                arguments = listOf(navArgument("letterId") { type = NavType.IntType })
            ) { backStackEntry ->
                val letterId = backStackEntry.arguments?.getInt("letterId")
                    ?: return@composable
                val vm: LetterDetailViewModel = viewModel(
                    factory = vmFactory { LetterDetailViewModel(app.repository) }
                )
                LaunchedEffect(letterId) { vm.load(letterId) }
                LetterDetailScreen(
                    viewModel = vm,
                    onBack = { navController.popBackStack() },
                    onMarkedRead = { unreadViewModel.refresh() },
                    onReplyClick = { characterId ->
                        navController.navigate(Routes.writeLetter(characterId))
                    },
                    isRegistered = isRegistered,
                    onRegisterClick = { navController.navigate(Routes.ACCOUNT) }
                )
            }
            composable(Routes.ME) {
                val vm: MeViewModel = viewModel(
                    factory = vmFactory { MeViewModel(app.repository, app.settings) }
                )
                MeScreen(
                    viewModel = vm,
                    onAccountClick = { navController.navigate(Routes.ACCOUNT) },
                    onPrivacyClick = { navController.navigate(Routes.PRIVACY) },
                    onLanguageChange = onLanguageChange
                )
            }
            composable(Routes.ACCOUNT) {
                val vm: AccountViewModel = viewModel(
                    factory = vmFactory { AccountViewModel(app.repository, app.settings) }
                )
                AccountScreen(
                    viewModel = vm,
                    onPrivacyClick = { navController.navigate(Routes.PRIVACY) },
                    onGoWrite = { goTab(Routes.CHARACTERS) },
                    onGoHome = { goTab(Routes.HOME) },
                    onBack = { navController.popBackStack() },
                    // Login success goes home (not the verify /
                    // change-password form) and the "Signed in" toast
                    // is shown on Home, where the user can see it.
                    onLoginSuccess = {
                        homeViewModel.showNotice(Notice(R.string.account_login_success))
                        goTab(Routes.HOME)
                    }
                )
            }
            composable(Routes.PRIVACY) {
                val vm: PrivacyViewModel = viewModel(
                    factory = vmFactory { PrivacyViewModel(app.repository) }
                )
                PrivacyScreen(
                    viewModel = vm,
                    onBack = { navController.popBackStack() }
                )
            }
        }
    }
}
