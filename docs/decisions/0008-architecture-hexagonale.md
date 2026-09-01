# 0008 – Architecture hexagonale en couches, paquet `src/rocky`, Python 3.13

Date : 2026-09-01. Statut : acceptée.

## Contexte

Deux couches aujourd'hui : `dashboard/` (UI) et `dashboard/rocky/` (métier
sans UI), un dépôt de 2638 lignes, des scripts qui manipulent `sys.path`.
Alternative pesée et non retenue : tranches verticales par fonctionnalité
(un dossier par fonctionnalité, adaptateurs partagés). Elle facilite la
navigation des agents mais protège moins le domaine des adaptateurs.

## Décision

Layout `src/`, paquet `rocky`, cinq couches :

| Couche         | Contenu                                                     |
|----------------|-------------------------------------------------------------|
| `domain/`      | entités, règles métier, ports (`Protocol`). Aucune dépendance externe |
| `application/` | cas d'usage : veille, triage, préparation de candidature, documents |
| `adapters/`    | `db/`, `mistral/`, `gmail/`, `sources/`, `documents/`, `browser/` |
| `web/`         | app FastAPI, templates Jinja2, static                       |
| `cli/`         | commandes typer                                             |

Règle de dépendance : `web` et `cli` importent `application`, qui importe
`domain`. Les adaptateurs implémentent les ports de `domain` et ne sont
importés que par la composition, dans `web` et `cli`. Un import qui remonte
est une erreur.

Python 3.13, épinglé dans `.python-version` et `requires-python >= 3.13`.

Contrôle par `import-linter`, trois contrats dans `pyproject.toml` :

- `layers` : `rocky.web | rocky.cli`, puis `rocky.application |
  rocky.adapters`, puis `rocky.domain`, avec `exhaustive = true`. Le `|`
  rend les couches soeurs indépendantes : `application` et `adapters` ne
  s'importent jamais, seuls `web` et `cli` les assemblent. `exhaustive`
  interdit un module hors couche, donc tout dossier `utils/` fourre-tout.
- `forbidden`, avec `include_external_packages = true` : `rocky.domain` et
  `rocky.application` n'importent ni `sqlalchemy`, `fastapi`, `httpx`,
  `mistralai`, `typst`, ni `playwright`.
- `independence` entre `adapters.db`, `adapters.mistral`, `adapters.gmail`,
  `adapters.sources`, `adapters.documents` et `adapters.browser`.

`lint-imports` tourne à trois endroits : un hook après chaque écriture sous
`src/` (Claude Code et Codex), `prek` avant commit, la CI. Alternative
écartée : `tach`, dont `tach sync` réécrit la config depuis l'état courant
et permet de légaliser une violation sans revue.

## Conséquences

- Les `.claude/rules/` sont réécrits par couche quand le squelette existe.
  Les règles par fonctionnalité actuelles restent valables sur `dashboard/`
  jusqu'à sa suppression. Une règle `architecture.md` scopée sur
  `src/rocky/**` énonce le sens des dépendances et la commande
  `lint-imports`.
- Ce que l'outil ne voit pas, de la logique métier dans une route ou un objet
  SQLAlchemy typé `Any` qui traverse le domaine, est couvert par un cliquet
  xenon plus sévère sur `web/` et `adapters/`, et par la revue.
- Plus de `sys.path.insert` ni d'exception `E402`.
- Les schémas de l'architecture vivent dans `docs/architecture.md`.
- TODO : réévaluer Python 3.14 une fois vérifiées les roues arm64 de
  `playwright`, `pydantic-core` et `typst`.
