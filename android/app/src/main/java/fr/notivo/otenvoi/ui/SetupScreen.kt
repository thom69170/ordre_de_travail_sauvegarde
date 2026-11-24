package fr.notivo.otenvoi.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import fr.notivo.otenvoi.mail.MailAccount
import fr.notivo.otenvoi.mail.MailClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Réglages : adresse de la boîte dédiée et son mot de passe d'application (saisis une seule fois). */
@Composable
fun SetupScreen(
    existing: MailAccount?,
    onSaved: (address: String, password: String) -> Unit,
    onForget: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var address by remember { mutableStateOf(existing?.address.orEmpty()) }
    var password by remember { mutableStateOf("") }
    var showPassword by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<Pair<Boolean, String>?>(null) }

    // Mot de passe laissé vide alors qu'un compte existe : on garde celui déjà enregistré.
    fun effective(): MailAccount? {
        val pwd = password.ifBlank { existing?.password.orEmpty() }
        return if (address.isBlank() || pwd.isBlank()) null else MailAccount(address.trim(), pwd.replace(" ", ""))
    }

    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Spacer(Modifier.height(24.dp))
        Text("OT Envoi", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
        Text(
            "Envoie tes ordres de travail en photo dans la boîte mail dédiée. Les photos ne sont jamais " +
                "enregistrées sur ce téléphone : elles partent directement par e-mail.",
        )
        Text("Boîte mail dédiée", fontWeight = FontWeight.SemiBold)
        OutlinedTextField(
            value = address, onValueChange = { address = it }, singleLine = true,
            label = { Text("Adresse (ex. ma.boite@gmail.com)") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = password, onValueChange = { password = it }, singleLine = true,
            label = { Text(if (existing != null) "Mot de passe d'application (laisser vide = inchangé)" else "Mot de passe d'application") },
            visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            modifier = Modifier.fillMaxWidth(),
        )
        TextButton(onClick = { showPassword = !showPassword }) { Text(if (showPassword) "Masquer" else "Afficher") }
        Text(
            "C'est le mot de passe d'application de 16 lettres créé sur myaccount.google.com/apppasswords " +
                "(pas le mot de passe habituel de la boîte). Il est stocké chiffré sur ce téléphone.",
            fontSize = 13.sp, color = Color.Gray,
        )

        message?.let { (ok, text) ->
            Text(text, color = if (ok) Color(0xFF0F7B0F) else Color(0xFFC42B1C))
        }

        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(enabled = !busy && effective() != null, onClick = {
                val account = effective() ?: return@OutlinedButton
                busy = true; message = null
                scope.launch {
                    val result = withContext(Dispatchers.IO) { runCatching { MailClient(account).test() } }
                    busy = false
                    message = result.fold({ true to it }, { false to (it.message ?: "Échec de la connexion.") })
                }
            }) { Text(if (busy) "Test…" else "Tester") }
            Button(enabled = !busy && effective() != null, onClick = {
                val account = effective() ?: return@Button
                onSaved(account.address, account.password)
            }) { Text("Enregistrer") }
        }
        if (existing != null) {
            TextButton(onClick = onForget) { Text("Oublier cette boîte sur ce téléphone", color = Color(0xFFC42B1C)) }
        }
    }
}
