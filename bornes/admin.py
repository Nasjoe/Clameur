from django.contrib import admin

from bornes.models import Borne


@admin.register(Borne)
class BorneAdmin(admin.ModelAdmin):
    list_display = ("nom", "slug", "active", "numero_serie_imprimante", "dots_par_ligne")
    list_filter = ("active",)
    search_fields = ("nom", "slug", "numero_serie_imprimante")
    prepopulated_fields = {"slug": ("nom",)}
