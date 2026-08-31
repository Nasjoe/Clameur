"""La console operateur. En v1, c'est l'admin Django : l'operateur est present
sur place, authentifie, et l'admin fournit deja listes, filtres et actions.
/ The operator console. In v1 it is the Django admin."""

from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from capsules.models import Capsule, StatutCapsule, Tag, TagDeCapsule


class TagDeCapsuleInline(admin.TabularInline):
    model = TagDeCapsule
    extra = 0
    autocomplete_fields = ["tag"]


@admin.register(Capsule)
class CapsuleAdmin(admin.ModelAdmin):
    list_display = ("__str__", "borne", "statut", "duree_secondes", "nombre_ecoutes", "enrichie_le")
    list_filter = ("statut", "borne", "langue_detectee")
    search_fields = ("pseudo", "transcription_texte")
    readonly_fields = ("uuid", "creee_le", "publiee_le", "enrichie_le", "nombre_ecoutes", "embedding")
    inlines = [TagDeCapsuleInline]
    actions = ["retirer", "republier", "rejouer_l_enrichissement"]

    @admin.action(description=_("Retirer (kill switch)"))
    def retirer(self, request, queryset):
        # Le moyen technique de l'obligation de retrait prompt (LCEN).
        # / The technical means of the prompt-takedown obligation.
        nombre = queryset.update(statut=StatutCapsule.RETIREE)
        self.message_user(
            request,
            ngettext("%d clameur retirée.", "%d clameurs retirées.", nombre) % nombre,
            messages.WARNING,
        )

    @admin.action(description=_("Republier"))
    def republier(self, request, queryset):
        # SEULEMENT CE QUI A ETE RETIRE. Publier un brouillon par ce chemin le
        # rendrait accessible sans etre jamais passe par `publier()` : pas
        # d'audio normalise — donc muet sur iPhone —, pas de ticket, pas
        # d'enrichissement.
        # / Only withdrawn capsules: a draft published this way never went
        #   through publier() and would be silent on iOS.
        nombre = queryset.filter(statut=StatutCapsule.RETIREE).update(
            statut=StatutCapsule.PUBLIEE
        )
        self.message_user(request, _("%d clameur(s) republiée(s).") % nombre)

    @admin.action(description=_("Rejouer l'enrichissement"))
    def rejouer_l_enrichissement(self, request, queryset):
        from capsules.tasks import transcrire

        lancees, impossibles = 0, 0
        for capsule in queryset:
            try:
                transcrire.delay(str(capsule.uuid))
                lancees += 1
            except Exception:
                impossibles += 1
        if lancees:
            self.message_user(request, _("%d enrichissement(s) relancé(s).") % lancees)
        if impossibles:
            self.message_user(
                request,
                _("%d relance(s) impossible(s) : Celery est-il joignable ?") % impossibles,
                messages.ERROR,
            )


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    search_fields = ["nom"]
    list_display = ("nom",)
