# Ordres de travail

Application Windows autonome pour archiver tes ordres de travail (photo ou PDF, 1 à 2 par jour),
en extraire automatiquement (OCR) le temps de travail et les trajets effectués, et suivre tes
statistiques par semaine / mois / année.

## Utilisation

1. Double-clique sur **`Ordres de travail.bat`** à la racine du dossier.
   - **Si Windows affiche "Contrôle intelligent des applications a bloqué un fichier
     potentiellement dangereux"** : ça arrive quand le dossier vient d'un `.zip` téléchargé
     (GitHub tague tous les fichiers extraits comme "venant d'internet"). Contrairement au
     blocage de `OrdreDeTravail.exe` (voir [Note sur `OrdreDeTravail.exe`](#note-sur-ordredetravailexe)),
     celui-ci se règle simplement et de façon fiable : ouvre PowerShell dans le dossier et lance
     ```
     Get-ChildItem -Recurse | Unblock-File
     ```
     (ou, fichier par fichier : clic droit sur `Ordres de travail.bat` → Propriétés → coche **Débloquer**
     en bas → OK ; à refaire pour `setup\bootstrap.ps1` et `setup\bootstrap_setup.py` si besoin).
     Relance ensuite `Ordres de travail.bat` normalement.
   - **Premier lancement** (une fois débloqué) : installe automatiquement tout ce qu'il faut
     (Python si besoin, les dépendances, le moteur OCR Tesseract) dans
     `%LOCALAPPDATA%\OrdreDeTravail\runtime\` — compte 1 à 2 minutes, connexion internet
     nécessaire. Rien de tout ça n'est mélangé avec un Python que tu aurais déjà sur ta machine
     (environnement dédié à l'app, isolé).
   - **Si l'installation automatique échoue avec "Permission denied" / "La création de
     l'environnement virtuel a échoué"** : c'est généralement un antivirus qui bloque
     temporairement l'écriture des fichiers fraîchement créés dans
     `%LOCALAPPDATA%\OrdreDeTravail\`. Le script réessaie déjà automatiquement plusieurs fois ;
     si ça échoue quand même, vérifie qu'aucun antivirus ne bloque ce dossier, puis relance
     `Ordres de travail.bat`.
   - **Lancements suivants** : instantané, tout est déjà en place.
   - Un `.bat` n'ayant pas d'icône propre, un raccourci **« Ordres de travail »** (avec l'icône
     de l'app) est créé automatiquement **sur le Bureau** au premier lancement, quel que soit
     l'endroit où se trouve ce dossier — utilise-le au quotidien plutôt que le `.bat` lui-même.
2. Onglet **Importer** : choisis une photo ou un PDF d'ordre de travail. L'app tente de lire
   automatiquement la date, le récapitulatif (TPS/TTE/Amplitude...) et les trajets effectués.
   **Vérifie toujours les valeurs pré-remplies en les comparant à l'aperçu de la photo affiché
   à gauche** avant d'enregistrer : l'OCR (lecture automatique) n'est pas fiable à 100 %,
   surtout sur des photos prises au téléphone (flou, reflet, pli du papier...).
   - **Envoyer une photo depuis le téléphone** : bouton **Recevoir depuis le téléphone...**.
     Une fenêtre affiche un QR code ; scanne-le avec l'appareil photo du téléphone (connecté au
     **même Wi-Fi** que ce PC) pour ouvrir une page qui permet de prendre la photo ou de choisir
     un fichier et de l'envoyer directement — pas d'appli à installer sur le téléphone. La photo
     reçue est traitée automatiquement, comme si elle avait été importée depuis le PC. Windows
     peut demander une autorisation de pare-feu la première fois (à accepter, sinon le téléphone
     ne peut pas joindre le PC). **La fenêtre reste ouverte pour envoyer plusieurs photos à la
     suite** avec le même QR code : si tu en envoies une nouvelle pendant que la précédente est
     encore en cours d'analyse/relecture, elle est mise en attente (compteur affiché en haut) et
     chargée automatiquement dès que tu enregistres ou réinitialises le formulaire courant.
   - **Numéro de ligne** : chaque trajet peut être associé à un numéro de ligne (ex: "164 —
     CHARMILLES / TARARE GARE") — pratique quand tu fais plusieurs lignes différentes le même
     jour. Avec Gemini configuré, il est détecté automatiquement (lu depuis le code de service
     sur l'OT, ex: "164TATA1520" → ligne 164) ; tu peux aussi le modifier (double-clique sur un
     trajet) ou en ajouter un manuellement — les numéros déjà utilisés sont alors proposés
     automatiquement (pas besoin de les retaper).
   - **Mise à jour automatique des anciens OT** : quand une mise à jour améliore la lecture des
     trajets (comme celle-ci), l'app relit automatiquement en arrière-plan (avec Gemini) les
     anciens OT jamais retouchés depuis leur import, pour leur appliquer la nouvelle logique —
     un message s'affiche une fois que c'est fait. Seuls les trajets sont concernés (jamais les
     autres champs), et un OT que tu as déjà corrigé/réenregistré à la main n'est jamais touché.
   - **Changement de dernière minute (prime)** : case à cocher qui signale qu'un service a été
     modifié moins de 48h avant la prise de service (donne droit à une prime selon la convention
     collective). Avec Gemini configuré, elle est cochée automatiquement en comparant la date
     d'édition de l'OT (ligne "Edition du JJ/MM/AAAA à HH:MM" en haut du document) à l'heure de
     prise de service — vérifie toujours, et corrige à la main si besoin (sans Gemini, coche-la
     toi-même). Visible aussi dans **Historique** (colonne dédiée, ligne surlignée) et dans
     **Statistiques** (nombre de primes sur la période).
3. Onglet **Historique** : liste de tous les jours enregistrés, avec modification/suppression.
4. Onglet **Statistiques** : temps de travail total par semaine/mois/année, et classement des
   trajets/lignes les plus fréquents.
5. Onglet **Heures sup.** : suivi des heures supplémentaires (25 %/50 %) relevées sur tes
   **feuilles de prépaie** (le rapport d'activité RNA - pas le bulletin de paie officiel, dont la
   mise en page n'est pas reconnue par la lecture automatique). **L'app ne calcule jamais
   elle-même tes heures sup** (le mode de calcul exact - modulation du temps de travail - n'est
   pas garanti fiable à deviner) : elle se contente de relire les chiffres déjà présents sur le
   document (import direct du PDF, lecture automatique du texte - pas besoin d'OCR/Gemini, ça
   marche même sans clé configurée) et de les garder en historique. Vérifie toujours les valeurs
   pré-remplies avant d'enregistrer. Comme dans l'onglet Importer, tu peux aussi envoyer le PDF
   depuis ton téléphone via le bouton **Recevoir depuis le téléphone...** (même Wi-Fi requis),
   en enchaînant plusieurs feuilles de prépaie à la suite avec le même QR code si besoin.
   En plus des heures sup, la lecture récupère aussi tous les autres compteurs du document
   (jours travaillés, TTE, repos différés, RC nuit, cumuls annuels...) — accessibles via le
   bouton **Voir tous les détails...**.
6. Onglet **Paramètres** (facultatif) : permet de configurer une clé API Gemini (Google) pour
   remplacer l'OCR local par une lecture beaucoup plus fiable par IA — tutoriel complet dans
   l'onglet, avec le lien pour générer une clé gratuite. **Si tu configures une clé, tes photos
   sont alors envoyées aux serveurs de Google pour être analysées** (l'onglet l'explique
   clairement) ; sans clé, tout continue de fonctionner en local comme avant. Cet onglet permet
   aussi de vérifier et d'installer les mises à jour (voir ci-dessous).

## Mises à jour

L'app vérifie automatiquement (au démarrage, en arrière-plan, sans bloquer) si une nouvelle
version est publiée sur ce dépôt GitHub. Si oui, l'onglet **Paramètres** se marque ("Paramètres 🔵
MàJ") ; un bouton **Vérifier les mises à jour** permet aussi de le faire à la demande. Clique sur
**Télécharger et installer** pour l'installer : l'app se ferme et redémarre automatiquement une
fois terminé.

Comme cette mise à jour ne télécharge et n'exécute jamais de `.exe` (uniquement les fichiers
source du dépôt, appliqués par simple copie de fichiers avant le redémarrage), le Contrôle
intelligent des applications de Windows n'a rien à bloquer.

Pour publier une mise à jour toi-même : après avoir modifié le code et testé, incrémente
`VERSION` dans `app/version.py` avant de commit/push — c'est cette comparaison de version qui
déclenche la détection côté utilisateurs.

Tes données (base + copies des photos/PDF importés, et la clé Gemini si tu en configures une)
sont stockées dans : `%LOCALAPPDATA%\OrdreDeTravail\` (généralement
`C:\Users\<toi>\AppData\Local\OrdreDeTravail\`). Rien n'est envoyé sur internet par défaut ; ça
change uniquement si tu configures toi-même une clé Gemini dans l'onglet Paramètres.

## Distribuer l'app à d'autres personnes

Deux façons de partager l'app, selon ce qui compte le plus pour toi :

### Option A — Publier le code sur GitHub (léger, recommandé)

C'est ce que permet le système `Ordres de travail.bat` + `setup/` décrit ci-dessus : comme il télécharge
Python/les dépendances/Tesseract **au premier lancement plutôt que de les inclure**, le dépôt à
publier ne contient que du code source (quelques centaines de Ko, aucun exécutable, aucun gros
fichier binaire).

**Fichiers à publier :** `app/`, `assets/icon.ico`, `setup/`, `main.py`, `requirements-app.txt`,
`Ordres de travail.bat`, `.gitignore`, ce README.
**À ne jamais publier :** `codesign/` (contient la clé privée du certificat), et les dossiers
générés `build/`, `dist/`, `portable/`, `vendor/` — le `.gitignore` fourni les exclut déjà tous.

```
git init
git add app assets/icon.ico setup main.py requirements-app.txt "Ordres de travail.bat" .gitignore README.md
git commit -m "Version initiale"
git remote add origin https://github.com/<toi>/<nom-du-depot>.git
git push -u origin main
```

Celui qui récupère le dépôt (`git clone` ou "Code → Download ZIP") double-clique juste sur
`Ordres de travail.bat` — tout s'installe tout seul au premier lancement (voir [Utilisation](#utilisation)
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
`Ordres de travail.bat` + `setup/` décrit plus haut : un exécutable unique construit avec PyInstaller. Il
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
`Ordres de travail.bat`.

**Limite constatée :** même signé par ce certificat désormais approuvé sur ce PC, un exe
fraîchement reconstruit a quand même été bloqué par le Contrôle intelligent des applications lors
d'un test. Un certificat auto-signé suffit pour la vérification de signature classique, mais pas
forcément pour ce système, qui semble aussi consulter une réputation en ligne par fichier. Résultat
pas garanti à 100 % → `Ordres de travail.bat` reste la méthode recommandée.

## Structure du projet

- `app/db.py` — stockage SQLite (base `ordres.db`)
- `app/ocr_engine.py` — rendu des PDF/photos en image + appel à Tesseract
- `app/parser.py` — extraction (date, conducteur, récapitulatif, trajets) depuis le texte OCR
- `app/gemini_engine.py` — extraction équivalente via l'API Gemini (si une clé est configurée)
- `app/extraction.py` — choisit Gemini ou Tesseract, avec repli automatique sur Tesseract
- `app/config.py` — configuration locale (clé API Gemini)
- `app/version.py` / `app/updater.py` — numéro de version et vérification/installation des
  mises à jour depuis GitHub
- `app/stats.py` — agrégations semaine/mois/année, classement des trajets
- `app/ui/` — interface graphique (Tkinter) : onglets Importer / Historique / Statistiques /
  Paramètres
- `main.py` — point d'entrée
- `setup/bootstrap.ps1` — installe Python (si besoin) + crée l'environnement virtuel de l'app,
  appelé automatiquement par `Ordres de travail.bat` au premier lancement
- `setup/bootstrap_setup.py` — installe/détecte Tesseract et télécharge les langues OCR
- `requirements-app.txt` — dépendances minimales pour *faire tourner* l'app (utilisées par le
  bootstrap) ; `requirements.txt` couvre en plus les outils de développement (PyInstaller...)
- `portable/` — version autonome tout-en-un, alternative hors ligne (voir
  [Distribuer l'app à d'autres personnes](#distribuer-lapp-à-dautres-personnes))
- `codesign/` — certificat local utilisé pour signer `dist\OrdreDeTravail\OrdreDeTravail.exe`
