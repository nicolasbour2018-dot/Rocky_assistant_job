# C3 — Mesure de l'analyse d'annonce

Décision : `docs/decisions/C3-analyse.md` (Q3). Critère de sortie de C3 : « Extraction mesurée sur un échantillon de
l'archive ». Les textes des annonces restent dans l'archive (`backups/`, hors dépôt) ; seuls leurs identifiants et
les annotations sont versionnés.

## 1. Échantillon

```sh
python3 docs/procedures/c3-mesure/sample.py --archive backups/rocky-v1-20260924
```

40 annonces à description complète, tirage fixe (graine `20260925`) : Adzuna 10, LinkedIn 8, Wellfound 7, Welcome to
the Jungle 6, Indeed 4, Hellowork 3, Apec 2 → `echantillon.json`.

## 2. Annotations (`annotations.json`)

Écrites par Claude le 25/09/2026 **avant toute règle**, puis 10 annonces contrôlées par Nicolas (`checked_by_nicolas`).
Une annotation corrigée après la mesure l'est seulement pour une erreur de lecture, notée ci-dessous.

Profil de référence : les 52 compétences de Nicolas (fichier relu de B5, hors dépôt). Champs et conventions :

| Champ | Convention |
|---|---|
| `contracts` | Contrat proposé, lu dans le titre, le texte ou les faits de la source. « CDI à la clé » après un stage n'est pas le contrat. Le « contract » d'Adzuna (CDD **ou** mission) ne suffit pas seul ; un TJM ou « Freelance » dans le titre donne `freelance`. |
| `remote` | `on_site`, `hybrid` (jours de télétravail, « hybride », `partial`/`punctual` de WTTJ), `full_remote` (« fully remote », `fulltime` de WTTJ). « Télétravail » sans modalité et « pas de full remote » laissent le mode inconnu (`null`). |
| `salary` | Salaire de l'employeur (bornes, devise, période). Période écrite si elle l'est, sinon celle que le montant rend évidente. Une estimation de la plateforme n'en est pas un. |
| `conditions` | `nationality` (nationalité, droit au travail, visa), `clearance` (habilitation), `driving_licence` (permis). Une mention dans une clause de non-discrimination ou un modèle à remplir n'en est pas une. |
| `experience_years` | Minimum d'années demandé au candidat. Plusieurs exigences cumulées : la plus haute ; des alternatives (« 8 ans OU 5 ans avec un master ») : la plus basse. « 0 à 3 ans » donne 0. |
| `languages` | Langues demandées (codes ISO). « Aucune langue attendue » : aucune. Jamais éliminatoire (Q6). |
| `skills` | Compétences du profil **nommées** par l'annonce (nom, alias, variantes « X (Y) »), sans casse, accents ni ponctuation, mots entiers, pluriel du dernier mot toléré. Une notion voisine non nommée ne compte pas (« dashboards » ≠ « Dashboarding »). |
| `eliminatory_skills` | Compétence dont la phrase, ou l'intitulé de section qui la précède, porte « obligatoire », « indispensable », « requis », « exigé », « impératif » (et « required », « essential », « must-have », « mandatory »). Une négation (« n'est pas requis ») n'en fait pas une exigence. |
| `preferred_skills` | Même lecture avec « un plus », « apprécié », « souhaité », « atout » (et « nice to have », « preferred », « bonus »). « Vous appréciez le travail en mode agile » décrit le candidat : pas une préférence. |

Cas notés à l'annotation : « LLM » de l'annonce 32 est un diplôme de droit (Master of Laws) — compté, car la règle
lit des noms, pas un sens ; aucune annonce de l'échantillon n'écrit de date limite dans son texte (la date limite est
couverte par les tests).

### Corrections après la première mesure (25/09/2026)

Chaque écart a été relu avec sa phrase-preuve. Corrigées dans `annotations.json` (champ `corrected`) : les seules
**erreurs de lecture**, que la convention ci-dessus tranchait déjà.
- Libellés **anglais** des compétences du profil, ignorés à l'annotation (« Data management », « Rigor »,
  « Modeling », « Data analysis », « Automation », « artificial intelligence »…) : 18 annonces.
- Deux oublis en français : « la rigueur d'un cabinet » (768), « gestion des données » (70).
- Importances imposées par la convention : « essential » de Qair couvre aussi « rigor » et « Autonomy » (451) ;
  « Compétences indispensables … Data Analysis » (753) ; « Qualités requises … intelligence artificielle » (657) ;
  bloc « Bonus » de Tremendous (794) ; « constitue un atout important » (622).

Corrigés dans **les règles**, l'annotation restant inchangée : tiret de liste « , - Capacité » non vu comme une
coupure (Agile faussement éliminatoire, 940) ; « is a plus » hors de la fenêtre (450) ; « 2-3 ans minimum » lu 3 ;
« visa sponsorship » trop loin de sa négation (649) ; « leader français … professionnelle » pris pour une langue
(445) ; « stage, alternance ou premier emploi » pris pour un contrat (575). Hors échantillon : « Permis B apprécié »
compté comme condition, « Pas de télétravail possible » lu hybride.

Écarts restants, assumés : le modèle à remplir de Scalian (« ouvert aux freelances oui/non », 1030) ; Plotly dans un
bloc d'atouts sans ponctuation (1035) ; alternatives « 8 ans OU 5 ans avec un master » (1072, la règle garde le plus
exigeant) ; « 10 à 15 ans de CDI » sans le mot expérience (70) ; contrat des offres Hellowork (1225, 1226, 940) que
l'import C2 ne récupère pas (le JSON-LD donne `FULL_TIME`, le CDI n'est que dans le titre de la page).

## 3. Mesurer

```sh
uv run python docs/procedures/c3-mesure/measure.py --archive backups/rocky-v1-20260924 \
  --profile ~/Developer/rocky-profil-nicolas.json
```

Précision et rappel par champ, et la liste des écarts annonce par annonce.
