# B2 — Base et événements

Date : 24/09/2026 · Étape : B2 (plan v2)

Critère de sortie : « `upgrade` / `downgrade` fonctionnent sur base vide. »

## Décisions

| Sujet | Décision | Raison |
|---|---|---|
| Accès SQL | **SQLAlchemy Core** : tables déclarées en Python sur un `metadata` commun, requêtes composées (`select`, `insert`), pas d'ORM ; pilote psycopg 3 (choix de Nicolas) | Requêtes dynamiques (filtres de listes) sans concaténer du SQL ; un test compare les tables déclarées aux migrations et signale toute dérive. |
| URL de connexion | `ROCKY_DATABASE_URL` reste une URL libpq (`postgresql://…`) ; `create_db_engine` impose le pilote `postgresql+psycopg` | L'URL reste utilisable par `psql` ; sans pilote explicite, SQLAlchemy chercherait psycopg2, absent. |
| Convention de nommage | `metadata` avec convention de noms pour clés, index, contraintes (`pk_`, `fk_`, `ix_`, `uq_`, `ck_`) | Noms déterministes : une migration peut toujours nommer ce qu'elle supprime. |
| Configuration d'Alembic | `[tool.alembic]` dans `pyproject.toml`, `script_location = "rocky.system:migrations"` ; aucun `alembic.ini` | Alembic ≥ 1.16 le permet ; un `alembic.ini` serait un fichier de racine hors tableau. |
| Révisions | Une seule histoire linéaire dans `rocky/system/migrations/versions/` ; identifiants `NNNN` fixés à la création (`0001_create_events.py`) ; migrations écrites à la main ; une migration appliquée ne se modifie jamais | Ordre lisible ; le test de cohérence tient lieu de génération automatique. |
| Exécution des migrations | Service Compose `migrate` (image de l'application, `alembic upgrade head`) ; `app` démarre seulement s'il réussit | L'application ne tourne jamais sur un schéma en retard ; un échec de migration est visible (code de sortie, journaux). |
| Journal d'événements | Table `events` : `id` (ordre), `occurred_at`, `type` (`<module>.<fait>`, par ex. `offres.decision_recorded`), `actor` (`user`, `rule`, `ai`, `system`), sujet facultatif (`subject_type`, `subject_id`, les deux ou aucun), `payload` JSON | Toute décision ou transition y est inscrite (`AGENTS.md` §4) ; le sujet servira aux chronologies ; les acteurs reprennent ceux de `job_decisions` (plan §3). |
| Ajout seul | Déclencheurs qui refusent `UPDATE`, `DELETE` et `TRUNCATE` sur `events` | `rocky_app` est propriétaire de la table : retirer un privilège ne l'empêcherait pas de se le rendre. Le déclencheur protège des erreurs, pas d'une désactivation délibérée. |
| Transactions | `append_event(conn, event)` n'ouvre ni ne valide de transaction : l'appelant écrit l'événement dans la transaction du changement qu'il décrit | Un changement et son événement réussissent ou échouent ensemble (défaut de l'ancien Rocky : statut Gmail changé avant l'enregistrement du message). |
| Périmètre | Pas de compte sur l'événement (B3 l'ajoute avec la table `accounts`) ; pas de fonction de lecture (écrite avec le premier écran qui l'affiche) | Ne pas anticiper les étapes suivantes. |
| Isolation des tests | Un schéma PostgreSQL unique par exécution de pytest, migré par Alembic puis supprimé ; chaque test dans une transaction annulée ; le test des migrations sur son propre schéma vide | Constat B1 → B2 : `test-db` reste démarré entre deux vérifications ; deux exécutions simultanées (poste et `check`) ne se gênent pas. |

## Dépendances ajoutées

| Dépendance | Groupe | Justification |
|---|---|---|
| `sqlalchemy` | exécution | accès SQL des modules ; base d'Alembic |
| `alembic` | exécution | migrations (D9), lancées par le service `migrate` dans l'image de l'application |

## Mesures

Mesuré le 24/09/2026 :

| Contrôle | Résultat |
|---|---|
| **Critère de sortie**, schéma de test vide : vide → `upgrade head` → `downgrade base` → `upgrade head` | vert (`test_upgrade_and_downgrade_work_on_an_empty_database`) |
| **Critère de sortie**, base de développement vide : `migrate` → `0001`, puis `alembic downgrade base` | `events` et `rocky_forbid_event_change` créées puis supprimées ; reste `alembic_version` |
| Tables déclarées = migrations (`compare_metadata`) | vert ; une colonne ajoutée seulement dans le code fait échouer le test (contrôle volontaire, retiré) |
| `UPDATE` et `DELETE` sur `events` en `psql` | refusés : `events is append-only: UPDATE refused` |
| `docker compose up -d --build --wait app` | `migrate` terminé (code 0), puis `app` `healthy`, `/health` → 200 |
| Vérification globale, après ajout des dépendances (image reconstruite, `test-db` démarré) | 26 s, 28 tests verts |
| Vérification globale après modification de code | 4,3 s |
| Schémas `test_…` restants dans `test-db` après une exécution | aucun |

La sonde `psql` a laissé un événement permanent dans la base de développement ; la base a été remise à zéro par
`downgrade base` puis `upgrade head` (la suppression de la table n'est pas bloquée par les déclencheurs).
