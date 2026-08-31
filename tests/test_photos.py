"""La purge des metadonnees des photos.

Une photo prise au telephone embarque tres souvent des coordonnees GPS.
Publiee telle quelle, elle geolocalise la borne et parfois son auteur — ce qui
contredirait frontalement la promesse du projet : « le systeme ne saura jamais
ou un ticket a ete pose ».
/ Phone photos carry GPS EXIF: publishing them would geolocate the borne.
"""

import io

from PIL import Image

from capsules.photos import purger_les_exif

TAG_ORIENTATION = 0x0112
TAG_GPS = 0x8825


def une_photo_de_telephone():
    """Une photo avec coordonnees GPS et orientation, comme en produit un telephone."""
    image = Image.new("RGB", (60, 40), "grey")
    exif = image.getexif()
    exif[TAG_ORIENTATION] = 6  # rotation de 90 degres
    gps = exif.get_ifd(TAG_GPS)
    gps[1] = "N"
    gps[2] = (48.0, 51.0, 0.0)
    gps[3] = "E"
    gps[4] = (2.0, 21.0, 0.0)

    tampon = io.BytesIO()
    image.save(tampon, format="JPEG", exif=exif.tobytes())
    tampon.seek(0)
    return tampon


def test_la_photo_de_depart_porte_bien_des_coordonnees():
    """Garde-fou : sans lui, les tests suivants passeraient sur une photo vide."""
    metadonnees = Image.open(une_photo_de_telephone()).getexif()
    assert dict(metadonnees.get_ifd(TAG_GPS)), "la fixture ne porte aucun GPS"


def test_les_coordonnees_gps_disparaissent():
    resultat = purger_les_exif(une_photo_de_telephone())
    metadonnees = Image.open(resultat).getexif()
    assert not dict(metadonnees.get_ifd(TAG_GPS)), "coordonnees GPS encore presentes"


def test_l_orientation_est_appliquee_avant_d_etre_effacee():
    """Effacer l'EXIF sans appliquer l'orientation afficherait la photo de travers
    sur la moitie des telephones."""
    image = Image.open(purger_les_exif(une_photo_de_telephone()))
    assert image.size == (40, 60), "rotation non appliquee avant la purge"
    assert image.getexif().get(TAG_ORIENTATION) is None
