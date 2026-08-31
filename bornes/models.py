"""Les reglages du lieu : une seule ligne, jamais deux.
/ The venue's settings: one row, never two.

POURQUOI UN OBJET UNIQUE PLUTOT QU'UNE TABLE.
Ce modele s'appelait « borne » et se voulait multiple : plusieurs lieux,
plusieurs imprimantes simultanees. C'etait une hypothese que personne n'avait
formulee, et elle se payait cher — une table vide rendait le site inutilisable,
sans que rien ne l'explique, et le mot n'evoquait rien a qui ouvrait l'admin.

Ce qu'il porte reellement, c'est de la CONFIGURATION : quelle imprimante, quel
papier, quel texte d'accueil, ouvert ou ferme. `django-solo` garantit qu'il n'y
en a qu'un exemplaire et le rend directement editable, sans liste ni bouton
« ajouter ».
/ It was modelled as many venues, a need nobody had expressed; what it really
  carries is configuration. django-solo keeps exactly one row.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from solo.models import SingletonModel


class Reglages(SingletonModel):
    nom = models.CharField(
        max_length=200, default="Clameur", verbose_name=_("nom du lieu"),
        help_text=_("Usage interne, et titre de l'affiche."),
    )

    # Le numero de serie n'est PAS un secret : il vit en base, contrairement
    # a SUNMI_APP_ID et SUNMI_APP_KEY qui restent dans l'environnement.
    # / The serial number is not a secret, unlike the app credentials.
    numero_serie_imprimante = models.CharField(
        max_length=100, blank=True,
        verbose_name=_("numéro de série de l'imprimante"),
        help_text=_("Le SN Sunmi de l'imprimante posée à côté de l'affiche."),
    )

    dots_par_ligne = models.PositiveIntegerField(
        default=576, verbose_name=_("points par ligne"),
        help_text=_("576 pour du papier 80 mm, 384 pour du 58 mm."),
    )

    active = models.BooleanField(
        default=True, verbose_name=_("ouverte"),
        help_text=_("Décochée, plus personne ne peut enregistrer."),
    )

    texte_accueil = models.TextField(
        blank=True,
        default=(
            "Une idée, un souvenir, une colère. Deux minutes suffisent, "
            "et tu repars avec un ticket à coller où tu veux."
        ),
        verbose_name=_("texte d'accueil"),
        help_text=_("La phrase que lit le visiteur en arrivant sur la page."),
    )

    # Garde-fou TECHNIQUE, pas editorial : le client arrete MediaRecorder a
    # cette duree, mais le serveur accepte ce qui lui arrive au-dela. Un
    # enregistrement ne doit jamais etre detruit par un depassement.
    # / Technical guard only: the client stops, the server still accepts.
    duree_max_secondes = models.PositiveIntegerField(
        default=600, verbose_name=_("durée maximale en secondes"),
        help_text=_("Garde-fou contre l'enregistrement oublié en poche."),
    )

    class Meta:
        verbose_name = _("réglages")
        verbose_name_plural = _("réglages")

    def __str__(self):
        return str(_("Réglages"))
