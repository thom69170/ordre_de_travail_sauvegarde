package fr.notivo.otenvoi

import com.icegreen.greenmail.configuration.GreenMailConfiguration
import com.icegreen.greenmail.util.GreenMail
import com.icegreen.greenmail.util.ServerSetupTest
import fr.notivo.otenvoi.mail.MailAccount
import fr.notivo.otenvoi.mail.MailClient
import fr.notivo.otenvoi.mail.MailException
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.io.ByteArrayOutputStream
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

/** Envoi et lecture de l'état contre de faux serveurs SMTP/IMAP locaux : aucune vraie boîte n'est touchée. */
class MailClientTest {
    private val address = "boite@test.local"
    private lateinit var green: GreenMail

    @Before
    fun start() {
        green = GreenMail(ServerSetupTest.SMTP_IMAP)
            .withConfiguration(GreenMailConfiguration.aConfig().withUser(address, address, "secret"))
        green.start()
    }

    @After
    fun stop() {
        green.stop()
    }

    private fun account(password: String = "secret") = MailAccount(
        address = address, password = password,
        imapHost = "127.0.0.1", imapPort = ServerSetupTest.IMAP.port,
        smtpHost = "127.0.0.1", smtpPort = ServerSetupTest.SMTP.port, secure = false,
    )

    /** Une « photo » JPEG : l'image d'exemple fournie par OT_SAMPLE_JPEG si elle existe, sinon une image générée. */
    private fun sampleJpeg(seed: Int): ByteArray {
        System.getenv("OT_SAMPLE_JPEG")?.let { path -> File(path).takeIf { it.exists() }?.let { return it.readBytes() } }
        val image = java.awt.image.BufferedImage(900, 1200, java.awt.image.BufferedImage.TYPE_INT_RGB)
        val g = image.createGraphics()
        g.color = java.awt.Color.WHITE; g.fillRect(0, 0, 900, 1200)
        g.color = java.awt.Color.BLACK; g.drawString("OT test page $seed", 60, 80)
        g.dispose()
        val out = ByteArrayOutputStream()
        javax.imageio.ImageIO.write(image, "jpg", out)
        return out.toByteArray()
    }

    @Test
    fun sendDeliversEveryPageAsAnAttachment() {
        val pages = listOf(sampleJpeg(1), sampleJpeg(2) + byteArrayOf(0, 1, 2)) // deux pages différentes
        MailClient(account()).send(LocalDate.of(2026, 11, 24), pages)

        assertTrue("le message doit arriver", green.waitForIncomingEmail(5000, 1))
        val message = green.receivedMessages.single() as MimeMessage
        assertEquals("OT 2026-11-24", message.subject)
        assertEquals(address, (message.from.single() as InternetAddress).address)
        assertEquals(address, (message.allRecipients.single() as InternetAddress).address)
        assertEquals("android", message.getHeader("X-OT-Source")?.firstOrNull())

        val parts = message.content as Multipart
        val attachments = (0 until parts.count).map { parts.getBodyPart(it) as MimeBodyPart }.filter { it.fileName != null }
        assertEquals(listOf("page1.jpg", "page2.jpg"), attachments.map { it.fileName })
        assertTrue(attachments.all { it.isMimeType("image/jpeg") })
        // octet pour octet : ce qui part est exactement ce qui a été photographié
        assertArrayEquals(pages[0], attachments[0].inputStream.readBytes())
        assertArrayEquals(pages[1], attachments[1].inputStream.readBytes())

        // message d'exemple pour vérifier, côté PC, que l'application de bureau sait le lire
        val target = File("build/test-artifacts/ot_android_sample.eml").apply { parentFile.mkdirs() }
        FileOutputStream(target).use { message.writeTo(it) }
        assertTrue(target.length() > pages.sumOf { it.size })
    }

    @Test
    fun sendRequiresAtLeastOnePage() {
        try {
            MailClient(account()).send(LocalDate.of(2026, 11, 24), emptyList())
            fail("un envoi sans page doit être refusé")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message!!.contains("Aucune page"))
        }
    }

    @Test
    fun fetchStateListsSentDaysWithoutDownloadingPhotos() {
        val client = MailClient(account())
        client.send(LocalDate.of(2026, 11, 24), listOf(sampleJpeg(1)))
        client.send(LocalDate.of(2026, 11, 20), listOf(sampleJpeg(2)))
        // un message étranger (autre objet) est ignoré
        MailClient(account()).also {
            val session = Session.getInstance(Properties())
            val other = MimeMessage(session).apply {
                setFrom(InternetAddress("autre@test.local")); setRecipient(javax.mail.Message.RecipientType.TO, InternetAddress(address))
                subject = "Bonjour"; setText("coucou")
            }
            com.icegreen.greenmail.util.GreenMailUtil.sendTextEmail(address, "autre@test.local", "Bonjour", "coucou", ServerSetupTest.SMTP)
        }
        assertTrue(green.waitForIncomingEmail(5000, 3))

        val state = client.fetchState(LocalDate.of(2026, 11, 1))
        assertEquals(setOf(LocalDate.of(2026, 11, 24), LocalDate.of(2026, 11, 20)), state.sentDates)
        assertNull("le PC n'a rien publié", state.pc)
    }

    @Test
    fun fetchStateReadsTheStatePublishedByThePc() {
        // le PC dépose un message JSON dans le dossier OT-etat (comme app/mail_import.py : publish_state)
        val session = Session.getInstance(Properties())
        val store = session.getStore("imap").apply { connect("127.0.0.1", ServerSetupTest.IMAP.port, address, "secret") }
        val folder = store.getFolder(Protocol.STATUS_FOLDER)
        assertTrue(folder.create(Folder.HOLDS_MESSAGES))
        fun state(generated: String, vararg dates: String) = MimeMessage(session).apply {
            setFrom(InternetAddress(address)); setRecipient(javax.mail.Message.RecipientType.TO, InternetAddress(address))
            subject = "OT-ETAT"; sentDate = java.util.Date()
            setText("""{"v":1,"generated":"$generated","dates":[${dates.joinToString(",") { "\"$it\"" }}],"review":["2026-11-19"]}""", "UTF-8")
        }
        folder.open(Folder.READ_WRITE)
        folder.appendMessages(arrayOf(state("2026-11-23T08:00:00", "2026-11-10")))
        Thread.sleep(1100) // le plus récent doit gagner
        folder.appendMessages(arrayOf(state("2026-11-24T08:00:00", "2026-11-10", "2026-11-12")))
        folder.close(false); store.close()

        val pc = MailClient(account()).fetchState(LocalDate.of(2026, 11, 1)).pc
        assertNotNull(pc)
        assertEquals(setOf(LocalDate.of(2026, 11, 10), LocalDate.of(2026, 11, 12)), pc!!.savedDates)
        assertEquals(setOf(LocalDate.of(2026, 11, 19)), pc.reviewDates)
        assertEquals("2026-11-24T08:00:00", pc.generatedAt)
    }

    @Test
    fun connectionTestSucceedsAndExplainsFailures() {
        assertTrue(MailClient(account()).test().startsWith("Connexion réussie"))

        try {
            MailClient(account(password = "mauvais")).test()
            fail("un mauvais mot de passe doit être refusé")
        } catch (e: MailException) {
            assertTrue(e.message!!.contains("mot de passe d'application"))
        }

        val dead = account().copy(imapPort = 1, smtpPort = 1)
        try {
            MailClient(dead).test()
            fail("un serveur injoignable doit être signalé")
        } catch (e: MailException) {
            assertFalse(e.message.isNullOrBlank())
        }
    }
}
