from django.urls import path

from capsules import views

app_name = "capsules"

urlpatterns = [
    path("b/<slug:slug>", views.accueil_borne, name="accueil_borne"),
    path("b/<slug:slug>/capsule", views.creer_capsule, name="creer_capsule"),
    path("b/<slug:slug>/affiche", views.affiche_borne, name="affiche_borne"),
    path("c/<uuid:uuid>", views.lire_capsule, name="lire_capsule"),
    path("c/<uuid:uuid>/publier", views.publier_capsule, name="publier_capsule"),
    path("c/<uuid:uuid>/ecoute", views.compter_une_ecoute, name="compter_une_ecoute"),
    path("mentions-legales", views.mentions_legales, name="mentions_legales"),
]
