# Rocky — Règles pour les agents

## 1. Contexte

Rocky est en **refonte complète**. Le document normatif est `docs/rocky-refonte-plan-v2.md`.
Le nouveau Rocky est développé sur la branche **`refonte`**. L'ancien Rocky (Streamlit) reste l'outil
quotidien de Nicolas jusqu'à la bascule (étape F2) : il tourne dans Docker, lancé depuis le worktree
`../Rocky_v1` (tag `rocky-v1-streamlit`), jamais depuis ce dépôt.

Ordre des sources de vérité, en cas de conflit :
1. `docs/rocky-refonte-plan-v2.md` (décisions D1–D16, étapes, critères de sortie) ;
2. ce fichier ;
3. `docs/decisions/` (décisions détaillées prises pendant une étape) ;
4. le code du nouveau Rocky.

`docs/archive/` et l'ancien code sont **historiques et non normatifs** : on peut les lire pour porter
une logique, jamais les suivre comme règle. Les anciennes règles d'agent sont dans `docs/archive/rules-v1/`.

## 2. Méthode de travail

- Lire le plan v2 en entier, puis ne réaliser **qu'une seule étape** à la fois.
- Respecter le niveau de préparation de l'étape : direct, mode plan, ou *grill me* puis mode plan.
  Tout plan cite le critère de sortie de l'étape et liste les fichiers qu'il touche.
- Une étape est terminée quand son **critère de sortie est vérifié** et que la vérification globale est verte.
- Mettre à jour la colonne « État » de l'étape dans le plan.
- Un constat hors du périmètre de l'étape est **noté** dans la section 8 du plan (avec l'étape concernée), pas corrigé.
- Les décisions métier obtenues avec Nicolas sont consignées dans `docs/decisions/<étape>-<sujet>.md` avant l'implémentation.
- Une étape = une session de travail = un commit (ou une petite série de commits cohérente), **poussé** sur `origin`
  à la fin de l'étape : GitHub est la source de vérité du code.
- En cas de doute sur une règle métier : demander à Nicolas plutôt qu'inventer.

## 3. Écritures

| Chemin | Droit |
|---|---|
| `rocky/` (`system/`, `profil/`, `offres/`, `candidatures/`, `messages/`) | écriture — nouveau code |
| `tests/<module>/`, `tests/conftest.py` | écriture — tests du nouveau code |
| `docs/` hors `docs/archive/` | écriture — plan (colonne « État », section 8), `docs/decisions/`, `docs/procedures/`, docs du nouveau code |
| `pyproject.toml`, `uv.lock`, `docker-compose.yml`, `.env.example`, `README.md`, `.gitignore` | écriture — fichiers de racine du nouveau Rocky ; `uv.lock` n'est modifié que par `uv` (`uv add`, `uv lock`), jamais à la main |
| `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.codex/` | écriture — configuration des agents, alignée sur le plan v2 |
| `.github/workflows/` | écriture — vérification sur GitHub ; elle exécute la même commande que la vérification locale, sans secret |
| `dashboard/`, `database/`, `scripts/`, `cron/`, `templates/`, `deployment/`, `assets/`, `.streamlit/`, `output/`, `Dockerfile`, `.dockerignore`, `requirements.txt`, `tests/test_*.py` (tests à plat) | **lecture seule** — ancien Rocky, retiré en F2 |
| `../Rocky_v1/` (worktree de l'ancien Rocky, avec son `compose.yaml` non versionné, son `.env` et son `output/` d'hôte) | **lecture seule** |
| `backups/` (archive A1), `data/`, `logs/`, `docs/archive/` | **lecture seule** — seul `docs/procedures/a1-archive/archive.sh` écrit dans `backups/` |
| `.env` (sauf `.env.example`), `.secrets/`, `credentials*.json`, `token*.json`, clés d'API | **interdit**, même en lecture, et jamais versionné |

Également interdit :
- toucher la base PostgreSQL de l'ancien Rocky (`job-assistant-postgres`) ou ses volumes Docker, sauf lecture
  explicitement demandée par l'étape ;
- créer à la racine un fichier absent du tableau ;
- modifier les décisions D1–D16 du plan sans validation explicite de Nicolas ;
- ajouter une dépendance sans justification dans le plan ou la décision de l'étape.

**Garde-fou** : `.claude/hooks/guard_paths.py` (hook `PreToolUse` de Claude Code) refuse les outils de fichiers
qui écrivent dans une zone en lecture seule et toute mention d'un secret, y compris dans une commande shell.
Un refus ne se contourne pas (pas d'écriture par `sed`, `cp` ou script à la place) : on demande à Nicolas.
Les écritures par commande shell restent régies par ce tableau. Cas de contrôle :
`/usr/bin/python3 .claude/hooks/check_guard_paths.py`.

## 4. Architecture (rappel du plan, section 3)

```
rocky/
  system/        base, config, comptes & sessions, événements, LLM, fichiers, planificateur, layout web
  profil/        profil unique FR/EN, pistes, compétences, CV maître
  offres/        sources, import URL, analyse d'annonce, scoring, veille, décisions
  candidatures/  dossier, statuts, documents, révisions, envoi, suivi
  messages/      Gmail, classification, alertes emploi, décisions sur les candidatures
tests/
  <module>/      un dossier par module, miroir de rocky/ (les tests à plat tests/test_*.py sont ceux de l'ancien Rocky)
docs/
```

- Modules métier (`profil`, `offres`, `candidatures`, `messages`) sur un socle technique `system`.
  Un module utilise `system` ; il ne recopie pas ce qui s'y trouve et n'accède pas au SQL d'un autre module.
- Forme interne d'un module : règles métier (fonctions pures, dataclasses) → cas d'usage → accès SQL du module
  → routes FastAPI et gabarits HTMX.
- Les cas d'usage sont testables avec de faux adaptateurs, sans FastAPI, SQL, Gmail ni LLM.
- Pas d'interface par table, pas de hiérarchie de classes sans besoin démontré.
- Toute opération qui écrit plusieurs choses liées le fait **dans une seule transaction** et de façon **idempotente**.
- Toute décision ou transition est inscrite dans le journal d'événements (ajout seul).
- **Aucune exception avalée en silence** : une erreur est soit remontée, soit enregistrée et rendue visible.
- Une fonction de calcul (score, classification) n'a pas d'effet de bord ; l'écriture est une opération nommée séparée.
- PostgreSQL uniquement, y compris pour les tests (PostgreSQL de test). Schéma géré par Alembic.
- Règles d'agent par module : `.claude/rules/<module>.md` (`paths: rocky/<module>/**`), créées quand le module
  naît, uniquement pour ce qui n'est pas déjà dans ce fichier.

## 5. Conventions

| Élément | Langue |
|---|---|
| Code : identifiants, docstrings, commentaires, messages d'erreur internes, noms de tests | anglais |
| Messages de commit et descriptions de PR | anglais |
| Noms des modules métier (D13) : `profil`, `offres`, `candidatures`, `messages` | français (fixés par le plan) |
| Textes de l'interface, documentation (`docs/`, README), décisions | français |

- Commits : `<type>(<étape>): <summary>` à l'impératif, par ex. `feat(B2): add append-only event journal`.
  Types : `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.
- Branche de travail : `refonte` ; une PR vers `main` seulement à la bascule, sauf demande de Nicolas.
- Poste de travail : le dépôt vit dans `~/Developer/Rocky_assistant_job`, l'ancien Rocky dans `~/Developer/Rocky_v1`,
  **hors iCloud**. Ne jamais placer le dépôt dans le Bureau, Documents ou un dossier synchronisé (incident A1/A2 :
  fichiers déchargés puis supprimés par iCloud).

## 6. Invariants produit

- Rocky **ne postule jamais** à la place de l'utilisateur : préremplissage avec confirmation, envoi final manuel.
- Gmail en **lecture seule** ; aucun élargissement de scope.
- Aucun contournement des protections des sites sources.
- Le scoring est **déterministe et explicable** ; le LLM n'attribue jamais le score.
- Le scoring stocke ses caractéristiques, preuves et version de règles ; les décisions de l'utilisateur
  sont conservées avec leur raison (données d'entraînement, décision D14).
- Aucune offre collectée n'est jetée : une offre sous le seuil est conservée avec son motif.

## 7. Réseau, API et données de test

- Tests : aucun appel réseau ni fournisseur LLM ; utiliser des jeux de données enregistrés et des faux adaptateurs.
- Appels réels (sources, Gmail, Gemini) seulement quand l'étape l'exige, avec l'accord de Nicolas.
- Les jeux de test issus de l'archive sont anonymisés si nécessaire et ne contiennent aucun secret.

## 8. Vérification

- Vérification globale : `docker compose run --rm --build check` (ruff format, ruff check, mypy strict, pytest
  sur la base de test) — doit rester verte en moins de 2 min.
- Tests seuls, boucle rapide : `docker compose up -d test-db` puis `uv run pytest` (idem `uv run ruff check`, `uv run mypy`).
- Lancer l'application : `docker compose up -d --build --wait app` → `http://127.0.0.1:8000/health`
  (le service `migrate` amène d'abord la base à la dernière migration).
- Migrations sur la base de développement : `docker compose run --rm --build migrate` (`upgrade head`) ;
  `docker compose run --rm migrate alembic <commande>` pour les autres (`current`, `downgrade -1`…).
  Règles d'écriture des migrations : `.claude/rules/system.md`.
- Inviter une personne (seule façon de créer un compte) : `docker compose run --rm app rocky-admin invite <email>` ;
  `--print-link` affiche le lien d'activation au lieu de l'envoyer (aucun e-mail ne part).
- Diagnostic des sources (vraie collecte, rien n'est écrit) :
  `docker compose run --rm app rocky-admin sources <email> [--piste <nom>] [--detail]`.
- Garde-fou des agents : `/usr/bin/python3 .claude/hooks/check_guard_paths.py`
- Sur GitHub : `.github/workflows/verification.yml` exécute la vérification globale à chaque push sur `refonte` et
  sur chaque PR. Une étape n'est terminée que si ce passage est vert aussi.

Précautions (détails : `docs/decisions/B1-squelette.md`) :
- **ne jamais lancer `docker compose config`** : il affiche les valeurs interpolées depuis le `.env` ;
- aucune commande n'a besoin de nommer le `.env` : Compose le lit seul ;
- une base de test injoignable fait échouer les tests, elle ne les fait jamais ignorer ;
- dépendances ajoutées avec `uv add` (ou `uv add --dev`), jamais avec `pip`.

## 9. Standard de revue

Toute revue ou tout audit sépare :
1. les faits observés (avec références fichier/module) ;
2. les risques déduits ;
3. les recommandations, proportionnées au projet.

Le relecteur conteste toute affirmation non étayée par le dépôt.
