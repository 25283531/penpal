package com.junze.penpal.ui.account

import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Birth-date parsing + the 18+ registration gate (BirthDate.kt).
 *
 * Pure JVM tests (no Android framework). The boundary that matters most:
 * full years only — a birthday not yet reached this year does not count.
 */
class BirthDateTest {

    // Fixed "today" so the boundary tests never drift with the calendar.
    private val today = LocalDate.of(2026, 11, 22)

    @Test
    fun parse_validDate() {
        assertEquals(LocalDate.of(1990, 5, 20), parseBirthDate("1990-05-20"))
    }

    @Test
    fun parse_rejectsImpossibleDates() {
        assertNull(parseBirthDate("1990-02-30"))
        assertNull(parseBirthDate("1990-13-01"))
        assertNull(parseBirthDate("1990-00-10"))
    }

    @Test
    fun parse_rejectsWrongShapes() {
        assertNull(parseBirthDate("90-05-20"))
        assertNull(parseBirthDate("1990/05/20"))
        assertNull(parseBirthDate("1990-5-2"))
        assertNull(parseBirthDate(""))
    }

    @Test
    fun parse_trimsSurroundingWhitespace() {
        assertEquals(LocalDate.of(1990, 5, 20), parseBirthDate(" 1990-05-20 "))
    }

    @Test
    fun format_roundTrips() {
        assertEquals("2008-02-29", formatBirthDate(LocalDate.of(2008, 2, 29)))
    }

    @Test
    fun fullYears_birthdayNotYetReachedThisYear() {
        // Born 2008-11-23: still 17 on 2026-11-22, 18 the next day.
        assertEquals(17, fullYearsOld(LocalDate.of(2008, 11, 23), today))
        assertEquals(18, fullYearsOld(LocalDate.of(2008, 11, 23), LocalDate.of(2026, 11, 23)))
    }

    @Test
    fun fullYears_leapDayBirthday() {
        // Born 2008-02-29: 17 on 2026-02-28, 18 on 2026-03-01.
        assertEquals(17, fullYearsOld(LocalDate.of(2008, 2, 29), LocalDate.of(2026, 2, 28)))
        assertEquals(18, fullYearsOld(LocalDate.of(2008, 2, 29), LocalDate.of(2026, 3, 1)))
    }

    @Test
    fun check_blank() {
        assertEquals(BirthDateCheck.Blank, checkBirthDate("", today))
        assertEquals(BirthDateCheck.Blank, checkBirthDate("   ", today))
    }

    @Test
    fun check_invalidFormat() {
        assertEquals(BirthDateCheck.InvalidFormat, checkBirthDate("1990-02-30", today))
        assertEquals(BirthDateCheck.InvalidFormat, checkBirthDate("not-a-date", today))
    }

    @Test
    fun check_futureDate() {
        assertEquals(BirthDateCheck.FutureDate, checkBirthDate("2026-11-23", today))
        assertEquals(BirthDateCheck.FutureDate, checkBirthDate("2030-01-01", today))
    }

    @Test
    fun check_exactly18Today_isOfAge() {
        assertEquals(BirthDateCheck.OfAge(18), checkBirthDate("2008-11-22", today))
    }

    @Test
    fun check_dayBefore18thBirthday_isUnderage() {
        assertEquals(BirthDateCheck.Underage(17), checkBirthDate("2008-11-23", today))
    }

    @Test
    fun check_adult_isOfAge() {
        assertEquals(BirthDateCheck.OfAge(36), checkBirthDate("1990-05-20", today))
    }
}
