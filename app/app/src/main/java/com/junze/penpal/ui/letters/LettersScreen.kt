package com.junze.penpal.ui.letters

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
import androidx.compose.foundation.rememberScrollState
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.junze.penpal.R
import com.junze.penpal.data.api.CharacterDto
import com.junze.penpal.data.api.LetterDto
import com.junze.penpal.data.repository.MAX_LETTER_CHARS
import com.junze.penpal.data.repository.PenpalRepository
import com.junze.penpal.ui.components.EmptyBox
import com.junze.penpal.ui.components.userMessage
import com.junze.penpal.ui.home.replyDueText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

// ---------- Characters ----------

class CharactersViewModel(
    private val repository: PenpalRepository
) : ViewModel() {

    val characters: StateFlow<List<CharacterDto>> = repository.characters
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading

    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _isLoading.value = true
            repository.refreshCharacters().onFailure {
                _notice.value = it.userMessage()
            }
            _isLoading.value = false
        }
    }

    fun thread(characterId: String) = repository.lettersForCharacter(characterId)

    suspend fun loadCharacter(characterId: String): CharacterDto? {
        refresh()
        return repository.getCharacter(characterId)
    }

    fun clearNotice() {
        _notice.value = null
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CharactersScreen(
    viewModel: CharactersViewModel,
    onCharacterClick: (String) -> Unit
) {
    val characters by viewModel.characters.collectAsState()
    val isLoading by viewModel.isLoading.collectAsState()
    val notice by viewModel.notice.collectAsState()

    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(notice) {
        notice?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
        }
    }

    // Locked characters are hidden (M0: P01–P05 are all unlocked by default).
    val unlocked = characters.filter { it.unlocked }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
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
                    text = "每一位都是虚拟知己，不是真人；回信由 AI 生成。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (unlocked.isEmpty() && !isLoading) {
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
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = character.name,
                    style = MaterialTheme.typography.titleMedium
                )
                Text(
                    text = stringResource(R.string.character_ai_label),
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary
                )
            }
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = listOfNotNull(
                    character.age?.let { "$it 岁" },
                    character.occupation
                ).joinToString(" · "),
                style = MaterialTheme.typography.bodyMedium
            )
            character.personality?.let {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 3
                )
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
    onBack: () -> Unit
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
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
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
                        Text(
                            text = "${current.name} · ${current.occupation ?: ""}",
                            style = MaterialTheme.typography.titleLarge
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "${stringResource(R.string.character_relationship)} · " +
                                stringResource(R.string.character_ai_label),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.primary
                        )
                        current.appearance?.let {
                            Spacer(modifier = Modifier.height(8.dp))
                            Text(text = it, style = MaterialTheme.typography.bodyLarge)
                        }
                        current.personality?.let {
                            Spacer(modifier = Modifier.height(8.dp))
                            Text(text = it, style = MaterialTheme.typography.bodyLarge)
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
            item {
                Button(
                    onClick = onWriteClick,
                    modifier = Modifier.fillMaxWidth().height(48.dp)
                ) {
                    Text(text = stringResource(R.string.character_write))
                }
            }
            item {
                Text(
                    text = "${stringResource(R.string.character_thread)}（${thread.size}）",
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
            Text(
                text = listOfNotNull(
                    letter.createdAt?.take(10),
                    replyDueText(letter.replyDueAt).takeIf { it.isNotBlank() },
                    if (letter.direction == "ai" && letter.readAt == null) "未读" else null
                ).joinToString(" · "),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

// ---------- Write a letter ----------

class WriteLetterViewModel(
    private val repository: PenpalRepository
) : ViewModel() {

    private val _isSending = MutableStateFlow(false)
    val isSending: StateFlow<Boolean> = _isSending

    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice

    fun send(characterId: String, text: String, onSent: () -> Unit) {
        viewModelScope.launch {
            _isSending.value = true
            repository.sendLetter(characterId, text.trim())
                .onSuccess {
                    _notice.value = "信已寄出，对方会慢慢回信"
                    onSent()
                }
                .onFailure { _notice.value = it.userMessage() }
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
    onBack: () -> Unit
) {
    var text by remember { mutableStateOf("") }
    val isSending by viewModel.isSending.collectAsState()
    val notice by viewModel.notice.collectAsState()

    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(notice) {
        notice?.let {
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
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text(
                text = "第一封信对方今天就会回；之后免费每 3 天回一封。每天最多寄 1 封信。",
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
                onClick = { viewModel.send(characterId, text) { onSent() } },
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

    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice

    fun load(letterId: Int) {
        viewModelScope.launch {
            _letter.value = repository.getLetter(letterId)
            repository.refreshLetters()
            _letter.value = repository.getLetter(letterId)
        }
    }

    /** Only AI replies can be marked read (server rule); awards +1 point. */
    fun markRead() {
        val current = _letter.value ?: return
        if (current.direction != "ai" || current.readAt != null) return
        viewModelScope.launch {
            repository.markLetterRead(current.id)
                .onSuccess { _letter.value = repository.getLetter(current.id) }
                .onFailure { _notice.value = it.userMessage() }
        }
    }

    fun clearNotice() {
        _notice.value = null
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LetterDetailScreen(
    viewModel: LetterDetailViewModel,
    onBack: () -> Unit
) {
    val letter by viewModel.letter.collectAsState()
    val notice by viewModel.notice.collectAsState()

    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(notice) {
        notice?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
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
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
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
                            text = current.createdAt?.take(10) ?: "",
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
                    val due = replyDueText(current.replyDueAt)
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
                }
            }
            if (current.direction == "ai") {
                Button(
                    onClick = { viewModel.markRead() },
                    enabled = current.readAt == null,
                    modifier = Modifier.fillMaxWidth().height(48.dp)
                ) {
                    Text(
                        text = if (current.readAt == null) {
                            stringResource(R.string.letter_mark_read)
                        } else {
                            stringResource(R.string.letter_read)
                        }
                    )
                }
            }
        }
    }
}
