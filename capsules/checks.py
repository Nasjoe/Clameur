"""Controles executes par `manage.py check`.
/ Checks run by `manage.py check`."""

from django.conf import settings
from django.core.checks import Error, Warning, register


@register(deploy=True)
def les_mentions_legales_sont_renseignees(app_configs, **kwargs):
    """Le projet heberge de la parole publique : il doit dire qui l'edite.

    Sans editeur ni adresse de contact, la page des mentions legales ne permet
    a personne de signaler une clameur — alors que c'est le moyen technique de
    l'obligation de retrait prompt.
    / Without these, nobody can report a clameur, though that is the technical
      means of the prompt-takedown obligation.
    """
    manquants = [
        nom for nom in ("EDITEUR", "CONTACT") if not getattr(settings, nom, "")
    ]
    if not manquants:
        return []
    return [
        Error(
            f"{' et '.join(manquants)} non renseigné(s) dans l'environnement.",
            hint="Le site ne peut pas recevoir de signalement (LCEN). "
                 "Renseigne EDITEUR et CONTACT dans le .env.",
            id="clameur.E001",
        )
    ]


@register(deploy=True)
def l_url_publique_est_en_https(app_configs, **kwargs):
    """Elle est imprimee dans le QR de chaque ticket.

    Un ticket porte une URL pour des semaines. En http, les telephones
    refuseront le micro sur la page d'enregistrement, et l'adresse imprimee
    sera fausse.
    / A ticket carries its URL for weeks; http would refuse the microphone.
    """
    if settings.URL_PUBLIQUE.startswith("https://"):
        return []
    return [
        Warning(
            f"URL_PUBLIQUE vaut {settings.URL_PUBLIQUE!r}, sans https.",
            hint="Elle est encodée dans le QR de chaque ticket imprimé, et "
                 "les navigateurs refusent le micro hors HTTPS.",
            id="clameur.W001",
        )
    ]
