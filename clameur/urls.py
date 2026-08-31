from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path

from clameur.medias_dev import servir_un_media

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("capsules.urls")),
]

if settings.DEBUG:
    # PAS `static()` : sa vue ignore l'en-tete Range, et le lecteur audio des
    # navigateurs reste alors bloque. Voir clameur/medias_dev.py.
    # / Not `static()`: its view ignores Range and stalls the audio player.
    urlpatterns += [
        re_path(r"^medias/(?P<chemin>.*)$", servir_un_media, name="medias_dev"),
    ]
