package com.junze.penpal.ui.privacy

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.junze.penpal.R
import com.junze.penpal.data.repository.PenpalRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class PrivacyViewModel(
    private val repository: PenpalRepository
) : ViewModel() {

    /** Latest policy text from the server (null until it loads). */
    private val _text = MutableStateFlow<String?>(null)
    val text: StateFlow<String?> = _text

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            repository.getPrivacy().onSuccess { _text.value = it.text }
        }
    }
}

/**
 * Shows the privacy policy. Loads it from GET /api/v1/privacy when online,
 * with a bundled copy as the offline fallback (same text as the server).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PrivacyScreen(
    viewModel: PrivacyViewModel,
    onBack: () -> Unit
) {
    val remoteText by viewModel.text.collectAsState()
    val context = LocalContext.current
    val bundledText = remember {
        try {
            context.resources.openRawResource(R.raw.privacy_policy)
                .bufferedReader().readText()
        } catch (_: Exception) {
            "隐私协议加载失败，请检查网络后重试。"
        }
    }
    val text = remoteText ?: bundledText

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = "隐私协议") },
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
                .padding(horizontal = 16.dp)
        ) {
            item { Spacer(modifier = Modifier.height(8.dp)) }
            item {
                Text(
                    text = text,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurface
                )
            }
            item { Spacer(modifier = Modifier.height(24.dp)) }
        }
    }
}
