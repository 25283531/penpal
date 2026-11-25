package com.junze.penpal.ui.letters

import com.junze.penpal.data.api.LetterDto
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The "Reply" button gate on an AI letter's detail page
 * (canReplyToLetter in LettersScreen.kt). It mirrors the server's
 * turn-taking rule: one outstanding (in_transit) user letter per
 * character blocks the next send (409 unanswered_letter).
 */
class LetterReplyTest {

    private fun letter(
        id: Int,
        direction: String,
        status: String?,
        characterId: String = "P01"
    ) = LetterDto(
        id = id,
        characterId = characterId,
        direction = direction,
        text = "hello",
        status = status
    )

    @Test
    fun deliveredAiReply_noOutstandingLetter_canReply() {
        val reply = letter(2, "ai", "delivered")
        val thread = listOf(
            letter(1, "user", "replied"),
            reply
        )
        assertTrue(canReplyToLetter(reply, thread))
    }

    @Test
    fun inTransitAiReply_cannotReply() {
        val reply = letter(2, "ai", "in_transit")
        assertFalse(canReplyToLetter(reply, listOf(reply)))
    }

    @Test
    fun userLetter_hasNoReplyButton() {
        val mine = letter(1, "user", "in_transit")
        assertFalse(canReplyToLetter(mine, listOf(mine)))
    }

    @Test
    fun deliveredAiReply_outstandingUserLetter_cannotReply() {
        // The thread's newest letter is a user letter still waiting
        // for its reply: the round is not over yet.
        val oldReply = letter(2, "ai", "delivered")
        val thread = listOf(
            letter(1, "user", "replied"),
            oldReply,
            letter(3, "user", "in_transit")
        )
        assertFalse(canReplyToLetter(oldReply, thread))
    }

    @Test
    fun deliveredAiReply_otherCharacterOutstanding_doesNotBlock() {
        // An outstanding letter to another character is irrelevant:
        // turn-taking is per character.
        val reply = letter(2, "ai", "delivered")
        val thread = listOf(
            letter(1, "user", "replied"),
            reply
        )
        val otherThread = thread + letter(9, "user", "in_transit", characterId = "P02")
        assertTrue(canReplyToLetter(reply, otherThread))
    }
}
