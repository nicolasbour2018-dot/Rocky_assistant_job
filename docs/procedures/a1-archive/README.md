# Procédure d'archivage de l'ancien Rocky

Étape A1 du plan de refonte v2 ; réutilisée pour l'export final en F2. Décisions : `docs/decisions/A1-archive.md`.

```bash
docs/procedures/a1-archive/archive.sh                 # → backups/rocky-v1-<AAAAMMJJ>/
docs/procedures/a1-archive/archive.sh /chemin/cible   # autre dossier (jamais écrasé s'il existe)
```

## Prérequis

- Conteneurs `job-assistant-postgres` et `rocky-assistant-local` démarrés ; port `127.0.0.1:55432` libre.
- `.venv` du dépôt (pandas, pyarrow, SQLAlchemy, psycopg2) et `jupyter nbconvert` (`/opt/anaconda3`).
  Variables surchargeables : `PYTHON`, `JUPYTER`, `LIVE_PG`, `APP`, `PG_USER`, `RESTORE_PORT`.
- Aucun secret lu : pas de `.env` ; l'accès PostgreSQL passe par la socket locale du conteneur ;
  la base de contrôle a un mot de passe aléatoire éphémère.

## Déroulé

1. Empreinte de chaque table (lignes + md5 du contenu), dump, nouvelle empreinte : si la base a bougé
   pendant le dump, on recommence (3 tentatives).
2. Restauration dans un conteneur `postgres` éphémère, base vierge ; comparaison table par table
   des empreintes, de la table `users` et des rôles → `verification/restauration.txt`. Échec = arrêt.
3. Exports Parquet + CSV depuis la **copie restaurée** (`export_tables.py`).
4. Copie des documents par flux `tar` (les montages bind Docker échouent sous macOS, OSError 35) :
   volume Docker, `./output` et `./data` de l'hôte, sans `gmail/` ni `browser_profile/` ; rapport des documents référencés (`verifier_documents.py`).
5. Exécution de `lecture_exports.ipynb` ; `SHA256SUMS` ; suppression du conteneur éphémère.

## Fichiers

| Fichier | Rôle |
|---|---|
| `archive.sh` | orchestration |
| `export_tables.py` | liste des tables par catégorie, conversions, `manifest.json` |
| `verifier_documents.py` | présence des documents référencés en base |
| `lecture_exports.ipynb` | notebook de lecture et de contrôle, copié puis exécuté dans l'archive |
| `README_archive.md` | README copié à la racine de l'archive (dictionnaire des tables) |
