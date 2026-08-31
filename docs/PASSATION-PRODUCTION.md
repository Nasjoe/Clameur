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

## 2. Prérequis

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

Le **numéro de série de l'imprimante n'est pas ici** : il se saisit sur la
`Borne` depuis la console. Ce n'est pas un secret.

## 4. Déployer

```bash
uv lock                                          # 1
docker compose -f docker-compose-prod.yml build  # 2
docker compose -f docker-compose-prod.yml up -d  # 3
docker compose -f docker-compose-prod.yml exec web python manage.py migrate
docker compose -f docker-compose-prod.yml exec web python manage.py createsuperuser
```

**Étape 1 — `uv lock` n'est pas optionnel.** Le Dockerfile fait
`uv sync --frozen`, qui installe le fichier de verrouillage tel quel. Un
`pyproject.toml` modifié sans relock installe **l'ancien jeu de dépendances,
sans le moindre message**.

**Note sur `exec` :** dans les conteneurs de production, les commandes
s'appellent directement (`python manage.py …`), **jamais via `uv run`**. Un
wrapper `uv` intercepterait le `SIGTERM` destiné au worker Celery ; c'est aussi
pourquoi `supervisord.conf` n'en utilise nulle part.

`collectstatic` **est déjà fait au build** — n'y reviens pas.

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
`https://<domaine>/b/<slug-de-la-borne>` et vérifie que le bouton demande
l'accès au micro. C'est le seul test qui compte vraiment.

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
  python manage.py tester_l_imprimante <slug-de-la-borne>
```

La commande vérifie la configuration, interroge l'imprimante, imprime, puis
liste ce qu'il faut contrôler sur le papier. **Le point encore incertain est
`dots_par_ligne`** : 576 pour du 80 mm, 384 pour du 58 mm. Le README du pilote
d'origine annonce 384 pour du 80 mm là où ses propres tests utilisent 576. Si
le texte est coupé sur les bords, change la valeur sur la `Borne`.

L'affiche à imprimer, avec son QR, est sur `/b/<slug>/affiche` — réservée au
personnel, `Ctrl+P`, A4, marges « aucune », arrière-plans activés.

**Après chaque vague d'enrichissement**, recalcule le ciel :

```bash
docker compose -f docker-compose-prod.yml exec web \
  python manage.py projeter_la_constellation
```

Une projection est **globale** : une nouvelle clameur déplace toutes les
autres. La commande affiche la variance expliquée ; si elle s'effondre et que
les étoiles forment une bouillie, c'est le signal de passer de la PCA à t-SNE
(ce qui demanderait `scikit-learn`, aujourd'hui absent volontairement).

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

## 8. En cas de panne

| Symptôme | Où regarder |
|---|---|
| Le bouton du micro ne fait rien | HTTPS et `X-Forwarded-Proto`. C'est presque toujours ça. |
| Lecteur audio bloqué à `0:00 / 0:00` | type MIME du `.m4a`, puis les requêtes `Range` (§5 d–e) |
| Les transcriptions n'arrivent plus en direct | daphne redémarré depuis la dernière modification des consumers ? |
| Aucun ticket ne sort | `SUNMI_APP_ID` / `SUNMI_APP_KEY` présents ? Sinon le backend de simulation prend la main et écrit dans les journaux. |
| Capsules publiées mais jamais enrichies | `MISTRAL_API_KEY`, puis `docker compose logs celery` |
| Le ciel est vide | `projeter_la_constellation` a-t-il tourné ? Une capsule sans position n'a pas d'étoile. |
| Une page se comporte comme une version antérieure | statiques en cache : les fichiers portent leur empreinte, donc c'est un `collectstatic` manquant après un changement de code |

**Rien n'est perdu quand une dépendance tombe.** Les invariants garantissent
qu'une capsule publiée reste écoutable même si Redis, Mistral et l'imprimante
sont tous en panne. La base est la source de vérité, jamais la file.
