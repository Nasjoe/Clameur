/*
 * Enregistreur de clameur. JS vanilla, sans dependance.
 * / Clameur recorder. Vanilla JS, no dependency.
 *
 * DEUX PRINCIPES :
 *  - la reecoute se fait sur le blob LOCAL, jamais sur le fichier remonte :
 *    instantane, et insensible a un mauvais reseau ;
 *  - l'audio part des l'arret, avant la saisie du pseudo : le temps de frappe
 *    sert a l'upload, et rien n'est perdu si l'onglet se ferme.
 * / Playback from the local blob; upload starts as soon as recording stops.
 *
 * DEUX SOURCES, UN SEUL PARCOURS : le micro, ou un fichier audio deja pret.
 * Les deux aboutissent a `accueillirLAudio`, et tout ce qui suit est commun.
 * / Two sources, one path: both end in accueillirLAudio.
 */

(function () {
  "use strict";

  const config = window.CLAMEUR;

  // Quand la borne est fermee, le gabarit ne rend aucun bouton : on sort avant
  // d'essayer de leur attacher quoi que ce soit. Sans cela, tout visiteur de
  // la page recoit une TypeError, et tout code ajoute plus bas ne s'execute
  // jamais sur cette page.
  // / A closed borne renders no buttons: bail out before wiring anything.
  if (!document.getElementById("bouton-demarrer")) return;
  const ecran = {
    accueil: document.getElementById("etape-accueil"),
    enregistrement: document.getElementById("etape-enregistrement"),
    formulaire: document.getElementById("etape-formulaire"),
    fin: document.getElementById("etape-fin"),
  };

  let enregistreur = null;
  let morceaux = [];
  let blobLocal = null;
  let nomDuFichier = "";
  let dureeAnnoncee = 0;
  let uuidCapsule = null;
  let debutEnMs = 0;
  let minuterieChrono = null;
  let verrouEcran = null;
  let contexteDuDirect = null;
  let boucleDuDirect = null;
  let niveauxDeLaReecoute = [];
  let dureeDeLaReecoute = 0;

  // UNE BARRE D'ONDE EN DIRECT TOUTES LES 80 MS : assez vite pour que la voix
  // se voie bouger, assez lent pour qu'une phrase tienne a l'ecran.
  // / One live bar every 80 ms: the voice visibly moves, a sentence fits.
  const DUREE_D_UNE_BARRE_MS = 80;
  const PAS_DES_BARRES_PX = 5;
  // Sous -60 dB, la barre est a plat. Une echelle en decibels, et non
  // lineaire : la voix calme reste visible, et seul un micro coupe (des
  // zeros purs) dessine une ligne parfaitement plate.
  // / Decibel scale: quiet speech stays visible, only a muted mic is flat.
  const PLANCHER_EN_DECIBELS = -60;
  // Au-dela, decoder le fichier pour dessiner son onde couterait trop de
  // memoire au telephone (un fichier depose peut durer des heures). On
  // renonce a l'onde, pas a la reecoute.
  // / Above this, decoding would exhaust a phone's memory: no waveform then.
  const TAILLE_MAX_POUR_DESSINER_L_ONDE = 25 * 1024 * 1024;

  function montrer(nom) {
    Object.entries(ecran).forEach(([cle, section]) => {
      if (section) section.hidden = cle !== nom;
    });
  }

  // LES DEUX PORTES DE L'ACCUEIL SE FERMENT DES LE PREMIER APPUI. Pendant que
  // le telephone demande le micro, un second appui lancait un second
  // enregistreur dans le meme tampon — audio corrompu, micro jamais rendu — et
  // « Envoyer un fichier » partait par-dessus l'enregistrement.
  // / Both buttons lock on the first tap: a double tap started two recorders.
  function verrouillerLAccueil(verrou) {
    document.getElementById("bouton-demarrer").disabled = verrou;
    document.getElementById("bouton-fichier").disabled = verrou;
  }

  function secondesEcoulees() {
    return Math.floor((Date.now() - debutEnMs) / 1000);
  }

  function rafraichirChrono() {
    const total = secondesEcoulees();
    const minutes = Math.floor(total / 60);
    const secondes = String(total % 60).padStart(2, "0");
    document.getElementById("chrono").textContent = `${minutes}:${secondes}`;
  }

  /*
   * L'ECRAN RESTE ALLUME PENDANT L'ENREGISTREMENT.
   * / The screen stays on while recording.
   *
   * LE BUG DU 2026-10-01. Un Galaxy S23, dans le navigateur integre de
   * Facebook, a enregistre deux clameurs muettes passe 35 s. Le fichier
   * envoye contenait des zeros purs : la voix s'arretait net, en pleine
   * phrase. 35 s, c'est la mise en veille de l'ecran (30 s) plus son
   * assombrissement. Personne ne touche son ecran en parlant. Ecran eteint,
   * Android coupe le micro de la page. MediaRecorder, lui, continue
   * d'encoder du silence, et le chrono continue de tourner.
   *
   * Le verrou saute de lui-meme quand la page passe en arriere-plan : on le
   * redemande a son retour (voir l'ecouteur `visibilitychange` en bas).
   * Sans Wake Lock — c'est le cas des navigateurs integres — on previent la
   * personne : c'est tout ce qu'on peut faire.
   * / Without Wake Lock (in-app browsers), we warn the visitor instead.
   */
  async function garderLEcranAllume() {
    const avisVeille = document.getElementById("avis-veille");
    if (!("wakeLock" in navigator)) {
      avisVeille.hidden = false;
      return;
    }
    try {
      verrouEcran = await navigator.wakeLock.request("screen");
      avisVeille.hidden = true;
    } catch (erreur) {
      // Refus possible : batterie faible, mode economie d'energie.
      // / Can be refused: low battery, power saving.
      avisVeille.hidden = false;
      return;
    }
    // L'enregistrement a pu s'arreter pendant qu'on attendait le verrou.
    // / Recording may have stopped while we waited for the lock.
    const enregistrementEnCours = enregistreur && enregistreur.state === "recording";
    if (!enregistrementEnCours) rendreLEcran();
  }

  function rendreLEcran() {
    if (verrouEcran) verrouEcran.release().catch(() => {});
    verrouEcran = null;
  }

  /*
   * Dessine des barres d'onde, centrees, de droite a gauche.
   * / Draws centred waveform bars, right-aligned.
   *
   * `niveaux` : des valeurs de 0 a 1, une par barre.
   * `nombreDePlaces` : combien de barres tiennent dans la largeur. En direct,
   *   il y en a plus que de niveaux au debut : l'onde entre par la droite.
   * `avancement` : de 0 a 1, la part deja lue, en ambre ; le reste est terne.
   * Un niveau nul dessine quand meme un trait : c'est la ligne plate qui doit
   * se voir.
   * / A zero level still draws a line: the flat line must be visible.
   */
  function dessinerLesBarres(canevas, niveaux, nombreDePlaces, avancement) {
    const densite = window.devicePixelRatio || 1;
    const largeur = canevas.clientWidth;
    const hauteur = canevas.clientHeight;
    // La resolution suit la taille affichee : sinon le trait est flou.
    // / Resolution follows the displayed size, or the bars blur.
    if (canevas.width !== Math.round(largeur * densite)) canevas.width = Math.round(largeur * densite);
    if (canevas.height !== Math.round(hauteur * densite)) canevas.height = Math.round(hauteur * densite);

    const pinceau = canevas.getContext("2d");
    pinceau.setTransform(densite, 0, 0, densite, 0, 0);
    pinceau.clearRect(0, 0, largeur, hauteur);

    const styles = getComputedStyle(document.documentElement);
    const pas = largeur / Math.max(1, nombreDePlaces);
    const epaisseur = Math.max(1, pas * 0.6);

    for (let index = 0; index < niveaux.length; index++) {
      const dejaLue = (index + 0.5) / niveaux.length <= avancement;
      // Couleur de repli D'ABORD : un navigateur qui ne comprend pas oklch()
      // ignore l'affectation suivante et garde la couleur de repli, au lieu
      // de peindre en noir sur le fond sombre.
      // / Fallback colour first: a browser without oklch() keeps it.
      pinceau.fillStyle = dejaLue ? "#f0b54f" : "#9b9389";
      pinceau.fillStyle = styles.getPropertyValue(dejaLue ? "--color-ambre" : "--color-ink-tenu").trim();

      const hauteurDeLaBarre = Math.max(2, niveaux[index] * hauteur);
      const gauche = largeur - (niveaux.length - index) * pas;
      pinceau.fillRect(gauche, (hauteur - hauteurDeLaBarre) / 2, epaisseur, hauteurDeLaBarre);
    }
  }

  // Un pic d'amplitude (0 a 1) devient une hauteur de barre (0 a 1).
  // / Converts a peak amplitude into a bar height, on a decibel scale.
  function niveauDuPic(pic) {
    if (pic <= 0) return 0;
    const decibels = 20 * Math.log10(pic);
    return Math.min(1, Math.max(0, (decibels - PLANCHER_EN_DECIBELS) / -PLANCHER_EN_DECIBELS));
  }

  function creerUnContexteAudio() {
    const ContexteAudio = window.AudioContext || window.webkitAudioContext;
    return ContexteAudio ? new ContexteAudio() : null;
  }

  /*
   * L'onde en direct, lue sur le flux du micro.
   * / The live waveform, read from the microphone stream.
   *
   * L'analyseur est une BRANCHE A COTE de MediaRecorder : il lit le meme
   * flux, sans rien y changer. Il n'est relie a aucune sortie : rien ne
   * sort du haut-parleur, pas d'effet Larsen.
   * / A side branch: same stream, nothing changed, nothing to the speaker.
   */
  function brancherLOndeEnDirect(contexte, flux) {
    if (!contexte) return;
    contexteDuDirect = contexte;
    const analyseur = contexte.createAnalyser();
    analyseur.fftSize = 2048;
    contexte.createMediaStreamSource(flux).connect(analyseur);

    const canevas = document.getElementById("onde-direct");
    const echantillons = new Float32Array(analyseur.fftSize);
    const niveauxVisibles = [];
    let picDeLaBarre = 0;
    let debutDeLaBarre = performance.now();

    function dessinerUneImage(maintenant) {
      analyseur.getFloatTimeDomainData(echantillons);
      for (const echantillon of echantillons) {
        picDeLaBarre = Math.max(picDeLaBarre, Math.abs(echantillon));
      }
      if (maintenant - debutDeLaBarre >= DUREE_D_UNE_BARRE_MS) {
        niveauxVisibles.push(niveauDuPic(picDeLaBarre));
        picDeLaBarre = 0;
        debutDeLaBarre = maintenant;
      }
      const nombreDePlaces = Math.max(1, Math.floor(canevas.clientWidth / PAS_DES_BARRES_PX));
      while (niveauxVisibles.length > nombreDePlaces) niveauxVisibles.shift();

      dessinerLesBarres(canevas, niveauxVisibles, nombreDePlaces, 1);
      boucleDuDirect = requestAnimationFrame(dessinerUneImage);
    }
    boucleDuDirect = requestAnimationFrame(dessinerUneImage);
  }

  function debrancherLOndeEnDirect() {
    cancelAnimationFrame(boucleDuDirect);
    if (contexteDuDirect) contexteDuDirect.close().catch(() => {});
    contexteDuDirect = null;
  }

  /*
   * L'onde de la reecoute, tiree du fichier LUI-MEME.
   * / The playback waveform, computed from the file itself.
   *
   * On decode le blob qui part au serveur, et non ce que l'analyseur a vu en
   * direct : si l'enregistrement a un trou, c'est ici qu'on le voit, avant
   * de publier. Sans Web Audio, fichier trop lourd ou format que le
   * navigateur ne sait pas decoder : pas d'onde, la reecoute reste.
   * / Decodes the uploaded blob: a gap shows before publishing.
   */
  async function dessinerLOndeDeLaReecoute(blob) {
    const canevas = document.getElementById("onde-reecoute");
    if (blob.size > TAILLE_MAX_POUR_DESSINER_L_ONDE) return;
    const contexte = creerUnContexteAudio();
    if (!contexte) return;

    let son;
    try {
      son = await contexte.decodeAudioData(await blob.arrayBuffer());
    } catch (erreur) {
      return;
    } finally {
      contexte.close().catch(() => {});
    }

    // Visible AVANT de mesurer : un element cache a une largeur nulle.
    // / Shown before measuring: a hidden element has zero width.
    canevas.hidden = false;
    const nombreDeBarres = Math.max(1, Math.floor(canevas.clientWidth / PAS_DES_BARRES_PX));
    const echantillons = son.getChannelData(0);
    const echantillonsParBarre = Math.max(1, Math.floor(echantillons.length / nombreDeBarres));

    niveauxDeLaReecoute = [];
    for (let barre = 0; barre < nombreDeBarres; barre++) {
      const debut = barre * echantillonsParBarre;
      const fin = Math.min(echantillons.length, debut + echantillonsParBarre);
      let pic = 0;
      for (let index = debut; index < fin; index++) {
        pic = Math.max(pic, Math.abs(echantillons[index]));
      }
      niveauxDeLaReecoute.push(niveauDuPic(pic));
    }
    // LA DUREE DU SON DECODE, PAS CELLE DU LECTEUR. Le webm de MediaRecorder
    // n'annonce pas sa duree : Chrome y lit `Infinity`.
    // / Chrome reports Infinity for a MediaRecorder webm: use the decoded one.
    dureeDeLaReecoute = son.duration;
    redessinerLaReecoute();
  }

  function redessinerLaReecoute() {
    if (!niveauxDeLaReecoute.length) return;
    const lecteur = document.getElementById("reecoute");
    const avancement = dureeDeLaReecoute ? Math.min(1, lecteur.currentTime / dureeDeLaReecoute) : 0;
    dessinerLesBarres(
      document.getElementById("onde-reecoute"),
      niveauxDeLaReecoute,
      niveauxDeLaReecoute.length,
      avancement
    );
  }

  // Un toucher sur l'onde deplace la lecture a cet endroit.
  // / Tapping the waveform seeks there.
  function allerAuPointTouche(evenement) {
    if (!dureeDeLaReecoute) return;
    const cadre = evenement.currentTarget.getBoundingClientRect();
    const proportion = (evenement.clientX - cadre.left) / cadre.width;
    document.getElementById("reecoute").currentTime = proportion * dureeDeLaReecoute;
  }

  async function demarrer() {
    verrouillerLAccueil(true);
    // LE CONTEXTE AUDIO NAIT ICI, PENDANT LE TOUCHER, AVANT TOUTE ATTENTE.
    // Cree apres `await getUserMedia`, Safari le laisse suspendu : l'onde
    // serait plate alors que le micro marche — exactement le faux signal
    // qu'elle est la pour eviter.
    // / Created during the tap: after an await, Safari leaves it suspended
    //   and the waveform would falsely read as a dead mic.
    const contexteAudio = creerUnContexteAudio();
    let flux;
    try {
      // Exige HTTPS (ou localhost) : sans lui, pas de micro du tout.
      // / Requires HTTPS, otherwise there is no microphone at all.
      flux = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (erreur) {
      if (contexteAudio) contexteAudio.close().catch(() => {});
      // Micro refuse : l'autre porte, le fichier, doit rester ouverte.
      // / Mic refused: the file option must stay available.
      verrouillerLAccueil(false);
      document.getElementById("bouton-demarrer").insertAdjacentHTML(
        "afterend",
        `<p class="carte avis" role="alert">${config.textes.micRefuse}</p>`
      );
      return;
    }

    morceaux = [];
    enregistreur = new MediaRecorder(flux);
    enregistreur.ondataavailable = (evenement) => {
      if (evenement.data.size > 0) morceaux.push(evenement.data);
    };
    enregistreur.onstop = () => {
      debrancherLOndeEnDirect();
      rendreLEcran();
      flux.getTracks().forEach((piste) => piste.stop());
      const blob = new Blob(morceaux, { type: enregistreur.mimeType });
      accueillirLAudio(blob, `capsule.${extensionDuType(blob.type)}`, secondesEcoulees());
    };

    // PAS DE DUREE MAXIMALE, retiree le 2026-09-11 : elle coupait les longues
    // clameurs. C'est le visiteur qui arrete ; le plafond reel est la taille
    // acceptee par nginx, verifiee avant l'envoi.
    // / No maximum duration: the visitor stops; nginx's size cap is the limit.
    enregistreur.start();
    debutEnMs = Date.now();
    montrer("enregistrement");
    rafraichirChrono();
    minuterieChrono = setInterval(rafraichirChrono, 1000);
    garderLEcranAllume();
    brancherLOndeEnDirect(contexteAudio, flux);
  }

  function arreter() {
    clearInterval(minuterieChrono);
    if (enregistreur && enregistreur.state === "recording") enregistreur.stop();
  }

  function choisirUnFichier(evenement) {
    const fichier = evenement.target.files[0];
    if (!fichier) return;
    // La duree d'un fichier, le serveur la mesure (ffprobe) a la publication :
    // annoncer 0, c'est le laisser faire. Aucun chronometre n'a tourne ici.
    // / The server measures a file's duration; no stopwatch ran here.
    accueillirLAudio(fichier, fichier.name, 0);
  }

  function accueillirLAudio(blob, nom, duree) {
    blobLocal = blob;
    nomDuFichier = nom;
    dureeAnnoncee = duree;
    document.getElementById("reecoute").src = URL.createObjectURL(blobLocal);
    montrer("formulaire");
    envoyerLAudio();
    // Apres `montrer` : le canevas doit etre dans une etape visible pour
    // avoir une largeur. / After montrer: the canvas needs a visible step.
    dessinerLOndeDeLaReecoute(blobLocal);
  }

  function extensionDuType(type) {
    const minuscules = (type || "").toLowerCase();
    if (minuscules.includes("mp4") || minuscules.includes("aac")) return "m4a";
    if (minuscules.includes("ogg")) return "ogg";
    return "webm";
  }

  async function envoyerLAudio() {
    const etat = document.getElementById("etat-envoi");
    const publier = document.getElementById("bouton-publier");
    publier.disabled = true;

    // LE PLAFOND DE NGINX, VERIFIE AVANT D'ENVOYER. Au-dela, nginx repond 413 :
    // le visiteur lirait « l'envoi a echoue », et « reessayer » echouerait a
    // l'identique, sans qu'il comprenne pourquoi.
    // / Checked before sending: a 413 would look like a network glitch.
    if (blobLocal.size > config.tailleMaxOctets) {
      etat.textContent = config.textes.tropLourd;
      return;
    }

    etat.textContent = config.textes.envoiEnCours;

    const donnees = new FormData();
    donnees.append("audio", blobLocal, nomDuFichier);
    donnees.append("duree", String(dureeAnnoncee));

    // Le serveur explique ses refus — fichier sans son, trop d'envois, borne
    // fermee. Sa phrase dit la vraie raison ; « reessayer » n'y changerait rien.
    // / The server states its reasons; retrying would not change them.
    let refusDuServeur = "";
    try {
      const reponse = await fetch(config.urlCreation, {
        method: "POST",
        headers: { "X-CSRFToken": config.jetonCsrf },
        body: donnees,
      });
      if (!reponse.ok) {
        refusDuServeur = (await reponse.json().catch(() => ({}))).erreur || "";
        throw new Error(refusDuServeur);
      }
      uuidCapsule = (await reponse.json()).uuid;
      etat.textContent = "";
      publier.disabled = false;
    } catch (erreur) {
      etat.innerHTML = "";
      if (refusDuServeur) {
        etat.textContent = refusDuServeur;
        return;
      }
      // AUCUN REESSAI AUTOMATIQUE SILENCIEUX. Le blob reste en memoire et le
      // visiteur decide. / No silent auto-retry: the blob stays, the visitor decides.
      etat.textContent = config.textes.envoiEchoue + " ";
      const bouton = document.createElement("button");
      bouton.type = "button";
      bouton.className = "porte porte--fantome";
      bouton.textContent = config.textes.reessayer;
      bouton.addEventListener("click", envoyerLAudio, { once: true });
      etat.appendChild(bouton);
    }
  }

  async function publierLaCapsule(evenement) {
    evenement.preventDefault();
    if (!uuidCapsule) return;

    const etat = document.getElementById("etat-envoi");
    const bouton = document.getElementById("bouton-publier");
    bouton.disabled = true;
    etat.textContent = config.textes.publication;

    const donnees = new FormData(document.getElementById("formulaire-publication"));
    try {
      const reponse = await fetch(`/c/${uuidCapsule}/publier`, {
        method: "POST",
        headers: { "X-CSRFToken": config.jetonCsrf },
        body: donnees,
      });
      if (!reponse.ok) throw new Error(await reponse.text());
      const resultat = await reponse.json();
      document.getElementById("lien-capsule").href = resultat.url;
      montrer("fin");
    } catch (erreur) {
      etat.textContent = config.textes.envoiEchoue;
      bouton.disabled = false;
    }
  }

  document.getElementById("bouton-demarrer").addEventListener("click", demarrer);
  document.getElementById("bouton-arreter").addEventListener("click", arreter);
  // Un vrai bouton ouvre le selecteur : le champ fichier, masque, ne se
  // prendrait pas au clavier. / A real button opens the hidden file picker.
  const champFichier = document.getElementById("fichier-audio");
  document.getElementById("bouton-fichier").addEventListener("click", () => champFichier.click());
  champFichier.addEventListener("change", choisirUnFichier);
  document.getElementById("bouton-recommencer").addEventListener("click", () => {
    window.location.reload();
  });
  document
    .getElementById("formulaire-publication")
    .addEventListener("submit", publierLaCapsule);

  // L'onde de la reecoute suit la lecture, et un toucher la deplace.
  // / The playback waveform follows playback; a tap seeks.
  const lecteurDeReecoute = document.getElementById("reecoute");
  ["timeupdate", "seeked", "ended"].forEach((nomDeLEvenement) => {
    lecteurDeReecoute.addEventListener(nomDeLEvenement, redessinerLaReecoute);
  });
  document.getElementById("onde-reecoute").addEventListener("click", allerAuPointTouche);
  // Le telephone pivote : la largeur change, on redessine.
  // / The phone rotates: the width changes, redraw.
  window.addEventListener("resize", redessinerLaReecoute);

  // Le verrou d'ecran saute quand la page passe en arriere-plan : on le
  // redemande a son retour, si l'enregistrement tourne toujours.
  // / The wake lock drops when the page is hidden: request it again on return.
  document.addEventListener("visibilitychange", () => {
    const enregistrementEnCours = enregistreur && enregistreur.state === "recording";
    if (document.visibilityState === "visible" && enregistrementEnCours) garderLEcranAllume();
  });
})();
