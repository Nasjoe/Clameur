#!/bin/bash
set -euo pipefail

##### INSTRUCTION
#
# LA PREUVE PAR LA RESTAURATION. Lance par :  make essai
#
# `make check` repond « ce dump se deroule ». Ce script-ci va plus loin : il
# restaure vraiment la derniere archive dans une base JETABLE, a cote de la
# base en service, et compare ce qui en sort avec ce qui tourne. Puis il
# recompare les medias extraits, octet par octet, avec ceux du disque.
# / check says the dump unrolls; this actually restores it and compares.
#
# RIEN N'EST TOUCHE EN PRODUCTION. La base restauree porte un autre nom, elle
# est supprimee a la fin — meme en cas d'erreur —, et les fichiers sont
# extraits dans un dossier temporaire HORS de la pile : extraits dedans, ils
# partiraient dans la prochaine sauvegarde, qui doublerait de taille a chaque
# essai. / Nothing in production is touched; the temp dir lives outside the
#   stack, otherwise each test would double the next archive.
#
# A LANCER APRES CHAQUE CHANGEMENT DE LA PILE, et au moins une fois avant un
# evenement. Une sauvegarde qu'on n'a jamais restauree n'est pas une
# sauvegarde, c'est une intention.
# / A backup never restored is not a backup, it is an intention.
#
# Variables utiles :
#   ARCHIVE=<nom>     essayer une archive precise (defaut : la derniere)
#   SANS_MEDIAS=1     ne restaurer que la base (corpus devenu volumineux)
#####

DOSSIER_SCRIPT="$(cd -- "$(dirname -- "$0")" && pwd)"
DOSSIER_PILE="${DOSSIER_PILE:-$(dirname "$DOSSIER_SCRIPT")}"
COMPOSE_FICHIER="$DOSSIER_PILE/docker-compose-prod.yml"
FICHIER_ENV="$DOSSIER_SCRIPT/.env"

BASE_ESSAI="${BASE_ESSAI:-clameur_essai_de_restauration}"

ok()     { echo "  [ok]   $*"; }
ko()     { echo "  [KO]   $*" >&2; ERREURS=$((ERREURS + 1)); }
mourir() { echo "[essai] ERREUR : $*" >&2; exit 2; }
ERREURS=0

[ -f "$FICHIER_ENV" ] || mourir ".env introuvable : $FICHIER_ENV (make init)"
set -a
# shellcheck disable=SC1090
. "$FICHIER_ENV"
set +a

[ -n "${BORG_PREFIX:-}" ]     || mourir "BORG_PREFIX absent du .env (make init)"
[ -n "${BORG_REPO:-}" ]       || mourir "BORG_REPO absent du .env (make init)"
[ -n "${BORG_PASSPHRASE:-}" ] || mourir "BORG_PASSPHRASE absent du .env (make init)"
command -v borg >/dev/null || mourir "borg introuvable dans le PATH."

CLE_SSH="$DOSSIER_SCRIPT/.ssh/${BORG_PREFIX}_ed25519"
[ -f "$CLE_SSH" ] && export BORG_RSH="/usr/bin/ssh -oStrictHostKeyChecking=accept-new -oIdentitiesOnly=yes -i $CLE_SSH"

compose() { docker compose -f "$COMPOSE_FICHIER" "$@"; }
compose ps --status running --services 2>/dev/null | grep -qx db \
  || mourir "conteneur db a l'arret : impossible de restaurer quoi que ce soit."

PG_USER="$(compose exec -T db printenv POSTGRES_USER | tr -d '\r\n')"
PG_BASE="$(compose exec -T db printenv POSTGRES_DB | tr -d '\r\n')"
# `client_min_messages=warning` fait taire le NOTICE du DROP ... IF EXISTS sur
# une base absente, qui parasitait le rapport. Il passe par PGOPTIONS et NON
# par un `SET` en tete de requete : psql enveloppe alors les deux ordres dans
# une seule transaction, et DROP DATABASE refuse de tourner dans une
# transaction. / Via PGOPTIONS, not a leading SET: that would wrap both
#   statements in one transaction, and DROP DATABASE refuses to run in one.
sql_sur() {
  compose exec -T -e PGOPTIONS='-c client_min_messages=warning' db \
    psql -X -q -U "$PG_USER" -d "$1" -v ON_ERROR_STOP=1 -Atc "$2"
}

# Le dossier temporaire est HORS de la pile : voir l'en-tete.
DOSSIER_ESSAI="$(mktemp -d "${TMPDIR:-/tmp}/clameur-essai-XXXXXX")"
nettoyer() {
  sql_sur postgres "DROP DATABASE IF EXISTS $BASE_ESSAI" >/dev/null 2>&1 || true
  rm -rf "$DOSSIER_ESSAI"
}
trap nettoyer EXIT

DANS_ARCHIVE="${DOSSIER_PILE#/}"

echo "[essai] depot : $BORG_REPO"


#### 1. QUELLE ARCHIVE ? ####
echo
echo "1. L'archive"
if [ -z "${ARCHIVE:-}" ]; then
  ARCHIVE="$(borg list --glob-archives "$BORG_PREFIX-*" --last 1 --format '{archive}{NL}' "$BORG_REPO")"
fi
[ -n "$ARCHIVE" ] || mourir "aucune archive '$BORG_PREFIX-*' dans le depot."
ok "archive choisie : $ARCHIVE"

CHEMIN_DUMP="$(borg list --format '{path}{NL}' "$BORG_REPO::$ARCHIVE" \
  | grep -E "^$DANS_ARCHIVE/sauvegarde/dump-[^/]+/clameur\.dump$" | head -n1 || true)"
[ -n "$CHEMIN_DUMP" ] || mourir "aucun dump dans cette archive."


#### 2. RESTAURER LA BASE, POUR DE VRAI ####
echo
echo "2. Restauration de la base dans '$BASE_ESSAI'"

sql_sur postgres "DROP DATABASE IF EXISTS $BASE_ESSAI" >/dev/null
sql_sur postgres "CREATE DATABASE $BASE_ESSAI" >/dev/null
ok "base jetable creee"

JOURNAL="$DOSSIER_ESSAI/pg_restore.log"
if borg extract --stdout "$BORG_REPO::$ARCHIVE" "$CHEMIN_DUMP" \
   | compose exec -T db pg_restore -U "$PG_USER" -d "$BASE_ESSAI" \
       --no-owner --no-privileges >"$JOURNAL" 2>&1; then
  ok "pg_restore termine sans erreur"
else
  ko "pg_restore a signale des erreurs :"
  sed 's/^/         /' "$JOURNAL" | tail -n 15 >&2
fi


#### 3. LA BASE RESTAUREE DIT-ELLE LA MEME CHOSE QUE CELLE EN SERVICE ? ####
echo
echo "3. Comparaison avec la base en service"

TABLES="bornes_borne capsules_capsule capsules_tag capsules_tagdecapsule impression_jobimpression auth_user"
printf "         %-28s %10s %10s\n" "table" "en service" "restauree"
for table in $TABLES; do
  VIVANT="$(sql_sur "$PG_BASE"   "SELECT count(*) FROM $table" 2>/dev/null || echo "?")"
  RESTAURE="$(sql_sur "$BASE_ESSAI" "SELECT count(*) FROM $table" 2>/dev/null || echo "?")"
  printf "         %-28s %10s %10s\n" "$table" "$VIVANT" "$RESTAURE"
  if [ "$VIVANT" = "$RESTAURE" ] && [ "$VIVANT" != "?" ]; then
    continue
  fi
  # Un ecart n'est pas forcement une faute : une clameur publiee depuis la
  # derniere sauvegarde n'a aucune raison d'etre dans l'archive. On le signale
  # comme un ecart, et c'est a l'oeil humain de trancher.
  # / A gap is not always a fault: a capsule published since the last backup
  #   has no reason to be in the archive.
  ko "ecart sur $table (en service : $VIVANT, restauree : $RESTAURE)"
done

# LE VECTEUR EST LE POINT FRAGILE D'UNE RESTAURATION : sans l'extension
# pgvector dans la base cible, la colonne ne se recree pas et l'erreur se perd
# dans le bruit de pg_restore. On interroge donc la colonne elle-meme.
# / Query the column itself: a missing pgvector extension hides in the noise.
if TYPE_VECTEUR="$(sql_sur "$BASE_ESSAI" \
     "SELECT format_type(atttypid, atttypmod) FROM pg_attribute
      WHERE attrelid = 'capsules_capsule'::regclass AND attname = 'embedding'" 2>/dev/null)" \
   && [ -n "$TYPE_VECTEUR" ]; then
  ok "colonne embedding restauree, de type $TYPE_VECTEUR"
else
  ko "colonne embedding absente de la base restauree (extension pgvector ?)."
fi


#### 4. LES MEDIAS SONT-ILS IDENTIQUES, OCTET POUR OCTET ? ####
echo
echo "4. Les medias"

if [ -n "${SANS_MEDIAS:-}" ]; then
  echo "  [--]   extraction des medias sautee (SANS_MEDIAS)"
else
  # borg stocke les chemins sans leur '/' initial : l'extraction recree
  # l'arborescence sous le dossier courant. / Paths are stored without the
  # leading slash: extraction rebuilds the tree under the current directory.
  ( cd "$DOSSIER_ESSAI" && borg extract "$BORG_REPO::$ARCHIVE" "$DANS_ARCHIVE/donnees/medias" )
  RACINE_EXTRAITE="$DOSSIER_ESSAI/$DANS_ARCHIVE/donnees/medias"

  if [ ! -d "$RACINE_EXTRAITE" ]; then
    echo "  [--]   aucun media dans l'archive — normal tant que personne n'a enregistre."
  else
    IDENTIQUES=0 ; DIFFERENTS=0 ; DISPARUS=0
    while IFS= read -r -d '' extrait; do
      relatif="${extrait#$RACINE_EXTRAITE/}"
      vivant="$DOSSIER_PILE/donnees/medias/$relatif"
      if [ ! -f "$vivant" ]; then
        # Le fichier est dans l'archive mais plus sur le disque : c'est
        # exactement le cas que la sauvegarde existe pour rattraper.
        # / In the archive but no longer on disk: precisely what backups are for.
        DISPARUS=$((DISPARUS + 1))
      elif cmp -s "$extrait" "$vivant"; then
        IDENTIQUES=$((IDENTIQUES + 1))
      else
        DIFFERENTS=$((DIFFERENTS + 1))
        echo "         different : $relatif" >&2
      fi
    done < <(find "$RACINE_EXTRAITE" -type f -print0)

    if [ $((IDENTIQUES + DIFFERENTS + DISPARUS)) -eq 0 ]; then
      # L'extraction a bien recree l'arborescence, mais elle est vide : il n'y
      # a simplement aucune voix a sauvegarder pour l'instant.
      # / The tree came back, but empty: no voice recorded yet.
      echo "  [--]   aucun media dans l'archive — normal tant que personne n'a enregistre."
    elif [ "$DIFFERENTS" -eq 0 ]; then
      ok "$IDENTIQUES media(s) restaure(s) identiques au disque, octet pour octet"
    else
      ko "$DIFFERENTS media(s) restaure(s) different(s) de ceux du disque."
    fi
    [ "$DISPARUS" -eq 0 ] || echo "  [--]   $DISPARUS media(s) presents dans l'archive et absents du disque."
  fi
fi


#### VERDICT ####
echo
if [ "$ERREURS" -eq 0 ]; then
  echo "[essai] Restauration reussie. La base jetable et les fichiers extraits"
  echo "        viennent d'etre supprimes : rien ne subsiste de cet essai."
  exit 0
fi
echo "[essai] $ERREURS probleme(s) : cette archive ne restaure pas correctement." >&2
exit 1
