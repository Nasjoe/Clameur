"""Envoi des tickets. / Ticket sending."""

import logging
import os

from celery import shared_task
from django.conf import settings
from django.urls import reverse

from impression.mock import MockBackend
from impression.models import JobImpression, StatutJob
from impression.sunmi_cloud import SunmiCloudBackend

logger = logging.getLogger(__name__)


def choisir_le_backend(borne):
    """Sunmi si les identifiants sont la, le mock sinon.

    En developpement, personne n'a d'imprimante sous la main : le mock ecrit le
    ticket dans les journaux, avec exactement les memes octets.
    / Mock when no credentials: same bytes, printed to the log.
    """
    if os.environ.get("SUNMI_APP_ID") and os.environ.get("SUNMI_APP_KEY"):
        return SunmiCloudBackend(borne)
    return MockBackend(borne)


def url_de_la_capsule(capsule) -> str:
    chemin = reverse("capsules:lire_capsule", args=[capsule.uuid])
    return f"{settings.URL_PUBLIQUE.rstrip('/')}{chemin}"


@shared_task
def envoyer_le_ticket(job_pk: int) -> str:
    job = JobImpression.objects.select_related("capsule", "borne").get(pk=job_pk)

    # CELERY REDELIVRE LES TACHES INTERROMPUES (`task_acks_late`). Sans ce
    # garde, un redemarrage au mauvais moment — un redeploiement, un worker
    # tue — ferait repartir l'envoi et sortir un second ticket identique. Le
    # papier, lui, ne se rembobine pas.
    # / acks_late redelivers interrupted tasks: without this guard a redeploy
    #   would print the same ticket twice.
    if job.statut == StatutJob.ENVOYE:
        logger.info("ticket %s deja envoye, on ne le rejoue pas", job.pk)
        return job.statut

    backend = choisir_le_backend(job.borne)

    possible, message = backend.can_print()
    if not possible:
        job.statut = StatutJob.ECHOUE
        job.message_erreur = message
        job.tentatives += 1
        job.save()
        logger.warning("ticket %s impossible : %s", job.pk, message)
        return job.statut

    try:
        job.trade_no = backend.print_ticket(job.capsule, url_de_la_capsule(job.capsule))
        job.statut = StatutJob.ENVOYE
        job.message_erreur = ""
    except Exception as erreur:
        job.statut = StatutJob.ECHOUE
        job.message_erreur = str(erreur)
        logger.exception("envoi du ticket %s echoue", job.pk)

    job.tentatives += 1
    job.save()
    return job.statut
