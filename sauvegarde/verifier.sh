#!/bin/bash
set -euo pipefail

##### INSTRUCTION
#
# Verifie que la derniere sauvegarde est REELLEMENT restaurable, sans rien
# restaurer et sans toucher a la base en service. Lance par :  make check
#
# Quatre questions, dans l'ordre :
#   1. Une archive recente existe-t-elle ?      (sinon : le cron est mort)
#   2. Contient-elle le dump, les medias, le .env et le compose ?
#   3. Le dump se deroule-t-il ENTIEREMENT, et porte-t-il le schema attendu ?
#   4. Les medias sont-ils la, et non vides ?
#
# LE POINT 3 EST CELUI QUI COMPTE. Un dump tronque — disque plein, conteneur
# tue en plein vol — a une taille credible, se trouve bien dans l'archive, et
# ne se restaure pas. Le derouler entierement dans `pg_restore` est la seule
# preuve. Verifier seulement l'en-tete ne prouverait rien : la table des
# matieres d'un dump custom est au debut du fichier.
# / A truncated dump has a credible size and lists fine: only a full unroll
#   proves anything.
#
# LE POINT 4 EST CELUI QU'ON OUBLIE. Une sauvegarde ou la base est parfaite et
# les medias absents laisse un corpus de fiches sans voix : exactement ce que
# ce projet ne peut pas se permettre.
# / A perfect base without the media leaves cards with no voices.
#
# Sort en code non nul si quoi que ce soit cloche : branchable sur un
# monitoring tel quel. / Non-zero exit on any problem: monitoring-ready.
#####

DOSSIER_SCRIPT="$(cd -- "$(dirname -- "$0")" && pwd)"
DOSSIER_PILE="${DOSSIER_PILE:-$(dirname "$DOSSIER_SCRIPT")}"
COMPOSE_FICHIER="$DOSSIER_PILE/docker-compose-prod.yml"
FICHIER_ENV="$DOSSIER_SCRIPT/.env"

# 25 h = la sauvegarde quotidienne d'hier, plus une heure de marge. C'est aussi
# le reglage de l'alerte borgwarehouse, pose par `make init`.
AGE_MAX_HEURES_DEFAUT=25

ok()     { echo "  [ok]   $*"; }
ko()     { echo "  [KO]   $*" >&2; ERREURS=$((ERREURS + 1)); }
mourir() { echo "[check] ERREUR : $*" >&2; exit 2; }
ERREURS=0

[ -f "$FICHIER_ENV" ] || mourir ".env introuvable : $FICHIER_ENV — la sauvegarde n'est pas configuree (make init)"
set -a
# shellcheck disable=SC1090
. "$FICHIER_ENV"
set +a

[ -n "${BORG_PREFIX:-}" ] || mourir "BORG_PREFIX absent du .env — la sauvegarde n'est pas configuree (make init)"
[ -n "${BORG_REPO:-}" ]       || mourir "BORG_REPO absent du .env (make init)"
[ -n "${BORG_PASSPHRASE:-}" ] || mourir "BORG_PASSPHRASE absent du .env (make init)"
command -v borg >/dev/null || mourir "borg introuvable dans le PATH."

AGE_MAX_HEURES="${AGE_MAX_HEURES:-$AGE_MAX_HEURES_DEFAUT}"
CLE_SSH="$DOSSIER_SCRIPT/.ssh/${BORG_PREFIX}_ed25519"
[ -f "$CLE_SSH" ] && export BORG_RSH="/usr/bin/ssh -oStrictHostKeyChecking=accept-new -oIdentitiesOnly=yes -i $CLE_SSH"

compose() { docker compose -f "$COMPOSE_FICHIER" "$@"; }

echo "[check] depot : $BORG_REPO"
echo


#### 1. FRAICHEUR ####
echo "1. Fraicheur"

# --glob-archives : on ne regarde QUE les archives de cette pile. Sans ce
# filtre, une autre sauvegarde partageant le depot suffirait a nous rassurer.
DERNIERE="$(borg list --glob-archives "$BORG_PREFIX-*" --last 1 \
  --format '{archive}{TAB}{time:%Y-%m-%d %H:%M:%S}{NL}' "$BORG_REPO")"
[ -n "$DERNIERE" ] || mourir "aucune archive '$BORG_PREFIX-*' dans le depot. La sauvegarde n'a jamais tourne."

ARCHIVE="${DERNIERE%%	*}"
DATE_ARCHIVE="${DERNIERE#*	}"
AGE_HEURES=$(( ( $(date +%s) - $(date -d "$DATE_ARCHIVE" +%s) ) / 3600 ))

if [ "$AGE_HEURES" -le "$AGE_MAX_HEURES" ]; then
  ok "derniere archive : $ARCHIVE (il y a ${AGE_HEURES} h)"
else
  ko "derniere archive : $ARCHIVE — ${AGE_HEURES} h, soit plus de ${AGE_MAX_HEURES} h."
  ko "le cron ne tourne plus. Verifie : crontab -l"
fi


#### 2. CONTENU ####
echo
echo "2. Contenu de l'archive"

# On liste une fois, avec la taille : elle sert au controle des medias.
CONTENU="$(borg list --format '{size}{TAB}{path}{NL}' "$BORG_REPO::$ARCHIVE")"
chemins() { printf '%s\n' "$CONTENU" | cut -f2-; }

# Borg stocke un chemin absolu SANS son '/' initial : `/mnt/x/Clameur/.env`
# devient `mnt/x/Clameur/.env`. On vise donc le chemin exact de cette pile-ci,
# et non un motif approchant qui confondrait le .env de la pile avec celui de
# la sauvegarde. / Borg strips the leading slash: match this stack's real path.
DANS_ARCHIVE="${DOSSIER_PILE#/}"

CHEMIN_DUMP="$(chemins | grep -E "^$DANS_ARCHIVE/sauvegarde/dump-[^/]+/clameur\.dump$" | head -n1 || true)"
if [ -n "$CHEMIN_DUMP" ]; then
  ok "dump present : ${CHEMIN_DUMP##*/}"
else
  ko "aucun dump PostgreSQL dans l'archive."
fi

if chemins | grep -qF "$DANS_ARCHIVE/donnees/medias/"; then
  ok "dossier des medias present"
else
  ko "donnees/medias absent de l'archive : les voix ne sont PAS sauvegardees."
fi

if chemins | grep -qxF "$DANS_ARCHIVE/.env"; then
  ok ".env present (la pile est remontable telle quelle)"
else
  ko ".env absent : une restauration demanderait de resaisir tous les secrets."
fi

if chemins | grep -qxF "$DANS_ARCHIVE/docker-compose-prod.yml"; then
  ok "docker-compose-prod.yml present"
else
  ko "le compose de production est absent de l'archive."
fi

# Le contraire de ce qu'on veut : les fichiers bruts de PostgreSQL, copies a
# chaud, donneraient une base corrompue et feraient croire a une sauvegarde
# plus complete qu'elle ne l'est.
# / Raw PGDATA in the archive would fake a completeness it does not have.
if chemins | grep -qF "$DANS_ARCHIVE/donnees/postgres/"; then
  ko "donnees/postgres est dans l'archive : copie a chaud, donc corrompue. Verifie l'exclusion."
else
  ok "donnees/postgres correctement exclu (seul le dump fait foi)"
fi


#### 3. LE DUMP EST-IL EXPLOITABLE, ET COMPLET ? ####
echo
echo "3. Le dump se deroule-t-il entierement ?"

if [ -z "$CHEMIN_DUMP" ]; then
  ko "pas de dump a verifier."
elif ! docker compose -f "$COMPOSE_FICHIER" ps --status running --services 2>/dev/null | grep -qx db; then
  ko "conteneur db a l'arret : impossible de derouler le dump. Relance la pile."
else
  # `pg_restore -f -` convertit le dump en SQL sur la sortie standard SANS
  # toucher a la moindre base. On lit TOUT le flux dans awk (pas de grep -q qui
  # fermerait le tuyau : borg recevrait un SIGPIPE et pipefail ferait echouer
  # le script a tort).
  # / -f - converts to SQL touching no database; awk reads the whole stream.
  # `pipefail` est actif : le code de retour de la substitution est celui du
  # premier maillon qui a lache. PIPESTATUS ne servirait a rien ici — il decrit
  # le pipeline courant, et la substitution de commande en est un autre.
  # / pipefail gives us the failing link; PIPESTATUS would describe the wrong
  #   pipeline, the one made of this single assignment.
  set +e
  VERDICT="$(borg extract --stdout "$BORG_REPO::$ARCHIVE" "$CHEMIN_DUMP" \
    | compose exec -T db pg_restore -f - 2>/dev/null \
    | awk '
        /CREATE TABLE public\.capsules_capsule/ { capsules = 1 }
        /CREATE TABLE public\.bornes_borne/     { bornes   = 1 }
        /CREATE EXTENSION.* vector/             { vecteur  = 1 }
        /^COPY public\./                        { copies++ }
        END { printf "%d %d %d %d", capsules + 0, bornes + 0, vecteur + 0, copies + 0 }
      ')"
  CODE=$?
  set -e
  read -r A_CAPSULES A_BORNES A_VECTEUR NB_COPIES <<< "$VERDICT"

  if [ "$CODE" != 0 ]; then
    ko "le dump ne se deroule pas jusqu'au bout (tronque ?) — NON restaurable."
  else
    ok "dump deroule entierement par pg_restore"
  fi

  if [ "$A_CAPSULES" = 1 ] && [ "$A_BORNES" = 1 ]; then
    ok "schema Clameur retrouve (tables capsules_capsule et bornes_borne)"
  else
    ko "le dump ne contient pas le schema attendu."
  fi

  # Sans l'extension, une base restauree refuse le VectorField : la
  # constellation ne remonterait pas. / Without it the vector column fails.
  if [ "$A_VECTEUR" = 1 ]; then
    ok "extension pgvector presente dans le dump"
  else
    ko "CREATE EXTENSION vector absent : la base restauree n'aurait pas de vecteurs."
  fi

  # Un dump sans aucun COPY est syntaxiquement valide et parfaitement vide :
  # c'est le cas d'une sauvegarde prise sur une base fraichement migree, ou
  # d'un dump qui a echoue sans le dire. / A dump with no COPY is valid, and
  # empty: a freshly migrated base, or a silent failure.
  if [ "$NB_COPIES" -gt 0 ]; then
    ok "$NB_COPIES table(s) avec leurs donnees"
  else
    ko "aucune donnee dans le dump : pas un seul COPY."
  fi
fi


#### 4. LES MEDIAS SONT-ILS LA, ET NON VIDES ? ####
echo
echo "4. Les medias"

# Les dossiers ont une taille nulle : on ne compte que les fichiers, reperes a
# leur extension. / Directories weigh zero: count files, not entries.
LIGNES_MEDIAS="$(printf '%s\n' "$CONTENU" \
  | awk -F'\t' -v prefixe="$DANS_ARCHIVE/donnees/medias/" \
        'index($2, prefixe) == 1 && $2 ~ /\.[A-Za-z0-9]+$/')"
NB_MEDIAS="$(printf '%s' "$LIGNES_MEDIAS" | grep -c . || true)"
NB_VIDES="$(printf '%s\n' "$LIGNES_MEDIAS" | awk -F'\t' '$1 == 0' | grep -c . || true)"

if [ "$NB_MEDIAS" -eq 0 ]; then
  # Pas une erreur en soi : avant le premier evenement, il n'y a aucune voix.
  # / Not an error: before the first event there is no voice to save.
  echo "  [--]   aucun media dans l'archive — normal tant que personne n'a enregistre."
else
  ok "$NB_MEDIAS fichier(s) de media archive(s)"
  if [ "$NB_VIDES" -eq 0 ]; then
    ok "aucun media vide"
  else
    ko "$NB_VIDES media(s) de taille nulle dans l'archive."
  fi
fi


#### VERDICT ####
echo
if [ "$ERREURS" -eq 0 ]; then
  echo "[check] La derniere sauvegarde est restaurable."
  echo "[check] Pour en faire la preuve sur une vraie base : make essai"
  exit 0
fi
echo "[check] $ERREURS probleme(s). Cette sauvegarde n'est pas fiable." >&2
exit 1
