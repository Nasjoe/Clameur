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
 */

(function () {
  "use strict";

  const config = window.CLAMEUR;
  const ecran = {
    accueil: document.getElementById("etape-accueil"),
    enregistrement: document.getElementById("etape-enregistrement"),
    formulaire: document.getElementById("etape-formulaire"),
    fin: document.getElementById("etape-fin"),
  };

  let enregistreur = null;
  let morceaux = [];
  let blobLocal = null;
  let uuidCapsule = null;
  let debutEnMs = 0;
  let minuterieChrono = null;
  let minuterieGardeFou = null;

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
      blobLocal = new Blob(morceaux, { type: enregistreur.mimeType });
      document.getElementById("reecoute").src = URL.createObjectURL(blobLocal);
      montrer("formulaire");
      envoyerLAudio();
    };

    enregistreur.start();
    debutEnMs = Date.now();
    montrer("enregistrement");
    rafraichirChrono();
    minuterieChrono = setInterval(rafraichirChrono, 1000);

    // Garde-fou technique contre l'enregistrement oublie en poche. Le serveur,
    // lui, accepte ce qui lui arrive : on ne detruit jamais une voix.
    // / Technical guard only; the server still accepts what it receives.
    minuterieGardeFou = setTimeout(arreter, config.dureeMaxSecondes * 1000);
  }

  function arreter() {
    clearInterval(minuterieChrono);
    clearTimeout(minuterieGardeFou);
    if (enregistreur && enregistreur.state === "recording") enregistreur.stop();
  }

  function extensionDuBlob() {
    const type = (blobLocal.type || "").toLowerCase();
    if (type.includes("mp4") || type.includes("aac")) return "m4a";
    if (type.includes("ogg")) return "ogg";
    return "webm";
  }

  async function envoyerLAudio() {
    const etat = document.getElementById("etat-envoi");
    const publier = document.getElementById("bouton-publier");
    etat.textContent = config.textes.envoiEnCours;
    publier.disabled = true;

    const donnees = new FormData();
    donnees.append("audio", blobLocal, `capsule.${extensionDuBlob()}`);
    donnees.append("duree", String(secondesEcoulees()));

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
      bouton.className = "bouton bouton--fantome";
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
  document.getElementById("bouton-recommencer").addEventListener("click", () => {
    window.location.reload();
  });
  document
    .getElementById("formulaire-publication")
    .addEventListener("submit", publierLaCapsule);
})();
