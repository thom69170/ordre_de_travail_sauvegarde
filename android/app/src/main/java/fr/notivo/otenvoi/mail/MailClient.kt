package fr.notivo.otenvoi.mail

import fr.notivo.otenvoi.Protocol
import org.json.JSONObject
import java.time.LocalDate
import java.time.ZoneId
import java.util.Date
import java.util.Properties
import javax.activation.CommandMap
import javax.activation.DataHandler
import javax.activation.MailcapCommandMap
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
    /** Accepte n'importe quel certificat : UNIQUEMENT pour les faux serveurs des tests (certificat auto-signé). */
    val trustAllCertificates: Boolean = false,
)

/**
 * Ce que le PC a publié : jours enregistrés, jours à relire, et quand. [restDates] : jours de repos notés
 * sur le PC (null si l'application du PC est trop ancienne pour les connaître).
 */
data class PcState(
    val savedDates: Set<LocalDate>,
    val reviewDates: Set<LocalDate>,
    val generatedAt: String?,
    val restDates: Set<LocalDate>? = null,
)

/** Dernier message de repos envoyé pour un jour : [rest] vrai = en repos, faux = repos annulé. */
data class RestMark(val rest: Boolean, val at: Long)

/**
 * sentAt : pour chaque jour envoyé, l'heure (millisecondes) de réception du dernier envoi ;
 * pc : état publié par le PC (null s'il n'a jamais répondu) ;
 * restMarks : dernier message de repos de chaque jour.
 */
data class MailState(
    val sentAt: Map<LocalDate, Long>,
    val pc: PcState?,
    val restMarks: Map<LocalDate, RestMark> = emptyMap(),
) {
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
            withSmtp(session) { transport -> transport.sendMessage(message, message.allRecipients) }
        } catch (e: MessagingException) {
            throw friendly(e)
        }
    }

    /** Annonce au PC un jour de repos ([rest] vrai) ou annule cette annonce. */
    fun sendRest(date: LocalDate, rest: Boolean) {
        val session = smtpSession()
        val message = MimeMessage(session).apply {
            val me = InternetAddress(account.address)
            setFrom(me)
            setRecipient(Message.RecipientType.TO, me)
            setSubject(Protocol.restSubjectFor(date, rest), "UTF-8")
            setHeader(Protocol.SOURCE_HEADER, Protocol.SOURCE_VALUE)
            val what = if (rest) "Jour de repos" else "Repos annulé"
            setText("$what le $date, envoyé depuis OT Envoi.", "UTF-8")
            saveChanges()
        }
        try {
            withSmtp(session) { transport -> transport.sendMessage(message, message.allRecipients) }
        } catch (e: MessagingException) {
            throw friendly(e)
        }
    }

    /**
     * Ouvre la connexion SMTP avec l'hôte et le port EXPLICITES, exécute [block], puis la ferme. (Transport.send()
     * cherche ses réglages sous le protocole « smtp » : avec une connexion chiffrée déclarée sous « smtps »,
     * il retombait sur localhost:25.)
     */
    private fun <T> withSmtp(session: Session, block: (Transport) -> T): T {
        val transport = session.getTransport("smtp")
        transport.connect(account.smtpHost, account.smtpPort, account.address, account.password)
        try {
            return block(transport)
        } finally {
            runCatching { transport.close() }
        }
    }

    // ------------------------------------------------------------------ test de connexion

    /** Vérifie l'envoi (SMTP) ET la lecture (IMAP) sans rien envoyer. Retourne un message de succès. */
    fun test(): String {
        try {
            withSmtp(smtpSession()) { }
            withStore { }
        } catch (e: MessagingException) {
            throw friendly(e)
        }
        return "Connexion réussie : envoi et lecture de la boîte fonctionnent."
    }

    // ------------------------------------------------------------------ état

    /**
     * Envois et repos déjà annoncés (messages reçus depuis [since]) et état publié par le PC.
     * Seuls les en-têtes sont lus : aucune photo n'est téléchargée.
     */
    fun fetchState(since: LocalDate): MailState {
        try {
            return withStore { store -> readInbox(store, since).copy(pc = readPcState(store)) }
        } catch (e: MessagingException) {
            throw friendly(e)
        }
    }

    private fun readInbox(store: Store, since: LocalDate): MailState {
        val inbox = store.getFolder("INBOX")
        inbox.open(Folder.READ_ONLY)
        try {
            val start = Date.from(since.atStartOfDay(ZoneId.systemDefault()).toInstant())
            val messages = inbox.search(ReceivedDateTerm(ComparisonTerm.GE, start))
            if (messages.isEmpty()) return MailState(emptyMap(), null)
            inbox.fetch(messages, FetchProfile().apply { add(FetchProfile.Item.ENVELOPE) })
            val latest = mutableMapOf<LocalDate, Long>()
            val marks = mutableMapOf<LocalDate, RestMark>()
            // Dans l'ordre d'arrivée : à la même seconde, le message le plus récent l'emporte.
            for (message in messages) {
                val subject = message.subject
                val at = (message.receivedDate ?: message.sentDate)?.time ?: 0L
                Protocol.dateFromSubject(subject)?.let { day -> latest[day] = maxOf(latest[day] ?: 0L, at) }
                Protocol.restFromSubject(subject)?.let { (day, rest) ->
                    if (at >= (marks[day]?.at ?: 0L)) marks[day] = RestMark(rest, at)
                }
            }
            return MailState(latest, null, marks)
        } finally {
            runCatching { inbox.close(false) }
        }
    }

    private fun readPcState(store: Store): PcState? {
        val folder = store.getFolder(Protocol.STATUS_FOLDER)
        trace("dossier ${Protocol.STATUS_FOLDER} existe=${folder.exists()}")
        if (!folder.exists()) return null
        folder.open(Folder.READ_ONLY)
        try {
            val all = folder.messages
            trace("messages dans le dossier = ${all.size}")
            val newest = all.maxByOrNull { (it.sentDate ?: it.receivedDate)?.time ?: 0L } ?: return null
            val content = newest.content
            trace("contenu : classe=${content?.javaClass?.name} type=${newest.contentType}")
            val text = textOf(newest)
            trace("texte lu : ${text.length} caracteres")
            return parseState(text).also { trace("etat lu = ${it != null}") }
        } finally {
            runCatching { folder.close(false) }
        }
    }

    // ------------------------------------------------------------------ connexions

    private fun smtpSession(): Session {
        val props = Properties()
        props["mail.smtp.host"] = account.smtpHost
        props["mail.smtp.port"] = account.smtpPort.toString()
        props["mail.smtp.auth"] = "true"
        props["mail.smtp.connectiontimeout"] = "15000"
        props["mail.smtp.timeout"] = "30000"
        props["mail.smtp.writetimeout"] = "60000"
        if (account.secure) props["mail.smtp.ssl.enable"] = "true"
        if (account.trustAllCertificates) props["mail.smtp.ssl.trust"] = "*"
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
        if (account.trustAllCertificates) props["mail.$protocol.ssl.trust"] = "*"
        val store = Session.getInstance(props).getStore(protocol)
        store.connect(account.imapHost, account.imapPort, account.address, account.password)
        try {
            return block(store)
        } finally {
            runCatching { store.close() }
        }
    }

    /** Trace technique (aucune donnée personnelle) : visible avec « adb logcat -s OTENVOI ». */
    private fun trace(message: String) {
        runCatching { android.util.Log.d("OTENVOI", message) }
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
        init {
            // Sur Android, les fichiers META-INF/mailcap de la bibliothèque ne sont pas chargés : sans cette
            // déclaration, getContent() renvoie un flux brut au lieu du texte et l'envoi d'un message à pièces
            // jointes échoue (« no object DCH for MIME type multipart/mixed »). Déclaré en dur, ça marche partout.
            val mailcap = MailcapCommandMap()
            mailcap.addMailcap("text/plain;; x-java-content-handler=com.sun.mail.handlers.text_plain")
            mailcap.addMailcap("text/html;; x-java-content-handler=com.sun.mail.handlers.text_html")
            mailcap.addMailcap("text/xml;; x-java-content-handler=com.sun.mail.handlers.text_xml")
            mailcap.addMailcap("multipart/*;; x-java-content-handler=com.sun.mail.handlers.multipart_mixed")
            mailcap.addMailcap("message/rfc822;; x-java-content-handler=com.sun.mail.handlers.message_rfc822")
            CommandMap.setDefaultCommandMap(mailcap)
        }

        /** Lit le JSON publié par le PC. Tolérant : un champ manquant ou une date invalide est ignoré. */
        fun parseState(json: String): PcState? {
            val obj = runCatching { JSONObject(json) }.getOrNull() ?: return null
            fun dates(key: String): Set<LocalDate> {
                val array = obj.optJSONArray(key) ?: return emptySet()
                return (0 until array.length()).mapNotNull {
                    runCatching { LocalDate.parse(array.getString(it)) }.getOrNull()
                }.toSet()
            }
            return PcState(
                dates("dates"), dates("review"), obj.optString("generated").ifBlank { null },
                if (obj.has("rest")) dates("rest") else null,
            )
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
