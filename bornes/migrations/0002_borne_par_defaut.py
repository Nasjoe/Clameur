"""Crée une borne par défaut si la base n'en a aucune.

SANS ELLE, UN SITE FRAÎCHEMENT DÉPLOYÉ EST INUTILISABLE : la page d'accueil
n'affiche le bouton « Enregistrer une nouvelle clameur » que s'il existe une
borne ouverte, et sans ce bouton personne ne peut déposer la première clameur.
Le site restait donc vide, définitivement, sans que rien ne l'explique.
/ Without this a freshly deployed site is unusable: no borne means no button,
  and no button means nobody can post the first clameur.
"""

from django.db import migrations

REGLAGES = {
    "nom": "Clameur",
    "texte_accueil": (
        "Une idée, un souvenir, une colère. Deux minutes suffisent, "
        "et tu repars avec un ticket à coller où tu veux."
    ),
}


def creer_la_borne_par_defaut(apps, schema_editor):
    Borne = apps.get_model("bornes", "Borne")
    if Borne.objects.exists():
        return
    Borne.objects.create(slug="clameur", **REGLAGES)


def ne_rien_defaire(apps, schema_editor):
    """On ne supprime rien en arrière : la borne a pu recevoir des réglages,
    et des clameurs y sont peut-être attachées.
    / Nothing is undone: the borne may hold settings and capsules."""


class Migration(migrations.Migration):
    dependencies = [("bornes", "0001_initial")]
    operations = [migrations.RunPython(creer_la_borne_par_defaut, ne_rien_defaire)]
