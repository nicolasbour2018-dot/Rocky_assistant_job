# 0004 – Portes de qualité : radon et vulture

Date : 2026-09-01. Statut : acceptée.

## Contexte

L'ADR 0001 place GitHub Actions en phase 2 et liste les outils à poser. radon
et vulture n'y figurent pas, mais les deux mesurent quelque chose qu'aucun
outil déjà en place ne voit : la complexité des fonctions, et le code que plus
rien n'appelle.

État mesuré le 2026-09-01, sur `dashboard scripts` :

| Outil | Mesure |
|---|---|
| `radon cc -a` | moyenne B (5,44) sur 621 blocs |
| `radon cc -n D` | 26 fonctions notées D ou pire, dans 16 fichiers |
| `vulture --min-confidence 80` | 0 signalement |
| `vulture --min-confidence 60` | 52 signalements |

Les 26 fonctions ne sont pas un défaut à corriger tout de suite. L'ADR 0001
interdit tout refactor de fond avant la fin de la phase 2, et une porte dure
au grade C forcerait 26 découpages sur un calendrier que le code ne réclame
pas.

## Décision

Les deux outils entrent dans `[dependency-groups] dev` et dans la CI, réglés
pour **empêcher l'aggravation sans forcer un refactor**.

**vulture bloque, à `--min-confidence 80`.** Le seuil est dans
`[tool.vulture]`. À 80 il rend zéro signalement : il garde la place, comme les
neuf familles ruff activées à zéro site. Les 52 constats à 60 sont des
méthodes de `repository.py` appelées depuis les pages Streamlit par des chemins
que vulture ne suit pas ; les trier est un travail en soi, pas une porte.

**radon bloque par xenon, aux seuils d'aujourd'hui :**

```
xenon --max-absolute F --max-modules C --max-average B dashboard scripts
```

Mesuré : sort en 0 sur l'état actuel. Un module qui glisse en D échoue ; une
moyenne qui dépasse B échoue.

`--max-absolute F` ne bloque rien au niveau fonction, F étant la dernière note.
C'est délibéré. Une seule fonction empêche de descendre à E :

```
ERROR:xenon:block "dashboard/job_detail_components.py:848 render_letter_workshop" has a rank of F
```

L'alternative était `--max-absolute E --exclude dashboard/job_detail_components.py`,
qui attrape toute nouvelle fonction F ailleurs mais rend ce fichier — celui qui
porte le plus de complexité, 4 des 26 — entièrement invisible. Aucun angle mort
vaut mieux qu'un seuil plus serré.

**radon lui-même est informatif.** L'étape `radon cc -n D -s` liste les
fonctions complexes à chaque exécution, en `continue-on-error`. C'est une
lecture, pas une porte.

## Conséquences

Aucun des 26 refactors n'est forcé. La barre ne monte jamais toute seule : elle
descend quand un refactor le permet, et la CI le constate.

Le seuil `--max-absolute` passe à `E` le jour où `render_letter_workshop`
descend sous F. C'est la seule action qui débloque un cran de la porte.

radon ne lit aucune configuration depuis `pyproject.toml` : les seuils vivent
dans `.github/workflows/ci.yml` et nulle part ailleurs.
