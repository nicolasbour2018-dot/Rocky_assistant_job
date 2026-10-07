---
paths: rocky/system/**
---

# Module `system` — règles propres

Complète `AGENTS.md` ; ne répète pas ce qui s'y trouve. Décisions : `docs/decisions/B2-base-evenements.md`,
`docs/decisions/B3-comptes-sessions.md`.

## Schéma et migrations
- Une seule histoire Alembic, linéaire : `rocky/system/migrations/versions/NNNN_<slug>.py`, identifiant `NNNN`
  (`uv run alembic revision -m "<summary>" --rev-id NNNN`), écrite à la main.
- Une migration **appliquée** (commitée) ne se modifie jamais : on en ajoute une nouvelle.
- Toute table est déclarée sur `rocky.system.db.metadata`, dans le fichier d'accès SQL de son module, **listée dans
  `rocky/system/tables.py`** et créée par une migration. `test_declared_tables_match_migrations` échoue sinon.
- Noms explicites dans les migrations (`op.f("pk_…")`), conformes à la convention de `db.py`.
- Chaque migration a un `downgrade` complet ; `test_upgrade_and_downgrade_work_on_an_empty_database` le vérifie.

## Journal d'événements
- `append_event(conn, event)` s'appelle **dans la transaction de l'appelant**, avec le changement qu'il décrit ;
  il ne valide jamais lui-même.
- `events` ne subit jamais `UPDATE`, `DELETE` ni `TRUNCATE` (la base les refuse) : une correction est un nouvel
  événement. Ne jamais sonder le journal d'une vraie base hors d'une transaction annulée.
- Type d'événement : `<module>.<fait_au_passé>` (`offres.decision_recorded`) ; `account_id` quand un compte est
  concerné.

## Authentification (`rocky/system/auth/`)
- Tout le SQL des comptes, jetons et sessions est dans `auth/sql.py` ; aucun autre fichier ne lit ces tables.
- Un jeton (lien, cookie) n'est jamais stocké ni journalisé en clair : seule son empreinte (`token_hash`) l'est.
- Réponses neutres : connexion refusée et mot de passe oublié répondent pareil qu'un compte existe ou non.
- Une route ou une commande = un cas d'usage dans **une** transaction (`auth_transaction`) ; les e-mails partent
  **après** la validation, et un échec d'envoi est affiché.
- Pas d'inscription publique : un compte naît par `rocky-admin invite`.

## Modèles de langage (`rocky/system/llm/`, décisions `docs/decisions/C3-analyse.md`, `G4-assistant.md`)
- Un port (`JsonModel`, `port.py`) et un adaptateur HTTP par fournisseur, sans SDK : `gemini.py`, `anthropic.py`,
  `chat_completions.py` (OpenAI, Mistral). Délai borné, aucun réessai, réponse JSON contrainte par le schéma, dont
  l'appelant vérifie la forme ; chaque réponse rend ses jetons (`Completion`). Toute panne est une
  `LlmUnavailableError` avec sa raison en français.
- Le modèle se choisit **par type d'appel** (`CallType`) : `ROCKY_MODEL_PROVIDER` / `ROCKY_MODEL_NAME` par défaut,
  `ROCKY_<TYPE>_MODEL_PROVIDER` / `…_NAME` ensemble, une clé par fournisseur. Une route demande
  `model_for(request, CallType.X, account)` ; jamais un adaptateur construit à la main.
- **Tout appel est inscrit** dans `model_calls` (`calls.py`) : compte, type, fournisseur, modèle, issue, jetons, durée ;
  un modèle sans clé n'envoie rien et n'écrit rien. Un nouveau type d'appel = une valeur de `CallType`, son libellé
  dans `costs.py`, une migration de la contrainte.
- Coûts : jetons mesurés, euros **estimés** par `prices.py` (tarifs datés, sources en commentaire) ; un modèle sans
  tarif est « sans tarif », jamais 0 €.
- La clé ne figure jamais dans une raison, une URL ni un journal. Tests : faux modèle (`use_model` des tests web) ou
  `MockTransport`, jamais d'appel réel (AGENTS §7).

## Poste Rocky (`rocky/system/workstation.py`, `workstation_host.py`, décisions `docs/decisions/E5-lecture-assistee.md`, `D5-revisions-envoi.md`)
- Trois demandes sous les mêmes gardes : `/ouvrir` et `/lire` (lecture assistée, E5), `/preremplir` (**en sommeil**
  depuis la recette de D5, appelé seulement si `candidatures.web.PREFILL_ENABLED`).
- L'application ne lance jamais de navigateur visible : elle appelle le poste (`app.state.workstation`, installé par
  `system/web.py`, faux poste dans les tests), **hors de toute transaction**. Le poste tourne sur l'ordinateur
  (`uv run rocky-poste`), écoute sur `127.0.0.1`, refuse `Origin`, exige JSON et un `Host` connu.
- Le poste ne clique ni ne soumet jamais, ne résout aucun défi, ne retente rien ; chaque échec rend sa raison en
  français. Un onglet ouvert est nommé par un jeton aléatoire (`Tabs`), qui voyage dans le formulaire de l'écran ; il
  reste ouvert après la lecture. Un seul fil possède Playwright (ses objets appartiennent au fil qui les a créés).
- Tests : `Tabs` et `fill_form` dans un Chromium headless (`data:` et `set_content`) ; jamais de site réel.

## Planificateur (`rocky/system/scheduler.py`, décision `docs/decisions/C6-veille.md`)
- **Seul déclencheur** (D12) : aucune tâche par cron ni par un autre fil. Tâches quotidiennes à heure de Paris (une heure
  déjà passée au démarrage n'est pas rattrapée : l'écran le propose), tâches périodiques réveillables (`wake`), tâches
  ponctuelles (`submit`). Les tâches sont enregistrées par la composition (`system/web.py`, `_plan`).
- Une tâche en échec est journalisée avec sa trace et le fil continue ; l'état durable d'une tâche est en base.
- Démarré par le *lifespan* seulement si `scheduler_enabled` (vrai par `load_settings`, faux dans les `Settings` des
  tests) : un test n'a jamais de fil ; il appelle `tick()` sur un `Scheduler` sans tâches.
- Un module est prévenu d'un changement d'un autre par un crochet de `app.state` installé par la composition
  (`profile_changed`), jamais par un import de l'un dans l'autre.

## Heure et jour (`rocky/system/clock.py`, étape H2, `docs/decisions/H-revue-code.md`)
- Une seule horloge, `app.state.auth.clock` (instants UTC, réglée par les tests : `clock.now`) ; un seul jour, celui
  de Paris : `paris_day(instant)`, et `today_of(request)` dans une route. Jamais de `.date()` sur un instant UTC ni de
  `datetime.now(...)` hors de `utc_now` : entre minuit et 2 h, heure de Paris, le jour aurait un jour de retard.
- Une heure affichée passe par `paris_time` (filtre Jinja `paris_time`, posé par `system/web.py`).

## Erreurs métier (`rocky/system/errors.py`, étape H1, `docs/decisions/H-revue-code.md`)
- Une erreur dont le message (français) est pour l'utilisateur hérite de `UserFacingError` ; une route oubliée ne
  donne pas de 500 : `shell.show_user_error` la journalise et l'affiche (fragment reciblé sur `#erreur`, page entière
  sinon). Ce filet ne remplace pas le traitement local d'une route, qui garde le formulaire et son contexte.
- Un nom de fichier téléchargé passe par `shell.content_disposition` (nom hors latin‑1).
- Aucun refus muet sous HTMX (décision G6, A4, A9) : la coque fait afficher les réponses 4xx (`htmx-config` du
  gabarit) et `shell.show_refusals` change une réponse 4xx sans HTML (404 vide, JSON d'un formulaire refusé) en
  message dans `#erreur`, statut gardé. Un refus qui doit laisser un panneau ouvert répond `shell.refusal(...)`.
- Aucun conteneur ne porte `hx-target` ni `hx-swap` pour se relire lui-même : un élément vide et caché demande la
  relecture, sinon les liens et formulaires boostés qu'il contient en héritent (décision G6, A1–A3 ;
  `tests/system/test_inheritance.py`). Un geste qui quitte Rocky (Google) est une `Action(leaves=True)`, non boostée.
- `rocky.js` met en attente une touche frappée pendant une requête HTMX et la rejoue après `htmx:afterSettle`
  (décision G6, A8 ; `tests/system/test_browser.py`, Chromium headless). Il désactive le bouton d'une requête en vol
  et montre la barre d'attente après 300 ms ; il ouvre la fenêtre (`#fenetre`) quand un fragment arrive dans
  `#fenetre-contenu`, la ferme sur « Fermer » (`data-close-window`), Échap ou l'événement `fenetre-fermer`.
- Pièces partagées des écrans : `system/templates/ui.html` (`notice` pour un geste fait, `waiting` pour un appel long,
  `window` pour l'en-tête de la fenêtre). Un module ne refait pas sa propre version (décision G6, bloc 1).
- Un libellé suit le lexique de la décision G6 ; un nom écarté est refusé par `tests/system/test_lexicon.py`.

## Écrans transverses (`rocky/system/shell.py`, décision `docs/decisions/F1-ecrans-transverses.md`)
- `system` n'importe aucun module métier : ⚙️ Système se construit par des **registres** remplis à l'installation des
  modules (`add_system_cards`, `add_badge`). L'ordre des blocs est fixé dans
  `SYSTEM_ORDER` ; une clé inconnue est refusée.
- Un bloc est une `Card` (titre, lignes, détails, au plus une `Action`, `problem`, `polling`) : la coque choisit **le
  seul bouton principal** de l'écran (`main_action` : premier problème avec une action, sinon première action, sinon
  l'action de repli). Un module ne rend jamais lui-même de `btn-primary` dans une carte. Tout nouvel état d'un écran
  a son test « exactement un bouton principal ».
- Un geste d'un écran transverse qui doit y revenir passe `retour=systeme` (valeur fixe, jamais une URL).

## Assistant 🐾 (`rocky/system/assistant/`, décision `docs/decisions/G4-assistant.md`)
- Le tiroir est l'assistant : il se lit à son ouverture (`GET /tiroir`), jamais au rendu de la page. Un écran nomme son
  objet par `assistant/subject.html` (champ `objet` rattaché au formulaire `#rocky-question`) ; sans objet, ou celui
  d'un autre compte, c'est la conversation générale.
- Les faits viennent des modules par registres (`add_facts` par type d'objet, `add_summary` pour le compte, ordre
  `SUMMARY_KEYS`) ; un lecteur **ne fait que lire** (aucune écriture, aucun `FOR UPDATE` : `tests/candidatures/
  test_assistant.py`). Chaque fait a un identifiant `<type>.<champ>` unique, jamais un type d'événement
  (`candidatures.…` est réservé au journal : préfixe `compte.` pour le résumé).
- `ask` : plafond du jour de Paris, appel **hors transaction**, puis l'appel et le tour écrits ensemble ; une réponse
  sans fait connu est remplacée (`checked`). Aucun événement au journal pour une question (Q29).

## Cockpit (`rocky/system/cockpit.py`, décision `docs/decisions/G3-cockpit.md`)
- 🧭 Cockpit (clé de navigation `today`, route `/`) : chaque module inscrit ses `Parts` par `add_cockpit` (héros,
  instruments et séries, fil, phrases, suggestions, problèmes, lignes d'état, progression, nouveautés, célébrations) ;
  la coque dispose et choisit (`pick_hero` dans l'ordre `HERO_ORDER`, `main_gesture` : un problème avec un geste,
  sinon le héros), sans calculer de chiffre métier. Chaque état a son test « exactement un bouton principal ».
- Un geste fait depuis le cockpit répond `cockpit.changed()` (`HX-Trigger: cockpit-changed`) : le cockpit se relit
  en fragment, avec la visite précédente (`depuis`). Seul un chargement complet de `/` écrit le repère de visite.
- Une courbe d'instrument est un **flux** recalculable (dates déjà en base), jamais un stock passé reconstruit ; les
  semaines et les mois sont ceux de Paris (`system/periods.py`).

## Tests
- Fixtures de `tests/conftest.py` : `db` (transaction annulée) pour tout test SQL ; `migrated_engine` quand le
  test doit valider ; `empty_engine` pour un schéma vierge. Ne jamais écrire dans le schéma `public` de `test-db`.
- Le schéma de test est partagé par toute l'exécution et contient ce que les autres tests ont validé : ne jamais
  supposer une table vide ; filtrer sur ses propres identifiants, adresses uniques (`uuid4`).
- Faux adaptateurs partagés : `tests/<module>/…/fakes.py`, importés par `tests.<module>…fakes`.
- Jinja échappe l'apostrophe (`n'a` → `n&#39;a`) : en tenir compte dans les assertions sur le HTML.
