"""Vérification et installation des mises à jour depuis le dépôt GitHub public.

Ne télécharge et n'exécute jamais de fichier .exe : uniquement les fichiers source (texte),
appliqués par simple copie de fichiers. Windows n'a donc rien à bloquer (contrairement à un
véritable installeur/exécutable téléchargé depuis internet).
"""
from __future__ import annotations

import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from app.paths import base_dir, data_dir
from app.version import VERSION

REPO_OWNER = "thom69170"
REPO_NAME = "ordre_de_travail_sauvegarde"
REPO_BRANCH = "main"

RAW_VERSION_URL = (
    f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{REPO_BRANCH}/app/version.py"
)
ZIP_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/archive/refs/heads/{REPO_BRANCH}.zip"

TIMEOUT_SECONDS = 10

# Fichiers/dossiers du dépôt à appliquer lors d'une mise à jour (on ne touche à rien d'autre,
# notamment pas à vendor/, portable/, dist/, codesign/ qui ne sont pas publiés).
UPDATABLE_ENTRIES = [
    "app", "assets", "setup", "main.py", "requirements-app.txt", "requirements.txt",
    "Lancer.bat", "README.md", ".gitignore",
]


class UpdateError(Exception):
    pass


def get_local_version() -> str:
    return VERSION


def _parse_version(v: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts) or (0,)


def get_remote_version() -> str | None:
    """Récupère le numéro de version publié sur GitHub, ou None si indisponible (pas de
    connexion, dépôt inaccessible...) - jamais bloquant/fatal pour l'appelant."""
    try:
        with urllib.request.urlopen(RAW_VERSION_URL, timeout=TIMEOUT_SECONDS) as resp:
            content = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    match = re.search(r'VERSION\s*=\s*"([\d.]+)"', content)
    return match.group(1) if match else None


def check_for_update() -> str | None:
    """Retourne le numéro de la version distante si elle est plus récente que la version
    locale, sinon None (déjà à jour, ou vérification impossible)."""
    remote = get_remote_version()
    if remote is None:
        return None
    if _parse_version(remote) > _parse_version(VERSION):
        return remote
    return None


def pending_update_dir() -> Path:
    return data_dir() / "pending_update"


def download_and_stage_update() -> None:
    """Télécharge l'archive du dépôt et la prépare dans un dossier d'attente ; Lancer.bat
    l'applique (copie de fichiers) au prochain démarrage, une fois l'application fermée."""
    staging = pending_update_dir()
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "update.zip"
        try:
            urllib.request.urlretrieve(ZIP_URL, zip_path)
        except (urllib.error.URLError, OSError) as exc:
            raise UpdateError(f"Téléchargement impossible : {exc}") from exc

        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
        except zipfile.BadZipFile as exc:
            raise UpdateError(f"Archive téléchargée invalide : {exc}") from exc

        extracted_root = Path(tmp) / f"{REPO_NAME}-{REPO_BRANCH}"
        if not extracted_root.exists():
            candidates = [p for p in Path(tmp).iterdir() if p.is_dir()]
            if len(candidates) != 1:
                raise UpdateError("Structure de l'archive téléchargée inattendue.")
            extracted_root = candidates[0]

        for name in UPDATABLE_ENTRIES:
            src = extracted_root / name
            if not src.exists():
                continue
            dest = staging / name
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)


def restart_application() -> None:
    """Ferme l'application et relance Lancer.bat (qui appliquera la mise à jour en attente
    avant de redémarrer l'app)."""
    import os
    import subprocess

    lancer_bat = base_dir() / "Lancer.bat"
    subprocess.Popen(
        ["cmd", "/c", "start", "", str(lancer_bat)],
        cwd=str(base_dir()),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    os._exit(0)
