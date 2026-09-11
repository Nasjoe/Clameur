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

  function montrer(nom) {
    Object.entries(ecran).forEach(([cle, section]) => {
      if (section) section.hidden = cle !== nom;
    });
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

  async function demarrer() {
    let flux;
    try {
      // Exige HTTPS (ou localhost) : sans lui, pas de micro du tout.
      // / Requires HTTPS, otherwise there is no microphone at all.
      flux = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (erreur) {
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

    try {
      const reponse = await fetch(config.urlCreation, {
        method: "POST",
        headers: { "X-CSRFToken": config.jetonCsrf },
        body: donnees,
      });
      if (!reponse.ok) throw new Error(await reponse.text());
      uuidCapsule = (await reponse.json()).uuid;
      etat.textContent = "";
      publier.disabled = false;
    } catch (erreur) {
      // AUCUN REESSAI AUTOMATIQUE SILENCIEUX. Le blob reste en memoire et le
      // visiteur decide. / No silent auto-retry: the blob stays, the visitor decides.
      etat.innerHTML = "";
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
})();
