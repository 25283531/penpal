package com.junze.penpal.ui.letters

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.junze.penpal.R
import com.junze.penpal.data.api.ApiClient
import com.junze.penpal.data.api.CharacterDto
import com.junze.penpal.data.api.CharacterPhotoDto
import com.junze.penpal.data.api.LetterDto
import com.junze.penpal.data.prefs.SettingsStore
import com.junze.penpal.data.repository.MAX_LETTER_CHARS
import com.junze.penpal.data.repository.PenpalRepository
import com.junze.penpal.ui.components.EmptyBox
import com.junze.penpal.ui.components.Notice
import com.junze.penpal.ui.components.SessionExpiredException
import com.junze.penpal.ui.components.expectedReplyText
import com.junze.penpal.ui.components.formatDateTimeShanghai
import com.junze.penpal.ui.components.userNotice
import com.junze.penpal.ui.home.letterReadLine
import java.util.Locale
import retrofit2.HttpException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

// ---------- Characters ----------

class CharactersViewModel(
    private val repository: PenpalRepository,
    private val settings: SettingsStore
) : ViewModel() {

    val characters: StateFlow<List<CharacterDto>> = repository.characters
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    /** Null = no email account yet: the screen shows the browse-only
     * status ("未注册、仅浏览") instead of any age wording. */
    val accountEmail: StateFlow<String?> = settings.accountEmail
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading

    /**
     * Last characters-load failure, kept (not just a transient
     * snackbar). While set, the screen shows the error with a retry
     * action — and keeps any cached characters visible. It must
     * never silently show "no pen pals" when the load actually
     * failed, and a failed load must never be blamed on the network
     * when the server (or the session) is the problem: the notice
     * text comes from the failure itself (no connection ->
     * "server unreachable", HTTP failure -> the backend code's
     * text, 401 -> session expired). Cleared on the next refresh
     * attempt / success.
     */
    private val _charactersError = MutableStateFlow<Notice?>(null)
    val charactersError: StateFlow<Notice?> = _charactersError

    /** True when the characters error is a dead session (sign in again). */
    private val _charactersErrorSessionExpired = MutableStateFlow(false)
    val charactersErrorSessionExpired: StateFlow<Boolean> = _charactersErrorSessionExpired

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _isLoading.value = true
            _charactersError.value = null
            _charactersErrorSessionExpired.value = false
            repository.refreshCharacters()
                .onSuccess {
                    _charactersError.value = null
                    _charactersErrorSessionExpired.value = false
                }
                .onFailure {
                    _charactersError.value = it.userNotice()
                    _charactersErrorSessionExpired.value = it is SessionExpiredException ||
                        (it is HttpException && it.code() == 401)
                }
            _isLoading.value = false
        }
    }

    fun thread(characterId: String) = repository.lettersForCharacter(characterId)

    suspend fun loadCharacter(characterId: String): CharacterDto? {
        refresh()
        return repository.getCharacter(characterId)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CharactersScreen(
    viewModel: CharactersViewModel,
    onCharacterClick: (String) -> Unit,
    onLoginClick: () -> Unit = {}
) {
    val characters by viewModel.characters.collectAsState()
    val accountEmail by viewModel.accountEmail.collectAsState()
    val isLoading by viewModel.isLoading.collectAsState()
    val charactersError by viewModel.charactersError.collectAsState()
    val charactersErrorSessionExpired by viewModel.charactersErrorSessionExpired.collectAsState()

    // Locked characters are hidden (M0: P01–P05 are all unlocked by default).
    val unlocked = characters.filter { it.unlocked }

    Scaffold(
        topBar = { TopAppBar(title = { Text(text = stringResource(R.string.characters_title)) }) }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item { Spacer(modifier = Modifier.height(4.dp)) }
            item {
                Text(
                    text = stringResource(R.string.characters_intro),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            // Not registered yet: browse-only status, never an age error.
            if (accountEmail == null) {
                item {
                    Text(
                        text = stringResource(R.string.account_not_logged_in),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            // A failed load keeps its error on screen with a retry
            // action; cached characters below stay visible, and an
            // empty list shows the error instead of "no pen pals".
            // The error text itself says what failed (no connection
            // vs server vs session) — it is never a blanket network
            // message.
            val error = charactersError
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
                            if (unlocked.isNotEmpty()) {
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = stringResource(R.string.characters_cached_notice),
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            Spacer(modifier = Modifier.height(12.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button(onClick = { viewModel.refresh() }) {
                                    Text(text = stringResource(R.string.action_retry))
                                }
                                if (charactersErrorSessionExpired) {
                                    OutlinedButton(onClick = onLoginClick) {
                                        Text(text = stringResource(R.string.account_login_register))
                                    }
                                }
                            }
                        }
                    }
                }
            }
            if (unlocked.isEmpty() && !isLoading && error == null) {
                item {
                    EmptyBox(
                        message = stringResource(R.string.characters_empty),
                        modifier = Modifier.height(120.dp)
                    )
                }
            }
            items(unlocked, key = { it.id }) { character ->
                CharacterCard(character = character, onClick = { onCharacterClick(character.id) })
            }
            item { Spacer(modifier = Modifier.height(16.dp)) }
        }
    }
}

/**
 * Backend returns gender as "male"/"female" (the task brief said "男"/"女";
 * accept both). Displayed as 男 / 女 in Chinese, Male / Female in English,
 * never as the English code. Unknown values pass through unchanged.
 */
fun displayGender(gender: String?): String? = when (gender?.trim()?.lowercase()) {
    "male", "男" -> if (Locale.getDefault().language == Locale.ENGLISH.language) "Male" else "男"
    "female", "女" -> if (Locale.getDefault().language == Locale.ENGLISH.language) "Female" else "女"
    else -> gender?.takeIf { it.isNotBlank() }
}

/**
 * The backend returns photo paths RELATIVE to the server root
 * ("/static/photos/P01/avatar.jpg"). Resolve them against the app's
 * fixed base URL for Coil; absolute URLs pass through unchanged.
 * Null / blank / unrecognised values stay null — the caller then
 * shows the initial-letter placeholder, never a broken image.
 */
fun resolvePhotoUrl(url: String?): String? {
    val u = url?.trim().orEmpty()
    if (u.isBlank()) return null
    if (u.startsWith("http://") || u.startsWith("https://")) return u
    if (u.startsWith("/")) return ApiClient.DEFAULT_BASE_URL + u
    return null
}

/**
 * The 3 life-photo slots for a character. Real photos (is_placeholder
 * false, photo_url set) are shown as images; slots without a real URL
 * stay labelled placeholders — never presented as a real photo.
 */
fun CharacterDto.photoSlots(): List<CharacterPhotoDto> {
    val real = (photos ?: emptyList()).take(3)
    return real + List(3 - real.size) {
        // Label is null: the UI falls back to stringResource(character_ai_label),
        // so the placeholder text follows the app language.
        CharacterPhotoDto(
            photoUrl = null,
            isPlaceholder = true,
            label = null
        )
    }
}

/** Avatar: the real photo when available, else the initial-letter placeholder. */
@Composable
fun CharacterAvatar(character: CharacterDto, size: androidx.compose.ui.unit.Dp) {
    val url = resolvePhotoUrl(character.photoUrl)
    var loadFailed by remember(url) { mutableStateOf(false) }
    if (url == null || loadFailed) {
        Box(
            modifier = Modifier
                .size(size)
                .clip(CircleShape)
                .background(MaterialTheme.colorScheme.primaryContainer),
            contentAlignment = Alignment.Center
        ) {
            Text(
                text = character.name.firstOrNull()?.toString() ?: "？",
                style = MaterialTheme.typography.headlineMedium,
                color = MaterialTheme.colorScheme.onPrimaryContainer
            )
        }
    } else {
        AsyncImage(
            model = ImageRequest.Builder(LocalContext.current)
                .data(url)
                .crossfade(true)
                .build(),
            contentDescription = stringResource(R.string.character_photo_desc, character.name),
            contentScale = ContentScale.Crop,
            modifier = Modifier
                .size(size)
                .clip(CircleShape),
            onError = { loadFailed = true }
        )
    }
}

@Composable
fun CharacterCard(character: CharacterDto, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            horizontalArrangement = Arrangement.spacedBy(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                CharacterAvatar(character = character, size = 64.dp)
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = stringResource(R.string.character_ai_label),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary,
                    textAlign = TextAlign.Center
                )
            }
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = character.name,
                    style = MaterialTheme.typography.titleMedium
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = listOfNotNull(
                        displayGender(character.gender),
                        character.age?.let { stringResource(R.string.character_age, it) },
                        character.occupation
                    ).joinToString(" · "),
                    style = MaterialTheme.typography.bodyMedium
                )
                if (!character.hobbies.isNullOrEmpty()) {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = stringResource(
                            R.string.character_hobbies,
                            character.hobbies!!.joinToString("、")
                        ),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2
                    )
                }
                character.motto?.takeIf { it.isNotBlank() }?.let { motto ->
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "“$motto”",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2
                    )
                }
            }
        }
    }
}

// ---------- Character detail + thread ----------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CharacterDetailScreen(
    characterId: String,
    viewModel: CharactersViewModel,
    onWriteClick: () -> Unit,
    onLetterClick: (Int) -> Unit,
    onBack: () -> Unit,
    /** False = anonymous browsing: the write entry is visibly disabled
     * with a prompt + a register action (writing needs an email account). */
    isRegistered: Boolean = true,
    onRegisterClick: () -> Unit = {}
) {
    var character by remember { mutableStateOf<CharacterDto?>(null) }
    val thread by viewModel.thread(characterId).collectAsState(initial = emptyList())

    LaunchedEffect(characterId) {
        character = viewModel.loadCharacter(characterId)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = character?.name ?: stringResource(R.string.characters_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.action_back)
                        )
                    }
                }
            )
        }
    ) { padding ->
        val current = character
        if (current == null) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                CircularProgressIndicator()
            }
            return@Scaffold
        }
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item { Spacer(modifier = Modifier.height(4.dp)) }
            item {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surface
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(16.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                CharacterAvatar(character = current, size = 96.dp)
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = stringResource(R.string.character_ai_label),
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.primary,
                                    textAlign = TextAlign.Center
                                )
                            }
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = current.name,
                                    style = MaterialTheme.typography.titleLarge
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = listOfNotNull(
                                        displayGender(current.gender),
                                        current.age?.let { stringResource(R.string.character_age, it) },
                                        current.occupation,
                                        current.city
                                    ).joinToString(" · "),
                                    style = MaterialTheme.typography.bodyMedium
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = "${stringResource(R.string.character_relationship)} · " +
                                        stringResource(R.string.character_ai_label),
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.primary
                                )
                            }
                        }
                        current.motto?.takeIf { it.isNotBlank() }?.let { motto ->
                            Spacer(modifier = Modifier.height(12.dp))
                            Text(
                                text = stringResource(R.string.character_motto_title),
                                style = MaterialTheme.typography.titleMedium
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = "“$motto”",
                                style = MaterialTheme.typography.bodyLarge
                            )
                        }
                        current.appearance?.let {
                            Spacer(modifier = Modifier.height(8.dp))
                            Text(text = it, style = MaterialTheme.typography.bodyLarge)
                        }
                        current.personality?.let {
                            Spacer(modifier = Modifier.height(8.dp))
                            Text(text = it, style = MaterialTheme.typography.bodyLarge)
                        }
                        if (!current.hobbies.isNullOrEmpty()) {
                            Spacer(modifier = Modifier.height(12.dp))
                            Text(
                                text = stringResource(R.string.character_hobbies_title),
                                style = MaterialTheme.typography.titleMedium
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = current.hobbies!!.joinToString("、"),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        if (!current.topics.isNullOrEmpty()) {
                            Spacer(modifier = Modifier.height(12.dp))
                            Text(
                                text = stringResource(R.string.character_topics),
                                style = MaterialTheme.typography.titleMedium
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = current.topics!!.joinToString("、"),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            }
            // ---- 3 life photos (real image when the backend has one, else placeholder) ----
            item {
                Text(
                    text = stringResource(R.string.character_life_photos),
                    style = MaterialTheme.typography.titleLarge
                )
            }
            items(current.photoSlots()) { photo ->
                val photoUrl = resolvePhotoUrl(photo.photoUrl)
                var photoFailed by remember(photoUrl) { mutableStateOf(false) }
                val showReal = photoUrl != null && photo.isPlaceholder != true && !photoFailed
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    )
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(16.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        if (showReal) {
                            AsyncImage(
                                model = ImageRequest.Builder(LocalContext.current)
                                    .data(photoUrl)
                                    .crossfade(true)
                                    .build(),
                                contentDescription = photo.scene
                                    ?: stringResource(R.string.character_photo_fallback),
                                contentScale = ContentScale.Crop,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .aspectRatio(3f / 4f)
                                    .clip(RoundedCornerShape(8.dp)),
                                onError = { photoFailed = true }
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                        }
                        Text(
                            text = photo.scene ?: stringResource(R.string.character_photo_fallback),
                            style = MaterialTheme.typography.bodyLarge
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = photo.label ?: stringResource(R.string.character_ai_label),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.primary
                        )
                        if (!showReal) {
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = stringResource(R.string.character_photo_not_live),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                textAlign = TextAlign.Center
                            )
                        }
                    }
                }
            }
            item {
                if (isRegistered) {
                    Button(
                        onClick = onWriteClick,
                        modifier = Modifier.fillMaxWidth().height(48.dp)
                    ) {
                        Text(text = stringResource(R.string.character_write))
                    }
                } else {
                    // Anonymous browsing: the entry is visibly disabled
                    // and says why, with a direct route to register —
                    // never let the user write a whole letter first and
                    // only then discover they cannot send it.
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = {},
                            enabled = false,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) {
                            Text(text = stringResource(R.string.character_write))
                        }
                        Text(
                            text = stringResource(R.string.err_email_required),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        OutlinedButton(
                            onClick = onRegisterClick,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) {
                            Text(text = stringResource(R.string.account_login_register))
                        }
                    }
                }
            }
            item {
                Text(
                    text = stringResource(R.string.character_thread_count, thread.size),
                    style = MaterialTheme.typography.titleLarge
                )
            }
            if (thread.isEmpty()) {
                item {
                    EmptyBox(
                        message = stringResource(R.string.letter_thread_empty),
                        modifier = Modifier.height(80.dp)
                    )
                }
            }
            items(thread, key = { it.id }) { letter ->
                LetterRow(letter = letter, onClick = { onLetterClick(letter.id) })
            }
            item { Spacer(modifier = Modifier.height(16.dp)) }
        }
    }
}

@Composable
fun LetterRow(letter: LetterDto, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(
            containerColor = if (letter.direction == "ai") {
                MaterialTheme.colorScheme.surface
            } else {
                MaterialTheme.colorScheme.surfaceVariant
            }
        )
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = if (letter.direction == "ai") {
                        stringResource(R.string.letter_from_friend)
                    } else {
                        stringResource(R.string.letter_from_me)
                    },
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary
                )
                if (letter.direction == "ai" && letter.aiGenerated == true) {
                    Text(
                        text = stringResource(R.string.letter_ai_label),
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = letter.text.take(120) + if (letter.text.length > 120) "…" else "",
                style = MaterialTheme.typography.bodyMedium
            )
            Spacer(modifier = Modifier.height(8.dp))
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
                    expectedReplyText(letter.expectedReplyAt, letter.replyDueAt)
                        .takeIf { it.isNotBlank() && letter.direction == "user" }
                ).joinToString(" · "),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

// ---------- Write a letter ----------

class WriteLetterViewModel(
    private val repository: PenpalRepository,
    private val settings: SettingsStore
) : ViewModel() {

    private val _isSending = MutableStateFlow(false)
    val isSending: StateFlow<Boolean> = _isSending

    private val _notice = MutableStateFlow<Notice?>(null)
    val notice: StateFlow<Notice?> = _notice

    /** The letter just sent (null until a send succeeds). The screen shows
     * its backend-computed expected reply time instead of popping away. */
    private val _sentLetter = MutableStateFlow<LetterDto?>(null)
    val sentLetter: StateFlow<LetterDto?> = _sentLetter

    fun send(characterId: String, text: String) {
        viewModelScope.launch {
            // Defence in depth for the write gate: anonymous accounts
            // never reach the API (the UI disables the entry, and the
            // server 403s too) — show the localised prompt instead.
            if (settings.accountEmail.first() == null) {
                _notice.value = Notice(R.string.err_email_required)
                return@launch
            }
            _isSending.value = true
            repository.sendLetter(characterId, text.trim())
                .onSuccess { _sentLetter.value = it }
                .onFailure {
                    _notice.value = it.userNotice()
                    // A failed send can mean the server already holds a
                    // letter we have not cached (e.g. the 409
                    // unanswered-letter case): pull the timeline so Home
                    // shows it with its delivery status + expected reply
                    // time instead of "还没有信".
                    runCatching { repository.refreshLetters() }
                }
            _isSending.value = false
        }
    }

    fun clearNotice() {
        _notice.value = null
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WriteLetterScreen(
    characterId: String,
    viewModel: WriteLetterViewModel,
    onSent: () -> Unit,
    onBack: () -> Unit,
    /** False = anonymous browsing: show the gate, not the editor. */
    isRegistered: Boolean = true,
    onRegisterClick: () -> Unit = {}
) {
    var text by remember { mutableStateOf("") }
    val isSending by viewModel.isSending.collectAsState()
    val notice by viewModel.notice.collectAsState()
    val sentLetter by viewModel.sentLetter.collectAsState()

    val snackbarHostState = remember { SnackbarHostState() }
    val noticeText = notice?.let { stringResource(it.resId, *it.args.toTypedArray()) }
    LaunchedEffect(noticeText) {
        noticeText?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text(text = stringResource(R.string.letter_write_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.action_back)
                        )
                    }
                }
            )
        }
    ) { padding ->
        if (!isRegistered) {
            // ---- Anonymous gate: no editor at all, just the prompt and
            // a direct route to register. ----
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Text(
                    text = stringResource(R.string.err_email_required),
                    style = MaterialTheme.typography.headlineMedium
                )
                Text(
                    text = stringResource(R.string.account_not_logged_in),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Button(
                    onClick = onRegisterClick,
                    modifier = Modifier.fillMaxWidth().height(48.dp)
                ) {
                    Text(text = stringResource(R.string.account_login_register))
                }
            }
            return@Scaffold
        }
        val sent = sentLetter
        if (sent != null) {
            // ---- Sent: show the backend's expected reply time + the rules ----
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Text(
                    text = stringResource(R.string.letter_sent_title),
                    style = MaterialTheme.typography.headlineMedium
                )
                val expected = expectedReplyText(sent.expectedReplyAt, sent.replyDueAt)
                if (expected.isNotBlank()) {
                    Text(
                        text = expected,
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
                sent.deliveryStageText?.takeIf { it.isNotBlank() }?.let { stage ->
                    Text(
                        text = stage,
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
                Text(
                    text = stringResource(R.string.letter_sent_rules),
                    style = MaterialTheme.typography.bodyLarge
                )
                Text(
                    text = stringResource(R.string.letter_sent_reminder),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Button(
                    onClick = onSent,
                    modifier = Modifier.fillMaxWidth().height(48.dp)
                ) {
                    Text(text = stringResource(R.string.action_done))
                }
            }
            return@Scaffold
        }
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text(
                text = stringResource(R.string.letter_write_intro),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            OutlinedTextField(
                value = text,
                onValueChange = { if (it.length <= MAX_LETTER_CHARS) text = it },
                label = { Text(text = stringResource(R.string.letter_hint)) },
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                minLines = 10
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = stringResource(R.string.letter_chars, text.length),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Button(
                onClick = { viewModel.send(characterId, text) },
                enabled = text.isNotBlank() && !isSending,
                modifier = Modifier.fillMaxWidth().height(48.dp)
            ) {
                if (isSending) {
                    CircularProgressIndicator(
                        modifier = Modifier.padding(end = 8.dp),
                        strokeWidth = 2.dp
                    )
                    Text(text = stringResource(R.string.letter_sending))
                } else {
                    Text(text = stringResource(R.string.letter_send))
                }
            }
        }
    }
}

// ---------- Letter detail ----------

class LetterDetailViewModel(
    private val repository: PenpalRepository
) : ViewModel() {

    private val _letter = MutableStateFlow<LetterDto?>(null)
    val letter: StateFlow<LetterDto?> = _letter

    private val _notice = MutableStateFlow<Notice?>(null)
    val notice: StateFlow<Notice?> = _notice

    fun load(letterId: Int) {
        viewModelScope.launch {
            _letter.value = repository.getLetter(letterId)
            repository.refreshLetters()
            _letter.value = repository.getLetter(letterId)
        }
    }

    /** Only AI replies can be marked read (server rule); awards +1 point.
     * [onMarked] runs after a successful mark so the caller can refresh
     * the unread badge / timeline. */
    fun markRead(onMarked: (() -> Unit)? = null) {
        val current = _letter.value ?: return
        if (current.direction != "ai") return
        if ((current.userReadAt ?: current.readAt) != null) return
        viewModelScope.launch {
            repository.markLetterRead(current.id)
                .onSuccess {
                    _letter.value = repository.getLetter(current.id)
                    repository.refreshLetters()
                    onMarked?.invoke()
                }
                .onFailure { _notice.value = it.userNotice() }
        }
    }

    fun clearNotice() {
        _notice.value = null
    }

    /** The thread for one character (oldest first), for the reply gate:
     * the server allows the next letter only when no user letter for
     * this character is still in_transit (409 unanswered_letter). */
    fun thread(characterId: String) = repository.lettersForCharacter(characterId)
}

/**
 * Whether the "Reply" button on an AI letter's detail page may open the
 * write screen. Mirrors the server's turn-taking rule exactly: one
 * outstanding (in_transit) user letter per character blocks the next
 * send (409 unanswered_letter). A reply still in transit is not
 * reply-able either — it has not been delivered yet.
 */
fun canReplyToLetter(letter: LetterDto, thread: List<LetterDto>): Boolean {
    if (letter.direction != "ai") return false
    if (letter.status == "in_transit") return false
    return thread
        .filter { it.characterId == letter.characterId }
        .none { it.direction == "user" && it.status == "in_transit" }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LetterDetailScreen(
    viewModel: LetterDetailViewModel,
    onBack: () -> Unit,
    onMarkedRead: () -> Unit = {},
    /** Opens the write screen for this letter's character. */
    onReplyClick: (String) -> Unit = {},
    /** False = anonymous browsing: the reply entry is visibly disabled
     * with a prompt + a register action (writing needs an email account). */
    isRegistered: Boolean = true,
    onRegisterClick: () -> Unit = {}
) {
    val letter by viewModel.letter.collectAsState()
    val notice by viewModel.notice.collectAsState()

    // The character's thread, for the reply gate below. The flow only
    // emits the cached thread once the letter itself is loaded, so the
    // reply button waits until the thread actually contains this letter
    // (threadLoaded) instead of deciding on an empty initial list.
    val thread by viewModel.thread(letter?.characterId ?: "").collectAsState(initial = emptyList())
    val threadLoaded = letter?.let { shown -> thread.any { it.id == shown.id } } ?: false

    val snackbarHostState = remember { SnackbarHostState() }
    val noticeText = notice?.let { stringResource(it.resId, *it.args.toTypedArray()) }
    LaunchedEffect(noticeText) {
        noticeText?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
        }
    }

    // Opening a reply marks it read (POST /letters/{id}/read) and refreshes
    // the timeline + unread badge. The guard in markRead keeps this
    // idempotent — already-read letters are never re-marked.
    val currentLetter = letter
    LaunchedEffect(currentLetter?.id, currentLetter?.direction) {
        val current = currentLetter ?: return@LaunchedEffect
        if (current.direction == "ai" && (current.userReadAt ?: current.readAt) == null) {
            viewModel.markRead { onMarkedRead() }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = if (letter?.direction == "ai") {
                            stringResource(R.string.letter_from_friend)
                        } else {
                            stringResource(R.string.letter_from_me)
                        }
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.action_back)
                        )
                    }
                }
            )
        }
    ) { padding ->
        val current = letter
        if (current == null) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                CircularProgressIndicator()
            }
            return@Scaffold
        }
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surface
                )
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text(
                            text = formatDateTimeShanghai(current.createdAt),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        if (current.direction == "ai") {
                            Text(
                                text = stringResource(R.string.letter_ai_label),
                                style = MaterialTheme.typography.labelLarge,
                                color = MaterialTheme.colorScheme.primary,
                                fontWeight = FontWeight.Medium
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = current.text,
                        style = MaterialTheme.typography.bodyLarge
                    )
                    current.deliveryStageText?.takeIf { it.isNotBlank() }?.let { stage ->
                        Spacer(modifier = Modifier.height(12.dp))
                        Text(
                            text = stage,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }
                    val due = expectedReplyText(current.expectedReplyAt, current.replyDueAt)
                    if (due.isNotBlank() && current.direction == "user") {
                        Spacer(modifier = Modifier.height(12.dp))
                        Text(
                            text = due,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        if (current.isFirst == true) {
                            Text(
                                text = stringResource(R.string.letter_first_note),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        } else {
                            Text(
                                text = stringResource(R.string.letter_detail_rule),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                    if (current.direction == "ai" && current.status == "in_transit") {
                        Spacer(modifier = Modifier.height(12.dp))
                        Text(
                            text = stringResource(R.string.letter_reply_waiting),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = letterReadLine(current),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            if (current.direction == "ai") {
                val alreadyRead = (current.userReadAt ?: current.readAt) != null
                Button(
                    onClick = { viewModel.markRead { onMarkedRead() } },
                    enabled = !alreadyRead,
                    modifier = Modifier.fillMaxWidth().height(48.dp)
                ) {
                    Text(
                        text = if (!alreadyRead) {
                            stringResource(R.string.letter_mark_read)
                        } else {
                            stringResource(R.string.letter_read)
                        }
                    )
                }
                // ---- Reply: opens the write screen for this character.
                // Only once the thread is loaded (never decide on the
                // empty initial list), and only when the turn-taking
                // rule allows a new letter — otherwise the button stays
                // disabled with the reason, never a tap-then-error.
                if (threadLoaded) {
                    if (!isRegistered) {
                        Button(
                            onClick = {},
                            enabled = false,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) {
                            Text(text = stringResource(R.string.letter_reply))
                        }
                        Text(
                            text = stringResource(R.string.err_email_required),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        OutlinedButton(
                            onClick = onRegisterClick,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) {
                            Text(text = stringResource(R.string.account_login_register))
                        }
                    } else if (canReplyToLetter(current, thread)) {
                        Button(
                            onClick = { onReplyClick(current.characterId) },
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) {
                            Text(text = stringResource(R.string.letter_reply))
                        }
                    } else {
                        Button(
                            onClick = {},
                            enabled = false,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) {
                            Text(text = stringResource(R.string.letter_reply))
                        }
                        Text(
                            text = stringResource(
                                if (current.status == "in_transit") {
                                    R.string.letter_reply_waiting
                                } else {
                                    R.string.err_unanswered_letter
                                }
                            ),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
        }
    }
}
