"""Relance et diagnostic des tickets. / Ticket retry and diagnosis."""

from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from impression.models import JobImpression, StatutJob


@admin.register(JobImpression)
class JobImpressionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "statut", "tentatives", "creee_le")
    list_filter = ("statut",)
    readonly_fields = ("trade_no", "creee_le", "tentatives")
    actions = ["relancer", "interroger_sunmi"]

    @admin.action(description=_("Relancer l'impression"))
    def relancer(self, request, queryset):
        from impression.tasks import envoyer_le_ticket

        for job in queryset:
            job.statut = StatutJob.EN_ATTENTE
            job.save(update_fields=["statut"])
            try:
                envoyer_le_ticket.delay(job.pk)
            except Exception:
                self.message_user(
                    request, _("Celery injoignable : ticket %s non relancé.") % job.pk,
                    messages.ERROR,
                )
        self.message_user(request, _("Relance demandée."))

    @admin.action(description=_("Interroger Sunmi (printStatus)"))
    def interroger_sunmi(self, request, queryset):
        """Le mode push n'a pas de callback : c'est ici qu'on leve un doute.
        / Push mode has no callback: this is where a doubt gets settled."""
        from impression.tasks import choisir_le_backend

        for job in queryset.exclude(trade_no=""):
            backend = choisir_le_backend(job.reglages)
            if not hasattr(backend, "_pilote"):
                self.message_user(request, _("Backend mock : rien à interroger."))
                continue
            try:
                reponse = backend._pilote().printStatus(job.trade_no)
                self.message_user(request, f"{job.trade_no} : {reponse}")
            except Exception as erreur:
                self.message_user(request, f"{job.trade_no} : {erreur}", messages.ERROR)
