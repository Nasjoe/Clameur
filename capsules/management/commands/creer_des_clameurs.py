"""Fabrique un corpus de démonstration : des clameurs écoutables, taguées,
illustrées, et sémantiquement groupées.
/ Builds a demo corpus: audible, tagged, illustrated, semantically clustered.

POURQUOI LES VECTEURS NE SONT PAS ALEATOIRES.
Ces fixtures servent aussi à préparer la constellation (sous-projet 2). Des
embeddings tirés au hasard donneraient un nuage uniforme, sans structure :
impossible de savoir si une projection UMAP fonctionne ou non. Ici chaque
thème a un centre dans l'espace 1024D, et ses clameurs se dispersent autour.
Une projection correcte doit donc faire apparaître des amas nets.
/ Random vectors would give a shapeless cloud; clustered ones let you tell
whether a projection actually works.
"""

import io
import math
import random
import subprocess
import tempfile
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFilter

from bornes.models import Borne
from capsules.models import Capsule, StatutCapsule, Tag, TagDeCapsule

# Huit familles de sujets. Chacune porte ses tags, ses tournures, sa teinte et
# sa note — de quoi rendre le corpus lisible à l'œil comme à l'oreille.
# / Eight subject families, each with its tags, phrasings, hue and note.
THEMES = [
    {
        "nom": "mémoire",
        "tags": ["souvenir", "enfance", "grand-mère", "photo", "odeur"],
        "teinte": 35,
        "note": 196,
        "phrases": [
            "Ma grand-mère faisait ce gâteau le dimanche, je n'ai jamais retrouvé la recette.",
            "On s'est rencontrés ici même, il pleuvait, tu avais un parapluie jaune.",
            "Je me souviens du bruit de la grille quand mon père rentrait.",
            "Cette odeur de craie, c'était l'école, je devais avoir sept ans.",
            "Elle chantait faux et personne n'osait le lui dire.",
        ],
    },
    {
        "nom": "colère",
        "tags": ["injustice", "loyer", "patron", "colère", "assez"],
        "teinte": 12,
        "note": 110,
        "phrases": [
            "Trois ans qu'on demande un ascenseur dans cet immeuble. Trois ans.",
            "Le loyer a encore augmenté et la chaudière ne marche toujours pas.",
            "On nous parle de mérite, mais on ne parle jamais des héritages.",
            "J'en ai assez qu'on décide pour nous sans jamais nous demander.",
            "Ils ont fermé la dernière école du quartier un mardi, sans prévenir.",
        ],
    },
    {
        "nom": "quartier",
        "tags": ["quartier", "voisins", "marché", "rue", "boulangerie"],
        "teinte": 62,
        "note": 262,
        "phrases": [
            "Le marché du mercredi, c'est le seul moment où tout le monde se parle.",
            "La boulangère connaît le prénom de tous les enfants de la rue.",
            "Avant, il y avait un cinéma là où on voit ce parking.",
            "Les voisins du troisième ont installé des bacs devant l'immeuble.",
            "On a repeint le mur ensemble un dimanche, on était douze.",
        ],
    },
    {
        "nom": "nuit",
        "tags": ["nuit", "insomnie", "étoiles", "silence", "veille"],
        "teinte": 350,
        "note": 147,
        "phrases": [
            "À trois heures du matin, la ville a une autre respiration.",
            "Je ne dors pas depuis des semaines et j'ai fini par aimer ça.",
            "On voyait les étoiles ici avant, maintenant il y a trop de lumière.",
            "La nuit, on entend le train qu'on n'entend jamais le jour.",
            "Je marche pour ne pas penser, et je pense quand même.",
        ],
    },
    {
        "nom": "travail",
        "tags": ["travail", "usine", "métier", "mains", "retraite"],
        "teinte": 78,
        "note": 175,
        "phrases": [
            "Quarante ans à la même machine, et je connais son bruit par cœur.",
            "On m'a dit que mon métier disparaîtrait, il n'a pas disparu.",
            "Mes mains racontent mieux mon travail que mon curriculum.",
            "Le premier jour, personne ne m'a expliqué, j'ai regardé et j'ai appris.",
            "Je pars à la retraite vendredi et je ne sais pas quoi en penser.",
        ],
    },
    {
        "nom": "amour",
        "tags": ["amour", "rencontre", "rupture", "lettre", "attente"],
        "teinte": 0,
        "note": 220,
        "phrases": [
            "Je lui ai écrit une lettre que je n'ai jamais envoyée.",
            "On s'est quittés bien, c'est ce qui a été le plus dur.",
            "Elle riait avant la fin des blagues, toujours.",
            "Trente-deux ans ensemble, et il me surprend encore.",
            "Je l'attends tous les jeudis à cette table, c'est notre habitude.",
        ],
    },
    {
        "nom": "avenir",
        "tags": ["avenir", "climat", "enfants", "espoir", "peur"],
        "teinte": 95,
        "note": 294,
        "phrases": [
            "Ma fille m'a demandé si l'été serait toujours comme ça. J'ai menti.",
            "On plante des arbres dont on ne verra pas l'ombre, c'est bien le but.",
            "J'ai peur, mais j'ai surtout envie qu'on fasse quelque chose.",
            "Dans dix ans, ce quartier sera méconnaissable. En bien, j'espère.",
            "Les jeunes savent des choses qu'on refuse d'entendre.",
        ],
    },
    {
        "nom": "exil",
        "tags": ["exil", "langue", "voyage", "racines", "papiers"],
        "teinte": 25,
        "note": 330,
        "phrases": [
            "Je rêve encore dans ma première langue, mais je compte dans la seconde.",
            "Ma mère m'appelle le dimanche, on parle du temps qu'il fait là-bas.",
            "Il a fallu trois ans pour un papier qui tient sur une page.",
            "On dit que je n'ai pas d'accent. Je ne sais pas si c'est un compliment.",
            "J'ai emporté une poignée de terre, elle est dans un bocal.",
        ],
    },
]

PRENOMS = [
    "Nina", "Samir", "Colette", "Yanis", "Fatou", "Léon", "Amel", "Gaspard",
    "Rosa", "Malik", "Jeanne", "Ibrahim", "Adèle", "Youssef", "Simone", "Tarek",
    "Louise", "Mehdi", "Odette", "Kofi", "Camille", "Ana", "Bakary", "Élise",
    "Hugo", "Nour", "Marcel", "Leïla", "Basile", "Sonia", "Aimé", "Rachida",
    "Théo", "Maya", "Antoine", "Djamila", "Paulette", "Ousmane", "Iris", "Vasco",
]


class Command(BaseCommand):
    help = "Crée un corpus de clameurs de démonstration, écoutables et illustrées."

    def add_arguments(self, parseur):
        parseur.add_argument("--nombre", type=int, default=100)
        parseur.add_argument("--borne", default="place-du-marche")
        parseur.add_argument(
            "--vider", action="store_true",
            help="Supprime les capsules existantes et leurs fichiers avant de créer.",
        )
        parseur.add_argument("--graine", type=int, default=1789)

    def handle(self, *args, **options):
        alea = random.Random(options["graine"])

        borne, cree = Borne.objects.get_or_create(
            slug=options["borne"],
            defaults={
                "nom": "Place du marché",
                "numero_serie_imprimante": "N411245U00000",
                "texte_accueil": (
                    "Ici, on dépose une idée, un souvenir, une colère. "
                    "Deux minutes suffisent. Tu repars avec un ticket."
                ),
            },
        )
        if cree:
            self.stdout.write(f"Borne créée : /b/{borne.slug}")

        if options["vider"]:
            self._vider()

        for numero in range(options["nombre"]):
            theme = THEMES[numero % len(THEMES)]
            self._creer_une_clameur(borne, theme, alea)
            if (numero + 1) % 20 == 0:
                self.stdout.write(f"  {numero + 1} clameurs…")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{options['nombre']} clameurs créées sur /b/{borne.slug}"
        ))
        self.stdout.write(f"  {Tag.objects.count()} tags, "
                          f"{Capsule.objects.filter(photo='').count()} sans photo")

    # ------------------------------------------------------------------ #

    def _vider(self):
        capsules = Capsule.objects.all()
        nombre = capsules.count()
        for capsule in capsules:
            for champ in (capsule.audio_original, capsule.audio_diffusion, capsule.photo):
                if champ:
                    champ.delete(save=False)
        capsules.delete()
        Tag.objects.all().delete()
        self.stdout.write(self.style.WARNING(f"{nombre} capsule(s) supprimée(s)."))

    def _creer_une_clameur(self, borne, theme, alea):
        duree = alea.randint(14, 195)
        pseudo = alea.choice(PRENOMS) if alea.random() > 0.12 else ""

        capsule = Capsule(
            borne=borne,
            pseudo=pseudo,
            statut=StatutCapsule.PUBLIEE,
            duree_secondes=duree,
            langue_detectee="fr",
            nombre_ecoutes=max(0, int(alea.gauss(6, 9))),
        )

        audio = self._fabriquer_l_audio(theme["note"], duree, alea)
        # audio_original en m4a : c'est exactement ce qu'envoie un iPhone, et
        # cela évite une conversion inutile pour des fixtures.
        # / m4a original: that is what an iPhone sends anyway.
        capsule.audio_original.save("capsule.m4a", File(audio), save=False)
        audio.seek(0)
        capsule.audio_diffusion.save("diffusion.m4a", File(audio), save=False)

        if alea.random() > 0.35:
            capsule.photo.save(
                "photo.jpg", File(self._fabriquer_une_image(theme["teinte"], alea)),
                save=False,
            )

        segments, texte = self._fabriquer_la_transcription(theme, duree, alea)
        capsule.transcription_raw = {"segments": segments}
        capsule.transcription_texte = texte
        capsule.embedding = self._fabriquer_le_vecteur(theme, alea)
        capsule.enrichie_le = timezone.now()
        capsule.save()

        Capsule.objects.filter(pk=capsule.pk).update(
            creee_le=timezone.now() - timezone.timedelta(
                hours=alea.randint(1, 720), minutes=alea.randint(0, 59)
            ),
            publiee_le=timezone.now() - timezone.timedelta(hours=alea.randint(1, 720)),
        )

        for nom_de_tag in alea.sample(theme["tags"], alea.randint(1, 2)):
            tag, _cree = Tag.objects.get_or_create(nom=nom_de_tag)
            TagDeCapsule.objects.get_or_create(
                capsule=capsule, tag=tag, origine=TagDeCapsule.AUTEUR
            )

    def _fabriquer_l_audio(self, note, duree, alea):
        """Un son court et audible, propre à chaque thème.

        On borne à huit secondes : cent fichiers de trois minutes pèseraient
        des dizaines de mégaoctets pour rien. `duree_secondes` affiche la durée
        annoncée, ce qui suffit à voir la mise en page.
        / Capped at eight seconds: a hundred three-minute files would be wasteful.
        """
        secondes = min(duree, 8)
        harmonique = note * alea.choice([1, 1.5, 2])
        with tempfile.TemporaryDirectory() as dossier:
            sortie = Path(dossier) / "c.m4a"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", f"sine=frequency={note}:duration={secondes}",
                    "-f", "lavfi",
                    "-i", f"sine=frequency={harmonique:.0f}:duration={secondes}",
                    "-filter_complex", "[0][1]amix=inputs=2,tremolo=f=3:d=0.6",
                    "-c:a", "aac", "-b:a", "64k", "-ac", "1",
                    "-movflags", "+faststart", str(sortie),
                ],
                check=True, capture_output=True, timeout=60,
            )
            return io.BytesIO(sortie.read_bytes())

    def _fabriquer_une_image(self, teinte, alea):
        """Une image abstraite dans la teinte du thème.

        Les teintes restent dans l'arc chaud du projet : une photo violette
        sur un papier brun ne se lit pas comme une variation, mais comme un
        accident. / Warm arc only: a violet image on brown paper reads as
        an accident.

        Elle doit rester lisible une fois tramée en noir et blanc sur le
        ticket : on garde des formes larges et contrastées.
        / It must survive dithering to black and white on the ticket.
        """
        largeur, hauteur = 900, 675
        image = Image.new("RGB", (largeur, hauteur))
        dessin = ImageDraw.Draw(image)

        for y in range(hauteur):
            melange = y / hauteur
            dessin.line(
                [(0, y), (largeur, y)],
                fill=self._teinte_vers_rvb(teinte, 0.45, 0.22 + 0.5 * melange),
            )
        for _ in range(alea.randint(3, 6)):
            x, y = alea.randint(0, largeur), alea.randint(0, hauteur)
            rayon = alea.randint(70, 260)
            dessin.ellipse(
                [x - rayon, y - rayon, x + rayon, y + rayon],
                fill=self._teinte_vers_rvb(
                    (teinte + alea.randint(-25, 25)) % 360, 0.55, alea.uniform(0.4, 0.85)
                ),
            )

        image = image.filter(ImageFilter.GaussianBlur(radius=alea.randint(8, 26)))
        tampon = io.BytesIO()
        image.save(tampon, format="JPEG", quality=82)
        tampon.seek(0)
        return tampon

    @staticmethod
    def _teinte_vers_rvb(teinte, saturation, valeur):
        secteur = (teinte % 360) / 60
        composante = valeur * saturation
        secondaire = composante * (1 - abs(secteur % 2 - 1))
        base = valeur - composante
        table = [
            (composante, secondaire, 0), (secondaire, composante, 0),
            (0, composante, secondaire), (0, secondaire, composante),
            (secondaire, 0, composante), (composante, 0, secondaire),
        ]
        rouge, vert, bleu = table[int(secteur) % 6]
        return (
            int((rouge + base) * 255), int((vert + base) * 255), int((bleu + base) * 255)
        )

    def _fabriquer_la_transcription(self, theme, duree, alea):
        """Une à trois voix, pour que la diarisation ait quelque chose à montrer."""
        nombre_de_voix = alea.choices([1, 2, 3], weights=[6, 3, 1])[0]
        phrases = alea.sample(theme["phrases"], min(len(theme["phrases"]),
                                                    alea.randint(2, 4)))
        segments, debut = [], 0.0
        for index, phrase in enumerate(phrases):
            longueur = max(2.0, duree / max(len(phrases), 1))
            segments.append({
                "speaker": f"voix {index % nombre_de_voix + 1}",
                "start": round(debut, 2),
                "end": round(debut + longueur, 2),
                "text": phrase,
            })
            debut += longueur
        return segments, " ".join(phrases)

    def _fabriquer_le_vecteur(self, theme, alea):
        """Un vecteur de 1024 dimensions, groupé autour du centre de son thème.

        Le centre est déterministe (dérivé du nom du thème) : deux exécutions
        donnent les mêmes amas, donc la même constellation.
        / Deterministic cluster centres: two runs give the same constellation.
        """
        centre = random.Random(theme["nom"])
        # 0.85 de dispersion, et non 0.35 : trop serrees, les clameurs d'un
        # meme theme se superposaient en une seule tache dans le ciel, sans
        # qu'on puisse en distinguer ni en cliquer une seule.
        # / Wider spread: tighter clusters collapsed into a single blob.
        vecteur = [
            centre.gauss(0, 1) + alea.gauss(0, 0.85)
            for _ in range(1024)
        ]
        norme = math.sqrt(sum(valeur * valeur for valeur in vecteur)) or 1.0
        return [valeur / norme for valeur in vecteur]
