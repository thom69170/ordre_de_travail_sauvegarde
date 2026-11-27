# OT Envoi — application Android

Envoie tes ordres de travail **en photo, directement dans la boîte mail dédiée**, et indique pour chaque
jour si l'OT est déjà enregistré sur le PC. On peut aussi y noter ses **jours de repos**.
**Aucune photo n'est enregistrée sur le téléphone.**

## Utilisation

1. Installe l'APK (`app/build/outputs/apk/release/app-release.apk`) : copie-le sur le téléphone, ouvre-le et
   autorise l'installation depuis cette source si Android le demande.
2. Au premier lancement, saisis l'adresse de la boîte dédiée et son **mot de passe d'application**
   (16 lettres, créé sur <https://myaccount.google.com/apppasswords>), puis **Tester** et **Enregistrer**.
3. L'écran principal liste les jours de **J+7 à J-29** (les OT sont publiés quelques jours à l'avance). Appuie
   sur **Photographier** pour un jour : l'appareil photo s'ouvre, prends chaque page (une ou deux), vérifie les
   miniatures (✕ pour en retirer), puis **Envoyer**. **Choisir dans la galerie** ajoute des photos déjà prises
   (jusqu'à 6 pages au total) : elles sont lues en mémoire, sans être copiées.
4. **Jour de repos** : sur un jour sans envoi, appuie sur **🛌 En repos**. Le jour passe en « Repos (en attente
   du PC) », puis « Repos » quand le PC l'a noté. **Annuler** revient en arrière (pour photographier un OT sur ce
   jour : annule d'abord le repos). Il faut l'application du PC en version ≥ 2.11.0.
5. L'état de chaque jour :
   - **✓ Enregistré sur le PC** — l'OT est dans l'application du PC ;
   - **⚠ À relire sur le PC** — après trois lectures, le PC a encore un doute et attend ta relecture (onglet
     Importer) ;
   - **⏳ Envoyé, en attente du PC** — le PC n'a pas encore traité l'envoi (PC éteint ou application fermée) ;
   - **⚠ Envoyé, mais pas trouvé sur le PC** — le PC a répondu depuis, sans cet OT à cette date : le jour
     choisi n'est sans doute pas celui de l'OT ;
   - **Rien d'envoyé**.

## Comment ça marche

Tout passe par la boîte mail ; le PC et le téléphone ne se parlent jamais directement.

| Sens | Quoi |
|---|---|
| téléphone → boîte | un e-mail de la boîte à elle-même, objet `OT AAAA-MM-JJ`, une pièce jointe JPEG par page, en-tête `X-OT-Source: android` |
| téléphone → boîte | repos : un e-mail sans pièce jointe, objet `REPOS AAAA-MM-JJ` (annulation : `REPOS-ANNULE AAAA-MM-JJ`) |
| PC → téléphone | dans le dossier (libellé) `OT-etat` de la boîte, un message texte contenant `{"v":1,"generated":"…","dates":[…],"review":[…],"rest":[…]}` : les jours enregistrés, ceux à relire et les repos |

Côté PC (application « Ordres de travail », version ≥ 2.10.0) : la boîte est toujours un expéditeur autorisé
(`app/mail_import.py`) et l'état est publié après chaque relève (`publish_state`), seulement s'il a changé ou
toutes les 12 h. **Le PC doit être allumé, application ouverte, pour traiter les envois et mettre l'état à jour.**

## Confidentialité : aucune photo sur le téléphone

- La photo est capturée **en mémoire** (`ImageCapture.OnImageCapturedCallback`) puis encodée en JPEG en mémoire
  (`PageEncoder`), jointe à l'e-mail à partir de ces octets, et oubliée dès l'envoi ou en quittant l'écran.
- Le code n'utilise **aucune API de fichier, de cache ni de galerie** (vérifié par recherche dans les sources) et le
  manifeste ne déclare **que** `INTERNET` et `CAMERA` : l'application n'a même pas le droit d'écrire dans le stockage.
- La galerie passe par le **sélecteur de photos du système** : l'application n'obtient que les photos que tu
  choisis, sans permission de stockage. (Parcourir la galerie fait générer des vignettes au système lui-même,
  dans son propre cache : ce ne sont pas des copies faites par l'application.)
- Les captures d'écran sont **bloquées** dans la version finale (`FLAG_SECURE`) : une capture d'écran serait
  enregistrée dans la galerie du téléphone. Les sauvegardes cloud sont désactivées.
- Seules données gardées : l'adresse de la boîte et son mot de passe d'application, **chiffré** avec une clé du
  coffre matériel Android (Keystore).
- Les e-mails envoyés restent dans la boîte mail dédiée (c'est le but) : à toi de les supprimer si besoin.

## Compiler

Android Studio, ou en ligne de commande (Java 17, SDK Android installé) :

```
cd android
gradlew assembleRelease      # APK dans app/build/outputs/apk/release/
gradlew testDebugUnitTest    # tests
```

Le fichier `local.properties` (chemin du SDK, non versionné) doit contenir par exemple
`sdk.dir=C\:/Users/<toi>/AppData/Local/Android/Sdk`. L'APK de la version finale est signé avec la clé de
développement : prévu pour un usage personnel.

## Piège connu : « mailcap »

Sur Android, les fichiers `META-INF/mailcap` de la bibliothèque de messagerie ne sont pas chargés. Sans la
déclaration en dur faite dans `MailClient` (bloc `init` du companion), `getContent()` renvoie un flux brut au lieu du
texte (l'état du PC n'est alors pas lu) et l'envoi d'un message à pièces jointes échoue. Les tests sur PC ne le voient
pas (les fichiers sont dans le classpath) : seul un essai sur téléphone le révèle.

## Essayer sur un téléphone sans vraie boîte

`DeviceServer` (test, inactif sans `DEVICE_SERVER=1`) lance un faux serveur SMTP/IMAP sur le PC et y publie un état
« du PC ». Avec le téléphone en USB (débogage activé) : `adb reverse tcp:3025 tcp:3025` et `tcp:3143 tcp:3143`, puis
déposer un compte de test dans `shared_prefs/otenvoi_debug.xml` (lu **uniquement** par une version de développement :
`adb shell run-as fr.notivo.otenvoi ...`). Le message reçu est sauvegardé dans `build/device-artifacts/`.

## Tests

`ProtocolTest` (objets, fusion des états, tolérance du JSON du PC) et `MailClientTest` (envoi réel vers un faux
serveur SMTP/IMAP GreenMail : pièces jointes identiques octet pour octet, lecture des envois, état publié par le
PC, test de connexion et messages d'erreur). Le message produit par le test est relu par le code du PC
(`build/test-artifacts/ot_android_sample.eml`).

Non couvert par les tests automatiques : l'interface et l'appareil photo (à essayer sur le téléphone), et la
connexion à une vraie boîte Gmail.
