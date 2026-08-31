"""Ingestion des photos : on retire tout ce qui n'est pas l'image.
/ Photo ingestion: everything that is not the image is stripped."""

import io

from PIL import Image, ImageOps


def purger_les_exif(fichier) -> io.BytesIO:
    """Rend un JPEG sans aucune metadonnee.

    L'ORDRE COMPTE. On applique d'abord l'orientation, ensuite seulement on
    efface : effacer avant afficherait la photo de travers sur la moitie des
    telephones. Et si on n'effacait pas, les coordonnees GPS publieraient la
    position de la borne, et parfois celle de l'auteur.
    / Order matters: apply orientation first, then strip. Otherwise photos come
    out sideways — and unstripped GPS would reveal where the borne stands.
    """
    image = Image.open(fichier)
    image = ImageOps.exif_transpose(image)

    # TOUJOURS EN RGB, y compris depuis un niveau de gris. Le pilote de
    # l'imprimante indexe trois canaux par pixel : une image en mode `L` lui
    # donne un tableau a deux dimensions et le fait lever une IndexError. La
    # capsule serait publiee, mais son ticket ne sortirait jamais, et chaque
    # relance echouerait a l'identique.
    # / Always RGB, greyscale included: the printer driver indexes three
    #   channels and an `L` image would make every print attempt fail.
    if image.mode != "RGB":
        image = image.convert("RGB")

    # Recreer l'image depuis ses seuls pixels : rien d'autre ne survit.
    # / Rebuild from pixels alone: nothing else survives.
    image_nue = Image.new(image.mode, image.size)
    image_nue.paste(image)

    sortie = io.BytesIO()
    image_nue.save(sortie, format="JPEG", quality=85)
    sortie.seek(0)
    return sortie
