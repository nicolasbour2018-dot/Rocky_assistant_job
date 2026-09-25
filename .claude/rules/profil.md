---
paths: rocky/profil/**
---

# Module `profil` — règles propres

Complète `AGENTS.md` ; ne répète pas ce qui s'y trouve. Décision : `docs/decisions/B5-profil-pistes.md`.

## Données
- Un compte = un profil, créé au premier usage par `ProfileEditor` ; demander si l'onboarding est dû ne le crée pas.
- Compétences **propres au compte**. Tout nom d'une compétence (libellé FR, EN, alias) passe par `normalize_term`
  et figure dans `skill_terms`, dont la clé primaire interdit qu'une autre compétence du profil le porte. Ne jamais
  écrire `skills` sans réécrire ses termes dans la même transaction (`SqlProfileStore` le fait).
- Textes FR obligatoires, EN facultatifs (`Text`) ; un EN vide ne bloque jamais rien.
- Une table liée à une compétence porte `profile_id` et une clé étrangère composite `(profile_id, …)` : la base
  refuse de lier la compétence d'un autre profil.
- Pistes : pas de suppression définitive d'une piste à laquelle une offre est rattachée (garde à ajouter en C6).

## Journal
- Seulement ce qui explique un changement de score ou de veille : pistes, compétences, préférences, import,
  onboarding terminé. Pas les corrections de texte. Une modification sans changement n'écrit rien.

## Écran
- Chaque section est `#section-<clé>` et se remplace en entier (`outerHTML`). Tout lien ou formulaire d'une section
  déclare `hx-get`/`hx-post`, `hx-target` et `hx-swap` (macros de `templates/profil/macros.html`).
- `wants_fragment` (`rocky/system/shell.py`) : une navigation boostée (`HX-Boosted`) reçoit une page entière,
  jamais un fragment.
- Une erreur de saisie demandée par HTMX répond 200 (HTMX n'insère pas les 4xx) ; sans HTMX, 400 et la page entière.
- La porte d'onboarding ne s'applique qu'aux adresses des entrées de navigation, en GET.
