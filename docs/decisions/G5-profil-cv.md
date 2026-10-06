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

| Sujet | Décision | Raison |
|---|---|---|
| Nom replié (Q4) | `fold_term` = `normalize_term` sans espaces ; contrôlé par le cas d'usage (`_refuse_similar`) à l'ajout et à la modification d'une compétence, **pas** à l'import d'un fichier (Q9 seule) ; la base ne garantit que les termes exacts (`skill_terms`) | Une ressemblance n'est pas un doublon : elle se propose, elle ne bloque pas un import relu. |
| Geste « autre nom » | `add_aliases` passe par `update_skill` (mêmes contrôles, mêmes termes, événement `profil.skill_updated`) ; un nom déjà porté par la compétence est sauté ; un champ caché par nom | Aucune écriture SQL nouvelle, une seule transaction. |
| Listes des pistes | Mots-clés et mots exclus se découpent aussi aux virgules (`comma_lines`) ; intitulés et lieux non (« Paris, 8e ») | « senior, lead, staff » sur une ligne était un seul mot exclu, introuvable. |
| Gabarit neutre dense (Q1) | Corps 8 pt, interligne 1,25, colonne latérale 55 mm, marges resserrées ; intitulé, employeur et lieu d'une entrée sur une ligne ; étiquettes des projets en ligne (« Problème : … ») plutôt qu'en grille | La densité seule fait tenir le parcours de Nicolas : les limites ne sont qu'un filet. |
| Limites (Q1) | `NeutralLimits` : accroche 300 caractères en tout, puce d'emploi 140, puce de formation 90, partie de projet 140 ; coupe après le dernier mot entier, « … » compris (`shortened`) ; l'accroche garde son gras, les paragraphes au-delà de la limite tombent | Calées pour qu'un parcours « long » aux limites (3 emplois × 3 puces, 4 formations × 2 puces, 3 projets, accroche) tienne : 9 mm de marge. Les textes de Nicolas (jusqu'à 137 caractères) ne sont pas coupés. |
| Coupe visible (Q1) | Faite à un seul endroit, `neutral_html` : le PDF, l'empreinte d'une révision (`cv_fingerprint`) et « Vérifier mon CV » voient le même texte ; chaque coupe est nommée (`CvPdf.notices`) et dite dans Profil & kit (par langue sans gabarit actif) et sous l'aperçu du CV du dossier (`profil/cv_cuts.html`) | Jamais silencieuse ; non bloquante. Trop d'entrées restent une erreur nommée : rien n'est retiré. |
| Carte d'une zone (Q2) | Formes du design relevées par `pdf_page.drawn_boxes` (même parcours du SVG que `cut_svg`, factorisé dans `_drawn`) ; une forme de moins de la moitié de la page qui contient les lignes est une carte ; la plus petite borne la zone : à droite et en bas, la marge de gauche du texte ; jamais sous le texte suivant ; jamais plus petite que les lignes d'origine | Le texte « Pilotage d'association sportive » sortait de sa carte sans alerte. |
| Sans carte (Q2) | La zone = ses lignes et leur interligne (`ROOM` retiré), en français comme pour les paragraphes de la version anglaise (`_unit_html`) | Décision Q2. |
| Calque | Les décorations des anciens textes s'effacent toujours sur l'ancienne zone (lignes et une ligne, `ERASED_BELOW`), pas sur la carte entière | Agrandir la zone ne doit effacer aucun élément du design. |
| Format | `rocky-cv-gabarit/5`, seul format lu : un gabarit plus ancien demande un réimport (`OLD_FORMAT`), qui réutilise la réponse gardée du modèle (aucun appel) | Les zones se mesurent autrement. |
| Second design (Q3) | Projets numérotés colonne par colonne, puis de haut en bas (cartes empilées) ; une ligne « nom » juste sous une partie, dans sa colonne, continue la partie ; une ligne qui commence par une étiquette **attestée** (une autre ligne commence vraiment par elle) prend sa partie ; groupes « **Nom :** compétences » sur une ligne si le design les écrit ainsi (gras puis texte normal sur une ligne) ; transversales jointes par la marque du design (`·`, `|`, `•` ; jamais virgule ni barre oblique, qu'une compétence peut contenir) ; le nom d'un projet garde son « : » | Le second design a montré cinq règles taillées pour le seul Canva de Nicolas. |

## Mesures (06/10/2026)

| Contrôle | Résultat |
|---|---|
| Gabarit neutre, profil de Nicolas (base de développement) | Avant : débordement de **89 mm** (FR) et **77 mm** (EN). Après : une page, **10,3 mm** (FR) et **17,2 mm** (EN) de marge, **aucune coupe** |
| Parcours « long » fictif aux limites | Une page, 9,2 mm de marge, aucune coupe ; un caractère de plus est coupé et nommé |
| Second design, deux lectures du faux modèle | Mêmes zones, même texte rendu, aucun débordement ; chaque projet dans sa carte |
| Vérification globale | Verte (1 680 tests) ; 78 s sur une machine calme, 105 à 142 s sous une charge de 12 (deux agents en parallèle) |

## Recette avec Nicolas (critère 2, à faire)

Application de développement reconstruite avec G5 (`docker compose up -d --build --wait app`). Les deux gabarits actifs
du compte (FR et sa version anglaise) sont au format 4 : le CV demande un réimport.

1. Profil & kit → importer de nouveau le PDF du Canva français (même fichier : la réponse gardée du modèle sert, aucun
   appel à Gemini), puis refaire « Préparer mon CV anglais ».
2. Aperçu du CV français, puis d'un dossier : blocs projets dans leurs cartes, « : » des noms, retours à la ligne et
   écarts des parties ; débordement éventuel nommé.
3. **À trancher (D2 Q32)** : « l'espace vide sous les compétences accueille des compétences en plus ». Avec Q2, une zone
   sans carte n'a plus de ligne d'air : si les compétences du Canva ne sont pas dans une forme dessinée, une compétence
   de plus qui passe à la ligne est refusée. Même effet pour les paragraphes traduits de la version anglaise.
4. Aperçu du CV anglais par le gabarit neutre (gabarit anglais désactivé, ou compte sans CV importé) : une page.
