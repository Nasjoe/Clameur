"""Contrat avec le SDK Mistral.

Ces tests ne parlent a aucune API : ils verifient que le SDK installe expose
encore ce sur quoi le code compte. Sans eux, une montee de version casse
l'enrichissement EN SILENCE — la tache Celery attrape l'exception et se
contente d'ecrire « echec » dans erreur_enrichissement.
/ Contract tests: a SDK upgrade would otherwise break enrichment silently.
"""

import inspect


def test_le_client_s_importe_depuis_mistralai_client():
    """En v2 la distribution est un namespace package : `from mistralai import
    Mistral` ne fonctionne plus."""
    from mistralai.client import Mistral

    assert Mistral is not None


def test_la_transcription_accepte_diarisation_et_granularite():
    """Les trois contraintes de la spec reposent sur ces parametres."""
    from mistralai.client import Mistral

    parametres = inspect.signature(
        Mistral(api_key="factice").audio.transcriptions.complete
    ).parameters
    for attendu in ("model", "file", "diarize", "timestamp_granularities", "language"):
        assert attendu in parametres, f"parametre {attendu} disparu du SDK"


def test_les_embeddings_prennent_toujours_model_et_inputs():
    from mistralai.client import Mistral

    parametres = inspect.signature(Mistral(api_key="factice").embeddings.create).parameters
    assert "model" in parametres
    assert "inputs" in parametres
