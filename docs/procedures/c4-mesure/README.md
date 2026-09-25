# C4 — Mesure du score

Décision : `docs/decisions/C4-scoring.md` (Q13). Critère de sortie de C4 : « Chaque score s'explique composante par
composante ; la "Data Protection Analyst" (79,6 % en v1) ne remonte plus. » Les textes des annonces restent dans
l'archive (`backups/`, hors dépôt) ; seuls leurs identifiants, intitulés et scores sont versionnés ici.

## Lancer

Dans le conteneur de l'application (le profil est lu, **en lecture seule**, dans la base de développement) :

```sh
docker compose run --rm --build -T \
  -v "$PWD/backups:/archive:ro" -v "$PWD/docs/procedures:/procedures:ro" \
  app python /procedures/c4-mesure/measure.py --archive /archive/rocky-v1-20260924 --profile-id 1
```

Profil 1 : le profil de Nicolas réimporté en B5 (52 compétences, dont 13 clés et 11 prouvées), ses deux pistes actives
(« Data analyst », « Data scientist / IA », lieux Paris, Île-de-France, « Eure et Loire », aucun mot exclu) et ses
préférences (CDI, CDD, VIE ; aucun mode de télétravail ; 35 000 € minimum ; pas de TJM). Chaque annonce de l'archive
devient l'offre que donnerait la nouvelle collecte (conversion de `c3-mesure/measure.py`, plus le lieu et le pays).

## Résultats du 25/09/2026 (règles `score-2026-09-25.1`)

### Échantillon C3 (40 annonces, dont la 1193)

| Id | Source | Intitulé | v1 | C4 | Piste | Confiance | Plafond |
|---|---|---|---|---|---|---|---|
| 1035 | Adzuna | Marketing Data Scientist Consultant | 62.5 | 100 | Data scientist / IA | medium |  |
| 451 | Indeed | Data Analyst – Power Markets M/F | 60.2 | 100 | Data analyst | high |  |
| 575 | LinkedIn | Data scientist-e / Data ingénieur-e | 59.9 | 82 | Data scientist / IA | medium |  |
| 1042 | LinkedIn | DATA SCIENTIST H/F | 72.6 | 80 | Data scientist / IA | medium |  |
| 856 | Adzuna | Data Scientist - Solutions Front (H/F) | 63.9 | 77 | Data scientist / IA | medium |  |
| 879 | Wellfound | Data Scientist | 74.6 | 76 | Data scientist / IA | medium |  |
| 1245 | Indeed | Data analyst - Lutte Contre La Fraude H/F | 45.2 | 76 | Data analyst | low |  |
| 768 | LinkedIn | Data Analyst Senior H/F | 55.8 | 74 | Data analyst | medium |  |
| 753 | Adzuna | Data Analyst Technico-Fonctionnel (F/H) - Freela | 53.3 | 73 | Data analyst | medium |  |
| 7 | LinkedIn | Data Analyst / CDI / H/F | 54.6 | 72 | Data analyst | low |  |
| 450 | Indeed | Confirmed Data Analyst - Demand | 48.0 | 71 | Data analyst | low |  |
| 1155 | LinkedIn | 🦊 Data Scientist (CDI) | 63.5 | 70 | Data scientist / IA | low |  |
| 794 | Wellfound | Senior Data Analyst, GTM | 42.9 | 69 | Data analyst | low |  |
| 944 | LinkedIn | Data Scientist | 71.6 | 67 | Data scientist / IA | low |  |
| 1064 | Welcome to the Jungle | Data Scientist | 44.6 | 67 | Data scientist / IA | low |  |
| 173 | Adzuna | Data Analyst | 65.5 | 66 | Data analyst | low |  |
| 1225 | hellowork.com | Data Scientist Sénior - Expert Rag H/F | 81.1 | 66 | Data scientist / IA | medium |  |
| 940 | hellowork.com | Data Scientist - Domaine Lcb - Ft H/F | 88.0 | 64 | Data scientist / IA | low |  |
| 775 | Welcome to the Jungle | Data Analyst Marketing | 41.1 | 60 | Data analyst | low |  |
| 461 | Wellfound | Data Analyst | 53.3 | 58 | Data analyst | low |  |
| 49 | LinkedIn | Data Analyst F/H | 62.9 | 56 | Data analyst | low |  |
| 176 | Adzuna | Data Engineer Databricks F/H | 55.5 | 55 | Data analyst | low |  |
| 792 | Wellfound | Senior Data Analyst | 30.6 | 55 | Data analyst | low |  |
| 434 | Adzuna | Business Analyst Data - MDM Informatica - Servic | 79.2 | 53 | Data analyst | low |  |
| 65 | Welcome to the Jungle | Chef de projet Data (H/F) | 49.5 | 53 | Data analyst | medium |  |
| 1158 | Indeed | Data Scientist / Risk Analyst – Risque Crédit (H | 81.8 | 49 | Data scientist / IA | low |  |
| 1072 | Wellfound | Principal Data Scientist | 57.4 | 48 | Data scientist / IA | low |  |
| 1080 | Adzuna | Stage Data Scientist - Paris (H/F/X) | 61.4 | 43 | Data scientist / IA | low |  |
| 445 | LinkedIn | CHARGE(E) DE PROJETS Data & Pilotage de la perfo | 66.1 | 42 | Data analyst | low |  |
| 32 | Wellfound | Data Analyst – AI Legal Training | 73.8 | 41 | Data analyst | low |  |
| 861 | Welcome to the Jungle | Data Scientist | 86.2 | 36 | Data scientist / IA | low |  |
| 622 | Apec | Développeur Python / DevOps GCP F/H | 58.5 | 35 | Data analyst | medium |  |
| 70 | Apec | Data analyst F/H | 30.6 | 30 | Data analyst | low | Bloquant : Habilitation |
| 1193 | Adzuna | Data Protection Analyst - Freelance | 79.6 | 29 | Data analyst | low |  |
| 1226 | hellowork.com | Ingénieur IA - Llmops H/F | 73.6 | 24 | Data scientist / IA | low |  |
| 453 | Welcome to the Jungle | Senior Business Intelligence Analyst | 39.3 | 20 | Data analyst | low |  |
| 222 | Adzuna | Médecin Généraliste F/H - Corbeil-Essonnes 91100 | — | 18 | Data analyst | low |  |
| 657 | Welcome to the Jungle | Project Manager DATA / IA  F/H | 71.9 | 17 | Data analyst | low |  |
| 1030 | Adzuna | Sourcing Transformation Digitale IDF SBR | 78.1 | 12 | Data analyst | low |  |
| 649 | Wellfound | Head of Talent Acquisition | 72.0 | 7 | Data analyst | low | Bloquant : Nationalité ou droit au travail |

### Ensemble des annonces notées en v1

404 annonces à description complète notées en v1 (sources lues par la nouvelle collecte) :

- corrélation de rang (Spearman) v1 / C4 : 0.08
- v1 ≥ 50 : 332 ; C4 ≥ 50 : 264
- moyenne v1 : 63.7 ; moyenne C4 : 58.7
- 20 premières communes aux deux classements : 0
- confiance C4 : haute 10, moyenne 131, faible 263
- plafonnées : 13

20 premières en C4 :

| Id | Source | Intitulé | v1 | C4 | Piste | Confiance | Plafond |
|---|---|---|---|---|---|---|---|
| 2 | Adzuna | Data Scientist Junior F/H | 72.0 | 100 | Data scientist / IA | medium |  |
| 3 | Adzuna | Data Scientist Junior F/H | 72.0 | 100 | Data scientist / IA | medium |  |
| 4 | Adzuna | Data Scientist Junior F/H | 69.6 | 100 | Data scientist / IA | medium |  |
| 20 | Welcome to the Jungle | Data Scientist Junior F/H | 69.6 | 100 | Data scientist / IA | medium |  |
| 451 | Indeed | Data Analyst – Power Markets M/F | 60.2 | 100 | Data analyst | high |  |
| 467 | LinkedIn | Data Scientist – Power Markets M/F – Paris | 77.5 | 100 | Data scientist / IA | high |  |
| 608 | Adzuna | ADJOINT CHEF DE BUREAU - DATA ANALYST | 82.1 | 100 | Data analyst | medium |  |
| 764 | Adzuna | Data analyst/engineer | 58.9 | 100 | Data analyst | medium |  |
| 847 | LinkedIn | Data Analyst – Power Markets M/F – Paris | 72.6 | 100 | Data analyst | high |  |
| 858 | LinkedIn | Data scientist H/F | 76.4 | 100 | Data scientist / IA | medium |  |
| 922 | Wellfound | Senior Data Scientist | 65.7 | 100 | Data scientist / IA | medium |  |
| 924 | Wellfound | Data Scientist | 64.5 | 100 | Data scientist / IA | medium |  |
| 1051 | Adzuna | Junior Data Scientist - Downstream Demand Foreca | 69.2 | 100 | Data scientist / IA | medium |  |
| 1054 | Adzuna | Junior Data Scientist - Downstream Demand Foreca | 69.2 | 100 | Data scientist / IA | medium |  |
| 1060 | LinkedIn | Data Scientist IA – H/F | 67.5 | 100 | Data scientist / IA | medium |  |
| 1035 | Adzuna | Marketing Data Scientist Consultant | 62.5 | 100 | Data scientist / IA | medium |  |
| 1115 | Adzuna | Data Scientist - Retail & Distribution F/H | 71.8 | 100 | Data scientist / IA | medium |  |
| 1129 | Indeed | Data Scientist expérimenté | 70.2 | 100 | Data scientist / IA | medium |  |
| 54 | LinkedIn | Data Scientist Suptech (H/F) | 73.0 | 100 | Data scientist / IA | medium |  |
| 449 | Indeed | Data Scientist Junior F/H | 64.0 | 98 | Data scientist / IA | medium |  |

## Lecture

- **Critère de sortie** : la « Data Protection Analyst » (1193) passe de 79,6 à **29**, confiance faible (« preuves
  insuffisantes »), avec le profil réel. Avec un profil de test qui la favorise (sa seule compétence clé et prouvée,
  Paris dans la zone, freelance recherché), elle reste à 47 < 50 (`tests/offres/scoring/test_data_protection_analyst.py`) :
  la marge est étroite, C5 la resserre.
- Les hors-sujets de la v1 tombent : « Head of Talent Acquisition » 72,0 → 7 (et bloquant : nationalité), « Sourcing
  Transformation Digitale » 78,1 → 12, « Project Manager DATA / IA » 71,9 → 17, « Médecin généraliste » → 18.
- Corrélation de rang v1 / C4 de 0,08, aucune des 20 premières en commun : les deux classements n'ont presque rien en
  commun. Seules les annotations de Nicolas (C5) diront lequel est juste.

## Écarts à traiter en C5 (calibrage)

- **Confiance faible pour 65 % des annonces** (263 sur 404), presque toujours pour « preuves insuffisantes » : la médiane
  des preuves est de 1,4 point (seuil de 2) ; la composante compétences n'est pleine que pour 29 annonces sur 404.
  Cause : la plupart des compétences trouvées sont « mentionnées » (0,3) et non prouvées (×0,7) — 11 compétences
  prouvées sur 52.
- **Le haut du classement sature** : 19 annonces à 100 parmi les 20 premières (intitulé exact + preuves pleines +
  composantes facultatives absentes, donc renormalisées).
- **Fausses exigences hors profil** (règle C3) : « Maîtrise de l'anglais obligatoire » compte comme une exigence hors
  profil alors que l'anglais (C1) est au profil ; « This posting is representative of multiple roles… » aussi.
- Préférences du profil : sans mode de télétravail, la composante télétravail est toujours absente ; sans « Freelance »,
  une mission freelance vaut 0 au contrat ; sans mot exclu, « Stage Data Scientist » n'est pas plafonnée (43).
