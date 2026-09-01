"""L'enrichissement sémantique : transcrire, taguer, embarquer.

Aucune de ces tâches n'était testée. C'est pourtant là que vivent les deux
défauts les plus coûteux trouvés en relecture : une transcription qui
ressuscitait une capsule retirée, et un embedding qu'un échec d'extraction de
mots-clés empêchait à jamais.
/ None of these tasks were tested, yet they held the two costliest defects.
"""

from unittest.mock import patch

import pytest

from capsules.models import Capsule, StatutCapsule, TagDeCapsule
from capsules.tasks import embarquer, taguer, transcrire

TRANSCRIPTION = {
    "texte": "On s'est rencontrés ici, un mardi.",
    "langue": "fr",
    "segments": [
        {"speaker": "voix 1", "start": 0, "end": 2, "text": "On s'est rencontrés ici,"},
        {"speaker": "voix 2", "start": 2, "end": 4, "text": "un mardi."},
    ],
}


@pytest.fixture
def capsule_a_transcrire(capsule_publiee):
    capsule_publiee.audio_diffusion = capsule_publiee.audio_original
    capsule_publiee.save()
    return capsule_publiee


# --------------------------------------------------------------- transcrire

@pytest.mark.django_db
def test_la_transcription_enregistre_les_segments_et_la_langue(capsule_a_transcrire):
    with patch("capsules.tasks.transcrire_le_fichier", return_value=TRANSCRIPTION), \
         patch("capsules.tasks.diffuser_la_transcription"):
        assert transcrire(str(capsule_a_transcrire.uuid)) == "ok"

    capsule_a_transcrire.refresh_from_db()
    assert capsule_a_transcrire.transcription_texte.startswith("On s'est")
    assert capsule_a_transcrire.langue_detectee == "fr"
    assert len(capsule_a_transcrire.transcription_raw["segments"]) == 2


@pytest.mark.django_db
def test_la_transcription_ne_ressuscite_pas_une_capsule_retiree(capsule_a_transcrire):
    """L'opérateur retire une capsule pendant que Voxtral travaille — un appel
    qui dure de dix secondes à une minute. Un `save()` complet réécrirait
    l'état d'avant l'appel et remettrait la capsule en ligne, sans trace.
    C'est le kill switch de la LCEN qui sauterait.
    / A full save would resurrect a capsule the operator withdrew mid-call."""
    def retirer_pendant_l_appel(chemin):
        Capsule.objects.filter(pk=capsule_a_transcrire.pk).update(
            statut=StatutCapsule.RETIREE
        )
        return TRANSCRIPTION

    with patch("capsules.tasks.transcrire_le_fichier", side_effect=retirer_pendant_l_appel), \
         patch("capsules.tasks.diffuser_la_transcription"):
        transcrire(str(capsule_a_transcrire.uuid))

    capsule_a_transcrire.refresh_from_db()
    assert capsule_a_transcrire.statut == StatutCapsule.RETIREE, "le retrait a été annulé"
    assert capsule_a_transcrire.transcription_texte, "la transcription a été perdue"


@pytest.mark.django_db
def test_la_transcription_ne_perd_pas_les_ecoutes_comptees_pendant_l_appel(
    capsule_a_transcrire,
):
    def ecouter_pendant_l_appel(chemin):
        from django.db.models import F

        Capsule.objects.filter(pk=capsule_a_transcrire.pk).update(
            nombre_ecoutes=F("nombre_ecoutes") + 3
        )
        return TRANSCRIPTION

    with patch("capsules.tasks.transcrire_le_fichier", side_effect=ecouter_pendant_l_appel), \
         patch("capsules.tasks.diffuser_la_transcription"):
        transcrire(str(capsule_a_transcrire.uuid))

    capsule_a_transcrire.refresh_from_db()
    assert capsule_a_transcrire.nombre_ecoutes == 3


@pytest.mark.django_db
def test_un_echec_de_transcription_laisse_la_capsule_publiee(capsule_a_transcrire):
    with patch("capsules.tasks.transcrire_le_fichier", side_effect=OSError("Voxtral muet")):
        assert transcrire(str(capsule_a_transcrire.uuid)) == "echec"

    capsule_a_transcrire.refresh_from_db()
    assert capsule_a_transcrire.statut == StatutCapsule.PUBLIEE
    assert "Voxtral muet" in capsule_a_transcrire.erreur_enrichissement


@pytest.mark.django_db
def test_l_embedding_ne_depend_pas_de_l_extraction_des_tags(capsule_a_transcrire):
    """C'est l'embedding qui donne son étoile à la clameur. L'enchaîner derrière
    l'extraction de mots-clés — l'étape la plus fragile — faisait dépendre sa
    présence même sur la page d'accueil de la réussite de celle-ci.
    / The embedding is what gives a clameur its star; it must not hang behind
      the most brittle step of the chain."""
    lances = []
    with patch("capsules.tasks.transcrire_le_fichier", return_value=TRANSCRIPTION), \
         patch("capsules.tasks.diffuser_la_transcription"), \
         patch.object(taguer, "delay", lambda u: lances.append("taguer")), \
         patch.object(embarquer, "delay", lambda u: lances.append("embarquer")):
        transcrire(str(capsule_a_transcrire.uuid))

    assert set(lances) == {"taguer", "embarquer"}, (
        "les deux suites doivent partir de transcrire, en parallèle"
    )


# ------------------------------------------------------------------- taguer

@pytest.mark.django_db
def test_les_tags_du_modele_sont_marques_comme_tels(capsule_a_transcrire):
    capsule_a_transcrire.transcription_texte = TRANSCRIPTION["texte"]
    capsule_a_transcrire.save()

    with patch("capsules.tasks._appeler_le_modele_de_tags", return_value=["rue", "pluie"]):
        assert taguer(str(capsule_a_transcrire.uuid)) == "ok"

    origines = {
        lien.tag.nom: lien.origine
        for lien in capsule_a_transcrire.tags_de_capsule.all()
    }
    assert origines == {"rue": TagDeCapsule.MACHINE, "pluie": TagDeCapsule.MACHINE}


@pytest.mark.django_db
def test_un_echec_de_tags_laisse_la_capsule_publiee(capsule_a_transcrire):
    capsule_a_transcrire.transcription_texte = TRANSCRIPTION["texte"]
    capsule_a_transcrire.save()

    with patch("capsules.tasks._appeler_le_modele_de_tags", side_effect=ValueError("JSON illisible")):
        assert taguer(str(capsule_a_transcrire.uuid)) == "echec"

    capsule_a_transcrire.refresh_from_db()
    assert capsule_a_transcrire.statut == StatutCapsule.PUBLIEE


# ---------------------------------------------------------------- embarquer

@pytest.mark.django_db
def test_un_vecteur_de_mauvaise_dimension_est_refuse(capsule_a_transcrire):
    """Un vecteur tronqué entrerait en base et fausserait toute la projection
    sans que rien ne le signale.
    / A truncated vector would silently skew the whole projection."""
    capsule_a_transcrire.transcription_texte = TRANSCRIPTION["texte"]
    capsule_a_transcrire.save()

    with patch("capsules.tasks._calculer_le_vecteur", return_value=[0.1] * 512):
        assert embarquer(str(capsule_a_transcrire.uuid)) == "echec"

    capsule_a_transcrire.refresh_from_db()
    assert capsule_a_transcrire.embedding is None
    assert "512" in capsule_a_transcrire.erreur_enrichissement


@pytest.mark.django_db
def test_un_vecteur_conforme_est_enregistre(capsule_a_transcrire):
    capsule_a_transcrire.transcription_texte = TRANSCRIPTION["texte"]
    capsule_a_transcrire.save()

    with patch("capsules.tasks._calculer_le_vecteur", return_value=[0.01] * 1024):
        assert embarquer(str(capsule_a_transcrire.uuid)) == "ok"

    capsule_a_transcrire.refresh_from_db()
    assert capsule_a_transcrire.embedding is not None
    assert capsule_a_transcrire.enrichie_le is not None


# ------------------------------------------- la forme reelle de la reponse

def _client_qui_repond(contenu: str):
    """Un client Mistral factice qui rend exactement ce qu'a rendu le vrai.
    / A fake client returning verbatim what the real one returned."""
    from unittest.mock import MagicMock

    client = MagicMock()
    client.chat.complete.return_value.choices = [
        MagicMock(message=MagicMock(content=contenu))
    ]
    return lambda **_: client


def test_les_mots_cles_survivent_a_une_reponse_en_objet_json():
    """`mistral-small` répond un OBJET, jamais le tableau qu'on lui demande.

    Relevé le 2026-08-31 sur une vraie capsule, trois fois sur trois :

        ```json
        {"mots-clés": ["boulangerie", "fermeture", "nostalgie"]}
        ```

    Itérer sur ce dictionnaire donne ses CLÉS. Chaque capsule recevait donc un
    unique tag machine nommé « mots-clés », et ses vrais mots-clés étaient
    perdus — sans erreur, sans trace, sans que rien ne le signale.
    / The model returns an object, never the requested array; iterating it
      yields the keys, so every capsule got a single tag named "mots-clés".
    """
    from capsules.tasks import _appeler_le_modele_de_tags

    with patch(
        "mistralai.client.Mistral",
        _client_qui_repond(
            '```json\n{"mots-clés": ["boulangerie", "fermeture", "nostalgie"]}\n```'
        ),
    ):
        assert _appeler_le_modele_de_tags("peu importe") == [
            "boulangerie", "fermeture", "nostalgie",
        ]


def test_les_mots_cles_acceptent_aussi_le_tableau_nu():
    """L'autre forme reste valable : le jour où le modèle obéit, rien ne casse.
    / The obedient form must keep working."""
    from capsules.tasks import _appeler_le_modele_de_tags

    with patch("mistralai.client.Mistral",
               _client_qui_repond('["rue", "pluie", "marché"]')):
        assert _appeler_le_modele_de_tags("peu importe") == ["rue", "pluie", "marché"]
