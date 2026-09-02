/* Copier le lien d'une clameur.
 * / Copy a clameur's link.
 *
 * DEUX CHEMINS, ET LE SECOND N'EST PAS DU LUXE. `navigator.clipboard`
 * N'EXISTE PAS hors contexte securise : en developpement, sur
 * http://localhost c'est encore bon, mais sur http://192.168.x.x — le
 * telephone qui teste la borne sur le reseau local — l'objet est absent et le
 * bouton ne ferait RIEN, sans erreur visible. Le repli par `execCommand` est
 * deprecie et fonctionne partout.
 * / navigator.clipboard is absent outside secure contexts: on a phone hitting
 *   the dev machine by IP the button would silently do nothing.
 */
(function () {
  "use strict";

  const DUREE_DU_MERCI = 1600;

  async function copier(texte) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(texte);
      return;
    }
    const champ = document.createElement("textarea");
    champ.value = texte;
    // Hors de l'ecran, mais PAS `display:none` : un champ non affiche n'est
    // pas selectionnable, et la copie echouerait en silence.
    // / Off-screen, not hidden: a hidden field cannot be selected.
    champ.setAttribute("readonly", "");
    champ.style.position = "fixed";
    champ.style.top = "-1000px";
    document.body.appendChild(champ);
    champ.select();
    document.execCommand("copy");
    document.body.removeChild(champ);
  }

  // Delegation sur le document : les fiches arrivent et repartent au fil des
  // recherches HTMX, et un ecouteur pose sur chacune disparaitrait avec elles.
  // / Delegated: cards come and go with every HTMX search.
  document.addEventListener("click", async function (evenement) {
    const bouton = evenement.target.closest("[data-partager]");
    if (!bouton) return;

    evenement.preventDefault();
    const dit = bouton.querySelector(".partager-dit");
    try {
      await copier(bouton.dataset.partager);
      if (dit) dit.textContent = bouton.dataset.merci || "Lien copié";
      bouton.classList.add("dit");
    } catch (erreur) {
      // Le presse-papier peut etre refuse par l'utilisateur ou le navigateur.
      // On le dit, plutot que de laisser croire que c'est copie.
      // / Say it, rather than let them believe it worked.
      if (dit) dit.textContent = bouton.dataset.echec || "Copie refusée";
      bouton.classList.add("dit");
    }
    setTimeout(function () {
      if (dit) dit.textContent = "";
      bouton.classList.remove("dit");
    }, DUREE_DU_MERCI);
  });
})();
