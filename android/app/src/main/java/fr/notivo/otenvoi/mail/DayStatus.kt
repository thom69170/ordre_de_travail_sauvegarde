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
     */
    fun merge(days: List<LocalDate>, state: MailState?): Map<LocalDate, DayState> =
        days.associateWith { day ->
            when {
                state?.pc?.savedDates?.contains(day) == true -> DayState.SAVED
                state?.pc?.reviewDates?.contains(day) == true -> DayState.REVIEW
                state?.sentAt?.containsKey(day) == true -> {
                    val sent = state.sentAt.getValue(day)
                    val generated = generatedMillis(state.pc)
                    if (generated != null && generated > sent + GRACE_MS) DayState.MISSING else DayState.PENDING
                }
                else -> DayState.NONE
            }
        }
}
