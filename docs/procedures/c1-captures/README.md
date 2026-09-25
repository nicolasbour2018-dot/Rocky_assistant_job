# C1 — Captures des sources

Décision : `docs/decisions/C1-sources.md` (Q3, Q5). Produit les jeux de données enregistrés des tests
(`tests/offres/sources/data/`, origine de chaque fichier dans son `README.md`).

À refaire quand une plateforme change de format (un test de connecteur ne reflète plus la réalité, ou
`rocky-admin sources` signale une panne « réponse inattendue »). Chaque capture fait de **vrais appels** :
avec l'accord de Nicolas, une fois, jamais en boucle.

## 1. Capturer

Les réponses sont écrites **hors du dépôt**, avec leur statut et leurs en-têtes anti-robot ; jamais l'URL de la
requête, ses paramètres ni ses en-têtes (les clés d'API y passent).

Sources sans clé, depuis le poste :

```sh
uv run python docs/procedures/c1-captures/capture.py ~/rocky-captures --only apec --only wttj --only linkedin --only wellfound
```

Sources à clé (Adzuna ; France Travail quand l'accès sera accordé) : dans le conteneur de l'application, seul à lire
le `.env` :

```sh
mkdir -p ~/rocky-captures-adzuna && chmod 777 ~/rocky-captures-adzuna
docker compose run --rm --build --no-deps \
  -v "$PWD/docs/procedures/c1-captures:/capture:ro" -v ~/rocky-captures-adzuna:/out \
  app python /capture/capture.py /out --only adzuna
```

Par défaut : « Data analyst » à Paris, 5 offres par source, puis un détail par source qui en a un. Le script affiche
l'état de chaque source. **Au premier refus d'une source (HTTP 403, 429, défi), on s'arrête et on en parle à
Nicolas** avant toute autre tentative (règle d'arrêt, Q5).

## 2. Préparer les jeux de test

```sh
uv run python docs/procedures/c1-captures/prepare.py ~/rocky-captures
```

`prepare.py` range chaque réponse dans `tests/offres/sources/data/<source>/`, et :
- anonymise les paramètres de session du lien de défi DataDome ;
- retire du détail WTTJ les vidéos de l'entreprise (prénoms de salariés) ;
- réduit la page Wellfound à ses données `__NEXT_DATA__`.

Relire ensuite les fichiers (aucune adresse e-mail, aucun nom de recruteur, aucune clé : `utm_source` d'Adzuna
porte l'identifiant de l'application et doit être absent ou neutralisé), mettre à jour les valeurs attendues des
tests du connecteur, et la date de capture dans `tests/offres/sources/data/README.md`.

## Mesures du 25/09/2026

| Source | Résultat |
|---|---|
| Apec | référentiel de lieux : « Paris » introuvable seul (4 réponses au plus, par ordre alphabétique), « Paris - » → `75` ; recherche filtrée : 184 offres à Paris contre une recherche nationale ; en-tête `x-datadome: protected` **sur les réponses acceptées aussi** ; détail `offre/public` : **403 DataDome** |
| Welcome to the Jungle | 10 offres par page, **aucun filtre de lieu accepté** (`Unexpected field`), offres du monde entier ; détail complet |
| LinkedIn | cartes publiques, lieu en texte libre accepté |
| Wellfound | page `/role/l/<rôle>/<lieu>` servie derrière Cloudflare, sans défi |
| Adzuna | API officielle ; description = extrait de 500 caractères ; `utm_source` des liens = identifiant de l'application ; un TJM freelance arrive dans `salary_min` (450) ; catégorie « Unknown » quand elle manque. Première tentative « non configurée » : clés recopiées sans le préfixe `ROCKY_` |
| France Travail | non capturé : accès en attente (D8) |
