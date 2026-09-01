# Sauvegarder Clameur

**Ce dossier ne sauvegarde qu'une chose qui compte vraiment : les voix.**

La base se reconstruit à partir d'un dump, les fichiers statiques se
recompilent, les vecteurs se recalculent, le code est sur la forge. Les
enregistrements de `donnees/medias/`, non. Un média perdu l'est définitivement,
et le ticket qui pointe vers lui est déjà collé sur un mur.

C'est le [kit borgwarehouse](https://github.com/CoopCodeCommun/borgwarehouse)
(dossier `scripts/`), adapté à une pile Docker Compose sur le modèle du dépôt
[ghost](https://github.com/CoopCodeCommun/ghost) : une base dans un conteneur
ne se copie pas à chaud, elle se dumpe.

## Les quatre commandes

```bash
cp env_example .env && chmod 600 .env
make init      # clé SSH, dépôt sur borgwarehouse, passphrase, cron, 1re sauvegarde
make backup    # une sauvegarde maintenant
make check     # la dernière sauvegarde est-elle restaurable ?
make essai     # la restaurer POUR DE VRAI, dans une base jetable
```

`make init` est **rejouable**. Le seul cas où il refuse, c'est quand le dépôt
contient déjà des archives : régénérer une passphrase les rendrait
définitivement illisibles.

## Ce que contient une archive

Tout le dossier de la pile, pris au même instant : le dump PostgreSQL,
`donnees/medias/`, le `.env`, `docker-compose-prod.yml`, `nginx/`, les scripts.
**Une archive suffit à remonter le site de zéro.**

Trois exclusions, chacune pour une raison :

| Exclu | Pourquoi |
|---|---|
| `donnees/postgres/` | Les fichiers bruts de PostgreSQL. Les copier à chaud donnerait une base **corrompue** : le dump est la seule forme fiable. Ils sont de toute façon illisibles par l'utilisateur qui sauvegarde. |
| `sauvegarde/.ssh/` | La clé privée du dépôt. On ne l'archive pas dans le dépôt qu'elle protège. |
| `.git/` | Déjà sur la forge. |

Le `.env` part donc dans l'archive, passphrase du dépôt comprise. C'est sans
conséquence : il faut déjà connaître cette passphrase pour ouvrir l'archive qui
la contient.

## `make check` et `make essai` ne répondent pas à la même question

**`make check`** — *cette archive est-elle restaurable ?* Sans rien restaurer,
donc lançable en boucle depuis un monitoring : il sort en code non nul dès que
quelque chose cloche. Il vérifie la fraîcheur, le contenu, la présence des
médias, et surtout **déroule le dump entièrement dans `pg_restore`**. C'est le
point qui compte : un dump tronqué — disque plein, conteneur tué en plein vol —
a une taille crédible, se trouve bien dans l'archive, et ne se restaure pas.

**`make essai`** — *restaure-t-elle vraiment ?* Il restaure la dernière archive
dans une base **jetable** à côté de la base en service, compare le nombre de
lignes table par table, vérifie que la colonne `embedding` est bien revenue en
`vector(1024)`, puis compare les médias extraits au disque **octet pour octet**.
La base jetable et les fichiers sont supprimés à la fin, même en cas d'erreur.

À lancer après tout changement de la pile, et au moins une fois avant un
événement. *Une sauvegarde qu'on n'a jamais restaurée n'est pas une sauvegarde,
c'est une intention.*

## Ce qui doit être au coffre-fort

`make init` les affiche une fois ; `make coffre` les réaffiche :

- la **passphrase** du dépôt ;
- la **clé exportée** (`borg key export`) ;
- l'**adresse du dépôt**.

C'est le seul maillon que la sauvegarde ne peut pas se sauvegarder elle-même.
Sans lui, les archives sont un bloc chiffré définitivement illisible.

**La clé SSH n'a pas besoin d'y être.** Si la machine brûle, elle brûle avec —
et ce n'est pas grave : on en regénère une et on colle sa clé publique sur le
dépôt depuis l'interface de borgwarehouse. La passphrase, elle, ne se retrouve
nulle part.

## Restaurer pour de bon

Sur une machine neuve, avec Docker et `borg` :

```bash
export BORG_PASSPHRASE='<celle du coffre>'
export BORG_RSH='ssh -i <une clé autorisée sur le dépôt>'
DEPOT='ssh://borgwarehouse@borgwarehouse.codecommun.coop:2226/./<id>'

borg list "$DEPOT"                      # choisir une archive
cd / && borg extract "$DEPOT::<archive>"   # l'arborescence revient à sa place

cd <dossier de la pile>
docker compose -f docker-compose-prod.yml up -d db     # base vide, créée par l'image
docker compose -f docker-compose-prod.yml exec -T db \
  pg_restore -U clameur -d clameur --no-owner --no-privileges \
  < sauvegarde/dump-*/clameur.dump
make start
```

Les médias sont déjà revenus avec l'extraction : ils n'ont pas d'autre étape.

**Pour ne récupérer qu'un seul enregistrement** — effacé par accident, par
exemple — inutile de tout extraire :

```bash
make mount ARCHIVE=<archive>   # monte le dépôt en lecture seule
# … on pioche dans /tmp/borg-clameur …
make umount
```

## Les deux filets

- **`make check`** dit si la dernière sauvegarde est restaurable.
- **borgwarehouse** envoie un mail si le dépôt ne reçoit plus rien. C'est le
  seul mécanisme qui prévient qu'une sauvegarde **n'est pas arrivée** — un cron
  qui échoue en silence, c'est un backup qui n'existe pas.

## Rétention

7 jours glissants, 30 quotidiennes, 12 hebdomadaires, puis **toutes** les
mensuelles et annuelles. Le `prune` ne touche que les archives de cette pile
(`--glob-archives`) : si un jour deux sauvegardes partagent un dépôt, sans ce
filtre elles se rogneraient mutuellement leur rétention, en silence.
