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
def test_l_embedding_ne_part_plus_derriere_la_transcription(capsule_a_transcrire):
    """L'embedding est EN SOMMEIL depuis le 2026-09-01, avec la constellation.

    La tâche existe toujours et se rejoue depuis la console, mais plus rien ne
    l'enfile : publier une clameur ne déclenche aucun calcul de proximité.
    / Dormant since the constellation was shelved: the task remains, nothing
      queues it."""
    lances = []
    with patch("capsules.tasks.transcrire_le_fichier", return_value=TRANSCRIPTION), \
         patch("capsules.tasks.diffuser_la_transcription"), \
         patch.object(taguer, "delay", lambda u: lances.append("taguer")), \
         patch.object(embarquer, "delay", lambda u: lances.append("embarquer")):
        transcrire(str(capsule_a_transcrire.uuid))

    assert lances == ["taguer"], (
        "seule l'extraction du titre et des mots-clés suit la transcription"
    )


# ------------------------------------------------------------------- taguer

@pytest.mark.django_db
def test_les_tags_du_modele_sont_marques_comme_tels(capsule_a_transcrire):
    capsule_a_transcrire.transcription_texte = TRANSCRIPTION["texte"]
    capsule_a_transcrire.save()

    with patch("capsules.tasks._appeler_le_modele", return_value=("", ["rue", "pluie"])):
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

    with patch("capsules.tasks._appeler_le_modele", side_effect=ValueError("JSON illisible")):
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

@pytest.fixture(autouse=True)
def cle_factice(monkeypatch):
    """`_appeler_le_modele_de_tags` lit `os.environ["MISTRAL_API_KEY"]` sans
    filet. Les tests ci-dessous ne tenaient que parce que le `.env` du
    conteneur porte la ligne, même vide : le jour où elle disparaît, ils
    lèveraient un KeyError sans rapport avec ce qu'ils vérifient. La spec veut
    un projet testable sans clé.
    / The tests only held because the container's .env carries the line.
    """
    monkeypatch.setenv("MISTRAL_API_KEY", "clé-factice-jamais-appelée")


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
    from capsules.tasks import _appeler_le_modele

    with patch(
        "mistralai.client.Mistral",
        _client_qui_repond(
            '```json\n{"mots-clés": ["boulangerie", "fermeture", "nostalgie"]}\n```'
        ),
    ):
        _titre, mots = _appeler_le_modele("peu importe")

    assert mots == ["boulangerie", "fermeture", "nostalgie"]


def test_les_mots_cles_acceptent_aussi_le_tableau_nu():
    """L'autre forme reste valable : le jour où le modèle obéit, rien ne casse.
    / The obedient form must keep working."""
    from capsules.tasks import _appeler_le_modele

    with patch("mistralai.client.Mistral",
               _client_qui_repond('["rue", "pluie", "marché"]')):
        _titre, mots = _appeler_le_modele("peu importe")

    assert mots == ["rue", "pluie", "marché"]


def test_une_reponse_sans_aucune_liste_est_un_echec_visible():
    """Le modèle a répondu quelque chose, mais rien qui ressemble à des tags.

    Rendre une liste vide ferait dire « ok » à la tâche et laisserait la
    capsule sans mots-clés, sans erreur, sans trace — exactement la panne
    silencieuse qu'on vient de corriger. Mieux vaut un échec inscrit dans
    `erreur_enrichissement`, que l'opérateur voit et peut rejouer.
    / An empty list would report success and lose the keywords in silence.
    """
    from capsules.tasks import _appeler_le_modele

    with patch("mistralai.client.Mistral",
               _client_qui_repond('{"resultat": "je ne sais pas"}')), \
         pytest.raises(ValueError):
        _appeler_le_modele("peu importe")


def test_on_demande_au_modele_un_objet_json():
    """L'autre moitié du correctif : on ne se contente pas de tolérer l'objet,
    on le demande. Sans `response_format`, le modèle retombe sur ses habitudes
    et sur ses balises de code, et le nettoyage redevient la seule défense.
    / We don't merely tolerate the object shape, we ask for it.
    """
    from capsules.tasks import _appeler_le_modele

    fabrique = _client_qui_repond('{"tags": ["rue", "pluie", "marché"]}')
    client = fabrique()
    with patch("mistralai.client.Mistral", lambda **_: client):
        _appeler_le_modele("peu importe")

    appel = client.chat.complete.call_args.kwargs
    assert appel["response_format"] == {"type": "json_object"}


# ------------------------------- l'erreur s'efface quand l'etape reussit

@pytest.mark.django_db
def test_un_tagage_reussi_efface_l_erreur_de_tagage(capsule_a_transcrire):
    """Une erreur périmée reste affichée en console tant que rien ne l'efface.

    L'opérateur rejoue l'étape, elle réussit, et la capsule continue d'annoncer
    un échec : il ne peut plus distinguer ce qui est réparé de ce qui ne l'est
    pas. / A stale error keeps a repaired capsule looking broken.
    """
    capsule_a_transcrire.transcription_texte = TRANSCRIPTION["texte"]
    capsule_a_transcrire.erreur_enrichissement = "Extraction des tags : JSON illisible"
    capsule_a_transcrire.save()

    with patch("capsules.tasks._appeler_le_modele", return_value=("", ["rue"])):
        assert taguer(str(capsule_a_transcrire.uuid)) == "ok"

    capsule_a_transcrire.refresh_from_db()
    assert capsule_a_transcrire.erreur_enrichissement == ""


@pytest.mark.django_db
def test_un_tagage_reussi_ne_masque_pas_l_echec_D_UNE_AUTRE_ETAPE(capsule_a_transcrire):
    """Les trois étapes partagent un seul champ, et deux d'entre elles courent
    EN PARALLÈLE. Effacer sans regarder ferait disparaître l'échec du voisin :
    la capsule n'aurait plus d'étoile, et plus rien ne dirait pourquoi.
    / One field for three steps, two of them concurrent: a blind wipe would
      hide the neighbour's failure.
    """
    capsule_a_transcrire.transcription_texte = TRANSCRIPTION["texte"]
    capsule_a_transcrire.erreur_enrichissement = "Embedding : 512 dimensions au lieu de 1024"
    capsule_a_transcrire.save()

    with patch("capsules.tasks._appeler_le_modele", return_value=("", ["rue"])):
        assert taguer(str(capsule_a_transcrire.uuid)) == "ok"

    capsule_a_transcrire.refresh_from_db()
    assert capsule_a_transcrire.erreur_enrichissement.startswith("Embedding"), (
        "l'échec de l'embedding a été effacé par la réussite du tagage"
    )


@pytest.mark.django_db
def test_un_embedding_reussi_efface_l_erreur_d_embedding(capsule_a_transcrire):
    capsule_a_transcrire.transcription_texte = TRANSCRIPTION["texte"]
    capsule_a_transcrire.erreur_enrichissement = "Embedding : service indisponible"
    capsule_a_transcrire.save()

    with patch("capsules.tasks._calculer_le_vecteur", return_value=[0.1] * 1024):
        assert embarquer(str(capsule_a_transcrire.uuid)) == "ok"

    capsule_a_transcrire.refresh_from_db()
    assert capsule_a_transcrire.erreur_enrichissement == ""


@pytest.mark.django_db
def test_un_embedding_reussi_ne_masque_pas_l_echec_des_tags(capsule_a_transcrire):
    capsule_a_transcrire.transcription_texte = TRANSCRIPTION["texte"]
    capsule_a_transcrire.erreur_enrichissement = "Extraction des tags : JSON illisible"
    capsule_a_transcrire.save()

    with patch("capsules.tasks._calculer_le_vecteur", return_value=[0.1] * 1024):
        assert embarquer(str(capsule_a_transcrire.uuid)) == "ok"

    capsule_a_transcrire.refresh_from_db()
    assert capsule_a_transcrire.erreur_enrichissement.startswith("Extraction des tags"), (
        "l'échec des tags a été effacé par la réussite de l'embedding"
    )


@pytest.mark.django_db
def test_le_titre_arrive_avec_les_mots_cles(capsule_a_transcrire):
    """Un titre, dans le MEME appel que les mots-clés : ni étape, ni coût de
    plus. C'est ce titre que la liste affiche en premier.
    / One call for both: no extra step, no extra cost."""
    capsule_a_transcrire.transcription_texte = TRANSCRIPTION["texte"]
    capsule_a_transcrire.save()

    with patch("capsules.tasks._appeler_le_modele",
               return_value=("La boulangerie ferme", ["boulangerie", "quartier"])):
        assert taguer(str(capsule_a_transcrire.uuid)) == "ok"

    capsule_a_transcrire.refresh_from_db()
    assert capsule_a_transcrire.titre == "La boulangerie ferme"


def test_le_titre_se_lit_dans_la_reponse_du_modele():
    from capsules.tasks import _appeler_le_modele

    with patch("mistralai.client.Mistral", _client_qui_repond(
        '{"titre": "La boulangerie ferme", "tags": ["boulangerie", "fermeture"]}'
    )):
        titre, mots = _appeler_le_modele("peu importe")

    assert titre == "La boulangerie ferme"
    assert mots == ["boulangerie", "fermeture"]


def test_un_titre_absent_n_empeche_pas_les_mots_cles():
    """Le titre est un confort, les mots-clés sont la matière de la recherche :
    l'un ne doit pas emporter l'autre.
    / The title is a comfort; the keywords feed the search."""
    from capsules.tasks import _appeler_le_modele

    with patch("mistralai.client.Mistral",
               _client_qui_repond('{"tags": ["rue", "pluie"]}')):
        titre, mots = _appeler_le_modele("peu importe")

    assert titre == ""
    assert mots == ["rue", "pluie"]
