# B1 — Squelette

Date : 24/09/2026 · Étape : B1 (plan v2)

Critère de sortie : « Vérification verte en moins de 2 min. »

## Décisions (validées avec Nicolas)

| Sujet | Décision | Raison |
|---|---|---|
| Environnement Python | **uv**, installé sur le poste avec Homebrew ; `uv.lock` versionné à la racine (ajouté au tableau d'`AGENTS.md`) ; Python 3.13 géré par uv (`python-preference = "only-managed"`) | Versions identiques sur le poste et dans l'image. `main` utilisait déjà uv. `"managed"` ne suffit pas : faute de Python géré déjà installé, uv avait pris celui d'Anaconda présent dans le `PATH`. |
| Service `app` en B1 | FastAPI minimal : fabrique `create_app` et route `GET /health` | Prouver dès B1 que l'image démarre et charge sa configuration ; FastAPI est acté (D6) et nécessaire dès B3. La coque web (Jinja, HTMX, layout) reste en B4. |
| Dockerfile | Écrit en ligne dans `docker-compose.yml` (`build.dockerfile_inline`) ; à extraire en `Dockerfile` en F2 | `Dockerfile` et `.dockerignore` à la racine sont ceux de l'ancien Rocky, en lecture seule jusqu'en F2, et aucun autre fichier de racine n'est permis. Le `.dockerignore` hérité s'applique et exclut déjà les secrets, les données et les archives. |
| Variables d'environnement | Préfixe `ROCKY_` ; aucun `env_file` : chaque service reçoit des variables explicites | Le `.env` de ce dépôt contient encore les variables de l'ancien Rocky (`DATABASE_URL`, `DB_*`) ; les injecter en bloc risquerait de connecter le nouveau code à l'ancienne base. |
| PostgreSQL | Image `postgres:18` (celle de la CI de `main`) ; base de développement en volume nommé `rocky-db-data`, non publiée sur l'hôte | Constat A1 : données en volumes nommés. |
| Rôles PostgreSQL | Administrateur `rocky_admin` réservé à l'initialisation ; l'application et les tests utilisent `rocky_app` (`NOSUPERUSER NOCREATEDB NOCREATEROLE`), propriétaire de sa base | Constat A1 : l'ancien Rocky tournait avec un superutilisateur. Un test vérifie que le rôle de connexion n'est pas superutilisateur. |
| PostgreSQL de test | Service `test-db` : même image et même script de rôles ; données en `tmpfs`, `fsync` et `synchronous_commit` désactivés ; identifiants fixes non secrets ; publié sur `127.0.0.1:55432` | Base jetable et locale : la vitesse prime sur la durabilité. La publication permet de lancer pytest depuis le poste. |
| Mots de passe de développement | `ROCKY_DB_ADMIN_PASSWORD` et `ROCKY_DB_APP_PASSWORD`, dans le `.env` de Nicolas ; interpolés en `${…:-}` | Compose interpole tout le fichier avant de choisir les services : une variable obligatoire (`${…:?}`) manquante empêcherait aussi la vérification, qui n'en a pas besoin. Une valeur vide fait échouer PostgreSQL ou le script de rôles avec un message explicite. |
| Vérification | Service `check` (profil `tools`) : `ruff format --check`, `ruff check`, `mypy`, `pytest`, contre `test-db` ; code monté en lecture seule (montages bind) | Une seule commande, sans outil requis sur le poste hors Docker. Les montages bind vérifient le constat A1 (iCloud). |
| Vérification sur GitHub | Workflow `.github/workflows/verification.yml` : `docker compose run --rm --build check` à chaque push sur `refonte` et sur chaque PR ; `.github/workflows/` ajouté au tableau des écritures d'`AGENTS.md` (arbitrage de Nicolas, 24/09) | Garantit que le code **poussé** passe la vérification, pas seulement le poste d'un agent (fichier oublié dans un commit, dérive locale). Même commande qu'en local : aucune seconde définition de la base de test ni des versions. Aucun secret requis. Sert de condition à la PR de bascule (protection de `main`, réglée en F2). |
| Lint | ruff, sélection de règles reprise de `origin/main`, portée limitée à `rocky/` et `tests/` hors anciens tests | Règles déjà rodées sur le projet. |
| Typage | mypy en mode `strict` sur `rocky/` et `tests/` | Nouveau code : autant commencer strict que devoir durcir plus tard. |
| Collecte des tests | `tests/conftest.py` ignore les tests à plat `tests/test_*.py` ; `--import-mode=importlib` | Constat A2 : seuls les tests `tests/<module>/` du nouveau Rocky sont collectés. Le mode `importlib` évite les conflits entre fichiers de test homonymes de deux modules. |
| Avertissements | `filterwarnings = ["error"]` dans pytest | Une dépréciation d'une dépendance fait échouer les tests au lieu de défiler (cas rencontré : `httpx` → `httpx2`). |
| Base de test injoignable | Échec explicite, jamais de test ignoré | Pas d'erreur avalée en silence (`AGENTS.md` §4). |
| Isolation entre tests | Reportée en B2 | Pas encore de schéma. |
| Nom du projet Compose | `rocky` ; application publiée sur `127.0.0.1:8000` | Distinct de `rocky-v1` et `job-assistant` ; ports 8501 et 8081 déjà pris. |

## Dépendances ajoutées

| Dépendance | Groupe | Justification |
|---|---|---|
| `fastapi` | exécution | D6 ; route `/health` dès B1 |
| `uvicorn` | exécution | serveur ASGI de l'application |
| `psycopg[binary]` | exécution | D5 (PostgreSQL seul) ; utilisé par les tests dès B1, par l'application à partir de B2 |
| `ruff`, `mypy`, `pytest` | dev | vérification globale (B1) |
| `httpx2` | dev | requis par le `TestClient` de FastAPI ; Starlette 1.7 déclare `httpx` obsolète pour cet usage |

## Précautions

- Ne jamais lancer `docker compose config` : cette commande affiche les valeurs interpolées depuis le `.env`.
- Aucune commande n'a besoin de nommer le `.env` : Compose le lit seul pour l'interpolation.

## Mesures

Mesuré le 24/09/2026 sur le Mac de Nicolas (Apple Silicon), `time docker compose run --rm --build check` :

| Passage | Durée | Résultat |
|---|---|---|
| À froid (images `postgres:18`, `python:3.13-slim`, `uv` téléchargées, image construite) | 54 s | vert, 8 tests |
| Après modification de code (cas du critère) | 3,6 s | vert |
| Erreur de type introduite volontairement | — | échec (mypy, code de sortie 1) |

Autres contrôles :
- `pytest --collect-only` : 8 tests, tous dans `tests/system/` ; aucun ancien test collecté.
- ruff et mypy : 12 fichiers analysés, tous du nouveau Rocky.
- Montages bind (constat A1, iCloud) : fonctionnent depuis `~/Developer/`.
- `rocky_app` : `rolsuper`, `rolcreatedb`, `rolcreaterole` faux, propriétaire de la base `rocky` ; l'application
  s'y connecte avec l'URL construite par Compose.
- `docker compose up -d --build --wait app` : conteneurs `healthy`, `/health` → `{"status":"ok"}`, utilisateur non-root
  (uid 1000) ; l'ancien Rocky (`rocky-assistant-local`, `job-assistant-postgres`) n'est pas touché.
