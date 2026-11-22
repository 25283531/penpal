package com.junze.penpal.ui.account

import java.time.LocalDate
import java.time.Period
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.time.format.ResolverStyle

/**
 * Date of birth handling for registration (2026-11-22 decision).
 *
 * Registration requires a date of birth — no longer just an age number —
 * and the user must be at least [MIN_REGISTER_AGE_YEARS] full years old.
 * There is no real-name verification and the app does not audit whether
 * the age is real; the disclaimer under the field says so, and the local
 * gate below only enforces what can be computed from the entered date.
 *
 * Pure Kotlin (java.time only): no Android framework, so this file is
 * unit-testable on the JVM (see BirthDateTest).
 */

/** Minimum age (full years) to register. */
const val MIN_REGISTER_AGE_YEARS = 18

private val BIRTH_DATE_FORMATTER: DateTimeFormatter =
    DateTimeFormatter.ofPattern("uuuu-MM-dd").withResolverStyle(ResolverStyle.STRICT)

/**
 * Strict YYYY-MM-DD parse. Rejects impossible dates (1990-02-30,
 * 1990-13-01) and wrong shapes (90-05-20, 1990/05/20, 1990-5-2).
 */
fun parseBirthDate(text: String): LocalDate? {
    val trimmed = text.trim()
    if (!Regex("^\\d{4}-\\d{2}-\\d{2}$").matches(trimmed)) return null
    return try {
        LocalDate.parse(trimmed, BIRTH_DATE_FORMATTER)
    } catch (_: DateTimeParseException) {
        null
    }
}

/** Formats a date as YYYY-MM-DD (the wire format for `birth_date`). */
fun formatBirthDate(date: LocalDate): String = date.format(BIRTH_DATE_FORMATTER)

/**
 * Full years between [birthDate] and [today]: a birthday not yet reached
 * this year does not count (so someone born 2008-11-23 is still 17 on
 * 2026-11-22).
 */
fun fullYearsOld(birthDate: LocalDate, today: LocalDate = LocalDate.now()): Int =
    Period.between(birthDate, today).years

/** Local pre-submit verdict for the entered birth date. */
sealed interface BirthDateCheck {
    data object Blank : BirthDateCheck
    data object InvalidFormat : BirthDateCheck
    data object FutureDate : BirthDateCheck
    data class Underage(val years: Int) : BirthDateCheck
    data class OfAge(val years: Int) : BirthDateCheck
}

/**
 * Local gate, checked before anything is submitted: blank / malformed /
 * future / under-18 dates are all refused here, so the user never waits
 * on the backend to be told. The backend still re-checks (400
 * `age_under_18`) and that code maps to the same localised wording.
 */
fun checkBirthDate(text: String, today: LocalDate = LocalDate.now()): BirthDateCheck {
    if (text.isBlank()) return BirthDateCheck.Blank
    val date = parseBirthDate(text) ?: return BirthDateCheck.InvalidFormat
    if (date.isAfter(today)) return BirthDateCheck.FutureDate
    val years = fullYearsOld(date, today)
    return if (years >= MIN_REGISTER_AGE_YEARS) BirthDateCheck.OfAge(years)
    else BirthDateCheck.Underage(years)
}
