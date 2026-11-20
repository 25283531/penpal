package com.junze.penpal.ui.me

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Divider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
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
import com.junze.penpal.ui.components.userMessage
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

    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy

    init {
        refresh()
    }

    /** Fetch-on-open: membership / points / unlocks / messages / activities. */
    fun refresh() {
        viewModelScope.launch {
            repository.getMembershipStatus().onSuccess { _membership.value = it }
            repository.getPoints().onSuccess { _points.value = it }
            repository.getUnlocks().onSuccess { _unlocks.value = it }
            repository.getMessages()
                .onSuccess { _messages.value = it }
                .onFailure { _notice.value = it.userMessage() }
            repository.getActivities().onSuccess { _activities.value = it }
        }
    }

    fun changePassword(current: String, new: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.changePassword(current, new)
                .onSuccess { _notice.value = "密码已修改" }
                .onFailure { _notice.value = it.userMessage() }
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
    onPrivacyClick: () -> Unit
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

    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(notice) {
        notice?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
        }
    }

    var currentPassword by remember { mutableStateOf("") }
    var newPassword by remember { mutableStateOf("") }

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
                        Text(
                            text = "当前积分：${points?.points ?: 0}",
                            style = MaterialTheme.typography.bodyLarge,
                            fontWeight = FontWeight.Medium
                        )
                        Text(
                            text = stringResource(R.string.me_points_hint),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        val unlocked = unlocks?.unlockedCharacterIds
                        if (!unlocked.isNullOrEmpty()) {
                            Spacer(modifier = Modifier.height(8.dp))
                            Text(
                                text = "${stringResource(R.string.me_unlocks)}：已解锁 ${unlocked.size} 位" +
                                    "（${unlocked.joinToString("、")}）",
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
                            text = accountEmail ?: "未登录",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Medium
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = when {
                                accountEmail == null -> "未登录邮箱，仍可用设备号正常写信"
                                emailVerified -> "邮箱已验证"
                                else -> "邮箱未验证（可正常使用；改密码、找回密码需先验证）"
                            },
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Button(
                            onClick = onAccountClick,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) {
                            Text(text = stringResource(R.string.account_login_register))
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
                                    text = "请先登录或注册邮箱。",
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
                                    label = { Text(text = "当前密码") },
                                    modifier = Modifier.fillMaxWidth(),
                                    singleLine = true,
                                    visualTransformation = PasswordVisualTransformation()
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                                OutlinedTextField(
                                    value = newPassword,
                                    onValueChange = { newPassword = it },
                                    label = { Text(text = "新密码（至少 8 位）") },
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
                MessageRow(title = activity.title, content = activity.text(), tag = "活动")
            }
            items(messages, key = { "m-${it.id}" }) { message ->
                MessageRow(title = message.title, content = message.text(), tag = "消息")
            }

            // ---- About ----
            item {
                Divider()
                // The app icon itself, so the "我" page shows the new
                // postman artwork too (same foreground as the launcher).
                Image(
                    painter = painterResource(R.drawable.ic_launcher_foreground),
                    contentDescription = "笔友图标",
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

@Composable
private fun membershipText(membership: MembershipStatusDto?): String {
    return when (membership?.plan) {
        "member" -> "会员 · ¥9.9/月"
        "premium" -> "高级会员 · ¥19.9/月"
        else -> "免费 · 第一阶段全部免费"
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
