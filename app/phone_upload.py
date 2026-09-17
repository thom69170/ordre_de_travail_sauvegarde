"""Réception d'une photo/PDF envoyé depuis le téléphone, sur le même réseau Wi-Fi.

Principe : un petit serveur HTTP local (ThreadingHTTPServer) sert une page web simple
(scannée via QR code depuis le téléphone) qui permet de prendre une photo ou choisir un
fichier et l'envoyer directement en HTTP au PC — sans appli à installer sur le téléphone.

Le fichier est envoyé en corps de requête brut (pas en multipart) : c'est le téléphone
(JavaScript, fetch) qui simplifie les choses ainsi, pas le serveur.
"""
from __future__ import annotations

import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

from app.paths import phone_uploads_dir

MAX_UPLOAD_BYTES = 30 * 1024 * 1024  # 30 Mo, largement suffisant pour une photo de téléphone

ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".pdf"}

_UPLOAD_PAGE_TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  body { font-family: Segoe UI, Arial, sans-serif; background: #fafafa; color: #202020;
         margin: 0; padding: 24px 16px; text-align: center; }
  h1 { font-size: 20px; margin-bottom: 4px; }
  p { color: #636363; font-size: 14px; }
  input[type=file] { display: none; }
  label, button { display: inline-block; width: 100%; max-width: 320px; box-sizing: border-box;
         padding: 16px; margin-top: 16px; font-size: 16px; border-radius: 8px; border: none;
         background: #005fb8; color: white; cursor: pointer; }
  button:disabled { background: #a9a9a9; cursor: default; }
  #status { margin-top: 20px; font-size: 15px; }
  #preview { margin-top: 16px; max-width: 90%; max-height: 240px; border-radius: 8px;
         display: none; }
</style>
</head>
<body>
  <h1>__TITLE__</h1>
  <p>__INSTRUCTION__</p>
  <label for="f">__CHOOSE_LABEL__</label>
  <input type="file" id="f" accept="__ACCEPT__"__CAPTURE_ATTR__>
  <img id="preview">
  <button id="send" disabled>Envoyer au PC</button>
  <div id="status"></div>
<script>
  const input = document.getElementById('f');
  const sendBtn = document.getElementById('send');
  const status = document.getElementById('status');
  const preview = document.getElementById('preview');
  let file = null;

  input.addEventListener('change', () => {
    file = input.files[0] || null;
    sendBtn.disabled = !file;
    status.textContent = '';
    if (file && file.type.startsWith('image/')) {
      preview.src = URL.createObjectURL(file);
      preview.style.display = 'inline-block';
    } else {
      preview.style.display = 'none';
    }
  });

  sendBtn.addEventListener('click', () => {
    if (!file) return;
    sendBtn.disabled = true;
    status.textContent = 'Envoi en cours...';
    fetch(window.location.pathname, {
      method: 'POST',
      headers: {
        'Content-Type': file.type || 'application/octet-stream',
        'X-Filename': encodeURIComponent(file.name || 'photo.jpg'),
      },
      body: file,
    }).then(r => {
      if (r.ok) {
        status.textContent = 'Envoyé ! Tu peux fermer cette page ou envoyer un autre fichier.';
        input.value = '';
        file = null;
        preview.style.display = 'none';
      } else {
        status.textContent = "Échec de l'envoi (" + r.status + "). Réessaie.";
        sendBtn.disabled = false;
      }
    }).catch(() => {
      status.textContent = "Échec de l'envoi (connexion). Réessaie.";
      sendBtn.disabled = false;
    });
  });
</script>
</body>
</html>"""


def _build_upload_page(title: str, instruction: str, choose_label: str, accept: str, capture: bool) -> bytes:
    # Remplacement de texte simple plutôt que str.format() : le CSS/JS du template contient
    # beaucoup d'accolades littérales qu'il faudrait sinon toutes doubler (source d'un bug déjà
    # rencontré ici - voir l'historique du fichier).
    html = _UPLOAD_PAGE_TEMPLATE
    html = html.replace("__TITLE__", title)
    html = html.replace("__INSTRUCTION__", instruction)
    html = html.replace("__CHOOSE_LABEL__", choose_label)
    html = html.replace("__ACCEPT__", accept)
    html = html.replace("__CAPTURE_ATTR__", ' capture="environment"' if capture else "")
    return html.encode("utf-8")


def get_local_ip() -> str:
    """Adresse IP locale du PC sur le réseau Wi-Fi/Ethernet (pour que le téléphone puisse la joindre)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class PhoneUploadServer:
    """Serveur HTTP local éphémère, actif seulement pendant que la boîte de dialogue est ouverte."""

    def __init__(
        self,
        on_file_received: Callable[[Path], None],
        *,
        page_title: str = "Ordres de travail",
        instruction: str = "Prends une photo de l'ordre de travail ou choisis un fichier, puis envoie-le au PC.",
        choose_label: str = "Choisir / prendre une photo",
        accept: str = "image/*,.pdf",
        capture: bool = True,
        allowed_suffixes: frozenset[str] = ALLOWED_SUFFIXES,
        default_suffix: str = ".jpg",
    ):
        self._on_file_received = on_file_received
        self._token = secrets.token_urlsafe(16)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._page_body = _build_upload_page(page_title, instruction, choose_label, accept, capture)
        self._allowed_suffixes = allowed_suffixes
        self._default_suffix = default_suffix

    @property
    def token(self) -> str:
        return self._token

    def start(self) -> str:
        """Démarre le serveur et retourne l'URL complète à afficher/encoder en QR code."""
        token = self._token
        on_file_received = self._on_file_received
        page_body = self._page_body
        allowed_suffixes = self._allowed_suffixes
        default_suffix = self._default_suffix

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002 - silence la sortie console
                pass

            def do_GET(self):
                if self.path.rstrip("/") == f"/u/{token}":
                    body = page_body
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path.rstrip("/") != f"/u/{token}":
                    self.send_response(404)
                    self.end_headers()
                    return

                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_UPLOAD_BYTES:
                    self.send_response(413)
                    self.end_headers()
                    return

                data = self.rfile.read(length)

                raw_name = self.headers.get("X-Filename", "photo.jpg")
                try:
                    raw_name = unquote(raw_name)
                except Exception:  # noqa: BLE001
                    pass
                suffix = Path(raw_name).suffix.lower()
                if suffix not in allowed_suffixes:
                    suffix = default_suffix

                dest_dir = phone_uploads_dir()
                dest_path = dest_dir / f"telephone_{secrets.token_hex(4)}{suffix}"
                dest_path.write_bytes(data)

                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

                try:
                    on_file_received(dest_path)
                except Exception:  # noqa: BLE001
                    pass

        self._httpd = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

        return f"http://{get_local_ip()}:{port}/u/{token}"

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
