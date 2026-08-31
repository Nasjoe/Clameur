# Clameur

Enregistre une capsule sonore depuis ton téléphone. Repars avec un ticket
imprimé qui porte un QR code. Colle-le où tu veux. Celui qui le trouve scanne,
et t'écoute.

> Les *clameurs*, dans *La Zone du Dehors* d'Alain Damasio (1999), sont des
> poèmes déposés dans les rues de Cerclon — un tract sonore comme forme de
> résistance. Ce projet leur emprunte son nom et son geste.

**Licence : AGPL-3.0.**

---

## Le parcours

```
Affiche (QR fixe)  →  /b/<borne>  ←  le téléphone du visiteur
   ↓ il parle, il se réécoute, il choisit un pseudo et deux mots-clés
   ↓ publier
   ├─→ un ticket sort de l'imprimante thermique posée à côté
   └─→ transcription, mots-clés et vecteur, en tâche de fond
Le ticket porte le QR de /c/<uuid>  →  la page d'écoute
```

Le visiteur enregistre **avec son propre téléphone** : la borne n'est qu'une
affiche et une imprimante. Pas de micro à nettoyer, pas d'écran à protéger.

## La constellation

La page d'accueil montre les clameurs deux fois, côte à côte : une liste à
gauche, un ciel à droite. Chaque étoile est une capsule, placée par proximité
**sémantique** — deux clameurs voisines parlent de la même chose.

Cliquer une étoile fait défiler la liste jusqu'à sa fiche et lance la lecture ;
cliquer une fiche illumine son étoile.

Les positions sont **calculées une fois et stockées**. Une projection est
globale : la recalculer à chaque visite déplacerait toutes les étoiles, et on
ne pourrait plus revenir à une clameur repérée la veille.

## Trois invariants

Ils tiennent une seule promesse : **un ticket déjà collé sur un mur ne doit
jamais mener à une page vide.**

| | |
|---|---|
| **I1** | Une capsule publiée est immédiatement écoutable sur tous les navigateurs. La normalisation ffmpeg est synchrone. |
| **I2** | La publication ne dépend jamais de Celery. Si Redis est mort, la capsule est publiée et le ticket attend une relance. |
| **I3** | La publication ne dépend jamais de l'imprimante. |

`tests/test_invariants.py` les vérifie. Ce sont les tests les plus importants
du projet.

## Démarrer

**Docker, et rien d'autre.** Ni Python, ni uv, ni ffmpeg, ni PostgreSQL sur
le poste : tout vit dans les conteneurs.

```bash
cp .env.example .env
make fixture     # migre, crée 100 clameurs de démonstration, puis lance le serveur
```

- Constellation : http://localhost:8000/
- Borne : http://localhost:8000/b/place-du-marche
- Console : http://localhost:8000/admin/ (`make console` pour créer un compte)

Sans clé Mistral, l'enrichissement échoue proprement : la capsule reste
publiée et écoutable. Sans identifiants Sunmi, l'impression bascule sur un
backend de simulation qui écrit le ticket dans les journaux — **avec les mêmes
octets ESC/POS** que la vraie imprimante :

```
docker compose logs -f celery | grep -A 20 "Ticket (mock)"
```

| Commande | |
|---|---|
| `make run` | serveur + worker, en `DEBUG` |
| `make test` | les 76 tests |
| `make fixture` | corpus de démonstration puis serveur |
| `make constellation` | recalcule les positions du ciel |
| `make imprimante` | ticket de test sur une vraie Sunmi |
| `make console` | crée un compte opérateur |
| `make rebuild` | après ajout d'une dépendance |

## Architecture

Trois applications Django.

| | |
|---|---|
| `bornes` | La `Borne` : elle relie une affiche, une imprimante et des réglages. Le slug du QR est le seul moyen, pour le téléphone du visiteur, de désigner l'imprimante posée à côté de lui. |
| `capsules` | Le cœur : modèles, capture, lecture, constellation, enrichissement, WebSocket. |
| `impression` | Pilote Sunmi et file de tickets, isolés pour être testables sans matériel. |

**Stack** — Django 6, Celery, Channels, HTMX, JavaScript vanilla, PostgreSQL +
pgvector, Redis, ffmpeg, Mistral (Voxtral pour la transcription diarisée,
`mistral-embed` pour les vecteurs), imprimante Sunmi Cloud en mode push.

En production : Traefik → nginx → gunicorn, avec daphne pour les WebSocket,
le tout tenu par supervisord. Voir [`docs/PASSATION-PRODUCTION.md`](docs/PASSATION-PRODUCTION.md).

## Design

Le système visuel est dans `capsules/static/capsules/tokens.css`, portable tel
quel. Papier brun chaud, Bricolage Grotesque et Plus Jakarta Sans (vendorisées,
aucune requête vers un tiers), et un composant signature — **la porte** : une
ombre dure et décalée dans laquelle l'objet s'enfonce au survol.

## Vie privée

Ni compte, ni cookie de suivi, ni position. Le site conserve l'enregistrement,
la photo éventuelle, le pseudo et les mots-clés saisis. **Les métadonnées EXIF
des photos sont supprimées à l'ingestion** : une photo de téléphone porte
souvent des coordonnées GPS, qui trahiraient l'emplacement de la borne.

Le projet est hébergeur au sens de la LCEN : la console opérateur porte un
retrait immédiat par capsule.

## État

Le logiciel tourne et il est testé. **Il n'a pas encore servi sur le terrain.**
Deux choses n'ont jamais été exercées en vrai : l'impression sur une NT311
physique, et un événement avec de vrais visiteurs.
