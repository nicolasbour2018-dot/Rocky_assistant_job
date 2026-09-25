# C4 — Scoring : règles

Date : 25/09/2026 · Étape : C4 (plan v2) · Préparation : *grill me* avec Nicolas (Q1–Q26) puis mode plan

Critère de sortie : « Chaque score s'explique composante par composante ; la "Data Protection Analyst" (79,6 % en v1)
ne remonte plus. »

## Constats de départ (ancien Rocky, archive A1, étapes précédentes)

| Constat | Source |
|---|---|
| Score v1 : moyenne pondérée renormalisée sur les composantes disponibles (compétences 55, intitulé 20, contrat 8, lieu 8, télétravail 5, salaire 4) ; compétences = trouvées / détectées, détectées par un dictionnaire global ; intitulé par Jaccard + `SequenceMatcher` | `dashboard/rocky/matching.py` (tag `rocky-v1-streamlit`) |
| « Data Protection Analyst – Freelance » (id 1193) : une seule compétence détectée, couverte → composante compétences pleine, 79,6 % malgré un intitulé à 22,7 % ; TJM 550 lu comme un salaire | `docs/archive/rocky-refonte-plan.md`, `job_offers.csv` (A1) |
| L'analyse C3 ne détecte **que les compétences du compte** : le ratio v1 vaudrait toujours 100 %. Ce qui manque au profil n'arrive que comme phrases d'exigence (`requirements`) | `rocky/offres/analysis/model.py` |
| Aucune table d'offres ni de scores : les migrations `0001`–`0003` couvrent événements, comptes et profil | `rocky/system/migrations/versions/` |
| Données du profil utilisables : compétences (`is_key`, `level`, liens aux expériences et projets), pistes (`titles`, `keywords`, `excluded_keywords`, `locations` en libellés libres), préférences (contrats, télétravail, `min_salary_eur`, `min_daily_rate_eur`), langues, expériences datées (`job` ou `education`) | `rocky/profil/model.py`, plan §8 (B5 → C4) |
| La version des règles v1 s'appelle `matching-v1` : la nouvelle porte un nom distinct | plan §8 (A2 → C4) |
| WTTJ et Wellfound ne filtrent pas le lieu : le lieu doit peser dans le score | plan §8 (C1 → C4) |
| Une période de salaire déduite du montant doit peser moins qu'une période écrite | plan §8 (C3 → C4) |

## Décisions métier (grill avec Nicolas, 25/09)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Portée | **Un score par (offre, piste).** L'offre affiche le meilleur ; le détail nomme la piste. Chaque couple est une ligne d'entraînement (D14). |
| Q2 | Compétences | **Quantité de preuves pondérée** : éliminatoire 1, un plus 0,6, mentionnée 0,3. Composante pleine à **4 points** (preuve minimale : 1 ou 2 compétences ne la remplissent jamais). |
| Q3 | Poids d'une compétence | Compétence **clé ×1,5** ; **prouvée** (liée à une expérience ou un projet) ×1, non prouvée ×0,7. Le niveau déclaré est affiché, jamais pondéré (auto-évaluation). |
| Q4 | Intitulé | Meilleure piste : intitulé de la piste **tel quel** dans celui de l'annonce → 1 ; **tous ses mots** présents mais séparés → 0,5 ; sinon part des mots présents × 0,5. Mots vides ignorés (H/F, de, en…). Les `keywords` n'y entrent pas. |
| Q5 | Mots exclus | Un mot exclu de la piste **dans l'intitulé** plafonne le score (motif « mot exclu : … ») ; dans la description, il est seulement affiché. |
| Q6 | Conditions | Nationalité, habilitation, permis : **plafond**, libellé « Bloquant : \<condition\> ». Le profil ne dit pas encore si on les remplit : si le cas se présente, on ajoutera ces critères au profil. |
| Q7 | Contrat, télétravail | Comparés aux préférences ; un contrat non voulu ne coûte que ses points (pas de plafond). Sans préférence ou sans information : composante absente. |
| Q8 | Salaire | Annuel, ou mensuel ×12 → `min_salary_eur` ; journalier → `min_daily_rate_eur` ; horaire **ignoré et signalé**. On compare le **maximum** de la fourchette : `min(1, montant / minimum)`. Période **déduite** : poids divisé par 2. |
| Q9 | Lieu | Hors de France → 0, « hors zone » ; en France dans un lieu de la piste → 1 ; en France ailleurs → 0,3 ; télétravail complet → lieu neutre (absent) ; lieu inconnu → absent. Pas de géocodage en C4. |
| Q10 | Expérience, langues | Calculées, avec un petit poids, et affichées dans les manques. |
| Q11 | Confiance | **Trois niveaux** (haute, moyenne, faible), chaque raison affichée ; **sans effet sur le score**. |
| Q12 | Stockage | C4 produit un **résultat sérialisable** (score, composantes, preuves, caractéristiques D14, version des règles) ; la table naît en C6 avec l'offre et ses pistes. Version : `score-AAAA-MM-JJ.n`. |
| Q13 | Preuve de sortie | Test sur l'annonce 1193 anonymisée ; mesure v1 contre nouvelle version sur l'échantillon C3 ; détail validé par Nicolas dans l'aperçu d'import. |
| Q14 | Plafond | **30**, valeur unique ; le plus bas s'applique, tous les motifs listés en tête. Les exigences hors profil restent une pénalité (Q26), sans plafond. |
| Q15 | Télétravail et lieu | Hors zone en France : télétravail complet → lieu neutre ; hybride → **0,5** au lieu de 0,3. À l'étranger en télétravail complet → **0,5**, marqué « vérifier le droit au travail et le fuseau ». |
| Q16 | Poids | Compétences 40, intitulé 25, contrat 10, lieu 10, télétravail 5, salaire 5, expérience 3, langues 2. |
| Q17 | Fusion | Compétences et intitulé **comptent toujours** (0 possible) ; les composantes facultatives absentes sont renormalisées et baissent la confiance. |
| Q18 | Seuil | **50** (constante) ; la fonction de score donne le motif « score sous le seuil (xx < 50) ». C5 le recalibre. |
| Q19 | Mots-clés des pistes | Aucun poids ; ceux trouvés dans l'annonce sont gardés comme caractéristique. |
| Q20 | Offre sans piste | Scorée contre **toutes les pistes actives**, la meilleure l'emporte. Sans piste active : ni intitulé ni lieu, confiance faible (« aucune piste active »). |
| Q21 | Affichage | **Entier sur 100** ; la valeur exacte est gardée. |
| Q22 | Années d'expérience | Calcul sur les années **pertinentes** (emplois liés à une compétence trouvée dans l'annonce) ; le total des emplois est affiché et gardé ; les formations ne comptent jamais. `min(1, pertinentes / demandées)`. |
| Q23 | Langues | Par langue demandée : 1 si le niveau du profil est atteint (ou non précisé et la langue présente), 0,5 si la langue est au profil à un niveau inférieur, 0 si elle manque ; moyenne. |
| Q24 | Autre devise | Pas de conversion : composante absente, marquée « salaire en USD, non comparé ». |
| Q25 | Règle de confiance | **Faible** : description incomplète, preuves < 2 points ou aucune piste active. **Moyenne** : au moins 3 composantes facultatives absentes sur 6, période de salaire déduite, ou lieu inconnu. **Haute** sinon. |
| Q26 | Exigences hors profil | Chaque phrase `requirements` retire **1 point de preuve** (plancher 0) et figure dans les manques avec sa phrase. |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Forme | Sous-module `rocky/offres/scoring/` : `model.py` (paramètres, dataclasses, sérialisation), `rules.py` (fonction pure `score`) | Même forme que `analysis/` ; AGENTS §4. |
| Entrées | `score(analysis, offer, profile)` : l'analyse C3, l'offre collectée (intitulé, lieu, pays, complétude) et une vue `ScoringProfile` construite depuis `Profile` | Le score ne relit pas le texte : tous les faits viennent de l'analyse (une seule lecture, une seule version de règles d'extraction). |
| Profil | `profil.web.profile_of` (cas d'usage du profil), jamais le SQL de `profil` | AGENTS §4. |
| Comparaison des termes | `fold` / `term_pattern` de l'analyse pour l'intitulé, les lieux et les mots | Même forme de comparaison que les compétences (sans casse, accents ni ponctuation, mots entiers). |
| Pays | `CollectedOffer.country` : `France`, `FR`, `FRA` = France. Pays inconnu : l'offre est traitée en France, avec le marqueur « pays non précisé » | Les connecteurs français donnent `France` ; WTTJ un code ISO ; LinkedIn et Wellfound rien. |
| Paramètres | Toutes les valeurs de ce document sont des constantes de `model.py`, à calibrer en C5 ; toute modification change `RULES_VERSION` | D14 : un score garde la version exacte de ses règles. |
| Conservation | Rien n'est persisté en C4 ; `Score.to_json()` donne la forme stockée en C6 | Même règle que C1–C3. |
| Preuve d'une compétence | Liée à une expérience (emploi **ou formation**) ou à un projet | Q3 dit « expérience ou projet » ; le profil range les formations parmi les expériences. À revoir en C5 si une formation prouve trop. |
| Devise absente | Un montant sans devise est lu en euros | Les sources sont françaises ; une devise écrite autre que l'euro rend la composante absente (Q24). |
| Lieu « France » | Un lieu de piste nommé « France » couvre tout le pays | Sans géocodage, c'est la seule façon de dire « partout en France ». |
| Écran | Le détail du score s'affiche dans l'aperçu d'import, avant l'analyse : chiffre entier, piste, confiance et ses raisons, plafonds, tableau des composantes (valeur, poids, ce qui a été comparé, preuves), manques, score par piste | Q13, Q21. La fiche d'offre (C7) reprendra ce gabarit. |

## Mesures (25/09/2026)

Procédure et tableaux : `docs/procedures/c4-mesure/` (profil réel de Nicolas, lu dans la base de développement).

| Mesure | Résultat |
|---|---|
| « Data Protection Analyst » (1193) | 79,6 en v1 → **29** (profil réel), confiance faible, « preuves insuffisantes » ; 47 < 50 avec un profil de test qui la favorise (test de sortie) |
| Hors-sujets de la v1 | « Head of Talent Acquisition » 72 → 7 ; « Sourcing Transformation Digitale » 78 → 12 ; « Project Manager DATA / IA » 72 → 17 |
| 404 annonces notées en v1 | Corrélation de rang v1 / C4 : 0,08 ; ≥ 50 : 332 en v1, 264 en C4 ; confiance haute 10, moyenne 131, faible 263 ; 13 plafonnées |
| Écarts laissés à C5 | Confiance faible trop fréquente (médiane des preuves 1,4 point) ; haut du classement saturé à 100 ; fausses exigences hors profil de l'analyse (« anglais obligatoire ») |

Vérifié dans un navigateur (Chromium, instance à part, schéma jetable de `test-db`) : aperçu d'une description
collée (DPA : 19, sous le seuil) et d'un lien Hellowork réel (69) ; console sans erreur.
