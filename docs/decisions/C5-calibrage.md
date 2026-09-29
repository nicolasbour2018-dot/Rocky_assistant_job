# C5 — Scoring : calibrage

Date : 28/09/2026 · Étape : C5 (plan v2) · Préparation : *grill me* avec Nicolas (Q1–Q21) puis mode plan

Critère de sortie : « Les annonces jugées pertinentes remontent ; écart chiffré et documenté. »

## Constats de départ (mesure C4 du 28/09, archive A1)

| Constat | Source |
|---|---|
| Règles `score-2026-09-25.1`, profil complété : la 1193 à 44 ; confiance faible pour 263 annonces sur 404 ; 20 premières toutes à 100 ; corrélation de rang v1 / C4 de 0,10 | `docs/procedures/c4-mesure/README.md` |
| Contrat, lieu et salaire pleins, renormalisés faute d'autres informations, portent le score sans preuve de métier (1193 à 44, 1030 « Sourcing » à 24 avec compétences et intitulé à 0) ; le télétravail, les trois modes acceptés, vaut 1 dès que l'annonce en parle | idem, plan §8 (C4 → C5) |
| Fausses exigences hors profil : « Maîtrise de l'anglais obligatoire » et « This posting is representative of multiple roles… » retirent chacune un point de preuve | plan §8 (C4 → C3, C5) |
| Candidatures du profil 1 : 43 annonces distinctes hors RETIRÉE, dont 36 parmi les 404 annonces mesurées | `applications.csv` (A1) |
| Sur ces 36 candidatures, C4 classe moins bien que v1 : rang médian dans le top 42 % (v1 : 21 %) ; 12 dans le premier quart (v1 : 20) ; 28 au-dessus de 50 (v1 : 34) | calcul du 28/09 (lecture seule) |
| 870 offres ÉCARTÉE, sans motif ni origine connue (manuelle ou automatique) | `job_offers.csv` (A1) |
| Répartition C4 des 368 annonces hors candidatures : 0–19 : 7 · 20–39 : 46 · 40–59 : 129 · 60–79 : 121 · 80–100 : 64 | calcul du 28/09 |

## Décisions métier (grill avec Nicolas, 28/09)

### Protocole d'annotation

| # | Sujet | Décision |
|---|---|---|
| Q1 | Critère | « **Postulerais-je ?** » avec le profil et les préférences d'aujourd'hui, tout compris (métier, compétences, contrat, lieu, salaire, entreprise), en ignorant l'ancienneté de l'annonce. |
| Q2 | Échelle | **Oui / À examiner / Non**. Pertinente = Oui + À examiner (critère du plan) ; ordre attendu Oui > À examiner > Non. |
| Q3 | Unité | Une étiquette **par annonce**, comparée au meilleur score (celui affiché) ; « mauvaise piste » se signale en motif. Pour D14, l'étiquette s'applique au meilleur couple (offre, piste). |
| Q4 | Étiquettes v1 | Les candidatures v1 (sauf la RETIRÉE) forment l'ensemble de **contrôle**, jamais utilisé pour régler. Les ÉCARTÉE ne sont pas utilisées. |
| Q5 | Aveugle | Ni score v1, ni score C4, ni statut v1 à l'annotation ; ordre tiré au sort. |
| Q6 | Forme des motifs | Liste fermée à choix multiple, plus « Autre » avec un commentaire libre. |
| Q7 | Motif obligatoire | **Toujours**, y compris pour Oui (motif court). |
| Q8 | Support | Page HTML locale générée **hors dépôt** (texte complet et formulaire) → `annotations.json` versionné : identifiant, niveau, motifs, commentaire, sans texte d'annonce. |
| Q9 | Motifs | Métier / intitulé ; Compétences / stack ; Séniorité ; Secteur / domaine ; Entreprise ; Contrat ; Lieu ; Télétravail ; Salaire / TJM ; Langue ; Condition bloquante ; Mauvaise piste ; Annonce floue ou incomplète ; Autre. Chaque motif coché porte un signe **+** (attire) ou **−** (rebute). Un Oui a au moins un motif +, un Non au moins un motif −. |
| Q10 | Échantillon | **50 annonces** parmi les annonces mesurées hors contrôle, graine fixe, par tranche de score C4 de référence : 15 en 80–100, 15 en 60–79, 12 en 40–59, 8 en 0–39. |
| Q11 | Stabilité | **5 doublons** non signalés en fin de série (55 annonces affichées) ; accord mesuré. |
| Q17 | Profil | Derniers ajustements de Nicolas (mots exclus, préférences), puis profil **figé** jusqu'à la fin de C5, son état relevé dans la procédure. Une modification souhaitée en cours de route est notée et appliquée après. |
| Q18 | Correction d'étiquette | Seulement pour une erreur de lecture, notée avec sa raison (règle C3). |
| Q19 | Doublon incohérent | La première réponse compte ; la seconde ne sert qu'à la stabilité ; les deux sont gardées. |

### Cibles de réussite (fixées avant l'annotation)

| # | Sujet | Cible |
|---|---|---|
| Q12 | Ordre (annotations) | AUC pertinente contre Non **≥ 0,80** et **aucune Non** dans les 10 premières ; C4 calibré meilleur que v1 sur les deux. Trois classements comparés sur les mêmes étiquettes : v1, C4 de référence, C4 calibré. |
| Q13 | Seuil | Seuil libre (50 aujourd'hui). **100 % des Oui** et **≥ 90 % des pertinentes** au-dessus ; **≤ 1/3 des Non** au-dessus. Rater une bonne offre coûte plus qu'en examiner une mauvaise. |
| Q14 | Contrôle (candidatures) | Parmi les annonces mesurées : rang médian dans le **top 25 %** ; **≥ 20 sur 36** dans le premier quart ; **≥ 32 sur 36** au-dessus du seuil. |

### Réglage et clôture

| # | Sujet | Décision |
|---|---|---|
| Q15 | Périmètre | Constantes de `rocky/offres/scoring/model.py` ; nouvelles règles de fusion **justifiées par des motifs comptés** ; correction C3 des fausses exigences. Une nouvelle composante (secteur, entreprise) est seulement notée en section 8. |
| Q16 | Méthode | Itérations manuelles guidées par le décompte des motifs ; chaque `RULES_VERSION` est mesurée sur les annotations et le contrôle. Recherche automatique réservée au seuil (l'apprentissage des poids est laissé à D14). |
| Q20 | Cibles non atteintes | Point d'arrêt avec Nicolas après **3 versions** de règles : continuer, accepter l'écart documenté ou reporter en section 8. |
| Q21 | Validation | Nicolas relit, sur la version calibrée, les 20 premières, les 10 juste sous le seuil et les candidatures de contrôle restées sous le seuil. |

### Première version des règles (grill avec Nicolas, 29/09, après la mesure de référence)

| # | Sujet | Décision |
|---|---|---|
| Q22 | Préférence ou règle | Une **préférence personnelle** (séniorité refusée, secteur) va dans le **profil** ; une **règle** ne code que ce qui vaut pour tout compte. Garde-fou contre le biais d'un annotateur unique : les règles restent justes pour un autre utilisateur (alpha-testeurs, D15). |
| Q23 | Séniorité | Premier motif de Non (18 sur 29), souvent bloquante au recrutement (Nicolas). **Exception à Q17** : Nicolas complète les mots exclus de ses deux pistes (la piste « Data scientist / IA », sans mot exclu, contournait le plafond « senior » de l'autre). Un réglage « niveau visé » du profil est noté en section 8. |
| Q24 | Étranger | Une annonce **hors de France**, connue ou **présumée** (pays absent sur une source qui ne filtre pas le lieu : Wellfound), est **plafonnée** (« Hors de France »), en télétravail complet aussi (droit au travail : visa américain, par exemple), sauf si un lieu de la piste couvre ce pays ou cette ville. |
| Q25 | Version 1 | Q23 (profil), Q24 (règle) et la correction C3 des fausses exigences de langue ; mesurée avant toute règle plus risquée (intitulé à 0, poids du contrat, du lieu et du salaire). |

Rappel (Nicolas, 29/09) : un Non n'est pas une annonce « non pertinente pour le profil » mais une annonce où il ne
postulerait pas, souvent pour un **motif bloquant** (visa, séniorité). La faire passer sous le seuil par un plafond ne
la jette pas : elle reste conservée avec son motif (invariant « aucune offre n'est jetée »).

Contrôle ajusté (Nicolas, 29/09, après Q24) : 860 (New York) et 917 (Londres), plafonnées par Q24, sortent du
contrôle, l'étranger étant désormais bloquant pour Nicolas. Le contrôle compte 34 candidatures ; les cibles Q14 sont
ramenées dans la même proportion : ≥ 19 dans le premier quart, ≥ 31 au-dessus du seuil, rang médian ≤ 25 %.

### Deuxième version (grill avec Nicolas, 29/09, après la mesure de la version 1)

| # | Sujet | Décision |
|---|---|---|
| Q26 | Candidatures hors des pistes | Jugées par Nicolas sur l'intitulé seul, **avant** toute nouvelle mesure : 272 « Quantitative consultant », 432 « BPCE », 655 « Responsable IA & Data » (niveau du poste) et 752 « Business Analysis support Cash Management » (management éliminatoire) sortent du contrôle ; 55 « Consultant Data Analytics » et 853 « Analyste OSINT » (piste Data analyst), 942 « Prompt Engineer » (piste Data scientist / IA) restent, leurs métiers entrant dans les intitulés des pistes (profil, Q22). Contrôle : 30 candidatures ; cibles Q14 dans la même proportion : ≥ 17 dans le premier quart, ≥ 27 au-dessus du seuil, rang médian ≤ 25 %. |
| Q27 | Annonce 751 | Motif « métier − » retiré (erreur de Nicolas, Q18) ; l'étiquette Non reste, pour des compétences demandées absentes du profil et le secteur. |
| Q28 | Savoir-être | Une compétence de catégorie « Savoir-être » compte **×0,5** dans les points de preuve : presque toutes les annonces en citent ; règle valable pour tout compte. |

### Point d'arrêt (Q20, grill avec Nicolas, 29/09, après deux versions de règles)

| # | Sujet | Décision |
|---|---|---|
| Q29 | Contrôle | **Écart accepté et documenté**, la cible n'est pas réécrite : sur les 30 candidatures, `score-2026-09-29.2` fait 27 % · 14 · 28 (rang médian · premier quart · au-dessus du seuil), la v1 26 % · 15 · 28 ; l'intention de Q14 (parité avec la v1) est tenue, les chiffres (≤ 25 % · ≥ 17 · ≥ 27) ne le sont pas pour les deux premiers. Ces règles sont un **point de départ** : elles seront affinées sur les décisions réelles de Nicolas (C7, étiquettes D14). |
| Q30 | Annonce 751 | **Limite acceptée** : sa non-pertinence dépend du poids des compétences de finance dans l'annonce, que l'analyse ne voit pas (elle ne lit que les termes du profil). Direction d'amélioration notée en section 8. |
| Q31 | Seuil | **50** : seul seuil qui tient à la fois les cibles Q13 et le contrôle au-dessus du seuil (à 61, lu sur la courbe, 2 Non au-dessus au lieu de 5, mais le contrôle tombe à 21 sur 30). |

### Troisième version (grill avec Nicolas, 29/09, après sa relecture de la version 2)

| # | Sujet | Décision |
|---|---|---|
| Q32 | Information absente | Une composante facultative dont l'annonce ne dit rien compte **0,5** (« on ne sait pas ») au lieu d'être retirée et renormalisée (révise C4 Q17) : 100 est réservé aux annonces qui disent tout et où tout correspond. « Rien à comparer » (aucune préférence au profil, aucune langue demandée, piste sans lieu, télétravail complet) reste **neutre** : retiré, sans effet sur la confiance. |
| Q33 | Intitulé partiel | Une partie seulement des mots d'un intitulé de piste (« Data » sans « analyst ») vaut **0** ; tous les mots présents mais séparés gardent 0,5 (« Data Science Analyst », au contrôle). |
| Q34 | Compétences implicites | 438 (« compétences pas toutes explicites mais accessibles ») : limite de l'analyse, qui ne lit que les termes du profil ; notée en section 8, pas de règle. |

### Limites de la mesure

- **Annotateur unique et subjectif** : c'est voulu (Q1, les étiquettes D14 sont les décisions de Nicolas), mais les
  règles ne doivent pas coder ses goûts (Q22).
- **Constance** : 4 doublons sur 5 identiques ; le jugement évolue aussi dans le temps (Nicolas a postulé en v1 à un
  « Adjoint chef de bureau – Data analyst » du contrôle et étiquette Non une annonce de même intitulé, 608).
- **Petit échantillon** (50) : le contrôle vérifie que le réglage vaut au-delà.
- **Contrôle biaisé** vers la v1 : les candidatures ont été choisies parmi ce que la v1 montrait.

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Procédure | `docs/procedures/c5-calibrage/` : `sample.py`, `page.py`, `measure.py`, `echantillon.json`, `annotations.json`, `README.md` | Même forme que `c3-mesure/` et `c4-mesure/`. |
| Conversion des annonces | `offer()` de `c3-mesure/measure.py` et `collected()` de `c4-mesure/measure.py`, date de référence fixe (25/09/2026) | Mesures comparables d'une étape à l'autre. |
| AUC | Mann-Whitney, ex-æquo au rang moyen | Sans dépendance ; même calcul que le rang de Spearman de C4. |
| Page d'annotation | Générée par `page.py` (python3 de l'hôte, bibliothèque standard) dans un dossier hors dépôt ; progression dans `localStorage` ; export JSON téléchargé | Les textes des annonces restent hors dépôt (A1) ; rien ne s'ajoute à Rocky avant C7. |
