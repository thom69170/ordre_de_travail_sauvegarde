package fr.notivo.otenvoi.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import fr.notivo.otenvoi.mail.DayState
import fr.notivo.otenvoi.mail.DayStatus
import fr.notivo.otenvoi.mail.MailAccount
import fr.notivo.otenvoi.mail.MailClient
import fr.notivo.otenvoi.mail.MailState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

private const val PAST_DAYS = 30
/** Les OT sont publiés quelques jours à l'avance : on peut aussi envoyer jusqu'à J+7. */
private const val FUTURE_DAYS = 7
private val DAY_FORMAT = DateTimeFormatter.ofPattern("EEEE d MMMM", Locale.FRENCH)

fun dayLabel(date: LocalDate): String = date.format(DAY_FORMAT).replaceFirstChar { it.uppercase() }

/** « aujourd'hui », « demain »… pour les jours proches. */
fun relativeTag(day: LocalDate, today: LocalDate): String? = when (day.toEpochDay() - today.toEpochDay()) {
    0L -> "aujourd'hui"
    1L -> "demain"
    -1L -> "hier"
    in 2L..FUTURE_DAYS.toLong() -> "dans ${day.toEpochDay() - today.toEpochDay()} jours"
    else -> null
}

/** Liste des derniers jours avec l'état de chaque ordre de travail, et le bouton pour le photographier. */
@Composable
fun HomeScreen(
    account: MailAccount,
    refreshKey: Int,
    onCapture: (LocalDate) -> Unit,
    onSettings: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val today = remember { LocalDate.now() }
    // De J+7 (en haut) jusqu'à 30 jours en arrière.
    val days = remember(today) { (-FUTURE_DAYS until PAST_DAYS).map { today.minusDays(it.toLong()) } }
    // La liste s'ouvre sur aujourd'hui, avec deux jours à venir juste au-dessus ; le reste se découvre en remontant.
    val listState = rememberLazyListState(initialFirstVisibleItemIndex = FUTURE_DAYS - 2)
    var state by remember { mutableStateOf<MailState?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var confirmResend by remember { mutableStateOf<LocalDate?>(null) }

    fun refresh() {
        loading = true; error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { MailClient(account).fetchState(today.minusDays(PAST_DAYS.toLong() + 5)) }
            }
            loading = false
            result.onSuccess { state = it }.onFailure { error = it.message ?: "Impossible de lire la boîte mail." }
        }
    }
    LaunchedEffect(refreshKey, account) { refresh() }

    val statuses = DayStatus.merge(days, state)

    Column(modifier = Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(horizontal = 16.dp)) {
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Mes ordres de travail", fontSize = 22.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            TextButton(onClick = { refresh() }, enabled = !loading) { Text("Actualiser") }
            TextButton(onClick = onSettings) { Text("Réglages") }
        }
        Card(
            colors = CardDefaults.cardColors(containerColor = Color(0xFFE8F1FB)),
            modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
        ) {
            Text(
                "Aucune photo n'est gardée sur ce téléphone : elles partent directement dans la boîte mail.",
                modifier = Modifier.padding(12.dp), fontSize = 13.sp,
            )
        }
        when {
            loading -> Text("Actualisation…", color = Color.Gray, fontSize = 13.sp)
            error != null -> Text(error!!, color = Color(0xFFC42B1C), fontSize = 13.sp)
            state?.pc == null -> Text(
                "Le PC n'a pas encore indiqué quels OT il a enregistrés (PC éteint, ou application du PC à mettre à jour). " +
                    "Les jours envoyés apparaissent « en attente ».",
                color = Color(0xFF8A5300), fontSize = 13.sp,
            )
            else -> Text(
                "État du PC : " + (state?.pc?.generatedAt?.take(16)?.replace("T", " à ") ?: "inconnu"),
                color = Color.Gray, fontSize = 13.sp,
            )
        }
        Spacer(Modifier.height(6.dp))
        LazyColumn(state = listState, verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxSize()) {
            items(days) { day ->
                val dayState = statuses[day] ?: DayState.NONE
                DayRow(day, relativeTag(day, today), dayState, onClick = {
                    if (dayState == DayState.SAVED) confirmResend = day else onCapture(day)
                })
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }

    confirmResend?.let { day ->
        AlertDialog(
            onDismissRequest = { confirmResend = null },
            title = { Text("Déjà enregistré") },
            text = { Text("L'OT du ${dayLabel(day).lowercase()} est déjà enregistré sur le PC. Le renvoyer quand même ?") },
            confirmButton = { TextButton(onClick = { confirmResend = null; onCapture(day) }) { Text("Renvoyer") } },
            dismissButton = { TextButton(onClick = { confirmResend = null }) { Text("Annuler") } },
        )
    }
}

@Composable
private fun DayRow(day: LocalDate, tag: String?, state: DayState, onClick: () -> Unit) {
    val (text, color) = when (state) {
        DayState.SAVED -> "✓ Enregistré sur le PC" to Color(0xFF0F7B0F)
        DayState.REVIEW -> "⚠ À relire sur le PC" to Color(0xFF8A5300)
        DayState.PENDING -> "⏳ Envoyé, en attente du PC" to Color(0xFF005FB8)
        DayState.MISSING -> "⚠ Envoyé, mais pas trouvé sur le PC (date différente de celle de l'OT ?)" to Color(0xFFC42B1C)
        DayState.NONE -> "Rien d'envoyé" to Color.Gray
    }
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(modifier = Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text(dayLabel(day), fontWeight = FontWeight.SemiBold)
                Text(text, color = color, fontSize = 13.sp)
                if (tag != null) Text(tag.replaceFirstChar { it.uppercase() }, color = Color.Gray, fontSize = 12.sp)
            }
            if (state == DayState.NONE) {
                Button(onClick = onClick) { Text("Photographier") }
            } else {
                OutlinedButton(onClick = onClick) { Text("Renvoyer") }
            }
        }
    }
}
