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

## CV maître (décision `docs/decisions/D2-cv-rendu.md`)
- Choix et ordre du CV : un seul objet `CvLayout`, réécrit en entier par `save_cv_layout` après `check_layout` ;
  chaque geste de l'écran est une fonction pure de `rocky/profil/cv/layout.py`. Pas d'événement (aucun score ne bouge).
- Une compétence technique est dans le CV par son groupe, les autres par leur seule position : la base le garantit
  (`ck_skills_cv_placement`). Un changement de catégorie retire la compétence du CV.
- `headline` = paragraphe de profil (import B5), `title` = titre court ; les liens sont une liste (`profile_links`).
- Dépôt public : ni photo, ni gabarit dérivé, ni rendu du CV d'une vraie personne dans Git ; tests sur données fictives.
- Un fichier de compte (photo, gabarit) passe par `system.files.FileStore` (chemin relatif, hash vérifié à la lecture).
- Import d'un CV (`rocky/profil/cv/importer.py`) : le modèle ne reçoit que les lignes de texte et leurs positions, jamais
  le fichier ; le PDF n'est pas conservé. La géométrie vient des lecteurs (`pdf_page.py`), le modèle ne nomme que les
  rubriques (`semantics.py`) ; une ligne sans rubrique refuse le gabarit, les propositions restent.
- Propositions (`proposals.py`) : une section à la fois, dans une transaction ; rien de rempli n'est remplacé.
- Rendu : le gabarit actif du compte (`derived.py`), sinon le gabarit neutre ; les plafonds viennent du gabarit actif.

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
