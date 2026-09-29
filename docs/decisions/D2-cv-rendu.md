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

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Dépôt public | Ni photo, ni gabarit dérivé, ni rendu du CV de Nicolas dans Git : ils vivent dans le volume de fichiers. Tests et références visuelles sur un profil et un PDF **fictifs** | AGENTS §7 (jeux anonymisés) ; données personnelles. |
| Dépendances | `playwright` (Apache-2.0) : rendu HTML → PDF et mesure du débordement, demandé par le plan. `pypdfium2` (Apache-2.0/BSD-3) : objets de page, images, rastérisation, 3ᵉ lecteur. `pdfminer.six` (MIT) et `pypdf` (BSD-3) : 2 autres lecteurs de « Vérifier mon CV » (Q12). `pillow` (HPND) : comparaison des pages rastérisées (Q13, Q17). Paquets système : Chromium (par Playwright) et `poppler-utils` (`pdftocairo`, appelé en sous-processus, Q25) | Chacune répond à une décision ; aucune n'est AGPL. |
| Fichiers | `ROCKY_STORAGE_ROOT` (volume nommé `rocky-files` dans l'application) ; chemins **relatifs** à la racine, jamais absolus ; dossiers immuables nommés par leur hash, relus avec vérification | Constats A1 → D5 et B1 → D2. |

## Mesures

*(À remplir pendant l'étape.)*

## Critère de sortie et clôture

*(À remplir à la validation de Nicolas.)*
