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
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDatePickerState
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.junze.penpal.R
import com.junze.penpal.data.api.CaptchaResult
import com.junze.penpal.data.prefs.SettingsStore
import com.junze.penpal.data.repository.PenpalRepository
import com.junze.penpal.ui.components.Notice
import com.junze.penpal.ui.components.isValidDisplayName
import com.junze.penpal.ui.components.userNotice
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

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

    /** Virtual-world name chosen at registration (null = not set yet). */
    val displayName: StateFlow<String?> = settings.displayName
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    private val _mode = MutableStateFlow(AuthMode.LOGIN)
    val mode: StateFlow<AuthMode> = _mode

    private val _captcha = MutableStateFlow<CaptchaResult?>(null)
    val captcha: StateFlow<CaptchaResult?> = _captcha

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy

    // Notices are resource ids (+ format args), resolved with
    // stringResource at the screen — never a raw backend string.
    private val _notice = MutableStateFlow<Notice?>(null)
    val notice: StateFlow<Notice?> = _notice

    /**
     * True only right after a successful registration, until the user
     * picks an exit. Registration already logs the user in (the register
     * response carries the token — see PenpalRepository.register), so
     * this is a success state, not a "go verify" dead end.
     */
    private val _justRegistered = MutableStateFlow(false)
    val justRegistered: StateFlow<Boolean> = _justRegistered

    /**
     * One-shot login-success event (LOGIN mode only). The screen consumes
     * it once and navigates home; a SharedFlow with no replay means a
     * rotation / recomposition can never re-fire the navigation. The
     * "Signed in" toast itself is shown on Home (see MainActivity),
     * because this screen leaves the composition on navigation.
     * Registration deliberately does NOT emit this — it keeps its own
     * success page with the "write first / verify later" exits.
     */
    private val _loginSuccess = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val loginSuccess: SharedFlow<Unit> = _loginSuccess

    fun dismissRegisterSuccess() {
        _justRegistered.value = false
    }

    fun setMode(mode: AuthMode) {
        _mode.value = mode
        _notice.value = null
        if (mode == AuthMode.REGISTER) loadCaptcha()
    }

    fun loadCaptcha() {
        viewModelScope.launch {
            repository.getCaptcha()
                .onSuccess { _captcha.value = it }
                .onFailure { _notice.value = Notice(R.string.account_captcha_load_failed) }
        }
    }

    fun login(email: String, password: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.loginEmail(email.trim(), password)
                .onSuccess { _loginSuccess.tryEmit(Unit) }
                .onFailure { _notice.value = it.userNotice() }
            _busy.value = false
        }
    }

    fun register(email: String, password: String, birthDateText: String, captchaText: String, displayName: String) {
        val name = displayName.trim()
        if (!isValidDisplayName(name)) {
            _notice.value = Notice(R.string.err_invalid_display_name)
            return
        }
        // Local age gate first: never submit a blank / malformed / future
        // / under-18 birth date. The backend re-checks (400 age_under_18)
        // and that code maps to the same wording via userNotice().
        val birthDate = when (val check = checkBirthDate(birthDateText)) {
            BirthDateCheck.Blank -> {
                _notice.value = Notice(R.string.err_birth_date_required)
                return
            }
            BirthDateCheck.InvalidFormat -> {
                _notice.value = Notice(R.string.err_birth_date_invalid)
                return
            }
            BirthDateCheck.FutureDate -> {
                _notice.value = Notice(R.string.err_birth_date_future)
                return
            }
            is BirthDateCheck.Underage -> {
                _notice.value = Notice(R.string.err_age_under_18)
                return
            }
            is BirthDateCheck.OfAge -> formatBirthDate(parseBirthDate(birthDateText)!!)
        }
        val token = _captcha.value?.token
        if (token.isNullOrBlank()) {
            _notice.value = Notice(R.string.account_captcha_required)
            return
        }
        viewModelScope.launch {
            _busy.value = true
            repository.register(email.trim(), password, birthDate, token, captchaText.trim(), name)
                .onSuccess {
                    // Register returns a token (flat AuthResponse), and
                    // saveAccountSession already stored it: the user IS
                    // logged in now — no second login call, no re-typing
                    // the password. Show the success state with exits.
                    _justRegistered.value = true
                    _notice.value = null
                }
                .onFailure {
                    _notice.value = it.userNotice()
                    loadCaptcha() // a failed attempt consumes the challenge
                }
            _busy.value = false
        }
    }

    fun sendVerifyCode(email: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.sendCode(email.trim(), "verify")
                .onSuccess { _notice.value = Notice(R.string.account_code_sent) }
                .onFailure { _notice.value = it.userNotice() }
            _busy.value = false
        }
    }

    fun verifyEmail(email: String, code: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.verifyEmail(email.trim(), code.trim())
                .onSuccess { _notice.value = Notice(R.string.account_verify_success) }
                .onFailure { _notice.value = it.userNotice() }
            _busy.value = false
        }
    }

    fun forgotPassword(email: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.forgotPassword(email.trim())
                .onSuccess { _notice.value = Notice(R.string.account_forgot_sent) }
                .onFailure { _notice.value = it.userNotice() }
            _busy.value = false
        }
    }

    fun resetPassword(email: String, code: String, newPassword: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.resetPassword(email.trim(), code.trim(), newPassword)
                .onSuccess {
                    _notice.value = Notice(R.string.account_reset_done)
                    _mode.value = AuthMode.LOGIN
                }
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

    fun logout() {
        viewModelScope.launch {
            _busy.value = true
            repository.logout()
                .onSuccess {
                    _justRegistered.value = false
                    _notice.value = Notice(R.string.account_logged_out)
                }
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
fun AccountScreen(
    viewModel: AccountViewModel,
    onPrivacyClick: () -> Unit,
    onGoWrite: () -> Unit,
    onGoHome: () -> Unit,
    onBack: () -> Unit,
    onLoginSuccess: () -> Unit = {}
) {
    val accountEmail by viewModel.accountEmail.collectAsState()
    val emailVerified by viewModel.emailVerified.collectAsState()
    val accountDisplayName by viewModel.displayName.collectAsState()
    val justRegistered by viewModel.justRegistered.collectAsState()
    val mode by viewModel.mode.collectAsState()
    val captcha by viewModel.captcha.collectAsState()
    val busy by viewModel.busy.collectAsState()
    val notice by viewModel.notice.collectAsState()

    // Login success navigates home exactly once: without this, a
    // successful login just flips accountEmail to non-null and this
    // screen re-renders in place as the verify / change-password form,
    // which reads as "I was thrown onto the verify page". Registration
    // does not come through here — it keeps its own success page.
    LaunchedEffect(Unit) {
        viewModel.loginSuccess.collect { onLoginSuccess() }
    }

    val snackbarHostState = remember { SnackbarHostState() }
    val noticeText = notice?.let { stringResource(it.resId, *it.args.toTypedArray()) }
    LaunchedEffect(noticeText) {
        noticeText?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
        }
    }

    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var confirmPassword by remember { mutableStateOf("") }
    var birthDateText by remember { mutableStateOf("") }
    var showBirthDatePicker by remember { mutableStateOf(false) }
    var displayName by remember { mutableStateOf("") }
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
                title = { Text(text = stringResource(R.string.account_title)) },
                navigationIcon = {
                    TextButton(onClick = onBack) { Text(text = stringResource(R.string.action_back)) }
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
                        ) { Text(text = stringResource(R.string.account_login)) }
                        OutlinedButton(
                            onClick = { viewModel.setMode(AuthMode.REGISTER) },
                            enabled = mode != AuthMode.REGISTER
                        ) { Text(text = stringResource(R.string.account_register)) }
                        TextButton(onClick = { viewModel.setMode(AuthMode.FORGOT) }) {
                            Text(text = stringResource(R.string.account_forgot))
                        }
                    }
                }
                item {
                    OutlinedTextField(
                        value = email,
                        onValueChange = { email = it },
                        label = { Text(text = stringResource(R.string.account_email)) },
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
                                label = { Text(text = stringResource(R.string.account_password)) },
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
                            ) { Text(text = stringResource(R.string.account_login)) }
                        }
                        item {
                            Text(
                                text = stringResource(R.string.account_login_hint),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                    AuthMode.REGISTER -> {
                        // ---- Virtual-world name (required): the name pen
                        // pals call the user by. Explicitly NOT a real
                        // name — see the hint below the field. ----
                        item {
                            OutlinedTextField(
                                value = displayName,
                                onValueChange = { displayName = it.take(20) },
                                label = { Text(text = stringResource(R.string.account_display_name)) },
                                placeholder = { Text(text = stringResource(R.string.account_display_name_placeholder)) },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                isError = displayName.isNotBlank() && !isValidDisplayName(displayName),
                                supportingText = {
                                    Text(
                                        text = if (displayName.isNotBlank() && !isValidDisplayName(displayName)) {
                                            stringResource(R.string.account_display_name_invalid)
                                        } else {
                                            stringResource(R.string.account_display_name_hint)
                                        }
                                    )
                                }
                            )
                        }
                        item {
                            OutlinedTextField(
                                value = password,
                                onValueChange = { password = it },
                                label = { Text(text = stringResource(R.string.account_password_hint)) },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                visualTransformation = PasswordVisualTransformation()
                            )
                        }
                        item {
                            OutlinedTextField(
                                value = confirmPassword,
                                onValueChange = { confirmPassword = it },
                                label = { Text(text = stringResource(R.string.account_password_confirm)) },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                visualTransformation = PasswordVisualTransformation()
                            )
                        }
                        item {
                            // Birth date: manual YYYY-MM-DD input + a
                            // picker. Nothing is pre-filled and the picker
                            // starts with no date selected — the user must
                            // actively choose. The computed full age shows
                            // immediately under the field.
                            val birthCheck = checkBirthDate(birthDateText)
                            OutlinedTextField(
                                value = birthDateText,
                                onValueChange = {
                                    birthDateText = it.filter { c -> c.isDigit() || c == '-' }.take(10)
                                },
                                label = { Text(text = stringResource(R.string.account_birth_date)) },
                                placeholder = { Text(text = stringResource(R.string.account_birth_date_placeholder)) },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                isError = birthCheck is BirthDateCheck.InvalidFormat ||
                                    birthCheck is BirthDateCheck.FutureDate ||
                                    birthCheck is BirthDateCheck.Underage,
                                supportingText = {
                                    Text(
                                        text = when (birthCheck) {
                                            BirthDateCheck.Blank ->
                                                stringResource(R.string.account_birth_date_format_hint)
                                            BirthDateCheck.InvalidFormat ->
                                                stringResource(R.string.err_birth_date_invalid)
                                            BirthDateCheck.FutureDate ->
                                                stringResource(R.string.err_birth_date_future)
                                            is BirthDateCheck.Underage ->
                                                stringResource(R.string.account_birth_date_underage)
                                            is BirthDateCheck.OfAge ->
                                                stringResource(R.string.account_birth_date_of_age, birthCheck.years)
                                        }
                                    )
                                },
                                trailingIcon = {
                                    TextButton(onClick = { showBirthDatePicker = true }) {
                                        Text(text = stringResource(R.string.account_birth_date_pick))
                                    }
                                }
                            )
                        }
                        // Disclaimer, verbatim per the user's wording: no
                        // real-name / age verification is possible; the
                        // user must enter a true age and bears legal
                        // responsibility for a false one.
                        item {
                            Text(
                                text = stringResource(R.string.account_birth_date_disclaimer),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        if (showBirthDatePicker) {
                            item {
                                val today = LocalDate.now()
                                val pickerState = rememberDatePickerState(
                                    yearRange = (today.year - 120)..today.year,
                                    selectableDates = object : SelectableDates {
                                        override fun isSelectableDate(utcTimeMillis: Long): Boolean {
                                            // The picker hands UTC start-of-day
                                            // millis; compare in UTC so the
                                            // boundary is the same everywhere.
                                            val date = Instant.ofEpochMilli(utcTimeMillis)
                                                .atZone(ZoneOffset.UTC).toLocalDate()
                                            return !date.isAfter(today)
                                        }
                                    }
                                )
                                DatePickerDialog(
                                    onDismissRequest = { showBirthDatePicker = false },
                                    confirmButton = {
                                        TextButton(
                                            onClick = {
                                                pickerState.selectedDateMillis?.let { millis ->
                                                    birthDateText = formatBirthDate(
                                                        Instant.ofEpochMilli(millis)
                                                            .atZone(ZoneOffset.UTC).toLocalDate()
                                                    )
                                                }
                                                showBirthDatePicker = false
                                            },
                                            enabled = pickerState.selectedDateMillis != null
                                        ) { Text(text = stringResource(R.string.action_confirm)) }
                                    },
                                    dismissButton = {
                                        TextButton(onClick = { showBirthDatePicker = false }) {
                                            Text(text = stringResource(R.string.action_cancel))
                                        }
                                    }
                                ) {
                                    DatePicker(
                                        state = pickerState,
                                        title = { Text(text = stringResource(R.string.account_birth_date_dialog_title)) }
                                    )
                                }
                            }
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
                                        contentDescription = stringResource(R.string.account_captcha_image_desc),
                                        modifier = Modifier
                                            .fillMaxWidth(0.6f)
                                            .height(60.dp)
                                    )
                                } else {
                                    CircularProgressIndicator()
                                }
                                OutlinedButton(onClick = { viewModel.loadCaptcha() }) {
                                    Text(text = stringResource(R.string.account_captcha_refresh))
                                }
                            }
                        }
                        item {
                            OutlinedTextField(
                                value = captchaText,
                                onValueChange = { captchaText = it },
                                label = { Text(text = stringResource(R.string.account_captcha)) },
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
                                Text(text = stringResource(R.string.account_privacy_agree))
                                Text(
                                    text = stringResource(R.string.account_privacy),
                                    color = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.clickable { onPrivacyClick() }
                                )
                            }
                        }
                        item {
                            val birthCheck = checkBirthDate(birthDateText)
                            Button(
                                onClick = {
                                    viewModel.register(email, password, birthDateText, captchaText, displayName)
                                },
                                enabled = !busy && email.isNotBlank() && password.length >= 8 &&
                                    password == confirmPassword && birthCheck is BirthDateCheck.OfAge &&
                                    isValidDisplayName(displayName.trim()) &&
                                    captchaText.isNotBlank() && privacyChecked,
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) { Text(text = stringResource(R.string.account_register)) }
                        }
                    }
                    AuthMode.FORGOT -> {
                        item {
                            Text(
                                text = stringResource(R.string.account_forgot_hint),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        item {
                            Button(
                                onClick = { viewModel.forgotPassword(email) },
                                enabled = !busy && email.isNotBlank(),
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) { Text(text = stringResource(R.string.account_send_code)) }
                        }
                        item {
                            OutlinedTextField(
                                value = code,
                                onValueChange = { code = it },
                                label = { Text(text = stringResource(R.string.account_code)) },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true
                            )
                        }
                        item {
                            OutlinedTextField(
                                value = newPassword,
                                onValueChange = { newPassword = it },
                                label = { Text(text = stringResource(R.string.account_new_password)) },
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
                            ) { Text(text = stringResource(R.string.account_reset_password)) }
                        }
                    }
                }
            } else {
                // ---- Logged in with an email account ----
                if (justRegistered) {
                    // ---- Registration success state ----
                    item {
                        Text(
                            text = stringResource(R.string.account_register_success),
                            style = MaterialTheme.typography.headlineMedium
                        )
                    }
                    item {
                        Text(
                            text = stringResource(R.string.account_register_hint),
                            style = MaterialTheme.typography.bodyLarge
                        )
                    }
                    if (!accountDisplayName.isNullOrBlank()) {
                        item {
                            Text(
                                text = stringResource(R.string.account_display_name) + "：" + accountDisplayName,
                                style = MaterialTheme.typography.bodyLarge,
                                fontWeight = androidx.compose.ui.text.font.FontWeight.Medium
                            )
                        }
                    }
                    item {
                        Button(
                            onClick = onGoWrite,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) { Text(text = stringResource(R.string.account_go_write)) }
                    }
                    item {
                        OutlinedButton(
                            onClick = { viewModel.dismissRegisterSuccess() },
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) { Text(text = stringResource(R.string.account_verify_later)) }
                    }
                }
                item {
                    Text(
                        text = accountEmail!!,
                        style = MaterialTheme.typography.titleMedium
                    )
                    Text(
                        text = if (emailVerified) stringResource(R.string.account_verified)
                        else stringResource(R.string.account_unverified),
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
                        ) { Text(text = stringResource(R.string.account_send_code)) }
                    }
                    item {
                        OutlinedTextField(
                            value = code,
                            onValueChange = { code = it },
                            label = { Text(text = stringResource(R.string.account_code)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true
                        )
                    }
                    item {
                        Button(
                            onClick = { viewModel.verifyEmail(accountEmail!!, code) },
                            enabled = !busy && code.length == 6,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) { Text(text = stringResource(R.string.account_verify_email)) }
                    }
                    // The verify page is never a dead end: write first,
                    // or leave and verify later.
                    item {
                        OutlinedButton(
                            onClick = onGoWrite,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) { Text(text = stringResource(R.string.account_go_write)) }
                    }
                    item {
                        TextButton(
                            onClick = onGoHome,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) { Text(text = stringResource(R.string.account_verify_go_home)) }
                    }
                } else {
                    item {
                        Text(
                            text = stringResource(R.string.account_change_password),
                            style = MaterialTheme.typography.titleMedium
                        )
                    }
                    item {
                        OutlinedTextField(
                            value = currentPassword,
                            onValueChange = { currentPassword = it },
                            label = { Text(text = stringResource(R.string.account_current_password)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            visualTransformation = PasswordVisualTransformation()
                        )
                    }
                    item {
                        OutlinedTextField(
                            value = newPassword,
                            onValueChange = { newPassword = it },
                            label = { Text(text = stringResource(R.string.account_new_password)) },
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
                        ) { Text(text = stringResource(R.string.account_change_password)) }
                    }
                }
                item {
                    OutlinedButton(
                        onClick = { viewModel.logout() },
                        enabled = !busy,
                        modifier = Modifier.fillMaxWidth().height(48.dp)
                    ) { Text(text = stringResource(R.string.account_logout)) }
                }
            }
            item { Spacer(modifier = Modifier.height(16.dp)) }
        }
    }
}
