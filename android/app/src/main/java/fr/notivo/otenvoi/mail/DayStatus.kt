package fr.notivo.otenvoi.mail

import java.time.LocalDate

/** État d'un jour, tel que l'application l'affiche. */
enum class DayState {
    /** Le PC a enregistré l'OT de ce jour. */
    SAVED,
    /** Le PC a lu l'OT mais attend une relecture (à faire sur le PC). */
    REVIEW,
    /** Envoyé, pas encore traité par le PC (éteint, ou application fermée). */
    PENDING,
    /** Envoyé, le PC a répondu depuis, mais n'a pas cet OT à cette date : date choisie différente de celle de l'OT ? */
    MISSING,
    /** Jour de repos noté sur le PC. */
    REST,
    /** Repos annoncé, pas encore noté par le PC. */
    REST_PENDING,
    /** Rien d'envoyé ce jour-là. */
    NONE,
}

object DayStatus {
    /** Délai laissé au PC pour lire l'envoi avant de s'étonner de ne pas le retrouver. */
    const val GRACE_MS = 15 * 60 * 1000L

    private fun generatedMillis(pc: PcState?): Long? =
        pc?.generatedAt?.let { text ->
            runCatching {
                java.time.LocalDateTime.parse(text).atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()
            }.getOrNull()
        }

    /**
     * Fusionne ce qui a été envoyé (boîte) et ce que le PC a publié. Le PC fait foi : un jour qu'il a
     * enregistré est « enregistré » même si l'envoi date de loin ; un jour qu'il signale « à relire » l'est
     * aussi ; un jour envoyé mais inconnu du PC est « en attente » - ou « pas trouvé » si le PC a publié son
     * état bien après l'envoi sans avoir cet OT (probablement une date choisie différente de celle de l'OT).
     * Pour le repos, le dernier message du téléphone vaut tant que le PC n'a pas eu le temps de le voir.
     */
    fun merge(days: List<LocalDate>, state: MailState?): Map<LocalDate, DayState> =
        days.associateWith { day -> stateOf(day, state) }

    private fun stateOf(day: LocalDate, state: MailState?): DayState {
        if (state == null) return DayState.NONE
        val pc = state.pc
        if (pc?.savedDates?.contains(day) == true) return DayState.SAVED

        val sent = state.sentAt[day]
        val generated = generatedMillis(pc)
        /** Le PC a-t-il publié son état assez longtemps après [at] pour avoir vu ce message ? */
        fun answeredSince(at: Long) = generated != null && generated > at + GRACE_MS

        var pcRest = pc?.restDates?.contains(day) == true
        val mark = state.restMarks[day]
        // Un OT envoyé après le message de repos l'emporte : finalement, ce jour-là a été travaillé.
        if (mark != null && (sent == null || mark.at >= sent)) {
            val pcHasSeenIt = pc?.restDates != null && answeredSince(mark.at)
            if (mark.rest) {
                if (pcRest) return DayState.REST
                if (!pcHasSeenIt) return DayState.REST_PENDING
            } else if (!pcHasSeenIt) {
                pcRest = false // annulation pas encore prise en compte par le PC
            }
        } else if (sent != null) {
            pcRest = false
        }
        return when {
            pc?.reviewDates?.contains(day) == true -> DayState.REVIEW
            pcRest -> DayState.REST
            sent != null && (mark == null || sent > mark.at) ->
                if (answeredSince(sent)) DayState.MISSING else DayState.PENDING
            else -> DayState.NONE
        }
    }
}
