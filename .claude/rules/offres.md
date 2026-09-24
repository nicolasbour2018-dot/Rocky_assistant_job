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
