"""Projette les vecteurs des clameurs en deux dimensions.
/ Projects clameur vectors onto two dimensions.

POURQUOI LES POSITIONS SONT STOCKEES, ET NON CALCULEES A L'AFFICHAGE.
Une projection est GLOBALE : ajouter une clameur deplace toutes les autres. Si
on la recalculait a chaque visite, la constellation serait differente a chaque
fois — on ne pourrait plus revenir a une etoile reperee la veille, ni la
montrer a quelqu'un. Les etoiles doivent etre fixes entre deux recalculs.
/ A projection is global: recomputing it per visit would move every star.

POURQUOI T-SNE, ET POURQUOI ECRIT ICI.
La PCA a tenu tant que les vecteurs venaient des fixtures — huit gaussiennes
bien separees, un cas facile. Sur de VRAIS vecteurs `mistral-embed`, mesure le
2026-08-31 sur soixante clameurs variees, elle place « dans le bon quartier »
sans placer le bon voisin : la clameur affichee a cote n'etait la plus proche
par le sens que dans un tiers des cas, et son rang median dans le vrai
classement etait de huit sur cinquante-neuf. Avec t-SNE, rang median zero, et
neuf fois sur dix le vrai voisin est a l'ecran.
scikit-learn apporterait cela en une ligne, et une centaine de megaoctets dans
l'image pour une commande lancee de loin en loin. Les quarante lignes ci-
dessous font le meme travail avec le numpy deja installe.
/ PCA held only while the vectors came from well-separated fixtures; on real
  embeddings it puts a clameur in the right neighbourhood but next to the wrong
  neighbour. t-SNE fixes that, and forty lines of numpy avoid a 100 MB
  dependency for a command run once in a while.

POURQUOI L'INITIALISATION PAR LA PCA.
Un t-SNE parti d'un nuage aleatoire donne un ciel different a chaque passage :
l'orientation change, et l'on ne retrouve plus une etoile reperee la veille.
Parti de la PCA, il est ENTIEREMENT DETERMINISTE — memes vecteurs, memes
positions — et il garde l'orientation d'ensemble d'une projection a l'autre.
/ A random start would reorient the sky at every run; the PCA start makes the
  result deterministic and keeps the overall orientation.

POURQUOI LA VARIANCE EXPLIQUEE N'EST PLUS AFFICHEE.
Elle passait pour le signal d'alerte. Elle ment : mesuree a 18,5 % sur les
fixtures — ou la separation est parfaite — et a 9,7 % sur de vraies clameurs.
Elle MONTE quand le probleme devient facile pour de mauvaises raisons. La
commande affiche desormais ce qui compte : la part des etoiles dont la plus
proche voisine a l'ecran fait vraiment partie de ses plus proches par le sens.
/ Explained variance was the alert signal, and it lies: 18.5 % on the easy
  fixtures against 9.7 % on real clameurs. We now show neighbourhood quality.

LA COMMANDE EST EN O(n²). Quelques centaines de clameurs passent en secondes ;
au-dela de quelques milliers, il faudra une autre methode.
/ O(n²): fine for hundreds, not for thousands.
"""

import numpy as np
from django.core.management.base import BaseCommand

from capsules.models import Capsule, StatutCapsule

MARGE = 0.04

# Combien de voisines chaque clameur « connait ». Trop peu, le ciel se casse en
# miettes ; trop, les groupes fondent les uns dans les autres.
# / How many neighbours each clameur knows: too few shatters the sky, too many
#   melts the groups together.
VOISINES = 30
ITERATIONS = 800


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

        fidelite = self._fidelite(vecteurs, positions)
        self.stdout.write(self.style.SUCCESS(
            f"{len(capsules)} clameurs projetées."
        ))
        self.stdout.write(
            f"  {fidelite:.0%} des étoiles ont pour plus proche voisine "
            "l'une de leurs cinq clameurs les plus proches par le sens."
        )
        if fidelite < 0.5:
            self.stdout.write(self.style.WARNING(
                "  Sous une étoile sur deux, le ciel ne dit plus grand-chose : "
                "les clameurs sont peut-être devenues trop nombreuses pour "
                "deux dimensions."
            ))

    def _projeter(self, vecteurs):
        """t-SNE initialise par une PCA, puis mise a l'echelle dans [0, 1].
        / PCA-seeded t-SNE, then rescaled into [0, 1]."""
        depart = self._pca(vecteurs)
        plan = self._tsne(vecteurs, depart)

        # Mise a l'echelle par axe : sans elle, un nuage tres allonge sur un
        # axe se tasserait en une ligne a l'ecran.
        # / Per-axis rescaling: otherwise an elongated cloud collapses to a line.
        minimum, maximum = plan.min(axis=0), plan.max(axis=0)
        etendue = np.where(maximum - minimum == 0, 1.0, maximum - minimum)
        return MARGE + (plan - minimum) / etendue * (1 - 2 * MARGE)

    def _pca(self, vecteurs):
        """Les deux axes de plus grande variance. / The two widest axes."""
        centres = vecteurs - vecteurs.mean(axis=0)
        _u, _valeurs, directions = np.linalg.svd(centres, full_matrices=False)
        return centres @ directions[:2].T

    def _tsne(self, vecteurs, depart):
        """t-SNE, en numpy. Rapproche a l'ecran ce qui est proche par le sens.

        Le principe tient en une phrase : on donne a chaque clameur une
        distribution de voisinage en 1024 dimensions, une autre a l'ecran, et
        l'on deplace les points jusqu'a ce que les deux se ressemblent.
        / Match the neighbourhood distributions of both spaces.
        """
        nombre = len(vecteurs)
        unitaires = vecteurs / np.linalg.norm(vecteurs, axis=1, keepdims=True)
        carres = ((unitaires[:, None, :] - unitaires[None, :, :]) ** 2).sum(-1)

        voisines = max(2.0, min(float(VOISINES), (nombre - 1) / 3))
        affinites = np.zeros_like(carres)
        for indice in range(nombre):
            # Chaque clameur a son propre rayon de voisinage, trouve par
            # dichotomie : dans un amas dense il est petit, dans un coin vide
            # il est large. C'est ce qui permet aux clameurs isolees d'exister
            # quand meme. / Each point gets its own radius, so lonely clameurs
            # still find a place.
            bas, haut, cible = 1e-10, 1e10, np.log(voisines)
            for _ in range(60):
                largeur = (bas + haut) / 2
                proximites = np.exp(-carres[indice] * largeur)
                proximites[indice] = 0
                somme = proximites.sum() or 1e-12
                entropie = np.log(somme) + largeur * (carres[indice] * proximites).sum() / somme
                if entropie > cible:
                    bas = largeur
                else:
                    haut = largeur
            affinites[indice] = proximites / somme

        affinites = np.maximum((affinites + affinites.T) / (2 * nombre), 1e-12)

        # L'EXAGERATION PRECOCE : on gonfle les affinites au debut pour que les
        # groupes se detachent avant de se ranger. Sans elle, tout se tasse au
        # centre et rien ne se separe. / Early exaggeration: groups must pull
        # apart before they settle.
        affinites *= 4

        positions = depart / (depart.std(axis=0).mean() or 1.0) * 1e-2
        vitesse = np.zeros_like(positions)
        for iteration in range(ITERATIONS):
            if iteration == 100:
                affinites /= 4
            ecarts = positions[:, None, :] - positions[None, :, :]
            inverses = 1 / (1 + (ecarts**2).sum(-1))
            np.fill_diagonal(inverses, 0)
            projetees = np.maximum(inverses / inverses.sum(), 1e-12)
            gradient = 4 * (
                (((affinites - projetees) * inverses)[:, :, None] * ecarts).sum(1)
            )
            vitesse = (0.5 if iteration < 250 else 0.8) * vitesse - 200 * gradient
            positions = positions + vitesse
            positions -= positions.mean(axis=0)
        return positions

    def _fidelite(self, vecteurs, positions) -> float:
        """La part des clameurs dont la voisine d'ecran est vraiment une proche.

        C'EST LA SEULE MESURE QUI DISE QUELQUE CHOSE au sujet du ciel : il
        promet que deux etoiles cote a cote parlent de la meme chose, et c'est
        exactement ce qu'on verifie ici.
        / The only measurement that speaks to the sky's own promise.
        """
        unitaires = vecteurs / np.linalg.norm(vecteurs, axis=1, keepdims=True)
        cosinus = unitaires @ unitaires.T
        np.fill_diagonal(cosinus, -np.inf)
        proches = np.argsort(-cosinus, axis=1)[:, :5]

        ecrans = ((positions[:, None, :] - positions[None, :, :]) ** 2).sum(-1)
        np.fill_diagonal(ecrans, np.inf)
        voisine = ecrans.argmin(axis=1)
        return float(np.mean([voisine[i] in proches[i] for i in range(len(vecteurs))]))
