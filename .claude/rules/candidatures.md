---
paths: rocky/candidatures/**
---

# Module `candidatures` — règles propres

Complète `AGENTS.md` ; ne répète pas ce qui s'y trouve. Décision : `docs/decisions/D1-dossier-statuts.md`.

## Dossier et changements
- Un dossier est une suite de **changements en ajout seul** (`application_changes` : création, étape, prochaine action,
  annulation). L'étape et la prochaine action en vigueur **se calculent** (`rules.dossier`), jamais stockées :
  aucune colonne « étape courante », aucun `UPDATE` ni `DELETE` sur les changements.
- « Annuler » ajoute une ligne `cancellation` qui vise le dernier changement en vigueur du dossier (`rules.to_cancel`) ;
  la base refuse une double annulation (`cancels_id` unique).
- Une création ou un changement d'étape fixe **aussi** la prochaine action (proposition de `PROPOSALS`, ou aucune).
- Un dossier par offre et par compte (`applications`, unique) : une réouverture ajoute une création sur la même ligne.
- Codes anglais seulement (`Stage`, `ChangeKind`) ; libellés français à l'affichage. Un code publié ne se renomme plus.

## Transactions
- Un cas d'usage = une transaction ouverte par la route ; il verrouille d'abord le dossier
  (`application_for_offer`, `locked_application`) puis écrit ses lignes et son événement `candidatures.<fait>`.
- Ce qui va ensemble s'écrit ensemble : l'annulation d'une création annule aussi la décision « Intéressé » écrite par
  « Préparer » (`decision_id`), sur la même connexion. Le critère de sortie de D1 (`tests/candidatures/test_sql.py`,
  panne injectée à chaque écriture) doit rester vert ; toute nouvelle écriture d'une annulation y ajoute son point.
- Transitions : l'utilisateur va librement d'une étape à l'autre ; une règle ou l'IA (E4) passe par
  `automatic_transition_allowed` (jamais en arrière, jamais hors d'une issue).

## Lien avec `offres`
- Aucune lecture des tables d'`offres` : le port `OfferDecisions` (adaptateur `OffresDecisions`) et `offer_headings`
  passent par les fonctions publiques d'`offres/web.py`, dans la transaction de l'appelant.
- « Préparer » sur une offre sans décision ou « Plus tard » enregistre « Intéressé » avec `application_started` en tête et
  au moins un motif choisi (`application_decision`) ; refusé sur une offre écartée.
- `offres` ne connaît `candidatures` que par l'URL de l'encart (`/candidatures/offre/{id}`, chargé par la fiche).

## Lettre et message (décision `docs/decisions/D4-lettre-message.md`)
- Règles pures dans `letter.py` (titre nettoyé, en-tête, contrôles `signals`, invite et réponse du modèle), lecture du
  formulaire et vue dans `letter_view.py` (sans FastAPI), PDF dans `letter_render.py`. Le modèle est appelé **avant**
  la transaction ; rien de non validé n'est stocké.
- `application_letters` et `application_messages` en ajout seul : la dernière lettre d'une langue est en vigueur, une
  ligne `none` est « Pas de lettre ». Chaque paragraphe garde son origine, la version proposée et ses signaux (D14).
- Les contrôles signalent, ne bloquent jamais ; une formule écrite par l'utilisateur dans sa lettre n'est jamais
  signalée. Toute modification des listes change `CHECKS_VERSION`.
- « Pas de lettre » et le passage à « Prête à envoyer » s'écrivent dans la même transaction (test de panne de
  `test_sql.py`).

## Écran
- Liste brute de D1, avec « À préparer » (offres « Intéressé » sans dossier, D3 Q26) ; l'écran 📝 Candidatures est D6.
- Page du dossier (D3, Q25) : fil 1. CV / 2. Lettre / 3. Envoi calculé par `rules.journey` (étape et état de la
  lettre) ; « Préparer » y atterrit. Les gestes qui changent le fil (valider, « Lettre prête », « Pas de lettre »)
  sont des formulaires non boostés qui reviennent sur `#lettre` ou `#envoi`.
  Un geste fait depuis le dossier envoie `retour=dossier`, valeur fixe et jamais une URL (pas de redirection ouverte).
- Mêmes règles d'écran que `offres` (fragments HTMX, `wants_fragment`, `hx-swap` explicite, chaque route répond aussi
  sans HTMX, 404 pour le dossier d'un autre compte).
