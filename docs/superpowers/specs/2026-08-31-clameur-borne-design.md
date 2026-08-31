# Clameur — Sous-projet 1 : la borne

**Date :** 2026-08-31
**Statut :** design validé et relu, prêt pour le plan d'implémentation
**Licence du projet :** AGPL-3.0

---

## 1. Intention

Permettre à quelqu'un d'enregistrer une capsule sonore — une idée, un souvenir, un
échange à plusieurs voix — et de repartir immédiatement avec un ticket imprimé
portant un QR code. Le ticket est collé où son auteur veut. Celui qui le trouve
scanne et écoute.

La référence est explicite : les *clameurs* d'Alain Damasio dans *La Zone du
Dehors* (1999) — des poèmes déposés dans les rues de Cerclon, un tract sonore
comme forme de résistance dans une société de contrôle.

### Ce qui est neuf

Les ancêtres du genre — [murmur] (2003), Yellow Arrow (2004-2006), Semapedia
(2005) — sont tous éteints. Aucun ne proposait l'objet physique remis en main
propre dans l'instant. Le geste « je parle, le ticket sort, je le colle » est le
cœur du projet et sa seule véritable nouveauté.

### État de l'art (recherche du 2026-08-30)

| Projet | Statut |
|---|---|
| Roundware (Django, maintenu) | Audio contributif **géolocalisé**, clients mobiles natifs. Écarté : notre parcours n'a ni GPS ni app. |
| Audiomark, qrvoice, AudioQR | Démos jouets, sans plateforme ni impression. |
| Audio Atlas (CLAP + t-SNE + DeepScatter) | Visualisation de corpus audio en nuage de points. **Brique à reprendre pour le sous-projet 2.** |

Aucun projet libre ne couvre l'assemblage capture → impression → lecture.

---

## 2. Périmètre

### Dans la v1

Capture sur le téléphone du visiteur, publication, impression du ticket, page de
lecture publique, enrichissement sémantique, console opérateur.

### Hors périmètre, explicitement

- **Sous-projet 2 — la constellation :** visualisation graphique du corpus par
  proximité sémantique. Les vecteurs sont produits dès la v1, mais **rien ne les
  consomme**. À spécifier après un premier événement réel, avec de vraies
  capsules. Aucune app v1 ne porte ce nom, il lui est réservé.

  *Vision arrêtée avec le mainteneur le 2026-08-31, à ne pas perdre :* **deux
  écrans côte à côte**, une liste simple et le graphe, **synchronisés dans les
  deux sens**. Cliquer une pastille du graphe fait défiler la liste jusqu'à la
  clameur, la focalise et lance la lecture ; cliquer un élément de la liste fait
  ressortir sa pastille. Le mécanisme existe déjà à moitié dans Hypostasia
  (`front/static/front/js/lecteur_audio.js` et `transcription_rythme.js`, qui
  font défiler et illuminer un texte au fil de la lecture).

  **Pas de graphe de forces.** Les positions se calculent côté serveur en
  projetant les vecteurs 1024D en 2D (UMAP ou t-SNE), une seule fois, et se
  stockent. Le front ne fait que dessiner des points. Une simulation physique
  replacerait les étoiles à chaque visite : on ne pourrait plus s'y repérer ni
  revenir à une clameur retrouvée la veille. Les étoiles doivent être fixes.

  Le « moteur de carto » de Lespass (`widget_carte_adresse.js`) ne sert pas ici :
  c'est du Leaflet + Nominatim pour saisir une adresse géographique.
- **Sous-projet 3 — la plateforme sociale :** comptes, collections, navigation
  entre capsules. Seulement si 1 et 2 trouvent leur public.
- **Vidéo.** Repoussée : 50 à 200× le poids de l'audio, pipeline de transcodage
  distinct, et une modération de nature différente.
- **Géolocalisation.** Impossible par construction : l'impression a lieu à la
  borne, le collage ailleurs. Le système ne saura jamais où un ticket a été posé
  — à condition de purger les EXIF des photos, voir §12.

---

## 3. Décisions arrêtées

| # | Décision | Raison |
|---|---|---|
| D1 | Contexte : **borne fixe en événement** | Public captif, **opérateur présent**, modération humaine gratuite, pas de comptes. La présence de l'opérateur est une hypothèse de conception : plusieurs mécanismes de rattrapage sont manuels. |
| D2 | Capture **sur le téléphone du visiteur** | Supprime le poste matériel le plus fragile d'une borne publique : micro, écran, hygiène. |
| D3 | **Auto-écoute puis publication** par le visiteur | Préserve l'immédiateté ; l'auteur assume ce qu'il publie ; l'opérateur garde un kill switch. |
| D4 | Capsules **permanentes**, sans code d'effacement | Choix du mainteneur. Dette assumée, voir §12. |
| D5 | **Audio + photo optionnelle** | La photo coûte presque rien et donne une vignette au ticket comme à la page. |
| D6 | **Diarisation conservée** | Une capsule peut porter plusieurs voix. |
| D7 | **Pas de limite éditoriale de durée**, garde-fou technique à 10 min | 10 min pèsent de 2,4 Mo (Opus 32 kbps) à ~10 Mo (AAC iOS) et coûtent 0,03 $ à transcrire. Ni le réseau ni le coût ne contraignent. Comportement exact au garde-fou : §6. |
| D8 | Sunmi : **uniquement des appels sortants, aucun endpoint entrant exposé**, 80 mm / 576 dots | Le serveur peut vivre derrière un NAT. Plusieurs appels sortants existent (`pushContent`, `onlineStatus`…), ce qui compte est qu'aucun ne rentre. |
| D9 | **Enrichissement sémantique dès la v1** | Choix du mainteneur, contre ma recommandation initiale de le différer. Voxtral à 0,003 $/min rend l'argument du coût caduc. |

---

## 4. Architecture

### Apps Django

| App | Responsabilité |
|---|---|
| `bornes` | Le modèle `Borne` : relie une affiche, une imprimante et des réglages. |
| `capsules` | `Capsule`, `Tag`, capture, page de lecture, **et les tâches d'enrichissement** (`capsules/tasks.py`). |
| `impression` | `JobImpression`, backends d'impression, tâche d'envoi. Isolé pour être testable sans matériel. |

Trois apps, pas quatre : une app sans aucun modèle, créée pour héberger trois
tâches Celery, serait de la structure pour rien.

### La Borne est l'objet pivot

Le QR de l'affiche encode `https://<domaine>/b/<slug>`. Ce slug est le seul moyen
pour le téléphone du visiteur de désigner **l'imprimante qui est à côté de lui**.
Sans cet objet, rien ne relie la page web à la machine physique.

### Flux de bout en bout

```
Affiche (QR fixe)  →  /b/<slug>  ←  téléphone du visiteur
   │  rendu serveur : onlineStatus(sn), résultat mis en cache 30 s
   ↓  MediaRecorder → arrêt → POST immédiat de l'audio
POST /b/<slug>/capsule                →  Capsule(statut=brouillon)
   ↓  réécoute du blob LOCAL pendant la saisie pseudo / tags / photo
POST /c/<uuid>/publier
   ├─ ffmpeg SYNCHRONE            →  audio_diffusion
   ├─ statut = publiee            →  écrit en base, source de vérité
   ├─→ JobImpression(en_attente)  →  Celery  →  openapi.sunmi.com  →  ticket
   └─→ Celery : transcrire → taguer → embarquer
Le ticket porte le QR de /c/<uuid>    →  page de lecture publique
```

### Trois invariants non négociables

**I1 — Une capsule publiée est immédiatement écoutable sur tous les
navigateurs.** La normalisation ffmpeg est **synchrone**, dans la vue de
publication : quelques secondes, locales, sans réseau. Sans elle, une capsule
enregistrée sur Android (webm/opus) et scannée depuis un iPhone ne se lirait pas —
et le premier à scanner un ticket est presque toujours son auteur, sur son propre
téléphone. Seules la transcription, les tags et l'embedding sont asynchrones,
parce qu'eux dépendent du réseau et de Mistral.

Si ffmpeg échoue malgré tout : la capsule est publiée quand même, la page sert
`audio_original`, l'erreur est visible en console et l'étape est rejouable.
Publier ne doit jamais échouer.

**I2 — La publication ne dépend jamais de Celery.** Le statut `publiee` et le
`JobImpression(en_attente)` sont écrits **en base d'abord**. L'envoi dans la file
Celery est enveloppé dans un `try/except` : si Redis est mort, la capsule est
publiée, écoutable, et le job attend une relance depuis la console. La base est
la source de vérité, jamais la file.

**I3 — La publication ne dépend jamais de l'imprimante.** Si la machine est
débranchée ou sans papier, la capsule existe quand même et le job reste en file.

Ces trois invariants ont une seule raison d'être : **un ticket déjà collé sur un
mur ne doit jamais mener à une page vide.**

---

## 5. Modèle de données

### `bornes.Borne`

| Champ | Type | Rôle |
|---|---|---|
| `slug` | slug unique | Ce que le QR de l'affiche encode |
| `nom` | char | Usage interne et console |
| `numero_serie_imprimante` | char | Le SN Sunmi. Ce n'est **pas** un secret. |
| `dots_par_ligne` | int, défaut 576 | 576 = 80 mm, 384 = 58 mm |
| `active` | bool | Coupe la capture sans redéploiement |
| `texte_accueil` | text | La phrase affichée au visiteur qui arrive |
| `duree_max_secondes` | int, défaut 600 | Garde-fou technique côté client, voir §6 |

### `capsules.Capsule`

| Champ | Type | Note |
|---|---|---|
| `uuid` | UUIDv4, clé publique | **Non énumérable.** Un entier auto-incrémenté laisserait parcourir tout le corpus. |
| `borne` | FK | |
| `pseudo` | char, blank | |
| `statut` | choices | `brouillon` / `publiee` / `retiree` |
| `audio_original` | File | **Jamais réencodé, jamais supprimé.** Voir ci-dessous. |
| `audio_diffusion` | File, blank | AAC/m4a 64 kbps mono, produit synchroniquement à la publication |
| `duree_secondes` | int | |
| `photo` | Image, blank | EXIF purgés à l'ingestion, voir §12 |
| `creee_le`, `publiee_le` | datetime | |
| `nombre_ecoutes` | int | Incrémenté par un POST dédié **au clic play**, pas au chargement de page. Affiché en console uniquement. |
| `transcription_raw` | JSON | Segments diarisés : `[{speaker, start, end, text}]` |
| `transcription_texte` | text | Concaténation, sert à l'embedding |
| `langue_detectee` | char | |
| `embedding` | `VectorField(1024)` | `mistral-embed` |
| `enrichie_le` | datetime, null | |
| `erreur_enrichissement` | text, blank | Visible en console |

**Pourquoi deux fichiers audio.** `audio_original` est le fichier brut tel que le
navigateur l'a envoyé. Il double le stockage — quelques Mo par millier de
capsules — et garantit qu'un meilleur modèle pourra retranscrire l'archive dans
trois ans. Un audio recompressé deux fois ne se répare pas.

**Pourquoi `nombre_ecoutes` malgré la règle anti-champ-mort.** Ce n'est pas un
champ « au cas où » : c'est la seule mesure qui répondra à la question dont
dépend tout le projet — *est-ce que les passants scannent réellement les tickets
collés ?* Sans elle, on ne saura pas si Clameur fonctionne.

### `capsules.Tag` et `capsules.TagDeCapsule`

`TagDeCapsule(capsule, tag, origine)` où `origine ∈ {auteur, machine}`.

C'est le seul endroit où l'on ajoute de la structure là où un M2M simple
suffirait, et c'est délibéré : les tags saisis par l'auteur sont sa parole, ceux
extraits par le LLM sont une hypothèse. Sur un projet qui affiche des voix sous
pseudo dans la rue, mélanger les deux reviendrait à mettre des mots dans la
bouche des gens.

### `impression.JobImpression`

| Champ | Note |
|---|---|
| `capsule`, `borne` | FK |
| `statut` | `en_attente → envoye` \| `echoue` |
| `trade_no` | Identifiant Sunmi, conservé pour interroger `printStatus` depuis la console |
| `tentatives`, `message_erreur` | |

**Pas d'état `imprime` en v1.** Le mode push n'expose aucun endpoint, donc Sunmi
ne rappelle jamais : un tel état serait inatteignable sans une tâche de
vérification différée que rien ne justifie tant que l'opérateur est devant la
machine et voit le papier sortir. `printStatus(trade_no)` reste appelable
manuellement depuis la console en cas de doute.

### Aucun modèle pour la constellation

Le vecteur vit sur la Capsule. Les voisins se calculeront à la volée par requête
pgvector, dans le sous-projet 2. **Pas de table d'arêtes :** un graphe
matérialisé se périme à chaque nouvelle capsule, et sur quelques milliers de
lignes une recherche de plus proches voisins est instantanée.

---

## 6. Parcours de capture

`/b/<slug>` → accueil (texte de la borne) → enregistrement avec chronomètre →
arrêt → **réécoute** → pseudo, tags, photo optionnelle → publier → « ton ticket
sort ».

Un écran par étape, transitions HTMX, **aucune page qui recharge pendant qu'un
micro est ouvert**.

### État de l'imprimante

Le rendu serveur de `/b/<slug>` appelle `onlineStatus(sn)` et affiche un message
si l'imprimante est hors ligne. **C'est une exigence, pas une option** : promettre
un ticket qu'aucune machine ne peut sortir est le pire échec du parcours.

Le résultat est mis en cache 30 secondes (cache Django) : sans cela, chaque
visiteur déclencherait un appel à l'API Sunmi. Aucune route AJAX dédiée — le
téléphone du visiteur ne peut pas appeler Sunmi lui-même, les secrets HMAC sont
côté serveur.

### Ordre des opérations, et pourquoi

**L'audio est envoyé dès l'arrêt de l'enregistrement**, avant la saisie du pseudo :
cela met à profit le temps de frappe pour l'upload et garantit qu'un audio n'est
jamais perdu si le visiteur ferme l'onglet.

**La réécoute se fait sur le blob local**, jamais sur le fichier remonté :
instantané, sans re-téléchargement, et fonctionne même si le réseau est mauvais.

Si le POST échoue, l'écran de publication n'est pas atteint : le blob reste en
mémoire et un bouton « réessayer » est affiché. **Aucun réessai automatique
silencieux** — le visiteur doit savoir où en est son enregistrement.

### Formats audio

**On accepte tel quel ce que le navigateur envoie** — `webm/opus` sur Chrome et
Android, `mp4/aac` sur iOS, `ogg/opus` sur Firefox, et tout ce qui viendra
ensuite. **Aucune liste blanche de formats** : elle rejetterait un navigateur
minoritaire sans que personne s'en aperçoive. ffmpeg normalise ensuite en
AAC/m4a, le seul format lu partout, Safari compris.

### Garde-fou de durée

À `duree_max_secondes` (600 par défaut), **le client arrête `MediaRecorder`** et
affiche un message. Le serveur, lui, **accepte ce qui lui arrive, même au-delà** :
cohérent avec la règle « ne jamais perdre un audio », et un client bridé ne
protège pas d'un fichier forgé — c'est le rôle du throttle (§12), pas d'un
rejet qui détruirait un enregistrement.

### Contrainte absolue

**HTTPS obligatoire.** Sans lui, pas d'accès au micro : la borne ne fonctionne
pas du tout.

---

## 7. Page de lecture

`/c/<uuid>` — publique, sans authentification.

### L'autoplay est impossible

iOS et Android bloquent la lecture audio non muette tant que l'utilisateur n'a
pas interagi avec la page. C'est une protection anti-publicité, sans dérogation.
**Un passant qui scanne arrivera toujours sur une page silencieuse.**

Le travail se déplace donc sur le fait de **donner envie d'appuyer** : un unique
bouton occupant l'écran, la photo en fond, le pseudo, les tags, la durée annoncée
honnêtement — et rien d'autre.

### Selon le statut

| Statut | Comportement |
|---|---|
| `publiee` | La page normale. |
| `retiree` | Une page sobre : « cette capsule a été retirée ». **Jamais un 404 nu** — le ticket est dans la rue, son porteur mérite une explication. |
| `brouillon` | 404. Aucun ticket n'existe pour une capsule jamais publiée. |

### Transcription affichée

Quand elle existe, la transcription est affichée **colorée par locuteur**. Ce
n'est pas décoratif : c'est ce qui rend une capsule accessible à un passant sourd,
ou à quelqu'un sans écouteurs dans un lieu bruyant.

Si l'enrichissement a échoué ou n'est pas terminé, la page fonctionne sans.

### Pied de page

Un lien discret vers `/mentions-legales`, qui porte l'éditeur, l'adresse de
contact et la procédure de signalement. C'est le support technique de
l'obligation LCEN décrite au §12.

---

## 8. Le ticket

C'est, avec la page de lecture, l'endroit où se joue le projet. Il n'y a pas de
mystère technique ici, uniquement du design.

Contenu, de haut en bas :

1. La **photo tramée** si elle existe
2. Une **phrase amorce** : pseudo, tags, durée
3. Le **QR** vers `/c/<uuid>` (`appendQRcode`, natif)
4. Une ligne d'identité du projet

**Le tramage doit être explicite :** `appendImage(..., mode=DIFFUSE_DITHER)`. Le
défaut du pilote est `THRESHOLD_DITHER`, un simple seuillage qui transforme une
photo en aplats noirs illisibles. `DIFFUSE_DITHER` est une vraie diffusion
d'erreur Floyd-Steinberg (7/16, 5/16, 3/16, 1/16).

Personne ne scanne un carré noir anonyme sur un mur en 2026 : la méfiance envers
les QR codes est aujourd'hui la norme. Ce qui déclenche le scan, c'est ce qu'il y
a autour du carré.

---

## 9. Impression Sunmi

### Protocole (mode push direct)

```
POST https://openapi.sunmi.com/v2/printer/open/open/device/pushContent
Headers : Sunmi-Appid, Sunmi-Timestamp, Sunmi-Nonce, Sunmi-Sign, Source: openapi
Sign    = HMAC-SHA256(body + app_id + timestamp + nonce, clé = app_key)
body.content = ESC/POS encodé en hexadécimal
```

Autres appels sortants utiles : `onlineStatus(sn)`, `printStatus(trade_no)`,
`clearPrintJob(sn)`, `pushVoice(sn, content)` — cette dernière fait sonner
l'imprimante, ce qui attire le passant suivant.

Contrepartie du mode push : le contenu du ticket transite chez Sunmi (voir §12).

### Architecture d'impression (reprise de Lespass)

Lespass a fait évoluer le code de LaBoutik vers un **pattern Strategy** que l'on
reprend, parce qu'il résout exactement nos besoins :

| Fichier | Rôle |
|---|---|
| `impression/base.py` | `PrinterBackend` : trois méthodes. Pas d'ABC ni de metaclass — une simple classe avec `NotImplementedError`, plus lisible. |
| `impression/escpos_builder.py` | `construire_le_ticket(capsule) -> bytes`. **La construction du ticket est séparée de son envoi.** |
| `impression/sunmi_cloud.py` | Backend réel : HMAC SHA256, `pushContent`. |
| `impression/mock.py` | Backend de test. |
| `impression/sunmi_cloud_printer.py` | Pilote bas niveau, vendorisé (824 lignes). |

**`can_print()` avant d'essayer.** Chaque backend vérifie ses préconditions —
numéro de série présent, credentials configurés — et renvoie un message explicite
plutôt que d'échouer au milieu d'un envoi. Complémentaire de `onlineStatus`, qui
teste l'état réseau et non la configuration.

**Le mock n'est pas un bouchon, c'est un test de bout en bout.** Il construit
**les mêmes octets ESC/POS** que le backend réel, puis les décode en texte
lisible affiché dans la console Celery. Si le ticket est lisible là, il sera
lisible sur le papier. C'est aussi le meilleur outil pour travailler la mise en
page du ticket sans consommer de rouleau.

**Credentials.** Lespass les chiffre en base avec Fernet parce qu'il est
multi-tenant. Clameur est mono-tenant : variables d'environnement, point.

### Le pilote bas niveau

`sunmi_cloud_printer.py` (824 lignes, éprouvé en production) est **vendorisé tel
quel**. C'est un pilote, pas de la logique métier : le réécrire serait absurde et
risqué.

**Quatre corrections obligatoires avant usage :**

1. **`requests.post()` n'a aucun `timeout`.** Dans un worker Celery, un appel qui
   ne répond jamais bloque le worker indéfiniment. Seul défaut réellement
   dangereux.
2. `print()` en dur dans `httpPost` → `logger`.
3. Le code réseau ignore le code HTTP et le statut applicatif Sunmi. Sans
   correction, `echoue` n'est jamais atteint et un job raté passe pour envoyé.
4. **`onlineStatus()`, `printStatus()` et `clearPrintJob()` ne retournent rien** —
   la réponse est seulement affichée. Elles doivent rendre le JSON parsé à
   l'appelant, sans quoi ni le contrôle d'état du §6 ni celui du §5 ne sont
   réalisables.

Le SN est passé en paramètre au pilote. À défaut il le lit dans l'environnement
et lève `ValueError` à l'initialisation — comportement à ne pas subir par
accident.

---

## 10. Enrichissement (`capsules/tasks.py`)

Trois tâches Celery, **chacune idempotente et rejouable depuis la console** :

```
transcrire   Voxtral, diarisation activée
taguer       Mistral small → tags machine (TagDeCapsule, origine=machine)
embarquer    mistral-embed → vecteur 1024 dimensions sur transcription_texte
```

La normalisation ffmpeg n'est pas ici : elle est synchrone dans la vue de
publication (voir I1).

### Contraintes de l'API Mistral, apprises sur Hypostasia

Ces trois règles sont non négociables, elles ont déjà coûté du temps ailleurs :

1. `diarize=True` **exige** `timestamp_granularities=["segment"]`.
2. `language` et `timestamp_granularities` sont **incompatibles**. Puisqu'on
   diarise, **on ne peut pas forcer la langue** : détection automatique
   obligatoire. Dans l'espace public c'est un avantage — une capsule en créole ou
   en arabe sera transcrite sans rien déclarer.
3. La clé se lit dans `os.environ["MISTRAL_API_KEY"]`, **jamais en base**.

Appel : SDK `mistralai`, `client.audio.transcriptions.complete()`.

### Coûts

Voxtral : 0,003 $/minute, diarisation incluse. Mille capsules d'une minute
coûtent 0,30 $. Le coût n'est pas un facteur de conception.

---

## 11. Console opérateur

**En v1, la console est l'admin Django.** Pas de vue dédiée : l'opérateur est un
administrateur authentifié, présent sur place, et l'admin fournit déjà les
listes, les filtres et les actions.

Liste fermée des actions attendues :

| Action | Sur |
|---|---|
| Retirer une capsule (kill switch) / la republier | `Capsule` |
| Relancer un `JobImpression` resté `en_attente` ou `echoue` | `JobImpression` |
| Interroger `printStatus(trade_no)` en cas de doute | `JobImpression` |
| Rejouer `transcrire`, `taguer`, `embarquer` sur une capsule | `Capsule` |
| Activer / désactiver une borne | `Borne` |
| Purger les brouillons abandonnés | commande de gestion |

Le mot « console » désigne cet écran dans tout le document ; « admin » n'est pas
employé pour autre chose.

---

## 12. Modes dégradés, sécurité, données

### Modes dégradés

| Panne | Comportement |
|---|---|
| Mistral indisponible | Capsule publiée et écoutable, non enrichie, erreur visible en console. Rejouable. |
| ffmpeg échoue | Capsule publiée, la page sert `audio_original`, erreur en console, étape rejouable. |
| Sunmi indisponible | Capsule publiée, job `en_attente`, message « ton ticket sortira dans un instant », relance depuis la console. |
| Imprimante hors ligne | Détecté par `onlineStatus` au rendu de `/b/<slug>`, **avant** de promettre un ticket. |
| Redis mort | Publication et lecture continuent. Le `JobImpression` reste `en_attente` et l'enrichissement ne part pas ; les deux se relancent depuis la console. Il n'y a **pas** de tâche périodique de rattrapage : l'opérateur est présent (D1), et un beat pour un cas de panne rare serait de la complexité non gagnée. |
| Réseau du visiteur défaillant | Bouton « réessayer », blob conservé en mémoire, jamais de perte silencieuse. |

### Vie privée et obligations

- **Statut d'hébergeur (LCEN).** Le projet héberge de la parole publique sous
  pseudo. Obligation de retrait prompt après signalement : le kill switch de la
  console est le moyen technique de cette obligation, et `/mentions-legales`
  porte l'adresse de contact.
- **EXIF des photos purgés à l'ingestion.** Une photo prise au téléphone embarque
  très souvent des coordonnées GPS. Publiée telle quelle, elle **géolocalise la
  borne, et parfois son auteur** — ce qui contredirait frontalement la promesse
  du §2. On retire toutes les métadonnées, en appliquant au préalable
  l'orientation pour ne pas afficher la photo de travers.
- **Dette D4 — pas de code d'effacement en v1.** Sans compte ni code de
  rétractation, une demande de suppression passe nécessairement par un contact
  humain et la console. Tenable, mais à traiter en v2.
- **Le contenu du ticket transite chez Sunmi**, sous-traitant probablement hors
  UE. Aujourd'hui il ne contient qu'une URL, un pseudo et des tags, et il est
  destiné à être collé dans la rue. **Si un extrait de transcription y était
  ajouté un jour, ce serait de la parole de tiers passant par ce sous-traitant** —
  à reconsidérer à ce moment-là.
- **Secrets** : `MISTRAL_API_KEY`, `APP_ID`, `APP_KEY` en variables
  d'environnement uniquement, jamais en base, jamais versionnés. Le numéro de
  série de l'imprimante n'en est pas un : il vit sur la `Borne`.
- **UUID non énumérables** pour empêcher le parcours exhaustif du corpus.

### Anti-abus

Le QR de l'affiche se photographie, et `/b/<slug>` fonctionne depuis n'importe
où : sans garde-fou, quelqu'un peut faire cracher des tickets en continu et vider
le rouleau. **Throttle par IP et par session sur la création et sur la
publication**, via le cache Django. `active=False` ne protège que hors événement.

### Brouillons abandonnés

Enregistrer sans publier laisse une `Capsule(brouillon)` et son audio. Une
**commande de gestion** purge ceux de plus de 24 h ; l'opérateur la lance en fin
d'événement. Pas de tâche périodique : même raison que ci-dessus.

---

## 13. Tests

Deux backends Mock, repris d'Hypostasia pour la transcription et de Lespass pour
l'impression. Toute la chaîne doit être testable sans clé Mistral et sans
imprimante branchée — sinon personne ne lance la suite.

Couverture attendue :

- **Les trois invariants I1, I2, I3** : une capsule publiée est écoutable et son
  `audio_diffusion` existe ; elle reste publiée quand Redis est mort ; elle reste
  publiée quand l'imprimante est absente. **Ce sont les tests les plus importants
  du projet.**
- Machine à états de `JobImpression`, sans matériel.
- Construction du ticket : vérifier les octets ESC/POS produits, sans envoi.
- Signature HMAC : vecteur de test figé.
- Purge EXIF : une photo avec GPS entre, une photo sans métadonnées sort.
- Page de lecture selon les trois statuts.
- Enrichissement avec réponses Mistral mockées, y compris les échecs.

L'implémentation suivra le skill `djc` : noms explicites, i18n dès l'écriture,
accessibilité réelle sur la page de lecture — consultée debout, dehors, au
soleil, par des gens pressés.

---

## 14. Vérification matérielle

Aucune inconnue sur le protocole : le code de LaBoutik et de Lespass a répondu à
tout.

Reste une vérification à faire **en première tâche du plan** : imprimer un ticket
de test avec un QR figé sur la vraie machine, avant d'écrire la moindre ligne de
modèle Django. Le README de LaBoutik annonce 384 dots pour du 80 mm quand ses
propres tests utilisent 576 ; `dots_par_ligne` reste donc configurable sur la
Borne, avec 576 par défaut.

### Environnement

Le poste dispose de Python 3.14, uv, Docker et node, mais **ni ffmpeg, ni
PostgreSQL, ni Redis**. PostgreSQL + pgvector et Redis passent par
`docker-compose`, comme sur Hypostasia ; ffmpeg est une dépendance de l'image
web, pas du poste.
