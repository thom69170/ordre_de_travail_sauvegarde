package fr.notivo.otenvoi.mail

import fr.notivo.otenvoi.Protocol
import org.json.JSONObject
import java.time.LocalDate
import java.time.ZoneId
import java.util.Date
import java.util.Properties
import javax.activation.DataHandler
import javax.mail.AuthenticationFailedException
import javax.mail.Authenticator
import javax.mail.FetchProfile
import javax.mail.Folder
import javax.mail.Message
import javax.mail.MessagingException
import javax.mail.Multipart
import javax.mail.PasswordAuthentication
import javax.mail.Session
import javax.mail.Store
import javax.mail.Transport
import javax.mail.internet.InternetAddress
import javax.mail.internet.MimeBodyPart
import javax.mail.internet.MimeMessage
import javax.mail.internet.MimeMultipart
import javax.mail.search.ComparisonTerm
import javax.mail.search.ReceivedDateTerm
import javax.mail.util.ByteArrayDataSource

/** Erreur lisible par l'utilisateur (le message est affiché tel quel). */
class MailException(message: String, cause: Throwable? = null) : Exception(message, cause)

data class MailAccount(
    val address: String,
    val password: String,
    val imapHost: String = "imap.gmail.com",
    val imapPort: Int = 993,
    val smtpHost: String = "smtp.gmail.com",
    val smtpPort: Int = 465,
    /** SSL dès la connexion (Gmail). Faux seulement pour les tests locaux. */
    val secure: Boolean = true,
)

/** Ce que le PC a publié : jours enregistrés et jours à relire, et quand. */
data class PcState(val savedDates: Set<LocalDate>, val reviewDates: Set<LocalDate>, val generatedAt: String?)

/**
 * sentAt : pour chaque jour envoyé, l'heure (millisecondes) de réception du dernier envoi ;
 * pc : état publié par le PC (null s'il n'a jamais répondu).
 */
data class MailState(val sentAt: Map<LocalDate, Long>, val pc: PcState?) {
    val sentDates: Set<LocalDate> get() = sentAt.keys
}

/**
 * Tout ce que l'application fait avec la boîte mail. Les photos arrivent ici sous forme d'octets en
 * mémoire et ne sont JAMAIS écrites sur le téléphone : pas de fichier, pas de cache, pas de galerie.
 */
class MailClient(private val account: MailAccount) {

    // ------------------------------------------------------------------ envoi

    /** Envoie les pages d'un ordre de travail (un e-mail, une pièce jointe JPEG par page). */
    fun send(date: LocalDate, pages: List<ByteArray>) {
        require(pages.isNotEmpty()) { "Aucune page à envoyer." }
        val session = smtpSession()
        val message = MimeMessage(session).apply {
            val me = InternetAddress(account.address)
            setFrom(me)
            setRecipient(Message.RecipientType.TO, me)
            setSubject(Protocol.subjectFor(date), "UTF-8")
            setHeader(Protocol.SOURCE_HEADER, Protocol.SOURCE_VALUE)
            val body = MimeBodyPart().apply {
                setText("Ordre de travail du $date : ${pages.size} page(s), envoyé depuis OT Envoi.", "UTF-8")
            }
            val parts: Multipart = MimeMultipart("mixed").apply { addBodyPart(body) }
            pages.forEachIndexed { index, jpeg ->
                parts.addBodyPart(MimeBodyPart().apply {
                    dataHandler = DataHandler(ByteArrayDataSource(jpeg, "image/jpeg"))
                    fileName = "page${index + 1}.jpg"
                    disposition = "attachment"
                })
            }
            setContent(parts)
            saveChanges()
        }
        try {
            Transport.send(message)
        } catch (e: MessagingException) {
            throw friendly(e)
        }
    }

    // ------------------------------------------------------------------ test de connexion

    /** Vérifie l'envoi (SMTP) ET la lecture (IMAP) sans rien envoyer. Retourne un message de succès. */
    fun test(): String {
        try {
            val session = smtpSession()
            val transport = session.getTransport(if (account.secure) "smtps" else "smtp")
            try {
                transport.connect(account.smtpHost, account.smtpPort, account.address, account.password)
            } finally {
                runCatching { transport.close() }
            }
            withStore { }
        } catch (e: MessagingException) {
            throw friendly(e)
        }
        return "Connexion réussie : envoi et lecture de la boîte fonctionnent."
    }

    // ------------------------------------------------------------------ état

    /**
     * Envois déjà faits (objets « OT AAAA-MM-JJ » reçus depuis [since]) et état publié par le PC.
     * Seuls les en-têtes sont lus : aucune photo n'est téléchargée.
     */
    fun fetchState(since: LocalDate): MailState {
        try {
            return withStore { store -> MailState(readSentDates(store, since), readPcState(store)) }
        } catch (e: MessagingException) {
            throw friendly(e)
        }
    }

    private fun readSentDates(store: Store, since: LocalDate): Map<LocalDate, Long> {
        val inbox = store.getFolder("INBOX")
        inbox.open(Folder.READ_ONLY)
        try {
            val start = Date.from(since.atStartOfDay(ZoneId.systemDefault()).toInstant())
            val messages = inbox.search(ReceivedDateTerm(ComparisonTerm.GE, start))
            if (messages.isEmpty()) return emptyMap()
            inbox.fetch(messages, FetchProfile().apply { add(FetchProfile.Item.ENVELOPE) })
            val latest = mutableMapOf<LocalDate, Long>()
            for (message in messages) {
                val day = Protocol.dateFromSubject(message.subject) ?: continue
                val at = (message.receivedDate ?: message.sentDate)?.time ?: 0L
                latest[day] = maxOf(latest[day] ?: 0L, at)
            }
            return latest
        } finally {
            runCatching { inbox.close(false) }
        }
    }

    private fun readPcState(store: Store): PcState? {
        val folder = store.getFolder(Protocol.STATUS_FOLDER)
        if (!folder.exists()) return null
        folder.open(Folder.READ_ONLY)
        try {
            val newest = folder.messages.maxByOrNull { (it.sentDate ?: it.receivedDate)?.time ?: 0L } ?: return null
            return parseState(textOf(newest))
        } finally {
            runCatching { folder.close(false) }
        }
    }

    // ------------------------------------------------------------------ connexions

    private fun smtpSession(): Session {
        val props = Properties()
        val protocol = if (account.secure) "smtps" else "smtp"
        props["mail.$protocol.host"] = account.smtpHost
        props["mail.$protocol.port"] = account.smtpPort.toString()
        props["mail.$protocol.auth"] = "true"
        props["mail.$protocol.connectiontimeout"] = "15000"
        props["mail.$protocol.timeout"] = "30000"
        props["mail.$protocol.writetimeout"] = "60000"
        props["mail.transport.protocol"] = protocol
        return Session.getInstance(props, object : Authenticator() {
            override fun getPasswordAuthentication() = PasswordAuthentication(account.address, account.password)
        })
    }

    /** Ouvre la boîte (IMAP), exécute [block], puis la referme quoi qu'il arrive. */
    private fun <T> withStore(block: (Store) -> T): T {
        val protocol = if (account.secure) "imaps" else "imap"
        val props = Properties()
        props["mail.$protocol.connectiontimeout"] = "15000"
        props["mail.$protocol.timeout"] = "30000"
        val store = Session.getInstance(props).getStore(protocol)
        store.connect(account.imapHost, account.imapPort, account.address, account.password)
        try {
            return block(store)
        } finally {
            runCatching { store.close() }
        }
    }

    private fun friendly(e: MessagingException): MailException {
        val root = generateSequence<Throwable>(e) { it.cause }.last()
        val text = when {
            e is AuthenticationFailedException ->
                "Adresse ou mot de passe d'application refusé. Utilise le mot de passe d'application de la " +
                    "boîte (16 lettres), pas son mot de passe habituel, et vérifie que l'accès IMAP est activé."
            root is java.net.UnknownHostException || root is java.net.ConnectException ||
                root is java.net.SocketTimeoutException ->
                "Pas de connexion à la boîte mail (réseau indisponible ?)."
            else -> "Erreur de messagerie : ${e.message ?: root.message ?: "inconnue"}"
        }
        return MailException(text, e)
    }

    companion object {
        /** Lit le JSON publié par le PC. Tolérant : un champ manquant ou une date invalide est ignoré. */
        fun parseState(json: String): PcState? {
            val obj = runCatching { JSONObject(json) }.getOrNull() ?: return null
            fun dates(key: String): Set<LocalDate> {
                val array = obj.optJSONArray(key) ?: return emptySet()
                return (0 until array.length()).mapNotNull {
                    runCatching { LocalDate.parse(array.getString(it)) }.getOrNull()
                }.toSet()
            }
            return PcState(dates("dates"), dates("review"), obj.optString("generated").ifBlank { null })
        }

        private fun textOf(message: Message): String {
            val content = message.content
            if (content is String) return content
            if (content is Multipart) {
                for (i in 0 until content.count) {
                    val part = content.getBodyPart(i)
                    if (part.isMimeType("text/plain")) return part.content as String
                }
            }
            return ""
        }
    }
}
