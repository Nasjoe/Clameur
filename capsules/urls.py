from django.urls import path

from capsules import views

app_name = "capsules"

urlpatterns = [
    # LA LISTE EST LA PAGE D'ACCUEIL. C'etait la constellation jusqu'au
    # 2026-09-01 ; elle est en sommeil, et sa vue n'est plus routee.
    # / The list is the home page; the constellation view is dormant.
    path("", views.liste, name="liste"),

    # L'adresse ou l'on depose une clameur. Une seule, puisqu'il n'y a qu'un
    # lieu : elle tient dans une phrase et s'encode dans le QR de l'affiche.
    # / One address, said aloud and printed in the poster's QR code.
    path("nouvelle", views.accueil_enregistrement, name="nouvelle"),
    path("nouvelle/capsule", views.creer_capsule, name="creer_capsule"),
    path("affiche", views.affiche, name="affiche"),

    path("c/<uuid:uuid>", views.lire_capsule, name="lire_capsule"),
    path("c/<uuid:uuid>/publier", views.publier_capsule, name="publier_capsule"),
    path("c/<uuid:uuid>/ecoute", views.compter_une_ecoute, name="compter_une_ecoute"),
    path("c/<uuid:uuid>/retirer", views.retirer_capsule, name="retirer_capsule"),
    path("c/<uuid:uuid>/reimprimer", views.reimprimer_capsule, name="reimprimer_capsule"),
    path("mentions-legales", views.mentions_legales, name="mentions_legales"),
    # Deux adresses que personne ne tape et que tout le monde demande.
    # / Two addresses nobody types and everything requests.
    path("robots.txt", views.robots, name="robots"),
    path("favicon.ico", views.icone_du_site, name="icone_du_site"),
]
