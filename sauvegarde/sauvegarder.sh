#!/bin/bash
set -euo pipefail

##### INSTRUCTION
#
# Sauvegarde de la pile Clameur vers un depot borgwarehouse (BWH).
#
# PRINCIPE : un dump PostgreSQL coherent est depose dans ce dossier, puis TOUT
# le dossier de la pile part dans UNE SEULE archive borg. L'archive contient
# donc le dump, `donnees/medias/`, le `.env`, le `docker-compose-prod.yml` et
# les scripts : tout ce qu'il faut pour remonter le site de zero, et le tout
# coherent au meme instant.
# / One archive holds the dump, the media, the .env and the compose file:
#   everything needed to rebuild the site, consistent at a single instant.
#
# CE QUI COMPTE VRAIMENT ICI, C'EST `donnees/medias/`. La base se reconstruit
# a partir du dump, les fichiers statiques se recompilent, les vecteurs se
# recalculent — les voix des gens, non. Un media perdu l'est definitivement.
# / The media are the only thing that cannot be regenerated.
#
# EXCLUSIONS, et pourquoi chacune :
#   donnees/postgres/   les fichiers bruts de PostgreSQL. Les copier a chaud
#                       donnerait une base CORROMPUE : le dump est la seule
#                       forme fiable. Ils sont de toute facon illisibles par
#                       l'utilisateur qui sauvegarde (uid 999, mode 0700).
#   sauvegarde/.ssh/    la cle privee du depot. On ne l'archive pas dans le
#                       depot qu'elle protege. Elle va au coffre (make init).
#   .git/               deja sur la forge.
#   *.lock              le verrou de ce script lui-meme.
#
# AUCUN SECRET DANS CE FICHIER. Il lit BORG_PREFIX, BORG_REPO et
# BORG_PASSPHRASE dans le `.env` pose a cote de lui, que git ignore. Ce script,
# lui, est versionne : y ecrire une passphrase, c'est la pousser sur la forge
# au premier `git add -A` distrait.
# / No secrets here: the script is versioned, the .env is not.
#
# Le `.env` de la pile part dans l'archive, et celui de la sauvegarde aussi,
# passphrase comprise. C'est sans consequence : il faut deja connaitre cette
# passphrase pour ouvrir l'archive qui la contient.
#
# Usage :  make backup        (ou bash sauvegarde/sauvegarder.sh)
# Cron  :  pose par `make init`.
#####

## Surveillance optionnelle via Sentry :
## curl -sL https://sentry.io/get-cli/ | bash
# export SENTRY_DSN=''
# eval "$(sentry-cli bash-hook)"

DOSSIER_SCRIPT="$(cd -- "$(dirname -- "$0")" && pwd)"
DOSSIER_PILE="${DOSSIER_PILE:-$(dirname "$DOSSIER_SCRIPT")}"
COMPOSE_FICHIER="$DOSSIER_PILE/docker-compose-prod.yml"
FICHIER_ENV="$DOSSIER_SCRIPT/.env"

dire() { echo "[sauvegarde] $*"; }
mourir() { echo "[sauvegarde] ERREUR : $*" >&2; exit 1; }

[ -f "$FICHIER_ENV" ] || mourir ".env introuvable : $FICHIER_ENV — lance d'abord : make init"
set -a
# shellcheck disable=SC1090
. "$FICHIER_ENV"
set +a

PREFIXE="${BORG_PREFIX:-}"
[ -n "$PREFIXE" ]              || mourir "BORG_PREFIX absent du .env — lance d'abord : make init"
CLE_SSH="$DOSSIER_SCRIPT/.ssh/${PREFIXE}_ed25519"
DOSSIER_DUMP="${DOSSIER_DUMP:-$DOSSIER_SCRIPT/dump-$PREFIXE}"

export BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK=yes
export BORG_RELOCATED_REPO_ACCESS_IS_OK=yes

# UN SEUL PASSAGE A LA FOIS. Sans ce verrou, un lancement a la main tombant
# pendant le cron partagerait le meme DOSSIER_DUMP : le premier a finir le
# supprime — trap EXIT — pendant que l'autre archive encore, et on obtient une
# archive SANS DUMP, silencieusement.
# / Without this lock a manual run during the cron yields a dump-less archive.
exec 9>"$DOSSIER_SCRIPT/.sauvegarde-$PREFIXE.lock"
flock -n 9 || mourir "une sauvegarde est deja en cours — abandon."

[ -n "${BORG_REPO:-}" ]       || mourir "BORG_REPO absent du .env (make init)"
[ -n "${BORG_PASSPHRASE:-}" ] || mourir "BORG_PASSPHRASE absent du .env (make init)"
for outil in borg docker flock; do
  command -v "$outil" >/dev/null || mourir "$outil introuvable dans le PATH."
done
[ -f "$COMPOSE_FICHIER" ] || mourir "compose introuvable : $COMPOSE_FICHIER"
[ -d "$DOSSIER_PILE/donnees/medias" ] || mourir "dossier des medias introuvable : $DOSSIER_PILE/donnees/medias"

MAINTENANT=$(date +%Y-%m-%d-%H-%M)

# Force l'usage de CETTE cle, et pas d'une autre proposee par l'agent SSH :
# borgwarehouse restreint chaque cle a un seul depot et refuserait la connexion.
# / -oIdentitiesOnly: one key = one repo on borgwarehouse.
if [ -f "$CLE_SSH" ]; then
  chmod 600 "$CLE_SSH" 2>/dev/null || true
  export BORG_RSH="/usr/bin/ssh -oStrictHostKeyChecking=accept-new -oIdentitiesOnly=yes -i $CLE_SSH"
else
  dire "[INFO] aucune cle a $CLE_SSH — SSH utilisera la configuration systeme."
fi

compose() { docker compose -f "$COMPOSE_FICHIER" "$@"; }


#### DUMP POSTGRESQL ####
# Nettoyage garanti du dump, meme en cas d'erreur : il n'a aucune raison de
# survivre a l'archivage, et il contient toute la base en clair.
# / The dump never outlives the archiving: it holds the whole base in clear.
trap 'rm -rf "$DOSSIER_DUMP"' EXIT
rm -rf "$DOSSIER_DUMP"
mkdir -p "$DOSSIER_DUMP"
FICHIER_DUMP="$DOSSIER_DUMP/clameur.dump"

# L'utilisateur et la base sont lus DANS le conteneur qui tourne, pas dans un
# fichier : c'est la seule source de verite sur ce qui est reellement servi, et
# le mot de passe ne transite jamais par ce script.
# / Read from the running container: the only truth about what is being served.
PG_USER="$(compose exec -T db printenv POSTGRES_USER | tr -d '\r\n')"
PG_BASE="$(compose exec -T db printenv POSTGRES_DB | tr -d '\r\n')"
[ -n "$PG_USER" ] && [ -n "$PG_BASE" ] || mourir "conteneur db injoignable : impossible de lire POSTGRES_USER/POSTGRES_DB."

dire "$MAINTENANT dump de la base '$PG_BASE' (format custom, compresse)"
# -Fc : le format custom permet une restauration selective (pg_restore) et se
# verifie ligne a ligne, ce qu'un .sql brut ne permet pas.
# / Custom format: selective restore, and verifiable end to end.
compose exec -T db pg_dump -U "$PG_USER" -d "$PG_BASE" -Fc --no-owner --no-privileges > "$FICHIER_DUMP"

[ -s "$FICHIER_DUMP" ] || mourir "dump vide ($FICHIER_DUMP) — rien n'est archive."

# ON VERIFIE LE DUMP AVANT DE L'ARCHIVER. Un dump tronque — disque plein,
# conteneur tue en plein vol — a une taille credible et s'archive tres bien.
# Le derouler entierement ici, c'est refuser d'ecrire une archive inutile
# plutot que de le decouvrir le jour de la restauration.
# / Unroll the dump before archiving: a truncated one archives just fine.
if ! compose exec -T db pg_restore -f /dev/null < "$FICHIER_DUMP" 2>/dev/null; then
  mourir "le dump ne se deroule pas (tronque ?) — rien n'est archive."
fi
dire "dump verifie : $(du -h "$FICHIER_DUMP" | cut -f1)"


#### ARCHIVE BORG ####
dire "$MAINTENANT creation de l'archive (dossier complet de la pile)"
/usr/bin/borg create -vs --compression lz4 \
  --exclude "$DOSSIER_PILE/donnees/postgres" \
  --exclude "$DOSSIER_SCRIPT/.ssh" \
  --exclude "$DOSSIER_PILE/.git" \
  --exclude-caches \
  --exclude '*.lock' \
  "$BORG_REPO::$PREFIXE-$MAINTENANT" \
  "$DOSSIER_PILE"

dire "$MAINTENANT prune des anciennes archives :"
# --glob-archives : le prune ne touche QUE les archives de cette pile. Si deux
# sauvegardes partagent un jour le meme depot, sans ce filtre elles se rognent
# mutuellement leur retention, en silence.
# / Prune only this stack's archives, otherwise two backups trim each other.
/usr/bin/borg prune -v --list \
  --glob-archives "$PREFIXE-*" \
  --keep-within=7d --keep-daily=30 --keep-weekly=12 --keep-monthly=-1 --keep-yearly=-1 \
  "$BORG_REPO"

dire "$MAINTENANT termine"
