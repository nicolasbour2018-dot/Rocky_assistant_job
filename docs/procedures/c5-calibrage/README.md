# C5 — Calibrage du score

Décision : `docs/decisions/C5-calibrage.md`. Critère de sortie de C5 : « Les annonces jugées pertinentes remontent ;
écart chiffré et documenté. » Les textes des annonces restent dans l'archive (`backups/`, hors dépôt) et dans la page
d'annotation, générée hors dépôt ; seuls les identifiants, les scores et les étiquettes sont versionnés ici.

> **Nicolas : n'ouvre ni `echantillon.json` ni `reference.json` avant d'avoir fini d'annoter.** Ils contiennent les
> tranches de score et les scores de référence (annotation à l'aveugle, Q5).

## Fichiers

| Fichier | Rôle |
|---|---|
| `common.py` | Chargement de l'archive (annonces, scores v1, candidatures de contrôle), annonces mesurées, score avec le profil de la base de développement (lecture seule) |
| `sample.py` | Scores de référence (`reference.json`) et tirage stratifié (`echantillon.json`) |
| `page.py`, `page.html` | Page d'annotation locale, générée hors dépôt |
| `measure.py` | Mesure : contrôle, ordre, seuil, motifs, désaccords, stabilité |
| `annotations.json` | Les étiquettes de Nicolas (export de la page) |

## Profil figé (28/09/2026)

Profil 1 (Nicolas), après ses derniers ajustements (Q17) ; il ne change plus jusqu'à la fin de C5.

- 56 compétences, 13 clés, 40 prouvées (liées à une expérience ou un projet) ; clés non prouvées : SQL, Rigueur.
- Piste « Data analyst » : intitulés Data analyst, Analyst engineer, Business analyst ; mots exclus manager, lead,
  senior ; lieux Paris, Ile de france, Eure et Loire.
- Piste « Data scientist / IA » : intitulés Data scientist, IA engineer ; aucun mot exclu ; lieux Paris, Ile de
  France, Eure et Loire.
- Préférences : CDI, CDD, Freelance, VIE ; sur site, hybride, télétravail complet ; 35 000 € minimum ; TJM 350 €.
- Langues : français (natif), anglais C1, espagnol B2 ; 3 emplois.

## 1. Référence et tirage

```sh
docker compose run --rm --build -T \
  -v "$PWD/backups:/archive:ro" -v "$PWD/docs/procedures:/procedures:ro" \
  -v "$PWD/docs/procedures/c5-calibrage:/procedures/c5-calibrage" \
  app python /procedures/c5-calibrage/sample.py --archive /archive/rocky-v1-20260924 --profile-id 1
```

Les 404 annonces de la mesure C4 (notées en v1, description complète, sources lues par la nouvelle collecte), avec la
date de référence du 25/09/2026. Règles `score-2026-09-25.1`, profil figé. Contrôle : 36 candidatures parmi les 404.

| Tranche de référence | Hors contrôle | Tirées |
|---|---|---|
| 80–100 | 99 | 15 |
| 60–79 | 110 | 15 |
| 40–59 | 103 | 12 |
| 0–39 | 56 | 8 |

50 annonces (graine `20260928`), affichées dans un ordre tiré au sort, suivies de 5 doublons non signalés : 55.

## 2. Annotation

```sh
python3 docs/procedures/c5-calibrage/page.py --archive backups/rocky-v1-20260924 --out ../rocky-c5-annotation
open ../rocky-c5-annotation/index.html
```

La page refuse un dossier de sortie dans le dépôt. Elle montre l'intitulé, l'entreprise, le lieu, le contrat, le
télétravail, le salaire écrit, la source et le texte ; ni score, ni statut v1, ni date. La progression est gardée
dans le navigateur (`localStorage`) ; « Télécharger annotations.json » exporte les réponses, « Reprendre un fichier »
les recharge. Le fichier exporté est copié dans ce dossier.

Conventions (décision C5) :

- **Question** : « Postulerais-je ? », avec le profil et les préférences d'aujourd'hui, tout compris ; l'ancienneté de
  l'annonce est ignorée.
- **Niveau** : Oui / À examiner / Non (touches 1, 2, 3 ; flèches pour naviguer).
- **Motifs** : toujours au moins un, chacun signé + (attire) ou − (rebute) ; un Oui a au moins un +, un Non au moins un
  − ; « Autre » demande un commentaire. Codes : `metier`, `competences`, `seniorite`, `secteur`, `entreprise`,
  `contrat`, `lieu`, `teletravail`, `salaire`, `langue`, `condition`, `piste` (mauvaise piste), `floue`, `autre`.
- **Doublons** : la première réponse compte ; la seconde mesure la stabilité.
- **Correction** : seulement pour une erreur de lecture, notée ci-dessous avec sa raison.

## 3. Mesure

```sh
docker compose run --rm --build -T \
  -v "$PWD/backups:/archive:ro" -v "$PWD/docs/procedures:/procedures:ro" \
  app python /procedures/c5-calibrage/measure.py --archive /archive/rocky-v1-20260924 --profile-id 1
```

Trois classements sur les mêmes étiquettes : v1, référence (`reference.json`), règles actuelles. AUC pertinente
(Oui + À examiner) contre Non, calculée par Mann-Whitney avec les ex-æquo à ½ ; seuil comparé au score entier affiché ;
« part devant » = part des 404 annonces classées strictement devant.

### Référence (28/09/2026, avant annotation)

| Contrôle (36 candidatures) | Rang médian (part devant) | Premier quart | Au-dessus du seuil |
|---|---|---|---|
| v1 | 21 % | 20 / 36 | 34 / 36 |
| Référence `score-2026-09-25.1`, profil figé | 38 % | 13 / 36 | 28 / 36 |
| **Cible (Q14)** | **≤ 25 %** | **≥ 20 / 36** | **≥ 32 / 36** |

Le profil figé améliore le contrôle par rapport au 28/09 matin (42 %, 12, 28), sans combler l'écart avec la v1.

### Annotations (29/09/2026) : mesure de référence

Nicolas a annoté les 55 annonces à l'aveugle (sans ouvrir `echantillon.json` ni `reference.json`) : 50 annonces,
**Oui 12, À examiner 9, Non 29**. Stabilité : 4 doublons sur 5 identiques (1058 : Non puis À examiner).

| Ordre (50 annonces) | AUC pertinente / Non | Pertinentes dans les 10 premières | Non dans les 10 premières |
|---|---|---|---|
| v1 | 0,52 | 3 | 7 |
| Référence `score-2026-09-25.1` | 0,75 | 7 | 3 |
| **Cible (Q12)** | **≥ 0,80** | — | **0** |

| Seuil 50 | Oui au-dessus | Pertinentes au-dessus | Non au-dessus |
|---|---|---|---|
| v1 | 12 / 12 | 18 / 21 | 25 / 29 |
| Référence | 12 / 12 | 20 / 21 | 20 / 29 |
| **Cible (Q13)** | **12 / 12** | **≥ 19 / 21** | **≤ 9 / 29** |

Motifs − des 29 Non : séniorité 18, compétences 18, métier 11, condition bloquante 10, lieu 8, secteur 3, contrat 1,
salaire 1, piste 1.

Sur les annotations, la référence C4 classe déjà nettement mieux que la v1 (0,75 contre 0,52), alors que sur le
contrôle la v1 reste devant ; mais le contrôle a été choisi parmi ce que la v1 montrait. Écarts à la cible : 20 Non
au-dessus du seuil (≤ 9 visé) et 3 Non dans les 10 premières. Les 20 Non au-dessus de 50 se rangent en trois familles
(causes vérifiées sur le détail des composantes) :

- **Mot exclu contourné par l'autre piste** (794, 404, 1058, 1225) : « senior » plafonne la piste « Data analyst » à
  30, mais la piste « Data scientist / IA », sans mot exclu, l'emporte (51 à 72).
- **Étranger lu comme la France** (1190 Toronto, 879 San Francisco, 880 Miami, 32 Alaska, 794 New York, 1071
  Bangalore, 1074) : Wellfound ne donne pas le pays ; le pays absent est lu comme la France et le télétravail complet
  rend le lieu neutre (66 à 90).
- **Séniorité et métier portés par l'intitulé** (608 « Adjoint chef de bureau », 846 « Chef de section », 990 « Expert
  haut niveau », 1082 « Lead développeur », 1074 « Staff ») : l'expérience pèse 3 et vaut 1 dès que les années liées
  aux compétences de l'annonce suffisent ; un intitulé à 0 (1082) laisse encore 67.

## Versions de règles

| Version | Changement | Motif compté qui le justifie |
|---|---|---|
| `score-2026-09-29.1` + `analyse-2026-09-29.1` | Plafond « Hors de France » (connu, ou présumé pour une annonce Wellfound sans pays hors des lieux des pistes), levé si un lieu de la piste couvre le pays ou la ville (Q24) ; une phrase de langue n'est plus une exigence hors profil, « Anglais indispensable » devient un besoin de langue | condition − × 10 et lieu − × 8 sur les Non ; 21 exigences hors profil sur 118 étaient des phrases de langue |
| Profil (exception Q23) | Mots exclus des deux pistes : senior, lead, staff, principal, head, chef, expert, directeur, manager (un par ligne ; « sénior » se confond avec « senior ») | séniorité − × 18 sur les Non |

| `score-2026-10-06.1` (G2) | Lieux lus dans le référentiel COG INSEE : une région ou un département couvre ses communes (décision G2) | « Paris » seul : 590 scores hors zone sur la base de développement avec les pistes du 06/10 |
| `score-2026-09-29.2` | Un savoir-être (catégorie « Savoir-être » du profil) compte ×0,5 dans les points de preuve (Q28) | compétences − × 18 sur les Non ; leurs compétences trouvées viennent à 55 % des catégories métier et savoir-être (39 % pour les pertinentes) ; 751 remplissait sa composante avec Autonomie, Pédagogie, Rigueur |

Contrôle ajusté (Nicolas, 29/09) : 860 (New York) et 917 (Londres) en sortent, l'étranger étant désormais bloquant
pour lui ; 34 candidatures, cibles ramenées dans la même proportion (≥ 19 dans le premier quart, ≥ 31 au-dessus du
seuil). La mesure de la v1 et de la référence est recalculée sur ces 34.

Puis (Q26, jugé sur l'intitulé seul avant toute nouvelle mesure) : 272 « Quantitative consultant », 432 « BPCE », 655
« Responsable IA & Data » (niveau du poste) et 752 « Business Analysis support Cash Management » (management
éliminatoire) sortent ; 55 « Consultant Data Analytics », 853 « Analyste OSINT » et 942 « Prompt Engineer » restent,
leurs métiers entrant dans les pistes. **30 candidatures ; cibles : rang médian ≤ 25 %, ≥ 17 dans le premier quart,
≥ 27 au-dessus du seuil.**

### Mesure de la version 2 (29/09/2026, avant les intitulés ajoutés aux pistes)

| | AUC | Non dans les 10 premières | Seuil : Oui · pertinentes · Non au-dessus | Contrôle (30) : rang médian · premier quart · au-dessus |
|---|---|---|---|---|
| v1 | 0,52 | 7 | 12 · 18 · 25 | 26 % · 15 · 28 |
| Référence | 0,75 | 3 | 12 · 20 · 20 | 34 % · 13 · 26 |
| `score-2026-09-29.2` | **0,93** | 1 (751, à 86) | 12 · 20 · 6 | 26 % · 14 · 25 |

### Mesure de la version 1 (29/09/2026)

| Ordre (50 annonces) | AUC pertinente / Non | Non dans les 10 premières |
|---|---|---|
| v1 | 0,52 | 7 |
| Référence | 0,75 | 3 |
| **Version 1** | **0,92** ✅ | **1** ❌ (751, « Business Analyst Data Financement Structuré ») |

| Seuil 50 | Oui au-dessus | Pertinentes au-dessus | Non au-dessus |
|---|---|---|---|
| Référence | 12 / 12 | 20 / 21 | 20 / 29 |
| **Version 1** | **12 / 12** ✅ | **20 / 21** ✅ | **6 / 29** ✅ |

| Contrôle (34) | Rang médian (part devant) | Premier quart | Au-dessus du seuil |
|---|---|---|---|
| v1 | 23 % | 18 | 32 |
| Référence | 38 % | 13 | 26 |
| **Version 1** | **28 %** ❌ | **15** ❌ | **25** ❌ |
| Cible | ≤ 25 % | ≥ 19 | ≥ 31 |

Les 9 candidatures sous le seuil : 7 sont des métiers hors des intitulés des pistes (intitulé à 0 ou 0,25 :
« Consultant Data Analytics », « Quantitative consultant », « BPCE », « Responsable IA & Data », « Business Analysis
support Cash Management », « Analyste OSINT », « Prompt Engineer ») ; 70 est plafonnée par une habilitation exigée ;
750 par le mot exclu « chef ». Aucune n'est descendue à cause d'une règle de la version 1 : elles étaient déjà sous le
seuil avec la référence, sauf 750 (choix de Nicolas, Q23).

### Mesure finale (29/09/2026) : `score-2026-09-29.2`, profil complété

Profil après les ajustements de Nicolas (Q23, Q26) : mots exclus des deux pistes senior, lead, staff, principal, head,
chef, expert, directeur, manager, stage ; intitulés ajoutés « Analyste OSINT » et « Consultant data » (Data analyst),
« Prompt engineer » (Data scientist / IA).

| | Cible | v1 | Référence | Finale | |
|---|---|---|---|---|---|
| AUC pertinente / Non | ≥ 0,80 | 0,52 | 0,75 | **0,94** | ✅ |
| Non dans les 10 premières | 0 | 7 | 3 | **1** (751) | ❌ accepté (Q30) |
| Oui au-dessus du seuil 50 | 12 / 12 | 12 | 12 | **12** | ✅ |
| Pertinentes au-dessus | ≥ 19 / 21 | 18 | 20 | **20** | ✅ |
| Non au-dessus | ≤ 9 / 29 | 25 | 20 | **5** | ✅ |
| Contrôle (30) : rang médian | ≤ 25 % | 26 % | 34 % | **27 %** | ❌ accepté (Q29) |
| Contrôle : premier quart | ≥ 17 | 15 | 13 | **14** | ❌ accepté (Q29) |
| Contrôle : au-dessus du seuil | ≥ 27 | 28 | 26 | **28** | ✅ |

Stabilité : 4 doublons sur 5. Seuil gardé à 50 (Q31). Les deux candidatures du contrôle sous le seuil sont plafonnées
par des choix de Nicolas : 70 (habilitation exigée), 750 (mot exclu « chef »).

### Relecture de `score-2026-09-29.2` (29/09/2026, `relecture.json`)

32 annonces non annotées : 20 premières → juste 3, **trop haute 17** (« il manque trop d'informations pour avoir
100 % », expérience, salaire, contrat) ; 10 juste sous le seuil → juste 6, trop haute 2 (1193 et 445 : « data seul
ne doit pas faire monter le score »), trop basse 2 (393 : savoir-être, déjà traité par Q28 ; 438 : compétences
implicites, limite de l'analyse) ; contrôle sous le seuil → juste 2.

| Version | Changement | Motif qui le justifie |
|---|---|---|
| `score-2026-09-29.3` | Une composante facultative dont l'annonce ne dit rien compte **0,5** au lieu d'être retirée (Q32) ; « rien à comparer » (aucune préférence, aucune langue demandée, piste sans lieu, télétravail complet) reste neutre et retiré ; un intitulé **partiel** vaut 0, un intitulé dont tous les mots sont présents mais séparés garde 0,5 (Q33) | Relecture : 17 des 20 premières jugées trop hautes faute d'informations ; 1193 et 445 trop hautes sur « data » seul |

Simulation avant de coder (composante absente à 0,3 / 0,5 / 0,7) : 0,3 fait tomber le contrôle à 26 sur 30 au-dessus
du seuil ; 0,5 et 0,7 gardent toutes les mesures, 0,5 marque le plus l'écart entre annonces complètes et incomplètes.

### Mesure de la version 3 (29/09/2026)

| | Cible | v1 | Référence | `score-2026-09-29.3` | |
|---|---|---|---|---|---|
| AUC pertinente / Non | ≥ 0,80 | 0,52 | 0,75 | **0,94** | ✅ |
| Non dans les 10 premières | 0 | 7 | 3 | **1** (751, à 83) | ❌ accepté (Q30) |
| Oui · pertinentes · Non au-dessus de 50 | 12 · ≥ 19 · ≤ 9 | 12 · 18 · 25 | 12 · 20 · 20 | **12 · 20 · 5** | ✅ |
| Contrôle (30) : rang médian · premier quart · au-dessus | ≤ 25 % · ≥ 17 · ≥ 27 | 26 % · 15 · 28 | 34 % · 13 · 26 | **26 % · 14 · 28** | ❌ accepté (Q29), ✅ |

Mesure C4 relancée avec cette version : 1193 à **45** (< 50, critère de C4 tenu) ; 1 annonce à 100 parmi les 404 (23
avant) ; 186 au-dessus de 50 ; 180 plafonnées (mots exclus du profil et étranger) ; confiance haute 61, moyenne 125,
faible 218 ; corrélation de rang v1 / C4 : 0,00.

### Mesure de G2 (06/10/2026) : `score-2026-10-06.1`, lieux lus dans le référentiel

Pistes du jour : lieux « Ile de France », « Eure et Loir » (« Paris » retiré et « Loire » corrigé par Nicolas après
le 29/09 ; profil sinon inchangé). Le point de départ est remesuré avec ces pistes, d'où l'écart avec la ligne du
29/09 : sans « Paris », Paris était hors zone. Décision `docs/decisions/G2-lieux-date-limite.md`.

| | `score-2026-09-29.3`, pistes du 06/10 | `score-2026-10-06.1` |
|---|---|---|
| AUC pertinente / Non | 0,93 | **0,94** |
| Non dans les 10 premières | 1 | 1 |
| Oui · pertinentes · Non au-dessus de 50 | 12 · 20 · 5 | **12 · 20 · 5** |
| Contrôle (30) : rang médian · premier quart · au-dessus | 28 % · 14 · 27 | **27 % · 13 · 28** |

## 4. Relecture (Q21)

```sh
docker compose run --rm --build -T \
  -v "$PWD/backups:/archive:ro" -v "$PWD/docs/procedures:/procedures:ro" -v "$PWD/../rocky-c5-annotation:/out" \
  app python /procedures/c5-calibrage/review.py --archive /archive/rocky-v1-20260924 --profile-id 1 --out /out
open ../rocky-c5-annotation/relecture.html
```

Hors des annonces annotées : les 20 premières des 404, les 10 juste sous le seuil et les candidatures du contrôle sous
le seuil, cette fois **avec** le score et son détail. Pour chacune : place juste, trop haute ou trop basse, et un
commentaire ; « Télécharger la relecture » exporte les verdicts (`relecture-<version des règles>.json` ; la première,
faite sur `score-2026-09-29.2`, est `relecture.json`), copiés dans ce dossier.

## Corrections d'annotation

- **751** (« Business Analyst Data Financement Structuré », 29/09) : motif « métier − » retiré, erreur de Nicolas ;
  l'étiquette Non reste. Ce qui la rend non pertinente : des compétences demandées absentes du profil (« compétences
  − ») et le secteur. L'analyse n'y trouve que des compétences génériques (Autonomie, Pédagogie, Rigueur, Gestion de
  projet, Gestion des données, Modélisation ; Spark et SQL en « un plus ») et aucune exigence hors profil.
