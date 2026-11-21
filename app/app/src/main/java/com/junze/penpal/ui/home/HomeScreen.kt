package com.junze.penpal.ui.home

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.junze.penpal.R
import com.junze.penpal.data.api.CharacterDto
import com.junze.penpal.data.api.LetterDto
import com.junze.penpal.data.prefs.SettingsStore
import com.junze.penpal.data.repository.PenpalRepository
import com.junze.penpal.ui.components.EmptyBox
import com.junze.penpal.ui.components.Notice
import com.junze.penpal.ui.components.SessionExpiredException
import com.junze.penpal.ui.components.expectedReplyText
import com.junze.penpal.ui.components.formatDateTimeShanghai
import com.junze.penpal.ui.components.userNotice
import retrofit2.HttpException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class HomeViewModel(
    private val repository: PenpalRepository,
    settings: SettingsStore
) : ViewModel() {

    val characters: StateFlow<List<CharacterDto>> = repository.characters
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val letters: StateFlow<List<LetterDto>> = repository.letters
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    /** Null = no email account yet; non-null + unverified = show the banner. */
    val accountEmail: StateFlow<String?> = settings.accountEmail
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val emailVerified: StateFlow<Boolean> = settings.emailVerified
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), false)

    private val _isRefreshing = MutableStateFlow(false)
    val isRefreshing: StateFlow<Boolean> = _isRefreshing

    private val _points = MutableStateFlow<Int?>(null)
    val points: StateFlow<Int?> = _points

    private val _notice = MutableStateFlow<Notice?>(null)
    val notice: StateFlow<Notice?> = _notice

    /**
     * Last letters-refresh failure, kept (not just a transient snackbar).
     * While set AND the timeline is empty, the screen shows an explicit
     * error card with retry — it must never silently show "还没有信"
     * when the server could not be reached or the session expired.
     * Cleared on the next refresh attempt / success.
     */
    private val _lettersError = MutableStateFlow<Notice?>(null)
    val lettersError: StateFlow<Notice?> = _lettersError

    /** True when the letters error is a dead session (sign in again). */
    private val _lettersErrorSessionExpired = MutableStateFlow(false)
    val lettersErrorSessionExpired: StateFlow<Boolean> = _lettersErrorSessionExpired

    // No init refresh: MainScaffold refreshes whenever the user navigates
    // back to HOME (so a letter discovered by a failed send — e.g. the
    // 409 unanswered-letter case — appears as soon as they return).
    fun refresh() {
        viewModelScope.launch {
            _isRefreshing.value = true
            _lettersError.value = null
            _lettersErrorSessionExpired.value = false
            // Device auth happens inside withAuth; the daily-login point is
            // best effort and never blocks the letter flow.
            repository.dailyLogin()
                .onSuccess { _points.value = it.points }
                .onFailure { repository.getPoints().onSuccess { _points.value = it.points } }
            repository.refreshCharacters().onFailure {
                _notice.value = it.userNotice()
            }
            repository.refreshLetters()
                .onSuccess {
                    _lettersError.value = null
                    _lettersErrorSessionExpired.value = false
                }
                .onFailure {
                    _lettersError.value = it.userNotice()
                    _lettersErrorSessionExpired.value = it is SessionExpiredException ||
                        (it is HttpException && it.code() == 401)
                    if (_notice.value == null) _notice.value = it.userNotice()
                }
            _isRefreshing.value = false
        }
    }

    fun clearNotice() {
        _notice.value = null
    }
}

/** Read-time line for one timeline row (Asia/Shanghai, never invented). */
@Composable
fun letterReadLine(letter: LetterDto): String {
    return if (letter.direction == "ai") {
        val readAt = letter.userReadAt ?: letter.readAt
        if (readAt.isNullOrBlank()) stringResource(R.string.letter_read_mine_unread)
        else stringResource(R.string.letter_read_mine, formatDateTimeShanghai(readAt))
    } else {
        val readAt = letter.characterReadAt
        if (readAt.isNullOrBlank()) stringResource(R.string.letter_read_theirs_notyet)
        else stringResource(R.string.letter_read_theirs, formatDateTimeShanghai(readAt))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    viewModel: HomeViewModel,
    onLetterClick: (Int) -> Unit,
    onVerifyClick: () -> Unit,
    onRefreshUnread: () -> Unit = {},
    onLoginClick: () -> Unit = {}
) {
    val characters by viewModel.characters.collectAsState()
    val letters by viewModel.letters.collectAsState()
    val accountEmail by viewModel.accountEmail.collectAsState()
    val emailVerified by viewModel.emailVerified.collectAsState()
    val isRefreshing by viewModel.isRefreshing.collectAsState()
    val points by viewModel.points.collectAsState()
    val notice by viewModel.notice.collectAsState()
    val lettersError by viewModel.lettersError.collectAsState()
    val lettersErrorSessionExpired by viewModel.lettersErrorSessionExpired.collectAsState()

    val snackbarHostState = remember { SnackbarHostState() }
    val noticeText = notice?.let { stringResource(it.resId, *it.args.toTypedArray()) }
    LaunchedEffect(noticeText) {
        noticeText?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
        }
    }

    // Unverified users are never blocked — just a gentle banner.
    val showVerifyBanner = accountEmail != null && !emailVerified
    // Newest first: Room already orders letters by createdAt DESC.
    val characterNames = characters.associate { it.id to it.name }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text(text = stringResource(R.string.app_name)) },
                actions = {
                    IconButton(onClick = {
                        viewModel.refresh()
                        onRefreshUnread()
                    }) {
                        Icon(
                            Icons.Filled.Refresh,
                            contentDescription = stringResource(R.string.action_refresh_desc)
                        )
                    }
                }
            )
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item {
                Text(
                    text = stringResource(R.string.home_subtitle),
                    style = MaterialTheme.typography.headlineMedium,
                    modifier = Modifier.padding(top = 8.dp, bottom = 4.dp)
                )
            }
            if (showVerifyBanner) {
                item {
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.primaryContainer
                        )
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(16.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = stringResource(R.string.verify_banner),
                                style = MaterialTheme.typography.bodyMedium,
                                modifier = Modifier.weight(1f)
                            )
                            OutlinedButton(onClick = onVerifyClick) {
                                Text(text = stringResource(R.string.verify_action))
                            }
                        }
                    }
                }
            }
            points?.let {
                item {
                    Text(
                        text = stringResource(R.string.home_points, it),
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.Medium
                    )
                }
            }
            // ---- Letter timeline (no "认识笔友" section here any more:
            // characters live on the "征友信息" tab) ----
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = stringResource(R.string.home_my_letters),
                        style = MaterialTheme.typography.titleLarge
                    )
                    if (isRefreshing) CircularProgressIndicator()
                }
            }
            // Empty timeline: show the error card when the refresh failed
            // (never a silent "还没有信"), the empty state only when the
            // refresh actually succeeded and the inbox is genuinely empty.
            if (letters.isEmpty() && !isRefreshing) {
                val error = lettersError
                if (error != null) {
                    item {
                        Card(
                            colors = CardDefaults.cardColors(
                                containerColor = MaterialTheme.colorScheme.surface
                            )
                        ) {
                            Column(modifier = Modifier.padding(16.dp)) {
                                Text(
                                    text = stringResource(error.resId, *error.args.toTypedArray()),
                                    style = MaterialTheme.typography.bodyLarge
                                )
                                Spacer(modifier = Modifier.height(12.dp))
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    androidx.compose.material3.Button(
                                        onClick = {
                                            viewModel.refresh()
                                            onRefreshUnread()
                                        }
                                    ) {
                                        Text(text = stringResource(R.string.action_retry))
                                    }
                                    if (lettersErrorSessionExpired) {
                                        androidx.compose.material3.OutlinedButton(
                                            onClick = onLoginClick
                                        ) {
                                            Text(text = stringResource(R.string.account_login_register))
                                        }
                                    }
                                }
                            }
                        }
                    }
                } else {
                    item {
                        EmptyBox(
                            message = stringResource(R.string.home_no_letters),
                            modifier = Modifier.height(80.dp)
                        )
                    }
                }
            }
            items(letters, key = { it.id }) { letter ->
                val recipient = characterNames[letter.characterId]
                    ?: stringResource(R.string.home_friend_fallback)
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onLetterClick(letter.id) },
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surface
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = if (letter.direction == "ai") {
                                stringResource(R.string.home_letter_received, recipient)
                            } else {
                                stringResource(R.string.home_letter_sent, recipient)
                            },
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.primary
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = letter.text.take(100) +
                                if (letter.text.length > 100) "…" else "",
                            style = MaterialTheme.typography.bodyMedium
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        // Poetic in-transit status, exactly as the backend
                        // returned it — the client invents no progress.
                        letter.deliveryStageText?.takeIf { it.isNotBlank() }?.let { stage ->
                            Text(
                                text = stage,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.primary
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                        }
                        Text(
                            text = listOfNotNull(
                                stringResource(
                                    R.string.home_sent_time,
                                    formatDateTimeShanghai(letter.createdAt)
                                ).takeIf { !letter.createdAt.isNullOrBlank() },
                                letterReadLine(letter),
                                expectedReplyText(
                                    letter.expectedReplyAt,
                                    letter.replyDueAt
                                ).takeIf { it.isNotBlank() && letter.direction == "user" }
                            ).joinToString(" · "),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
            item { Spacer(modifier = Modifier.height(16.dp)) }
        }
    }
}
