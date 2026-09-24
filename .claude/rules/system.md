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

## Tests
- Fixtures de `tests/conftest.py` : `db` (transaction annulée) pour tout test SQL ; `migrated_engine` quand le
  test doit valider ; `empty_engine` pour un schéma vierge. Ne jamais écrire dans le schéma `public` de `test-db`.
- Le schéma de test est partagé par toute l'exécution et contient ce que les autres tests ont validé : ne jamais
  supposer une table vide ; filtrer sur ses propres identifiants, adresses uniques (`uuid4`).
- Faux adaptateurs partagés : `tests/<module>/…/fakes.py`, importés par `tests.<module>…fakes`.
- Jinja échappe l'apostrophe (`n'a` → `n&#39;a`) : en tenir compte dans les assertions sur le HTML.
