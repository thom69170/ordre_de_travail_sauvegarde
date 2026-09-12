@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "RUNTIME_PY=%LOCALAPPDATA%\OrdreDeTravail\runtime\venv\Scripts\python.exe"
set "RUNTIME_PYW=%LOCALAPPDATA%\OrdreDeTravail\runtime\venv\Scripts\pythonw.exe"
set "SETUP_MARKER=%LOCALAPPDATA%\OrdreDeTravail\runtime\setup_complete.txt"
set "PENDING_UPDATE=%LOCALAPPDATA%\OrdreDeTravail\pending_update"

if exist "%PENDING_UPDATE%" (
    echo Application de la mise a jour telechargee...
    robocopy "%PENDING_UPDATE%" "%~dp0" /E /NFL /NDL /NJH /NJS /NC /NS /NP >nul
    rmdir /s /q "%PENDING_UPDATE%" >nul 2>&1
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
