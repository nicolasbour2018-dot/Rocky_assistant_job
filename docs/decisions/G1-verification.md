# G1 — Vérification

Date : 05/10/2026 · Étape : G1 (plan v2) · Préparation : *direct*

Critère de sortie (plan) : « Vérification GitHub verte en 1 min 40 au plus ».

Mesure retenue, la même que pour les relevés précédents (E3, E5, F1) : la durée de pytest affichée dans le passage
GitHub (`1556 passed in 120.70s`). Image, ruff et mypy s'y ajoutent (environ 1 min) et ne sont pas visés.

## Constats de départ

| Constat | Source |
|---|---|
| Dernier passage vert : 1 556 tests en **116 à 121 s** sur GitHub (`37361566948`, `37362055158`) ; 64 à 67 s sur le poste à 4 workers, comme le runner GitHub (4 processeurs, `-n auto`) | `gh run view`, plan §8 (E3 → B1) |
| Les deux passages suivants (`37366149287`, `37366156486`) ont échoué **sans démarrer** : « The job was not acquired by Runner of type hosted even after multiple attempts ». Incident de GitHub, aucune étape lancée | annotations des passages |
| `ubuntu-latest` passe à Ubuntu 26 à partir du 19/10/2026 | annotation des passages, plan §8 (B2) |
| Profil de la suite en séquentiel (cProfile) : **242 comptes connectés** (`logged_in`) ; chaque invitation passe par `rocky-admin invite`, qui construit un vrai `Argon2Hasher` : son constructeur calcule un hachage factice (**42 ms**), alors qu'une invitation ne hache rien (255 hachages, 11 s) | `tests/system/web_support.py`, `rocky/system/auth/admin.py`, `usecases.py` (`Argon2Hasher`) |
| Chaque test crée une application, donc un environnement Jinja neuf : **1 089 compilations** de gabarits pour la suite (16 s profilées) | `rocky/system/web.py` (`create_app`), `make_app` |
| **92 rendus Chromium** (environ 0,33 s de lancement chacun), dont **37 doublons exacts** : surtout l'import du même CV fictif (un PDF et deux calques à 300 dpi) dans quatre fichiers de `profil` | compteur posé pendant la mesure (`render_pdf`, `render_image`) |
| Les fixtures « boîte » et « dossier » (`messages`, `candidatures`, `offres`) sont **modifiées par chaque test** (messages enregistrés, classements, décisions, étapes) ; un compte coûte 33 ms une fois l'argon2 retiré | `tests/messages/test_decisions_usecases.py` (`box`), `tests/offres/test_web.py` (`board`) |

## Décisions

| Sujet | Décision | Raison |
|---|---|---|
| Comptes des tests | `invitation_token` appelle le cas d'usage `Auth.invite` avec le faux hacheur, plus la commande `rocky-admin invite` (testée à part dans `tests/system/auth/test_admin.py`) | Même chemin métier (compte en attente, jeton, lien) sans le hachage inutile ; le compte connecté passe de 75 à 33 ms. |
| Gabarits Jinja | `make_app` donne à chaque application de test un **cache de bytecode partagé** pour l'exécution (`SharedBytecode`, en mémoire) | Le code compilé ne dépend que de la source (empreinte vérifiée par Jinja) ; filtres et globales sont lus au rendu. Le code de production ne change pas. |
| Rendus | `tests/profil/conftest.py` garde le premier rendu de chaque entrée (HTML et ressources, ou SVG et dimensions) et le rend aux tests suivants de `profil` ; remplacé **pendant les tests de `profil` seulement** | Un rendu ne dépend que des octets qu'il reçoit (`rocky.system.render`) ; sa stabilité reste testée sur de vrais rendus (`tests/system/test_render.py`). `candidatures` garde un vrai rendu à chaque génération : ses tests portent sur les révisions (deux générations, deux PDF distincts). |
| Comptes et boîtes partagés par module (piste du plan) | **Non retenu** | Les mesures placent le coût dans l'argon2 et la compilation, pas dans le SQL du compte ; partager une boîte ou un dossier que chaque test modifie rendrait les tests dépendants de leur ordre (et de la répartition de `pytest-xdist`). |
| Runner GitHub | `runs-on: ubuntu-24.04` | Pas de changement d'image en silence le 19/10 ; un passage à Ubuntu 26 se fera par un choix explicite. |
| Dépendances | Aucune | — |

## Mesures

| Mesure | Avant | Après |
|---|---|---|
| Poste, `uv run pytest -n 4` | 64 à 67 s | 45 à 48 s |
| Docker limité à 4 processeurs (tests et `test-db`, `cpuset: "0-3"`, comme le runner GitHub) | 68 s | 44 à 46 s |
| Rendus Chromium réels (séquentiel) | 92, dont 12 calques à 300 dpi | 68, dont 4 calques |
| Vérification globale (`docker compose run --rm --build check`, 8 processeurs) | — | verte, 1 556 tests en 52 s |
| GitHub (pytest ; job complet 3 min 06 → 2 min 40) | 116 à 121 s | **86 s**, `ubuntu-24.04` (passage `37372057971`, 06/10) |

## Clôture (06/10)

Critère vérifié : vérification GitHub verte, pytest en **86 s** (limite 100 s), passage `37372057971`. Le premier essai
(05/10) n'avait pas démarré : panne de GitHub Actions de 19 h 11 à 21 h 54 UTC (attribution des runners hébergés),
relancé une fois l'incident levé.
