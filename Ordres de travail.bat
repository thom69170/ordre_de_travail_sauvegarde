@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "RUNTIME_PY=%LOCALAPPDATA%\OrdreDeTravail\runtime\venv\Scripts\python.exe"
set "RUNTIME_PYW=%LOCALAPPDATA%\OrdreDeTravail\runtime\venv\Scripts\pythonw.exe"
set "SETUP_MARKER=%LOCALAPPDATA%\OrdreDeTravail\runtime\setup_complete.txt"
set "PENDING_UPDATE=%LOCALAPPDATA%\OrdreDeTravail\pending_update"

if exist "%PENDING_UPDATE%" (
    echo Application de la mise a jour telechargee...
    rem /IS force la copie meme si robocopy pense que le fichier est "identique" (taille/date) :
    rem sans ca, les fichiers fraichement extraits du zip GitHub sont souvent ignores a tort.
    rem "%~dp0." (avec le point) plutot que "%~dp0" seul : %~dp0 se termine par un \, et un \
    rem juste avant un guillemet fermant fait que Windows avale les indicateurs suivants dans
    rem le chemin de destination (robocopy echouait alors silencieusement, tout etant redirige
    rem vers nul, sans qu'aucun fichier ne soit jamais reellement copie).
    rem /R:3 /W:1 : par defaut robocopy retente 1 million de fois en attendant 30s a chaque
    rem fois si un fichier semble verrouille (ex: l'ancienne instance qui vient de se fermer et
    rem n'a pas encore relache tous ses fichiers) - ca peut bloquer cette fenetre tres longtemps.
    robocopy "%PENDING_UPDATE%" "%~dp0." /E /IS /IT /R:3 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP >nul
    if errorlevel 8 (
        echo La mise a jour a echoue ^(erreur robocopy^) : l'application precedente va demarrer.
    ) else (
        rmdir /s /q "%PENDING_UPDATE%" >nul 2>&1
        rem Une mise a jour peut ajouter une nouvelle dependance Python (ex: qrcode) : on
        rem s'assure qu'elle est installee, meme si le venv existait deja avant cette maj.
        "%RUNTIME_PY%" -m pip install --quiet --no-warn-script-location -r "%~dp0requirements-app.txt" >nul 2>&1
    )
)

if not exist "%SETUP_MARKER%" (
    echo Premiere installation : mise en place de l'application ^(1 a 2 minutes, connexion internet requise^)...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\bootstrap.ps1"
    if errorlevel 1 (
        echo.
        echo L'installation automatique a echoue. Verifie ta connexion internet et reessaie.
        pause
        exit /b 1
    )
)

rem Un .bat n'a pas d'icone propre (Windows utilise toujours l'icone generique des scripts) :
rem cree un raccourci avec l'icone de l'app directement sur le Bureau, la premiere fois, peu
rem importe ou se trouve ce dossier. [Environment]::GetFolderPath gere aussi le cas d'un Bureau
rem redirige (ex: OneDrive). Ne fait rien si le raccourci existe deja (pas a chaque lancement).
powershell -NoProfile -Command "$d=[Environment]::GetFolderPath('Desktop'); $p=Join-Path $d 'Ordres de travail.lnk'; if (-not (Test-Path $p)) { $s=(New-Object -ComObject WScript.Shell).CreateShortcut($p); $s.TargetPath='%~dp0Ordres de travail.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0assets\icon.ico'; $s.Save() }" >nul 2>&1

rem Lance l'app sans console (pythonw) et en tache detachee (start) pour que cette
rem fenetre se ferme aussitot au lieu de rester affichee tant que l'app tourne.
start "" "%RUNTIME_PYW%" "%~dp0main.py"
