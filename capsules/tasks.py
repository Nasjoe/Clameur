"""Enrichissement semantique. Toujours facultatif, jamais bloquant.
/ Semantic enrichment: always optional, never blocking."""

import json
import logging
import os

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from capsules.diffusion import diffuser_la_transcription
from capsules.models import Capsule, Tag, TagDeCapsule
from capsules.transcription import transcrire_le_fichier

logger = logging.getLogger(__name__)

NOMBRE_DE_TAGS_MACHINE = 3


def _noter_l_echec(capsule, etape: str, erreur: Exception) -> None:
    """Une panne de Mistral ne depublie JAMAIS une capsule : elle la prive
    seulement de sa transcription. / A Mistral outage never unpublishes."""
    logger.exception("%s impossible pour %s", etape, capsule.uuid)
    capsule.erreur_enrichissement = f"{etape} : {erreur}"
    capsule.save(update_fields=["erreur_enrichissement"])


@shared_task
def transcrire(uuid_capsule: str) -> str:
    capsule = Capsule.objects.get(uuid=uuid_capsule)
    try:
        resultat = transcrire_le_fichier(capsule.audio_a_servir.path)
    except Exception as erreur:
        _noter_l_echec(capsule, "Transcription", erreur)
        return "echec"

    capsule.transcription_raw = {"segments": resultat["segments"]}
    capsule.transcription_texte = resultat["texte"]
    capsule.langue_detectee = resultat["langue"]
    capsule.erreur_enrichissement = ""
    capsule.save()

    # DIFFERE AU COMMIT : diffuser avant que la transaction soit ecrite
    # enverrait un texte que la base ne contient pas encore. En cas de
    # rollback, la page afficherait une transcription qui n'existe pas.
    # / Deferred to commit: broadcasting earlier could push uncommitted text.
    transaction.on_commit(lambda: diffuser_la_transcription(capsule))

    taguer.delay(uuid_capsule)
    return "ok"


@shared_task
def taguer(uuid_capsule: str) -> str:
    capsule = Capsule.objects.get(uuid=uuid_capsule)
    if not capsule.transcription_texte:
        return "rien a taguer"

    try:
        from mistralai.client import Mistral

        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        reponse = client.chat.complete(
            model=settings.MISTRAL_MODELE_TAGS,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Donne exactement {NOMBRE_DE_TAGS_MACHINE} mots-clés en "
                        "français décrivant ce témoignage. Réponds uniquement par "
                        'un tableau JSON de chaînes, sans commentaire.\n\n'
                        f"{capsule.transcription_texte[:4000]}"
                    ),
                }
            ],
        )
        mots = json.loads(reponse.choices[0].message.content)
    except Exception as erreur:
        _noter_l_echec(capsule, "Extraction des tags", erreur)
        return "echec"

    for mot in [str(m).strip().lower()[:60] for m in mots][:NOMBRE_DE_TAGS_MACHINE]:
        if not mot:
            continue
        tag, _ = Tag.objects.get_or_create(nom=mot)
        # Les tags de la machine ne se melangent jamais a ceux de l'auteur.
        # / Machine tags never blend into the author's own words.
        TagDeCapsule.objects.get_or_create(
            capsule=capsule, tag=tag, origine=TagDeCapsule.MACHINE
        )

    embarquer.delay(uuid_capsule)
    return "ok"


@shared_task
def embarquer(uuid_capsule: str) -> str:
    """Calcule le vecteur qui servira la constellation du sous-projet 2.
    Rien ne le consomme aujourd'hui, et c'est voulu.
    / Computes the vector for sub-project 2. Nothing reads it yet, by design."""
    capsule = Capsule.objects.get(uuid=uuid_capsule)
    if not capsule.transcription_texte:
        return "rien a embarquer"

    try:
        from mistralai.client import Mistral

        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        reponse = client.embeddings.create(
            model=settings.MISTRAL_MODELE_EMBEDDING,
            inputs=[capsule.transcription_texte[:8000]],
        )
        vecteur = reponse.data[0].embedding
    except Exception as erreur:
        _noter_l_echec(capsule, "Embedding", erreur)
        return "echec"

    attendu = settings.MISTRAL_DIMENSIONS_EMBEDDING
    if len(vecteur) != attendu:
        _noter_l_echec(
            capsule, "Embedding",
            ValueError(f"{len(vecteur)} dimensions au lieu de {attendu}"),
        )
        return "echec"

    capsule.embedding = vecteur
    capsule.enrichie_le = timezone.now()
    capsule.save(update_fields=["embedding", "enrichie_le"])
    return "ok"
