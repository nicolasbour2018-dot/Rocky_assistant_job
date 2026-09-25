# C3 — Analyse d'annonce

Date : 25/09/2026 · Étape : C3 (plan v2) · Préparation : questions à Nicolas puis mode plan

Critère de sortie : « Extraction mesurée sur un échantillon de l'archive. »

## Constats de départ (ancien Rocky, archive A1, étapes précédentes)

| Constat | Source |
|---|---|
| `job_analysis` ne détecte que des compétences, avec un dictionnaire global (`SKILL_ALIASES`) ; B5 a rendu compétences et alias propres au compte | `dashboard/job_analysis.py`, plan §8 (B5 → C3) |
| L'ATS V3 classe une exigence « obligatoire », « souhaitée » ou « détectée » selon les marqueurs de sa phrase | `dashboard/rocky/ats_v3.py` (`_importance`) |
| Le reste de l'analyse (contrat, expérience, domaine…) était demandé à Groq, sans preuve | `dashboard/rocky/llm.py` (`enrich_job`) |
| 1 278 offres, 454 à description complète ; marqueurs `requis`/`un plus` 58, `indispensable` 45, `obligatoire` 34, `nationalité` 12, `tjm` 12 ; 36 `salary_min` < 2 000 (TJM, voire taux horaires) ; 96 descriptions Markdown (70 Wellfound) ; date limite renseignée 284 fois | `job_offers.csv` (A1) |
| Faits bruts laissés à interpréter : TJM Adzuna dans `salary_min`, codes Apec sans libellé, `FULL_TIME`, `TELECOMMUTE`, `YEAR`, `deadline` | plan §8 (C1, C2) |

## Décisions métier (avec Nicolas, 25/09)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Méthode | **Règles déterministes pour tous les faits** (explicables, testables, mesurables). Le LLM (Gemini) sert **au résumé seulement**, jamais à un fait ni au score. |
| Q2 | Éliminatoires | Les **exigences marquées** (« obligatoire », « indispensable », « requis », « exigé », « impératif ») et les conditions que rien ne compense : **nationalité, habilitation, permis**. Tout le reste est préférence ou simple mention. |
| Q3 | Mesure | Claude annote une quarantaine d'annonces de l'archive **avant d'écrire les règles** ; Nicolas en contrôle 10. Précision et rappel par champ. |
| Q4 | « X (Y) » | Dans une annonce, une compétence « Traitement du langage naturel (NLP) » répond à son nom entier, à « Traitement du langage naturel » et à « NLP ». La comparaison des noms entiers du profil (B5, Q9) ne change pas. |
| Q5 | Période du salaire | Une période écrite prime (« TJM », « /jour », « k€/an », `unitText`). Sinon elle est **déduite du montant** et marquée comme telle : ≤ 150 horaire, ≤ 2 000 journalier, ≤ 15 000 mensuel, au-delà annuel. |
| Q6 | Expérience et langues | Extraites avec leur preuve comme **préférences** de l'annonce, jamais éliminatoires. |
| Q7 | Résumé | **Trois puces en français** (missions, contexte, profil), quelle que soit la langue de l'annonce, **à la demande** (à l'ouverture de l'offre). Sans clé ou en panne : « résumé indisponible » avec la raison. |
| Q8 | Codes Apec | Une **capture réelle du référentiel public** d'Apec décode contrat et télétravail ; un code inconnu reste vide ; au premier refus, arrêt et on en parle. |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Forme | Sous-module `rocky/offres/analysis/` : `model.py`, `rules.py` (pur), `usecases.py` | Même forme que `sources/` et `imports/`. |
| Vocabulaire | `Contract`, `RemoteMode`, `LanguageLevel` de `rocky/profil/model.py` réutilisés | L'annonce et les préférences du profil parlent la même langue (C4). |
| Compétences | Termes du compte (`skill_terms`, `normalize_term`), lus par le cas d'usage de `profil`, jamais par son SQL ; recherche par mots entiers | B5 (Q2) ; AGENTS §4. |
| Fonction pure | `analyze(offer, skills, …)` n'écrit rien ; une version des règles (`RULES_VERSION`) accompagne chaque analyse | AGENTS §4 ; D14. |
| LLM | Adaptateur `rocky/system/llm.py` (API REST Gemini par `httpx2`, aucune dépendance ajoutée), délai borné, aucun réessai, sortie validée, erreurs typées avec raison | Le plan place le LLM dans `system` ; Groq → Gemini (plan §8, B5). |
| Conservation | Rien n'est persisté en C3 ; le résumé et l'analyse s'enregistrent avec l'offre (C6/C7) | Même règle que C1 et C2. |
