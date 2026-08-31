"""Transcription par Voxtral, avec diarisation.
/ Voxtral transcription, with diarization."""

import logging
import os
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)


def transcrire_le_fichier(chemin_audio: str) -> dict:
    """Rend {"texte": str, "langue": str, "segments": [{speaker, start, end, text}]}.

    TROIS CONTRAINTES DE L'API MISTRAL, APPRISES EN PRODUCTION SUR HYPOSTASIA.
    Les violer coute une demi-journee :
      1. `diarize=True` EXIGE `timestamp_granularities=["segment"]`.
      2. `language` est INCOMPATIBLE avec `timestamp_granularities`. Puisqu'on
         diarise, on NE PEUT PAS forcer la langue : detection automatique
         obligatoire. Dans l'espace public c'est un avantage — une capsule en
         creole ou en arabe sera transcrite sans rien declarer.
      3. La cle vit dans l'environnement, JAMAIS en base.
    / Three hard-won Mistral API constraints; violating them costs half a day.
    """
    # SDK v2 : l'import est `mistralai.client`, PAS `mistralai`. En v2 la
    # distribution est devenue un namespace package sans __init__ — `from
    # mistralai import Mistral` leve alors un ImportError « unknown location »,
    # que la tache attrape et enregistre comme un simple echec d'enrichissement.
    # La panne serait donc silencieuse. Les signatures, elles, n'ont pas bouge.
    # / v2 moved the export to mistralai.client; the old import fails silently here.
    from mistralai.client import Mistral

    cle = os.environ.get("MISTRAL_API_KEY", "")
    if not cle:
        raise ValueError("Clé API Mistral manquante. Renseignez MISTRAL_API_KEY.")

    client = Mistral(api_key=cle)

    with open(chemin_audio, "rb") as fichier:
        reponse = client.audio.transcriptions.complete(
            file={"content": fichier, "file_name": Path(chemin_audio).name},
            model=settings.MISTRAL_MODELE_TRANSCRIPTION,
            diarize=True,
            timestamp_granularities=["segment"],
        )

    segments = []
    for segment in reponse.segments or []:
        identifiant = getattr(segment, "speaker_id", None)
        segments.append(
            {
                "speaker": identifiant if identifiant else "voix",
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
            }
        )

    return {
        "texte": reponse.text or " ".join(s["text"] for s in segments),
        "langue": getattr(reponse, "language", "") or "",
        "segments": segments,
    }
