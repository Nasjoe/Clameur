"""Imprime un ticket de test sur une vraie imprimante Sunmi.

PREMIERE CHOSE A FAIRE AVANT UN EVENEMENT. L'imprimante est le seul maillon de
la chaine que le projet ne controle pas : credentials, appairage, largeur de
papier, tramage. Tout le reste est teste automatiquement ; cela, non.
/ Run this first: the printer is the one link the project does not control.
"""

import os
import time

from django.core.management.base import BaseCommand, CommandError

from bornes.models import Borne
from impression.escpos_builder import construire_le_ticket
from impression.sunmi_cloud import SunmiCloudBackend


class TicketDeTest:
    """Une capsule factice, juste assez pour construire un ticket.
    / A fake capsule, just enough to build a ticket."""

    uuid = "00000000-0000-0000-0000-000000000000"
    pseudo = "ticket de test"
    duree_secondes = 42
    photo = None

    class _SansTags:
        def all(self):
            return []

    tags_de_capsule = _SansTags()


class Command(BaseCommand):
    help = "Imprime un ticket de test sur l'imprimante d'une borne."

    def add_arguments(self, parseur):
        parseur.add_argument("slug", help="Le slug de la borne à tester.")
        parseur.add_argument(
            "--url", default="https://exemple.test/c/ticket-de-test",
            help="L'URL encodée dans le QR code du ticket de test.",
        )

    def handle(self, *args, **options):
        try:
            borne = Borne.objects.get(slug=options["slug"])
        except Borne.DoesNotExist:
            connues = ", ".join(Borne.objects.values_list("slug", flat=True)) or "aucune"
            raise CommandError(f"Borne inconnue. Bornes existantes : {connues}")

        if not os.environ.get("SUNMI_APP_ID") or not os.environ.get("SUNMI_APP_KEY"):
            raise CommandError(
                "SUNMI_APP_ID et SUNMI_APP_KEY doivent être dans l'environnement. "
                "Sans eux, le projet bascule sur le backend mock et rien ne s'imprime."
            )

        backend = SunmiCloudBackend(borne)

        possible, message = backend.can_print()
        if not possible:
            raise CommandError(message)
        self.stdout.write(self.style.SUCCESS("Configuration : OK"))

        en_ligne, message = backend.est_en_ligne()
        self.stdout.write(
            self.style.SUCCESS("Imprimante  : en ligne")
            if en_ligne
            else self.style.WARNING(f"Imprimante  : {message} — on tente quand même")
        )

        octets = construire_le_ticket(
            TicketDeTest(), borne.dots_par_ligne, options["url"]
        )
        self.stdout.write(
            f"Ticket      : {len(octets)} octets ESC/POS, "
            f"{borne.dots_par_ligne} points par ligne "
            f"({'80 mm' if borne.dots_par_ligne >= 576 else '58 mm'})"
        )

        pilote = backend._pilote()
        pilote.appendRawData(octets)
        numero = f"{borne.numero_serie_imprimante}_test_{int(time.time())}"
        pilote.pushContent(
            trade_no=numero, sn=borne.numero_serie_imprimante, count=1,
            media_text="Clameur — test",
        )

        self.stdout.write(self.style.SUCCESS(f"Envoyé      : {numero}"))
        self.stdout.write("")
        self.stdout.write("À VÉRIFIER SUR LE PAPIER :")
        self.stdout.write("  1. Le texte n'est pas coupé sur les bords")
        self.stdout.write("     → sinon, corrige dots_par_ligne sur la borne (576 / 384)")
        self.stdout.write("  2. Le QR code se scanne avec un téléphone")
        self.stdout.write("  3. Le papier est bien coupé à la fin")
