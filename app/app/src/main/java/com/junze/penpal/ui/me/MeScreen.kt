package com.junze.penpal.ui.me

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Divider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.junze.penpal.R
import com.junze.penpal.data.api.ActivityDto
import com.junze.penpal.data.api.MembershipStatusDto
import com.junze.penpal.data.api.MessageDto
import com.junze.penpal.data.api.PointsDto
import com.junze.penpal.data.api.UnlocksDto
import com.junze.penpal.data.prefs.SettingsStore
import com.junze.penpal.data.repository.PenpalRepository
import com.junze.penpal.ui.components.LocaleHelper
import com.junze.penpal.ui.components.Notice
import com.junze.penpal.ui.components.isValidDisplayName
import com.junze.penpal.ui.components.userNotice
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class MeViewModel(
    private val repository: PenpalRepository,
    settings: SettingsStore
) : ViewModel() {

    /** Null = no email account on this device. */
    val accountEmail: StateFlow<String?> = settings.accountEmail
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val emailVerified: StateFlow<Boolean> = settings.emailVerified
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), false)

    /** Virtual-world name (the name pen pals call the user by). */
    val displayName: StateFlow<String?> = settings.displayName
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    /** App language ("zh" default, "en"); drives the language switch UI. */
    val language: StateFlow<String> = settings.language
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), LocaleHelper.LANGUAGE_ZH)

    private val _membership = MutableStateFlow<MembershipStatusDto?>(null)
    val membership: StateFlow<MembershipStatusDto?> = _membership

    private val _points = MutableStateFlow<PointsDto?>(null)
    val points: StateFlow<PointsDto?> = _points

    private val _unlocks = MutableStateFlow<UnlocksDto?>(null)
    val unlocks: StateFlow<UnlocksDto?> = _unlocks

    private val _messages = MutableStateFlow<List<MessageDto>>(emptyList())
    val messages: StateFlow<List<MessageDto>> = _messages

    private val _activities = MutableStateFlow<List<ActivityDto>>(emptyList())
    val activities: StateFlow<List<ActivityDto>> = _activities

    private val _notice = MutableStateFlow<Notice?>(null)
    val notice: StateFlow<Notice?> = _notice

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy

    init {
        refresh()
    }

    /** Fetch-on-open: membership / points / unlocks / messages / activities.
     * Also syncs the virtual-world name from the server (GET /auth/me) so
     * the page never shows a stale name; that sync is best effort. */
    fun refresh() {
        viewModelScope.launch {
            repository.getProfile()
            repository.getMembershipStatus().onSuccess { _membership.value = it }
            repository.getPoints().onSuccess { _points.value = it }
            repository.getUnlocks().onSuccess { _unlocks.value = it }
            repository.getMessages()
                .onSuccess { _messages.value = it }
                .onFailure { _notice.value = it.userNotice() }
            repository.getActivities().onSuccess { _activities.value = it }
        }
    }

    /** Rename the virtual-world name. Validated the same way as at
     * registration; the server applies it immediately and the local copy
     * follows the response. */
    fun updateDisplayName(name: String) {
        val trimmed = name.trim()
        if (!isValidDisplayName(trimmed)) {
            _notice.value = Notice(R.string.err_invalid_display_name)
            return
        }
        viewModelScope.launch {
            _busy.value = true
            repository.updateDisplayName(trimmed)
                .onSuccess { _notice.value = Notice(R.string.account_display_name_saved) }
                .onFailure { _notice.value = it.userNotice() }
            _busy.value = false
        }
    }

    fun logout() {
        viewModelScope.launch {
            _busy.value = true
            repository.logout()
                .onSuccess { _notice.value = Notice(R.string.account_logged_out) }
                .onFailure { _notice.value = it.userNotice() }
            _busy.value = false
        }
    }

    fun changePassword(current: String, new: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.changePassword(current, new)
                .onSuccess { _notice.value = Notice(R.string.account_password_changed) }
                .onFailure { _notice.value = it.userNotice() }
            _busy.value = false
        }
    }

    fun clearNotice() {
        _notice.value = null
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MeScreen(
    viewModel: MeViewModel,
    onAccountClick: () -> Unit,
    onPrivacyClick: () -> Unit,
    onLanguageChange: (String) -> Unit = {}
) {
    val membership by viewModel.membership.collectAsState()
    val points by viewModel.points.collectAsState()
    val unlocks by viewModel.unlocks.collectAsState()
    val messages by viewModel.messages.collectAsState()
    val activities by viewModel.activities.collectAsState()
    val notice by viewModel.notice.collectAsState()
    val busy by viewModel.busy.collectAsState()
    val accountEmail by viewModel.accountEmail.collectAsState()
    val emailVerified by viewModel.emailVerified.collectAsState()
    val displayName by viewModel.displayName.collectAsState()
    val language by viewModel.language.collectAsState()

    val snackbarHostState = remember { SnackbarHostState() }
    val noticeText = notice?.let { stringResource(it.resId, *it.args.toTypedArray()) }
    LaunchedEffect(noticeText) {
        noticeText?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
        }
    }

    var currentPassword by remember { mutableStateOf("") }
    var newPassword by remember { mutableStateOf("") }
    var editingName by remember { mutableStateOf(false) }
    var nameDraft by remember { mutableStateOf("") }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = { TopAppBar(title = { Text(text = stringResource(R.string.nav_me)) }) }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item { Spacer(modifier = Modifier.height(4.dp)) }

            // ---- Profile header: avatar initial + virtual-world name
            // (editable, applies immediately) + email + verified chip.
            // Warm primaryContainer card, postmark-style ring on the avatar.
            item {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.primaryContainer
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(16.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Box(
                                modifier = Modifier
                                    .size(64.dp)
                                    .clip(CircleShape)
                                    .background(MaterialTheme.colorScheme.primary)
                                    .border(
                                        2.dp,
                                        MaterialTheme.colorScheme.onPrimaryContainer,
                                        CircleShape
                                    ),
                                contentAlignment = Alignment.Center
                            ) {
                                Text(
                                    text = (displayName ?: accountEmail)
                                        ?.firstOrNull()?.toString() ?: "？",
                                    style = MaterialTheme.typography.headlineMedium,
                                    color = MaterialTheme.colorScheme.onPrimary
                                )
                            }
                            Column(modifier = Modifier.weight(1f)) {
                                if (editingName) {
                                    OutlinedTextField(
                                        value = nameDraft,
                                        onValueChange = { nameDraft = it.take(20) },
                                        label = { Text(text = stringResource(R.string.account_display_name)) },
                                        modifier = Modifier.fillMaxWidth(),
                                        singleLine = true,
                                        isError = nameDraft.isNotBlank() &&
                                            !isValidDisplayName(nameDraft.trim())
                                    )
                                    Spacer(modifier = Modifier.height(8.dp))
                                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        Button(
                                            onClick = {
                                                viewModel.updateDisplayName(nameDraft)
                                                editingName = false
                                            },
                                            enabled = !busy && isValidDisplayName(nameDraft.trim())
                                        ) { Text(text = stringResource(R.string.common_save)) }
                                        OutlinedButton(onClick = { editingName = false }) {
                                            Text(text = stringResource(R.string.common_cancel))
                                        }
                                    }
                                } else {
                                    Text(
                                        text = displayName
                                            ?: stringResource(R.string.account_display_name_not_set),
                                        style = MaterialTheme.typography.titleLarge
                                    )
                                    Spacer(modifier = Modifier.height(4.dp))
                                    Text(
                                        text = accountEmail
                                            ?: stringResource(R.string.account_not_logged_in_short),
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                    if (emailVerified) {
                                        Spacer(modifier = Modifier.height(4.dp))
                                        Text(
                                            text = "✓ " + stringResource(R.string.me_verified),
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = MaterialTheme.colorScheme.primary,
                                            fontWeight = FontWeight.Medium
                                        )
                                    }
                                }
                            }
                            if (accountEmail != null && !editingName) {
                                TextButton(onClick = {
                                    nameDraft = displayName ?: ""
                                    editingName = true
                                }) {
                                    Text(text = stringResource(R.string.common_edit))
                                }
                            }
                        }
                        if (accountEmail != null) {
                            Spacer(modifier = Modifier.height(12.dp))
                            Text(
                                text = stringResource(R.string.account_display_name_hint),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        } else {
                            Spacer(modifier = Modifier.height(12.dp))
                            Button(
                                onClick = onAccountClick,
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) {
                                Text(text = stringResource(R.string.account_login_register))
                            }
                        }
                    }
                }
            }

            // ---- Membership ----
            item {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.primaryContainer
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = stringResource(R.string.me_membership),
                            style = MaterialTheme.typography.titleMedium
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = membershipText(membership),
                            style = MaterialTheme.typography.bodyLarge,
                            fontWeight = FontWeight.Medium
                        )
                        Text(
                            text = stringResource(R.string.me_membership_plan),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }

            // ---- Points / unlocks ----
            item {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surface
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = stringResource(R.string.me_points),
                            style = MaterialTheme.typography.titleMedium
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        val currentPoints = points?.points ?: 0
                        Text(
                            text = stringResource(R.string.me_points_current, currentPoints),
                            style = MaterialTheme.typography.bodyLarge,
                            fontWeight = FontWeight.Medium
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        // Progress to the next points unlock (thresholds
                        // from the server when available, else 100 / 300).
                        val thresholds = unlocks?.thresholds?.get("points")
                            ?.filter { it > 0 }?.sorted()?.takeIf { it.isNotEmpty() }
                            ?: listOf(100, 300)
                        val nextThreshold = thresholds.firstOrNull { it > currentPoints }
                        LinearProgressIndicator(
                            progress = if (nextThreshold != null) {
                                currentPoints.toFloat() / nextThreshold
                            } else {
                                1f
                            },
                            modifier = Modifier.fillMaxWidth()
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = if (nextThreshold != null) {
                                stringResource(
                                    R.string.me_points_next_unlock,
                                    nextThreshold - currentPoints
                                )
                            } else {
                                stringResource(R.string.me_points_all_unlocked)
                            },
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.primary
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = stringResource(R.string.me_points_hint),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        val unlocked = unlocks?.unlockedCharacterIds
                        if (!unlocked.isNullOrEmpty()) {
                            Spacer(modifier = Modifier.height(8.dp))
                            Text(
                                text = stringResource(
                                    R.string.me_unlocks_line,
                                    unlocked.size,
                                    unlocked.joinToString(
                                        if (language == LocaleHelper.LANGUAGE_EN) ", " else "、"
                                    )
                                ),
                                style = MaterialTheme.typography.bodyMedium
                            )
                        }
                    }
                }
            }

            // ---- Account ----
            item {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surface
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = stringResource(R.string.account_title),
                            style = MaterialTheme.typography.titleMedium
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = accountEmail ?: stringResource(R.string.account_not_logged_in_short),
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Medium
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = when {
                                accountEmail == null -> stringResource(R.string.account_not_logged_in)
                                emailVerified -> stringResource(R.string.account_verified)
                                else -> stringResource(R.string.account_unverified)
                            },
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        if (accountEmail != null) {
                            OutlinedButton(
                                onClick = { viewModel.logout() },
                                enabled = !busy,
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) {
                                Text(text = stringResource(R.string.account_logout))
                            }
                        } else {
                            Button(
                                onClick = onAccountClick,
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) {
                                Text(text = stringResource(R.string.account_login_register))
                            }
                        }
                    }
                }
            }

            // ---- Language: Chinese (default) / English. Takes effect
            // immediately — the Activity is recreated (not the app) and
            // the choice is persisted, so it survives a force-stop. ----
            item {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surface
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = stringResource(R.string.me_language_title),
                            style = MaterialTheme.typography.titleMedium
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            // Language names are shown in their own language
                            // (standard practice) in both locales.
                            LanguageOption(
                                label = "中文",
                                selected = language != LocaleHelper.LANGUAGE_EN,
                                onClick = { onLanguageChange(LocaleHelper.LANGUAGE_ZH) },
                                modifier = Modifier.weight(1f)
                            )
                            LanguageOption(
                                label = "English",
                                selected = language == LocaleHelper.LANGUAGE_EN,
                                onClick = { onLanguageChange(LocaleHelper.LANGUAGE_EN) },
                                modifier = Modifier.weight(1f)
                            )
                        }
                    }
                }
            }

            // ---- Change password (verified email only) ----
            // Unverified / not-logged-in: show "请先验证邮箱" + a Verify
            // action instead of the change form. Verified: the form.
            item {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surface
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = stringResource(R.string.account_change_password),
                            style = MaterialTheme.typography.titleMedium
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        when {
                            accountEmail == null -> {
                                Text(
                                    text = stringResource(R.string.account_login_first),
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                                Button(
                                    onClick = onAccountClick,
                                    modifier = Modifier.fillMaxWidth().height(48.dp)
                                ) { Text(text = stringResource(R.string.account_login_register)) }
                            }
                            !emailVerified -> {
                                Text(
                                    text = stringResource(R.string.account_verify_first),
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                                Button(
                                    onClick = onAccountClick,
                                    modifier = Modifier.fillMaxWidth().height(48.dp)
                                ) { Text(text = stringResource(R.string.verify_action)) }
                            }
                            else -> {
                                OutlinedTextField(
                                    value = currentPassword,
                                    onValueChange = { currentPassword = it },
                                    label = { Text(text = stringResource(R.string.account_current_password)) },
                                    modifier = Modifier.fillMaxWidth(),
                                    singleLine = true,
                                    visualTransformation = PasswordVisualTransformation()
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                                OutlinedTextField(
                                    value = newPassword,
                                    onValueChange = { newPassword = it },
                                    label = { Text(text = stringResource(R.string.account_new_password)) },
                                    modifier = Modifier.fillMaxWidth(),
                                    singleLine = true,
                                    visualTransformation = PasswordVisualTransformation()
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                                Button(
                                    onClick = { viewModel.changePassword(currentPassword, newPassword) },
                                    enabled = !busy && currentPassword.isNotBlank() && newPassword.length >= 8,
                                    modifier = Modifier.fillMaxWidth().height(48.dp)
                                ) { Text(text = stringResource(R.string.account_change_password)) }
                            }
                        }
                    }
                }
            }

            // ---- Messages & activities (fetch-on-open) ----
            item {
                Text(
                    text = stringResource(R.string.messages),
                    style = MaterialTheme.typography.titleLarge
                )
            }
            if (messages.isEmpty() && activities.isEmpty()) {
                item {
                    Text(
                        text = stringResource(R.string.messages_empty),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            items(activities, key = { "a-${it.id}" }) { activity ->
                MessageRow(
                    title = activity.title,
                    content = activity.text(),
                    tag = stringResource(R.string.me_tag_activity)
                )
            }
            items(messages, key = { "m-${it.id}" }) { message ->
                MessageRow(
                    title = message.title,
                    content = message.text(),
                    tag = stringResource(R.string.me_tag_message)
                )
            }

            // ---- About ----
            item {
                Divider()
                // The app icon itself, so the "我" page shows the new
                // postman artwork too (same foreground as the launcher).
                Image(
                    painter = painterResource(R.drawable.ic_launcher_foreground),
                    contentDescription = stringResource(R.string.me_icon_desc),
                    modifier = Modifier
                        .size(72.dp)
                        .clip(RoundedCornerShape(16.dp))
                )
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = stringResource(R.string.about_title),
                    style = MaterialTheme.typography.titleLarge
                )
                Text(
                    text = stringResource(R.string.about_text),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = stringResource(R.string.version),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedButton(onClick = onPrivacyClick) {
                    Text(text = stringResource(R.string.privacy_policy))
                }
                Spacer(modifier = Modifier.height(16.dp))
            }
        }
    }
}

/** One row of the language switch: radio + the language's own name. */
@Composable
private fun LanguageOption(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .clickable(onClick = onClick)
            .padding(vertical = 4.dp),
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        RadioButton(selected = selected, onClick = onClick)
        Text(text = label, style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
private fun membershipText(membership: MembershipStatusDto?): String {    return when (membership?.plan) {
        "member" -> stringResource(R.string.me_plan_member)
        "premium" -> stringResource(R.string.me_plan_premium)
        else -> stringResource(R.string.me_membership_free)
    }
}

@Composable
private fun MessageRow(title: String, content: String, tag: String) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface
        )
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    text = tag,
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary
                )
                Text(text = title, fontWeight = FontWeight.Medium)
            }
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = content,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}
