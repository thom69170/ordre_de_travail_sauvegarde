package fr.notivo.otenvoi

import java.time.LocalDate

/**
 * Contrat entre cette application et l'application « Ordres de travail » du PC (voir app/mail_import.py
 * côté PC). Tout passe par la boîte mail dédiée :
 *
 *  - téléphone -> boîte : un e-mail de la boîte à elle-même, objet « OT AAAA-MM-JJ », une pièce jointe
 *    JPEG par page de l'ordre de travail ;
 *  - PC -> téléphone : dans le dossier [STATUS_FOLDER] de la boîte, un message texte contenant un JSON
 *    {"v":1,"generated":"…","dates":["AAAA-MM-JJ",…],"review":["AAAA-MM-JJ",…]} : les jours dont l'OT est
 *    enregistré, et ceux qui attendent une relecture sur le PC.
 */
object Protocol {
    const val STATUS_FOLDER = "OT-etat"
    const val SOURCE_HEADER = "X-OT-Source"
    const val SOURCE_VALUE = "android"

    private val SUBJECT = Regex("""^OT (\d{4}-\d{2}-\d{2})\b""")

    fun subjectFor(date: LocalDate): String = "OT $date"

    /** Jour d'un objet « OT 2026-11-24 », ou null si l'objet n'est pas celui d'un envoi de l'application. */
    fun dateFromSubject(subject: String?): LocalDate? {
        val match = SUBJECT.find(subject?.trim().orEmpty()) ?: return null
        return runCatching { LocalDate.parse(match.groupValues[1]) }.getOrNull()
    }
}
