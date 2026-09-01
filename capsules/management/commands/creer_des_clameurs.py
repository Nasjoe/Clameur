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

import base64
import io
import logging
import math
import os
import random
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFilter

from bornes.models import Reglages
from capsules.models import Capsule, StatutCapsule, Tag, TagDeCapsule

logger = logging.getLogger(__name__)

# Combien de clameurs sont REELLEMENT PARLEES sous `--avec-mistral`. Six
# suffisent a entendre le corpus et a voir une transcription a deux voix ;
# cent coûteraient une minute d'attente et autant d'appels a la synthese.
# / Six spoken capsules are enough to hear the corpus without paying for a hundred.
CAPSULES_PARLEES = 6

MODELE_TTS = "voxtral-mini-tts-latest"
TAILLE_DU_LOT = 32
SILENCE_ENTRE_REPLIQUES = 0.4

# LE CATALOGUE MISTRAL N'A QU'UNE VOIX FRANCAISE — `marie`, en six emotions.
# Un dialogue demande DEUX TIMBRES : sans quoi la diarisation n'a rien a
# separer. On emprunte donc une voix anglaise, qui lit le francais avec un
# accent. Verifie le 2026-08-31 : Voxtral la transcrit sans faute et la
# distingue nettement de marie. Un accent dans la rue n'est pas une anomalie.
# / Mistral ships a single French voice; a dialogue needs two timbres, so we
#   borrow an English one. Voxtral transcribes and separates it perfectly.
VOIX = {
    "posee": "5a271406-039d-46fe-835b-fbbb00eaf08d",   # fr_marie_neutral
    "en colere": "a7c07cdc-1c35-4d87-a938-c610a654f600",  # fr_marie_angry
    "emue": "4adeb2c6-25a3-44bc-8100-5234dfc1193b",    # fr_marie_sad
    "autre timbre": "e3596645-b1af-469e-b857-f18ddedc7652",  # gb_oliver_neutral
}


def _vecteurs_du_modele(textes: list[str]) -> list[list[float]] | None:
    """Les vrais vecteurs de `mistral-embed`, ou None s'il faut s'en passer.

    NE LEVE JAMAIS. Une clef absente, un reseau coupe, une API en panne : le
    corpus doit se fabriquer quand meme, avec ses vecteurs synthetiques. C'est
    la promesse du README — `make fixture` marche sans clef.
    / Never raises: the README promises fixtures work with no key at all.
    """
    if not os.environ.get("MISTRAL_API_KEY"):
        return None
    try:
        from mistralai.client import Mistral

        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        vecteurs: list[list[float]] = []
        for debut in range(0, len(textes), TAILLE_DU_LOT):
            reponse = client.embeddings.create(
                model=settings.MISTRAL_MODELE_EMBEDDING,
                inputs=textes[debut:debut + TAILLE_DU_LOT],
            )
            vecteurs.extend(donnee.embedding for donnee in reponse.data)
        return vecteurs
    except Exception:
        logger.exception("embeddings reels indisponibles, repli sur le synthetique")
        return None


def _synthetiser_une_replique(texte: str, voix: str, dossier: str, index: int) -> Path:
    """Fait dire une phrase par une voix, et rend le wav produit.
    / Has one voice say one line, and returns the wav it produced."""
    from mistralai.client import Mistral

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    reponse = client.audio.speech.complete(
        model=MODELE_TTS, input=texte, voice_id=voix, response_format="wav",
    )
    chemin = Path(dossier) / f"{index:02d}.wav"
    # L'API rend du base64, jamais des octets : `write_bytes` sur la chaine
    # brute leve un TypeError. / The API returns base64, never raw bytes.
    chemin.write_bytes(base64.b64decode(reponse.audio_data))
    return chemin

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
        parseur.add_argument(
            "--vider", action="store_true",
            help="Supprime les capsules existantes et leurs fichiers avant de créer.",
        )
        parseur.add_argument("--graine", type=int, default=1789)
        parseur.add_argument(
            "--avec-mistral", action="store_true",
            help=(
                "Appelle vraiment l'API : vecteurs de mistral-embed et "
                f"{CAPSULES_PARLEES} clameurs parlées par la synthèse vocale. "
                "Sans clé, le corpus se fabrique quand même, en synthétique."
            ),
        )

    def handle(self, *args, **options):
        alea = random.Random(options["graine"])
        self._creees = []

        # `get_solo()` cree l'objet unique avec ses valeurs par defaut s'il
        # n'existe pas encore. / get_solo() creates the single row if missing.
        reglages = Reglages.get_solo()

        if options["vider"]:
            self._vider()

        for numero in range(options["nombre"]):
            theme = THEMES[numero % len(THEMES)]
            self._creer_une_clameur(
                reglages, theme, alea,
                parlee=options["avec_mistral"] and numero < CAPSULES_PARLEES,
            )
            if (numero + 1) % 20 == 0:
                self.stdout.write(f"  {numero + 1} clameurs…")

        if options["avec_mistral"]:
            self._embarquer_pour_de_vrai()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{options['nombre']} clameurs créées"
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

    def _creer_une_clameur(self, reglages, theme, alea, parlee=False):
        duree = alea.randint(14, 195)
        pseudo = alea.choice(PRENOMS) if alea.random() > 0.12 else ""

        capsule = Capsule(
            reglages=reglages,
            pseudo=pseudo,
            statut=StatutCapsule.PUBLIEE,
            duree_secondes=duree,
            langue_detectee="fr",
            nombre_ecoutes=max(0, int(alea.gauss(6, 9))),
        )

        voix = self._fabriquer_une_voix(theme, alea) if parlee else None
        if voix:
            audio, segments_parles, duree = voix
            # LA DUREE EST CELLE DU FICHIER, PAS UN TIRAGE AU SORT. Une fiche
            # qui annonce trois minutes pour trente secondes de voix ment au
            # passant, et le lecteur affiche aussitot le desaccord.
            # / The duration is the file's own, not a random draw.
            capsule.duree_secondes = duree
        else:
            audio = self._fabriquer_l_audio(theme["note"], duree, alea)
            segments_parles = None
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

        if segments_parles:
            segments = segments_parles
            texte = " ".join(segment["text"] for segment in segments)
        else:
            segments, texte = self._fabriquer_la_transcription(theme, duree, alea)
        # `parlee` marque les clameurs dont l'audio DIT vraiment le texte : on
        # peut les ecouter en lisant. / Marks capsules whose audio says the text.
        capsule.transcription_raw = {"segments": segments, "parlee": bool(segments_parles)}
        capsule.transcription_texte = texte
        capsule.embedding = self._fabriquer_le_vecteur(theme, alea)
        capsule.enrichie_le = timezone.now()
        capsule.save()
        self._creees.append(capsule)

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

    def _embarquer_pour_de_vrai(self):
        """Remplace les vecteurs synthetiques par ceux de `mistral-embed`.

        EN UN SEUL PASSAGE, APRES COUP. Appeler l'API capsule par capsule
        ferait cent allers-retours la ou quatre suffisent ; et le faire apres
        garde la fabrication du corpus entierement hors ligne tant que l'API
        ne repond pas. / One pass, afterwards: four round trips instead of a
        hundred, and the corpus is built offline until the API answers.
        """
        vecteurs = _vecteurs_du_modele(
            [capsule.transcription_texte for capsule in self._creees]
        )
        if vecteurs is None:
            self.stdout.write(self.style.WARNING(
                "  Mistral injoignable : vecteurs synthétiques conservés."
            ))
            return

        for capsule, vecteur in zip(self._creees, vecteurs):
            capsule.embedding = vecteur
        Capsule.objects.bulk_update(self._creees, ["embedding"], batch_size=200)
        self.stdout.write(f"  {len(vecteurs)} vecteurs réels de mistral-embed.")

    def _fabriquer_une_voix(self, theme, alea):
        """Fait dire ses phrases au thème, et rend (audio m4a, segments, durée).

        Les segments portent les timings REELS, mesures sur les fichiers
        produits : on assemble soi-meme, donc on sait exactement quand chaque
        replique commence. Inutile de payer une transcription pour l'apprendre.
        / We assemble the audio ourselves, so the timings are known exactly.

        Rend None si la synthese echoue : une fixture ne doit jamais faire
        echouer `make fixture`. / Returns None on failure; fixtures never break.
        """
        phrases = alea.sample(theme["phrases"], min(len(theme["phrases"]), 3))
        # Une fois sur deux, deux timbres qui se repondent : c'est ce que la
        # diarisation doit savoir separer, et ce que la page doit savoir
        # colorer. / Half the time, two timbres answering each other.
        if alea.random() > 0.5:
            timbres = [VOIX["posee"], VOIX["autre timbre"]]
        else:
            timbres = [VOIX[alea.choice(["posee", "en colere", "emue"])]]

        try:
            with tempfile.TemporaryDirectory() as dossier:
                morceaux, segments, debut = [], [], 0.0
                for index, phrase in enumerate(phrases):
                    timbre = timbres[index % len(timbres)]
                    chemin = _synthetiser_une_replique(phrase, timbre, dossier, index)
                    longueur = self._duree_du_fichier(chemin)
                    morceaux.append(chemin)
                    segments.append({
                        "speaker": f"speaker_{index % len(timbres) + 1}",
                        "start": round(debut, 2),
                        "end": round(debut + longueur, 2),
                        "text": phrase,
                    })
                    debut += longueur + SILENCE_ENTRE_REPLIQUES

                audio = self._assembler(morceaux, dossier)
                return audio, segments, max(1, round(debut))
        except Exception:
            logger.exception("synthèse vocale impossible, repli sur le bip")
            return None

    def _assembler(self, morceaux, dossier):
        """Colle les repliques bout a bout, separees d'un souffle, en m4a.
        / Joins the lines with a breath between them."""
        silence = Path(dossier) / "silence.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
             "-t", str(SILENCE_ENTRE_REPLIQUES), str(silence)],
            check=True, capture_output=True, timeout=60,
        )
        liste = Path(dossier) / "liste.txt"
        liste.write_text(
            "".join(f"file '{m}'\nfile '{silence}'\n" for m in morceaux)
        )
        sortie = Path(dossier) / "voix.m4a"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(liste),
             "-c:a", "aac", "-b:a", "64k", "-ac", "1",
             "-movflags", "+faststart", str(sortie)],
            check=True, capture_output=True, timeout=120,
        )
        return io.BytesIO(sortie.read_bytes())

    def _duree_du_fichier(self, chemin) -> float:
        mesure = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(chemin)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        return float(mesure.stdout.strip())

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
