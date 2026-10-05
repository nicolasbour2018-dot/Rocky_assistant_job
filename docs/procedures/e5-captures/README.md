# E5 — Captures de fiches lues par le poste Rocky

Décision : `docs/decisions/E5-lecture-assistee.md` (Q4). Produit le jeu de test du lecteur des pages **rendues** par le
navigateur du poste (`tests/offres/imports/data/apec/`), là où un simple client HTTP ne lit qu'une coquille vide.

Chaque capture fait de **vrais appels** depuis le navigateur du poste : avec l'accord de Nicolas, une ou deux fiches,
jamais en boucle. **Au premier blocage** (défi qui ne se passe pas, page refusée), on s'arrête et on en parle à
Nicolas : aucun maquillage du navigateur, aucun réessai (décision C1, Q5).

## 1. Capturer

Dans un premier terminal, sur l'ordinateur (pas dans Docker) :

```sh
uv run playwright install chromium   # une fois
uv run rocky-poste
```

Dans un second terminal :

```sh
uv run python docs/procedures/e5-captures/capture.py ~/rocky-captures-e5 <adresse de la fiche> [<autre>…]
```

Pour chaque adresse, le poste ouvre un onglet. Passe l'éventuel défi dans la fenêtre, attends que l'annonce soit
affichée, puis appuie sur Entrée dans le terminal : le script écrit `<n>-<site>.json` (adresse affichée, HTML rendu,
heure) **hors du dépôt**. Note ce que tu as vu : défi ou non, page complète ou non.

## 2. Préparer le jeu de test

Relire la page capturée, puis n'en garder que ce que lit l'import (blocs JSON-LD, `<title>`, lien `canonical`,
balises `og:`, conteneur de l'annonce) : aucun nom de personne (recruteur, contact), aucune adresse e-mail, aucun
jeton. Le résultat va dans `tests/offres/imports/data/apec/`, avec son origine et sa date dans
`tests/offres/imports/data/README.md`.
