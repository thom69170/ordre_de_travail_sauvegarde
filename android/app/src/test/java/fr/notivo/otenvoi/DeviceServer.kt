package fr.notivo.otenvoi

import com.icegreen.greenmail.configuration.GreenMailConfiguration
import com.icegreen.greenmail.util.GreenMail
import com.icegreen.greenmail.util.ServerSetupTest
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.io.FileOutputStream
import java.time.LocalDate
import java.util.Properties
import javax.mail.Folder
import javax.mail.Multipart
import javax.mail.Session
import javax.mail.internet.InternetAddress
import javax.mail.internet.MimeBodyPart
import javax.mail.internet.MimeMessage

/**
 * Serveur de messagerie local pour essayer l'application sur un VRAI téléphone branché en USB
 * (adb reverse tcp:3025 / tcp:3143). Ne fait rien sans DEVICE_SERVER=1.
 * Publie un état « du PC », attend un envoi de l'application, puis en sauvegarde le contenu.
 */
class DeviceServer {
    @Test
    fun serveUntilAnOtArrives() {
        assumeTrue(System.getenv("DEVICE_SERVER") == "1")
        val address = "boite@test.local"
        val green = GreenMail(ServerSetupTest.SMTP_IMAP)
            .withConfiguration(GreenMailConfiguration.aConfig().withUser(address, address, "secret"))
        green.start()
        val out = File("build/device-artifacts").apply { mkdirs() }
        try {
            // l'état que publierait le PC : 2 jours enregistrés, 1 à relire
            val today = LocalDate.now()
            val session = Session.getInstance(Properties())
            val store = session.getStore("imap").apply { connect("127.0.0.1", ServerSetupTest.IMAP.port, address, "secret") }
            val folder = store.getFolder(Protocol.STATUS_FOLDER)
            folder.create(Folder.HOLDS_MESSAGES)
            folder.open(Folder.READ_WRITE)
            folder.appendMessages(arrayOf(MimeMessage(session).apply {
                setFrom(InternetAddress(address)); setRecipient(javax.mail.Message.RecipientType.TO, InternetAddress(address))
                subject = "OT-ETAT"; sentDate = java.util.Date()
                setText(
                    """{"v":1,"generated":"${java.time.LocalDateTime.now().withNano(0)}","dates":["${today.minusDays(1)}","${today.minusDays(2)}"],"review":["${today.minusDays(3)}"]}""",
                    "UTF-8",
                )
            }))
            folder.close(false); store.close()
            File(out, "ready.txt").writeText("serveur pret ${java.time.LocalTime.now()}")

            // attend l'envoi de l'application (au plus 9 minutes)
            val deadline = System.currentTimeMillis() + 9 * 60_000
            while (System.currentTimeMillis() < deadline && green.receivedMessages.none { (it.subject ?: "").startsWith("OT ") }) {
                Thread.sleep(500)
            }
            Thread.sleep(1500)
            val message = green.receivedMessages.firstOrNull { (it.subject ?: "").startsWith("OT ") }
            if (message == null) {
                File(out, "result.txt").writeText("AUCUN ENVOI RECU")
                return
            }
            FileOutputStream(File(out, "from_device.eml")).use { message.writeTo(it) }
            val parts = message.content as Multipart
            val attachments = (0 until parts.count).map { parts.getBodyPart(it) as MimeBodyPart }.filter { it.fileName != null }
            File(out, "result.txt").writeText(
                "objet=${message.subject}\nde=${(message.from.single() as InternetAddress).address}\n" +
                    "en-tete X-OT-Source=${message.getHeader("X-OT-Source")?.firstOrNull()}\n" +
                    "pieces=" + attachments.joinToString { "${it.fileName}:${it.inputStream.readBytes().size}o:${it.contentType.substringBefore(';')}" },
            )
        } finally {
            green.stop()
        }
    }
}
