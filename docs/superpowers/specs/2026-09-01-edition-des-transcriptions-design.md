# Clameur — Corriger une clameur

**Date :** 2026-09-01
**Statut :** design à relire
**Licence du projet :** AGPL-3.0

---

## 1. Intention

Voxtral entend mal. Il écrit « on la prend » pour « on l'apprend », massacre les
noms propres, et coupe les phrases au mauvais endroit. Le titre qu'en tire
`mistral-small` hérite de ces erreurs. Aujourd'hui, rien ne permet de les
réparer : la parole reste déformée sur la page, et sur le lien qu'on partage.

Ce chantier ouvre la correction de trois choses, **et de trois seulement** :

- le **titre** ;
- le **texte de chaque parole** ;
- le **nom de chaque voix** — « Voix 1 » devient « Fatima », quand on sait qui parle.

---

## 2. Décisions arrêtées avec le mainteneur

| | Décision | |
|---|---|---|
| **D1** | **Tout le monde peut corriger**, sans compte ni session. | Une coquille se répare par qui la voit. |
| **D2** | **On édite en place.** La transcription d'origine n'est pas conservée. | Une seule source de vérité. |
| **D3** | **Champ par champ**, en place, par HTMX. | Le geste vise la coquille isolée. |
| **D4** | **Pas de journal** des corrections. | Assumé : voir §9. |
| **D5** | **La correction prime.** Une clameur corrigée n'est plus jamais réécrite par une tâche automatique. | |
| **D6** | **Un nom par voix**, propre à la capsule. Pas de réattribution des répliques. | La diarisation reste celle de Voxtral. |

---

## 3. Modèle de données

Deux champs nouveaux sur `Capsule`, aucun modèle supplémentaire.

| Champ | Type | |
|---|---|---|
| `noms_des_voix` | `JSONField(default=dict)` | `{"speaker_1": "Fatima"}`. Vide tant que personne n'a nommé. |
| `corrigee_le` | `DateTimeField(null=True)` | La date de la première correction. **C'est le drapeau qui fige la clameur** (§4). |

Les champs existants sont édités en place :

- `titre` — écrit tel quel ;
- `transcription_raw["segments"]` — réécrit à partir des paroles affichées ;
- `transcription_texte` — **recalculé** à chaque correction, puisque c'est lui
  que la recherche interroge. Sans cela, on chercherait encore l'erreur.

### Où le nom d'une voix remplace « Voix 1 »

Dans `preparer_les_paroles`, et nulle part ailleurs. La fonction reçoit
aujourd'hui une liste de segments ; elle recevra aussi la correspondance des
noms, et posera `noms_des_voix["speaker_1"]` là où elle écrivait « Voix 1 ».
Tout le reste — la numérotation dans l'ordre d'apparition, l'étiquette absente
quand il n'y a qu'une voix, une couleur par locuteur — ne bouge pas.

Conséquence : les trois appelants (`lire_capsule`, `decrire_une_clameur`,
`diffusion.py`) passent désormais la capsule et non ses seuls segments.

### Le point délicat : paroles affichées contre segments bruts

L'affichage ne montre pas les segments de Voxtral tels quels : `preparer_les_paroles`
recolle ceux qui sont séparés par moins d'une seconde (`SILENCE_QUI_SEPARE`).
**On édite ce qui est affiché**, c'est-à-dire les paroles.

À l'enregistrement, chaque parole corrigée redevient **un segment**, avec les
bornes `start` et `end` de la parole d'origine. La granularité fine de Voxtral
est donc perdue à la première correction — conséquence directe de D2, et sans
effet visible : l'affichage recollait déjà ces segments.

---

## 4. Ce que la correction fige

Dès que `corrigee_le` est renseignée :

- `transcrire` rend `"corrigee"` sans rien réécrire ;
- `taguer` ne réécrit plus le titre (il peut toujours poser des mots-clés).

**Le rejeu existe et il est à portée de clic.** `capsules/admin.py` porte
l'action « Rejouer l'enrichissement », qui relance `transcrire`. Sans ce
verrou, un opérateur voulant réparer une transcription ratée effacerait la
correction que quelqu'un venait d'écrire, sans un mot. La console dira combien
de clameurs ont été laissées de côté parce qu'elles sont corrigées.

Un seul drapeau pour toute la capsule, et non un par champ : « cette clameur a
été touchée à la main, la machine n'y revient plus » se raisonne d'un coup
d'œil, et se teste.

---

## 5. Routes

Une seule.

```
POST /c/<uuid>/corriger     champ = titre | parole | voix
                            index  (pour une parole)   cle (pour une voix)
                            valeur
```

`index` désigne le rang de la parole **dans la liste affichée**, celle que
`preparer_les_paroles` vient de produire — et non le rang d'un segment brut.
Comme une parole corrigée redevient exactement un segment, les deux listes
convergent dès la première correction.

Deux personnes qui corrigent la même parole en même temps : la dernière écrite
gagne, sans avertissement. Le cas est trop rare, et l'enjeu trop mince, pour
mériter un verrou.

Elle rend **le fragment HTML du seul élément corrigé**, que HTMX remet en
place. Elle refuse :

- une capsule qui n'est pas `publiee` — on ne corrige pas une clameur retirée ;
- un champ inconnu, un index hors bornes ;
- une valeur qui dépasse les limites du §6 ;
- une requête au-delà de la limite anti-abus.

La page reste entièrement lisible sans JavaScript ; seule la correction
demande HTMX (D3).

---

## 6. Validation

| | Limite |
|---|---|
| titre | 120 caractères |
| parole | 2 000 caractères |
| nom de voix | 40 caractères |

Dans tous les cas : espaces normalisés, caractères de contrôle refusés, valeur
vide refusée pour le titre et les paroles (un nom de voix vide efface le nom et
rend « Voix N »).

**Pas de bibliothèque de sanitisation.** Django échappe tout ce qui sort d'un
`{{ }}`, et aucun de ces champs n'est rendu avec `|safe` : un `<script>` stocké
s'affiche comme du texte. Un test vérifie qu'aucun gabarit ne marque ces champs
comme sûrs — c'est le jour où quelqu'un ajoutera `|safe` que la faille
naîtrait, pas aujourd'hui.

**Limite anti-abus** par adresse, via `capsules/garde_fous.py`, déjà en place
pour la publication : D1 ouvre la correction à tous, y compris à une boucle de
`curl`.

---

## 7. Interface

Sur `/c/<uuid>` seulement. Jamais sur la liste : on corrige en écoutant.

Chaque élément corrigible porte un bouton discret, dans le style de l'atelier
existant (`.action`). Un clic le remplace par un champ, avec « Enregistrer » et
« Annuler ». Le fragment revient corrigé.

**Le lecteur audio n'est jamais dans la zone remplacée.** Un `<audio>` recréé
par un swap HTMX repart de zéro : la lecture s'arrête au milieu de la phrase
qu'on était en train de corriger. C'est la contrainte qui dessine le découpage
des fragments.

Les noms de voix se corrigent en tête de la transcription, une ligne par voix
présente — et cette ligne n'apparaît pas quand il n'y a qu'une voix, puisque
son étiquette ne s'affiche pas non plus.

---

## 8. Tests

- Corriger le titre, une parole, le nom d'une voix.
- `transcription_texte` suit la correction : **la recherche trouve le texte corrigé
  et non l'ancien**.
- Une clameur corrigée n'est réécrite ni par `transcrire` ni par `taguer`.
- Une clameur retirée refuse la correction.
- Les trois limites de longueur ; les caractères de contrôle ; la valeur vide.
- La limite anti-abus se déclenche.
- Aucun gabarit ne rend ces champs avec `|safe`.
- Le fragment renvoyé ne contient pas d'élément `<audio>`.

---

## 9. Ce qui est écarté, et assumé

Deux garde-fous ont été proposés puis écartés par le mainteneur, en
connaissance de cause. Ils sont consignés ici pour que personne ne les
redécouvre comme des oublis :

- **Aucune version d'origine** (D2). Une parole déformée — par erreur ou à
  dessein — l'est définitivement.
- **Aucun journal** (D4). Rien ne dit qui a corrigé, quand, ni ce qu'il y avait
  avant. Combiné à D1, cela signifie qu'un tiers peut réécrire la parole d'un
  autre sans laisser de trace, alors qu'il ne peut pas la retirer.

Le projet héberge de la parole publique sous pseudo (LCEN). Si un usage réel
fait apparaître le besoin, le journal est le premier ajout à envisager : une
table `Correction` et un `ModelAdmin` en lecture seule suffiraient.

**Hors périmètre :** réattribuer une réplique à une autre voix, corriger les
minutages, éditer les mots-clés ou le pseudo.
