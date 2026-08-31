"""Projette les vecteurs des clameurs en deux dimensions.
/ Projects clameur vectors onto two dimensions.

POURQUOI LES POSITIONS SONT STOCKEES, ET NON CALCULEES A L'AFFICHAGE.
Une projection est GLOBALE : ajouter une clameur deplace toutes les autres. Si
on la recalculait a chaque visite, la constellation serait differente a chaque
fois — on ne pourrait plus revenir a une etoile reperee la veille, ni la
montrer a quelqu'un. Les etoiles doivent etre fixes entre deux recalculs.
/ A projection is global: recomputing it per visit would move every star.

POURQUOI UNE PCA ET PAS T-SNE.
t-SNE separe mieux, mais exige scikit-learn (une centaine de megaoctets dans
l'image) pour une commande lancee de loin en loin. La PCA tient en dix lignes
de numpy, deja installe. La commande MESURE la qualite de la separation a
chaque passage : le jour ou elle chute sur de vraies capsules, ce sera le
signal de passer a t-SNE.
/ PCA needs no extra dependency; the command measures quality so we know when
it stops being enough.
"""

import numpy as np
from django.core.management.base import BaseCommand

from capsules.models import Capsule, StatutCapsule

MARGE = 0.04


class Command(BaseCommand):
    help = "Calcule la position de chaque clameur dans la constellation."

    def add_arguments(self, parseur):
        parseur.add_argument(
            "--tout", action="store_true",
            help="Projette aussi les capsules retirées (par défaut : publiées seules).",
        )

    def handle(self, *args, **options):
        capsules = Capsule.objects.exclude(embedding=None)
        if not options["tout"]:
            capsules = capsules.filter(statut=StatutCapsule.PUBLIEE)
        capsules = list(capsules.only("uuid", "embedding"))

        if len(capsules) < 3:
            self.stdout.write(self.style.WARNING(
                f"{len(capsules)} clameur(s) avec vecteur : trop peu pour projeter. "
                "Lance d'abord l'enrichissement, ou `creer_des_clameurs`."
            ))
            return

        vecteurs = np.vstack([np.asarray(c.embedding, dtype=float) for c in capsules])
        positions = self._projeter(vecteurs)

        for capsule, (x, y) in zip(capsules, positions):
            capsule.position_x = float(x)
            capsule.position_y = float(y)
        Capsule.objects.bulk_update(capsules, ["position_x", "position_y"], batch_size=200)

        self.stdout.write(self.style.SUCCESS(
            f"{len(capsules)} clameurs projetées."
        ))
        self.stdout.write(f"  variance expliquée : {self._variance:.1%}")
        self.stdout.write(
            "  Une variance très basse et des étoiles en bouillie signifient que "
            "la PCA ne sépare plus : il sera temps de passer à t-SNE."
        )

    def _projeter(self, vecteurs):
        """PCA sur deux axes, puis mise a l'echelle dans [0, 1].
        / Two-axis PCA, then rescaled into [0, 1]."""
        centres = vecteurs - vecteurs.mean(axis=0)
        _u, valeurs, directions = np.linalg.svd(centres, full_matrices=False)
        self._variance = float((valeurs[:2] ** 2).sum() / (valeurs**2).sum())

        plan = centres @ directions[:2].T

        # Mise a l'echelle par axe : sans elle, un nuage tres allonge sur un
        # axe se tasserait en une ligne a l'ecran.
        # / Per-axis rescaling: otherwise an elongated cloud collapses to a line.
        minimum, maximum = plan.min(axis=0), plan.max(axis=0)
        etendue = np.where(maximum - minimum == 0, 1.0, maximum - minimum)
        return MARGE + (plan - minimum) / etendue * (1 - 2 * MARGE)
