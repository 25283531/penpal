package com.junze.penpal.ui.home

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.junze.penpal.data.repository.PenpalRepository
import com.junze.penpal.worker.UnreadBadge
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/**
 * Unread AI-reply count, owned once at the activity level so both the
 * bottom-nav badge (MainActivity) and the screens share one source.
 *
 * The count always comes from the backend (GET /letters/unread-count);
 * it is never guessed locally. Every refresh also pushes the count to
 * the launcher badge (best effort, see UnreadBadge) and clearing to 0
 * cancels it. Failures are silent — a stale count is better than a
 * fake one, and the badge simply keeps its last value.
 */
class UnreadViewModel(
    application: Application,
    private val repository: PenpalRepository
) : AndroidViewModel(application) {

    private val _unreadCount = MutableStateFlow(0)
    val unreadCount: StateFlow<Int> = _unreadCount

    fun refresh() {
        viewModelScope.launch {
            repository.getUnreadCount()
                .onSuccess {
                    _unreadCount.value = it
                    UnreadBadge.update(getApplication(), it)
                }
        }
    }
}
