# G5 — Profil et CV

Date : 06/10/2026 · Étape : G5 (plan v2) · Préparation : *mode plan*, quatre questions tranchées par Nicolas (Q1–Q4)

Critère de sortie (fixé par le plan de l'étape) :

1. le CV anglais de Nicolas par le gabarit neutre tient sur une page, les coupes listées ; un profil fictif « long »
   (4 emplois × 4 puces, 4 projets, 4 formations, textes aux limites) tient sur une page ;
2. un texte de projet qui sort de sa carte dessinée est signalé par son nom ; le CV FR de Nicolas, gabarit refait par
   réimport (sans appel au modèle), sans débordement et validé visuellement par Nicolas ;
3. second design fictif : deux rangements du faux modèle donnent les mêmes zones et les mêmes textes rendus ;
4. « MLFlow » existant, « ML Flow » saisi : proposition d'alias en un geste, à l'écran comme à l'onboarding ;
5. aides des pistes justes (une valeur par ligne, mots exclus, département) ; vérification globale verte.

## Constats de départ

| Constat | Source |
|---|---|
| Le gabarit neutre est une page A4 fixe (`overflow:hidden`) ; tout dépassement d'une colonne est refusé et nommé (« environ 77 mm » pour le parcours complet de Nicolas en anglais) ; une 2ᵉ page est refusée | `rocky/profil/cv/neutral/cv.html`, `rendering.py` (`problems`) ; décision D2, mesures |
| La place d'une zone du gabarit déduit est l'union de ses lignes d'origine, plus une ligne d'air (`ROOM = 1.0`) ; la carte dessinée par le design n'est jamais mesurée : un texte plus large que la carte, ou qui remplit la ligne d'air, n'est pas signalé | `rocky/profil/cv/derived.py` (`_regions`, `ROOM`) ; plan §8 (D2, D3) |
| Le nom d'un projet est écrit sans la ponctuation de l'original ; les étiquettes reçoivent « : » de Rocky | `derived.py` (`_region_html`) ; clôture D2 |
| Les règles déterministes après la réponse du modèle (`_by_column`, `_continued`) n'ont été éprouvées que sur un design (le Canva de Nicolas et un PDF fictif qui l'imite) | `tests/profil/cv/fixtures.py` ; clôture D2 |
| `normalize_term` garde une espace entre les mots : « ML Flow » (`ml flow`) et « MLFlow » (`mlflow`) sont deux termes, deux compétences | `rocky/profil/rules.py` ; plan §8 (C5 → `profil`) |
| Les listes des pistes se découpent aux retours à la ligne seulement ; « Mots exclus » et « Mots-clés » ne le disent pas ; l'aide des mots exclus dit « les annonces qui les contiennent sont écartées », faux depuis C4 (plafond dans l'intitulé, simple signal dans la description) | `templates/profil/sections/pistes.html`, `onboarding.html` ; `offres/scoring/rules.py` (`_excluded_words`) |
| L'aide des lieux ne cite pas le département, que le score comprend depuis G2 | `pistes.html` ; plan §8 (G2 → G5) |

## Décisions métier (Nicolas, 06/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Gabarit neutre et parcours long | **Une page**, plus dense, avec **une limite de caractères par paragraphe** ; un paragraphe coupé est signalé par une petite alerte. Révise D2 Q6 (« aucune réduction automatique ») et Q10 (« rien n'est coupé en silence ») **pour le seul gabarit neutre** : la coupe est visible, jamais silencieuse. Le gabarit déduit garde sa règle (un dépassement est une erreur). |
| Q2 | Place d'un bloc du gabarit déduit | **Bornée par la carte dessinée** qui l'entoure, avec la marge du design ; sans forme qui l'entoure, plus de ligne d'air : la place est celle des lignes d'origine. Tout dépassement est une erreur qui nomme le bloc. |
| Q3 | Autre design | Un **second PDF fictif**, de design différent, dans les jeux de test, éprouvé avec deux rangements du faux modèle. |
| Q4 | Compétences qui ne diffèrent que par la casse ou un espace | Refus avec un bouton **« L'ajouter comme autre nom de X »** (un geste). À l'onboarding, la ligne devient un autre nom de X et l'écran le dit. |

## Décisions techniques

*(complétées pendant l'étape)*
