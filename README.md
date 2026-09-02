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
Affiche (QR fixe)  →  /nouvelle   ←  le téléphone du visiteur
   ↓ il parle, il se réécoute, il choisit un pseudo et deux mots-clés
   ↓ publier
   ├─→ un ticket sort de l'imprimante thermique posée à côté
   └─→ transcription, titre et mots-clés, en tâche de fond
Le ticket porte le QR de /c/<uuid>  →  la page d'écoute
```

Le visiteur enregistre **avec son propre téléphone** : la borne n'est qu'une
affiche et une imprimante. Pas de micro à nettoyer, pas d'écran à protéger.

## La liste

La page d'accueil est **la liste des clameurs**, la plus récente d'abord, en une
colonne centrée qui se lit aussi bien sur un téléphone que sur un écran large.
Une clameur y figure **dès sa publication** : la page ne dépend d'aucun calcul.

Un champ de recherche cherche dans les titres, les pseudos, les mots-clés et
les transcriptions. La requête vit dans l'adresse — `/?q=boulangerie` se
partage et se recharge — et la liste se met à jour sans rechargement.

Chaque clameur porte un bouton qui copie son lien : c'est ce lien-là qu'on
envoie à quelqu'un, celui du ticket.

Sur la page d'une clameur, **son auteur peut la retirer** — son téléphone s'en
souvient pendant six mois — et **le personnel peut relancer un second ticket**
si le premier s'est perdu.

Le **titre** est écrit par la machine, dans le même appel qui extrait les
mots-clés : rien de plus à saisir avant de publier, et rien de plus à payer.

### Le ciel, en sommeil

La page d'accueil montrait un second écran : un ciel où chaque étoile était une
clameur, placée par proximité sémantique. **Il est en sommeil depuis le
2026-09-01** — la projection et les vecteurs coûtaient du calcul pour une vue
dont l'usage restait à prouver, et une clameur fraîchement publiée n'y
apparaissait pas avant un recalcul lancé à la main.

Rien n'a été supprimé : `constellation.html`, son JavaScript, la tâche
`embarquer` et la commande `make constellation` sont intacts, simplement plus
appelés. Les vecteurs déjà calculés dorment en base.

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
make start
```

`make start` lit `DEBUG` dans le `.env` et en tire les conséquences : en
développement il lance `runserver` — qui sert à lui seul les pages, les
fichiers statiques **et** les WebSocket, puisque `daphne` le fait basculer en
ASGI — et remplit la base d'un corpus de démonstration si elle est vide. En
production (`DEBUG=false`), il lance la pile complète derrière supervisord.

La même commande, partout : un serveur n'a pas à se souvenir d'une cible
différente.

- Constellation : http://localhost:8000/
- Déposer une clameur : http://localhost:8000/nouvelle
- Console : http://localhost:8000/admin/ (`make console` pour créer un compte)

Sans clé Mistral, l'enrichissement échoue proprement : la capsule reste
publiée et écoutable. Sans identifiants Sunmi, l'impression bascule sur un
backend de simulation qui écrit le ticket dans les journaux — **avec les mêmes
octets ESC/POS** que la vraie imprimante :

```
docker compose logs -f celery | grep -A 20 "Ticket (mock)"
```

**`make` sans argument affiche l'aide** — les dix-sept commandes disponibles,
les URL utiles et ce qui fonctionne sans clé d'API. Les plus courantes :

| Commande | |
|---|---|
| `make start` | lance la pile, selon `DEBUG` |
| `make journaux` · `make arreter` | suivre, arrêter |
| `make fixture` | recrée le corpus de démonstration — **appelle Mistral** |
| `make test` | les 165 tests |
| `make lint` | style du code |
| `make constellation` | recalcule les positions du ciel — **en sommeil** |
| `make imprimante` | ticket de test sur une vraie Sunmi |
| `make verifier` | contrôle la configuration de déploiement |
| `make console` | crée un compte opérateur |
| `make rebuild` | après ajout d'une dépendance |

## Architecture

Trois applications Django.

| | |
|---|---|
| `bornes` | Les `Réglages` du lieu, en un seul exemplaire : quelle imprimante, quel papier, quel texte d'accueil, ouvert ou fermé. |
| `capsules` | Le cœur : modèles, capture, lecture, liste et recherche, enrichissement, WebSocket. |
| `impression` | Pilote Sunmi et file de tickets, isolés pour être testables sans matériel. |

**Stack** — Django 6, Celery, Channels, HTMX, JavaScript vanilla, PostgreSQL +
pgvector, Redis, ffmpeg, Mistral (Voxtral pour la transcription diarisée,
`mistral-small` pour le titre et les mots-clés), imprimante Sunmi Cloud en mode
push. `mistral-embed` et pgvector ne servent plus qu'au ciel en sommeil.

En production : Traefik → nginx → gunicorn, avec daphne pour les WebSocket,
le tout tenu par supervisord. Voir [`docs/PASSATION-PRODUCTION.md`](docs/PASSATION-PRODUCTION.md).

La sauvegarde vit dans [`sauvegarde/`](sauvegarde) : une archive borg
quotidienne chez borgwarehouse, qui porte le dump, les médias et la
configuration — et `make essai`, qui la restaure pour de vrai afin de prouver
qu'elle le peut.

## Design

Le système visuel est dans `capsules/static/capsules/tokens.css`, portable tel
quel. Papier brun chaud, Bricolage Grotesque et Plus Jakarta Sans (vendorisées,
aucune requête vers un tiers), et un composant signature — **la porte** : une
ombre dure et décalée dans laquelle l'objet s'enfonce au survol.

## Vie privée

Ni compte, ni mot de passe, ni position. Le site conserve l'enregistrement, la
photo éventuelle, le pseudo et les mots-clés saisis. **Les métadonnées EXIF des
photos sont supprimées à l'ingestion** : une photo de téléphone porte souvent
des coordonnées GPS, qui trahiraient l'emplacement de la borne.

**Un cookie de session, et rien d'autre.** Il ne suit personne : il retient
seulement *les clameurs que vous avez déposées* — c'est ce qui vous permet de
les retirer vous-même — et *le pseudo* sous lequel vous les signez, pour ne pas
le retaper. Ni page vue, ni écoute, ni provenance. Il dure six mois, parce
qu'un ticket collé sur un mur vit plus longtemps qu'une session ordinaire et
que son auteur doit pouvoir revenir dessus. Sans compte, c'est le seul lien
entre une personne et sa clameur : **nettoyer ses cookies le rompt
définitivement**, et rien ne peut le rétablir.

Le compteur d'écoutes, lui, ne s'appuie sur aucune session : il déduplique par
adresse, au prix d'être approximatif derrière une connexion partagée.

Le projet est hébergeur au sens de la LCEN. Le retrait existe à deux mains :
**l'auteur retire sa propre clameur** depuis sa page, et la console opérateur
retire n'importe laquelle sur signalement. Retirer n'est pas effacer : la
clameur quitte la liste, et le ticket déjà collé mène à une page qui l'explique
— jamais un 404 nu.

## État

Le logiciel tourne et il est testé. **Il n'a pas encore servi sur le terrain.**
Deux choses n'ont jamais été exercées en vrai : l'impression sur une NT311
physique, et un événement avec de vrais visiteurs.
