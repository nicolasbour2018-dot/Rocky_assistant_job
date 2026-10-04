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
- Un gabarit **inactif** se supprime (décision D6, Q8) : la ligne `cv_templates` disparaît, son dossier immuable reste
  dans le stockage, événement `profil.cv_template_deleted` ; le gabarit en service est refusé (`TEMPLATE_IN_SERVICE`).

## Journal
- Seulement ce qui explique un changement de score ou de veille : pistes, compétences, préférences, import,
  onboarding terminé. Pas les corrections de texte. Une modification sans changement n'écrit rien.
- Exception (décision D3, Q13) : une traduction proposée par le modèle et acceptée écrit `profil.translation_accepted`
  (champ, empreinte du français) : le texte vient de l'IA, validé par l'utilisateur.
- Exception (décision D4) : chaque version de la lettre générique écrit `profil.cover_letter_saved` (donnée D14).

## Lettre générique (décision `docs/decisions/D4-lettre-message.md`)
- Règles et import dans `letter.py`, écran dans `letter_web.py`, enregistré **avant** les routes du profil.
- `generic_letters` en ajout seul, la dernière d'une langue en vigueur ; son empreinte (`letter_sha256`) dit à un
  dossier que la lettre générique a changé. Une lettre anglaise garde l'empreinte de la française traduite.
- Import : le modèle ne reçoit que le texte, découpe sans réécrire ; un paragraphe qui n'est pas mot pour mot dans le
  texte lu est signalé à la relecture ; rien n'est enregistré avant « Enregistrer ma lettre ».
- Traduction : le moteur de D3 (`translation.propose`) avec les consignes de la lettre ; `{poste}` et `{entreprise}`
  sont des noms protégés.

## Traduction (décision `docs/decisions/D3-ciblage-traduction.md`)
- Règles pures et appel au modèle dans `rocky/profil/translation.py` ; écran dans `translation_web.py`, enregistré
  **avant** les routes du profil (`/profil/{key}` prendrait `/profil/traduction`).
- Un texte traduisible a une clé stable (`segments_of`) ; `accept_translation` refuse si le français a changé depuis la
  proposition (empreinte). Rien de non validé n'est stocké ; la mémoire (`translation_memory`) garde chaque validation.
- « À revoir » se déduit de la mémoire (`is_stale`) : aucune colonne d'état ; un anglais saisi à la main n'est jamais
  marqué.

## Écran
- Chaque section est `#section-<clé>` et se remplace en entier (`outerHTML`). Tout lien ou formulaire d'une section
  déclare `hx-get`/`hx-post`, `hx-target` et `hx-swap` (macros de `templates/profil/macros.html`).
- `wants_fragment` (`rocky/system/shell.py`) : une navigation boostée (`HX-Boosted`) reçoit une page entière,
  jamais un fragment.
- Une erreur de saisie demandée par HTMX répond 200 (HTMX n'insère pas les 4xx) ; sans HTMX, 400 et la page entière.
- La porte d'onboarding ne s'applique qu'aux adresses des entrées de navigation, en GET.
