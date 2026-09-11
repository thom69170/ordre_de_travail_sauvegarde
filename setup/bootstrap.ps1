# Premier lancement : s'assure qu'un Python utilisable (avec Tkinter) existe sur la machine
# (en installe un sans droits admin si besoin), puis cree un environnement virtuel local
# dedie a l'application (ses dependances n'affectent jamais un Python deja present).
# Appele automatiquement par Lancer.bat quand ce venv n'existe pas encore.
$ErrorActionPreference = "Stop"

$PythonVersion = "3.11.9"
$AppDataDir = Join-Path $env:LOCALAPPDATA "OrdreDeTravail"
$RuntimeDir = Join-Path $AppDataDir "runtime"
$VenvDir = Join-Path $RuntimeDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
# Ecrit uniquement quand TOUTES les etapes ci-dessous ont reussi : si une installation
# precedente a ete interrompue (ex: bloquee par Windows, coupure reseau...), ce marqueur est
# absent et on refait proprement l'installation au lieu de lancer l'app avec des dependances
# manquantes.
$MarkerFile = Join-Path $RuntimeDir "setup_complete.txt"

if ((Test-Path $VenvPython) -and (Test-Path $MarkerFile)) {
    Write-Host "Environnement deja pret : $VenvPython"
    exit 0
}

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

function Test-PythonWithTkinter($exePath) {
    if (-not (Test-Path $exePath)) { return $false }
    & $exePath -c "import tkinter" *> $null
    return ($LASTEXITCODE -eq 0)
}

# 1) Cherche un Python deja installe sur la machine (evite un telechargement inutile).
$basePython = $null
$candidates = @()
foreach ($hive in @("HKCU:\Software\Python\PythonCore", "HKLM:\Software\Python\PythonCore")) {
    if (Test-Path $hive) {
        Get-ChildItem $hive -ErrorAction SilentlyContinue | ForEach-Object {
            $installPathKey = Join-Path $_.PSPath "InstallPath"
            if (Test-Path $installPathKey) {
                $exe = (Get-ItemProperty $installPathKey -ErrorAction SilentlyContinue).ExecutablePath
                if ($exe) { $candidates += $exe }
            }
        }
    }
}
# Prefere les versions les plus repandues pour la compatibilite des paquets.
$preferredOrder = @("311", "312", "310", "313", "39")
$candidates = $candidates | Sort-Object -Unique | Sort-Object {
    $v = ([regex]::Match($_, "Python3(\d+)")).Groups[1].Value
    $idx = $preferredOrder.IndexOf($v)
    if ($idx -lt 0) { 99 } else { $idx }
}
foreach ($c in $candidates) {
    if (Test-PythonWithTkinter $c) {
        $basePython = $c
        break
    }
}

# 2) Aucun Python utilisable trouve : on en installe un, localement pour l'utilisateur courant.
if (-not $basePython) {
    Write-Host "Aucun Python utilisable trouve : telechargement de Python $PythonVersion (~26 Mo)..."
    $installerUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
    $installerPath = Join-Path $env:TEMP "OrdreDeTravail-python-installer.exe"
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

    Write-Host "Installation de Python (pour votre compte utilisateur uniquement, sans droits admin)..."
    $installArgs = @(
        "/quiet", "InstallAllUsers=0", "PrependPath=0", "Shortcuts=0", "AssociateFiles=0",
        "CompileAll=0", "Include_launcher=0", "Include_test=0", "Include_doc=0",
        "Include_dev=0", "Include_pip=1", "Include_tcltk=1"
    )
    $proc = Start-Process -FilePath $installerPath -ArgumentList $installArgs -PassThru -Wait
    Remove-Item -Force $installerPath -ErrorAction SilentlyContinue
    if ($proc.ExitCode -ne 0) {
        Write-Error "L'installation de Python a echoue (code $($proc.ExitCode))."
        exit 1
    }

    $shortVer = $PythonVersion -replace '^(\d+)\.(\d+).*', '$1$2'
    $basePython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$shortVer\python.exe"
    if (-not (Test-PythonWithTkinter $basePython)) {
        Write-Error "Python installe mais Tkinter indisponible ($basePython)."
        exit 1
    }
}

Write-Host "Python de base : $basePython"

# 3) Environnement virtuel dedie a l'application (isole des autres usages de ce Python).
Write-Host "Creation de l'environnement de l'application..."
& $basePython -m venv $VenvDir
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) {
    Write-Error "La creation de l'environnement virtuel a echoue."
    exit 1
}

Write-Host "Installation des dependances de l'application..."
$repoRoot = Split-Path -Parent $PSScriptRoot
& $VenvPython -m pip install --quiet --no-warn-script-location --upgrade pip
& $VenvPython -m pip install --quiet --no-warn-script-location -r (Join-Path $repoRoot "requirements-app.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Error "L'installation des dependances Python a echoue."
    exit 1
}

Write-Host "Configuration du moteur OCR (Tesseract)..."
& $VenvPython (Join-Path $PSScriptRoot "bootstrap_setup.py")

Set-Content -Path $MarkerFile -Value (Get-Date -Format "o")
Write-Host "Installation initiale terminee."
exit 0
