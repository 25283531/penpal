package com.junze.penpal.ui.nav

/** Bottom-nav tabs. */
object Routes {
    const val HOME = "home"
    const val CHARACTERS = "characters"
    const val ME = "me"

    /** Account (email registration / login / verify) and privacy policy. */
    const val ACCOUNT = "account"
    const val PRIVACY = "privacy"

    /** Character detail: info + thread + write button. */
    const val CHARACTER_DETAIL = "character/{characterId}"
    fun characterDetail(characterId: String) = "character/$characterId"

    /** Write a letter to a character. */
    const val WRITE_LETTER = "write/{characterId}"
    fun writeLetter(characterId: String) = "write/$characterId"

    /** One letter (full text, mark read for AI replies). */
    const val LETTER_DETAIL = "letter/{letterId}"
    fun letterDetail(letterId: Int) = "letter/$letterId"
}
