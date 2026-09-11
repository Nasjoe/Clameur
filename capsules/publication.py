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

# NETTEMENT SOUS LE DELAI DE GUNICORN (300 s, voir supervisord.conf). Les deux
# etaient egaux : gunicorn tuait donc le worker avant que ffmpeg n'atteigne son
# propre delai, et le repli sur l'audio d'origine — la moitie de l'invariant
# I1 — n'etait jamais atteint. Pire depuis que la publication tient dans une
# transaction : au lieu d'une capsule publiee sans ticket, on obtenait un
# rollback, une capsule bloquee en brouillon, et rien pour la rattraper.
# / They were equal, so gunicorn killed the worker before ffmpeg could time out
#   and the fallback was never reached.
#
# 240 S, ET NON PLUS 60, DEPUIS QUE LA DUREE D'UNE CLAMEUR N'EST PLUS BORNEE
# (2026-09-11). Mesure faite : une heure d'audio se normalise en 34 s. Le
# fichier le plus lourd que nginx laisse passer (64 Mo, un memo vocal a bas
# debit, quatre heures environ) en demanderait deux minutes et demie. Au-dela,
# le repli sur l'original joue : la publication n'echoue jamais.
# tests/test_delais.py verifie que gunicorn et nginx restent au-dessus.
# / 240 s since duration is unbounded: one hour takes 34 s to normalise.
DUREE_MAX_FFMPEG = 240

# ffprobe lit un en-tete, il ne convertit rien : trente secondes, c'est deja un
# fichier qui ne repond pas. Il court APRES ffmpeg a la publication, les deux
# s'additionnent donc sous le delai de gunicorn (tests/test_delais.py).
# / ffprobe runs after ffmpeg: both add up under gunicorn's timeout.
DUREE_MAX_FFPROBE = 30


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
                    # -vn : LE SON SEULEMENT. Un fichier depose peut etre une
                    # video ; sans cette option, ffmpeg reencodait aussi son
                    # image dans le m4a — lent, et lourd a servir.
                    # / Audio only: a dropped video file kept its picture track.
                    "-vn",
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
    except Exception as erreur:
        # Repli sur l'original : mieux vaut un audio mal encode que pas d'audio.
        # / Fall back to the original: bad encoding beats no audio at all.
        logger.exception("normalisation impossible pour %s", capsule.uuid)
        capsule.erreur_enrichissement = f"Normalisation audio impossible : {erreur}"

    # LA DUREE SE MESURE MEME QUAND FFMPEG A ABANDONNE. Un fichier depose arrive
    # avec une duree annoncee de 0 : mesuree dans le `try`, elle sautait avec
    # ffmpeg, et le ticket annoncait « 0 s ». Le m4a d'abord quand il existe :
    # ffprobe ne sait pas lire la duree d'un webm de MediaRecorder.
    # / Measured even when ffmpeg gave up; the m4a first, when there is one.
    if not capsule.duree_secondes:
        chemin = (
            capsule.audio_diffusion.path
            if capsule.audio_diffusion
            else capsule.audio_original.path
        )
        capsule.duree_secondes = _duree_du_fichier(chemin)


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
            timeout=DUREE_MAX_FFPROBE,
            text=True,
        )
        return int(float(resultat.stdout.strip()))
    except Exception:
        return 0


def a_une_piste_audio(chemin: str) -> bool:
    """Faux SEULEMENT si ffprobe lit le fichier et n'y trouve aucune piste audio.

    Au moindre doute — ffprobe en echec, trop lent, fichier qu'il ne sait pas
    lire — on repond vrai : refuser a tort un vrai enregistrement serait bien
    pire que laisser passer un fichier douteux. Ce n'est PAS une liste blanche
    de formats : c'est le contenu qu'on regarde.
    / False only when ffprobe reads the file and finds no audio stream.
    """
    try:
        resultat = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                chemin,
            ],
            check=True,
            capture_output=True,
            timeout=DUREE_MAX_FFPROBE,
            text=True,
        )
    except Exception:
        return True
    return bool(resultat.stdout.strip())


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
