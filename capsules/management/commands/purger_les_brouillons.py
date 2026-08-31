"""Supprime les brouillons abandonnes et leurs fichiers.

Enregistrer sans publier laisse une Capsule et son audio pour toujours.
L'operateur lance cette commande en fin d'evenement — pas de tache periodique
pour un menage qui se fait une fois par evenement.
/ Recording without publishing leaves files behind. Run at the end of an event.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from capsules.models import Capsule, StatutCapsule

HEURES_DE_GRACE = 24


class Command(BaseCommand):
    help = "Supprime les capsules restées en brouillon depuis plus de 24 heures."

    def add_arguments(self, parseur):
        parseur.add_argument(
            "--heures", type=int, default=HEURES_DE_GRACE,
            help="Âge minimal des brouillons à supprimer.",
        )
        parseur.add_argument(
            "--pour-de-vrai", action="store_true",
            help="Sans ce drapeau, la commande se contente d'annoncer.",
        )

    def handle(self, *args, **options):
        limite = timezone.now() - timezone.timedelta(hours=options["heures"])
        brouillons = Capsule.objects.filter(
            statut=StatutCapsule.BROUILLON, creee_le__lt=limite
        )
        nombre = brouillons.count()

        if not options["pour_de_vrai"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{nombre} brouillon(s) seraient supprimés. "
                    "Relancez avec --pour-de-vrai."
                )
            )
            return

        for capsule in brouillons:
            # Les fichiers d'abord : une ligne supprimee laisserait l'audio
            # orphelin sur le disque. / Files first, or the audio is orphaned.
            for champ in (capsule.audio_original, capsule.audio_diffusion, capsule.photo):
                if champ:
                    champ.delete(save=False)
            capsule.delete()

        self.stdout.write(self.style.SUCCESS(f"{nombre} brouillon(s) supprimés."))
