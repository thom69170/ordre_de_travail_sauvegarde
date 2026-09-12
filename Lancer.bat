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
    robocopy "%PENDING_UPDATE%" "%~dp0." /E /IS /IT /NFL /NDL /NJH /NJS /NC /NS /NP >nul
    if errorlevel 8 (
        echo La mise a jour a echoue ^(erreur robocopy^) : l'application precedente va demarrer.
    ) else (
        rmdir /s /q "%PENDING_UPDATE%" >nul 2>&1
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

rem Lance l'app sans console (pythonw) et en tache detachee (start) pour que cette
rem fenetre se ferme aussitot au lieu de rester affichee tant que l'app tourne.
start "" "%RUNTIME_PYW%" "%~dp0main.py"
