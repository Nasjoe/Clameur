/*
 * La constellation : deux ecrans synchronises.
 * / The constellation: two synchronised views.
 *
 * LES DONNEES VIENNENT DU DOM, pas d'un JSON. La liste est rendue par Django
 * pour que HTMX puisse y remplacer une transcription par swap OOB quand elle
 * arrive : on ne peut pas viser un element que le serveur n'a jamais rendu.
 * Le ciel se construit donc en lisant les fiches deja en place.
 * / Data comes from the DOM: Django renders the list so HTMX can OOB-swap into it.
 */

(function () {
  "use strict";

  const liste = document.getElementById("liste");
  const ciel = document.getElementById("ciel");
  const ESPACE_SVG = "http://www.w3.org/2000/svg";
  const COTE = 1000;

  const fiches = new Map();
  const pastilles = new Map();
  let choisie = null;

  // ---------------------------------------------------------------- lecture

  function lireLesFiches() {
    liste.querySelectorAll(".clameur").forEach((fiche) => {
      fiches.set(fiche.dataset.uuid, fiche);
    });
  }

  function construireLeCiel() {
    const fragment = document.createDocumentFragment();
    fiches.forEach((fiche, uuid) => {
      const teinte = fiche.dataset.teinte;
      const ecoutes = Number(fiche.dataset.ecoutes || 0);

      const pastille = document.createElementNS(ESPACE_SVG, "circle");
      pastille.setAttribute("cx", Number(fiche.dataset.x) * COTE);
      pastille.setAttribute("cy", Number(fiche.dataset.y) * COTE);
      // Une clameur plus ecoutee brille plus fort. La racine carree evite
      // qu'une seule tres ecoutee ecrase tout le ciel.
      // / Square root, so one popular capsule does not swallow the sky.
      pastille.setAttribute("r", 6 + Math.min(10, Math.sqrt(ecoutes) * 2.2));
      // Meme registre que les bordures de la reference : clair et peu sature,
      // pour tenir sur un papier brun sans crier.
      // / Same register as the reference borders: light, low chroma.
      pastille.setAttribute("fill", `oklch(0.74 0.13 ${teinte})`);
      pastille.setAttribute("opacity", "0.78");
      pastille.setAttribute("tabindex", "0");
      pastille.setAttribute("role", "button");

      const nom = fiche.querySelector(".clameur-nom").textContent.trim();
      pastille.setAttribute("aria-label", nom);
      const infobulle = document.createElementNS(ESPACE_SVG, "title");
      infobulle.textContent = nom;
      pastille.appendChild(infobulle);

      pastille.addEventListener("click", () => choisir(uuid, "ciel", true));
      pastille.addEventListener("keydown", (evenement) => {
        if (evenement.key === "Enter" || evenement.key === " ") {
          evenement.preventDefault();
          choisir(uuid, "ciel", true);
        }
      });

      pastilles.set(uuid, pastille);
      fragment.appendChild(pastille);
    });
    ciel.appendChild(fragment);
  }

  // ------------------------------------------------------------- accordeon

  function replierLesAutres(sauf) {
    /*
     * UNE SEULE FICHE DEPLIEE A LA FOIS, et ce n'est pas qu'une question de
     * gout : chaque depliant ouvert allonge la liste et decale l'`offsetTop`
     * de toutes les fiches en dessous. Le defilement declenche par une etoile
     * viserait alors une position perimee et tomberait a cote.
     * / One card open at a time: open cards shift every offsetTop below them,
     *   which would make the star-driven scroll land in the wrong place.
     */
    liste.querySelectorAll("details.depliant[open]").forEach((depliant) => {
      if (depliant !== sauf) depliant.open = false;
    });
  }

  // L'evenement `toggle` ne remonte pas : on ecoute en phase de capture.
  // / The `toggle` event does not bubble; listen during capture.
  liste.addEventListener("toggle", (evenement) => {
    const depliant = evenement.target;
    if (depliant.matches && depliant.matches("details.depliant") && depliant.open) {
      replierLesAutres(depliant);
    }
  }, true);

  // ------------------------------------------------------------ defilement

  let animationEnCours = null;

  function defilerVers(cible) {
    /*
     * ON ANIME NOUS-MEMES. `scrollTo({behavior:"smooth"})` et
     * `scroll-behavior: smooth` en CSS ne s'executent pas dans tous les
     * contextes : mesure faite, un defilement anime restait a zero apres deux
     * secondes et demie, sans erreur, la ou `behavior:"instant"` marchait. Or
     * ce defilement EST la synchronisation : s'il ne se produit pas, cliquer
     * une etoile ne mene nulle part.
     * / Native smooth scrolling silently did nothing in a measured case.
     */
    const depart = liste.scrollTop;
    const maximum = liste.scrollHeight - liste.clientHeight;
    const arrivee = Math.max(0, Math.min(cible, maximum));
    const distance = arrivee - depart;
    if (Math.abs(distance) < 2) return;

    if (animationEnCours) cancelAnimationFrame(animationEnCours);

    // Onglet masque : requestAnimationFrame est SUSPENDU (mesure : zero image
    // en sept cents millisecondes). Sans ce saut, un visiteur qui clique puis
    // change d'onglet retrouverait la liste figee a mi-chemin.
    // / A hidden tab suspends rAF entirely: jump instead of animating.
    if (document.hidden) {
      liste.scrollTop = arrivee;
      return;
    }

    const duree = Math.min(650, 220 + Math.abs(distance) * 0.25);
    const debut = performance.now();

    function pas(maintenant) {
      const avancement = Math.min(1, (maintenant - debut) / duree);
      const courbe = avancement < 0.5
        ? 4 * avancement ** 3
        : 1 - Math.pow(-2 * avancement + 2, 3) / 2;
      liste.scrollTop = depart + distance * courbe;
      if (avancement < 1) animationEnCours = requestAnimationFrame(pas);
    }
    animationEnCours = requestAnimationFrame(pas);
  }

  // ------------------------------------------------------------- selection

  function choisir(uuid, origine, lancerLaLecture) {
    const fiche = fiches.get(uuid);
    if (!fiche) return;

    if (choisie && choisie !== uuid) {
      const ancienne = fiches.get(choisie);
      if (ancienne) ancienne.setAttribute("aria-current", "false");
      const anciennePastille = pastilles.get(choisie);
      if (anciennePastille) {
        anciennePastille.classList.remove("choisie");
        anciennePastille.setAttribute("opacity", "0.78");
      }
    }
    choisie = uuid;

    fiche.setAttribute("aria-current", "true");
    const pastille = pastilles.get(uuid);
    if (pastille) {
      pastille.classList.add("choisie");
      pastille.setAttribute("opacity", "1");
    }

    // On ne defile que si le clic vient du ciel : venant de la liste,
    // l'element est deja sous les yeux et le deplacer le ferait fuir.
    // / Only scroll when the click came from the sky.
    if (origine === "ciel") {
      // Replier D'ABORD : une fiche ouverte plus haut dans la liste fausserait
      // l'offsetTop qu'on s'apprete a mesurer.
      // / Collapse first, or the offsetTop we are about to read is stale.
      replierLesAutres(null);
      defilerVers(fiche.offsetTop - liste.clientHeight / 2 + fiche.offsetHeight / 2);
    }
    if (lancerLaLecture) {
      const lecteur = fiche.querySelector("audio");
      if (lecteur) lecteur.play().catch(() => {
        // Un navigateur peut refuser la lecture automatique : le lecteur
        // reste visible et le visiteur appuie lui-meme.
        // / Autoplay may be refused; the visible player is the fallback.
      });
    }
  }

  // --------------------------------------------------------------- ecoutes

  function brancherLesLecteurs() {
    liste.addEventListener("play", (evenement) => {
      const lecteur = evenement.target;
      if (!lecteur.matches || !lecteur.matches("audio")) return;

      // Un seul son a la fois : cent lecteurs qui se chevauchent seraient
      // inecoutables. / One sound at a time.
      liste.querySelectorAll("audio").forEach((autre) => {
        if (autre !== lecteur && !autre.paused) autre.pause();
      });

      const uuid = lecteur.dataset.uuid;
      choisir(uuid, "liste", false);
      compterUneEcoute(uuid);
    }, true);  // capture : l'evenement `play` ne remonte pas naturellement
  }

  const dejaComptees = new Set();

  function compterUneEcoute(uuid) {
    if (dejaComptees.has(uuid)) return;   // une ecoute par page, pas par pause
    dejaComptees.add(uuid);
    fetch(window.URL_ECOUTE.replace("00000000-0000-0000-0000-000000000000", uuid), {
      method: "POST",
      headers: { "X-CSRFToken": window.JETON_CSRF },
    }).catch(() => {});
  }

  // ----------------------------------------------------------------- clics

  liste.addEventListener("click", (evenement) => {
    const bouton = evenement.target.closest("[data-choisir]");
    if (bouton) choisir(bouton.dataset.choisir, "liste", false);
  });

  /*
   * Les <script> arrivant par WebSocket ne sont JAMAIS executes par HTMX :
   * c'est une decision de securite de l'extension. Tout ce qui doit suivre un
   * swap se branche donc ici.
   * / HTMX never runs <script> received over its ws extension.
   */
  document.body.addEventListener("htmx:wsAfterMessage", () => {
    // La transcription remplacee ne change ni la position ni la couleur de
    // l'etoile : il n'y a rien a reconstruire dans le ciel. On se contente de
    // reprendre la reference de la fiche, que le swap OOB a pu recreer.
    // / An incoming transcription changes no star; just refresh our references.
    lireLesFiches();
  });

  // ------------------------------------------------------------ invitation

  const dialogue = document.getElementById("dialogue-invitation");
  if (dialogue) {
    // `showModal` (et non `show`) : c'est lui qui pose le fond, piege le
    // clavier dans la boite et rend Echap fonctionnel, sans une ligne de plus.
    // / showModal, not show: it gives the backdrop, focus trap and Escape.
    document.getElementById("bouton-inviter")
      .addEventListener("click", () => dialogue.showModal());
    document.getElementById("fermer-invitation")
      .addEventListener("click", () => dialogue.close());

    // Un clic hors de la boite la ferme aussi. L'evenement vise alors le
    // <dialog> lui-meme, jamais l'un de ses enfants.
    // / A click on the backdrop targets the dialog itself, never a child.
    dialogue.addEventListener("click", (evenement) => {
      if (evenement.target === dialogue) dialogue.close();
    });
  }

  lireLesFiches();
  construireLeCiel();
  brancherLesLecteurs();
})();
