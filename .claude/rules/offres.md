---
paths: rocky/offres/**
---

# Module `offres` — règles propres

Complète `AGENTS.md` ; ne répète pas ce qui s'y trouve. Décisions : `docs/decisions/B4-coque-prototype.md`.

## Ce qui est gardé, ce qui est jetable (prototype B4)
- **Gardés pour C7** : `decisions.py` (valeurs, motifs, règles), `web.py`, `templates/offres/`.
- **Jetables, supprimés en C7** : `prototype.py`, `prototype_offers.json` (et la procédure
  `docs/procedures/b4-prototype/`). Aucun autre fichier n'importe `prototype.py` hors de `web.py`.
- Les scores de `prototype_offers.json` sont une maquette : ne jamais s'en servir comme base du scoring C4.

## Décisions et motifs
- Données : codes anglais seulement (`rejected`, `too_senior`) ; libellés français uniquement à l'affichage.
- Un motif au moins pour toute décision ; `other` exige une précision ; au plus 9 motifs par décision (touches 1–9).

## Écran
- Le serveur rend chaque état en HTML ; HTMX place les fragments. Aucun état côté client.
- Seul JavaScript maison : `rocky/system/static/rocky.js` (raccourcis `data-key`). Toute nouvelle interaction passe
  par un attribut `hx-*` ou un élément HTML natif (`details`, `popover`, formulaire).
- Chaque route répond aussi sans HTMX (page entière ou redirection).
- `hx-swap` et `hx-target` s'héritent des ancêtres : tout élément qui cible une zone déclare explicitement son
  `hx-swap` (bug « Revenir » de B4).

## Sources (`rocky/offres/sources/`, décision `docs/decisions/C1-sources.md`)
- **Ligne rouge (Q5)** : jamais de résolution ni d'esquive d'un défi anti-robot, de session ou compte réutilisé, de
  proxy, d'imitation d'empreinte TLS, de réessai. Un refus (403, 429, 999 de LinkedIn, défi Cloudflare, mur de
  connexion) lève `SourceRefusedError` et la source s'arrête pour la collecte. L'en-tête `x-datadome: protected` seul
  n'est **pas** un refus. Détail : un refus ou une réponse illisible arrête le détail de la source, un 404 non.
- Jamais de « 0 offre » silencieux : une page sans la structure attendue (aucune carte, clé de données absente) est
  une panne (`SourceFailedError`) ; seule une réponse vide ou une liste vide vaut « aucun résultat ».
- Toute requête passe par `PublicHttp` (pause par hôte, aucun réessai) ; aucun autre client HTTP.
- Une source ne lève que `SourceRefusedError`, `SourceFailedError` ou `QuerySkippedError` ; tout le reste est un bug,
  isolé et journalisé par `collect`. Les raisons sont en français et ne citent jamais l'URL ni ses paramètres.
- Faits bruts de l'annonce seulement (textes contrat, télétravail, salaire) ; aucune interprétation (C3), aucune
  valeur devinée (un code inconnu reste vide). Une description partielle est gardée, marquée incomplète avec sa raison.
- Une source n'existe que par `registry.build_sources`. Nouveau connecteur : capture réelle
  (`docs/procedures/c1-captures/`), jeu anonymisé dans `tests/offres/sources/data/<source>/`, tests par `Replay`.
