# Passation — mise en production de Clameur

Ce document s'adresse à qui déploie Clameur sur le serveur, humain ou agent.
Il suppose que tu ne connais pas le projet. Lis-le en entier avant de lancer
quoi que ce soit : plusieurs pièges ci-dessous **échouent en silence**.

---

## 0. Règles de la maison

**Aucune commande `git` sans l'accord explicite du mainteneur.** Cela inclut
`git checkout --`, `git stash`, `git reset --hard`, `git restore --`,
`git clean -f`, autant que `commit`, `add` ou `push`. Le dépôt peut contenir
des heures de travail non commité.

**Jamais de mention `Co-Authored-By` dans un commit.**

Ne lance pas `ruff format` ni `ruff check --fix` sur des fichiers existants :
`--fix` supprime les imports à effet de bord, dont `clameur/__init__.py` qui
enregistre l'application Celery — sa disparition rend `.delay()` silencieux.

---

## 1. Ce que tu déploies

Une application Django qui enregistre des capsules sonores, imprime un ticket
avec un QR code sur une imprimante thermique, et affiche le corpus dans une
carte sémantique. Le README à la racine décrit le produit ; ce fichier ne
parle que du déploiement.

**Architecture de production :**

```
Traefik (TLS, réseau `frontend`)
   └── nginx        sert /static/ et /medias/, aiguille le reste
         ├── /ws/   → daphne   : 8002   WebSocket
         └── /      → gunicorn : 8001   pages
       supervisord tient gunicorn, daphne et le worker Celery
       db : postgres + pgvector      redis : file Celery + couche de canaux
```

## 2. Prérequis et données

**La base et les enregistrements vivent sur le disque**, dans `donnees/`, et
non dans des volumes Docker nommés :

```
donnees/postgres/   la base
donnees/medias/     les enregistrements et les photos
```

C'est délibéré. Un volume nommé vit dans les entrailles de Docker : on ne sait
pas où il est, `docker volume prune` l'emporte sans prévenir, et le sauvegarder
demande de passer par un conteneur. Ici, `pg_dump` et `rsync` y accèdent
directement, et une suppression est un geste conscient.

**`donnees/medias/` est ce qui ne se régénère pas.** La base se reconstruit à
partir d'un dump, les fichiers statiques se recompilent, les vecteurs se
recalculent — les voix des gens, non. C'est le dossier à sauvegarder en premier,
et c'est l'objet du §8.



- Docker et le plugin Compose.
- **La stack TraefikV3 doit tourner**, avec son réseau externe `frontend` et
  un `certresolver` nommé `myresolver`. Vérifie :
  ```bash
  docker network inspect frontend >/dev/null && echo "réseau frontend : ok"
  ```
- Un enregistrement DNS qui pointe le domaine vers ce serveur.

## 3. Le fichier `.env`

Copie `.env.example` en `.env` et renseigne :

| Variable | |
|---|---|
| `DEBUG` | **`false`.** En `true` tu exposerais les traces d'erreur et désactiverais les empreintes de fichiers statiques. |
| `SECRET_KEY` | une valeur aléatoire longue, propre à ce serveur |
| `DOMAIN` | le domaine, sans schéma. Il alimente Traefik, `ALLOWED_HOSTS` et le CSRF. |
| `URL_PUBLIQUE` | `https://<domaine>` — **schéma compris**. Elle est encodée dans le QR de chaque ticket : une erreur ici imprime des tickets morts, et le papier est déjà distribué. |
| `POSTGRES_*` | un mot de passe solide, pas celui de l'exemple |
| `MISTRAL_API_KEY` | facultative. Sans elle, les capsules restent publiées et écoutables, simplement sans transcription. |
| `SUNMI_APP_ID`, `SUNMI_APP_KEY` | facultatives. Sans elles, l'impression bascule sur un backend de simulation qui écrit le ticket dans les journaux. |

Le **numéro de série de l'imprimante n'est pas ici** : il se saisit dans les
`Réglages` depuis la console. Ce n'est pas un secret.

## 4. Déployer

Docker est le seul prérequis du serveur : ni Python, ni uv, ni ffmpeg à
installer.

```bash
make start                       # DEBUG=false ⇒ pile de production
make console                     # crée le compte opérateur
```

`make start` lit `DEBUG` dans le `.env` : à `false`, il construit les images,
démarre la pile, migre et lance `check --deploy`. Il ne crée **jamais** de
fixtures — on ne fabrique pas de fausses clameurs sur un site public.

L'équivalent à la main, si tu préfères voir chaque étape :

```bash
docker compose -f docker-compose-prod.yml up -d --build
docker compose -f docker-compose-prod.yml exec web python manage.py migrate
docker compose -f docker-compose-prod.yml exec web python manage.py check --deploy
```

**`check --deploy` refuse de passer** tant que `EDITEUR` et `CONTACT` ne sont
pas renseignés : sans eux, personne ne peut signaler une clameur, alors que
c'est le moyen technique de l'obligation de retrait de la LCEN. Il avertit
aussi si `URL_PUBLIQUE` n'est pas en `https`.

**Ne modifie pas `pyproject.toml` sur le serveur.** Le Dockerfile fait
`uv sync --frozen`, qui installe `uv.lock` tel quel : un `pyproject.toml`
modifié sans relock préalable installerait **l'ancien jeu de dépendances, sans
le moindre message**. Le verrouillage se fait sur la machine de développement
(`make rebuild`), et le dépôt arrive ici avec un `uv.lock` à jour.

**Les commandes s'appellent directement** (`python manage.py …`), jamais via
`uv run` : les binaires du venv sont dans le `PATH` de l'image, et un wrapper
`uv` intercepterait le `SIGTERM` destiné au worker Celery. C'est aussi pourquoi
`supervisord.conf` n'en utilise nulle part.

`collectstatic` tourne **à chaque démarrage** du conteneur, dans
`entrypoint-prod.sh`. Ce n'est pas une redondance avec le build : Docker ne
recopie l'image dans un volume nommé que si celui-ci est **vide**, donc au
tout premier `up` seulement. Sans ce passage, chaque redéploiement servirait
les fichiers statiques de la version précédente, en silence.

## 5. Vérifier

Dans l'ordre. Chaque commande a une sortie attendue.

```bash
# a. les quatre services tournent
docker compose -f docker-compose-prod.yml ps

# b. supervisord tient bien ses trois process
docker compose -f docker-compose-prod.yml logs web | grep "spawned"
#    attendu : gunicorn, daphne, celery_worker

# c. la page répond
curl -s -o /dev/null -w "%{http_code}\n" https://$DOMAIN/          # 200

# d. LE TYPE MIME DE L'AUDIO — sinon lecteur muet à « 0:00 / 0:00 »
#    (remplace <un-fichier> par un vrai chemin, visible dans l'admin)
curl -sI https://$DOMAIN/medias/<un-fichier>.m4a \
  | grep -i content-type                                          # audio/mp4

# d bis. LE TYPE MIME DES POLICES — sinon le préchargement est ignoré
curl -sI https://$DOMAIN/static/capsules/polices/plus-jakarta-sans-latin.woff2 \
  | grep -i content-type                                          # font/woff2

# e. LES REQUÊTES RANGE — sinon le lecteur audio reste bloqué
curl -s -o /dev/null -w "%{http_code}\n" -H "Range: bytes=0-99" \
  https://$DOMAIN/medias/<un-fichier>.m4a                         # 206

# f. le WebSocket monte
curl -s -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "Origin: https://$DOMAIN" https://$DOMAIN/ws/constellation | head -1
#    attendu : HTTP/1.1 101 Switching Protocols
```

Puis, dans un navigateur, sur **un vrai téléphone** : ouvre
`https://<domaine>/nouvelle` et vérifie que le bouton demande l'accès au
micro. C'est le seul test qui compte vraiment.

## 6. Les pièges

Ils ont tous été rencontrés pendant le développement. Aucun ne produit
d'erreur visible.

**HTTPS ou rien.** Les navigateurs refusent le micro hors contexte sécurisé.
Un certificat auto-signé ne suffit pas. Sans HTTPS valide, **la borne ne
fonctionne pas du tout** — le bouton échoue, sans explication.

**`X-Forwarded-Proto` doit arriver jusqu'à Django.** Sans lui, Django se croit
en HTTP derrière le TLS de Traefik : les POST sont rejetés par le CSRF et la
page est jugée non sécurisée, donc **micro refusé**. C'est réglé dans
`nginx/clameur.conf` et `SECURE_PROXY_SSL_HEADER` ; ne les touche pas.

**Daphne ne recharge jamais les consumers.** Après toute modification de
`capsules/consumers.py`, un message d'un type inconnu est **silencieusement
ignoré** : les journaux montrent la diffusion, mais rien n'arrive aux
navigateurs. Redémarre daphne, ou le conteneur `web`.

**Les deux fichiers Compose portent des noms de projet différents**, et c'est
un garde-fou. Sans `name:` en tête, Compose déduit le nom du dossier : les deux
fichiers en réclamaient le même, et **`make test` lancé sur le serveur recréait
les conteneurs `db` et `redis` de production avec la définition de
développement** — un volume nommé vide à la place du bind mount, et le site en
erreur 500. Les données restaient sur le disque, mais plus personne ne les
servait. Ne retire jamais ces deux lignes `name:`.

**`donnees/` est exclu du contexte de build** (`.dockerignore`). Sans cette
ligne, `docker compose build` **échoue** : les fichiers de PostgreSQL
appartiennent à l'utilisateur du conteneur, en 0700, et le démon ne peut pas
les lire pour constituer le contexte.

**Un `build` seul ne suffit pas.** Les conteneurs déjà lancés continuent de
tourner sur l'ancienne image. Il faut `up -d --force-recreate web`.

**Types MIME.** `.m4a` et `.woff2` sont déclarés côté Django *et* dans
`nginx/clameur.conf`. Un `.m4a` servi en `application/octet-stream` donne un
lecteur muet affichant `0:00 / 0:00`, sur un fichier pourtant valide.

**`gzip off` sur `/medias/`.** Compresser ferait sauter `Accept-Ranges`, et le
lecteur média du navigateur se bloquerait.

**Les délais.** `--timeout 120` sur gunicorn et `proxy_read_timeout 180s` sur
nginx : la publication est **synchrone** et appelle ffmpeg. Le défaut de 30 s
tuerait le worker au milieu d'une capsule longue, et le visiteur perdrait sa
voix.

## 7. Exploitation

**Avant un événement**, sur la vraie imprimante :

```bash
docker compose -f docker-compose-prod.yml exec web \
  python manage.py tester_l_imprimante
```

La commande vérifie la configuration, interroge l'imprimante, imprime, puis
liste ce qu'il faut contrôler sur le papier. **Le point encore incertain est
`dots_par_ligne`** : 576 pour du 80 mm, 384 pour du 58 mm. Le README du pilote
d'origine annonce 384 pour du 80 mm là où ses propres tests utilisent 576. Si
le texte est coupé sur les bords, change la valeur dans les `Réglages`.

L'affiche à imprimer, avec son QR, est sur `/affiche` — réservée au
personnel, `Ctrl+P`, A4, marges « aucune », arrière-plans activés.

**Le ciel est en sommeil depuis le 2026-09-01.** La page d'accueil est la
liste des clameurs, avec sa recherche ; elle ne dépend d'aucun calcul, et une
clameur y figure dès sa publication. Il n'y a donc plus rien à recalculer après
une vague d'enrichissement.

La commande reste là pour le jour où le ciel reviendra, et elle fonctionne
encore sur les vecteurs déjà en base :

```bash
docker compose -f docker-compose-prod.yml exec web \
  python manage.py projeter_la_constellation
```

Mais **plus rien ne calcule de nouveaux vecteurs** : la tâche `embarquer` n'est
plus enfilée derrière la transcription. Seules la transcription, le titre et
les mots-clés partent en tâche de fond.

**En fin d'événement**, purge les enregistrements jamais publiés :

```bash
docker compose -f docker-compose-prod.yml exec web \
  python manage.py purger_les_brouillons              # annonce seulement
docker compose -f docker-compose-prod.yml exec web \
  python manage.py purger_les_brouillons --pour-de-vrai
```

**La console** (`/admin/`) porte le retrait immédiat d'une capsule — le moyen
technique de l'obligation de retrait prompt de la LCEN —, la relance d'un
ticket, et le rejeu de l'enrichissement.

Le mode push de Sunmi n'a **pas de rappel** : le serveur ne sait pas si le
papier est sorti. En cas de doute, l'action « Interroger Sunmi » sur un
`JobImpression` appelle `printStatus`.

## 8. Sauvegarde

Elle est en place dans [`sauvegarde/`](../sauvegarde), qui a son propre README.
C'est le kit borgwarehouse, adapté à cette pile. Une archive quotidienne part
sur `borgwarehouse.codecommun.coop` ; elle contient le dump PostgreSQL, les
médias, le `.env` et le compose — **de quoi remonter le site de zéro**.

```bash
cd sauvegarde
make check     # la dernière sauvegarde est-elle restaurable ?
make essai     # la restaurer POUR DE VRAI, dans une base jetable
```

**`make essai` avant chaque événement.** Il restaure la dernière archive à côté
de la base en service, compare les lignes table par table et les médias octet
pour octet, puis efface tout. Une sauvegarde qu'on n'a jamais restaurée n'est
pas une sauvegarde, c'est une intention.

**Ce que la sauvegarde ne peut pas sauvegarder elle-même** : la passphrase du
dépôt, sa clé exportée et son adresse. Elles vivent au coffre-fort. Sans elles,
les archives sont un bloc chiffré définitivement illisible.

Le second filet est chez borgwarehouse : il envoie un mail si le dépôt ne reçoit
plus rien. Un cron qui échoue en silence, c'est un backup qui n'existe pas.

## 9. En cas de panne

| Symptôme | Où regarder |
|---|---|
| Le bouton du micro ne fait rien | HTTPS et `X-Forwarded-Proto`. C'est presque toujours ça. |
| Lecteur audio bloqué à `0:00 / 0:00` | type MIME du `.m4a`, puis les requêtes `Range` (§5 d–e) |
| Les transcriptions n'arrivent plus en direct | daphne redémarré depuis la dernière modification des consumers ? |
| Aucun ticket ne sort | `SUNMI_APP_ID` / `SUNMI_APP_KEY` présents ? Sinon le backend de simulation prend la main et écrit dans les journaux. |
| Capsules publiées mais sans titre ni transcription | `MISTRAL_API_KEY`, puis `docker compose logs celery` |
| Une clameur publiée n'apparaît pas sur l'accueil | Est-elle bien `publiee` et non `retiree` ? La liste ne dépend de rien d'autre. |
| borgwarehouse a envoyé un mail : plus de sauvegarde | `cd sauvegarde && make check`, puis `crontab -l` |
| Une page se comporte comme une version antérieure | le volume `statiques` n'a pas été rafraîchi : vérifie que `entrypoint-prod.sh` s'exécute bien au démarrage (`docker compose logs web \| head`) |

**Rien n'est perdu quand une dépendance tombe.** Les invariants garantissent
qu'une capsule publiée reste écoutable même si Redis, Mistral et l'imprimante
sont tous en panne. La base est la source de vérité, jamais la file.
