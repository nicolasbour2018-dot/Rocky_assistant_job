# 0011 – Frontières : pydantic-settings et httpx

Date : 2026-09-01. Statut : acceptée.

## Contexte

`config.py` lit l'environnement à l'import (`load_dotenv` puis `os.getenv`
dans les défauts d'une dataclass), valide 2 champs sur 27, et `database_url`
peut valoir `None`. Les sources utilisent `requests` avec un timeout codé en
dur (25 s), des en-têtes de navigateur simulés, aucun retry, et un repli sur
`curl` en sous-processus pour Wellfound.

## Décision

Configuration : `pydantic-settings`. Une classe `Settings` instanciée par la
composition, validation complète au démarrage, échec immédiat avec un message
sans secret. Le fichier `.env` reste supporté.

HTTP : `httpx` comme unique client, un client partagé par processus, timeouts
explicites. `tenacity` pour les retries. Le repli `curl` disparaît : une
source que le CDN refuse est signalée `PARTIAL`, comme le prévoit la règle.

## Conséquences

- `python-dotenv` et `requests` quittent les dépendances.
- `check_connections.py` devient `rocky check` (0012).
- Les doublures de test des sources ciblent `httpx`. `respx` est noté comme
  idée, non retenu.
