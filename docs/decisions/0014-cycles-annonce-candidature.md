# 0014 – Séparer la fraîcheur, la complétude, la décision et la candidature

Date : 2026-09-01. Statut : acceptée.

## Contexte

La colonne `job_offers.status` porte neuf valeurs qui mélangent trois
préoccupations : l'âge de l'annonce (`NOUVELLE`, `ANCIENNE`), sa complétude
(`INCOMPLÈTE`, doublée par le booléen `description_is_full`), la décision du
candidat (`À ÉTUDIER`, `RETENUE`, `ÉCARTÉE`) et l'avancement d'une
candidature recopié depuis `applications.status` (`CANDIDATURE ENVOYÉE`,
`ENTRETIEN`, `REFUS`). Ce statut est partagé entre tous les profils qui
reçoivent l'annonce, ce que `docs/multi_profile_jobs.md` signale comme une
limite. `ÉCARTÉE` a trois sens : expirée par ancienneté, écartée par le
candidat, candidature close.

L'inventaire du 2026-09-01 montre en plus : la garde de non-régression des
candidatures n'est appelée que par le triage Gmail, cinq écritures depuis
l'interface la contournent ; le sous-ensemble « mes annonces » est recopié
dans trois pages ; le passage `INCOMPLÈTE → NOUVELLE` est un effet de bord
d'un formulaire ; les annonces n'ont aucun journal d'événements.

Alternative pesée : garder un statut unique et documenter ses sens. Elle
laisse la décision partagée entre profils et le triple sens de `ÉCARTÉE`.

## Décision

- La **fraîcheur** (nouvelle jusqu'à sept jours, ancienne de huit à quatorze,
  expirée au-delà) se déduit de la date de publication et n'est jamais
  stockée. La politique nocturne qui réécrivait les statuts disparaît.
- La **complétude** est un seul fait sur l'annonce.
- La **décision** du candidat (à trier, à étudier, retenue, écartée) vit sur
  le rattachement profil-annonce, donc par profil.
- La **candidature** garde son cycle de dix étapes ; `ÉCARTÉE` y devient
  « abandonnée ». L'annonce ne reflète plus l'avancement : l'interface le lit
  par jointure.
- Toute transition passe par le domaine. La garde de non-régression
  s'applique à tous les automatismes ; un retour en arrière humain est une
  annulation tracée. Chaque changement d'étape produit un événement.

Le vocabulaire est fixé dans `CONTEXT.md`, les automates dans
`docs/domaine.md`.

## Conséquences

- La migration de données répartit l'ancienne colonne : la décision vers le
  rattachement, l'avancement vers la candidature existante, `ÉCARTÉE` par
  ancienneté vers « à trier » sur une annonce expirée.
- Les statistiques et les filtres se réécrivent sur le cycle de la
  candidature ; les trois copies de sous-ensembles dans l'interface
  disparaissent, ainsi que `APPLICATION_TO_JOB_STATUS`.
- L'interface ne propose plus une liste libre de statuts : elle propose les
  transitions permises depuis l'étape courante.
