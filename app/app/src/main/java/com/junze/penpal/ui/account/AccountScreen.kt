package com.junze.penpal.ui.account

import androidx.compose.foundation.Image
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
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.junze.penpal.data.api.CaptchaResult
import com.junze.penpal.data.prefs.SettingsStore
import com.junze.penpal.data.repository.PenpalRepository
import com.junze.penpal.ui.components.userMessage
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

// Public: AccountViewModel exposes StateFlow<AuthMode> and setMode(AuthMode)
// publicly, so the type itself must be public (was `private`, which broke
// the CI Kotlin build: "public exposes its private-in-file type").
enum class AuthMode { LOGIN, REGISTER, FORGOT }

class AccountViewModel(
    private val repository: PenpalRepository,
    settings: SettingsStore
) : ViewModel() {

    /** Null = no email account on this device (device auth still works). */
    val accountEmail: StateFlow<String?> = settings.accountEmail
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val emailVerified: StateFlow<Boolean> = settings.emailVerified
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), false)

    private val _mode = MutableStateFlow(AuthMode.LOGIN)
    val mode: StateFlow<AuthMode> = _mode

    private val _captcha = MutableStateFlow<CaptchaResult?>(null)
    val captcha: StateFlow<CaptchaResult?> = _captcha

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy

    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice

    fun setMode(mode: AuthMode) {
        _mode.value = mode
        _notice.value = null
        if (mode == AuthMode.REGISTER) loadCaptcha()
    }

    fun loadCaptcha() {
        viewModelScope.launch {
            repository.getCaptcha()
                .onSuccess { _captcha.value = it }
                .onFailure { _notice.value = "验证码加载失败：服务器未连接，请稍后再试" }
        }
    }

    fun login(email: String, password: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.loginEmail(email.trim(), password)
                .onSuccess { _notice.value = "登录成功" }
                .onFailure { _notice.value = it.userMessage() }
            _busy.value = false
        }
    }

    fun register(email: String, password: String, age: Int, captchaText: String) {
        val token = _captcha.value?.token
        if (token.isNullOrBlank()) {
            _notice.value = "请先加载验证码"
            return
        }
        viewModelScope.launch {
            _busy.value = true
            repository.register(email.trim(), password, age, token, captchaText.trim())
                .onSuccess {
                    // Registration sends no email (backend); verification is
                    // done with a code from 账号 → 发送验证码.
                    _notice.value = "注册成功，请去验证邮箱（发送验证码）"
                }
                .onFailure {
                    _notice.value = it.userMessage()
                    loadCaptcha() // a failed attempt consumes the challenge
                }
            _busy.value = false
        }
    }

    fun sendVerifyCode(email: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.sendCode(email.trim(), "verify")
                .onSuccess { _notice.value = "验证码已发送，请查收邮箱" }
                .onFailure { _notice.value = it.userMessage() }
            _busy.value = false
        }
    }

    fun verifyEmail(email: String, code: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.verifyEmail(email.trim(), code.trim())
                .onSuccess { _notice.value = "邮箱验证成功，现在可以改密/找回密码了" }
                .onFailure { _notice.value = it.userMessage() }
            _busy.value = false
        }
    }

    fun forgotPassword(email: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.forgotPassword(email.trim())
                .onSuccess { _notice.value = "如果该邮箱已注册且已验证，重置密码的邮件已发送" }
                .onFailure { _notice.value = it.userMessage() }
            _busy.value = false
        }
    }

    fun resetPassword(email: String, code: String, newPassword: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.resetPassword(email.trim(), code.trim(), newPassword)
                .onSuccess {
                    _notice.value = "密码已重置，请用新密码登录"
                    _mode.value = AuthMode.LOGIN
                }
                .onFailure { _notice.value = it.userMessage() }
            _busy.value = false
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

    fun logout() {
        viewModelScope.launch {
            _busy.value = true
            repository.logout()
                .onSuccess { _notice.value = "已退出登录（仍可用设备号写信）" }
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
fun AccountScreen(
    viewModel: AccountViewModel,
    onPrivacyClick: () -> Unit,
    onBack: () -> Unit
) {
    val accountEmail by viewModel.accountEmail.collectAsState()
    val emailVerified by viewModel.emailVerified.collectAsState()
    val mode by viewModel.mode.collectAsState()
    val captcha by viewModel.captcha.collectAsState()
    val busy by viewModel.busy.collectAsState()
    val notice by viewModel.notice.collectAsState()

    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(notice) {
        notice?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
        }
    }

    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var confirmPassword by remember { mutableStateOf("") }
    var ageText by remember { mutableStateOf("") }
    var captchaText by remember { mutableStateOf("") }
    var privacyChecked by remember { mutableStateOf(false) }
    var code by remember { mutableStateOf("") }
    var newPassword by remember { mutableStateOf("") }
    var currentPassword by remember { mutableStateOf("") }

    // Prefill the email field once the account is known.
    LaunchedEffect(accountEmail) {
        if (accountEmail != null && email.isBlank()) email = accountEmail!!
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text(text = "账号") },
                navigationIcon = {
                    TextButton(onClick = onBack) { Text(text = "返回") }
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
            item { Spacer(modifier = Modifier.height(4.dp)) }

            if (accountEmail == null) {
                // ---- Logged out: login / register / forgot ----
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            onClick = { viewModel.setMode(AuthMode.LOGIN) },
                            enabled = mode != AuthMode.LOGIN
                        ) { Text(text = "登录") }
                        OutlinedButton(
                            onClick = { viewModel.setMode(AuthMode.REGISTER) },
                            enabled = mode != AuthMode.REGISTER
                        ) { Text(text = "注册") }
                        TextButton(onClick = { viewModel.setMode(AuthMode.FORGOT) }) {
                            Text(text = "忘记密码")
                        }
                    }
                }
                item {
                    OutlinedTextField(
                        value = email,
                        onValueChange = { email = it },
                        label = { Text(text = "邮箱") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true
                    )
                }
                when (mode) {
                    AuthMode.LOGIN -> {
                        item {
                            OutlinedTextField(
                                value = password,
                                onValueChange = { password = it },
                                label = { Text(text = "密码") },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                visualTransformation = PasswordVisualTransformation()
                            )
                        }
                        item {
                            Button(
                                onClick = { viewModel.login(email, password) },
                                enabled = !busy && email.isNotBlank() && password.isNotBlank(),
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) { Text(text = "登录") }
                        }
                        item {
                            Text(
                                text = "未验证邮箱也可以正常使用；修改密码和找回密码需要先验证邮箱。",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                    AuthMode.REGISTER -> {
                        item {
                            OutlinedTextField(
                                value = password,
                                onValueChange = { password = it },
                                label = { Text(text = "密码（至少 8 位）") },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                visualTransformation = PasswordVisualTransformation()
                            )
                        }
                        item {
                            OutlinedTextField(
                                value = confirmPassword,
                                onValueChange = { confirmPassword = it },
                                label = { Text(text = "确认密码") },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                visualTransformation = PasswordVisualTransformation()
                            )
                        }
                        item {
                            OutlinedTextField(
                                value = ageText,
                                onValueChange = { ageText = it.filter { c -> c.isDigit() }.take(3) },
                                label = { Text(text = "年龄（未满 14 岁不能注册）") },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true
                            )
                        }
                        item {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                val bitmap = captcha?.bitmap
                                if (bitmap != null) {
                                    Image(
                                        bitmap = bitmap.asImageBitmap(),
                                        contentDescription = "验证码图片",
                                        modifier = Modifier
                                            .fillMaxWidth(0.6f)
                                            .height(60.dp)
                                    )
                                } else {
                                    CircularProgressIndicator()
                                }
                                OutlinedButton(onClick = { viewModel.loadCaptcha() }) {
                                    Text(text = "换一张")
                                }
                            }
                        }
                        item {
                            OutlinedTextField(
                                value = captchaText,
                                onValueChange = { captchaText = it },
                                label = { Text(text = "图中验证码") },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true
                            )
                        }
                        item {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Checkbox(
                                    checked = privacyChecked,
                                    onCheckedChange = { privacyChecked = it }
                                )
                                Text(text = "我已阅读并同意")
                                Text(
                                    text = "《隐私协议》",
                                    color = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.clickable { onPrivacyClick() }
                                )
                            }
                        }
                        item {
                            val age = ageText.toIntOrNull()
                            Button(
                                onClick = {
                                    viewModel.register(email, password, age ?: 0, captchaText)
                                },
                                enabled = !busy && email.isNotBlank() && password.length >= 8 &&
                                    password == confirmPassword && age != null && age >= 14 &&
                                    captchaText.isNotBlank() && privacyChecked,
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) { Text(text = "注册") }
                        }
                    }
                    AuthMode.FORGOT -> {
                        item {
                            Text(
                                text = "输入注册邮箱，我们会发一封带验证码的邮件（仅已验证的邮箱能收到）",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        item {
                            Button(
                                onClick = { viewModel.forgotPassword(email) },
                                enabled = !busy && email.isNotBlank(),
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) { Text(text = "发送验证码") }
                        }
                        item {
                            OutlinedTextField(
                                value = code,
                                onValueChange = { code = it },
                                label = { Text(text = "邮箱验证码（6 位）") },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true
                            )
                        }
                        item {
                            OutlinedTextField(
                                value = newPassword,
                                onValueChange = { newPassword = it },
                                label = { Text(text = "新密码（至少 8 位）") },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                visualTransformation = PasswordVisualTransformation()
                            )
                        }
                        item {
                            Button(
                                onClick = { viewModel.resetPassword(email, code, newPassword) },
                                enabled = !busy && code.length == 6 && newPassword.length >= 8,
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) { Text(text = "重置密码") }
                        }
                    }
                }
            } else {
                // ---- Logged in with an email account ----
                item {
                    Text(
                        text = accountEmail!!,
                        style = MaterialTheme.typography.titleMedium
                    )
                    Text(
                        text = if (emailVerified) "邮箱已验证" else "邮箱未验证（可正常使用；改密码、找回密码需先验证）",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                if (!emailVerified) {
                    item {
                        Button(
                            onClick = { viewModel.sendVerifyCode(accountEmail!!) },
                            enabled = !busy,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) { Text(text = "发送验证码") }
                    }
                    item {
                        OutlinedTextField(
                            value = code,
                            onValueChange = { code = it },
                            label = { Text(text = "邮箱验证码（6 位）") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true
                        )
                    }
                    item {
                        Button(
                            onClick = { viewModel.verifyEmail(accountEmail!!, code) },
                            enabled = !busy && code.length == 6,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) { Text(text = "验证邮箱") }
                    }
                } else {
                    item {
                        Text(text = "修改密码", style = MaterialTheme.typography.titleMedium)
                    }
                    item {
                        OutlinedTextField(
                            value = currentPassword,
                            onValueChange = { currentPassword = it },
                            label = { Text(text = "当前密码") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            visualTransformation = PasswordVisualTransformation()
                        )
                    }
                    item {
                        OutlinedTextField(
                            value = newPassword,
                            onValueChange = { newPassword = it },
                            label = { Text(text = "新密码（至少 8 位）") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            visualTransformation = PasswordVisualTransformation()
                        )
                    }
                    item {
                        Button(
                            onClick = { viewModel.changePassword(currentPassword, newPassword) },
                            enabled = !busy && currentPassword.isNotBlank() && newPassword.length >= 8,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) { Text(text = "修改密码") }
                    }
                }
                item {
                    OutlinedButton(
                        onClick = { viewModel.logout() },
                        enabled = !busy,
                        modifier = Modifier.fillMaxWidth().height(48.dp)
                    ) { Text(text = "退出登录") }
                }
            }
            item { Spacer(modifier = Modifier.height(16.dp)) }
        }
    }
}
