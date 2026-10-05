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

## Modèle de langage (`rocky/system/llm.py`, décision `docs/decisions/C3-analyse.md`)
- Un seul adaptateur (`GeminiModel`, protocole `JsonModel`) : délai borné, aucun réessai, réponse JSON dont l'appelant
  vérifie la forme ; toute panne est une `LlmUnavailableError` avec sa raison en français.
- La clé ne figure jamais dans une raison, une URL ni un journal. Sans clé, les fonctions qui en dépendent le disent.
- Tests : faux modèle ou `MockTransport`, jamais d'appel réel (AGENTS §7).

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

## Tests
- Fixtures de `tests/conftest.py` : `db` (transaction annulée) pour tout test SQL ; `migrated_engine` quand le
  test doit valider ; `empty_engine` pour un schéma vierge. Ne jamais écrire dans le schéma `public` de `test-db`.
- Le schéma de test est partagé par toute l'exécution et contient ce que les autres tests ont validé : ne jamais
  supposer une table vide ; filtrer sur ses propres identifiants, adresses uniques (`uuid4`).
- Faux adaptateurs partagés : `tests/<module>/…/fakes.py`, importés par `tests.<module>…fakes`.
- Jinja échappe l'apostrophe (`n'a` → `n&#39;a`) : en tenir compte dans les assertions sur le HTML.
