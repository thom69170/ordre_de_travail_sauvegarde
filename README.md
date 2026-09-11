# Ordres de travail

Application Windows autonome pour archiver tes ordres de travail (photo ou PDF, 1 à 2 par jour),
en extraire automatiquement (OCR) le temps de travail et les trajets effectués, et suivre tes
statistiques par semaine / mois / année.

## Utilisation

1. Double-clique sur **`Lancer.bat`** à la racine du dossier.
   - **Si Windows affiche "Contrôle intelligent des applications a bloqué un fichier
     potentiellement dangereux"** : ça arrive quand le dossier vient d'un `.zip` téléchargé
     (GitHub tague tous les fichiers extraits comme "venant d'internet"). Contrairement au
     blocage de `OrdreDeTravail.exe` (voir [Note sur `OrdreDeTravail.exe`](#note-sur-ordredetravailexe)),
     celui-ci se règle simplement et de façon fiable : ouvre PowerShell dans le dossier et lance
     ```
     Get-ChildItem -Recurse | Unblock-File
     ```
     (ou, fichier par fichier : clic droit sur `Lancer.bat` → Propriétés → coche **Débloquer**
     en bas → OK ; à refaire pour `setup\bootstrap.ps1` et `setup\bootstrap_setup.py` si besoin).
     Relance ensuite `Lancer.bat` normalement.
   - **Premier lancement** (une fois débloqué) : installe automatiquement tout ce qu'il faut
     (Python si besoin, les dépendances, le moteur OCR Tesseract) dans
     `%LOCALAPPDATA%\OrdreDeTravail\runtime\` — compte 1 à 2 minutes, connexion internet
     nécessaire. Rien de tout ça n'est mélangé avec un Python que tu aurais déjà sur ta machine
     (environnement dédié à l'app, isolé).
   - **Lancements suivants** : instantané, tout est déjà en place.
2. Onglet **Importer** : choisis une photo ou un PDF d'ordre de travail. L'app tente de lire
   automatiquement la date, le récapitulatif (TPS/TTE/Amplitude...) et les trajets effectués.
   **Vérifie toujours les valeurs pré-remplies en les comparant à l'aperçu de la photo affiché
   à gauche** avant d'enregistrer : l'OCR (lecture automatique) n'est pas fiable à 100 %,
   surtout sur des photos prises au téléphone (flou, reflet, pli du papier...).
3. Onglet **Historique** : liste de tous les jours enregistrés, avec modification/suppression.
4. Onglet **Statistiques** : temps de travail total par semaine/mois/année, et classement des
   trajets/lignes les plus fréquents.

Tes données (base + copies des photos/PDF importés) sont stockées dans :
`%LOCALAPPDATA%\OrdreDeTravail\` (généralement `C:\Users\<toi>\AppData\Local\OrdreDeTravail\`).
Rien n'est envoyé sur internet, tout reste sur ta machine.

## Distribuer l'app à d'autres personnes

Deux façons de partager l'app, selon ce qui compte le plus pour toi :

### Option A — Publier le code sur GitHub (léger, recommandé)

C'est ce que permet le système `Lancer.bat` + `setup/` décrit ci-dessus : comme il télécharge
Python/les dépendances/Tesseract **au premier lancement plutôt que de les inclure**, le dépôt à
publier ne contient que du code source (quelques centaines de Ko, aucun exécutable, aucun gros
fichier binaire).

**Fichiers à publier :** `app/`, `assets/icon.ico`, `setup/`, `main.py`, `requirements-app.txt`,
`Lancer.bat`, `.gitignore`, ce README.
**À ne jamais publier :** `codesign/` (contient la clé privée du certificat), et les dossiers
générés `build/`, `dist/`, `portable/`, `vendor/` — le `.gitignore` fourni les exclut déjà tous.

```
git init
git add app assets/icon.ico setup main.py requirements-app.txt Lancer.bat .gitignore README.md
git commit -m "Version initiale"
git remote add origin https://github.com/<toi>/<nom-du-depot>.git
git push -u origin main
```

Celui qui récupère le dépôt (`git clone` ou "Code → Download ZIP") double-clique juste sur
`Lancer.bat` — tout s'installe tout seul au premier lancement (voir [Utilisation](#utilisation)
ci-dessus). Seul prérequis chez lui : une connexion internet la première fois.

### Option B — Partager un dossier tout-en-un (fonctionne hors ligne, plus lourd)

Le dossier **`portable/`** est une version 100 % autonome (~220 Mo) : Python + Tkinter + toutes
les dépendances + Tesseract déjà inclus dedans, donc **aucune connexion internet nécessaire** au
moment où la personne l'utilise (utile si le destinataire n'a pas internet, ou si tu préfères ne
rien laisser télécharger automatiquement chez lui). À compresser en `.zip` et partager par un
autre moyen que Git (clé USB, lien de téléchargement, release GitHub...), jamais commité
directement dans le dépôt (voir `.gitignore`).

```
1. Compresse le dossier `portable/` en `.zip` (clic droit → Envoyer vers → Dossier compressé).
2. Partage ce `.zip`.
3. La personne le décompresse où elle veut, puis double-clique sur `Lancer.bat` à l'intérieur.
```

Après une modification du code, recopie-la dans `portable/` avant de re-zipper :

```
robocopy app "portable\app" /MIR
robocopy assets "portable\assets" /MIR
```

(`vendor/` et `portable/python/` ne changent pas d'une mise à jour à l'autre, pas besoin de les
retoucher sauf si Tesseract est mis à jour.)

---

Dans les deux cas, chaque installation est indépendante : les données de chaque personne
(`%LOCALAPPDATA%\OrdreDeTravail\`) restent séparées sur chaque machine, rien n'est partagé entre
elles.

## Ré-générer l'exécutable depuis le code source

Le code source Python est dans ce dossier (`app/`, `main.py`). Pour le modifier puis reconstruire
l'exécutable :

```
pip install -r requirements.txt
python main.py
```

(`python main.py` lance l'app directement, pratique pour tester une modification sans reconstruire
l'exe.)

Pour reconstruire `OrdreDeTravail.exe` après une modification :

```
python -m PyInstaller --name OrdreDeTravail --windowed --add-data "vendor/tesseract;vendor/tesseract" --distpath dist --workpath build --noconfirm main.py
powershell -ExecutionPolicy Bypass -File codesign\Signer.ps1
```

**N'oublie pas la 2e commande (`Signer.ps1`)** : PyInstaller régénère un exe non signé à chaque
fois, donc sans re-signature le Contrôle intelligent des applications le bloquera de nouveau.

Le dossier `vendor/tesseract/` contient une copie autonome du moteur OCR Tesseract (installé une
fois via `winget install --id UB-Mannheim.TesseractOCR`, avec le modèle de langue français ajouté
dans `vendor/tesseract/tessdata/fra.traineddata`) : c'est ce qui permet à l'exécutable final de
fonctionner sans rien installer d'autre.

## Note sur `OrdreDeTravail.exe`

Ce fichier (dans `dist\OrdreDeTravail\`) est une troisième option, antérieure au système
`Lancer.bat` + `setup/` décrit plus haut : un exécutable unique construit avec PyInstaller. Il
reste dans le projet mais **n'est plus la méthode recommandée** : voir la limite ci-dessous.

Windows 11 bloque par défaut tout exécutable non signé numériquement (Contrôle intelligent des
applications), sans possibilité de l'autoriser au cas par cas. Pour éviter ça sans désactiver
cette protection sur toute la machine, un certificat de signature **auto-signé** a été créé et
approuvé localement sur ce PC :

- `codesign/OrdreDeTravail.pfx` — le certificat + sa clé privée (protégé par le mot de passe
  `OrdreDeTravail-local`), utilisé pour signer l'exe. **Ne le partage pas** (ni sur GitHub, ni
  ailleurs) : n'importe qui pourrait l'utiliser pour signer un autre programme comme s'il venait
  de toi sur cette machine.
- `codesign/OrdreDeTravail.cer` — la partie publique du certificat, importée dans les magasins
  Windows *Autorités de certification racines de confiance* et *Éditeurs de confiance* du compte
  utilisateur (`certutil -user -addstore ...`). C'est cette confiance locale, propre à ce compte
  Windows sur ce PC, qui permet à l'exe signé de s'exécuter.
- `codesign/Signer.ps1` — à relancer après chaque reconstruction de l'exe (voir ci-dessus).

Cette confiance ne s'applique qu'à ce compte Windows sur ce PC. Sur une autre machine (ou un
autre compte), il faudrait soit ré-importer `OrdreDeTravail.cer` de la même façon, soit utiliser
`Lancer.bat`.

**Limite constatée :** même signé par ce certificat désormais approuvé sur ce PC, un exe
fraîchement reconstruit a quand même été bloqué par le Contrôle intelligent des applications lors
d'un test. Un certificat auto-signé suffit pour la vérification de signature classique, mais pas
forcément pour ce système, qui semble aussi consulter une réputation en ligne par fichier. Résultat
pas garanti à 100 % → `Lancer.bat` reste la méthode recommandée.

## Structure du projet

- `app/db.py` — stockage SQLite (base `ordres.db`)
- `app/ocr_engine.py` — rendu des PDF/photos en image + appel à Tesseract
- `app/parser.py` — extraction (date, chauffeur, récapitulatif, trajets) depuis le texte OCR
- `app/stats.py` — agrégations semaine/mois/année, classement des trajets
- `app/ui/` — interface graphique (Tkinter) : onglets Importer / Historique / Statistiques
- `main.py` — point d'entrée
- `setup/bootstrap.ps1` — installe Python (si besoin) + crée l'environnement virtuel de l'app,
  appelé automatiquement par `Lancer.bat` au premier lancement
- `setup/bootstrap_setup.py` — installe/détecte Tesseract et télécharge les langues OCR
- `requirements-app.txt` — dépendances minimales pour *faire tourner* l'app (utilisées par le
  bootstrap) ; `requirements.txt` couvre en plus les outils de développement (PyInstaller...)
- `portable/` — version autonome tout-en-un, alternative hors ligne (voir
  [Distribuer l'app à d'autres personnes](#distribuer-lapp-à-dautres-personnes))
- `codesign/` — certificat local utilisé pour signer `dist\OrdreDeTravail\OrdreDeTravail.exe`
