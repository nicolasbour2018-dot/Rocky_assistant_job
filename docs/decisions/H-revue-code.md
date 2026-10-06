# H — Revue de code, en parallèle de G

Date : 06/10/2026 · Origine : revue du code et de l'architecture du 05–06/10 (trois relecteurs, constats P1 revérifiés
dans le code), arbitrée avec Nicolas · Préparation : propre à chaque étape (ci-dessous)

Ce document décrit les étapes H1–H5 du plan v2 (§4, H). Chaque constat est cité avec sa référence au 06/10 (commit
`f1bd51a`) : l'agent d'une étape vérifie d'abord qu'il tient encore, car les lignes bougent avec G.

## Arbitrage de Nicolas (06/10)

Corriger ce qui cause un bug et lever **une** ambiguïté d'architecture (le `web.py` d'un module sert aussi d'API
publique aux autres) ; **ne pas suringénier**. On ne remanie que ce qui cause un bug ou ce qu'une étape va toucher de
toute façon.

| Retenu | Écarté (et pourquoi) |
|---|---|
| Bugs P1 et les 500 rares | — |
| Un gestionnaire global des erreurs métier, plus simple qu'un `try` par route | — |
| Un seul « jour de Paris » : corrige un bug de date | — |
| `api.py` par module : simple déplacement des fonctions publiques, sans nouvelle couche | — |
| Une fabrique unique de `MessagesService` (5 constructions différentes dans `admin.py`) | Racine de composition hors de `system`, dataclass `Services`, accesseur typé de `app.state` : coût sans bug à la clé |
| Calculs sortis de trois gabarits (dans G6) | Convention `views.py` généralisée : cérémonie pour un petit projet |
| — | Dédoublonnage des aides sans bug (verrou consultatif, `_in`, `_editor`, `_png`) et découpage de `messages/sql.py` : au fil de l'eau seulement (plan §8) |
| — | Rendre `profil.web.cv_document` / `cv_fingerprint` / `profile_of` indépendants de `Request` : seulement si G4 en a besoin |

## Travailler en parallèle de G

L'agent de G travaille sur `refonte` dans le dossier principal du dépôt. Une étape H ne doit jamais le gêner :

1. **Isolement.** Une étape H se fait dans un worktree `.claude/worktrees/hN` (ignoré par git), sur une branche
   `revue/hN-<sujet>` partie d'`origin/refonte` à jour. Jamais dans le dossier principal ; jamais de `git stash` nu
   (la pile est partagée entre worktrees).
2. **File unique.** Les étapes H se font l'une après l'autre (H1 → H5), à côté de la file G. Deux agents au plus en
   même temps : un sur G, un sur H.
3. **Fenêtres.** Chaque étape a une fenêtre (tableau du plan, colonne « Fenêtre ») : elle est fusionnée **avant** que
   l'étape G nommée ne commence son code. Si cette étape G a déjà commencé et touche les mêmes fichiers, l'étape H
   attend la fin de G et reprend la branche à jour.
4. **Périmètre.** Une étape H ne touche que les fichiers de sa section ci-dessous, plus ses tests et la mise à jour
   des règles d'agent qui citent ce qu'elle déplace. Dans le plan, elle ne modifie que **sa** ligne du tableau H et la
   section 8 ; jamais une ligne de G, une décision de G ni les décisions D1–D16.
5. **Fusion.** En fin d'étape : `git merge origin/refonte` dans la branche (pas de rebase), vérification globale verte
   (`docker compose run --rm --build check`), PR vers `refonte`, vérification GitHub verte, fusion **avec un commit de
   merge**, branche et worktree supprimés. Commits : `fix(H1): …`, `refactor(H4): …`.
6. **Côté G.** L'agent de G fait `git pull --no-rebase` avant de pousser : une fusion H arrivée entre-temps s'intègre
   par un merge ordinaire.

## H1 — Erreurs visibles et bugs bloquants

*Direct* (le gestionnaire d'erreurs : *mode plan*). **Fenêtre : maintenant, pendant G2 ; fusionnée avant le code de
G3 et de G5.**

1. **La touche `e` a deux sens.** `offres/decisions.py:55` donne `e` à « Écarté » ;
   `offres/templates/offres/browser_reading.html:14,24` donne aussi `data-key="e"` à « Lire la page affichée » et
   « Ouvrir dans le navigateur ». `rocky.js` clique le premier élément visible, et `#decision-area`
   (`offer_body.html:52`) précède la lecture assistée (`:69`) : sur une offre incomplète, `e` ouvre « Écarté ».
   → Autre touche pour la lecture assistée : **`n`, choisie par Nicolas le 06/10**, aide `SHORTCUTS`
   (`offres/web.py:127-145`) et décision E5 corrigées ; un test : aucune touche `data-key` en double dans une page
   rendue de la fiche incomplète.
2. **Gestionnaire global des erreurs métier.** Seul `LoginRequiredError` a un gestionnaire (`system/auth/web.py:167`) ;
   plusieurs routes laissent passer une erreur métier en 500. → Une classe de base dans `system` dont héritent
   `InvalidChangeError`, `ProfileInputError`, `CvRefusedError` (et `RenderError` pour sa raison) ; un
   `add_exception_handler` qui rend le message (fragment HTMX en 200, page en 409) et le journalise.
   *Réalisé (06/10)* : `system/errors.py` (`UserFacingError`), gestionnaire `shell.show_user_error` : un fragment
   HTMX est reciblé sur la zone `#erreur` du layout (`HX-Retarget`), sans écraser la cible ; une navigation boostée
   reçoit la page entière en **200** (HTMX n'échange pas une réponse 4xx : un 409 resterait invisible) ; seule une
   requête sans HTMX reçoit le 409. Les traitements
   locaux existants restent : le gestionnaire ne couvre que les oublis. L'erreur est rendue visible, jamais avalée
   (AGENTS §4).
3. **Onboarding : une ligne vide donne une 500.** `profil/usecases.py:338` (`add_skills`) appelle `make_skill` hors
   du `try` ; `make_skill` refuse un nom vide (`profil/rules.py:326`). → Ignorer les lignes vides.
4. **Candidature annulée : changer l'étape ou la prochaine action donne une 500.** `candidatures/web.py:535,570`
   appellent `change_stage` / `set_next_action` sans `try` ; `_open` lève `InvalidChangeError`
   (`candidatures/usecases.py:897`). → Couvert par le point 2, plus un test par route.
5. **Sélection CV qui vise une compétence ou un projet supprimé.** `selection_of` (`candidatures/targeting.py:262`)
   garde les identifiants tels quels ; `cv_content` (`profil/cv/content.py:139-150`) lit `skills[s]` sans garde →
   `KeyError` au PDF et à l'aperçu. → Test d'abord (le prouver), puis filtrer les identifiants inconnus ou rendre
   `None` (l'écran dit déjà « à reproposer »).
6. **Date limite ignorée par « Lettre prête » et « Pas de lettre ».** `_letter_gesture`
   (`candidatures/dossier_web.py:1009-1025`) ne passe jamais `deadline` à `skip_letter` / `letter_ready` : la
   prochaine action « Envoyer » peut tomber après la date limite (D6, Q8). → Lire `offer_deadlines` comme
   `web._deadline`.
7. **500 plus rares.**
   - `Content-Disposition` construit avec le nom brut (`profil/web.py:1203`, `candidatures/dossier_web.py:884,1265`) :
     un nom hors latin‑1 lève `UnicodeEncodeError`. → Réutiliser `_disposition` (`dossier_web.py:1525`).
   - `profil/web.py:1310` (`_slots`) ne convertit pas `FileError` ; `profil/translation_web.py:337`
     (`_english_screen`) n'attrape ni `RenderError` ni `CvRefusedError`.
   - `isdigit()` puis `int()` (`messages/web.py:671`, `offres/web.py:224`, `offres/screen.py`, `make_filters`) :
     `"²".isdigit()` est vrai. → `isascii() and isdigit()`.
   - `system/llm.py:119,138` : une réponse Gemini mal formée lève `AttributeError` au lieu de
     `LlmUnavailableError`.

**Critère de sortie** : chaque point a un test qui échouait avant (500, mauvaise touche, échéance) et passe ;
vérification globale verte.

## H2 — Un seul jour de Paris

*Direct.* **Fenêtre : après la fusion de G2 (qui touche le `today` de l'analyse) ; avant le code de G3.**

- Trois façons de compter le jour : `datetime.now(UTC).date()` (`offres/imports/web.py:107`), `now.date()` sur une
  horloge UTC (`offres/watch/usecases.py:180,309`), `datetime.now(UTC)` en dur dans le filtre `age`
  (`offres/web.py:201`) ; `messages` utilise `paris_day` (`messages/decisions/rules.py:162`). Entre minuit et 2 h,
  heure de Paris, analyse, score et « hier / aujourd'hui » ont un jour de retard. → `paris_day` déplacé dans
  `system`, utilisé partout ; le filtre `age` lit l'horloge injectée.
- `send_view.py:184` date un envoi en UTC (`changed_at.date()`), `report.py:67` en heure de Paris.
- `utc_now` défini trois fois (`system/web.py:71`, `system/admin.py:431`, `system/scheduler.py:29`) ; `paris_time`
  (`offres/watch/web.py:77`) et `_paris` (`system/web.py:166`) identiques ; `messages/web.py:72` importe son heure
  depuis `offres.watch.web`. → Une définition chacun, dans `system`.
- `system/admin.py:71` : `import_profile` reçoit `clock` mais passe `clock=utc_now` en dur (ligne 93).

**Critère de sortie** : un test à 00 h 30 heure de Paris (22 h 30 UTC la veille) donne le même jour à la veille, à
l'import, aux alertes et à l'affichage ; vérification globale verte.

*Réalisé (06/10)* : `rocky/system/clock.py` porte `PARIS`, `utc_now`, `paris_day`, `paris_time` (filtre Jinja posé
par `system/web.py`) et `today_of(request)`. `app.state.import_today` (un second « aujourd'hui » injectable, en UTC)
est retiré : tout jour se lit dans l'horloge unique `app.state.auth.clock`, que les tests règlent (`clock.now`). Le
filtre `age` devient `age(day, today)`, branché sur cette horloge. Même correction, pour le même bug, dans `profil`
(âge du CV, nom « CV importé le … »). Un test par lieu à 00 h 30 (veille et recalcul, aperçu d'import, alertes, âge
affiché, envoi, `import_profile`) ; `unix_date` (Wellfound) noté en §8 du plan.

## H3 — Veille, Gmail et alertes

*Grill me court (Q1, Q2), décisions ajoutées ici, puis direct.* **Fenêtre : avant le code de G3** (le cockpit montre
la veille en retard).

- **Q1 — Marge du retard de veille.** `LATE_AFTER = 24h` (`offres/watch/rules.py:27`) pour une veille quotidienne à
  12 h : au passage à l'heure d'hiver (25 h entre deux veilles), ou si le fil du planificateur est occupé à 12 h, la
  carte « Veille en retard » propose une seconde veille. Proposition : 25 h.
- **Q2 — eFinancialCareers.** Un lecteur d'alertes existe (`messages/alerts/rules.py:38`), mais
  `efinancialcareers.fr` manque à `ALERT_DOMAINS` (`messages/rules.py:33-40`) : une alerte rangée par Gmail en
  Promotions n'est pas relevée (à vérifier sur la requête REPLIES). Proposition : ajouter le domaine
  (`QUERIES_VERSION` changée).
- `messages/alerts/usecases.py:117-118` : un report « veille en cours » écrase le compte des alertes déjà reportées
  par la limite du jour et efface `DAY_LIMIT_REASON`.
- `TOO_OLD_REASON` (« plus de 3 jours », `alerts/usecases.py:51`) ne suit pas `max_age` ; « 50 000 caractères »
  (`offres/imports/rules.py:275`) ne suit pas `MAX_PASTED_CHARACTERS`. → Formater depuis les constantes.
- `messages/usecases.py:233` : `_collect` rattrape `AccessLostError` (sous-classe de `GmailError`) alors que `_list`
  (`:266`) la relance ; la boîte ne passerait pas « À reconnecter ».
- `system/files.py:121` (`find_bundle`) saute un paquet corrompu sans le journaliser.
- Repli « carte sans lien » (`messages/alerts/rules.py:95`, `message_link`) : inaccessible aujourd'hui, mais un futur
  lecteur donnerait la même URL à toutes les cartes d'une alerte, fusionnées en une offre par `SqlStore.find`
  (`offres/sql.py:310`). → Retirer le repli ou rendre l'URL propre à la carte.

### Décisions de Nicolas (grill du 06/10)

| Sujet | Décision |
|---|---|
| Q1 — Retard de veille | `LATE_AFTER` = **25 h** : couvre le passage à l'heure d'hiver et jusqu'à une heure de retard du planificateur. Révise C6 Q2 (24 h). |
| Q2 — eFinancialCareers | `efinancialcareers.fr` ajouté à `ALERT_DOMAINS`, nouvelle `QUERIES_VERSION`, **sans rattrapage** : la fenêtre de collecte ne se rouvre pas, et une alerte de plus de 3 jours ne donne de toute façon aucune offre. |
| Carte sans lien | **On garde le repli, propre à la carte** : l'adresse de l'offre est celle de l'alerte dans Gmail, avec l'identifiant de la carte (`?carte=…`), pour que deux cartes ne fusionnent jamais. La raison affichée demande de remplacer l'adresse Gmail par celle de l'annonce. Le geste « Remplacer l'adresse » (→ G6) et une ligne du fil du Cockpit, « offres d'alerte sans adresse à compléter » (→ G3), sont notés en §8 du plan : inutiles tant qu'aucun lecteur ne produit ce cas. |
| Reports cumulés | Le compte additionnerait les deux reports et garderait la raison de la limite du jour. **Sans objet** (vérifié en H3) : une veille en cours ne bloque qu'une alerte qui donne des offres, donc lue tant que la limite du jour n'est pas atteinte (`left > 0`) ; la limite ne reporte qu'ensuite, et seule une alerte trop ancienne (sans offre, sans verrou) s'écrit encore. Les deux reports ne se cumulent jamais dans une passe : le code ne change pas. |

`ALERTS_VERSION` ne change pas : aucun lecteur ne change, et le repli ne sert à aucun lecteur actuel.

*Réalisé (06/10)* : `LATE_AFTER` = 25 h (test du dimanche du passage à l'heure d'hiver, mesuré en UTC comme en base) ;
`efinancialcareers.fr` dans `ALERT_DOMAINS`, `QUERIES_VERSION = "mail-2026-10-06.1"` (test : chaque adresse de
`READERS` est couverte par la requête des alertes) ; `TOO_OLD_REASON` formatée depuis `max_age`, la limite du collage
depuis `MAX_PASTED_CHARACTERS` ; `AccessLostError` relancée pendant le téléchargement d'un message (la collecte
échouait en « partielle » et la boîte restait connectée) ; `find_bundle` journalise un paquet abîmé qu'il saute ;
`message_link(message, card_id)` donne `…/?carte=<identifiant>#all/<id>`, raison `NotTried.NO_LINK` réécrite et dite
même lors d'un passage sans lecture des fiches (test : deux cartes sans lien donnent deux offres, avant fusionnées en
une). Geste et ligne du Cockpit notés en §8 du plan (→ G6, → G3).

**Critère de sortie** : Q1 et Q2 consignées ici ; chaque point a son test ; `ALERTS_VERSION` / `QUERIES_VERSION`
changées si un lecteur ou une requête change ; vérification globale verte.

## H4 — API publique des modules

*Mode plan* (questions de départ : Q3, test d'architecture). **Fenêtre : après H1 (mêmes fichiers) ; avant le code de
G3 si possible, sinon juste après G3 ; toujours avant G4** (l'assistant lit les modules par leurs cas d'usage, en
lecture seule).

- Le `web.py` d'un module sert d'API aux autres : `offres/web.py:826-1006` (`offer_headings`, `offer_analysis`,
  `offer_deadlines`, `record_alert_offer`, `try_lock_offers`…), `candidatures/web.py:148-344` (`mail_targets`,
  `mail_stage`, `move_application_by_message`…), `profil.web.stored_profile`. Importés par `messages/links.py`,
  `messages/service.py`, `messages/sql.py`, `candidatures/web_common.py`, `candidatures/dossier_web.py`,
  `offres/imports/web.py`, `offres/watch/service.py`, `system/admin.py`. Un fil d'arrière-plan ou la CLI charge ainsi
  des modules de routes.
  → **Déplacer** ces fonctions dans `rocky/<module>/api.py`, sans réexport (un seul chemin), et corriger les
  importeurs. Pas de nouvelle abstraction : mêmes signatures, même transaction de l'appelant. Les fonctions de
  `profil.web` qui prennent une `Request` (`profile_of`, `cv_document`, `cv_fingerprint`, `cv_slots`) restent dans
  `web.py` (G4 décidera).
- `system/admin.py:536-580` construit `MessagesService` cinq fois, avec des configurations différentes ;
  `messages/web.py:139` une sixième. → Une fabrique dans `messages` (options explicites pour ce que la CLI omet
  volontairement).
- `system/admin.py` : la recherche du compte (`normalize_email` + `find_account`) est répétée 7 fois ; `check_sources`
  (`:154-167`) lit `SqlProfileStore` et refait `active_tracks`. → Une aide `_account` ; `stored_profile` +
  `active_tracks`.
- La docstring de `system/shell.py:4` dit que `system` n'importe aucun module : vrai pour `shell.py`, faux pour
  `system/web.py` et `admin.py` (assemblage). → La préciser.
- Règles d'agent à mettre à jour : `.claude/rules/offres.md:78,90,103`, `messages.md:50`, `candidatures.md:23,36`
  (citent `offres.web.*` / `profil.web.*`), et la forme interne d'un module (plan §3, AGENTS §4) : « API publique du
  module : `api.py` ».
- **Q3 (Nicolas)** : ajouter ou non un test d'architecture (une vingtaine de lignes sur les imports : aucun module
  n'importe le `web.py` ni le `sql.py` d'un autre ; `system` n'importe un module métier que dans `web.py`, `admin.py`,
  `tables.py`).

**Critère de sortie** : aucun import du `web.py` d'un autre module (`grep -rn "import web as" rocky` ne montre que
`system/web.py`, et les imports internes d'un module) ; fabrique unique de `MessagesService` ; vérification globale
verte.

## H5 — Petites dettes et code mort

*Direct.* **Fenêtre : avant le code de G6** (G6 reprend écrans et gabarits).

- **Code mort** (grep sur `rocky/` et `tests/`) : `REVISION_LABELS` (`candidatures/model.py:260`), `NEUTRAL_NAME`
  (`profil/cv/template.py:18`, alors que `profil/web.py:1262` écrit `"neutre"`), `GESTURE_LABELS`
  (`messages/decisions/model.py:46`), `platform_label` (`messages/alerts/rules.py:137`), `REFERENCE_URL`
  (`offres/sources/apec.py:34`) ; `MAX_REASON_KEYS` (`offres/decisions.py:25`) n'est utilisé que par les tests.
  Le code **DORMANT** du préremplissage n'est pas du code mort : on n'y touche pas.
- **Idempotence et effets** : `skip_letter` (`candidatures/usecases.py:476`) écrit deux lignes `none` sur un double
  clic ; `_editor(writes=True)` (`profil/web.py:262-267`, `:735`) réveille le recalcul même sans écriture.
- **Lecture inutile** : les routes « une offre » `offres/web.py:635,683,717` construisent `Screen`, qui lit toute la
  liste (contraire à la règle d'écran d'`offres.md`).
- **Doublon de formatage** : `offres/watch/web.py:240` (`source_line`) refait `offres/sources/report.py`.
- **Redirection** : `back_to` (`profil/translation_web.py:74`) accepte `/\evil.com`.
- **Noms et docstrings** : `send_view.py:3` (les routes sont dans `dossier_web.py`) ; deux `EnglishState`
  (`letter_web`, `translation_web`) ; deux `is_stale` de sens différents (`profil/translation.py:126`,
  `candidatures/rules.py:330`) ; typage effacé (`_letter_gesture(use_case: Callable[..., object])`,
  `profil/web.py:712+` en `-> Any`).
- **Textes** : « Un employeur candidaté est reconnu. » (`messages/classification/rules.py:934`) → « Un employeur où
  tu as candidaté est reconnu. » (change `CLASSIFY_VERSION` si le texte est une preuve stockée : à vérifier) ;
  « Gmail n'est pas configuré » formulé deux fois (`messages/web.py:114`, `system/admin.py:248`) ; pluriels « (s) »
  (`profil/letter_web.py:419`, `profil/translation_web.py:493`).
- **À vérifier avec Nicolas** : `Report.since` part de `changed_at` et non de `sent_on` (`candidatures/report.py`).

**Critère de sortie** : chaque point traité ou noté en §8 avec sa raison ; vérification globale verte.

## Hors H : rattaché à une étape existante (plan §8)

- **→ G2** : date limite sans année (`offres/analysis/rules.py:817`) : « avant le 15 janvier » lu le 20 décembre
  tombe dans l'année en cours. Année suivante si la date est passée ; nouvelle `RULES_VERSION`.
- **→ G6** : calculs dans les gabarits, vers les `rules.py` existants (`profil/templates/profil/sections/kit.html:30-32`
  compétences libres ; `offres/templates/offres/offer_body.html:10` refait `FRANCE_NAMES` ;
  `messages/templates/messages/row.html:61` refait `cited_employer`) ; découpage de `candidatures/dossier_web.py`
  (1 733 lignes, `_dossier_page` à 30 paramètres, `_cv_view` vers `targeting`, `_dossier` : une quinzaine de
  lectures et un `FOR UPDATE` pour lire, appelé 16 fois) ; « Envoyée » choisie depuis une candidature close mène à
  une étape sans formulaire (`candidatures/web.py:507-512`, `send_step.html`, à vérifier en recette) ;
  `stage_labels` posé deux fois dans les globales Jinja (`candidatures`, `messages`).
- **→ au fil de l'eau** (aucun bug) : verrou consultatif et `_in` copiés (`offres/sql.py`, `messages/sql.py`, et trois
  autres `_in`) ; `_editor` ×3, `_png` ×4, `LANGUAGES` ×4, `INVALID_ANSWER` ×2, `gmail_link` / `message_link`, `_host`
  ×2 ; découpage de `messages/sql.py` (1 631 lignes) ; normalisations des noms d'employeur divergentes
  (`offres/rules.py:21-41`, `messages/classification/rules.py:334-356`, change `CLASSIFY_VERSION` et passe par le
  test d'archive).
- **→ §5 (VPS, puis 50–100 utilisateurs)** : voir plan §8.
