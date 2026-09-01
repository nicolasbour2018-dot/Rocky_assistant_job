# 0007 – Persistance : SQLite seul, ORM SQLAlchemy 2.0, Alembic

Date : 2026-09-01. Statut : acceptée.

## Contexte

113 requêtes SQL écrites à la main dans `text()` (95 dans `repository.py`,
18 dans `auth.py`), aucun ORM, aucune migration. Le schéma vit en trois
exemplaires : `schema.sql`, `schema_sqlite.sql` et le dict `REQUIRED_SCHEMA`
de `database.py`. Une base existante est validée puis rejetée, jamais
modifiée. La dualité PostgreSQL / SQLite coûte 12 branches de dialecte et
les 19 `noqa: S608`. L'isolation par utilisateur repose sur 72 gardes
manuelles. `pandas` est soudé à la persistance : 9 méthodes renvoient des
DataFrames, la même table ressort en DataFrame, en dict ou en dataclass selon
la méthode. 20 des 27 fichiers de test tournent sur SQLite.

## Décision

SQLite est la seule base, en mode WAL, un fichier dans le dossier de
stockage, sauvegarde par copie. PostgreSQL disparaît.

Modèles SQLAlchemy 2.0 déclaratifs et typés (`Mapped[]`), une seule source de
schéma. Alembic pour les migrations, avec `render_as_batch=True` pour les
`ALTER` que SQLite ne sait pas faire en place.

Le dépôt renvoie des objets typés, jamais de DataFrame ni de dict brut.
`pandas` reste autorisé dans la couche web pour les statistiques, jamais
dans `adapters/db`.

Le filtre par utilisateur est posé à un seul endroit, dans la session ou la
requête de base, plus dans chaque méthode. Le SQL de `auth.py` rejoint la
couche `adapters/db` ; la règle « tout le SQL au même endroit » redevient
vraie.

## Conséquences

- `TEXT[]` et `JSONB` deviennent des colonnes `JSON`. Les 12 branches et les
  19 `noqa` disparaissent, ainsi que le parsing défensif d'`ensure_list` dans
  l'UI.
- `database/schema*.sql` et `REQUIRED_SCHEMA` sont remplacés par les
  migrations ; une base existante se migre au lieu d'être rejetée.
- Les tests gardent SQLite sous `tmp_path`, sans service à lancer.
- `psycopg2-binary` et `pandas-stubs` quittent les dépendances.
