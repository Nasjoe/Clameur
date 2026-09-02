"""Diffusion des transcriptions terminees aux pages ouvertes.
/ Pushes finished transcriptions to open pages."""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.template.loader import render_to_string

from capsules.consumers import GROUPE

logger = logging.getLogger(__name__)


def diffuser_la_transcription(capsule) -> None:
    """Envoie le fragment de transcription a toutes les pages ouvertes.

    NE LEVE JAMAIS. Une panne de Redis ou de la couche de canaux ne doit pas
    faire echouer la tache de transcription : le texte est deja enregistre en
    base, et il apparaitra au prochain chargement de la page. Le temps reel
    est un confort, jamais une condition.
    / Never raises: real time is a comfort, never a requirement.
    """
    from capsules.views import preparer_les_paroles

    try:
        html = render_to_string(
            "capsules/_transcription.html",
            {
                "capsule": capsule,
                "segments": preparer_les_paroles(
                    (capsule.transcription_raw or {}).get("segments") or []
                ),
                # `oob` ajoute hx-swap-oob sur l'element racine. On utilise
                # `outerHTML` et non `innerHTML` : innerHTML ne remplacerait
                # que le contenu, laissant les attributs de l'element intacts —
                # ici l'indicateur d'attente resterait en place.
                # / outerHTML, not innerHTML: attributes must be replaced too.
                "oob": True,
            },
        )
        async_to_sync(get_channel_layer().group_send)(
            GROUPE, {"type": "fragment.html", "html": html}
        )
    except Exception:
        logger.exception("diffusion de la transcription impossible pour %s", capsule.uuid)
