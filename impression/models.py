"""File d'impression des tickets. / Ticket printing queue."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class StatutJob(models.TextChoices):
    EN_ATTENTE = "en_attente", _("En attente")
    ENVOYE = "envoye", _("Envoyé")
    ECHOUE = "echoue", _("Échoué")


class JobImpression(models.Model):
    """Un ticket a imprimer.

    PAS D'ETAT « IMPRIME » EN V1. Le mode push n'expose aucun endpoint : Sunmi
    ne rappelle jamais, un tel etat serait donc inatteignable sans une tache de
    verification differee que rien ne justifie tant que l'operateur est devant
    la machine et voit le papier sortir. `printStatus(trade_no)` reste
    appelable a la main depuis la console en cas de doute.
    / No "printed" state in v1: push mode has no callback, so it would be unreachable.
    """

    capsule = models.ForeignKey(
        "capsules.Capsule", on_delete=models.CASCADE, related_name="jobs_impression",
    )
    borne = models.ForeignKey(
        "bornes.Borne", on_delete=models.PROTECT, related_name="jobs_impression",
    )
    statut = models.CharField(
        max_length=20, choices=StatutJob.choices,
        default=StatutJob.EN_ATTENTE, verbose_name=_("statut"),
    )
    trade_no = models.CharField(
        max_length=100, blank=True, verbose_name=_("numéro Sunmi"),
        help_text=_("Conservé pour interroger printStatus depuis la console."),
    )
    tentatives = models.PositiveIntegerField(default=0, verbose_name=_("tentatives"))
    message_erreur = models.TextField(blank=True, verbose_name=_("erreur"))
    creee_le = models.DateTimeField(auto_now_add=True, verbose_name=_("créé le"))

    class Meta:
        verbose_name = _("job d'impression")
        verbose_name_plural = _("jobs d'impression")
        ordering = ["-creee_le"]

    def __str__(self):
        return f"Ticket {self.capsule_id} — {self.get_statut_display()}"
