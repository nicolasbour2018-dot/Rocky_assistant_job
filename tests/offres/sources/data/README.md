# Jeux de données enregistrés des sources (étape C1)

Réponses réelles des plateformes, capturées le **25/09/2026** par `docs/procedures/c1-captures/`
(recherche « Data analyst » à Paris, 5 offres demandées), puis réduites et anonymisées par
`docs/procedures/c1-captures/prepare.py`. Aucune clé, aucune URL de requête, aucune donnée personnelle.

| Fichier | Origine |
|---|---|
| `apec/places-paris.json`, `apec/places-paris-dash.json` | capturés : référentiel de lieux, `q=Paris` puis `q=Paris -` |
| `apec/search.json` | capturé : recherche filtrée sur Paris (`lieux: ["75"]`) |
| `apec/detail-refused.json` | capturé : refus DataDome du détail (HTTP 403), paramètres de session anonymisés |
| `apec/detail.json` | **reconstruit** : Apec a refusé tout détail pendant la capture ; clés reprises de l'ancien `apec_detail.py` |
| `wttj/search.json`, `wttj/detail.json` | capturés ; vidéos de l'entreprise retirées du détail (prénoms de salariés) |
| `linkedin/search.html` | capturé : cartes publiques pour visiteurs |
| `wellfound/role-location.html` | capturé : page `/role/l/data-analyst/paris`, réduite à ses données `__NEXT_DATA__` |
| `adzuna/search.json` | voir la décision C1 (capture avec les clés de Nicolas) |
| `france_travail/search.json` | **reconstruit** : accès en attente (D8) ; format de l'API Offres d'emploi v2 et ancien test |

Recapturer après un changement de format d'une plateforme : suivre `docs/procedures/c1-captures/README.md`.
