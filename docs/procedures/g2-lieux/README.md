# G2 — Référentiel des lieux et mesure

Décision : `docs/decisions/G2-lieux-date-limite.md`. Critère de sortie de G2 : « "Paris 01 - 75", "Courbevoie - 92"
et "Chartres - 28" répondent aux lieux des pistes de Nicolas ; écart de classement chiffré et documenté. »

## Fichiers

| Fichier | Rôle |
|---|---|
| `build.py` | Réduit les trois fichiers du COG INSEE en `rocky/profil/data/lieux-cog-2026.csv` (type, code, nom, commune, département, région) |
| `count.py` | Score en mémoire toutes les offres d'un compte de la base de développement (lecture seule) : composante lieu, offres de 40 à 49 hors zone ; `--out` garde le meilleur score de chaque offre |
| `compare.py` | Compare deux sorties de `count.py` : corrélation de rang, passages du seuil, plus fortes hausses |

## 1. Référentiel (une fois par millésime, réseau)

Fichiers téléchargés le 06/10/2026, avec l'accord de Nicolas, depuis
`https://www.insee.fr/fr/statistiques/fichier/8740222/` (licence ouverte), dans un dossier **hors du dépôt** :

| Fichier | SHA-256 |
|---|---|
| `v_commune_2026.csv` | `7be1153de3a63df48fa0ca77f8490c8a0c5c9c4eb12f5cec1ca7f70b0237b1d3` |
| `v_departement_2026.csv` | `513900ca23edc682ef9b912d7bfc317129eac3a7d71ff19bc22b40ea4838e6eb` |
| `v_region_2026.csv` | `d903566d9c0d263389d279baea6761917b7460749a07bec8ba37dd8f2ff7d98a` |

```sh
python3 -I docs/procedures/g2-lieux/build.py --cog <dossier> --out rocky/profil/data/lieux-cog-2026.csv
```

35 039 lieux : 18 régions, 101 départements, 34 875 communes, 45 arrondissements municipaux (Paris, Lyon,
Marseille). Les communes déléguées et associées ne sont pas gardées. Un nouveau millésime change le nom du fichier, celui
lu par `rocky/profil/places.py` et la `RULES_VERSION` du score.

## 2. Mesure sur la base de développement

```sh
docker compose run --rm --build -T -v "$PWD/docs/procedures:/procedures:ro" -v "<dossier hors dépôt>:/out" \
  app python /procedures/g2-lieux/count.py --profile-id 1 --out /out/lieux.json
python3 -I docs/procedures/g2-lieux/compare.py <avant>/lieux.json <après>/lieux.json
```

Le jour de référence est fixé (06/10/2026) pour que deux passages ne diffèrent que par leurs règles. Les sorties JSON
contiennent les lieux des offres : elles restent hors du dépôt.

## Résultats du 06/10/2026 (profil 1, pistes « Ile de France », « Eure et Loir »)

1 663 offres, 3 326 scores (2 pistes). Avant : `score-2026-09-29.3` ; après : `score-2026-10-06.1`.

| Composante lieu (scores) | Avant | Après |
|---|---|---|
| 1 (dans la zone) | 318 | 2 778 |
| 0,3 (hors zone) | 2 290 | 220 |
| 0,5 (hors zone en hybride, ou étranger en télétravail complet) | 500 | 124 |
| 0 (étranger) | 186 | 148 |
| absente ou neutre | 32 | 56 |

| Offres (meilleur score) | Avant | Après |
|---|---|---|
| au-dessus du seuil (50) | 211 | 324 |
| entre 40 et 49 avec un lieu hors zone | 225 | 24 |

Comparaison : corrélation de rang 0,96 ; 1 123 scores changés, moyenne 30,5 → 35,1 ; **113 offres passent au-dessus
du seuil, aucune ne passe dessous** ; 14 des 15 premières restent en tête. Les plus fortes hausses (435 : 30 → 93 ;
434 : 30 → 59) sont des annonces Wellfound « Paris » sans pays : le plafond « hors de France présumé » se lève parce
qu'un lieu de la piste couvre la ville (règle C5, Q24, inchangée) ; les autres gagnent de 7 à 10 points.

Hors zone restants les plus fréquents : Le Mans, Orléans, Nantes, Lyon, « France » (sans ville), Londres, New York ;
tous justes pour des pistes « Ile de France » et « Eure et Loir ».
