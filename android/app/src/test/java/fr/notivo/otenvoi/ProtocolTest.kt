package fr.notivo.otenvoi

import fr.notivo.otenvoi.mail.DayState
import fr.notivo.otenvoi.mail.DayStatus
import fr.notivo.otenvoi.mail.MailClient
import fr.notivo.otenvoi.mail.MailState
import fr.notivo.otenvoi.mail.PcState
import fr.notivo.otenvoi.mail.RestMark
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
    fun restSubjectRoundTrip() {
        assertEquals("REPOS 2026-11-24", Protocol.restSubjectFor(d1, true))
        assertEquals("REPOS-ANNULE 2026-11-24", Protocol.restSubjectFor(d1, false))
        assertEquals(d1 to true, Protocol.restFromSubject("REPOS 2026-11-24"))
        assertEquals(d1 to false, Protocol.restFromSubject(" REPOS-ANNULE 2026-11-24 "))
        assertNull(Protocol.restFromSubject("OT 2026-11-24"))
        assertNull(Protocol.restFromSubject("REPOS 2026-13-45"))
        assertNull(Protocol.dateFromSubject("REPOS 2026-11-24")) // un repos n'est pas un envoi d'OT
    }

    private fun rest(
        sent: String? = null,
        mark: Pair<Boolean, String>? = null,
        pcRest: Boolean? = false, // null : PC trop ancien ; ou pas d'état du tout si generated == null
        generated: String? = "2026-11-24T08:00:00",
        saved: Boolean = false,
        review: Boolean = false,
    ): DayState {
        val pc = generated?.let {
            PcState(
                if (saved) setOf(d1) else emptySet(), if (review) setOf(d1) else emptySet(), it,
                pcRest?.let { has -> if (has) setOf(d1) else emptySet() },
            )
        }
        val state = MailState(
            sentAt = sent?.let { mapOf(d1 to millis(it)) } ?: emptyMap(),
            pc = pc,
            restMarks = mark?.let { mapOf(d1 to RestMark(it.first, millis(it.second))) } ?: emptyMap(),
        )
        return DayStatus.merge(listOf(d1), state).getValue(d1)
    }

    @Test
    fun restIsPendingUntilThePcConfirms() {
        assertEquals(DayState.REST_PENDING, rest(mark = true to "2026-11-24T09:00:00"))
        assertEquals(DayState.REST_PENDING, rest(mark = true to "2026-11-24T09:00:00", generated = null))
        assertEquals(DayState.REST, rest(mark = true to "2026-11-24T07:59:00", pcRest = true))
        assertEquals(DayState.REST, rest(pcRest = true)) // noté il y a longtemps : seul le PC le sait
        // PC pas encore mis à jour (il ne publie pas les repos) : on reste en attente
        assertEquals(DayState.REST_PENDING, rest(mark = true to "2026-11-24T06:00:00", pcRest = null))
        // retiré sur le PC bien après l'annonce : le PC fait foi
        assertEquals(DayState.NONE, rest(mark = true to "2026-11-24T06:00:00", pcRest = false))
    }

    @Test
    fun cancelledRestDisappearsAtOnce() {
        assertEquals(DayState.NONE, rest(mark = false to "2026-11-24T09:00:00", pcRest = true))
        assertEquals(DayState.NONE, rest(mark = false to "2026-11-24T07:59:00", pcRest = false))
        // le PC a répondu longtemps après et signale encore le repos (renoté depuis) : il fait foi
        assertEquals(DayState.REST, rest(mark = false to "2026-11-24T06:00:00", pcRest = true))
    }

    @Test
    fun anOtWinsOverRest() {
        assertEquals(DayState.SAVED, rest(mark = true to "2026-11-24T09:00:00", saved = true))
        // OT envoyé après le repos : jour travaillé finalement
        assertEquals(DayState.PENDING, rest(sent = "2026-11-24T09:30:00", mark = true to "2026-11-24T09:00:00", pcRest = true))
        assertEquals(DayState.REVIEW, rest(sent = "2026-11-24T07:00:00", mark = true to "2026-11-24T06:00:00", pcRest = true, review = true))
        // repos annoncé après un envoi resté sans suite
        assertEquals(DayState.REST_PENDING, rest(sent = "2026-11-24T08:30:00", mark = true to "2026-11-24T09:00:00"))
    }

    @Test
    fun parseStateReadsRestDays() {
        assertEquals(setOf(d1), MailClient.parseState("""{"dates":[],"rest":["2026-11-24"]}""")!!.restDates)
        assertEquals(emptySet<LocalDate>(), MailClient.parseState("""{"rest":[]}""")!!.restDates)
        assertNull(MailClient.parseState("""{"dates":[]}""")!!.restDates) // ancien PC
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
