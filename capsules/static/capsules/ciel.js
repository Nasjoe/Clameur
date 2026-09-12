/*
 * Le ciel : un relief de densite, des regions nommees, des etoiles.
 *
 * LES DONNEES VIENNENT DE `json_script`, JAMAIS DU DOM. HTMX remplace
 * `#resultats` a chaque frappe de la recherche, et une adresse partagee avec
 * `?q=` ne rend qu'une poignee de fiches : un ciel construit sur ces fiches
 * serait ampute de tout ce que la recherche ecarte.
 * / Data comes from json_script: HTMX swaps the list on every keystroke.
 *
 * LE SERVEUR CALCULE LE SENS, LE NAVIGATEUR DESSINE. Les positions, la grille
 * de densite et les regions nommees arrivent toutes faites ; ici on trace les
 * courbes, on pose les noms, on colore et on ecoute.
 * / The server computes meaning; this file only draws it.
 */

(function () {
  "use strict";

  const svg = document.getElementById("ciel");
  if (!svg) return;

  const ESPACE = "http://www.w3.org/2000/svg";
  const CASES = 96;
  const COTE = 1000;
  const NIVEAUX = 10;

  const lire = (id) => {
    const balise = document.getElementById(id);
    return balise ? JSON.parse(balise.textContent) : [];
  };
  const grille = lire("donnees-grille");
  const lesRegions = lire("donnees-regions");
  const CORPUS = lire("donnees-etoiles");

  // ---------------------------------------------------------------- le relief

  function dessinerLeRelief() {
    if (!grille.length) return;      // ciel vide : ni relief ni noms

    const seuils = [];
    for (let n = 1; n <= NIVEAUX; n++) seuils.push(n / (NIVEAUX + 1));

    const contours = d3.contours().size([CASES, CASES]).thresholds(seuils)(grille.flat());
    const echelle = COTE / CASES;
    const fragment = document.createDocumentFragment();

    contours.forEach((contour, rang) => {
      const chemin = document.createElementNS(ESPACE, "path");
      chemin.setAttribute("d", versChemin(contour, echelle));
      // Les anneaux interieurs sont des TROUS, pas des iles : sans `evenodd`,
      // une cuvette cernee par un massif se remplit comme un sommet.
      // / Inner rings are holes: without evenodd a basin fills like a peak.
      chemin.setAttribute("fill-rule", "evenodd");
      // Les hauteurs s'eclaircissent dans les tons du papier : la couleur
      // reste reservee aux etoiles.
      // / Heights lighten within the paper tones; colour belongs to the stars.
      const clarte = 0.205 + (rang / NIVEAUX) * 0.105;
      chemin.setAttribute("fill", `oklch(${clarte.toFixed(3)} 0.028 45)`);
      chemin.setAttribute("stroke", "oklch(0.94 0.016 70 / 0.10)");
      chemin.setAttribute("stroke-width", "1");
      chemin.setAttribute("vector-effect", "non-scaling-stroke");
      fragment.appendChild(chemin);
    });
    document.getElementById("relief").appendChild(fragment);
  }

  function versChemin(contour, echelle) {
    /*
     * d3-contour rend du GeoJSON : on ecrit les anneaux a la main plutot que
     * d'embarquer d3-geo, cinquante kilo-octets pour cette boucle.
     * L'AXE Y N'EST PAS INVERSE : la grille et le ciel ont la meme orientation.
     * / Hand-written rings instead of d3-geo; the y axis is not flipped.
     */
    let d = "";
    for (const polygone of contour.coordinates) {
      for (const anneau of polygone) {
        anneau.forEach((point, rang) => {
          d += (rang === 0 ? "M" : "L")
             + (point[0] * echelle).toFixed(1) + "," + (point[1] * echelle).toFixed(1);
        });
        d += "Z";
      }
    }
    return d;
  }

  // ------------------------------------------------------------ les etiquettes

  function poserLesEtiquettes() {
    const groupe = document.getElementById("etiquettes");
    groupe.replaceChildren();
    const cadre = svg.getBoundingClientRect();
    if (!cadre.width || !lesRegions.length) return;

    /*
     * L'ECHELLE SE LIT DANS LA MATRICE DU SVG, PAS DANS LA LARGEUR DU CADRE.
     * Avec `preserveAspectRatio` a `meet`, le dessin est mis a l'echelle par le
     * PLUS PETIT des deux rapports et centre : sur un panneau large et court,
     * `viewBox.width / cadre.width` sous-estime l'echelle, et les etiquettes
     * tombent a huit pixels au lieu de quatorze.
     * / Under `meet` the drawing scales by the smaller ratio.
     */
    const matrice = svg.getScreenCTM();
    if (!matrice) return;
    const parPixel = 1 / matrice.a;
    const posees = [];

    for (const region of lesRegions) {
      const taille = (region.poids >= 12 ? 17.5 : region.poids >= 6 ? 15.5 : 13.5) * parPixel;
      const texte = document.createElementNS(ESPACE, "text");
      texte.setAttribute("x", (region.x * COTE).toFixed(1));
      texte.setAttribute("y", (region.y * COTE - 14 * parPixel).toFixed(1));
      texte.setAttribute("text-anchor", "middle");
      texte.setAttribute("font-size", taille.toFixed(1));
      // `nom-de-region` et non `etiquette` : `base.html` porte deja une classe
      // globale de ce nom, qui met ses libelles en capitales. Le nom d'une
      // region est la parole d'un auteur, ecrite comme il l'a ecrite.
      // / Not `etiquette`: the global class of that name uppercases its text.
      texte.setAttribute(
        "class", "nom-de-region" + (region.origine === "machine" ? " machine" : "")
      );
      texte.textContent = region.nom;

      if (region.origine === "machine") {
        // La machine propose, elle n'affirme pas : l'italique le dit a l'oeil,
        // ce titre le dit aux lecteurs d'ecran.
        // / The machine suggests; italics say it to the eye, this to a reader.
        const titre = document.createElementNS(ESPACE, "title");
        titre.textContent = `${region.nom} — mot-clé proposé par la machine`;
        texte.appendChild(titre);
      }

      // LES NOMS NE SE TOUCHENT PAS : seules les etoiles repondent. Un nom
      // dit ou l'on est, il n'est pas une commande, et `pointer-events: none`
      // laisse le doigt traverser jusqu'au ciel — qui attrape alors l'etoile
      // la plus proche, ce qui est exactement le geste attendu.
      // / Labels are not controls: the finger passes through to the sky.
      groupe.appendChild(texte);

      // La boite est gonflee d'une marge : deux sommets voisins d'un meme
      // massif donnaient deux noms colles, qui se lisent comme du bruit. Une
      // etiquette qui chevauche est RETIREE, jamais deplacee : poussee
      // ailleurs, elle ne designerait plus son sommet.
      // / Overlapping labels are dropped, never moved.
      const brut = texte.getBBox();
      const marge = 26 * parPixel;
      const boite = {
        x: brut.x - marge, y: brut.y - marge,
        largeur: brut.width + 2 * marge, hauteur: brut.height + 2 * marge,
      };
      const chevauche = posees.some((autre) =>
        !(boite.x + boite.largeur < autre.x || autre.x + autre.largeur < boite.x ||
          boite.y + boite.hauteur < autre.y || autre.y + autre.hauteur < boite.y));
      if (chevauche) texte.remove();
      else posees.push(boite);
    }
  }

  // ------------------------------------------------ les etoiles et la couleur

  const TEINTES_VOIX = { 1: 78, 2: 38, 3: 12 };   // ambre, terracotta, rose
  const pastilles = new Map();
  const LEGENDES = document.getElementById("choix-couleur").dataset;
  let encodage = "duree";
  try {
    encodage = localStorage.getItem("ciel:couleur") || "duree";
  } catch (erreur) {
    // Navigation privee, stockage refuse : la duree fera l'affaire.
    // / Private browsing: duration will do.
  }
  let choisie = null;

  function teinte(clameur) {
    if (encodage === "voix") {
      return TEINTES_VOIX[Math.min(3, Math.max(1, clameur.voix || 1))];
    }
    if (encodage === "heure") {
      return clameur.heure >= 7 && clameur.heure < 20 ? 80 : 5;
    }
    // Duree : l'arc chaud, de la breve au dore, borne a trois minutes — au
    // dela, l'ecart ne se voit plus. / Capped at three minutes.
    return Math.round(350 + Math.min(1, (clameur.duree || 0) / 180) * 110) % 360;
  }

  function clarte(rang) {
    /*
     * LA FRAICHEUR SE LIT EN CLARTE, JAMAIS EN TEINTE : deux informations sur
     * la meme dimension n'en donnent aucune. Le serveur envoie les etoiles de
     * la plus recente a la plus ancienne, donc le rang suffit — pas une date a
     * relire. / Freshness is lightness; the server sends newest first.
     */
    const part = CORPUS.length > 1 ? rang / (CORPUS.length - 1) : 0;
    return 0.86 - part * 0.26;
  }

  const couleur = (clameur, rang) =>
    `oklch(${clarte(rang).toFixed(3)} 0.13 ${teinte(clameur)})`;

  function dessinerLesEtoiles() {
    const groupe = document.getElementById("etoiles");
    const fragment = document.createDocumentFragment();

    CORPUS.forEach((clameur, rang) => {
      const etoile = document.createElementNS(ESPACE, "circle");
      etoile.setAttribute("cx", (clameur.x * COTE).toFixed(1));
      etoile.setAttribute("cy", (clameur.y * COTE).toFixed(1));
      // Une clameur plus ecoutee brille plus fort ; la racine carree evite
      // qu'une seule tres ecoutee ecrase tout le ciel.
      // / Square root: one popular capsule must not swallow the sky.
      etoile.setAttribute(
        "r", (6 + Math.min(10, Math.sqrt(clameur.ecoutes || 0) * 2.2)).toFixed(1)
      );
      etoile.setAttribute("fill", couleur(clameur, rang));
      etoile.setAttribute("opacity", "0.85");
      etoile.setAttribute("class", "etoile");
      etoile.setAttribute("tabindex", "0");
      etoile.setAttribute("role", "button");
      etoile.setAttribute("aria-label", clameur.titre);
      etoile.addEventListener("keydown", (evenement) => {
        if (evenement.key === "Enter" || evenement.key === " ") {
          evenement.preventDefault();
          // Au clavier comme au doigt : choisir une etoile arrete la derive,
          // sinon elle repartirait de celle-ci au morceau suivant.
          // / Keyboard or finger alike: choosing a star stops the drift.
          arreterLaDerive();
          choisir(clameur.uuid, "ciel");
        }
      });
      pastilles.set(clameur.uuid, etoile);
      fragment.appendChild(etoile);
    });
    groupe.appendChild(fragment);
  }

  function recolorer() {
    CORPUS.forEach((clameur, rang) => {
      const teinteCourante = couleur(clameur, rang);
      const etoile = pastilles.get(clameur.uuid);
      if (etoile) etoile.setAttribute("fill", teinteCourante);
      // La pastille de la fiche porte la meme couleur que son etoile : c'est
      // ce qui relie les deux ecrans quand on passe de l'un a l'autre.
      // / The card's dot matches its star: that ties the two screens together.
      const fiche = document.getElementById(`clameur-${clameur.uuid}`);
      if (fiche) fiche.style.setProperty("--astre", teinteCourante);
    });
    const nom = `legende${encodage.charAt(0).toUpperCase()}${encodage.slice(1)}`;
    document.getElementById("legende").textContent = LEGENDES[nom] || "";
  }

  document.getElementById("choix-couleur").addEventListener("click", (evenement) => {
    const bouton = evenement.target.closest("button[data-encodage]");
    if (!bouton) return;
    encodage = bouton.dataset.encodage;
    try {
      localStorage.setItem("ciel:couleur", encodage);
    } catch (erreur) {
      // Le choix vaut pour la visite. / The choice lasts for this visit.
    }
    for (const autre of evenement.currentTarget.querySelectorAll("button")) {
      autre.setAttribute("aria-pressed", String(autre === bouton));
    }
    recolorer();
  });

  // --------------------------------------------------------- la selection

  // LE CONTENEUR QUI DEFILE, ET NON CE QUE HTMX REMPLACE. `#resultats` est
  // remplace a chaque frappe : son parent immediat change avec lui.
  // / The scrolling container, not the swapped fragment.
  const panneauListe = document.getElementById("panneau-liste");
  const surMobile = () => window.matchMedia("(max-width: 800px)").matches;

  const lecteurDeLaDerive = new Audio();

  // `scroll-behavior` en CSS ne s'applique PAS a `scrollTo({behavior})` : la
  // preference doit se lire ici, sinon la page glisse quand meme sous les yeux
  // de qui a demande qu'elle ne bouge pas.
  // / CSS scroll-behavior does not govern scrollTo({behavior}).
  const GLISSEMENT = matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "auto"
    : "smooth";

  function choisir(uuid, origine) {
    if (choisie && choisie !== uuid) {
      document.getElementById(`clameur-${choisie}`)?.setAttribute("aria-current", "false");
      const ancienne = pastilles.get(choisie);
      if (ancienne) {
        ancienne.classList.remove("choisie");
        ancienne.setAttribute("opacity", "0.85");
      }
    }
    choisie = uuid;

    const fiche = document.getElementById(`clameur-${uuid}`);
    fiche?.setAttribute("aria-current", "true");
    const etoile = pastilles.get(uuid);
    if (etoile) {
      etoile.classList.add("choisie");
      etoile.setAttribute("opacity", "1");
    }

    // On ne defile que si le geste vient du ciel : venant de la liste,
    // l'element est deja sous les yeux et le deplacer le ferait fuir.
    // / Only scroll when the gesture came from the sky.
    if (origine === "ciel" && fiche) {
      clignoter(fiche);
      if (surMobile()) {
        window.scrollTo({
          top: fiche.getBoundingClientRect().top + window.scrollY - window.innerHeight * 0.45,
          behavior: GLISSEMENT,
        });
      } else {
        panneauListe.scrollTo({
          top: fiche.offsetTop - panneauListe.clientHeight / 2 + fiche.offsetHeight / 2,
          behavior: GLISSEMENT,
        });
      }
    }
    // Le cadrage ne suit l'etoile choisie que dans le bandeau replie. Ailleurs
    // il reecrirait le meme cadrage et remesurerait quinze etiquettes pour
    // rien. / Only the folded band follows the chosen star.
    if (surMobile() && replie) cadrer();
  }

  function clignoter(fiche) {
    // ON RETIRE LA CLASSE ET ON FORCE UN RECALCUL AVANT DE LA REMETTRE. Sans
    // ce detour, retoucher la meme etoile ne rejoue rien : le navigateur voit
    // une classe deja presente et considere l'animation comme faite.
    // / Without the forced reflow, re-tapping the same star replays nothing.
    fiche.classList.remove("designee");
    void fiche.offsetWidth;
    fiche.classList.add("designee");
  }

  // L'evenement `play` ne remonte pas : on ecoute en phase de capture, sur un
  // parent que HTMX ne remplace jamais.
  // / `play` does not bubble: capture, on a parent HTMX never swaps.
  document.body.addEventListener("play", (evenement) => {
    const lecteur = evenement.target;
    if (!lecteur.matches || !lecteur.matches("audio")) return;

    // Un seul son a la fois : cent lecteurs qui se chevauchent seraient
    // inecoutables. / One sound at a time.
    for (const autre of document.querySelectorAll("audio")) {
      if (autre !== lecteur && !autre.paused) autre.pause();
    }
    // Lancer un lecteur de fiche arrete la derive. Pas de comparaison avec le
    // lecteur de la derive : il vit hors du document, son `play` ne remonte
    // jamais jusqu'ici. / The drift's player is outside the document; its play
    // event never reaches this listener.
    arreterLaDerive();

    const uuid = lecteur.dataset.uuid;
    if (uuid) {
      choisir(uuid, "liste");
      compterUneEcoute(uuid);
    }
  }, true);

  const dejaComptees = new Set();

  function compterUneEcoute(uuid) {
    if (dejaComptees.has(uuid)) return;   // une ecoute par page, pas par pause
    dejaComptees.add(uuid);
    fetch(window.URL_ECOUTE.replace("00000000-0000-0000-0000-000000000000", uuid), {
      method: "POST",
      headers: { "X-CSRFToken": window.JETON_CSRF },
    }).catch(() => {});
  }

  // ------------------------------------------------------------- le toucher

  // UN APPUI N'IMPORTE OU CHOISIT L'ETOILE LA PLUS PROCHE. Une etoile fait
  // deux a quatre pixels sur un telephone, un doigt en demande quarante-quatre :
  // sans ce rayon, le ciel n'est touchable par personne.
  // / A finger needs 44 px and a star is 3: without this radius, nothing is
  //   tappable on a phone.
  const RAYON_DU_DOIGT = 30;

  svg.addEventListener("click", (evenement) => {
    // UN GLISSEMENT N'EST PAS UN APPUI. Deplacer la carte finit par un `click`
    // comme n'importe quel geste : sans ce garde, chaque deplacement
    // selectionnerait l'etoile qui se trouve sous le doigt a l'arrivee.
    // / A drag ends with a click too: without this, panning would select.
    if (aGlisse) { aGlisse = false; return; }

    /*
     * LA CONVERSION PASSE PAR LA MATRICE DU SVG. Calculer a la main depuis le
     * cadre suppose que le dessin remplit exactement le panneau : sous
     * `preserveAspectRatio` a `meet`, il est centre avec des bandes vides, et
     * le point clique se retrouve decale.
     * / getScreenCTM knows about the letterboxing; we do not.
     */
    const matrice = svg.getScreenCTM();
    if (!matrice) return;
    const point = new DOMPoint(evenement.clientX, evenement.clientY)
      .matrixTransform(matrice.inverse());
    const parPixel = 1 / matrice.a;

    let trouvee = null;
    let distance = Infinity;
    for (const clameur of CORPUS) {
      const ecart = Math.hypot(clameur.x * COTE - point.x, clameur.y * COTE - point.y);
      if (ecart < distance) { distance = ecart; trouvee = clameur; }
    }
    // Au-dela du rayon, on ne choisit rien : un appui dans le vide ne doit pas
    // faire sauter la liste a l'autre bout du corpus, NI arreter une derive en
    // cours — c'est le choix d'une autre etoile qui l'arrete, pas un appui
    // manque. / A missed tap must neither jump the list nor stop the drift.
    if (trouvee && distance <= RAYON_DU_DOIGT * parPixel) {
      arreterLaDerive();
      choisir(trouvee.uuid, "ciel");
    }
  });

  // ------------------------------------------------------------ la recherche

  document.body.addEventListener("htmx:afterSwap", (evenement) => {
    if (evenement.target.id !== "resultats") return;

    const presents = new Set(
      [...document.querySelectorAll("#resultats .clameur")].map((f) => f.dataset.uuid)
    );
    // Une recherche sans resultat laisse le paysage entier et TOUTES les
    // etoiles pales : c'est la reponse juste a « rien ne correspond ». Le
    // relief, lui, ne bouge jamais — il decrit le corpus, pas le resultat.
    // / An empty search pales every star and keeps the whole landscape.
    for (const [uuid, etoile] of pastilles) {
      etoile.classList.toggle("pale", !presents.has(uuid));
    }

    // LES FICHES REVIENNENT NEUVES DU SERVEUR : teinte de la duree, et aucune
    // selection. Sans ces deux lignes, changer l'encodage puis taper une
    // lettre ramenerait toutes les pastilles a la couleur d'origine, et la
    // clameur en cours perdrait sa marque.
    // / Swapped cards come back server-fresh: recolour and re-mark them.
    recolorer();
    if (choisie) {
      document.getElementById(`clameur-${choisie}`)?.setAttribute("aria-current", "true");
    }
    // LA BARRE DE PROGRESSION SUIT LA FICHE NEUVE. Sans cela, chercher un mot
    // pendant une derive laissait la barre sur une fiche detachee du document,
    // et l'ecoute en cours n'avait plus rien de visible.
    // / The progress bar must follow the fresh card, or it writes into a
    //   detached element while the drift keeps playing.
    if (ficheEnDerive) marquerLaDerive(ficheEnDerive.dataset.uuid);
  });

  // --------------------------------------------------------- le bandeau mobile

  const panneauCiel = document.querySelector(".panneau-ciel");

  // DEUX SEUILS, ET NON UN SEUL : replier a 260 px et deployer a 200 px. Avec
  // un seuil unique, le changement de hauteur deplace la page, ce qui repasse
  // le seuil, et le bandeau bat entre ses deux etats.
  // / Hysteresis: one threshold makes the band oscillate.
  const SEUIL_DU_REPLI = 260;
  const SEUIL_DU_DEPLOIEMENT = 200;
  const FENETRE_REPLIEE = 420;

  let replie = false;
  let grand = false;
  let enAttente = false;

  const poignee = document.getElementById("poignee-ciel");

  poignee.addEventListener("click", () => {
    grand = !grand;
    // ON NE PEUT PAS ETRE A LA FOIS EN BANDEAU ET EN GRAND. Tant que la
    // poignee tient le grand format, le defilement ne replie plus : c'est
    // l'utilisateur qui a demande cette hauteur, pas la page.
    // / While the handle holds the tall state, scrolling stops folding.
    if (grand) replie = false;
    // QUITTER LE GRAND FORMAT OUBLIE LE DEPLACEMENT : on ne garde pas une
    // fenetre zoomee dans un bandeau de deux centimetres, ou plus rien ne
    // serait reconnaissable. / Leaving the tall state forgets the pan.
    vue = null;
    vueEntiere = null;
    // ET LES DOIGTS EN COURS AVEC. Toucher la poignee d'un second doigt
    // pendant un deplacement laissait un geste sans vue a manipuler, et le
    // mouvement suivant levait une erreur.
    // / Clear the fingers too: a gesture without a view throws.
    doigts.clear();
    depart = null;
    panneauCiel.classList.toggle("grand", grand);
    panneauCiel.classList.toggle("replie", replie);

    poignee.setAttribute("aria-expanded", String(grand));
    poignee.querySelector(".poignee-mot").textContent =
      grand ? poignee.dataset.reduire : poignee.dataset.agrandir;
    // Pas de `cadrer()` ici : la hauteur du panneau s'anime, et la mesure
    // prise maintenant serait celle d'avant. L'observateur ci-dessous le fera
    // quand la taille aura vraiment change.
    // / No cadrer() here: the panel height is still animating.
  });

  window.addEventListener("scroll", () => {
    if (!surMobile() || grand || enAttente) return;
    enAttente = true;
    requestAnimationFrame(() => {
      enAttente = false;
      const doitReplier = replie
        ? window.scrollY > SEUIL_DU_DEPLOIEMENT
        : window.scrollY > SEUIL_DU_REPLI;
      if (doitReplier === replie) return;
      replie = doitReplier;
      panneauCiel.classList.toggle("replie", replie);
      // Le cadrage attend l'observateur : la hauteur est en train de changer.
      // / The framing waits for the observer: the height is still moving.
    });
  }, { passive: true });

  function cadrer() {
    // UNE VUE DEPLACEE A LA MAIN PRIME SUR TOUT CADRAGE AUTOMATIQUE : on ne
    // ramene pas quelqu'un au point de depart parce qu'il a touche une etoile.
    // / A hand-moved view wins: we never yank it back.
    if (vue) {
      ecrireLaVue();
      poserLesEtiquettes();
      return;
    }
    if (!surMobile() || !replie) {
      svg.setAttribute("viewBox", `0 0 ${COTE} ${COTE}`);
    } else {
      /*
       * REPLIE, ON NE MONTRE PAS UN CIEL MINUSCULE : on cadre la zone autour
       * de l'etoile en cours. Et la fenetre prend le RATIO DU BANDEAU : une
       * fenetre carree dans un bandeau large et court serait ramenee a un
       * carre de la hauteur du bandeau — on aurait retreci le ciel au lieu de
       * le cadrer. / Collapsed, we frame the current star, at the band's ratio.
       */
      const centre = CORPUS.find((c) => c.uuid === choisie) || { x: 0.5, y: 0.5 };
      const cadre = svg.getBoundingClientRect();
      const largeur = FENETRE_REPLIEE;
      const hauteur = cadre.width ? largeur * (cadre.height / cadre.width) : largeur;
      const borne = (valeur, taille) => Math.max(0, Math.min(COTE - taille, valeur));
      const x = borne(centre.x * COTE - largeur / 2, largeur);
      const y = borne(centre.y * COTE - hauteur / 2, hauteur);
      svg.setAttribute(
        "viewBox",
        `${x.toFixed(0)} ${y.toFixed(0)} ${largeur.toFixed(0)} ${hauteur.toFixed(0)}`
      );
    }
    // L'echelle a change, donc la taille visee des etiquettes aussi.
    // / The scale changed, so the labels' target size did too.
    poserLesEtiquettes();
  }

  // --------------------------------------------- se deplacer dans la carte

  /*
   * DEPLACEMENT A UN DOIGT, ZOOM A DEUX, EN GRAND FORMAT SEULEMENT. Le CSS
   * ne nous donne le geste que la (`touch-action: none` sur `.grand`) : ailleurs
   * le doigt doit continuer de faire defiler la page.
   * / One finger pans, two pinch, and only in the tall state.
   */
  const ZOOM_MAXIMAL = 4;          // au-dela, on ne voit plus de paysage
  const GLISSEMENT_MINIMAL = 8;    // en pixels : en dessous, c'est un appui

  let vue = null;          // {x, y, largeur, hauteur} des qu'on touche la carte
  let vueEntiere = null;   // le cadrage d'ou l'on part : on ne dezoome pas plus
  let aGlisse = false;
  let depart = null;
  const doigts = new Map();

  const milieu = (points) => ({
    x: points.reduce((somme, p) => somme + p.x, 0) / points.length,
    y: points.reduce((somme, p) => somme + p.y, 0) / points.length,
  });

  const ecartEntre = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

  function ecrireLaVue() {
    // UNE DECIMALE, ET NON ZERO : a fort grossissement une unite vaut plus
    // d'un pixel et demi, et arrondir a l'entier faisait sauter la carte d'un
    // cran a chaque image. / One decimal: at full zoom a unit is over a pixel.
    svg.setAttribute(
      "viewBox",
      `${vue.x.toFixed(1)} ${vue.y.toFixed(1)} `
      + `${vue.largeur.toFixed(1)} ${vue.hauteur.toFixed(1)}`
    );
  }

  function memoriserLeDepart() {
    const points = [...doigts.values()];
    const matrice = svg.getScreenCTM();
    depart = {
      vue: { ...vue },
      milieu: milieu(points),
      ecart: points.length >= 2 ? ecartEntre(points[0], points[1]) : 0,
      /*
       * L'ECHELLE SE LIT DANS LA MATRICE, ET SE FIGE POUR TOUT LE GESTE.
       * Sous `preserveAspectRatio`, le dessin est mis a l'echelle par le PLUS
       * PETIT des deux rapports : `largeur / largeurDuCadre` est faux des que
       * le panneau n'a pas le rapport de la vue, et le paysage n'avance alors
       * ni a la vitesse ni dans la proportion du doigt. Figee au depart, elle
       * evite en plus qu'un pincement en cours ne change la conversion sous
       * nos pieds.
       * / Read from the matrix, frozen for the gesture.
       */
      parPixel: matrice ? 1 / matrice.a : 1,
    };
  }

  function bornerLaVue() {
    // ON NE SORT JAMAIS DU CADRAGE DE DEPART, ni en zoom ni en deplacement :
    // sans cette borne, on derivait dans le vide, hors du ciel, sans rien pour
    // se raccrocher. La vue garde aussi le RAPPORT du cadrage de depart, sinon
    // `preserveAspectRatio` ajouterait ses propres bandes et fausserait
    // l'echelle. / We never leave the starting frame, and we keep its ratio.
    const rapport = vueEntiere.hauteur / vueEntiere.largeur;
    vue.largeur = Math.min(
      vueEntiere.largeur,
      Math.max(vueEntiere.largeur / ZOOM_MAXIMAL, vue.largeur)
    );
    vue.hauteur = vue.largeur * rapport;

    const dans = (valeur, taille, debut, etendue) =>
      Math.max(debut, Math.min(valeur, debut + etendue - taille));
    vue.x = dans(vue.x, vue.largeur, vueEntiere.x, vueEntiere.largeur);
    vue.y = dans(vue.y, vue.hauteur, vueEntiere.y, vueEntiere.hauteur);
  }

  svg.addEventListener("pointerdown", (evenement) => {
    if (!surMobile() || !grand) return;
    svg.setPointerCapture(evenement.pointerId);
    doigts.set(evenement.pointerId, { x: evenement.clientX, y: evenement.clientY });
    if (doigts.size === 1) aGlisse = false;
    if (!vue) {
      /*
       * LA REFERENCE EST LA ZONE REELLEMENT VISIBLE, ET NON LE `viewBox`.
       * Sous `preserveAspectRatio`, un viewBox carre dans un panneau en
       * hauteur laisse deux bandes de papier vide : le prendre pour reference
       * gardait ce vide a tous les niveaux de zoom, et le grossissement ne
       * remplissait jamais l'ecran. On convertit donc les coins du panneau en
       * unites du ciel : a l'ecran c'est identique — rien ne saute — mais la
       * reference a enfin le rapport du cadre.
       * / The visible area, not the viewBox: a square viewBox in a tall panel
       *   keeps empty bands at every zoom level.
       */
      const matrice = svg.getScreenCTM();
      const cadre = svg.getBoundingClientRect();
      if (!matrice) return;
      const coin = new DOMPoint(cadre.left, cadre.top).matrixTransform(matrice.inverse());
      vueEntiere = {
        x: coin.x, y: coin.y,
        largeur: cadre.width / matrice.a, hauteur: cadre.height / matrice.a,
      };
      vue = { ...vueEntiere };
    }
    memoriserLeDepart();
  });

  svg.addEventListener("pointermove", (evenement) => {
    if (!doigts.has(evenement.pointerId) || !depart) return;
    doigts.set(evenement.pointerId, { x: evenement.clientX, y: evenement.clientY });

    const points = [...doigts.values()];
    const centre = milieu(points);

    if (points.length >= 2 && depart.ecart > 0) {
      const facteur = depart.ecart / (ecartEntre(points[0], points[1]) || 1);
      const largeur = depart.vue.largeur * facteur;
      const hauteur = depart.vue.hauteur * facteur;
      // Le centre de l'ecran reste fixe : la carte grandit sur place au lieu
      // de fuir vers un coin. / The screen centre stays put.
      vue.x = depart.vue.x + (depart.vue.largeur - largeur) / 2;
      vue.y = depart.vue.y + (depart.vue.hauteur - hauteur) / 2;
      vue.largeur = largeur;
      vue.hauteur = hauteur;
    } else {
      // Le paysage suit le doigt : on deplace la fenetre a l'oppose du geste.
      // / The landscape follows the finger: the window moves the other way.
      vue.x = depart.vue.x - (centre.x - depart.milieu.x) * depart.parPixel;
      vue.y = depart.vue.y - (centre.y - depart.milieu.y) * depart.parPixel;
    }

    if (ecartEntre(centre, depart.milieu) > GLISSEMENT_MINIMAL) aGlisse = true;

    bornerLaVue();
    // On ecrit le cadrage SANS replacer les etiquettes : quinze mesures de
    // texte par image rendraient le geste poussif. Elles se replacent au
    // relachement. / No label layout mid-gesture.
    ecrireLaVue();
  });

  function relacher(evenement) {
    if (!doigts.delete(evenement.pointerId)) return;
    if (doigts.size) { memoriserLeDepart(); return; }   // un doigt sur deux levé
    depart = null;
    cadrer();     // l'echelle a change : les etiquettes se replacent ici
  }
  svg.addEventListener("pointerup", relacher);
  svg.addEventListener("pointercancel", relacher);
  // UN DOIGT PERDU RESTERAIT DANS LA LISTE. Un passage a une autre
  // application, une alerte du systeme, et le navigateur ne livre parfois que
  // `lostpointercapture` : le geste suivant devenait un pincement fantome.
  // / A lost pointer would linger and turn the next gesture into a pinch.
  svg.addEventListener("lostpointercapture", relacher);

  /*
   * PAS DE DOUBLE-TOUCHER POUR REMONTER LA PAGE. Il entrait en concurrence
   * avec le defilement que la selection d'une etoile declenche, et avec le
   * double-tap dont on se sert pour explorer la carte : deux gestes pour deux
   * intentions contraires, au meme endroit. La poignee suffit a retrouver le
   * ciel entier.
   * / No double-tap to scroll up: it fought the selection's own scroll.
   */

  /*
   * ON OBSERVE LA TAILLE DU CIEL, ON N'ECOUTE PAS `resize`.
   * La hauteur du panneau s'anime sur un quart de seconde : cadrer au moment
   * du clic mesurait la hauteur d'AVANT, et la fenetre repliee recevait le
   * rapport du format deploye — `preserveAspectRatio` la calait alors sur la
   * hauteur en laissant deux bandes vides, et le ciel paraissait rétréci.
   * Rien ne le recalculait ensuite. L'observateur couvre la fin de la
   * transition, la rotation de l'appareil, l'apparition de la barre d'adresse
   * et le redimensionnement du bureau — un seul mecanisme au lieu de quatre.
   * / We observe the sky's size: cadrer() during the height transition measured
   *   the old height, and nothing recomputed it afterwards.
   */
  new ResizeObserver(() => {
    // Revenu sur le bureau, une vue zoomee ne se quitterait plus : la poignee
    // qui l'annule n'y existe pas. / On a desktop the handle is gone, so a
    // zoomed view would be stuck.
    if (!surMobile()) { vue = null; vueEntiere = null; }
    cadrer();
  }).observe(svg);

  // ---------------------------------------------------------------- la derive

  const bouton = document.getElementById("deriver");
  const annonce = document.getElementById("annonce-derive");
  const entendues = new Set();
  let deriveActive = false;
  let trace = null;
  let points = [];
  let ficheEnDerive = null;

  function marquerLaDerive(uuid) {
    oublierLaDerive();
    ficheEnDerive = document.getElementById(`clameur-${uuid}`);
    ficheEnDerive?.classList.add("en-derive");
  }

  function oublierLaDerive() {
    if (!ficheEnDerive) return;
    ficheEnDerive.classList.remove("en-derive");
    ficheEnDerive.style.removeProperty("--avancement");
    ficheEnDerive = null;
  }

  // LA SEULE PROGRESSION VISIBLE DE LA DERIVE. Le lecteur qui joue n'est pas
  // dans la page : la barre des fiches reste a zero, puisqu'elles ne jouent
  // pas. On alimente donc la notre avec l'avancement reel du son.
  // / The playing element is not in the page; this is the only visible progress.
  lecteurDeLaDerive.addEventListener("timeupdate", () => {
    const duree = lecteurDeLaDerive.duration;
    if (!ficheEnDerive || !duree || !isFinite(duree)) return;
    ficheEnDerive.style.setProperty(
      "--avancement", (lecteurDeLaDerive.currentTime / duree).toFixed(3)
    );
  });

  function fichesDeLaListe() {
    /*
     * SEULEMENT CE QUI EST DANS LA LISTE : c'est la que vivent l'URL de
     * l'audio et la cible du defilement. Une recherche filtree devient donc
     * une derive thematique, ce qui est un usage et non un defaut.
     * / Only what the list holds: a filtered search becomes a themed drift.
     */
    const presentes = new Map();
    for (const fiche of document.querySelectorAll("#resultats .clameur")) {
      presentes.set(fiche.dataset.uuid, fiche);
    }
    return presentes;
  }

  function laPlusProche(depuis, presentes) {
    let trouvee = null;
    let distance = Infinity;
    for (const clameur of CORPUS) {
      if (entendues.has(clameur.uuid) || !presentes.has(clameur.uuid)) continue;
      const ecart = Math.hypot(clameur.x - depuis.x, clameur.y - depuis.y);
      if (ecart < distance) { distance = ecart; trouvee = clameur; }
    }
    return trouvee;
  }

  function jouer(clameur, presentes) {
    const source = presentes.get(clameur.uuid)?.querySelector("audio source");
    if (!source || !source.src) { arreterLaDerive(); return; }

    entendues.add(clameur.uuid);
    lecteurDeLaDerive.src = source.src;
    lecteurDeLaDerive.play().catch(() => arreterLaDerive());

    choisir(clameur.uuid, "ciel");
    marquerLaDerive(clameur.uuid);
    compterUneEcoute(clameur.uuid);
    if (annonce) annonce.textContent = clameur.titre;

    points.push(`${(clameur.x * COTE).toFixed(0)},${(clameur.y * COTE).toFixed(0)}`);
    if (trace) trace.setAttribute("points", points.join(" "));
  }

  function arreterLaDerive() {
    if (!deriveActive) return;
    deriveActive = false;
    lecteurDeLaDerive.pause();
    oublierLaDerive();
    bouton.textContent = bouton.dataset.depart;
    bouton.setAttribute("aria-pressed", "false");
    trace?.remove();
    trace = null;
    points = [];
  }

  bouton.addEventListener("click", () => {
    if (deriveActive) { arreterLaDerive(); return; }

    const presentes = fichesDeLaListe();
    const depart = CORPUS.find((c) => c.uuid === choisie && presentes.has(c.uuid))
                || CORPUS.find((c) => presentes.has(c.uuid));
    if (!depart) return;

    deriveActive = true;
    entendues.clear();
    bouton.textContent = bouton.dataset.arret;
    bouton.setAttribute("aria-pressed", "true");
    trace = document.createElementNS(ESPACE, "polyline");
    trace.setAttribute("class", "trace");
    document.getElementById("traces").appendChild(trace);
    points = [];

    jouer(depart, presentes);
  });

  /*
   * UN SEUL LECTEUR POUR TOUTE LA DERIVE. Sur iOS, `play()` sur un element
   * qu'aucun doigt n'a touche est refuse : en changeant la source d'un lecteur
   * deja debloque par l'appui sur le bouton, l'enchainement passe.
   * / iOS refuses play() on an element no gesture has unlocked.
   */
  lecteurDeLaDerive.addEventListener("ended", () => {
    if (!deriveActive) return;
    const presentes = fichesDeLaListe();
    const courante = CORPUS.find((c) => c.uuid === choisie);
    const prochaine = courante && laPlusProche(courante, presentes);
    if (!prochaine) { arreterLaDerive(); return; }
    jouer(prochaine, presentes);
  });

  // ---------------------------------------------------------------- l'amorcage

  dessinerLeRelief();
  dessinerLesEtoiles();
  recolorer();
  poserLesEtiquettes();

  // Le bouton actif doit refleter le choix retenu en memoire, sinon la page
  // colore par la duree tout en montrant « Voix » enfonce.
  // / The pressed button must match the remembered choice.
  for (const bascule of document.querySelectorAll("#choix-couleur button")) {
    bascule.setAttribute("aria-pressed", String(bascule.dataset.encodage === encodage));
  }
})();
