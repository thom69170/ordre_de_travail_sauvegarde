package fr.notivo.otenvoi

import java.time.LocalDate

/**
 * Contrat entre cette application et l'application « Ordres de travail » du PC (voir app/mail_import.py
 * côté PC). Tout passe par la boîte mail dédiée :
 *
 *  - téléphone -> boîte : un e-mail de la boîte à elle-même, objet « OT AAAA-MM-JJ », une pièce jointe
 *    JPEG par page de l'ordre de travail ;
 *  - téléphone -> boîte, jour de repos : un message sans pièce jointe, objet « REPOS AAAA-MM-JJ », ou
 *    « REPOS-ANNULE AAAA-MM-JJ » pour revenir en arrière ;
 *  - PC -> téléphone : dans le dossier [STATUS_FOLDER] de la boîte, un message texte contenant un JSON
 *    {"v":1,"generated":"…","dates":["AAAA-MM-JJ",…],"review":[…],"rest":[…]} : les jours dont l'OT est
 *    enregistré, ceux qui attendent une relecture sur le PC, et les jours de repos notés.
 */
object Protocol {
    const val STATUS_FOLDER = "OT-etat"
    const val SOURCE_HEADER = "X-OT-Source"
    const val SOURCE_VALUE = "android"

    private val SUBJECT = Regex("""^OT (\d{4}-\d{2}-\d{2})\b""")

    private val REST_SUBJECT = Regex("""^REPOS(-ANNULE)? (\d{4}-\d{2}-\d{2})\b""")

    fun subjectFor(date: LocalDate): String = "OT $date"

    fun restSubjectFor(date: LocalDate, rest: Boolean): String = (if (rest) "REPOS " else "REPOS-ANNULE ") + date

    /** (jour, true pour un repos / false pour son annulation), ou null si ce n'est pas un message de repos. */
    fun restFromSubject(subject: String?): Pair<LocalDate, Boolean>? {
        val match = REST_SUBJECT.find(subject?.trim().orEmpty()) ?: return null
        val day = runCatching { LocalDate.parse(match.groupValues[2]) }.getOrNull() ?: return null
        return day to match.groupValues[1].isEmpty()
    }

    /** Jour d'un objet « OT 2026-11-24 », ou null si l'objet n'est pas celui d'un envoi de l'application. */
    fun dateFromSubject(subject: String?): LocalDate? {
        val match = SUBJECT.find(subject?.trim().orEmpty()) ?: return null
        return runCatching { LocalDate.parse(match.groupValues[1]) }.getOrNull()
    }
}
