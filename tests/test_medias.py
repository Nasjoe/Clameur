"""Le transport des fichiers audio.

Un audio valide ne suffit pas : s'il n'est pas servi correctement, le lecteur
du navigateur reste inerte et le passant n'entend rien.
/ A valid audio file is not enough: bad transport means a dead player.

La vue est appelee DIRECTEMENT : la route n'est montee que si DEBUG, et Django
force DEBUG=False pendant les tests. On teste donc la vue, pas son montage.
/ The view is called directly: its route only exists when DEBUG.
"""

import pytest
from django.http import Http404
from django.test import RequestFactory

from capsules.publication import publier
from clameur.medias_dev import servir_un_media


@pytest.fixture
def chemin_audio(capsule):
    publier(capsule)
    capsule.refresh_from_db()
    return capsule.audio_diffusion.name


def requete(plage=None):
    entetes = {"HTTP_RANGE": plage} if plage else {}
    return RequestFactory().get("/medias/x", **entetes)


@pytest.mark.django_db
def test_une_requete_de_plage_recoit_un_206(chemin_audio):
    """Le lecteur media demande des plages d'octets et attend un 206.
    Face a un 200, Chrome reste bloque en readyState 0 et n'affiche aucune duree."""
    reponse = servir_un_media(requete("bytes=0-99"), chemin_audio)
    assert reponse.status_code == 206
    assert reponse["Content-Range"].startswith("bytes 0-99/")
    assert reponse["Content-Length"] == "100"


@pytest.mark.django_db
def test_la_plage_rendue_contient_les_bons_octets(chemin_audio):
    reponse = servir_un_media(requete("bytes=4-11"), chemin_audio)
    contenu = reponse.content
    assert len(contenu) == 8
    # Les octets 4 a 7 d'un MP4 portent toujours le type de boite `ftyp`.
    # / Bytes 4-7 of an MP4 always carry the `ftyp` box type.
    assert contenu[:4] == b"ftyp"


@pytest.mark.django_db
def test_une_requete_normale_annonce_le_support_des_plages(chemin_audio):
    reponse = servir_un_media(requete(), chemin_audio)
    assert reponse.status_code == 200
    assert reponse["Accept-Ranges"] == "bytes"


@pytest.mark.django_db
def test_une_plage_hors_limites_recoit_un_416(chemin_audio):
    reponse = servir_un_media(requete("bytes=999999999-"), chemin_audio)
    assert reponse.status_code == 416


@pytest.mark.django_db
def test_on_ne_peut_pas_remonter_hors_du_dossier_medias():
    with pytest.raises(Http404):
        servir_un_media(requete(), "../clameur/settings.py")
