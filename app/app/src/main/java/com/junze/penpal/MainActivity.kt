package com.junze.penpal

import android.Manifest
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
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import com.junze.penpal.ui.letters.CharacterDetailScreen
import com.junze.penpal.ui.letters.CharactersScreen
import com.junze.penpal.ui.letters.CharactersViewModel
import com.junze.penpal.ui.letters.LetterDetailScreen
import com.junze.penpal.ui.letters.LetterDetailViewModel
import com.junze.penpal.ui.letters.WriteLetterScreen
import com.junze.penpal.ui.letters.WriteLetterViewModel
import com.junze.penpal.ui.me.MeScreen
import com.junze.penpal.ui.me.MeViewModel
import com.junze.penpal.ui.privacy.PrivacyScreen
import com.junze.penpal.ui.privacy.PrivacyViewModel
import com.junze.penpal.ui.nav.Routes
import com.junze.penpal.ui.theme.PenpalTheme

class MainActivity : ComponentActivity() {

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* best effort */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestNotificationPermissionIfNeeded()
        setContent {
            PenpalTheme {
                MainScaffold(app = application as PenpalApp)
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
private fun MainScaffold(app: PenpalApp) {
    val navController = rememberNavController()
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentDestination = navBackStackEntry?.destination

    Scaffold(
        bottomBar = {
            NavigationBar {
                TABS.forEach { tab ->
                    val selected = currentDestination?.hierarchy?.any { it.route == tab.route } == true
                    NavigationBarItem(
                        selected = selected,
                        onClick = {
                            navController.navigate(tab.route) {
                                popUpTo(navController.graph.findStartDestination().id) {
                                    saveState = true
                                }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = { Icon(tab.icon, contentDescription = null) },
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
                val vm: HomeViewModel = viewModel(
                    factory = vmFactory { HomeViewModel(app.repository, app.settings) }
                )
                HomeScreen(
                    viewModel = vm,
                    onCharacterClick = { id ->
                        navController.navigate(Routes.characterDetail(id))
                    },
                    onLetterClick = { id ->
                        navController.navigate(Routes.letterDetail(id))
                    },
                    onVerifyClick = { navController.navigate(Routes.ACCOUNT) },
                    onCharactersClick = { navController.navigate(Routes.CHARACTERS) }
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
                    onBack = { navController.popBackStack() }
                )
            }
            composable(
                route = Routes.WRITE_LETTER,
                arguments = listOf(navArgument("characterId") { type = NavType.StringType })
            ) { backStackEntry ->
                val characterId = backStackEntry.arguments?.getString("characterId")
                    ?: return@composable
                val vm: WriteLetterViewModel = viewModel(
                    factory = vmFactory { WriteLetterViewModel(app.repository) }
                )
                WriteLetterScreen(
                    characterId = characterId,
                    viewModel = vm,
                    onSent = { navController.popBackStack() },
                    onBack = { navController.popBackStack() }
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
                    onBack = { navController.popBackStack() }
                )
            }
            composable(Routes.ME) {
                val vm: MeViewModel = viewModel(
                    factory = vmFactory { MeViewModel(app.repository, app.settings) }
                )
                MeScreen(
                    viewModel = vm,
                    onAccountClick = { navController.navigate(Routes.ACCOUNT) },
                    onPrivacyClick = { navController.navigate(Routes.PRIVACY) }
                )
            }
            composable(Routes.ACCOUNT) {
                val vm: AccountViewModel = viewModel(
                    factory = vmFactory { AccountViewModel(app.repository, app.settings) }
                )
                AccountScreen(
                    viewModel = vm,
                    onPrivacyClick = { navController.navigate(Routes.PRIVACY) },
                    onBack = { navController.popBackStack() }
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
