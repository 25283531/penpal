package com.junze.penpal.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.junze.penpal.R

// Error text lives in ErrorMessages.kt: Throwables are mapped to a
// localised [Notice] with Throwable.userNotice(). Backend `detail`
// strings are never shown to the user (see that file).

/**
 * Virtual-world name rule, identical to the backend's
 * _DISPLAY_NAME_RE (backend/app/main.py): 1-20 chars, Chinese /
 * letters / digits only. This is NOT a real name and is never
 * identity-checked — it is only how pen pals address the user.
 */
private val DISPLAY_NAME_REGEX = Regex("^[\\u4e00-\\u9fffA-Za-z0-9]{1,20}$")

fun isValidDisplayName(name: String): Boolean = DISPLAY_NAME_REGEX.matches(name)

@Composable
fun LoadingBox(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        CircularProgressIndicator()
    }
}

@Composable
fun ErrorBox(
    message: String,
    onRetry: (() -> Unit)? = null,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center
            )
            if (onRetry != null) {
                Spacer(modifier = Modifier.height(12.dp))
                Button(onClick = onRetry) {
                    Text(text = stringResource(R.string.action_retry))
                }
            }
        }
    }
}

@Composable
fun EmptyBox(
    message: String,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center
        )
    }
}
