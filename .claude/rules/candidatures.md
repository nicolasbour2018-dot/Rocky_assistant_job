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
- « Fait » (D6, Q5) est un changement `action_done` qui fixe la prochaine action suivante ; l'action faite se déduit de
  l'action en vigueur avant lui (pas de colonne). Proposé seulement après l'envoi (`FOLLOW_UP_STAGES`).
- Notes (`application_notes`) et langue (`application_languages`) sont en ajout seul **hors** des changements : « Annuler »
  ne les touche jamais. Une note se retire par une ligne `removes_id` (unique) ; la langue en vigueur est la dernière,
  français sans ligne (`language_in_force`). Toutes les routes du dossier lisent la langue du dossier, jamais un paramètre.
- Avant l'envoi (`BEFORE_SENDING`), l'échéance proposée s'arrête à la date limite de l'offre (`offres.web.offer_deadlines`).

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
- `offres` ne connaît `candidatures` que par des URL : l'encart (`/candidatures/offre/{id}`, chargé par la fiche) et
  « Valider et préparer » du tri (`/candidatures/offre/{id}/preparer`, `contexte=tri`, D6 Q8).

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

## Révisions et envoi (décision `docs/decisions/D5-revisions-envoi.md`)
- Un PDF envoyé est une **révision** : rendu hors transaction, écrit par `FileStore.put_file` (`candidatures`, adressé
  par son hash) puis `record_revisions` ; jamais réécrit. Le téléchargement relit les octets avec leur hash
  (`read_file`) ; un fichier altéré est refusé avec sa raison. Les aperçus des étapes CV et Lettre restent éphémères.
- Empreinte d'entrée (`inputs_sha256`) : CV = `profil.web.cv_fingerprint` (HTML, gabarit, photo), lettre =
  `letter_fingerprint` (HTML sans la date). Une révision dont l'empreinte diffère est « a changé depuis ».
- Un envoi documente **un** changement « Envoyée » (`change_id`) : `confirm_sending` écrit le changement, l'envoi et
  leurs événements dans la même transaction (test de panne de `test_sql.py`). Aucun envoi sans confirmation : la liste
  renvoie au formulaire. Un envoi n'est en vigueur que si son changement l'est (`sending_in_force`).
- Préremplissage **en sommeil** (recette du 04/10) : code gardé et testé, marqué « DORMANT », fermé par
  `web.PREFILL_ENABLED` (routes 404, aucun bouton). Ne pas le supprimer ni le rebrancher sans Nicolas ; ses tests
  l'allument par `app.state.prefill_enabled`. Quand il est actif : `record_prefill` seulement **après** que le poste a pris le formulaire (rien n'est écrit sinon) ;
  passage à « Préremplie » depuis « Prête à envoyer ». Les révisions remises sont celles **montrées** à la
  confirmation (identifiants cachés, refus si elles ont changé). Seul le domaine du formulaire va au journal.

## Écran (décision `docs/decisions/D6-ecran-candidatures.md`)
- Liste à onglets (`rules.Tab`, `tabs_of`) : « À faire » (action due ou en retard) par défaut, en plus de l'onglet de
  l'étape ; « À préparer » liste les offres « Intéressé » sans dossier. Chaque geste de la liste renvoie son onglet
  (`vue`, champ caché) et se fait en un clic (le menu d'étape part au `change`).
- Routes : `web.py` (liste, gestes, encart de la fiche, « Préparer »), `dossier_web.py` (page du dossier par étape),
  `web_common.py` (moteur, horloge, fragment, port vers `offres`). `dossier_web` ne doit pas importer `web`.
- Page du dossier : une étape à la fois, `/candidatures/{id}?etape=cv|lettre|envoi|suivi` (`dossier_url`), par défaut
  `rules.journey(...).current` (Suivi une fois envoyée ou close). Un geste fait depuis le dossier envoie `retour` = une
  étape (`Step`) ou `dossier`, valeur fixe et jamais une URL (pas de redirection ouverte).
- Lettre : un seul texte par paragraphe (`texte_i`) ; l'origine se **calcule** en comparant au paragraphe générique et
  à la version de Gemini (`letter_view._version_of`). Le sélecteur « Ta lettre · Gemini · Ta version » est rendu par le
  serveur (`/lettre/basculer`, rien n'est stocké) : pas de JavaScript maison au-delà des raccourcis (décision B4, e).
- Étape CV en **puces** (recette de D6) : un clic retire ou ajoute ; aucune flèche d'ordre à l'écran (les gestes
  `*-monter`/`*-descendre` restent côté serveur). Les raisons s'affichent après 2 s par `.tip[data-why]` (CSS seul).
- Aperçus en **image** à côté de l'étape (`/cv/apercu`, `GET /lettre/apercu`, `page_preview.html`), chargés par
  `hx-trigger="load"` ; jamais gardés. Un geste (« Fait »…) qui peut passer inaperçu le dit par un message (`alert-done`).
- Chronologie : `system.events.events_about` + `timeline.py` ; tout type `candidatures.*` écrit doit avoir sa ligne dans
  `timeline.LINES` (`test_timeline.py` le vérifie).
- Mêmes règles d'écran que `offres` (fragments HTMX, `wants_fragment`, `hx-swap` explicite, chaque route répond aussi
  sans HTMX, 404 pour le dossier d'un autre compte).
