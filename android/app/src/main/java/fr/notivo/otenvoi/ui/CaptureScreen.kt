package fr.notivo.otenvoi.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import fr.notivo.otenvoi.camera.PageEncoder
import fr.notivo.otenvoi.mail.MailAccount
import fr.notivo.otenvoi.mail.MailClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.util.concurrent.Executors

/** Pages au maximum par envoi (un OT en compte une ou deux ; la marge évite un e-mail énorme). */
private const val MAX_PAGES = 6

/**
 * Appareil photo intégré. Chaque page est gardée EN MÉMOIRE (octets JPEG), jamais écrite dans un fichier ni
 * dans la galerie ; elle disparaît dès l'envoi réussi ou en quittant l'écran.
 */
@Composable
fun CaptureScreen(account: MailAccount, date: LocalDate, onClose: (sent: Boolean) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var granted by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
    }
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    LaunchedEffect(Unit) { if (!granted) permissionLauncher.launch(Manifest.permission.CAMERA) }

    val pages = remember { mutableStateListOf<ByteArray>() }
    var sending by remember { mutableStateOf(false) }
    var capturing by remember { mutableStateOf(false) }
    var torch by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var camera by remember { mutableStateOf<Camera?>(null) }

    // Photos déjà présentes dans la galerie : le sélecteur du système ne donne accès qu'à celles qu'on choisit
    // (aucune permission de stockage). Elles sont lues en mémoire ; rien n'est copié ni enregistré.
    val galleryLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.PickMultipleVisualMedia(MAX_PAGES),
    ) { uris ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        error = null
        scope.launch {
            val loaded = withContext(Dispatchers.IO) {
                uris.map { uri ->
                    runCatching {
                        val raw = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
                            ?: throw IllegalStateException("fichier inaccessible")
                        PageEncoder.encode(raw, PageEncoder.exifRotation(raw))
                    }
                }
            }
            for (result in loaded) {
                if (pages.size >= MAX_PAGES) break
                result.onSuccess { pages.add(it) }.onFailure { error = "Photo de la galerie illisible : ${it.message}" }
            }
        }
    }

    val previewView = remember { PreviewView(context).apply { scaleType = PreviewView.ScaleType.FIT_CENTER } }
    val imageCapture = remember { ImageCapture.Builder().setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY).build() }
    val executor = remember { Executors.newSingleThreadExecutor() }
    val mainHandler = remember { Handler(Looper.getMainLooper()) }

    DisposableEffect(Unit) {
        onDispose {
            executor.shutdown()
            pages.clear() // les photos non envoyées sont oubliées en quittant l'écran
            runCatching { ProcessCameraProvider.getInstance(context).get().unbindAll() }
        }
    }

    LaunchedEffect(granted) {
        if (!granted) return@LaunchedEffect
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            val provider = future.get()
            val preview = Preview.Builder().build().also { it.setSurfaceProvider(previewView.surfaceProvider) }
            provider.unbindAll()
            camera = runCatching {
                provider.bindToLifecycle(context as LifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, imageCapture)
            }.getOrElse { error = "Appareil photo indisponible : ${it.message}"; null }
        }, ContextCompat.getMainExecutor(context))
    }

    fun takePhoto() {
        if (capturing || sending) return
        if (pages.size >= MAX_PAGES) { error = "$MAX_PAGES pages au maximum par envoi."; return }
        capturing = true; error = null
        imageCapture.takePicture(executor, object : ImageCapture.OnImageCapturedCallback() {
            override fun onCaptureSuccess(image: ImageProxy) {
                val page = runCatching {
                    val buffer = image.planes[0].buffer
                    val raw = ByteArray(buffer.remaining()).also { buffer.get(it) }
                    PageEncoder.encode(raw, image.imageInfo.rotationDegrees)
                }
                image.close()
                mainHandler.post {
                    capturing = false
                    page.onSuccess { pages.add(it) }.onFailure { error = "Photo non prise : ${it.message}" }
                }
            }

            override fun onError(exception: ImageCaptureException) {
                mainHandler.post { capturing = false; error = "Photo non prise : ${exception.message}" }
            }
        })
    }

    fun send() {
        if (pages.isEmpty() || sending) return
        sending = true; error = null
        val snapshot = pages.toList()
        scope.launch {
            val result = withContext(Dispatchers.IO) { runCatching { MailClient(account).send(date, snapshot) } }
            sending = false
            result.onSuccess { pages.clear(); onClose(true) }.onFailure { error = it.message ?: "Envoi impossible." }
        }
    }

    Column(modifier = Modifier.fillMaxSize().background(Color.Black).statusBarsPadding().navigationBarsPadding()) {
        Row(modifier = Modifier.fillMaxWidth().padding(start = 16.dp, top = 8.dp, end = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text(dayLabel(date), color = Color.White, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                Text("Chaque page entière, à plat, bien éclairée", color = Color(0xFFCCCCCC), fontSize = 12.sp)
            }
            TextButton(onClick = { onClose(false) }) { Text("Annuler", color = Color.White) }
        }

        Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
            if (granted) {
                AndroidView(factory = { previewView }, modifier = Modifier.fillMaxSize())
            } else {
                Text(
                    "L'accès à l'appareil photo est nécessaire pour photographier l'ordre de travail.",
                    color = Color.White, modifier = Modifier.align(Alignment.Center).padding(24.dp),
                )
            }
        }

        if (pages.isNotEmpty()) {
            LazyRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                itemsIndexed(pages) { index, bytes ->
                    val bitmap = remember(bytes) { PageEncoder.thumbnail(bytes)?.asImageBitmap() }
                    Box {
                        if (bitmap != null) {
                            Image(bitmap, "Page ${index + 1}", contentScale = ContentScale.Crop, modifier = Modifier.size(72.dp, 96.dp))
                        }
                        Text("✕", color = Color.White, fontWeight = FontWeight.Bold,
                            modifier = Modifier.align(Alignment.TopEnd).background(Color(0x99000000))
                                .clickable { pages.removeAt(index) }.padding(6.dp))
                    }
                }
            }
        }

        error?.let { Text(it, color = Color(0xFFFFB4A9), modifier = Modifier.padding(horizontal = 16.dp), fontSize = 13.sp) }

        Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = { torch = !torch; camera?.cameraControl?.enableTorch(torch) }, enabled = granted) {
                    Text(if (torch) "Lampe ✓" else "Lampe", color = Color.White)
                }
                OutlinedButton(
                    onClick = { galleryLauncher.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
                    enabled = !sending && pages.size < MAX_PAGES,
                ) { Text("Choisir dans la galerie", color = Color.White) }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                Button(onClick = { takePhoto() }, enabled = granted && !capturing && !sending, modifier = Modifier.weight(1f).height(52.dp)) {
                    Text(if (capturing) "…" else "Photographier")
                }
                Button(onClick = { send() }, enabled = pages.isNotEmpty() && !sending, modifier = Modifier.height(52.dp)) {
                    Text(if (sending) "Envoi…" else "Envoyer (${pages.size})")
                }
            }
        }
    }
}
