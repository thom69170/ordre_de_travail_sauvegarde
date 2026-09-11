@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "RUNTIME_PY=%LOCALAPPDATA%\OrdreDeTravail\runtime\venv\Scripts\python.exe"
set "SETUP_MARKER=%LOCALAPPDATA%\OrdreDeTravail\runtime\setup_complete.txt"

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

"%RUNTIME_PY%" main.py
if errorlevel 1 (
    echo.
    echo Une erreur est survenue au lancement.
    pause
)
