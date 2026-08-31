"""Le coeur du projet : une capsule sonore et ses tags.
/ The heart of the project: a sound capsule and its tags."""

from uuid import uuid4

from django.db import models
from django.utils.translation import gettext_lazy as _
from pgvector.django import VectorField


class StatutCapsule(models.TextChoices):
    BROUILLON = "brouillon", _("Brouillon")
    PUBLIEE = "publiee", _("Publiée")
    RETIREE = "retiree", _("Retirée")


def chemin_audio_original(instance, nom_de_fichier):
    return f"capsules/{instance.uuid}/original_{nom_de_fichier}"


def chemin_audio_diffusion(instance, nom_de_fichier):
    return f"capsules/{instance.uuid}/diffusion.m4a"


def chemin_photo(instance, nom_de_fichier):
    return f"capsules/{instance.uuid}/photo.jpg"


class Capsule(models.Model):
    # UUID et NON un entier auto-incremente : l'identifiant est public, il
    # voyage sur un ticket colle dans la rue. Un entier laisserait parcourir
    # tout le corpus en incrementant.
    # / A public, non-enumerable identifier: it travels on a ticket in the street.
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False)

    reglages = models.ForeignKey(
        "bornes.Reglages", on_delete=models.PROTECT, related_name="capsules",
        verbose_name=_("réglages"),
    )
    pseudo = models.CharField(max_length=80, blank=True, verbose_name=_("pseudo"))
    statut = models.CharField(
        max_length=20, choices=StatutCapsule.choices,
        default=StatutCapsule.BROUILLON, verbose_name=_("statut"),
    )

    # DEUX FICHIERS AUDIO, ET C'EST VOLONTAIRE.
    # `audio_original` est le fichier brut tel que le navigateur l'a envoye :
    # jamais reencode, jamais supprime. Il double le stockage — quelques Mo
    # par millier de capsules — et garantit qu'un meilleur modele pourra
    # retranscrire l'archive dans trois ans. Un audio recompresse deux fois
    # ne se repare pas.
    # / The original is never re-encoded nor deleted: re-compressed audio never heals.
    audio_original = models.FileField(
        upload_to=chemin_audio_original, verbose_name=_("audio original"),
    )
    audio_diffusion = models.FileField(
        upload_to=chemin_audio_diffusion, blank=True,
        verbose_name=_("audio de diffusion"),
        help_text=_("AAC/m4a : le seul format lu par tous les navigateurs."),
    )
    duree_secondes = models.PositiveIntegerField(default=0, verbose_name=_("durée"))
    photo = models.ImageField(
        upload_to=chemin_photo, blank=True, null=True, verbose_name=_("photo"),
        help_text=_("Métadonnées EXIF purgées à l'ingestion."),
    )

    creee_le = models.DateTimeField(auto_now_add=True, verbose_name=_("créée le"))
    publiee_le = models.DateTimeField(null=True, blank=True, verbose_name=_("publiée le"))

    # Ce n'est pas un champ « au cas ou » : c'est la seule mesure qui repondra
    # a la question dont depend tout le projet — est-ce que les passants
    # scannent reellement les tickets colles ?
    # / The only metric that answers whether passers-by actually scan.
    nombre_ecoutes = models.PositiveIntegerField(default=0, verbose_name=_("écoutes"))

    transcription_raw = models.JSONField(
        null=True, blank=True, verbose_name=_("transcription brute"),
        help_text=_("Segments diarisés : [{speaker, start, end, text}]"),
    )
    transcription_texte = models.TextField(blank=True, verbose_name=_("transcription"))
    langue_detectee = models.CharField(max_length=10, blank=True, verbose_name=_("langue"))
    embedding = VectorField(dimensions=1024, null=True, blank=True, verbose_name=_("vecteur"))

    # Position dans la constellation, en [0, 1]. Calculee par la commande
    # `projeter_la_constellation` et STOCKEE : une projection se recalcule
    # globalement, pas capsule par capsule, et les etoiles doivent rester a la
    # meme place d'une visite a l'autre — sinon on ne peut plus s'y reperer.
    # / Stored, not computed live: the stars must not move between visits.
    position_x = models.FloatField(null=True, blank=True, verbose_name=_("position x"))
    position_y = models.FloatField(null=True, blank=True, verbose_name=_("position y"))
    enrichie_le = models.DateTimeField(null=True, blank=True, verbose_name=_("enrichie le"))
    erreur_enrichissement = models.TextField(blank=True, verbose_name=_("erreur"))

    class Meta:
        verbose_name = _("capsule")
        verbose_name_plural = _("capsules")
        ordering = ["-creee_le"]

    def __str__(self):
        return f"{self.pseudo or 'anonyme'} — {self.creee_le:%d/%m/%Y %H:%M}"

    @property
    def type_mime_a_servir(self) -> str:
        """Le type du fichier reellement servi.

        Annoncer `audio/mp4` sur le repli serait pire que de ne rien annoncer :
        quand ffmpeg a echoue, c'est le webm ou l'ogg d'origine qui part, et un
        navigateur a qui l'on ment sur le type refuse de le decoder sans jamais
        essayer autre chose. Le mode degrade promis par l'invariant I1 ne
        fonctionnerait pas.
        / Mislabelling the fallback is worse than saying nothing: the browser
          would refuse to decode it and never try anything else.
        """
        if self.audio_diffusion:
            return "audio/mp4"
        nom = (self.audio_original.name or "").lower()
        for extension, type_mime in (
            (".webm", "audio/webm"), (".ogg", "audio/ogg"), (".oga", "audio/ogg"),
            (".m4a", "audio/mp4"), (".mp4", "audio/mp4"), (".wav", "audio/wav"),
            (".mp3", "audio/mpeg"),
        ):
            if nom.endswith(extension):
                return type_mime
        return ""

    @property
    def audio_a_servir(self):
        """Le fichier que la page de lecture doit servir.
        Repli sur l'original si la normalisation a echoue : mieux vaut un
        audio illisible sur un navigateur que pas d'audio du tout.
        / Falls back to the original if normalisation failed."""
        return self.audio_diffusion if self.audio_diffusion else self.audio_original


class Tag(models.Model):
    nom = models.CharField(max_length=60, unique=True, verbose_name=_("nom"))

    class Meta:
        verbose_name = _("tag")
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class TagDeCapsule(models.Model):
    """Lien capsule-tag, QUI GARDE LA TRACE DE SON ORIGINE.

    Les tags saisis par l'auteur sont sa parole. Ceux extraits par le modele
    sont une hypothese. Sur un projet qui affiche des voix sous pseudo dans la
    rue, melanger les deux dans une table indistincte reviendrait a mettre des
    mots dans la bouche des gens.
    / Author tags are speech; machine tags are a guess. Never conflate them.
    """

    AUTEUR = "auteur"
    MACHINE = "machine"
    ORIGINES = [(AUTEUR, _("Saisi par l'auteur")), (MACHINE, _("Extrait par le modèle"))]

    capsule = models.ForeignKey(
        Capsule, on_delete=models.CASCADE, related_name="tags_de_capsule",
    )
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name="capsules")
    origine = models.CharField(max_length=10, choices=ORIGINES, verbose_name=_("origine"))

    class Meta:
        verbose_name = _("tag de capsule")
        unique_together = [("capsule", "tag", "origine")]

    def __str__(self):
        return f"{self.tag.nom} ({self.origine})"
