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


def _enfiler(tache, uuid_capsule: str) -> None:
    """Enfile une suite sans laisser son echec remonter.
    / Queues a follow-up without letting its failure bubble up."""
    try:
        tache.delay(uuid_capsule)
    except Exception:
        logger.exception("enqueue de %s impossible pour %s", tache.name, uuid_capsule)


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

    # `update_fields` N'EST PAS UNE OPTIMISATION ICI, C'EST UNE CORRECTION.
    # L'instance a ete chargee avant l'appel a Voxtral, qui dure de dix
    # secondes a une minute. Un `save()` complet reecrirait l'etat d'alors :
    # une capsule retiree entre-temps par l'operateur redeviendrait publiee —
    # le retrait LCEN annule sans trace — et les ecoutes comptees pendant
    # l'appel seraient perdues.
    # / Not an optimisation: a full save would resurrect a capsule the operator
    #   withdrew during the call, and lose the plays counted meanwhile.
    capsule.save(update_fields=[
        "transcription_raw", "transcription_texte",
        "langue_detectee", "erreur_enrichissement",
    ])

    # DIFFERE AU COMMIT : diffuser avant que la transaction soit ecrite
    # enverrait un texte que la base ne contient pas encore. En cas de
    # rollback, la page afficherait une transcription qui n'existe pas.
    # / Deferred to commit: broadcasting earlier could push uncommitted text.
    transaction.on_commit(lambda: diffuser_la_transcription(capsule))

    # LES DEUX SUITES PARTENT D'ICI, EN PARALLELE, ET C'EST VOLONTAIRE.
    # Enchainer `embarquer` derriere `taguer` faisait dependre la presence meme
    # de la clameur sur la page d'accueil — liste ET ciel — de la reussite
    # d'une extraction de mots-cles, l'etape la plus fragile de la chaine : il
    # suffisait que le modele entoure son JSON de balises de code pour que la
    # capsule reste invisible a jamais.
    # / Chaining the embedding behind tagging made the capsule's very presence
    #   on the home page depend on the most brittle step of the chain.
    _enfiler(taguer, uuid_capsule)
    _enfiler(embarquer, uuid_capsule)
    return "ok"


def _appeler_le_modele_de_tags(texte: str) -> list[str]:
    """Demande des mots-clés au modèle et rend une liste de chaînes.

    LE MODELE ENTOURE SOUVENT SON JSON DE BALISES DE CODE, même quand on lui
    demande de n'en pas mettre. Sans ce nettoyage, `json.loads` lève et la
    capsule perd ses mots-clés sur une question de mise en forme.
    / Models often fence their JSON even when told not to.

    ET IL REPOND UN OBJET, JAMAIS LE TABLEAU DEMANDE. Relevé sur une vraie
    capsule le 2026-08-31, trois fois sur trois :

        {"mots-clés": ["boulangerie", "fermeture", "nostalgie"]}

    Itérer sur ce dictionnaire donne ses CLÉS. Chaque capsule recevait donc un
    unique tag machine nommé « mots-clés » à la place de ses vrais mots-clés —
    sans erreur, sans trace : `taguer` rendait « ok ». Le mock de la suite de
    tests, lui, rendait sagement un tableau, et cachait le défaut.
    On demande donc un objet, ET on accepte les deux formes : la panne était
    silencieuse, elle mérite deux filets.
    / The model returns an object whose keys we were iterating over; we now ask
      for an object and accept both shapes.
    """
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
                    'un objet JSON de la forme {"tags": ["…"]}, sans commentaire.'
                    "\n\n"
                    f"{texte[:4000]}"
                ),
            }
        ],
        response_format={"type": "json_object"},
    )
    brut = (reponse.choices[0].message.content or "").strip()
    if brut.startswith("```"):
        brut = brut.split("```")[1] if "```" in brut[3:] else brut[3:]
        brut = brut.removeprefix("json").strip()
    valeur = json.loads(brut)
    if isinstance(valeur, dict):
        # La premiere valeur qui est une liste, quel que soit le nom de la cle :
        # le modele l'appelle tantot « tags », tantot « mots-clés », tantot
        # « mots_clés ». / Whatever the key is called.
        valeur = next((v for v in valeur.values() if isinstance(v, list)), [])
    return [str(mot) for mot in valeur]


@shared_task
def taguer(uuid_capsule: str) -> str:
    capsule = Capsule.objects.get(uuid=uuid_capsule)
    if not capsule.transcription_texte:
        return "rien a taguer"

    try:
        mots = _appeler_le_modele_de_tags(capsule.transcription_texte)
    except Exception as erreur:
        _noter_l_echec(capsule, "Extraction des tags", erreur)
        return "echec"

    for mot in [str(m).strip().lower()[:60] for m in mots][:NOMBRE_DE_TAGS_MACHINE]:
        if not mot:
            continue
        tag, _cree = Tag.objects.get_or_create(nom=mot)
        # Les tags de la machine ne se melangent jamais a ceux de l'auteur.
        # / Machine tags never blend into the author's own words.
        TagDeCapsule.objects.get_or_create(
            capsule=capsule, tag=tag, origine=TagDeCapsule.MACHINE
        )

    return "ok"


def _calculer_le_vecteur(texte: str) -> list[float]:
    """Rend le vecteur du texte, tel que le modèle le produit.
    / Returns the text's vector, as produced by the model."""
    from mistralai.client import Mistral

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    reponse = client.embeddings.create(
        model=settings.MISTRAL_MODELE_EMBEDDING, inputs=[texte[:8000]]
    )
    return reponse.data[0].embedding


@shared_task
def embarquer(uuid_capsule: str) -> str:
    """Calcule le vecteur qui place la clameur dans la constellation.
    / Computes the vector that places the clameur in the constellation."""
    capsule = Capsule.objects.get(uuid=uuid_capsule)
    if not capsule.transcription_texte:
        return "rien a embarquer"

    try:
        vecteur = _calculer_le_vecteur(capsule.transcription_texte)
    except Exception as erreur:
        _noter_l_echec(capsule, "Embedding", erreur)
        return "echec"

    attendu = settings.MISTRAL_DIMENSIONS_EMBEDDING
    if len(vecteur) != attendu:
        # Un vecteur tronque entrerait en base et fausserait la projection
        # entiere sans que rien ne le signale.
        # / A truncated vector would silently skew the whole projection.
        _noter_l_echec(
            capsule, "Embedding",
            ValueError(f"{len(vecteur)} dimensions au lieu de {attendu}"),
        )
        return "echec"

    capsule.embedding = vecteur
    capsule.enrichie_le = timezone.now()
    capsule.save(update_fields=["embedding", "enrichie_le"])
    return "ok"
