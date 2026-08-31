"""Sert les fichiers medias EN DEVELOPPEMENT, avec support des requetes Range.
/ Serves media files IN DEVELOPMENT, with HTTP Range support.

POURQUOI CE FICHIER EXISTE.
`django.views.static.serve` ignore l'en-tete `Range` : il repond 200 avec tout
le fichier. Or le lecteur media des navigateurs demande des plages d'octets et
attend un 206 ; face a un 200, Chrome reste bloque en readyState 0, affiche
« 0:00 / 0:00 » et une barre inerte. L'audio est pourtant valide et se decode
tres bien — c'est le transport qui cloche.
Sans cette vue, on ne peut donc pas ECOUTER une capsule en local : c'est-a-dire
qu'on ne peut pas tester le coeur du produit.
/ Django's static serve ignores Range; browsers' media stack then stalls.

EN PRODUCTION, ce fichier ne sert a rien : nginx gere Range nativement. La vue
n'est montee que si DEBUG.
/ In production nginx handles Range; this view is only mounted when DEBUG.
"""

import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse

MOTIF_DE_PLAGE = re.compile(r"bytes=(\d*)-(\d*)")


def servir_un_media(request, chemin):
    fichier = (Path(settings.MEDIA_ROOT) / chemin).resolve()
    racine = Path(settings.MEDIA_ROOT).resolve()

    # Empeche de remonter hors du dossier medias avec des ../
    # / Prevents escaping the media root with ../
    if not fichier.is_file() or racine not in fichier.parents:
        raise Http404(chemin)

    taille = fichier.stat().st_size
    demande = MOTIF_DE_PLAGE.match(request.headers.get("Range", ""))

    if not demande:
        reponse = FileResponse(fichier.open("rb"))
        reponse["Accept-Ranges"] = "bytes"
        return reponse

    debut = int(demande.group(1) or 0)
    fin = int(demande.group(2) or taille - 1)
    fin = min(fin, taille - 1)
    if debut > fin:
        reponse = HttpResponse(status=416)
        reponse["Content-Range"] = f"bytes */{taille}"
        return reponse

    # BORNER LA LECTURE, pas seulement la position de depart. Un simple
    # seek() suivi d'un FileResponse lirait jusqu'a la fin du fichier : le
    # Content-Length annoncerait la plage demandee et le corps en contiendrait
    # bien davantage. Les plages sont petites, on les lit en memoire.
    # / Bound the read, not just the seek: otherwise the body overruns Content-Length.
    with fichier.open("rb") as flux:
        flux.seek(debut)
        morceau = flux.read(fin - debut + 1)

    reponse = HttpResponse(morceau, status=206, content_type=_type_du_fichier(fichier))
    reponse["Content-Range"] = f"bytes {debut}-{fin}/{taille}"
    reponse["Content-Length"] = str(len(morceau))
    reponse["Accept-Ranges"] = "bytes"
    return reponse


def _type_du_fichier(fichier: Path) -> str:
    type_devine, _encodage = mimetypes.guess_type(fichier.name)
    return type_devine or "application/octet-stream"
