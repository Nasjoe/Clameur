"""Publier une capsule. Le moment le plus important du projet.
/ Publishing a capsule: the project's most important moment."""

import logging
import subprocess
import tempfile
from pathlib import Path

from django.core.files import File
from django.db import transaction
from django.utils import timezone

from capsules.models import StatutCapsule

logger = logging.getLogger(__name__)

# NETTEMENT SOUS LE DELAI DE GUNICORN (180 s, voir supervisord.conf). Les deux
# etaient egaux : gunicorn tuait donc le worker avant que ffmpeg n'atteigne son
# propre delai, et le repli sur l'audio d'origine — la moitie de l'invariant
# I1 — n'etait jamais atteint. Pire depuis que la publication tient dans une
# transaction : au lieu d'une capsule publiee sans ticket, on obtenait un
# rollback, une capsule bloquee en brouillon, et rien pour la rattraper.
# / They were equal, so gunicorn killed the worker before ffmpeg could time out
#   and the fallback was never reached.
DUREE_MAX_FFMPEG = 60


def normaliser_l_audio(capsule) -> None:
    """Produit l'AAC/m4a servi aux navigateurs.

    SYNCHRONE, ET C'EST DELIBERE. Le navigateur envoie du webm/opus (Chrome,
    Android), du mp4/aac (iOS) ou de l'ogg/opus (Firefox). Seul l'AAC est lu
    partout. Sans cette etape, une capsule enregistree sur Android reste muette
    sur l'iPhone qui scanne le ticket — et le premier a scanner, c'est presque
    toujours son auteur.
    / Synchronous on purpose: without AAC, an Android recording is silent on iOS.

    Ne leve jamais : publier ne doit pas pouvoir echouer.
    / Never raises: publishing must not be allowed to fail.
    """
    try:
        with tempfile.TemporaryDirectory() as dossier:
            sortie = Path(dossier) / "diffusion.m4a"
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", capsule.audio_original.path,
                    "-c:a", "aac", "-b:a", "64k", "-ac", "1",
                    # +faststart deplace l'atome `moov` en TETE du fichier.
                    # Sans lui, ffmpeg le laisse a la fin : le navigateur ne
                    # connait alors ni la duree ni ne peut se deplacer dans
                    # l'audio avant de l'avoir telecharge en entier. Le passant
                    # voit « 0:00 / 0:00 » et une barre inerte.
                    # / Without +faststart the player shows no duration and cannot seek.
                    "-movflags", "+faststart",
                    str(sortie),
                ],
                check=True,
                capture_output=True,
                timeout=DUREE_MAX_FFMPEG,
            )
            with open(sortie, "rb") as fichier:
                capsule.audio_diffusion.save("diffusion.m4a", File(fichier), save=False)

            capsule.duree_secondes = capsule.duree_secondes or _duree_du_fichier(
                capsule.audio_original.path
            )
    except Exception as erreur:
        # Repli sur l'original : mieux vaut un audio mal encode que pas d'audio.
        # / Fall back to the original: bad encoding beats no audio at all.
        logger.exception("normalisation impossible pour %s", capsule.uuid)
        capsule.erreur_enrichissement = f"Normalisation audio impossible : {erreur}"


def _duree_du_fichier(chemin: str) -> int:
    """Duree en secondes, 0 si ffprobe ne sait pas. / Duration, 0 if unknown."""
    try:
        resultat = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                chemin,
            ],
            check=True,
            capture_output=True,
            timeout=30,
            text=True,
        )
        return int(float(resultat.stdout.strip()))
    except Exception:
        return 0


def publier(capsule) -> None:
    """Rend une capsule ecoutable, met un ticket en file, lance l'enrichissement.

    L'ORDRE DES OPERATIONS EST LE DESIGN LUI-MEME :
    1. normaliser  — synchrone, sinon la capsule est muette sur iOS (I1)
    2. ecrire en base — la base est la source de verite, jamais la file (I2)
    3. enfiler — chaque enqueue peut echouer sans consequence (I2, I3)
    / The order of operations IS the design.
    """
    from capsules.tasks import transcrire
    from impression.models import JobImpression
    from impression.tasks import envoyer_le_ticket

    normaliser_l_audio(capsule)

    capsule.statut = StatutCapsule.PUBLIEE
    capsule.publiee_le = timezone.now()
    capsule.save()

    job = JobImpression.objects.create(capsule=capsule, reglages=capsule.reglages)

    # Redis n'est pas une dependance de la publication. S'il est mort, la
    # capsule est publiee et ecoutable, et l'operateur relance depuis la
    # console. / Redis is not a dependency of publishing.
    # APRES LE COMMIT, JAMAIS AVANT. Un worker Celery est un autre process
    # avec sa propre connexion : enfiler dans une transaction encore ouverte
    # lui ferait chercher une capsule que sa transaction ne voit pas encore.
    # Hors transaction, `on_commit` s'execute immediatement — le code est donc
    # correct dans les deux cas.
    # / A worker is another process: queueing inside an open transaction would
    #   send it looking for a row it cannot see yet.
    transaction.on_commit(
        lambda: _enfiler_sans_risque(lambda: envoyer_le_ticket.delay(job.pk), "impression")
    )
    transaction.on_commit(
        lambda: _enfiler_sans_risque(lambda: transcrire.delay(str(capsule.uuid)), "transcription")
    )


def _enfiler_sans_risque(envoi, nom_de_la_tache: str) -> None:
    try:
        envoi()
    except Exception:
        logger.exception(
            "enqueue %s impossible — relance depuis la console", nom_de_la_tache
        )
