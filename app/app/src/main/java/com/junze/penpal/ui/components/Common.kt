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
import org.json.JSONObject
import retrofit2.HttpException
import java.io.IOException

/**
 * Turns a failure into a message the user can act on.
 * - No connection / server not reachable yet -> "服务器未连接，请稍后再试"
 * - HTTP error with a backend {"detail": "..."} -> that detail
 *   (409 = outstanding letter, 429 = daily send limit reached)
 * - Anything else -> the exception message, or a generic fallback.
 */
fun Throwable.userMessage(): String {
    if (this is IOException) {
        return "服务器未连接，请稍后再试"
    }
    if (this is HttpException) {
        try {
            val body = response()?.errorBody()?.string()
            if (!body.isNullOrBlank()) {
                val detail = JSONObject(body).optString("detail", "")
                if (detail.isNotBlank()) return detail
            }
        } catch (_: Exception) {
            // fall through to the generic message
        }
        return when (code()) {
            429 -> "操作太频繁，请稍后再试"
            401 -> "登录已过期，请重新登录"
            404 -> "没有找到相关内容"
            else -> "请求失败（${code()}），请稍后再试"
        }
    }
    return message ?: "网络异常，请检查网络后重试"
}

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
