# D2 — CV maître et rendu

Date : 29/09/2026 · Étape : D2 (plan v2) · Préparation : *grill me* avec Nicolas (Q1–Q28) puis mode plan

Critère de sortie (plan, complété par Q20) : « CV FR et EN validés visuellement par Nicolas ; parsing du PDF vérifié ;
le gabarit déduit du CV Canva de Nicolas passe la mesure Q17 ; un PDF image est refusé avec sa raison et se rabat sur
le gabarit neutre. »

## Constats de départ

| Constat | Source |
|---|---|
| L'ancien Rocky ne **génère** pas de CV : il réécrit 8 zones (compétences techniques et transversales, 3 cartes projets) d'un export Canva, par coordonnées PDF (PyMuPDF). Le SHA-256 du PDF source bloque tout si le Canva change ; en-tête, profil, expériences et formations sont figés | `dashboard/rocky/cv_tailoring.py`, `assets/cv_template_v1.json` |
| LibreOffice ne servait qu'à la lettre ; le CV anglais était traduit ligne à ligne (Groq) vers une page ReportLab en Helvetica, mise en page perdue | `dashboard/rocky/profile_documents.py` |
| L'ATS V3 mêle des faits (3 lecteurs PDF, sections, contact, dates, cohérence) et des simulations (6 « ATS » Workday, Taleo… aux formules inventées, scores composites) | `dashboard/rocky/ats_v3.py`, `docs/ats_v3_methodology.md` |
| CV de référence : Canva, 1 page A4, fond `#F7F6F1` ; 36 tracés vectoriels, 7 images (photo, 3 icônes, 3 grandes images de courbes), 114 blocs de texte, 6 polices (Poppins Regular/Bold/Italic, Questrial, Glacial Indifference Regular/Bold) | archive A1, `…/users/1/profiles/1/fr/cv.pdf` (sondé en lecture seule) |
| Le CV EN de l'archive est une **image pleine page** avec une couche de texte (ligatures cassées), pas un export Canva | archive A1, `…/en/cv_230f3abde19e.pdf` |
| Glacial Indifference et Poppins Italic manquent au dépôt ; `assets/` appartient à l'ancien Rocky | `assets/fonts/` |
| Profil de Nicolas en base : 3 emplois et 4 formations, **aucun** titre ni puce EN ; 4 projets bilingues ; 52 compétences sur 56 avec un libellé EN, 13 clés | base de développement, lecture seule |
| Manquent au profil pour ce CV : âge, loisirs, lien HuggingFace, résumé distinct du titre, groupes de compétences techniques, ordre et sélection | `rocky/system/migrations/versions/0003_create_profile.py` |
| Aucun accès aux fichiers ni volume de fichiers ; Playwright et Chromium absents des images | `rocky/system/`, `docker-compose.yml` ; constat B1 → D2 |
| Le dépôt GitHub est **public** et sans licence | `gh repo view` |

## Décisions métier (grill avec Nicolas, 29/09)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Étape | D1 est close ; on attaque D2. |
| Q2 | Import d'un CV PDF | Dans D2 (constat B5 → D2), à l'onboarding et depuis Profil & kit, pour garder l'étape cohérente. |
| Q3 | Lecture assistée d'une offre | Hors D2 : ce n'est pas la même logique métier. Nouvelle étape **E5. Lecture assistée**, avant F1 (Q28). |
| Q4 | Répartition | `profil` : contenu du CV, édition, « Vérifier mon CV », import. `system` : accès aux fichiers, rendu HTML → PDF (Playwright), lecture PDF multi-lecteurs, réutilisables par la lettre (D4). Aucune révision immuable de document : c'est D5. |
| Q5 | Fidélité | **Reproduction à l'identique** du CV : seuls les textes changent, aucune modification de design, même mineure. |
| Q6 | Une page | A4 stricte. Un texte qui déborde de sa boîte est une **erreur visible** qui nomme la boîte, mesurée par Playwright après le rendu. Aucune réduction automatique. |
| Q7 | Photo | Facultative, téléversée dans Profil & kit, stockée sous la racine de fichiers du compte. |
| Q8 | Champs ajoutés | Date de naissance avec âge calculé et interrupteur « afficher l'âge » ; loisirs FR/EN ordonnés ; **liste de liens** (libellé, URL, icône connue), le portfolio y entre ; `headline` = titre court (« DATA SCIENTIST »), nouveau `summary` FR/EN pour le paragraphe, gras balisé `**…**`. |
| Q9 | Groupes de compétences | Définis par l'utilisateur (nom FR/EN, ordre) ; une compétence technique est rattachée à un groupe au plus. Transversales = catégories `soft` et `business`. |
| Q10 | Sélection et ordre | Ordre explicite et drapeau « dans le CV maître » pour projets, compétences et loisirs ; expériences et formations par date. Rien n'est coupé en silence. |
| Q11 | Anglais manquant | Le rendu EN **refuse** tant qu'un champ affiché n'a pas d'anglais, et liste les manques. Claude saisit l'anglais du profil de Nicolas ; la traduction par le LLM reste en D3. |
| Q12 | « Vérifier mon CV » | Les **faits** seulement : chaque lecteur (pypdf, pdfminer.six, pypdfium2) retrouve-t-il nom, contact, sections, dates, compétences du profil, dans l'ordre ; avertissements concrets. Ni ATS simulés, ni scores composites. La couverture d'une annonce passe à D3. |
| Q13 | Stabilité | « Même contenu → même CV » : hash du HTML rendu, comparaison des **pages rastérisées** (les octets d'un PDF de Chromium changent avec sa date de création). Test visuel dans la vérification globale ; la référence ne se régénère que par une commande explicite. |
| Q14 | Import | Aussi depuis Profil & kit, en **propositions** qui n'écrasent rien. Gemini reçoit le **texte extrait**, jamais le fichier, après une mention explicite. Relecture section par section (accepter / modifier / ignorer), une transaction par section acceptée. PDF source **non conservé**. Essai réel sur le Canva de Nicolas accepté. |
| Q15 | Méthode | Un **calque fixe** extrait du PDF (tracés en SVG, images à leur résolution d'origine) plus des **boîtes de texte en position absolue** (police, taille, couleur relevées). Un élément non reproductible est signalé, jamais redessiné en silence. |
| Q16 | Un gabarit par compte | Chaque compte a **son** gabarit, déduit du CV qu'il importe ; reproduire un même gabarit pour plusieurs comptes n'a pas de sens. Sans CV importé : gabarit neutre simplifié. |
| Q17 | Mesure de l'identique | Rendu du CV FR avec le même contenu que le Canva, rastérisation des deux pages à la même résolution : écart **hors boîtes** nul ou quasi nul (seuil consigné ci-dessous), écart **dans les boîtes** faible, image de différence. Puis validation visuelle par Nicolas. |
| Q18 | Où vit l'anglais | En base (seule vérité), plus une commande `rocky-admin export-profil` au format `rocky-profil/1` étendu, qui remplacera le fichier de réimport en F2. |
| Q19 | Éléments extérieurs | Polices OFL téléchargées depuis leur source officielle, avec leur licence, dans `rocky/profil/cv/fonts/` (les trois polices d'`assets/` y sont recopiées) ; photo et icônes extraites du PDF de l'archive (lecture seule). |
| Q20 | Déduction du gabarit | Mécanisme général appliqué à tout CV importé : **géométrie** déterministe (tracés et images → calque ; blocs → boîtes ; photo proposée) ; **sémantique** par le même appel Gemini que l'import (chaque bloc → section du profil ou texte fixe) ; relecture côte à côte. Refus motivé avec repli sur le gabarit neutre : PDF image, plus de 2 pages, blocs non rattachés. Le Canva de Nicolas est le premier cas ; aucun gabarit fait à la main. |
| Q21 | Anglais du gabarit | Un gabarit sert pour les deux langues ; ses textes fixes (titres de section) ont une version EN proposée par Gemini lors de la déduction et relue. Un texte EN trop long déborde (Q6). |
| Q22 | Polices d'un autre compte | Bibliothèque de polices libres (OFL) embarquée ; une police absente est remplacée par une proche, avec un avertissement visible à la relecture et au rendu. Pas de réseau à l'exécution. |
| Q23 | Gabarit neutre | En flux, une page A4, plafonds propres, photo seulement si le profil en a une. Il porte le test visuel versionné (profil fictif). Un PDF fictif fabriqué teste la déduction. |
| Q24 | Stockage d'un gabarit | Dossier **immuable** `<racine>/comptes/<compte>/gabarits/<hash>/` (`template.json`, images, SVG) et une ligne en base (compte, hash, date, actif). Un nouvel import crée un nouveau gabarit, l'ancien reste. Événements `profil.cv_template_derived`, `profil.cv_template_activated`. |
| Q25 | Licence | **Aucune dépendance AGPL** (PyMuPDF engagerait la licence de Rocky dès le VPS) : pypdfium2 pour objets, images, texte et polices, `pdftocairo -svg` (poppler, programme séparé) pour les tracés. Si le coût est trop élevé, retour à Nicolas avant PyMuPDF. |
| Q26 | Emplacements | Le gabarit déclare ses emplacements répétés (3 cartes projets…) ; le drapeau « dans le CV maître » refuse l'enregistrement au-delà (« ton gabarit a 3 cartes projets »). Un changement de gabarit qui rend une sélection trop longue est dit au rendu, rien n'est tronqué. |
| Q27 | Découpage | Une étape, une série de commits cohérents, chacun avec une vérification verte (docs ; `system` ; données du profil ; rendu ; vérification ; déduction et import ; données de Nicolas et clôture). |
| Q28 | Étape E5 | **E5. Lecture assistée** : navigateur visible sur le poste, geste « Enrichir » dans la fiche d'offre (décision C1, Q6). Critère : « une offre Apec incomplète enrichie depuis sa fiche ». |

### Révision après l'essai du gabarit déduit (Nicolas, 29/09, Q29–Q34)

Nicolas a trouvé la page reproduite fidèle mais la fonction sur-dimensionnée : le CV importé est à jour, il ne sert
qu'à adapter à l'offre les blocs qui en dépendent.

| # | Sujet | Décision |
|---|---|---|
| Q29 | Blocs variables | Seuls trois blocs sont remplis par le profil : **compétences techniques** (groupes), **compétences transversales**, **projets**. Tout le reste du CV importé est repris tel quel : nom, titre, âge, accroche, photo, contact, langues, loisirs, expériences, formations. Remplace Q7 (photo), Q8 (âge, titre, accroche) et Q10 (loisirs) pour un gabarit déduit ; le gabarit neutre les garde. |
| Q30 | Âge, accroche | Jamais générés ni modifiés : l'utilisateur fournit un CV à jour. Ils peuvent manquer d'un CV à l'autre. |
| Q31 | Projets | Un projet est un seul bloc qui s'écoule dans sa carte (problème, stack, livrable à la suite, avec l'écart d'origine entre paragraphes), et non trois zones fixes qui laissent des trous. Son nom garde sa zone. |
| Q32 | Compétences | L'espace vide sous les compétences est gardé : il accueille des compétences en plus. |
| Q33 | Anglais | **Un CV importé par langue**, l'import anglais étant **facultatif** : l'utilisateur peut importer aussi son CV anglais à jour ; les blocs non variables du CV anglais viennent de lui. Remplace Q21 (un gabarit pour deux langues). Sans CV importé dans une langue, le gabarit neutre sert. |
| Q34 | Plus tard | Adapter aussi expériences et formations : idée d'amélioration, à évaluer pendant les bêtas (section 8 du plan). |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Dépôt public | Ni photo, ni gabarit dérivé, ni rendu du CV de Nicolas dans Git : ils vivent dans le volume de fichiers. Tests et références visuelles sur un profil et un PDF **fictifs** | AGENTS §7 (jeux anonymisés) ; données personnelles. |
| Dépendances | `playwright` (Apache-2.0) : rendu HTML → PDF et mesure du débordement, demandé par le plan. `pypdfium2` (Apache-2.0/BSD-3) : objets de page, images, rastérisation, 3ᵉ lecteur. `pdfminer.six` (MIT) et `pypdf` (BSD-3) : 2 autres lecteurs de « Vérifier mon CV » (Q12). `pillow` (HPND) : comparaison des pages rastérisées (Q13, Q17). Paquets système : Chromium (par Playwright) et `poppler-utils` (`pdftocairo`, appelé en sous-processus, Q25) | Chacune répond à une décision ; aucune n'est AGPL. |
| Titre et paragraphe (Q8) | Le réimport B5 a placé le **paragraphe** de profil dans `headline` (« Accroche ») : `headline` le garde, un nouveau champ `title` porte le titre court (« Data Scientist »). Même décision métier (deux champs), sans déplacer de données | Aucune donnée réimportée ne change de sens. |
| CV maître (Q9, Q10) | `CvLayout` (groupes et leurs compétences, transversales, projets, loisirs) réécrit en entier dans une transaction ; `cv_position` vide = hors du CV ; une compétence technique est dans le CV par son groupe (`ck_skills_cv_placement`). Gestes de l'écran en fonctions pures (`rocky/profil/cv/layout.py`) | Un seul port, aucun état intermédiaire incohérent. |
| Liens (Q8) | Migration `0007` : LinkedIn, GitHub, portfolio copiés dans `profile_links` (dans cet ordre), colonnes retirées ; le `downgrade` les remet. Libellé déduit du site connu (LinkedIn, GitHub, Hugging Face) si l'utilisateur n'en donne pas | Un seul endroit pour les liens, testé dans les deux sens. |
| Chromium sous Linux | Lancé avec `--font-render-hinting=none` : avec le *hinting*, les avances des glyphes arrondies au pixel font lire « La ng a g es » aux lecteurs de PDF (constaté dans le conteneur, pas sur macOS). Titres du gabarit neutre espacés de 0,05 em au plus : au-delà, pypdf et pdfminer lisent « C O N T A C T » | Un CV que les lecteurs ne lisent pas mot à mot échoue au critère « parsing vérifié ». |
| Références visuelles | Rendues **dans le conteneur** (Linux, comme l'application) ; tolérance 0,05 % de la page sous Linux, 1 % sur macOS (≈ 0,45 % d'écart d'anticrénelage entre les deux) ; régénération par une commande explicite (en tête de `tests/profil/cv/test_rendering.py`) | Stable là où le CV est produit, sans casser la boucle rapide locale. |
| Polices | `@font-face` marqué sûr (l'échappement de Jinja cassait le CSS en silence) ; toutes les faces déclarées sont chargées avant la mesure, un échec de chargement est une erreur | Aucune police de repli silencieuse. |
| Calque du gabarit (Q15, Q25) | La page d'origine est dessinée en SVG par `pdftocairo` ; on en retire les glyphes des lignes de contenu, l'image de la photo et les petits tracés logés dans une zone de contenu (puces, soulignements), en composant les matrices des formulaires jusqu'à chaque glyphe. Deux calques : avec les textes fixes (français, identiques au pixel) et sans aucun texte (anglais, titres réécrits). Écarté : retirer les objets avec pdfium, dont la régénération casse les formulaires imbriqués de Canva (ressources perdues) | Aucune bibliothèque AGPL ; le design n'est jamais redessiné. |
| Unité de lecture (Q20) | La **ligne** (pdfminer), pas le bloc : un bloc de pdfminer peut joindre un titre et son contenu (« C O N T A C T » + l'e-mail) | Constaté au premier appel réel. |
| Zones et styles | Une zone par rubrique (union de ses lignes, un peu d'air en dessous) ; styles mesurés : principal, gras, italique, simple, interligne, écart entre entrées, alignement, espacement des lettres, capitales, séparateur des années ; seuls les projets sont numérotés | Reproduire sans rien deviner du design. |
| Photo (Q7, Q20) | L'image du PDF peut dépasser ce que la page montre (découpe en disque) : la zone visible est mesurée sur le rendu, l'image garde sa place et sa taille, découpée pareil | Cadrage identique avec sa propre photo. |
| Titres en anglais (Q21) | Un titre sur plusieurs lignes est traduit en entier sur sa première ligne, les suivantes vides | « COMPÉTENCES / TECHNIQUES » devenait « SKILLS / TECHNICAL ». |
| Aperçu de l'import | Rendu du contenu du CV lui-même (profil provisoire en mémoire), montré même imparfait avec ses débordements ; jamais stocké ; appel au modèle, dérivation et aperçu hors transaction, enregistrement du gabarit dans une transaction courte | Voir ce qui ne va pas plutôt qu'un refus sans image. |
| Titres des sections (Q12) | Chaque titre fixe porte, pour les lecteurs de PDF, les mêmes mots en texte invisible, sans les espaces que le design met entre les lettres (« CONTACT » au lieu de « C O N T A C T ») ; en anglais, le titre visible est dessiné en tracés (`fonttools`, MIT, contours des polices embarquées) pour n'être pas lu lettre par lettre | Le calque transforme les titres en tracés : sans ce texte, aucun titre ne serait lu ; lu espacé, il ne serait pas reconnu. |
| Robustesse face au modèle | Règles déterministes après sa réponse : une ligne ne commence une partie de projet que si son texte commence par l'étiquette ; une ligne sans étiquette (ou prise pour un nom de projet) continue la partie au-dessus ; les titres sur plusieurs lignes sont traduits en entier (liste « titles ») puis répartis ; une année seule n'est jamais « en cours » | Deux appels réels ont rangé différemment les mêmes lignes. |
| Page image (Q20) | Une image couvrant 80 % de la page ou plus refuse le gabarit (son texte y est superposé) ; les propositions restent | Le CV EN de l'archive avait 130 lignes de texte sur une image pleine page. |
| Calque en image (retour de Nicolas, 29/09) | Le calque SVG donnait dix masques doux (`/SMask`) que l'Aperçu de macOS dessinait en **gros blocs noirs** (poppler perdait aussi des courbes ; seul pdfium, le moteur de mes mesures, l'affichait juste). Le calque est désormais **une image opaque à 300 dpi** (résolution des images du design), rendue une fois par Chromium à l'écran ; format de gabarit `rocky-cv-gabarit/2`, un gabarit de l'ancien format demande un nouvel import. Test : aucun `/SMask` dans le CV d'un design à image transparente | Même rendu dans tous les lecteurs de PDF ; remplace « tracés en SVG » de Q15. |
| Rubriques gardées (retour de Nicolas, 29/09) | À l'import, des rubriques (loisirs, langues, compétences) peuvent être gardées telles que le CV d'origine les écrit : dans le CV français, le calque garde leur texte (et des mots invisibles pour les lecteurs) ; le CV anglais les prend du profil | « La partie loisirs est inutile à modifier ». |
| Numéros de projet | Par la géométrie : lignes de nom jointes quand elles se recouvrent, colonnes de gauche à droite, chaque ligne de projet rattachée à la colonne la plus proche ; le modèle ne donne que le rôle | Un appel avait croisé les projets 2 et 3. |
| Alignement | Centré quand les milieux des lignes varient trois fois moins que leurs débuts (Canva centre à 5 points près) | Transversales et loisirs sortaient alignés à gauche. |
| Réponse du modèle | Gardée avec l'import (`reponse-du-modele.json`, textes du CV et rubriques) : un gabarit se refait sans nouvel appel | Mise au point sans rappeler Gemini. |
| Fichiers | `ROCKY_STORAGE_ROOT` (volume nommé `rocky-files` dans l'application) ; chemins **relatifs** à la racine, jamais absolus ; dossiers immuables nommés par leur hash, relus avec vérification | Constats A1 → D5 et B1 → D2. |

## Mesures (29/09/2026)

| Contrôle | Résultat |
|---|---|
| Vérification globale | `docker compose run --rm --build check` : 888 tests, 39 s (43 s au total, image en cache) ; Chromium et poppler dans les images |
| Gabarit neutre | Références visuelles rendues sous Linux ; écart macOS / Linux ≈ 0,45 % de la page (anticrénelage) ; les trois lecteurs lisent tout le CV d'exemple |
| Import réel du Canva (Gemini 3.5 Flash Lite) | 152 lignes, 7 images, 36 tracés ; un appel de 10 à 15 s ; toutes les lignes rattachées ; photo trouvée (disque de 165 pt dans une image de 180 × 225 pt). Cinq appels réels pendant la mise au point, seulement sur le texte extrait |
| **Q17 — hors zones de texte et photo** (contenu du Canva recopié par le modèle, rendu dans le gabarit déduit, 100 dpi) | **0,22 %** des pixels après un flou de 1 px et un seuil de 48/255 (1,5 % en brut : liserés d'anticrénelage entre le rendu de pdfium et celui de Chromium). Seuil retenu : 0,5 % |
| Q17 — photo | 0 pixel d'écart (même image, même cadrage) |
| Q17 — dans les zones | 11,6 % des pixels : textes recopiés par le modèle (dont une puce de la stack du projet 2 rangée dans le problème), retours à la ligne. Écart de mise en page ramené de 20,5 % à 11,6 % par l'alignement des lignes de base |
| CV de Nicolas, FR et EN (profil réel, CV maître composé dans l'ordre du Canva, anglais saisi) | Rendus sans débordement ; « Vérifier mon CV » : **61 éléments sur 61 lus par les trois lecteurs**, en français et en anglais ; accord entre lecteurs 0,99 et 1,0 |
| PDF image | CV EN de l'archive : gabarit refusé (« image de page ») ; un PDF sans texte est refusé dès la lecture |
| **Après la révision Q29–Q33** (gabarit refait depuis la réponse conservée, sans nouvel appel) | Seuls groupes de compétences, transversales, noms et corps des projets sont des zones ; tout le reste est l'image du CV importé, lu par les lecteurs grâce aux mots invisibles. CV FR de Nicolas : aucun débordement, aucun masque doux, « Vérifier mon CV » **37 sur 37** (nom, contact, titres de section, compétences, projets). Sans CV anglais importé, le CV anglais passe par le gabarit neutre, où le parcours complet de Nicolas déborde de 77 mm : à importer (Q33) |

## Critère de sortie et clôture

*(À remplir à la validation de Nicolas.)*
