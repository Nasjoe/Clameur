#!/bin/sh
# Point d'entree de production.
#
# `collectstatic` A CHAQUE DEMARRAGE, ET NON SEULEMENT AU BUILD.
# Docker ne recopie le contenu de l'image dans un volume nomme que si celui-ci
# est VIDE, c'est-a-dire au tout premier `up`. A chaque redeploiement suivant,
# le volume existant masque le /app/staticfiles fraichement construit : les
# pages referenceraient les nouveaux noms haches pendant que nginx servirait
# les anciens fichiers. En silence.
# / Docker only seeds a named volume when it is empty: without this, every
#   redeploy would serve the previous build's static files.
set -e
python manage.py collectstatic --noinput
exec "$@"
