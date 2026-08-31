"""La Borne relie une affiche, une imprimante Sunmi et un evenement.
/ A Borne links a poster, a Sunmi printer and an event.

C'EST L'OBJET PIVOT DU PROJET. Le QR de l'affiche encode /b/<slug> : ce slug
est le seul moyen, pour le telephone du visiteur, de designer l'imprimante qui
se trouve a cote de lui. Sans cet objet, rien ne relie la page web a la machine
physique.
/ THE PIVOT OBJECT: the slug is how a visitor's phone names the printer next to them.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Borne(models.Model):
    slug = models.SlugField(
        unique=True,
        verbose_name=_("identifiant d'URL"),
        help_text=_("Ce que le QR code de l'affiche encode : /b/<slug>"),
    )
    nom = models.CharField(max_length=200, verbose_name=_("nom"))

    # Le numero de serie n'est PAS un secret : il vit en base, contrairement
    # a SUNMI_APP_ID et SUNMI_APP_KEY qui restent dans l'environnement.
    # / The serial number is not a secret, unlike the app credentials.
    numero_serie_imprimante = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("numéro de série de l'imprimante"),
        help_text=_("Le SN Sunmi de l'imprimante posée à côté de l'affiche."),
    )

    dots_par_ligne = models.PositiveIntegerField(
        default=576,
        verbose_name=_("points par ligne"),
        help_text=_("576 pour du papier 80 mm, 384 pour du 58 mm."),
    )

    active = models.BooleanField(
        default=True,
        verbose_name=_("active"),
        help_text=_("Décochée, la borne n'accepte plus d'enregistrement."),
    )

    texte_accueil = models.TextField(
        blank=True,
        verbose_name=_("texte d'accueil"),
        help_text=_("La phrase que lit le visiteur en arrivant sur la page."),
    )

    # Garde-fou TECHNIQUE, pas editorial : le client arrete MediaRecorder a
    # cette duree, mais le serveur accepte ce qui lui arrive au-dela. Un
    # enregistrement ne doit jamais etre detruit par un depassement.
    # / Technical guard only: the client stops, the server still accepts.
    duree_max_secondes = models.PositiveIntegerField(
        default=600,
        verbose_name=_("durée maximale en secondes"),
        help_text=_("Garde-fou contre l'enregistrement oublié en poche."),
    )

    creee_le = models.DateTimeField(auto_now_add=True, verbose_name=_("créée le"))

    class Meta:
        verbose_name = _("borne")
        verbose_name_plural = _("bornes")
        ordering = ["nom"]

    def __str__(self):
        return self.nom
