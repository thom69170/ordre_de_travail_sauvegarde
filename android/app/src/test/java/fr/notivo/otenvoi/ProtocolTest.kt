package fr.notivo.otenvoi

import fr.notivo.otenvoi.mail.DayState
import fr.notivo.otenvoi.mail.DayStatus
import fr.notivo.otenvoi.mail.MailClient
import fr.notivo.otenvoi.mail.MailState
import fr.notivo.otenvoi.mail.PcState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDate

class ProtocolTest {
    private val d1 = LocalDate.of(2026, 11, 24)
    private val d2 = LocalDate.of(2026, 11, 23)
    private val d3 = LocalDate.of(2026, 11, 22)
    private val d4 = LocalDate.of(2026, 11, 21)

    @Test
    fun subjectRoundTrip() {
        assertEquals("OT 2026-11-24", Protocol.subjectFor(d1))
        assertEquals(d1, Protocol.dateFromSubject("OT 2026-11-24"))
        assertEquals(d1, Protocol.dateFromSubject("  OT 2026-11-24 "))
    }

    @Test
    fun foreignSubjectsAreIgnored() {
        assertNull(Protocol.dateFromSubject("OT-ETAT"))
        assertNull(Protocol.dateFromSubject("Facture 2026-11-24"))
        assertNull(Protocol.dateFromSubject("OT 2026-13-45")) // date impossible
        assertNull(Protocol.dateFromSubject(null))
    }

    @Test
    fun pcStateOverridesSentState() {
        val state = MailState(
            sentAt = mapOf(d1 to millis("2026-11-24T07:59:00"), d2 to 1L, d3 to 1L),
            pc = PcState(savedDates = setOf(d2), reviewDates = setOf(d3), generatedAt = "2026-11-24T08:00:00"),
        )
        val merged = DayStatus.merge(listOf(d1, d2, d3, d4), state)
        assertEquals(DayState.PENDING, merged[d1]) // envoyé, inconnu du PC
        assertEquals(DayState.SAVED, merged[d2])   // enregistré par le PC
        assertEquals(DayState.REVIEW, merged[d3])  // à relire
        assertEquals(DayState.NONE, merged[d4])    // rien
    }

    @Test
    fun savedBeatsSentEvenIfSentLongAgo() {
        // Le PC a enregistré le jour d2 (envoi plus ancien que la fenêtre de lecture) : « enregistré ».
        val state = MailState(sentAt = emptyMap(), pc = PcState(setOf(d2), emptySet(), null))
        assertEquals(DayState.SAVED, DayStatus.merge(listOf(d2), state)[d2])
    }

    @Test
    fun noPcStateMeansPendingAtBest() {
        val state = MailState(sentAt = mapOf(d1 to 1L), pc = null)
        assertEquals(DayState.PENDING, DayStatus.merge(listOf(d1, d2), state)[d1])
        assertEquals(DayState.NONE, DayStatus.merge(listOf(d1, d2), state)[d2])
        assertEquals(DayState.NONE, DayStatus.merge(listOf(d1), null)[d1])
    }

    private fun millis(local: String): Long =
        java.time.LocalDateTime.parse(local).atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()

    @Test
    fun sentButUnknownToPcAfterItAnsweredIsMissing() {
        // envoyé à 07:00 ; le PC a publié son état à 08:00 (bien après) sans cet OT : date probablement erronée
        val pc = PcState(savedDates = setOf(d2), reviewDates = emptySet(), generatedAt = "2026-11-24T08:00:00")
        val late = MailState(sentAt = mapOf(d1 to millis("2026-11-24T07:00:00")), pc = pc)
        assertEquals(DayState.MISSING, DayStatus.merge(listOf(d1), late)[d1])
        // envoyé 5 minutes avant la publication : le PC n'a pas eu le temps, on reste « en attente »
        val recent = MailState(sentAt = mapOf(d1 to millis("2026-11-24T07:55:00")), pc = pc)
        assertEquals(DayState.PENDING, DayStatus.merge(listOf(d1), recent)[d1])
        // envoyé APRÈS la publication : le PC n'a forcément pas pu le voir
        val after = MailState(sentAt = mapOf(d1 to millis("2026-11-24T09:00:00")), pc = pc)
        assertEquals(DayState.PENDING, DayStatus.merge(listOf(d1), after)[d1])
    }

    @Test
    fun parseStateIsTolerant() {
        val ok = MailClient.parseState("""{"v":1,"generated":"2026-11-24T08:00:00","dates":["2026-11-10","oups","2026-11-12"],"review":["2026-11-19"]}""")
        assertNotNull(ok)
        assertEquals(setOf(LocalDate.of(2026, 11, 10), LocalDate.of(2026, 11, 12)), ok!!.savedDates)
        assertEquals(setOf(LocalDate.of(2026, 11, 19)), ok.reviewDates)
        assertEquals("2026-11-24T08:00:00", ok.generatedAt)
        // un état sans champs reste lisible ; un texte qui n'est pas du JSON est ignoré
        assertEquals(emptySet<LocalDate>(), MailClient.parseState("{}")!!.savedDates)
        assertNull(MailClient.parseState("pas du json"))
    }
}
