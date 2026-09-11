"""QR codes qui dessinent une image : l'algorithme QArt de Russ Cox.
/ QR codes that draw a picture: Russ Cox's QArt algorithm.

L'URL est encodee en mode octet, suivie de « # » et d'un nombre dont les
chiffres sont libres. Reed-Solomon etant lineaire sur GF(2), une elimination
de Gauss reporte cette liberte sur les modules de controle : on choisit alors
chaque bit pour que son module prenne la couleur de l'image. Le code reste
entierement valide, sa correction d'erreur est intacte.
Voir https://research.swtch.com/qart

Portage Python de rsc.io/qr (paquets qart, coding et gf256), sous licence :

Copyright (c) 2009 The Go Authors. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

   * Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
   * Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following disclaimer
in the documentation and/or other materials provided with the
distribution.
   * Neither the name of Google Inc. nor the names of its
contributors may be used to endorse or promote products derived from
this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import functools
import random

import numpy as np
from PIL import Image

# Version 10 (57 modules de cote), correction M (15 %) : le ticket vit dehors,
# plie ou mouille, et QArt n'ajoute aucune marge. Le masque 2 (colonnes) et la
# marge de 3 modules autour de l'image sont les reglages valides sur papier.
# / Version 10, level M: the ticket lives outdoors. Mask and margin as tested.
VERSION = 10
NIVEAU_M = 1
MASQUE = 2
MARGE_AUTOUR_DE_L_IMAGE = 3


# ------------------------------------------------------------- GF(256) et RS

EXPOSANTS = [0] * 512
LOGARITHMES = [0] * 256
_valeur = 1
for _i in range(255):
    EXPOSANTS[_i] = _valeur
    LOGARITHMES[_valeur] = _i
    _valeur <<= 1
    if _valeur & 0x100:
        _valeur ^= 0x11D
for _i in range(255, 512):
    EXPOSANTS[_i] = EXPOSANTS[_i - 255]


def _multiplier(a, b):
    if a == 0 or b == 0:
        return 0
    return EXPOSANTS[LOGARITHMES[a] + LOGARITHMES[b]]


@functools.cache
def _polynome_generateur(nombre_de_controles):
    polynome = [1]
    for i in range(nombre_de_controles):
        suivant = [*polynome, 0]
        for j in range(len(polynome)):
            suivant[j + 1] ^= _multiplier(polynome[j], EXPOSANTS[i])
        polynome = suivant
    return polynome


def _octets_de_controle(donnees, nombre_de_controles):
    """Reed-Solomon : le reste de la division des donnees par le generateur."""
    generateur = _polynome_generateur(nombre_de_controles)
    reste = list(donnees) + [0] * nombre_de_controles
    for i in range(len(donnees)):
        coefficient = reste[i]
        if coefficient:
            for j in range(1, nombre_de_controles + 1):
                reste[i + j] ^= _multiplier(generateur[j], coefficient)
    return reste[len(donnees):]


# ------------------------------------------------------------- flux de bits


class _Bits:
    def __init__(self):
        self.bits = []

    def __len__(self):
        return len(self.bits)

    def ecrire(self, valeur, nombre_de_bits):
        for i in range(nombre_de_bits - 1, -1, -1):
            self.bits.append((valeur >> i) & 1)

    def bourrer(self, nombre_de_bits):
        """Le bourrage de la norme : terminateur, alignement, puis EC 11 EC 11..."""
        if nombre_de_bits <= 4:
            self.ecrire(0, nombre_de_bits)
            return
        self.ecrire(0, 4)
        alignement = -len(self) & 7
        self.ecrire(0, alignement)
        nombre_d_octets = (nombre_de_bits - 4 - alignement) // 8
        for i in range(nombre_d_octets):
            self.ecrire(0xEC if i % 2 == 0 else 0x11, 8)

    def en_octets(self):
        return [
            int("".join(map(str, self.bits[i:i + 8])), 2) for i in range(0, len(self.bits), 8)
        ]


def _encoder_en_octets(bits, texte):
    octets = texte.encode("utf-8")
    bits.ecrire(4, 4)
    bits.ecrire(len(octets), 8 if VERSION <= 9 else 16)
    for octet in octets:
        bits.ecrire(octet, 8)


def _encoder_en_chiffres(bits, chiffres):
    bits.ecrire(1, 4)
    bits.ecrire(len(chiffres), 10 if VERSION <= 9 else 12)
    for i in range(0, len(chiffres) - 2, 3):
        bits.ecrire(int(chiffres[i:i + 3]), 10)


# ------------------------------------------------------------- plan du QR

# Par version : (position des alignements, pas entre eux, octets au total,
# motif de version, [(blocs, octets de controle par bloc) pour L, M, Q, H]).
TABLE_DES_VERSIONS = {
    10: (26, 22, 346, 0xA4D3, [(4, 18), (5, 26), (8, 24), (8, 28)]),
}

NOIR, INVERSE = 1, 2
POSITION, ALIGNEMENT, SYNCHRO, FORMAT, MOTIF_DE_VERSION, INUTILISE, DONNEE, CONTROLE, RESTE = (
    range(1, 10)
)


def _role(pixel):
    return (pixel >> 2) & 15


def _rang(pixel):
    return pixel >> 6


def _pixel(role, rang=0):
    return (role << 2) | (rang << 6)


def _masque(ligne, colonne):
    return colonne % 3 == 0


def _carre_de_position(pixels, x, y):
    cote = len(pixels)
    for dy in range(7):
        for dx in range(7):
            noir = dx in (0, 6) or dy in (0, 6) or (2 <= dx <= 4 and 2 <= dy <= 4)
            pixels[y + dy][x + dx] = _pixel(POSITION) | (NOIR if noir else 0)
    for d in range(-1, 8):
        if 0 <= y + d < cote:
            if x > 0:
                pixels[y + d][x - 1] = _pixel(POSITION)
            if x + 7 < cote:
                pixels[y + d][x + 7] = _pixel(POSITION)
        if 0 <= x + d < cote:
            if y > 0:
                pixels[y - 1][x + d] = _pixel(POSITION)
            if y + 7 < cote:
                pixels[y + 7][x + d] = _pixel(POSITION)


def _carre_d_alignement(pixels, x, y):
    for dy in range(5):
        for dx in range(5):
            noir = dx in (0, 4) or dy in (0, 4) or (dx == 2 and dy == 2)
            pixels[y + dy][x + dx] = _pixel(ALIGNEMENT) | (NOIR if noir else 0)


class _Plan:
    """Le role de chaque module : motif fixe, ou bit de donnee ou de controle."""

    def __init__(self):
        position, pas, total, motif, niveaux = TABLE_DES_VERSIONS[VERSION]
        cote = 17 + 4 * VERSION
        pixels = [[0] * cote for _ in range(cote)]
        self.pixels = pixels

        for i in range(cote):
            synchro = _pixel(SYNCHRO) | (NOIR if i % 2 == 0 else 0)
            pixels[i][6] = synchro
            pixels[6][i] = synchro
        _carre_de_position(pixels, 0, 0)
        _carre_de_position(pixels, cote - 7, 0)
        _carre_de_position(pixels, 0, cote - 7)
        x = 4
        while x + 5 < cote:
            y = 4
            while y + 5 < cote:
                dans_un_coin = (
                    (x < 7 and y < 7) or (x < 7 and y + 5 >= cote - 7) or (x + 5 >= cote - 7 and y < 7)
                )
                if not dans_un_coin:
                    _carre_d_alignement(pixels, x, y)
                y = position if y == 4 else y + pas
            x = position if x == 4 else x + pas
        for x in range(6):
            for y in range(3):
                bit = (motif >> (3 * x + y)) & 1
                pixels[cote - 11 + y][x] = _pixel(MOTIF_DE_VERSION) | (NOIR if bit else 0)
                pixels[x][cote - 11 + y] = _pixel(MOTIF_DE_VERSION) | (NOIR if bit else 0)
        pixels[cote - 8][8] = _pixel(INUTILISE) | NOIR

        self._placer_le_format()

        blocs, controles = niveaux[NIVEAU_M]
        self.blocs = blocs
        self.octets_de_controle = controles * blocs
        self.octets_de_donnees = total - self.octets_de_controle
        self._placer_les_bits(controles)

        for y in range(cote):
            for x in range(cote):
                if _role(pixels[y][x]) in (DONNEE, CONTROLE, RESTE) and _masque(y, x):
                    pixels[y][x] ^= NOIR | INVERSE

    def _placer_le_format(self):
        pixels = self.pixels
        cote = len(pixels)
        format_ = ((NIVEAU_M ^ 1) << 13) | (MASQUE << 10)
        reste = format_
        for i in range(14, 9, -1):
            if reste & (1 << i):
                reste ^= 0x537 << (i - 10)
        format_ |= reste
        for i in range(15):
            pixel = _pixel(FORMAT, i) | (NOIR if (format_ >> i) & 1 else 0)
            if (0x5412 >> i) & 1:
                pixel ^= INVERSE | NOIR
            if i < 6:
                pixels[i][8] = pixel
            elif i < 8:
                pixels[i + 1][8] = pixel
            elif i < 9:
                pixels[8][7] = pixel
            else:
                pixels[8][14 - i] = pixel
            if i < 8:
                pixels[8][cote - 1 - i] = pixel
            else:
                pixels[cote - 1 - (14 - i)][8] = pixel

    def _placer_les_bits(self, controles_par_bloc):
        """Entrelace les blocs, puis serpente par paires de colonnes (norme QR)."""
        pixels = self.pixels
        cote = len(pixels)
        par_bloc = self.octets_de_donnees // self.blocs
        blocs_longs = self.octets_de_donnees % self.blocs
        bits_de_donnees = self.octets_de_donnees * 8
        donnees = [_pixel(DONNEE, i) for i in range(bits_de_donnees)]
        controles = [
            _pixel(CONTROLE, i + bits_de_donnees) for i in range(self.octets_de_controle * 8)
        ]
        blocs_de_donnees, blocs_de_controle = [], []
        for i in range(self.blocs):
            longueur = (par_bloc + (1 if i >= self.blocs - blocs_longs else 0)) * 8
            blocs_de_donnees.append(donnees[:longueur])
            donnees = donnees[longueur:]
            blocs_de_controle.append(controles[:controles_par_bloc * 8])
            controles = controles[controles_par_bloc * 8:]
        sequence = []
        for i in range(par_bloc + 1):
            for bloc in blocs_de_donnees:
                sequence += bloc[i * 8:(i + 1) * 8]
        for i in range(controles_par_bloc):
            for bloc in blocs_de_controle:
                sequence += bloc[i * 8:(i + 1) * 8]
        sequence += [_pixel(RESTE)] * 7

        suivant = iter(sequence)
        x = cote
        while x > 0:
            for y in range(cote - 1, -1, -1):
                for colonne in (x - 1, x - 2):
                    if _role(pixels[y][colonne]) == 0:
                        pixels[y][colonne] = next(suivant)
            x -= 2
            if x == 7:
                x -= 1
            for y in range(cote):
                for colonne in (x - 1, x - 2):
                    if _role(pixels[y][colonne]) == 0:
                        pixels[y][colonne] = next(suivant)
            x -= 2


def _avec_les_controles(bits, plan):
    """Bourre jusqu'a la capacite, puis ajoute les controles de chaque bloc."""
    capacite = plan.octets_de_donnees * 8
    if len(bits) < capacite:
        bits.bourrer(capacite - len(bits))
    if len(bits) != capacite:
        raise ValueError("trop de donnees pour ce QR")
    donnees = bits.en_octets()
    par_bloc = plan.octets_de_donnees // plan.blocs
    blocs_longs = plan.octets_de_donnees % plan.blocs
    controles_par_bloc = plan.octets_de_controle // plan.blocs
    resultat = list(donnees)
    for i in range(plan.blocs):
        longueur = par_bloc + (1 if i >= plan.blocs - blocs_longs else 0)
        resultat += _octets_de_controle(donnees[:longueur], controles_par_bloc)
        donnees = donnees[longueur:]
    return resultat


# ------------------------------------------------------------- elimination


def _bit(octets, rang):
    return (octets[rang // 8] >> (7 - rang % 8)) & 1


def _en_vecteur(octets):
    """Octets -> entier ou le bit de rang r vaut 1 << r (XOR rapide)."""
    vecteur = 0
    for i, octet in enumerate(octets):
        for k in range(8):
            if (octet >> (7 - k)) & 1:
                vecteur |= 1 << (8 * i + k)
    return vecteur


def _en_octets(vecteur, nombre):
    octets = []
    for i in range(nombre):
        octet = 0
        for k in range(8):
            octet = (octet << 1) | ((vecteur >> (8 * i + k)) & 1)
        octets.append(octet)
    return octets


@functools.cache
def _base_des_mots_valides(octets_de_donnees, octets_de_controle):
    """Un mot Reed-Solomon valide par bit de donnee : leurs XOR le restent.
    Ne depend que des tailles, d'ou le cache. / One valid codeword per data bit."""
    base = []
    for i in range(octets_de_donnees * 8):
        donnees = [0] * octets_de_donnees
        donnees[i // 8] = 1 << (7 - i % 8)
        base.append(_en_vecteur(donnees + _octets_de_controle(donnees, octets_de_controle)))
    return tuple(base)


class _Bloc:
    """Un bloc Reed-Solomon dont on fixe les bits un par un, tant que la base
    le permet. / A block whose bits are fixed one by one while the basis allows."""

    def __init__(self, donnees, octets_de_controle):
        self.octets_de_donnees = len(donnees)
        self.octets_de_controle = octets_de_controle
        self.mot = _en_vecteur(list(donnees) + _octets_de_controle(donnees, octets_de_controle))
        self.base = list(_base_des_mots_valides(len(donnees), octets_de_controle))

    def fixer(self, rang, valeur):
        """Donne au bit `rang` la valeur voulue ; False si plus aucun degre de
        liberte ne le permet. Un bit fixe ne bouge plus ensuite."""
        masque = 1 << rang
        for j, ligne in enumerate(self.base):
            if ligne & masque:
                pivot = self.base.pop(j)
                break
        else:
            return False
        self.base = [ligne ^ pivot if ligne & masque else ligne for ligne in self.base]
        if (self.mot >> rang) & 1 != valeur:
            self.mot ^= pivot
        return True

    def octets(self):
        octets = _en_octets(self.mot, self.octets_de_donnees + self.octets_de_controle)
        donnees, controles = octets[:self.octets_de_donnees], octets[self.octets_de_donnees:]
        if _octets_de_controle(donnees, self.octets_de_controle) != controles:
            raise RuntimeError("bloc Reed-Solomon incoherent")
        return octets


# ------------------------------------------------------------- image cible


def _cible(chemin_image, cote):
    """L'image en gris 0..255, reduite au QR ; -1 hors de l'image."""
    image = Image.open(chemin_image).convert("RGBA")
    interieur = cote - 2 * MARGE_AUTOUR_DE_L_IMAGE
    largeur, hauteur = image.size
    if largeur > hauteur:
        largeur, hauteur = interieur, max(1, round(hauteur * interieur / largeur))
    else:
        largeur, hauteur = max(1, round(largeur * interieur / hauteur)), interieur
    pixels = np.asarray(image.resize((largeur, hauteur), Image.LANCZOS)).astype(int)
    gris = (299 * pixels[..., 0] + 587 * pixels[..., 1] + 114 * pixels[..., 2] + 500) // 1000
    gris[pixels[..., 3] == 0] = -1
    cible = -np.ones((cote, cote), dtype=int)
    gauche, haut = (cote - largeur) // 2, (cote - hauteur) // 2
    cible[haut:haut + hauteur, gauche:gauche + largeur] = gris
    return cible


def _contraste(cible):
    """Variance locale (fenetre 11x11) : les bords de l'image passent d'abord."""
    cote = cible.shape[0]
    somme = np.zeros_like(cible)
    somme_des_carres = np.zeros_like(cible)
    effectif = np.zeros_like(cible)
    for dy in range(-5, 6):
        for dx in range(-5, 6):
            y0, y1 = max(0, dy), min(cote, cote + dy)
            x0, x1 = max(0, dx), min(cote, cote + dx)
            voisins = cible[y0:y1, x0:x1]
            somme[y0 - dy:y1 - dy, x0 - dx:x1 - dx] += voisins
            somme_des_carres[y0 - dy:y1 - dy, x0 - dx:x1 - dx] += voisins * voisins
            effectif[y0 - dy:y1 - dy, x0 - dx:x1 - dx] += 1
    moyenne = somme // effectif
    contraste = somme_des_carres // effectif - moyenne * moyenne
    contraste[cible < 0] = -1
    return contraste


# ------------------------------------------------------------- QArt


def dessiner_le_qr(url, chemin_image, graine=None):
    """Le QR de `url` qui dessine `chemin_image`.

    Rend une grille carree de booleens (True = noir), sans zone de silence.
    Le texte encode est `url#<chiffres>` : le fragment est ignore par le
    navigateur. / Returns the module grid; the payload is `url#<digits>`.
    """
    hasard = random.Random(graine)
    plan = _Plan()
    cote = len(plan.pixels)
    cible = _cible(chemin_image, cote)
    contraste = _contraste(cible)

    modules = {}
    for y in range(cote):
        for x in range(cote):
            pixel = plan.pixels[y][x]
            if _role(pixel) in (DONNEE, CONTROLE):
                modules[_rang(pixel)] = {
                    "pixel": pixel,
                    "blanc_voulu": cible[y, x] < 0 or cible[y, x] >= 128,
                    "priorite": int(contraste[y, x]),
                    "force_a_zero": False,
                }

    prefixe = url + "#"
    entete = _Bits()
    _encoder_en_octets(entete, prefixe)
    _encoder_en_chiffres(entete, "")
    debut_libre = len(entete)
    bits_libres = plan.octets_de_donnees * 8 - debut_libre
    if bits_libres < 10:
        raise ValueError("URL trop longue pour ce QR")
    nombre_de_groupes = bits_libres // 10
    fin_libre = debut_libre + nombre_de_groupes * 10

    controles_par_bloc = plan.octets_de_controle // plan.blocs
    par_bloc = plan.octets_de_donnees // plan.blocs
    blocs_longs = plan.octets_de_donnees % plan.blocs

    # Un groupe de 10 bits code 3 chiffres, donc au plus 999 : un groupe qui
    # depasse voit un de ses bits force a zero, et l'on recommence.
    # / 10 bits hold 3 digits (max 999): force a bit to zero and retry.
    for _tentative in range(50):
        bits = _Bits()
        _encoder_en_octets(bits, prefixe)
        _encoder_en_chiffres(bits, "0" * (nombre_de_groupes * 3))
        octets = _avec_les_controles(bits, plan)

        debut_donnees = debut_controles = 0
        for numero in range(plan.blocs):
            longueur = par_bloc + (1 if numero >= plan.blocs - blocs_longs else 0)
            donnees = octets[debut_donnees // 8: debut_donnees // 8 + longueur]
            bloc = _Bloc(donnees, controles_par_bloc)

            libre_de = min(max(0, debut_libre - debut_donnees), longueur * 8)
            libre_a = max(min(longueur * 8, fin_libre - debut_donnees), libre_de)
            for rang in [*range(libre_de), *range(libre_a, longueur * 8)]:
                bloc.fixer(rang, _bit(donnees, rang))

            candidats = [debut_donnees + rang for rang in range(libre_de, libre_a)]
            candidats += [
                plan.octets_de_donnees * 8 + debut_controles + rang
                for rang in range(controles_par_bloc * 8)
            ]
            tirage = {rang: hasard.randrange(256) for rang in candidats}
            candidats.sort(key=lambda rang: (modules[rang]["priorite"], tirage[rang]), reverse=True)
            for rang_global in candidats:
                module = modules[rang_global]
                valeur = 0 if module["blanc_voulu"] else 1
                if module["pixel"] & INVERSE:
                    valeur ^= 1
                if module["force_a_zero"]:
                    valeur = 0
                if _role(module["pixel"]) == DONNEE:
                    rang = rang_global - debut_donnees
                else:
                    rang = rang_global - plan.octets_de_donnees * 8 - debut_controles + longueur * 8
                bloc.fixer(rang, valeur)

            resultat = bloc.octets()
            octets[debut_donnees // 8: debut_donnees // 8 + longueur] = resultat[:longueur]
            debut = plan.octets_de_donnees + debut_controles // 8
            octets[debut: debut + controles_par_bloc] = resultat[longueur:]
            debut_donnees += longueur * 8
            debut_controles += controles_par_bloc * 8

        chiffres = []
        depassements = 0
        for groupe in range(nombre_de_groupes):
            valeur = 0
            for j in range(10):
                valeur = (valeur << 1) | _bit(octets, debut_libre + 10 * groupe + j)
            if valeur >= 1000:
                module = modules[debut_libre + 10 * groupe + 3]
                module["priorite"] = 1 << 40
                module["force_a_zero"] = True
                depassements += 1
            chiffres.append(f"{valeur:03d}")
        if depassements == 0:
            break
    else:
        raise RuntimeError("QArt n'a pas trouve de nombre valide")

    verification = _Bits()
    _encoder_en_octets(verification, prefixe)
    _encoder_en_chiffres(verification, "".join(chiffres))
    if _avec_les_controles(verification, plan) != octets:
        raise RuntimeError("le QR ne correspond pas a son texte")

    grille = np.zeros((cote, cote), dtype=bool)
    for y in range(cote):
        for x in range(cote):
            pixel = plan.pixels[y][x]
            noir = bool(pixel & NOIR)
            if _role(pixel) in (DONNEE, CONTROLE) and _bit(octets, _rang(pixel)):
                noir = not noir
            grille[y, x] = noir
    return grille
