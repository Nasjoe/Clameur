"""La borne devient les réglages du lieu : un objet unique.

ÉCRITE À LA MAIN, ET NON GÉNÉRÉE. En mode non interactif, `makemigrations` ne
reconnaît pas un renommage : il produit un `DeleteModel` suivi d'un
`CreateModel`, ce qui effacerait la table et, avec elle, la clé étrangère de
toutes les capsules déjà publiées.
/ Hand-written: non-interactive makemigrations would emit a destructive
  delete-then-create instead of a rename.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    # LE RENOMMAGE DOIT VENIR APRES LES CLES ETRANGERES QUI VISENT L'ANCIEN
    # NOM. Sans ces deux dependances, Django est libre d'appliquer le rename
    # avant `capsules.0001`, qui declare une FK vers `bornes.Borne` : la
    # reconstruction de la base echoue alors sur « Related model
    # 'bornes.borne' cannot be resolved ».
    # / Without these, Django may rename before the FKs that target the old name.
    dependencies = [
        ("bornes", "0002_borne_par_defaut"),
        ("capsules", "0002_capsule_position_x_capsule_position_y"),
        ("impression", "0001_initial"),
    ]

    operations = [
        migrations.RenameModel(old_name="Borne", new_name="Reglages"),
        # Le slug servait à désigner UNE borne parmi plusieurs dans l'URL.
        # Avec un objet unique il ne désigne plus rien.
        # / The slug pointed at one borne among many; there is only one now.
        migrations.RemoveField(model_name="reglages", name="slug"),
        migrations.RemoveField(model_name="reglages", name="creee_le"),
        migrations.AlterField(
            model_name="reglages",
            name="nom",
            field=models.CharField(
                default="Clameur", max_length=200,
                help_text="Usage interne, et titre de l'affiche.",
                verbose_name="nom du lieu",
            ),
        ),
        migrations.AlterField(
            model_name="reglages",
            name="active",
            field=models.BooleanField(
                default=True, verbose_name="ouverte",
                help_text="Décochée, plus personne ne peut enregistrer.",
            ),
        ),
        migrations.AlterField(
            model_name="reglages",
            name="texte_accueil",
            field=models.TextField(
                blank=True,
                default=(
                    "Une idée, un souvenir, une colère. Deux minutes suffisent, "
                    "et tu repars avec un ticket à coller où tu veux."
                ),
                help_text="La phrase que lit le visiteur en arrivant sur la page.",
                verbose_name="texte d'accueil",
            ),
        ),
        migrations.AlterModelOptions(
            name="reglages",
            options={"verbose_name": "réglages", "verbose_name_plural": "réglages"},
        ),
    ]
