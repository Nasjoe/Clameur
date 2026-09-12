"""Force un recalcul du ciel : positions, relief et regions.
/ Forces a sky recomputation: positions, relief and regions.

CETTE COMMANDE NE PORTE PLUS D'ALGORITHME. Le calcul vit dans `capsules.ciel`,
et c'est la que sont expliques les choix qui le gouvernent — pourquoi les
positions sont stockees, pourquoi t-SNE plutot que la PCA, pourquoi il part
d'une PCA, et pourquoi la variance expliquee ne dit rien. La tache Celery
`recalculer_le_ciel` et cette commande appellent exactement le meme code : deux
copies auraient fini par diverger.
/ No algorithm here: it lives in capsules.ciel, and so do its explanations.

A QUOI ELLE SERT ENCORE, PUISQUE LE CALCUL EST AUTOMATIQUE.
Rien ne se declenche tant qu'aucune clameur n'est deposee ni retiree : au
premier deploiement, ou apres une restauration de sauvegarde, le ciel serait
vide sans elle. Elle sert aussi a voir la mesure de fidelite, que la tache ne
fait qu'ecrire dans son journal.
/ Nothing fires until a clameur is posted: on a fresh deployment, only this
  command fills the sky.

ELLE NE REDEPLACE PAS LES ETOILES SANS RAISON. Comme la tache, elle ne relance
la projection que si une clameur publiee attend encore sa position ; sinon elle
se contente du relief et des regions. Les etoiles ne bougent donc pas parce
qu'on a lance la commande deux fois de suite.
/ Like the task, it only projects when a star is missing.
"""

import logging

import numpy as np
from django.core.management.base import BaseCommand

from capsules import ciel
from capsules.models import Capsule, Ciel, StatutCapsule
from capsules.tasks import recalculer_le_ciel

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Recalcule le ciel : positions des clameurs, relief et régions."

    def add_arguments(self, parseur):
        parseur.add_argument(
            "--rattraper", action="store_true",
            help=(
                "Enfile aussi le calcul des vecteurs manquants. "
                "Un appel payant par clameur : sans ce drapeau, on se contente "
                "de les compter."
            ),
        )

    def handle(self, *args, **options):
        self._les_vecteurs_manquants(options["rattraper"])
        resultat = recalculer_le_ciel()

        projetees = list(
            Capsule.objects.filter(statut=StatutCapsule.PUBLIEE)
            .exclude(position_x=None)
            .exclude(embedding=None)
            .only("uuid", "embedding", "position_x", "position_y")
        )

        if resultat == "trop peu" or len(projetees) < 3:
            # ON COMPTE CE QUI EXISTE, ET NON CE QUI EST PROJETE. Le message
            # annoncait « 0 clameur exploitable » meme avec deux clameurs
            # vectorisees, parce qu'il lisait les positions — que le calcul
            # venait justement d'effacer. Il envoyait alors relancer un
            # enrichissement deja fait.
            # / Count what exists, not what got projected: the old message read
            #   positions the computation had just cleared.
            publiees = Capsule.objects.filter(statut=StatutCapsule.PUBLIEE)
            nombre = publiees.count()
            avec_vecteur = publiees.exclude(embedding=None).count()

            self.stdout.write(self.style.WARNING(
                f"Trop peu pour projeter : {avec_vecteur} clameur(s) avec vecteur "
                f"sur {nombre} publiée(s), et il en faut au moins trois."
            ))
            if avec_vecteur:
                self.stdout.write(
                    "  Elles sont posées côte à côte, sans relief : le ciel ne "
                    "prend son sens qu'à partir de trois clameurs."
                )
            if not nombre:
                self.stdout.write("  Aucune clameur publiée. Essaie `make fixture`.")
            elif avec_vecteur < nombre:
                self.stdout.write(
                    "  Les autres attendent leur vecteur : `make vecteurs` "
                    "(un appel payant par clameur)."
                )
            return

        objet = Ciel.get_solo()
        self.stdout.write(self.style.SUCCESS(
            f"{len(projetees)} clameurs projetées, "
            f"{len(objet.regions)} région(s) nommée(s)."
        ))

        # LA FIDELITE EST RECALCULEE ICI, ET NON LUE QUELQUE PART : c'est la
        # seule mesure qui dise si le ciel tient sa promesse — deux etoiles
        # cote a cote parlent-elles vraiment de la meme chose ? La tache, elle,
        # n'a personne a qui l'afficher.
        # / Recomputed here: it is the only measurement that speaks to the
        #   sky's own promise, and the task has nobody to show it to.
        vecteurs = np.vstack([np.asarray(c.embedding, dtype=float) for c in projetees])
        positions = np.array([[c.position_x, c.position_y] for c in projetees])
        fidelite = ciel.fidelite(vecteurs, positions)

        proches = ciel.combien_de_proches(len(projetees))
        self.stdout.write(
            f"  {fidelite:.0%} des étoiles ont pour plus proche voisine "
            f"l'une de leurs {proches} clameurs les plus proches par le sens."
            if proches > 1 else
            f"  {fidelite:.0%} des étoiles ont pour plus proche voisine "
            "leur clameur la plus proche par le sens."
        )
        if fidelite < 0.5:
            self.stdout.write(self.style.WARNING(
                "  Sous une étoile sur deux, le ciel ne dit plus grand-chose : "
                "les clameurs sont peut-être devenues trop nombreuses pour "
                "deux dimensions."
            ))

    def _les_vecteurs_manquants(self, rattraper: bool) -> None:
        """Compte les clameurs sans vecteur, et les enfile si on le demande.

        UNE CLAMEUR SANS VECTEUR EST DANS LA LISTE ET ABSENTE DU CIEL. C'est le
        cas de toutes celles publiees pendant que la tache `embarquer` n'etait
        pas enfilee : elles ne recevront d'etoile que si on les rattrape.

        SANS TRANSCRIPTION, PAS DE VECTEUR POSSIBLE : `embarquer` rendrait
        « rien a embarquer ». On les compte a part, pour que l'operateur sache
        pourquoi celles-la resteront sans etoile.
        / A clameur with no vector sits in the list but not in the sky; one with
          no transcription cannot be helped at all.
        """
        sans_vecteur = Capsule.objects.filter(
            statut=StatutCapsule.PUBLIEE, embedding=None
        )
        muettes = sans_vecteur.filter(transcription_texte="").count()
        a_calculer = list(
            sans_vecteur.exclude(transcription_texte="").values_list("uuid", flat=True)
        )

        if muettes:
            self.stdout.write(
                f"  {muettes} clameur(s) sans transcription : aucun vecteur "
                "possible, donc aucune étoile."
            )
        if not a_calculer:
            return

        phrase = (
            "1 clameur attend son vecteur"
            if len(a_calculer) == 1
            else f"{len(a_calculer)} clameurs attendent leur vecteur"
        )
        if not rattraper:
            self.stdout.write(self.style.WARNING(
                f"  {phrase}. Relance avec --rattraper pour l'enfiler "
                "(un appel payant par clameur)."
            ))
            return

        from capsules.tasks import embarquer

        enfiles = 0
        for uuid in a_calculer:
            # ON VA AU BOUT DE LA LISTE. Un courtier qui tombe a la troisieme
            # clameur ne doit pas laisser les cinquante suivantes sans vecteur,
            # et l'operateur doit pouvoir relancer sans rien casser : enfiler
            # deux fois le meme calcul ne fait que le refaire.
            # / A broker failing on the third must not abandon the next fifty.
            try:
                embarquer.delay(str(uuid))
                enfiles += 1
            except Exception:
                logger.exception("enqueue du vecteur de %s impossible", uuid)

        self.stdout.write(self.style.SUCCESS(
            f"  {enfiles} vecteur(s) en file. Le ciel se recalculera tout seul "
            "quand ils seront arrivés."
        ))
