# A2 — Cadrage écrit

Date : 24/09/2026 · Étape : A2 (plan v2)

Critère de sortie : « Un agent sait sans ambiguïté ce qu'il a le droit de toucher. »

## Décisions (validées avec Nicolas)

| Sujet | Décision | Raison |
|---|---|---|
| Anciennes règles `.claude/rules/` | Archivées dans `docs/archive/rules-v1/` ; de nouvelles règles seront créées module par module à partir de B1 | Les 13 règles visaient l'ancien code et plusieurs contredisent le plan v2 (SQLite en test, `repository.py` unique, pas de migrations, poids du scoring). Elles se chargeaient dès qu'un agent lisait l'ancien code pour le porter. |
| Garde-fou | Hook `PreToolUse` Claude Code : `.claude/hooks/guard_paths.py` ; 34 cas de contrôle dans `check_guard_paths.py` | Rendre le tableau d'écritures de `AGENTS.md` vérifiable par la machine, pas seulement lisible. |
| Fichiers d'agents à la racine | `brief.md`, `harness.yaml`, `project.yaml` → `docs/archive/audit-harness/` ; `AGENTS_old.md` → `docs/archive/AGENTS-v1.md` ; `.gitkeep` supprimé | Fichiers de la mission d'audit, non prévus par le plan ; la validation de `project.yaml` visait un rapport déjà archivé. |
| Ancien Rocky | Worktree `~/Developer/Rocky_v1` détaché sur le tag `rocky-v1-streamlit`, avec son `compose.yaml` (non versionné, exclu par `.git/info/exclude`), son `.env` et son `output/` d'hôte. Le conteneur `rocky-assistant-local` en est relancé : `docker compose -p rocky-v1 up -d --no-build` | La branche `refonte` peut évoluer (racine, `pyproject.toml`, README) sans toucher ce qui tourne. `--no-build` réutilise l'image `bbfb0e7443e2`, dont le code est identique au tag : aucune dérive de dépendances. Données inchangées (volumes nommés). |
| Nommage | « Rocky v1 » = la génération Streamlit actuelle (tag `rocky-v1-streamlit`, worktree `Rocky_v1`, archive `rocky-v1-<date>`) ; le nouveau Rocky n'a pas de numéro tant qu'il n'a pas remplacé l'ancien | Voir « Nommage des versions » ci-dessous. |
| Langue | Code (identifiants, docstrings, commentaires, messages internes, tests) et commits en **anglais** ; noms des modules métier (D13), interface et documentation en **français** | Choix de Nicolas ; les noms de modules restent ceux de D13. |
| Tests | Nouveaux tests dans `tests/<module>/` ; les tests à plat `tests/test_*.py` sont ceux de l'ancien Rocky, en lecture seule | Séparer les deux générations sans déplacer l'ancien code avant F2. |
| Source de vérité | GitHub pour le code (chaque étape commitée et poussée) ; le dépôt vit dans `~/Developer/`, **hors iCloud** | Incident iCloud du 24/09 (voir `A1-archive.md`). Seuls `.env`, `.secrets/` et `backups/` dépendent du disque local. |

## Nommage des versions

Termes déjà présents dans le dépôt et l'historique, qui ne désignent **pas** une génération de Rocky :

| Terme | Sens réel |
|---|---|
| `dashboard_v2.py`, `yolo-local-v2`, `test_yolo_v2.py`, dump `rocky_pre_yolo_v2_*` | itérations internes de l'interface Streamlit, toutes incluses dans Rocky v1 |
| ATS V1/V2/V3 (`ats.py`, `ats_v3.py`, `page_ats_v3.py`) | versions du banc d'analyse de CV |
| `cv_template_v1.json` | version d'un gabarit de CV |
| plan v1 / plan v2 (`docs/archive/rocky-refonte-plan.md`, `docs/rocky-refonte-plan-v2.md`) | versions du document de refonte |
| `matching-v1` (`scoring_version` de `job_match_history`) | règles de score de Rocky v1 ; le nouveau scoring (C4) portera un nom distinct, pas `matching-v2`, pour ne pas suggérer une continuité |
| `apec-offer-extraction-v1` (`schema_version`) | format de l'extraction détaillée APEC |
| `ATS V2` (`scripts/test_ats_v2.py`) | voir ATS ci-dessus |
| `~/Desktop/Projets_IA/Rocky_assistant_job_archive` | toute première version de Rocky, gardée à part par Nicolas pour des essais manuels ; **hors périmètre de la refonte**, les agents n'y touchent pas |
| `~/Desktop/Projets_IA/Archives/Rocky_assistant_job-main` | ancienne copie de travail, antérieure au déplacement du dépôt |

Règle : « v1 » seul, dans un nom de dossier, de tag, de branche ou d'archive, désigne la génération Streamlit.
Les autres numéros gardent un préfixe explicite (ATS, plan, scoring, gabarit). `docs/archive/AGENTS-v1.md` et
`docs/archive/rules-v1/` suivent cette règle : ce sont les règles d'agent de Rocky v1.

## Limites connues

- Le hook ne couvre que Claude Code. Codex n'a que `AGENTS.md` (son hook `codex-path-rules` lit `.claude/rules/`,
  désormais vide).
- Les écritures par commande shell dans l'ancien code ne sont pas bloquées (analyse de commandes trop fragile) ;
  seules les mentions de secrets le sont.
- Le hook ne s'active que dans une session Claude Code ouverte dans `~/Developer/Rocky_assistant_job`.
