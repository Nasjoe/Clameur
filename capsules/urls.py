from django.urls import path

from capsules import views

app_name = "capsules"

urlpatterns = [
    # La constellation EST la page d'accueil : c'est elle qu'on montre a
    # quelqu'un a qui l'on parle du projet, et elle donne acces au reste.
    # / The constellation is the home page.
    path("", views.constellation, name="constellation"),
    # L'adresse courte de la borne ouverte : celle qu'on dit a voix haute et
    # qu'on encode dans le QR. / The speakable address of the open borne.
    path("nouvelle", views.accueil_borne_par_defaut, name="nouvelle"),
    path("b/<slug:slug>", views.accueil_borne, name="accueil_borne"),
    path("b/<slug:slug>/capsule", views.creer_capsule, name="creer_capsule"),
    path("b/<slug:slug>/affiche", views.affiche_borne, name="affiche_borne"),
    path("c/<uuid:uuid>", views.lire_capsule, name="lire_capsule"),
    path("c/<uuid:uuid>/publier", views.publier_capsule, name="publier_capsule"),
    path("c/<uuid:uuid>/ecoute", views.compter_une_ecoute, name="compter_une_ecoute"),
    path("mentions-legales", views.mentions_legales, name="mentions_legales"),
]
