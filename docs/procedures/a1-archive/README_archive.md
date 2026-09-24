# Archive de l'ancien Rocky (Streamlit)

Produite par `docs/procedures/a1-archive/archive.sh` (étape A1 du plan de refonte v2).
Code correspondant : tag Git `rocky-v1-streamlit`.

**Contient des données personnelles et des empreintes de mots de passe : ne jamais versionner ni partager.**

## Arborescence

| Chemin | Contenu |
|---|---|
| `db/job_assistant.dump` | `pg_dump -Fc` de la base en service (source des exports) |
| `db/rocky.dump` | `pg_dump -Fc` de l'ancienne base `rocky` (dump seul) |
| `db/globals.sql` | rôles PostgreSQL, **sans** mot de passe |
| `db/sqlite/` | anciens fichiers SQLite `rocky.db` (volume et hôte) |
| `exports/parquet/`, `exports/csv/` | une table par fichier ; `exports/manifest.json` liste lignes, colonnes, types |
| `documents/volume/` | volume Docker `rocky-assistant-data` (`/data`) : CV, lettres, profils |
| `documents/hote/output/` | `./output` de l'hôte : candidatures d'août (chemins relatifs `output/…`) |
| `documents/hote/data/` | ancien `./data` de l'hôte |
| `verification/` | empreintes live / restaurées, `restauration.txt`, `documents.txt`, notebook exécuté |
| `SHA256SUMS` | vérifier avec `shasum -a 256 -c SHA256SUMS` |

Exclus : jetons OAuth Gmail (`*/gmail/`), profil navigateur (`*/browser_profile/`), journaux.
Absents des exports (présents dans le dump) : `user_sessions`, `account_tokens`, `users.password_hash`.

## Dictionnaire des exports

| Catégorie | Table | Remarques |
|---|---|---|
| Offres | `job_offers` | faits de l'annonce + `status` de l'ancien Rocky |
| Scores | `job_matches` | dernier score par (offre, profil) ; `breakdown` en JSON |
| Scores | `job_match_history` | historique des scores avec `scoring_version` |
| Rattachements | `profile_jobs` | offre ↔ profil qui l'a trouvée |
| Candidatures | `applications` | statut, chemins des documents, notes |
| Candidatures | `application_documents` | révisions de documents (chemin + sha256) |
| Candidatures | `application_browser_sessions` | préremplissages navigateur |
| Événements | `application_events` | transitions de statut (`source` : ui, gmail…) |
| Événements | `watch_runs` | veilles : statut, compteurs, erreurs par source |
| Mails et décisions Gmail | `email_messages` | `classification`, `confidence`, `matched_application_id`, `processing_state`, `reason`, `classification_manual` |
| Profil | `candidate_profiles`, `profile_localizations`, `candidate_skills`, `profile_projects`, `profile_documents`, `profile_analyses`, `monitoring_notes` | source du réimport B5 |
| Comptes | `users` | sans `password_hash` |

Conversions : JSONB → texte JSON ; tableaux → `list<string>` (Parquet) ou texte JSON (CSV) ;
`numeric` → float64 ; horodatages en UTC.

## Restaurer

```bash
docker run -d --name rocky-restore -e POSTGRES_USER=job_user -e POSTGRES_PASSWORD=... postgres:16
docker exec -i rocky-restore psql -U job_user -d postgres < db/globals.sql   # « role exists » attendu
docker exec rocky-restore createdb -U job_user job_assistant
docker exec -i rocky-restore pg_restore -U job_user -d job_assistant < db/job_assistant.dump
```
