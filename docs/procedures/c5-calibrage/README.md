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

## Versions de règles

_À compléter : une ligne par `RULES_VERSION`, avec le motif compté qui justifie chaque changement et sa mesure._

## Corrections d'annotation

_Aucune._
