package fr.notivo.otenvoi

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import fr.notivo.otenvoi.data.SecureStore
import fr.notivo.otenvoi.mail.MailAccount
import fr.notivo.otenvoi.ui.CaptureScreen
import fr.notivo.otenvoi.ui.HomeScreen
import fr.notivo.otenvoi.ui.SetupScreen
import java.time.LocalDate

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Interdit les captures d'écran et masque l'aperçu dans la liste des applications : une capture
        // d'écran serait enregistrée dans la galerie, ce que cette application évite à tout prix.
        // (Désactivé seulement dans une version de développement, pour pouvoir la tester.)
        val debuggable = applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE != 0
        if (!debuggable) {
            window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)
        }
        val store = SecureStore(applicationContext)
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = Color(0xFF005FB8))) {
                AppRoot(store)
            }
        }
    }
}

private sealed interface Screen {
    data object Setup : Screen
    data object Home : Screen
    data class Capture(val date: LocalDate) : Screen
}

@Composable
private fun AppRoot(store: SecureStore) {
    var account by remember { mutableStateOf<MailAccount?>(store.load()) }
    var screen by remember { mutableStateOf<Screen>(if (account == null) Screen.Setup else Screen.Home) }
    // Après un envoi réussi, la liste se recharge pour montrer le nouvel état.
    var refreshKey by remember { mutableStateOf(0) }

    when (val current = screen) {
        Screen.Setup -> {
            BackHandler(enabled = account != null) { screen = Screen.Home }
            SetupScreen(
                existing = account,
                onSaved = { address, password ->
                    store.save(address, password)
                    account = store.load()
                    refreshKey++
                    screen = Screen.Home
                },
                onForget = {
                    store.clear()
                    account = null
                },
            )
        }
        Screen.Home -> HomeScreen(
            account = account!!,
            refreshKey = refreshKey,
            onCapture = { screen = Screen.Capture(it) },
            onSettings = { screen = Screen.Setup },
        )
        is Screen.Capture -> {
            BackHandler { screen = Screen.Home }
            CaptureScreen(
                account = account!!,
                date = current.date,
                onClose = { sent ->
                    if (sent) refreshKey++
                    screen = Screen.Home
                },
            )
        }
    }
}
